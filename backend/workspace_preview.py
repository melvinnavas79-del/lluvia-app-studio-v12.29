"""
workspace_preview.py — Preview en vivo estilo Lovable/Bolt.

Arquitectura:
  - File watcher asyncio (500ms) por preview activo
  - SSE event bus: broadcast reload a todos los subscriptores de un app_slug
  - Script de live-reload inyectado en HTML proxiado (no necesita JS en el cliente)
  - Token temporal (1h) para proxy público sin JWT (shareable URL + iframe sin cookie)
  - Ring buffer de logs del proceso (últimas 200 líneas)
  - uvicorn --reload ya maneja cambios en server.py; el watcher solo notifica al browser

Endpoints:
  POST /api/me/apps/{slug}/preview            Arrancar preview → {url, token, share_url}
  POST /api/me/apps/{slug}/preview/stop       Detener
  GET  /api/me/apps/{slug}/preview/status     Estado + uptime
  GET  /api/me/apps/{slug}/preview/events     SSE stream (reload, log, status events)
  GET  /api/me/apps/{slug}/preview/logs       Últimas N líneas del proceso
  GET  /api/me/apps/p/{token}/{path}          Proxy público (token auth, no JWT)
  POST /api/me/apps/{slug}/screenshot         Screenshot Playwright
  GET  /api/me/apps/_/screenshots/{id}.png    Servir screenshot
"""

import asyncio
import json
import logging
import os
import re
import time
import uuid
from collections import deque
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from auth import get_current_user

logger = logging.getLogger("workspace_preview")
router = APIRouter(prefix="/me/apps", tags=["workspace_preview"])

_db_ref: dict = {"db": None}

PREVIEW_PORT_BASE = int(os.environ.get("PREVIEW_PORT_BASE", "9100"))
PREVIEW_PORT_MAX  = int(os.environ.get("PREVIEW_PORT_MAX",  "9300"))
PREVIEW_TTL_SEC   = int(os.environ.get("PREVIEW_TTL_SEC",   "3600"))  # 1h
MAX_PER_USER      = int(os.environ.get("MAX_PREVIEWS_PER_USER", "3"))
SCREENSHOTS_DIR   = Path(os.environ.get("SCREENSHOTS_DIR", "/tmp/lluvia_screenshots"))
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

# ── State ──────────────────────────────────────────────────────────────────────
# active_previews: key=(user_id, slug) → PreviewEntry dict
_active_previews: dict[tuple, dict] = {}

# token → {user_id, slug, expires_at}
_preview_tokens: dict[str, dict] = {}

# SSE queues: (user_id, slug) → list[asyncio.Queue]
_sse_queues: dict[tuple, list] = {}


def set_db(db) -> None:
    _db_ref["db"] = db


# ── Helpers ────────────────────────────────────────────────────────────────────

def _user_apps_dir(user_id: str) -> Path:
    base = os.environ.get("LLUVIA_HOME", "/app")
    return Path(base) / "user_apps" / user_id


def _safe_slug(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]", "", s or "")[:80]


def _next_free_port() -> int:
    used = {e["port"] for e in _active_previews.values()}
    for p in range(PREVIEW_PORT_BASE, PREVIEW_PORT_MAX + 1):
        if p not in used:
            return p
    raise HTTPException(503, "No hay puertos de preview disponibles (rango 9100-9300 lleno)")


def _make_preview_token(user_id: str, slug: str) -> str:
    token = uuid.uuid4().hex
    _preview_tokens[token] = {
        "user_id": user_id,
        "slug": slug,
        "expires_at": time.time() + PREVIEW_TTL_SEC,
    }
    return token


def _resolve_token(token: str) -> Optional[dict]:
    t = _preview_tokens.get(token)
    if not t:
        return None
    if time.time() > t["expires_at"]:
        _preview_tokens.pop(token, None)
        return None
    return t


def _broadcast(key: tuple, event: dict) -> None:
    """Envía evento a todos los clientes SSE subscriptos a esta app."""
    for q in list(_sse_queues.get(key, [])):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass


async def _kill_preview(key: tuple) -> None:
    entry = _active_previews.pop(key, None)
    if not entry:
        return
    # Cancel watcher
    watcher = entry.get("watcher_task")
    if watcher and not watcher.done():
        watcher.cancel()
    # Kill process
    proc = entry.get("process")
    if proc and proc.returncode is None:
        try:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    # Broadcast stopped event
    _broadcast(key, {"type": "status", "status": "stopped"})
    # Remove SSE queues
    _sse_queues.pop(key, None)


