"""
workspace_preview.py - Preview en vivo + screenshots con Playwright.

Endpoints:
  POST /api/me/apps/{app_slug}/preview     Arranca uvicorn temporal y devuelve URL
  POST /api/me/apps/{app_slug}/preview/stop Detiene preview activo
  GET  /api/me/apps/{app_slug}/preview/status Estado del preview
  POST /api/me/apps/{app_slug}/screenshot   Screenshot con Playwright headless

El preview se sirve via subprocess (uvicorn server:app --port PORT) en el rango
9100-9300 (separado de las apps deployadas a VPS que van en 8042-8999).
Auto-shutdown despues de 10 minutos sin uso.
"""

import os
import re
import sys
import uuid
import asyncio
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from auth import get_current_user

logger = logging.getLogger("workspace_preview")
router = APIRouter(prefix="/me/apps", tags=["workspace_preview"])

_db_ref: dict = {"db": None}

PREVIEW_PORT_BASE = int(os.environ.get("PREVIEW_PORT_BASE", "9100"))
PREVIEW_PORT_MAX = int(os.environ.get("PREVIEW_PORT_MAX", "9300"))
PREVIEW_TTL_SEC = 600   # 10 minutos
MAX_PREVIEWS_PER_USER = int(os.environ.get("MAX_PREVIEWS_PER_USER", "2"))
SCREENSHOTS_DIR = Path(os.environ.get("SCREENSHOTS_DIR", "/tmp/lluvia_screenshots"))
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

# In-memory registry de previews activos
# {(user_id, app_slug): {"port": int, "process": asyncio.subprocess, "started_at": dt, "last_seen": dt}}
_active_previews: dict = {}


def set_db(db) -> None:
    _db_ref["db"] = db


def _user_apps_dir(user_id: str) -> Path:
    base = os.environ.get("LLUVIA_HOME", "/app")
    return Path(base) / "user_apps" / user_id


def _safe_slug(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]", "", s or "")[:80]


def _next_free_port() -> int:
    used = {entry["port"] for entry in _active_previews.values()}
    for p in range(PREVIEW_PORT_BASE, PREVIEW_PORT_MAX + 1):
        if p not in used:
            return p
    raise HTTPException(503, "No hay puertos de preview disponibles")


async def _cleanup_idle_previews():
    """Mata previews que no se usaron en PREVIEW_TTL_SEC."""
    now = datetime.now(timezone.utc)
    to_kill = []
    for key, entry in list(_active_previews.items()):
        if (now - entry["last_seen"]).total_seconds() > PREVIEW_TTL_SEC:
            to_kill.append(key)
    for key in to_kill:
        entry = _active_previews.pop(key, None)
        if entry and entry.get("process"):
            try:
                entry["process"].terminate()
                await asyncio.wait_for(entry["process"].wait(), timeout=3)
            except Exception:
                try:
                    entry["process"].kill()
                except Exception:
                    pass


@router.post("/{app_slug}/preview")
async def start_preview(app_slug: str, user: dict = Depends(get_current_user)):
    """Arranca uvicorn de la app del workspace en un puerto libre. Devuelve URL."""
    await _cleanup_idle_previews()
    slug = _safe_slug(app_slug)
    base = _user_apps_dir(user["id"]) / slug
    if not base.exists():
        raise HTTPException(404, f"App '{slug}' no existe en tu workspace")
    backend_dir = base / "backend"
    if not (backend_dir / "server.py").exists():
        raise HTTPException(400, f"App '{slug}' no tiene backend/server.py")

    key = (user["id"], slug)
    if key in _active_previews:
        # Ya hay uno corriendo: refrescar timestamp y devolver
        _active_previews[key]["last_seen"] = datetime.now(timezone.utc)
        port = _active_previews[key]["port"]
        return {"ok": True, "port": port, "url": f"http://localhost:{port}",
                "started_at": _active_previews[key]["started_at"].isoformat(),
                "reused": True}

    user_previews = [k for k in _active_previews if k[0] == user["id"]]
    if len(user_previews) >= MAX_PREVIEWS_PER_USER:
        raise HTTPException(429, f"Máximo {MAX_PREVIEWS_PER_USER} previews activos por usuario")

    port = _next_free_port()
    # Instalar deps si no existe venv
    venv = backend_dir / "venv"
    setup_cmd = ""
    if not venv.exists():
        setup_cmd = (
            f"python3 -m venv {venv} && {venv}/bin/pip install --quiet "
            f"-r {backend_dir}/requirements.txt && "
        )
    cmd = (
        f"{setup_cmd}cd {backend_dir} && PORT={port} {venv}/bin/uvicorn server:app "
        f"--host 127.0.0.1 --port {port} --log-level warning --reload"
    )
    proc = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    _active_previews[key] = {
        "port": port,
        "process": proc,
        "started_at": datetime.now(timezone.utc),
        "last_seen": datetime.now(timezone.utc),
    }

    # Esperar un poco a que arranque y verificar
    await asyncio.sleep(2.5)
    if proc.returncode is not None:
        # Crash en startup
        out = await proc.stdout.read(2000)
        _active_previews.pop(key, None)
        raise HTTPException(500, f"Preview crash al arrancar: {out.decode('utf-8', 'ignore')[:1000]}")

    # Proxy interno: el front no puede acceder a localhost:9100 directamente, lo
    # proxyamos via /api/me/apps/{slug}/preview/proxy
    proxy_url = f"/api/me/apps/{slug}/preview/proxy/"
    return {"ok": True, "port": port, "url": proxy_url,
            "started_at": _active_previews[key]["started_at"].isoformat(),
            "ttl_sec": PREVIEW_TTL_SEC, "reused": False}


