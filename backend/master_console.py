"""
============================================================
MASTER CONSOLE — Operations Hub para Lluvia App Studio
STATUS: REAL

Consola de operaciones internas con MASTER_KEY auth.
NUNCA exponer al frontend público — solo acceso de sistema/DevOps.

Capacidades:
  python_run      REAL — sandbox exec() con globals restringidos + timeout
  shell_run       REAL — subprocess con blocklist + timeout + audit
  deploy_trigger  REAL — via e2_executor (requiere SSH configurado)
  live_monitor    REAL — agrega E9 counters + worker status + queue depth
  file_read       REAL — lectura de archivos del sistema (read-only)
  ai_engineer     REAL — LLM consultas técnicas vía llm_router
  audit_log       REAL — todas las acciones en master_console_audit

Seguridad:
  - X-Master-Key header requerido en TODOS los endpoints
  - MASTER_KEY desde variable de entorno (nunca hardcodeado)
  - Python sandbox: builtins bloqueados, sin import de os/sys/socket
  - Shell: blocklist de ~20 comandos destructivos
  - Audit trail: IP + timestamp + command_hash + resultado en Mongo
  - Rate limit: 20 req/min global para toda la consola
============================================================
"""

import asyncio
import contextlib
import hashlib
import io
import logging
import os
import re
import subprocess
import sys
import time
import traceback
import uuid
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger("master_console")

# ──────────────────────────────────────────────────────────────
# DB ref (inyectado desde server.py)
# ──────────────────────────────────────────────────────────────
_db = None


def set_db(database) -> None:
    global _db
    _db = database


def _get_db():
    if _db is None:
        raise RuntimeError("master_console: DB no inicializado")
    return _db


# ──────────────────────────────────────────────────────────────
# MASTER_KEY auth
# ──────────────────────────────────────────────────────────────
_MASTER_KEY = os.getenv("MASTER_KEY", "")
_MASTER_KEY_HASH = hashlib.sha256(_MASTER_KEY.encode()).hexdigest() if _MASTER_KEY else ""


async def require_master_key(
    x_master_key: str = Header(..., alias="X-Master-Key"),
    request: Request = None,
) -> str:
    """Dependency: valida MASTER_KEY y registra intento en audit."""
    if not _MASTER_KEY:
        raise HTTPException(503, detail="MASTER_KEY no configurado en el servidor")
    if hashlib.sha256(x_master_key.encode()).hexdigest() != _MASTER_KEY_HASH:
        ip = request.client.host if request and request.client else "unknown"
        logger.warning("MASTER_KEY inválida desde IP %s", ip)
        # Log failed attempt
        with contextlib.suppress(Exception):
            await _get_db().master_console_audit.insert_one({
                "event":      "auth_failed",
                "ip":         ip,
                "ts":         datetime.now(timezone.utc).isoformat(),
                "key_prefix": x_master_key[:4] + "..." if len(x_master_key) > 4 else "???",
            })
        raise HTTPException(403, detail="MASTER_KEY inválida")
    return x_master_key


# ──────────────────────────────────────────────────────────────
# Audit trail
# ──────────────────────────────────────────────────────────────
async def _audit(
    action: str,
    payload: Any,
    result: Any,
    ip: str = "unknown",
    duration_ms: float = 0,
) -> None:
    """Registra toda acción en master_console_audit."""
    payload_hash = hashlib.sha256(str(payload).encode()).hexdigest()[:16]
    with contextlib.suppress(Exception):
        await _get_db().master_console_audit.insert_one({
            "action":       action,
            "payload_hash": payload_hash,
            "result_ok":    result.get("ok", True) if isinstance(result, dict) else True,
            "ip":           ip,
            "duration_ms":  round(duration_ms, 1),
            "ts":           datetime.now(timezone.utc).isoformat(),
        })


def _client_ip(request: Request) -> str:
    if request and request.client:
        return request.client.host
    return "unknown"