async def _cleanup_expired() -> None:
    """Mata previews expirados. Llamar en cada start_preview."""
    now = time.time()
    for key, entry in list(_active_previews.items()):
        if now - entry.get("last_seen", 0) > PREVIEW_TTL_SEC:
            await _kill_preview(key)
    # Cleanup expired tokens
    for tok, t in list(_preview_tokens.items()):
        if now > t["expires_at"]:
            _preview_tokens.pop(tok, None)


# ── File Watcher ───────────────────────────────────────────────────────────────

async def _watch_app_dir(key: tuple, app_dir: Path, poll_ms: int = 600) -> None:
    """
    Asyncio task: monitorea cambios en app_dir y hace broadcast de eventos reload.
    Persiste mientras el preview esté activo.
    """
    prev_mtimes: dict[str, float] = {}

    def _scan() -> dict[str, float]:
        result = {}
        try:
            for p in app_dir.rglob("*"):
                if p.is_file() and ".git" not in str(p) and "__pycache__" not in str(p):
                    try:
                        result[str(p)] = p.stat().st_mtime
                    except OSError:
                        pass
        except Exception:
            pass
        return result

    prev_mtimes = _scan()

    while key in _active_previews:
        await asyncio.sleep(poll_ms / 1000)
        current = _scan()

        changed_files = []
        for fpath, mtime in current.items():
            if prev_mtimes.get(fpath) != mtime:
                changed_files.append(Path(fpath).name)
        for fpath in prev_mtimes:
            if fpath not in current:
                changed_files.append(Path(fpath).name + " (deleted)")

        if changed_files:
            logger.debug(f"[preview] {key[1]} changed: {changed_files[:5]}")
            prev_mtimes = current
            _active_previews[key]["last_changed"] = time.time()
            _broadcast(key, {
                "type": "reload",
                "ts": time.time(),
                "files": changed_files[:10],
            })


# ── Process Log Capture ────────────────────────────────────────────────────────

async def _stream_process_logs(key: tuple, proc) -> None:
    """Lee stdout del proceso y lo guarda en el ring buffer + broadcast a SSE."""
    try:
        while key in _active_previews and proc.returncode is None:
            try:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            if not line:
                break
            text = line.decode("utf-8", "ignore").rstrip()
            if not text:
                continue
            entry = _active_previews.get(key)
            if entry:
                entry["logs"].append(text)
            _broadcast(key, {"type": "log", "line": text, "ts": time.time()})
    except Exception:
        pass

    # Process exited
    if key in _active_previews:
        _broadcast(key, {"type": "status", "status": "crashed",
                         "code": proc.returncode})


# ── Start Preview ──────────────────────────────────────────────────────────────