@router.post("/{app_slug}/preview/stop")
async def stop_preview(app_slug: str, user: dict = Depends(get_current_user)):
    slug = _safe_slug(app_slug)
    key = (user["id"], slug)
    entry = _active_previews.pop(key, None)
    if not entry:
        return {"ok": True, "wasnt_running": True}
    try:
        entry["process"].terminate()
        await asyncio.wait_for(entry["process"].wait(), timeout=3)
    except Exception:
        try:
            entry["process"].kill()
        except Exception:
            pass
    return {"ok": True}


@router.get("/{app_slug}/preview/status")
async def preview_status(app_slug: str, user: dict = Depends(get_current_user)):
    slug = _safe_slug(app_slug)
    key = (user["id"], slug)
    entry = _active_previews.get(key)
    if not entry:
        return {"running": False}
    entry["last_seen"] = datetime.now(timezone.utc)
    return {
        "running": True,
        "port": entry["port"],
        "started_at": entry["started_at"].isoformat(),
        "uptime_sec": int((datetime.now(timezone.utc) - entry["started_at"]).total_seconds()),
    }


# Proxy a la app preview
@router.api_route("/{app_slug}/preview/proxy/{path:path}",
                  methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def preview_proxy(app_slug: str, path: str, request: Request,
                        user: dict = Depends(get_current_user)):
    slug = _safe_slug(app_slug)
    key = (user["id"], slug)
    entry = _active_previews.get(key)
    if not entry:
        raise HTTPException(404, "Preview no esta corriendo. POST /preview primero.")
    entry["last_seen"] = datetime.now(timezone.utc)
    import httpx
    upstream = f"http://127.0.0.1:{entry['port']}/{path}"
    if request.url.query:
        upstream += f"?{request.url.query}"
    body = await request.body()
    headers = {k: v for k, v in request.headers.items()
               if k.lower() not in {"host", "authorization", "cookie"}}
    async with httpx.AsyncClient(timeout=30.0) as cli:
        try:
            r = await cli.request(request.method, upstream, content=body, headers=headers)
        except Exception as e:
            raise HTTPException(502, f"Preview no responde: {e}")
    resp_headers = {k: v for k, v in r.headers.items()
                    if k.lower() not in {"content-encoding", "transfer-encoding", "content-length"}}
    return JSONResponse(content=None, status_code=r.status_code) if False else \
        _passthrough_response(r, resp_headers)


def _passthrough_response(r, headers):
    from fastapi.responses import Response
    return Response(content=r.content, status_code=r.status_code,
                    headers=headers, media_type=r.headers.get("content-type"))


# ============================================================
# Screenshot con Playwright
# ============================================================
class ScreenshotIn(BaseModel):
    url: str = Field(..., min_length=8, max_length=600)
    viewport_width: int = Field(1280, ge=320, le=2560)
    viewport_height: int = Field(800, ge=320, le=2000)
    full_page: bool = False
    wait_ms: int = Field(1500, ge=0, le=10000)


@router.post("/{app_slug}/screenshot")
async def take_screenshot(app_slug: str, data: ScreenshotIn,
                           user: dict = Depends(get_current_user)):
    """Toma screenshot de cualquier URL via Playwright headless chromium."""
    slug = _safe_slug(app_slug)
    shot_id = uuid.uuid4().hex[:12]
    shot_path = SCREENSHOTS_DIR / f"{user['id']}_{slug}_{shot_id}.png"

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise HTTPException(500, "Playwright no instalado. En el VPS: pip install playwright && playwright install chromium")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            ctx = await browser.new_context(viewport={"width": data.viewport_width, "height": data.viewport_height})
            page = await ctx.new_page()
            await page.goto(data.url, wait_until="domcontentloaded", timeout=20000)
            if data.wait_ms:
                await page.wait_for_timeout(data.wait_ms)
            await page.screenshot(path=str(shot_path), full_page=data.full_page, type="png")
            await browser.close()
    except Exception as e:
        raise HTTPException(500, f"Screenshot error: {e}")

    # Guardar metadata
    await _db_ref["db"].screenshots.insert_one({
        "id": shot_id,
        "user_id": user["id"],
        "app_slug": slug,
        "url": data.url,
        "filename": shot_path.name,
        "viewport": {"w": data.viewport_width, "h": data.viewport_height},
        "full_page": data.full_page,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    return {
        "ok": True,
        "screenshot_id": shot_id,
        "image_url": f"/api/me/apps/_/screenshots/{shot_id}.png",
        "size_bytes": shot_path.stat().st_size,
    }


@router.get("/_/screenshots/{shot_id}.png")
async def serve_screenshot(shot_id: str, user: dict = Depends(get_current_user)):
    safe = re.sub(r"[^a-zA-Z0-9]", "", shot_id)[:32]
    doc = await _db_ref["db"].screenshots.find_one({"id": safe, "user_id": user["id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(404)
    path = SCREENSHOTS_DIR / doc["filename"]
    if not path.exists():
        raise HTTPException(404, "Imagen no encontrada en disco")
    return FileResponse(str(path), media_type="image/png")