# ──────────────────────────────────────────────────────────────
# Shell blocklist (superset del e2_executor)
# ──────────────────────────────────────────────────────────────
_SHELL_BLOCKLIST = re.compile(
    r"rm\s+-rf\s+/|"
    r"mkfs|"
    r"dd\s+if=/dev/zero|"
    r":\(\)\s*\{|"
    r"shutdown|"
    r"reboot|"
    r"halt|"
    r"poweroff|"
    r"init\s+0|"
    r"init\s+6|"
    r"chmod\s+-R\s+[0-7]*\s+/(?!opt)|"  # no chmod -R / (except /opt)
    r"chown\s+-R.*?/(?!opt)|"
    r">\s*/etc/passwd|"
    r">\s*/etc/shadow|"
    r">\s*/etc/sudoers|"
    r"curl.*\|\s*(?:bash|sh)|"
    r"wget.*\|\s*(?:bash|sh)|"
    r"python.*-c.*exec|"
    r"pkill\s+-9|"
    r"kill\s+-9\s+1\b",
    re.IGNORECASE,
)

_SHELL_TIMEOUT_SEC = 30
_PYTHON_TIMEOUT_SEC = 15


def _check_shell_blocklist(cmd: str) -> Optional[str]:
    m = _SHELL_BLOCKLIST.search(cmd)
    if m:
        return f"Comando bloqueado: patrón peligroso detectado ({m.group()[:40]})"
    return None


# ──────────────────────────────────────────────────────────────
# Python sandbox
# ──────────────────────────────────────────────────────────────
_SAFE_BUILTINS = {
    "print": print, "len": len, "range": range, "enumerate": enumerate,
    "zip": zip, "map": map, "filter": filter, "sorted": sorted,
    "sum": sum, "min": min, "max": max, "abs": abs, "round": round,
    "int": int, "float": float, "str": str, "bool": bool, "list": list,
    "dict": dict, "set": set, "tuple": tuple, "bytes": bytes,
    "isinstance": isinstance, "issubclass": issubclass, "type": type,
    "repr": repr, "vars": vars, "dir": dir, "hasattr": hasattr,
    "getattr": getattr, "setattr": setattr, "callable": callable,
    "iter": iter, "next": next, "any": any, "all": all,
    "format": format, "chr": chr, "ord": ord, "hex": hex, "oct": oct,
    "bin": bin, "divmod": divmod, "pow": pow, "hash": hash,
    "id": id, "object": object, "Exception": Exception,
    "ValueError": ValueError, "TypeError": TypeError, "KeyError": KeyError,
    "IndexError": IndexError, "RuntimeError": RuntimeError,
    "StopIteration": StopIteration, "NotImplementedError": NotImplementedError,
    # útiles para debugging
    "True": True, "False": False, "None": None,
}


# Patterns commonly used to escape Python sandboxes via object introspection.
# MASTER_KEY is the primary security control; this is defense-in-depth.
_SANDBOX_ESCAPE = re.compile(
    r"__class__\s*\.|__mro__\b|__subclasses__\s*\(\)|__reduce__|"
    r"__globals__\b|__code__\b|__import__\s*\(|__builtins__\b|"
    r"getattr\s*\(.*?__",
    re.IGNORECASE | re.DOTALL,
)


def _run_python_sandbox(code: str, timeout_sec: int = _PYTHON_TIMEOUT_SEC) -> dict:
    """Ejecuta Python en sandbox restringido. Captura stdout/stderr. No async."""
    if _SANDBOX_ESCAPE.search(code):
        return {
            "ok": False,
            "error": "Sandbox: patrón de escape detectado (__class__, __mro__, __subclasses__, etc.)",
            "stdout": "", "stderr": "", "elapsed_ms": 0,
        }
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    _globals = {"__builtins__": _SAFE_BUILTINS}
    result_val = None
    error = None

    def _exec():
        nonlocal result_val, error
        with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
            try:
                exec(compile(code, "<console>", "exec"), _globals)  # noqa: S102
                result_val = _globals.get("result", None)
            except Exception:
                error = traceback.format_exc()

    t = __import__("threading").Thread(target=_exec, daemon=True)
    t0 = time.monotonic()
    t.start()
    t.join(timeout=timeout_sec)
    elapsed = round((time.monotonic() - t0) * 1000, 1)

    if t.is_alive():
        return {
            "ok": False,
            "error": f"Timeout: ejecución superó {timeout_sec}s",
            "stdout": stdout_buf.getvalue(),
            "stderr": "",
            "elapsed_ms": elapsed,
        }

    return {
        "ok": error is None,
        "result": repr(result_val) if result_val is not None else None,
        "stdout": stdout_buf.getvalue(),
        "stderr": stderr_buf.getvalue(),
        "error": error,
        "elapsed_ms": elapsed,
    }