@router.post("/{app_slug}/preview")
async def start_preview(app_slug: str, user: dict = Depends(get_current_user)):
    """
    Arranca el preview de la app. Devuelve:
      - proxy_url: URL autenticada vía JWT (/api/me/apps/{slug}/preview/proxy/)
      - share_url: URL temporal sin JWT (para iframe + demos)
      - events_url: SSE endpoint para live reload events
    """
    await _cleanup_expired()
    slug = _safe_slug(app_slug)
    app_dir = _user_apps_dir(user["id"]) / slug

    if not app_dir.exists():
        raise HTTPException(404, f"App '{slug}' no existe en tu workspace")

    backend_dir = app_dir / "backend"
    has_server = (backend_dir / "server.py").exists()
    has_index  = (app_dir / "frontend" / "index.html").exists() or \
                 (backend_dir / "index.html").exists() or \
                 (app_dir / "index.html").exists()

    if not has_server and not has_index:
        raise HTTPException(400, f"App '{slug}' no tiene backend/server.py ni index.html")

    key = (user["id"], slug)

    if key in _active_previews:
        # Ya corriendo → refrescar TTL y regenerar token
        _active_previews[key]["last_seen"] = time.time()
        token = _make_preview_token(user["id"], slug)
        return _preview_response(slug, _active_previews[key], token, reused=True)

    user_previews = [k for k in _active_previews if k[0] == user["id"]]
    if len(user_previews) >= MAX_PER_USER:
        raise HTTPException(429, f"Máximo {MAX_PER_USER} previews activos. Detén uno antes.")

    port = _next_free_port()

    if has_server:
        # Python backend: spawn uvicorn con --reload
        venv = backend_dir / "venv"
        pip_cmd = ""
        if not venv.exists() and (backend_dir / "requirements.txt").exists():
            pip_cmd = (
                f"python3 -m venv {venv} && "
                f"{venv}/bin/pip install --quiet -r {backend_dir}/requirements.txt && "
            )
        python = f"{venv}/bin/python3" if venv.exists() else "python3"
        uvicorn = f"{venv}/bin/uvicorn" if venv.exists() else "uvicorn"
        cmd = (
            f"{pip_cmd}cd {backend_dir} && "
            f"PORT={port} {uvicorn} server:app "
            f"--host 127.0.0.1 --port {port} --log-level info --reload"
        )
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    else:
        # Static only: servir con Python http.server
        static_dir = (app_dir / "frontend") if (app_dir / "frontend").exists() else app_dir
        cmd = f"cd {static_dir} && python3 -m http.server {port} --bind 127.0.0.1"
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

    logs_buffer: deque = deque(maxlen=200)
    now = time.time()

    _active_previews[key] = {
        "port": port,
        "process": proc,
        "started_at": now,
        "last_seen": now,
        "last_changed": now,
        "logs": logs_buffer,
        "app_dir": str(app_dir),
        "has_server": has_server,
        "status": "starting",
        "watcher_task": None,
        "log_task": None,
    }
    _sse_queues[key] = []

    # Broadcast startup
    _broadcast(key, {"type": "status", "status": "starting"})

    # Wait for startup
    await asyncio.sleep(2.5 if has_server else 0.5)
    if proc.returncode is not None:
        raw = b""
        try:
            raw = await asyncio.wait_for(proc.stdout.read(3000), timeout=2)
        except Exception:
            pass
        _active_previews.pop(key, None)
        _sse_queues.pop(key, None)
        raise HTTPException(500, f"Preview no pudo arrancar: {raw.decode('utf-8','ignore')[:800]}")

    _active_previews[key]["status"] = "ready"
    _broadcast(key, {"type": "status", "status": "ready", "port": port})

    # Start background tasks
    watcher = asyncio.create_task(_watch_app_dir(key, app_dir))
    log_task = asyncio.create_task(_stream_process_logs(key, proc))
    _active_previews[key]["watcher_task"] = watcher
    _active_previews[key]["log_task"] = log_task

    token = _make_preview_token(user["id"], slug)
    return _preview_response(slug, _active_previews[key], token, reused=False)


def _preview_response(slug: str, entry: dict, token: str, reused: bool) -> dict:
    base = os.environ.get("PUBLIC_BASE_URL", "")
    return {
        "ok": True,
        "reused": reused,
        "port": entry["port"],
        "status": entry.get("status", "ready"),
        "proxy_url": f"/api/me/apps/{slug}/preview/proxy/",
        "share_url": f"{base}/api/me/apps/p/{token}/",
        "events_url": f"/api/me/apps/{slug}/preview/events",
        "started_at": datetime.fromtimestamp(entry["started_at"], tz=timezone.utc).isoformat(),
        "ttl_sec": PREVIEW_TTL_SEC,
    }


# ── Stop ───────────────────────────────────────────────────────────────────────

@router.post("/{app_slug}/preview/stop")
async def stop_preview(app_slug: str, user: dict = Depends(get_current_user)):
    slug = _safe_slug(app_slug)
    key = (user["id"], slug)
    if key not in _active_previews:
        return {"ok": True, "wasnt_running": True}
    await _kill_preview(key)
    return {"ok": True}


# ── Status ─────────────────────────────────────────────────────────────────────

@router.get("/{app_slug}/preview/status")
async def preview_status(app_slug: str, user: dict = Depends(get_current_user)):
    slug = _safe_slug(app_slug)
    key = (user["id"], slug)
    entry = _active_previews.get(key)
    if not entry:
        return {"running": False, "status": "stopped"}
    entry["last_seen"] = time.time()
    proc = entry.get("process")
    alive = proc and proc.returncode is None
    if not alive and entry.get("status") != "crashed":
        entry["status"] = "crashed"
    return {
        "running": alive,
        "status": entry.get("status", "unknown"),
        "port": entry["port"],
        "uptime_sec": int(time.time() - entry["started_at"]),
        "last_changed": entry.get("last_changed"),
    }


# ── Logs ───────────────────────────────────────────────────────────────────────

@router.get("/{app_slug}/preview/logs")
async def preview_logs(app_slug: str, n: int = 100, user: dict = Depends(get_current_user)):
    slug = _safe_slug(app_slug)
    key = (user["id"], slug)
    entry = _active_previews.get(key)
    if not entry:
        raise HTTPException(404, "Preview no está corriendo")
    logs = list(entry["logs"])[-min(n, 200):]
    return {"ok": True, "lines": logs, "total": len(entry["logs"])}