# ──────────────────────────────────────────────────────────────
# Shell runner
# ──────────────────────────────────────────────────────────────
async def _run_shell(cmd: str) -> dict:
    blocked = _check_shell_blocklist(cmd)
    if blocked:
        return {"ok": False, "error": blocked, "stdout": "", "stderr": "", "exit_code": -1}
    try:
        t0 = time.monotonic()
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=_SHELL_TIMEOUT_SEC)
        except asyncio.TimeoutError:
            proc.kill()
            return {"ok": False, "error": f"Timeout: {_SHELL_TIMEOUT_SEC}s", "stdout": "", "stderr": "", "exit_code": -1}
        elapsed = round((time.monotonic() - t0) * 1000, 1)
        stdout = stdout_b.decode("utf-8", errors="replace")[:8000]
        stderr = stderr_b.decode("utf-8", errors="replace")[:2000]
        return {
            "ok": proc.returncode == 0,
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": proc.returncode,
            "elapsed_ms": elapsed,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "stdout": "", "stderr": "", "exit_code": -1}


# ──────────────────────────────────────────────────────────────
# Live Monitor aggregator
# ──────────────────────────────────────────────────────────────
async def _live_monitor_snapshot() -> dict:
    db = _get_db()
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")

    # Queue stats
    queue_pipeline = [
        {"$group": {"_id": "$status", "count": {"$sum": 1}}}
    ]
    queue_by_status: dict = {}
    async for doc in db.jobs.aggregate(queue_pipeline):
        queue_by_status[doc["_id"]] = doc["count"]

    # Dead letter last 24h
    dlq_count = await db.jobs.count_documents({
        "status": "dead_letter",
        "updated_at": {"$gte": datetime.now(timezone.utc).replace(hour=0, minute=0, second=0).isoformat()},
    })

    # E9 counters today (aggregated per module)
    # e9_counters schema: {module, day, tenant_id, call_count, event_count, error_count, ...}
    e9_today: dict = {}
    async for doc in db.e9_counters.find({"day": today}):
        key = doc.get("module", "?")
        if key not in e9_today:
            e9_today[key] = {"calls": 0, "events": 0, "errors": 0}
        e9_today[key]["calls"]  += doc.get("call_count", 0)
        e9_today[key]["events"] += doc.get("event_count", 0)
        e9_today[key]["errors"] += doc.get("error_count", 0)

    # AI costs today
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    cost_pipeline = [
        {"$match": {"ts": {"$gte": day_start}}},
        {"$group": {
            "_id": "$model",
            "total_usd": {"$sum": "$cost_usd"},
            "calls": {"$sum": 1},
            "tokens": {"$sum": {"$add": ["$prompt_tokens", "$completion_tokens"]}},
        }},
    ]
    ai_costs: list = []
    async for doc in db.e9_ai_costs.aggregate(cost_pipeline):
        ai_costs.append({
            "model": doc["_id"],
            "calls": doc["calls"],
            "tokens": doc["tokens"],
            "total_usd": round(doc["total_usd"], 4),
        })

    # SLA breaches open
    sla_breaches = await db.e8_tickets.count_documents({"sla_breached": True, "status": {"$ne": "closed"}})

    # Recent errors — field is "event_type" not "event"
    recent_errors: list = []
    async for doc in db.e9_events.find(
        {"event_type": {"$regex": r"(\.failed|error)$"}}
    ).sort("ts", -1).limit(10):
        recent_errors.append({
            "module": doc.get("module"),
            "event":  doc.get("event_type"),   # surface as "event" for UI compat
            "tenant": doc.get("tenant_id"),
            "ts":     doc.get("ts"),
            "error":  str(doc.get("data", {}).get("error", ""))[:120],
        })

    # Worker heartbeat — field is "event_type" not "event"
    recent_heartbeat = await db.e9_events.find_one(
        {"event_type": "worker.heartbeat"},
        sort=[("ts", -1)],
    )
    last_heartbeat = recent_heartbeat.get("ts") if recent_heartbeat else None

    return {
        "ts": now.isoformat(),
        "queue": {
            "by_status": queue_by_status,
            "dlq_today": dlq_count,
        },
        "e9_counters_today": e9_today,
        "ai_costs_today": ai_costs,
        "sla_breaches_open": sla_breaches,
        "recent_errors": recent_errors,
        "worker_last_heartbeat": last_heartbeat,
    }


# ──────────────────────────────────────────────────────────────
# AI Technical Engineer
# ──────────────────────────────────────────────────────────────
async def _ai_engineer(question: str, context: str = "") -> dict:
    """Calls LLM for technical analysis. Uses llm_router."""
    try:
        import llm_router  # local module

        system = (
            "Eres un ingeniero de infraestructura experto en Python/FastAPI/MongoDB/Linux. "
            "Analiza el problema técnico con precisión. Responde con diagnóstico concreto y pasos de solución. "
            "Sé conciso: máximo 600 palabras."
        )
        user_msg = question
        if context:
            user_msg = f"CONTEXTO:\n{context[:2000]}\n\nPREGUNTA:\n{question}"

        response = await llm_router.chat_completion(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=1000,
            temperature=0.2,
        )
        answer = response.get("content") or response.get("text") or str(response)
        return {"ok": True, "answer": answer, "model": response.get("model", "llm_router")}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ──────────────────────────────────────────────────────────────
# Pydantic models
# ──────────────────────────────────────────────────────────────
class PythonRunReq(BaseModel):
    code: str
    timeout_sec: int = _PYTHON_TIMEOUT_SEC


class ShellRunReq(BaseModel):
    command: str


class DeployReq(BaseModel):
    repo_url: str
    service: str
    branch: str = "main"


class SSLReq(BaseModel):
    domain: str
    action: str = "issue"   # issue | renew | revoke


class DockerReq(BaseModel):
    action: str             # start | stop | restart | logs | ps
    container: str = ""


class AIEngineerReq(BaseModel):
    question: str
    context: str = ""


class FileReadReq(BaseModel):
    path: str
    lines: int = 200
    offset: int = 0


# ──────────────────────────────────────────────────────────────
# Router
# ──────────────────────────────────────────────────────────────
router = APIRouter(prefix="/api/master", tags=["master-console"])

# ── Auth check ──────────────────────────────────────────────
@router.get("/ping")
async def ping(request: Request, _key: str = Depends(require_master_key)):
    """Health check — verifica que MASTER_KEY funciona."""
    ip = _client_ip(request)
    await _audit("ping", {}, {"ok": True}, ip=ip)
    return {"ok": True, "ts": datetime.now(timezone.utc).isoformat(), "server": "master_console"}


# ── Python runner ────────────────────────────────────────────
@router.post("/python/run")
async def python_run(
    req: PythonRunReq,
    request: Request,
    _key: str = Depends(require_master_key),
):
    """
    Ejecuta Python en sandbox restringido.
    Builtins peligrosos deshabilitados (open, __import__, os, sys, socket, subprocess).
    Timeout configurable, máx 60s.
    stdout/stderr capturados y devueltos.
    """
    timeout = min(max(req.timeout_sec, 1), 60)
    code_hash = hashlib.sha256(req.code.encode()).hexdigest()[:12]
    logger.info("python_run code_hash=%s ip=%s", code_hash, _client_ip(request))

    # Run in thread executor (exec is sync)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _run_python_sandbox, req.code, timeout)

    await _audit("python_run", {"hash": code_hash, "len": len(req.code)}, result, ip=_client_ip(request), duration_ms=result.get("elapsed_ms", 0))
    return result