# ── SSE Events ─────────────────────────────────────────────────────────────────

@router.get("/{app_slug}/preview/events")
async def preview_events(app_slug: str, user: dict = Depends(get_current_user)):
    """
    Server-Sent Events stream. El cliente JS en el iframe (o en PreviewIframe.js)
    se suscribe y recibe eventos: reload, log, status.
    """
    slug = _safe_slug(app_slug)
    key = (user["id"], slug)

    entry = _active_previews.get(key)
    if not entry:
        raise HTTPException(404, "Preview no está corriendo")

    queue: asyncio.Queue = asyncio.Queue(maxsize=50)
    _sse_queues.setdefault(key, []).append(queue)

    # Enviar estado inicial
    await queue.put({"type": "status", "status": entry.get("status", "ready"),
                     "port": entry["port"]})

    async def event_generator():
        try:
            while key in _active_previews:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=25.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            queues = _sse_queues.get(key, [])
            if queue in queues:
                queues.remove(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ── Live-reload script injected into proxied HTML ──────────────────────────────

_LIVERELOAD_SCRIPT = """
<script>
(function(){
  var SLUG = "{{SLUG}}";
  var TOKEN = "{{TOKEN}}";
  var baseUrl = (TOKEN ? "/api/me/apps/p/"+TOKEN : "/api/me/apps/"+SLUG+"/preview");
  var evtSrc;
  function connect() {
    var url = TOKEN
      ? "/api/me/apps/"+SLUG+"/preview/events?preview_token="+TOKEN
      : "/api/me/apps/"+SLUG+"/preview/events";
    evtSrc = new EventSource(url);
    evtSrc.onmessage = function(e) {
      try {
        var d = JSON.parse(e.data);
        if (d.type === "reload") {
          setTimeout(function(){ window.location.reload(); }, 120);
        }
        if (d.type === "status" && (d.status === "crashed" || d.status === "stopped")) {
          document.body.insertAdjacentHTML("beforeend",
            "<div style=\\"position:fixed;top:0;left:0;right:0;padding:8px 16px;"
            +"background:#DC2626;color:#fff;font-size:13px;font-family:monospace;"
            +"z-index:99999;text-align:center;\\">"
            +"⚠ Preview crashed — recargando en 3s...</div>");
          setTimeout(function(){ window.location.reload(); }, 3000);
        }
      } catch(_) {}
    };
    evtSrc.onerror = function() {
      evtSrc.close();
      setTimeout(connect, 3000);
    };
  }
  connect();
  window.addEventListener("beforeunload", function(){ if(evtSrc) evtSrc.close(); });
})();
</script>
"""


def _inject_livereload(html: bytes, slug: str, token: str = "") -> bytes:
    """Inyecta el script de live-reload antes de </body>."""
    script = (_LIVERELOAD_SCRIPT
              .replace("{{SLUG}}", slug)
              .replace("{{TOKEN}}", token))
    encoded = script.encode("utf-8")
    if b"</body>" in html:
        return html.replace(b"</body>", encoded + b"</body>", 1)
    return html + encoded


# ── Proxy (JWT auth) ───────────────────────────────────────────────────────────

@router.api_route("/{app_slug}/preview/proxy/{path:path}",
                  methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def preview_proxy(app_slug: str, path: str, request: Request,
                        user: dict = Depends(get_current_user)):
    slug = _safe_slug(app_slug)
    key = (user["id"], slug)
    entry = _active_previews.get(key)
    if not entry:
        raise HTTPException(404, "Preview no está corriendo. POST /preview primero.")
    entry["last_seen"] = time.time()

    return await _do_proxy(slug, entry["port"], path, request, token="")


# ── Proxy (token auth, shareable URL) ─────────────────────────────────────────

@router.api_route("/p/{token}/{path:path}",
                  methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def preview_proxy_token(token: str, path: str, request: Request):
    """Proxy público. Accesible sin JWT — solo con el token temporal de 1h."""
    t = _resolve_token(token)
    if not t:
        raise HTTPException(401, "Token de preview inválido o expirado")
    key = (t["user_id"], t["slug"])
    entry = _active_previews.get(key)
    if not entry:
        raise HTTPException(404, "Preview no está corriendo")
    entry["last_seen"] = time.time()
    return await _do_proxy(t["slug"], entry["port"], path, request, token=token)


async def _do_proxy(slug: str, port: int, path: str, request: Request,
                    token: str = "") -> Response:
    import httpx
    upstream = f"http://127.0.0.1:{port}/{path}"
    if request.url.query:
        upstream += f"?{request.url.query}"
    body = await request.body()
    headers = {k: v for k, v in request.headers.items()
               if k.lower() not in {"host", "authorization", "cookie"}}

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as cli:
        try:
            r = await cli.request(request.method, upstream, content=body, headers=headers)
        except httpx.ConnectError:
            raise HTTPException(502, "Preview no responde — puede estar reiniciando")
        except Exception as e:
            raise HTTPException(502, f"Proxy error: {e}")

    resp_headers = {
        k: v for k, v in r.headers.items()
        if k.lower() not in {"content-encoding", "transfer-encoding", "content-length"}
    }
    # Inyectar live-reload en HTML
    content_type = r.headers.get("content-type", "")
    content = r.content
    if "text/html" in content_type and request.method == "GET":
        content = _inject_livereload(content, slug, token)

    return Response(
        content=content,
        status_code=r.status_code,
        headers=resp_headers,
        media_type=content_type or None,
    )


# ── SSE via token (para el script inyectado en el iframe) ─────────────────────

@router.get("/{app_slug}/preview/events")
async def preview_events_token(
    app_slug: str,
    preview_token: str = "",
    request: Request = None,
):
    """
    SSE endpoint alternativo que acepta ?preview_token= para llamadas desde
    el script inyectado en el iframe (que no tiene JWT en headers).
    """
    slug = _safe_slug(app_slug)
    if preview_token:
        t = _resolve_token(preview_token)
        if not t or t["slug"] != slug:
            raise HTTPException(401, "Token inválido")
        key = (t["user_id"], slug)
    else:
        raise HTTPException(401, "Se requiere token o JWT")

    return await _sse_for_key(key)


async def _sse_for_key(key: tuple) -> StreamingResponse:
    entry = _active_previews.get(key)
    if not entry:
        raise HTTPException(404, "Preview no está corriendo")
    queue: asyncio.Queue = asyncio.Queue(maxsize=50)
    _sse_queues.setdefault(key, []).append(queue)
    await queue.put({"type": "status", "status": entry.get("status", "ready")})

    async def gen():
        try:
            while key in _active_previews:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=20.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": hb\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            qs = _sse_queues.get(key, [])
            if queue in qs:
                qs.remove(queue)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


# ── Screenshot ─────────────────────────────────────────────────────────────────

class ScreenshotIn(BaseModel):
    url: str = Field(..., min_length=8, max_length=600)
    viewport_width: int  = Field(1280, ge=320, le=2560)
    viewport_height: int = Field(800,  ge=320, le=2000)
    full_page: bool = False
    wait_ms: int    = Field(1500, ge=0, le=10000)


@router.post("/{app_slug}/screenshot")
async def take_screenshot(app_slug: str, data: ScreenshotIn,
                           user: dict = Depends(get_current_user)):
    slug = _safe_slug(app_slug)
    shot_id = uuid.uuid4().hex[:12]
    shot_path = SCREENSHOTS_DIR / f"{user['id']}_{slug}_{shot_id}.png"
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise HTTPException(500, "Playwright no instalado en el backend")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"])
            ctx = await browser.new_context(
                viewport={"width": data.viewport_width, "height": data.viewport_height})
            page = await ctx.new_page()
            await page.goto(data.url, wait_until="domcontentloaded", timeout=20000)
            if data.wait_ms:
                await page.wait_for_timeout(data.wait_ms)
            await page.screenshot(path=str(shot_path), full_page=data.full_page, type="png")
            await browser.close()
    except Exception as e:
        raise HTTPException(500, f"Screenshot error: {e}")
    await _db_ref["db"].screenshots.insert_one({
        "id": shot_id, "user_id": user["id"], "app_slug": slug,
        "url": data.url, "filename": shot_path.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return {"ok": True, "screenshot_id": shot_id,
            "image_url": f"/api/me/apps/_/screenshots/{shot_id}.png",
            "size_bytes": shot_path.stat().st_size}


@router.get("/_/screenshots/{shot_id}.png")
async def serve_screenshot(shot_id: str, user: dict = Depends(get_current_user)):
    safe = re.sub(r"[^a-zA-Z0-9]", "", shot_id)[:32]
    doc = await _db_ref["db"].screenshots.find_one(
        {"id": safe, "user_id": user["id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(404)
    path = SCREENSHOTS_DIR / doc["filename"]
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(str(path), media_type="image/png")