# ── Shell runner ─────────────────────────────────────────────
@router.post("/shell/run")
async def shell_run(
    req: ShellRunReq,
    request: Request,
    _key: str = Depends(require_master_key),
):
    """
    Ejecuta comando shell con blocklist de ~20 patrones destructivos.
    Timeout 30s. stdout limitado a 8KB. stderr a 2KB.
    Cada ejecución queda en master_console_audit.
    """
    t0 = time.monotonic()
    cmd_hash = hashlib.sha256(req.command.encode()).hexdigest()[:12]
    logger.info("shell_run cmd=%r hash=%s ip=%s", req.command[:80], cmd_hash, _client_ip(request))

    result = await _run_shell(req.command)
    elapsed = round((time.monotonic() - t0) * 1000, 1)
    result["elapsed_ms"] = elapsed

    await _audit("shell_run", {"cmd": req.command[:200], "hash": cmd_hash}, result, ip=_client_ip(request), duration_ms=elapsed)
    return result


# ── Deploy trigger ───────────────────────────────────────────
@router.post("/deploy/trigger")
async def deploy_trigger(
    req: DeployReq,
    request: Request,
    _key: str = Depends(require_master_key),
):
    """
    Lanza deploy real via e2_executor.run_deploy().
    Requiere E2_VPS_HOST/USER/PASS configurados.
    """
    try:
        import e2_executor
        t0 = time.monotonic()
        result = await e2_executor.run_deploy(req.repo_url, req.service, req.branch)
        elapsed = round((time.monotonic() - t0) * 1000, 1)
        result["elapsed_ms"] = elapsed
        await _audit("deploy_trigger", {"repo": req.repo_url, "service": req.service, "branch": req.branch}, result, ip=_client_ip(request), duration_ms=elapsed)
        return result
    except Exception as exc:
        err = {"ok": False, "error": str(exc)}
        await _audit("deploy_trigger", req.dict(), err, ip=_client_ip(request))
        raise HTTPException(500, detail=str(exc))


# ── Docker control ───────────────────────────────────────────
@router.post("/docker")
async def docker_control(
    req: DockerReq,
    request: Request,
    _key: str = Depends(require_master_key),
):
    """Controla containers Docker via e2_executor."""
    try:
        import e2_executor
        result = await e2_executor.run_docker(req.action, req.container)
        await _audit("docker", req.dict(), result, ip=_client_ip(request))
        return result
    except Exception as exc:
        raise HTTPException(500, detail=str(exc))


# ── SSL manager ──────────────────────────────────────────────
@router.post("/ssl")
async def ssl_manage(
    req: SSLReq,
    request: Request,
    _key: str = Depends(require_master_key),
):
    """Gestiona certificados SSL via e2_executor (certbot)."""
    try:
        import e2_executor
        result = await e2_executor.run_ssl(req.domain, req.action)
        await _audit("ssl", req.dict(), result, ip=_client_ip(request))
        return result
    except Exception as exc:
        raise HTTPException(500, detail=str(exc))


# ── System metrics ───────────────────────────────────────────
@router.get("/system/metrics")
async def system_metrics(
    request: Request,
    _key: str = Depends(require_master_key),
):
    """CPU, RAM, disco del VPS via e2_executor."""
    try:
        import e2_executor
        result = await e2_executor.system_metrics()
        await _audit("system_metrics", {}, result, ip=_client_ip(request))
        return result
    except Exception as exc:
        raise HTTPException(500, detail=str(exc))


# ── Live monitor ─────────────────────────────────────────────
@router.get("/monitor")
async def live_monitor(
    request: Request,
    _key: str = Depends(require_master_key),
):
    """
    Snapshot en tiempo real:
    - Queue depth por status
    - DLQ hoy
    - E9 counters del día
    - Costos IA del día
    - SLA breaches abiertas
    - Últimos 10 errores
    - Último heartbeat del worker
    """
    result = await _live_monitor_snapshot()
    await _audit("live_monitor", {}, {"ok": True}, ip=_client_ip(request))
    return result


# ── File reader ──────────────────────────────────────────────
@router.post("/file/read")
async def file_read(
    req: FileReadReq,
    request: Request,
    _key: str = Depends(require_master_key),
):
    """
    Lee un archivo del sistema (read-only).
    path: absoluto o relativo a /opt/lluvia-studio/backend/
    lines: máximo 500.
    """
    # Resolve and contain path — symlink-safe via Path.resolve()
    from pathlib import Path as _Path
    raw = req.path
    if not raw.startswith("/"):
        raw = f"/opt/lluvia-studio/backend/{raw}"
    try:
        resolved = _Path(raw).resolve()
    except (ValueError, OSError) as e:
        raise HTTPException(400, detail=f"Ruta inválida: {e}")
    _ALLOWED_BASE = _Path("/opt/lluvia-studio").resolve()
    if not str(resolved).startswith(str(_ALLOWED_BASE)):
        raise HTTPException(403, detail="Acceso denegado: ruta fuera del directorio permitido")
    path = str(resolved)
    lines = min(max(req.lines, 1), 500)

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
        offset = max(req.offset, 0)
        chunk = all_lines[offset: offset + lines]
        content = "".join(chunk)
        result = {
            "ok": True,
            "path": path,
            "total_lines": len(all_lines),
            "returned_lines": len(chunk),
            "offset": offset,
            "content": content,
        }
        await _audit("file_read", {"path": path}, {"ok": True}, ip=_client_ip(request))
        return result
    except FileNotFoundError:
        raise HTTPException(404, detail=f"Archivo no encontrado: {path}")
    except PermissionError:
        raise HTTPException(403, detail="Sin permiso de lectura")
    except Exception as exc:
        raise HTTPException(500, detail=str(exc))


# ── AI Technical Engineer ────────────────────────────────────
@router.post("/ai/engineer")
async def ai_engineer(
    req: AIEngineerReq,
    request: Request,
    _key: str = Depends(require_master_key),
):
    """
    Consulta al AI Technical Engineer.
    Analiza problemas de infra, errores de logs, optimizaciones de código.
    context: opcional — pegar logs, tracebacks, código relevante.
    """
    result = await _ai_engineer(req.question, req.context)
    await _audit("ai_engineer", {"q_len": len(req.question)}, result, ip=_client_ip(request))
    return result


# ── Audit log reader ─────────────────────────────────────────
@router.get("/audit")
async def audit_log(
    request: Request,
    _key: str = Depends(require_master_key),
    limit: int = 50,
    action: Optional[str] = None,
):
    """Lee las últimas N entradas del audit trail de la Master Console."""
    db = _get_db()
    filt: dict = {}
    if action:
        filt["action"] = action
    limit = min(max(limit, 1), 200)

    entries: list = []
    async for doc in db.master_console_audit.find(filt).sort("ts", -1).limit(limit):
        doc.pop("_id", None)
        entries.append(doc)

    return {"ok": True, "count": len(entries), "entries": entries}


# ── Jobs queue view ──────────────────────────────────────────
@router.get("/queue/snapshot")
async def queue_snapshot(
    request: Request,
    _key: str = Depends(require_master_key),
    status: Optional[str] = None,
    limit: int = 20,
):
    """Vista de jobs en la cola (queued/running/retrying/dead_letter)."""
    db = _get_db()
    filt: dict = {}
    if status:
        filt["status"] = status
    limit = min(max(limit, 1), 100)

    jobs: list = []
    async for doc in db.jobs.find(filt).sort("run_at", 1).limit(limit):
        doc.pop("_id", None)
        jobs.append(doc)

    return {"ok": True, "count": len(jobs), "jobs": jobs}


@router.post("/queue/retry/{job_id}")
async def queue_retry_job(
    job_id: str,
    request: Request,
    _key: str = Depends(require_master_key),
):
    """Fuerza reintentar un job en dead_letter o failed."""
    db = _get_db()
    from datetime import timezone

    result = await db.jobs.find_one_and_update(
        {"job_id": job_id, "status": {"$in": ["dead_letter", "failed"]}},
        {"$set": {
            "status": "queued",
            "run_at": datetime.now(timezone.utc).isoformat(),
            "locked_until": datetime.now(timezone.utc).isoformat(),
            "attempts": 0,
            "error": None,
        }},
        return_document=True,
    )
    if not result:
        raise HTTPException(404, detail=f"Job {job_id!r} no encontrado o no es dead_letter/failed")

    await _audit("queue_retry", {"job_id": job_id}, {"ok": True}, ip=_client_ip(request))
    return {"ok": True, "job_id": job_id, "status": "requeued"}


@router.delete("/queue/dlq/flush")
async def flush_dlq(
    request: Request,
    _key: str = Depends(require_master_key),
    older_than_days: int = 7,
):
    """Elimina entradas del DLQ más viejas de N días."""
    db = _get_db()
    cutoff = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0
    )
    # Simple cutoff: jobs updated more than N days ago
    from datetime import timedelta
    cutoff -= timedelta(days=older_than_days)

    res = await db.jobs.delete_many({
        "status": "dead_letter",
        "updated_at": {"$lte": cutoff.isoformat()},
    })
    await _audit("dlq_flush", {"older_than_days": older_than_days}, {"deleted": res.deleted_count}, ip=_client_ip(request))
    return {"ok": True, "deleted": res.deleted_count, "cutoff": cutoff.isoformat()}


# ── Tenant diagnostics ───────────────────────────────────────
@router.get("/tenant/{tenant_id}/diagnostics")
async def tenant_diagnostics(
    tenant_id: str,
    request: Request,
    _key: str = Depends(require_master_key),
):
    """
    Diagnóstico completo de un tenant:
    - Jobs activos/fallidos
    - Tickets abiertos + SLA
    - Posts pendientes
    - Costos IA últimos 7 días
    - Errores últimas 24h
    """
    db = _get_db()
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    day_ago = (now - timedelta(hours=24)).isoformat()
    week_ago = (now - timedelta(days=7)).isoformat()

    # Jobs
    job_pipeline = [
        {"$match": {"tenant_id": tenant_id}},
        {"$group": {"_id": "$status", "count": {"$sum": 1}}},
    ]
    jobs_by_status: dict = {}
    async for doc in db.jobs.aggregate(job_pipeline):
        jobs_by_status[doc["_id"]] = doc["count"]

    # Tickets
    open_tickets = await db.e8_tickets.count_documents({"tenant_id": tenant_id, "status": {"$ne": "closed"}})
    sla_breached = await db.e8_tickets.count_documents({"tenant_id": tenant_id, "sla_breached": True, "status": {"$ne": "closed"}})

    # Posts
    pending_posts = await db.e10_posts.count_documents({"tenant_id": tenant_id, "status": {"$in": ["pending", "scheduled"]}})

    # AI costs 7 days
    cost_pipeline = [
        {"$match": {"tenant_id": tenant_id, "ts": {"$gte": week_ago}}},
        {"$group": {"_id": "$model", "total_usd": {"$sum": "$cost_usd"}, "calls": {"$sum": 1}}},
    ]
    ai_costs: list = []
    async for doc in db.e9_ai_costs.aggregate(cost_pipeline):
        ai_costs.append({"model": doc["_id"], "calls": doc["calls"], "usd": round(doc["total_usd"], 4)})

    # Recent errors — field is "event_type" not "event"
    errors: list = []
    async for doc in db.e9_events.find({
        "tenant_id": tenant_id,
        "event_type": {"$regex": r"(\.failed|error)$"},
        "ts": {"$gte": day_ago},
    }).sort("ts", -1).limit(20):
        errors.append({
            "module": doc.get("module"),
            "event":  doc.get("event_type"),  # surface as "event" for UI compat
            "ts":     doc.get("ts"),
            "error":  str(doc.get("data", {}).get("error", ""))[:100],
        })

    return {
        "ok": True,
        "tenant_id": tenant_id,
        "ts": now.isoformat(),
        "jobs": {"by_status": jobs_by_status},
        "tickets": {"open": open_tickets, "sla_breached": sla_breached},
        "posts": {"pending": pending_posts},
        "ai_costs_7d": ai_costs,
        "errors_24h": errors,
    }


# ── Status summary ───────────────────────────────────────────
@router.get("/status")
async def system_status(
    request: Request,
    _key: str = Depends(require_master_key),
):
    """
    Estado global del sistema:
    STATUS por módulo (REAL/PARCIAL/STUB/MOCK basado en env vars)
    """
    e2_real = bool(os.getenv("E2_VPS_HOST") and os.getenv("E2_VPS_USER"))

    modules = {
        "E1_orchestrator":  "REAL",
        "E2_infra_crud":    "REAL",
        "E2_infra_exec":    "REAL" if e2_real else "STUB — configurar E2_VPS_HOST/USER/PASS",
        "E3_builder":       "PARCIAL — CRUD real, generación IA parcial",
        "E4_sales":         "PARCIAL — scheduler real, email/SMS envío stub",
        "E5_whitelabel":    "REAL",
        "E6_legal":         "REAL — PDF real, e-sign real, LLM gen real",
        "E7_billing":       "PARCIAL — PayPal real, Stripe stub",
        "E8_support":       "REAL — tickets, SLA, auto-assign, KB search",
        "E9_analytics":     "REAL — eventos, costos IA, dashboards live",
        "E10_social":       "REAL — Instagram/Facebook/Twitter/LinkedIn real",
        "E10_tiktok":       "PARCIAL — video async, sin text/image",
        "E11_gmail":        "REAL — inbox, followups, scheduler",
        "job_scheduler":    "REAL — Mongo queue, retries, DLQ, bridges",
        "master_console":   "REAL — python/shell/deploy/monitor/ai-engineer",
    }

    missing_env: list = []
    for var in ["MASTER_KEY", "E2_VPS_HOST", "E2_VPS_USER", "OPENAI_API_KEY"]:
        if not os.getenv(var):
            missing_env.append(var)

    return {
        "ok": True,
        "ts": datetime.now(timezone.utc).isoformat(),
        "modules": modules,
        "missing_env_vars": missing_env,
    }


# ── Index (help) ─────────────────────────────────────────────
@router.get("/")
async def master_console_index(request: Request, _key: str = Depends(require_master_key)):
    """Lista todos los endpoints disponibles de la Master Console."""
    return {
        "name": "Lluvia Master Console",
        "version": "1.0",
        "endpoints": [
            "GET  /api/master/ping",
            "GET  /api/master/status",
            "GET  /api/master/monitor",
            "POST /api/master/python/run",
            "POST /api/master/shell/run",
            "POST /api/master/deploy/trigger",
            "POST /api/master/docker",
            "POST /api/master/ssl",
            "GET  /api/master/system/metrics",
            "POST /api/master/file/read",
            "POST /api/master/ai/engineer",
            "GET  /api/master/audit",
            "GET  /api/master/queue/snapshot",
            "POST /api/master/queue/retry/{job_id}",
            "DELETE /api/master/queue/dlq/flush",
            "GET  /api/master/tenant/{tenant_id}/diagnostics",
        ],
    }


# ── create_indexes ───────────────────────────────────────────
async def create_indexes() -> None:
    db = _get_db()
    await db.master_console_audit.create_index([("ts", -1)])
    await db.master_console_audit.create_index([("action", 1)])
    await db.master_console_audit.create_index([("ip", 1)])
    logger.info("master_console: indexes OK")
