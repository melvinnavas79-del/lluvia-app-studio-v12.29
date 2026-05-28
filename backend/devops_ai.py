"""
devops_ai.py - AI Operating Center (Lluvia App Studio)

Endpoints:
  POST /api/devops/analyze               NL → propuesta con diffs (no aplica nada)
  GET  /api/devops/proposals             Lista propuestas DevOps (admin only)
  GET  /api/devops/proposals/{id}        Detalle completo + diff
  POST /api/devops/proposals/{id}/approve checkpoint automático + apply
  POST /api/devops/proposals/{id}/reject
  GET  /api/devops/checkpoints           Historial de snapshots
  POST /api/devops/checkpoints/{cid}/rollback  Restaurar estado anterior
  GET  /api/devops/status                Estado del sistema (git, containers, disco)

Seguridad:
  - NUNCA ejecuta código arbitrario
  - NUNCA modifica producción sin checkpoint previo
  - Solo lista blanca de comandos permitidos post-aprobación
  - Toda acción queda auditada en MongoDB (devops_proposals, devops_checkpoints)
  - Solo admins pueden usar estos endpoints
"""

import os
import re
import uuid
import json
import asyncio
import difflib
import logging
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import get_current_user
import config
import llm_router

logger = logging.getLogger("devops_ai")
router = APIRouter(prefix="/devops", tags=["devops_ai"])
_db_ref: dict = {"db": None}


# ============================================================
# PATHS (todos configurables via env)
# ============================================================
SOURCE_DIR   = Path(os.environ.get("LLUVIA_SOURCE_DIR",    "/opt/lluvia-studio"))
BACKEND_SRC  = SOURCE_DIR / "backend"
FRONTEND_SRC = SOURCE_DIR / "frontend" / "src"
PROD_BACKEND = Path(os.environ.get("LLUVIA_PROD_BACKEND",  "/opt/lluvia/backend"))
PROD_FRONTEND_BUILD = SOURCE_DIR / "frontend" / "build"
PROD_FRONTEND = Path(os.environ.get("LLUVIA_PROD_FRONTEND", "/opt/lluvia/frontend-build"))
DOCKER_COMPOSE = Path(os.environ.get("LLUVIA_DOCKER_COMPOSE", "/opt/lluvia/docker-compose.yml"))
BACKUPS_DIR  = Path(os.environ.get("DEVOPS_BACKUPS_DIR",   "/opt/lluvia-devops-backups"))
BACKUPS_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# LISTA BLANCA DE COMANDOS (lo único que puede ejecutar el sistema)
# ============================================================
ALLOWED_COMMANDS: dict[str, str] = {
    "build_frontend":    f"cd {SOURCE_DIR}/frontend && npm run build",
    "deploy_frontend":   f"cp -r {PROD_FRONTEND_BUILD}/. {PROD_FRONTEND}/",
    "restart_backend":   f"docker compose -f {DOCKER_COMPOSE} restart backend",
    "restart_frontend":  f"docker compose -f {DOCKER_COMPOSE} restart frontend",
    "git_status":        f"git -C {SOURCE_DIR} status --short",
    "git_log":           f"git -C {SOURCE_DIR} log --oneline -10",
}

# Extensiones de texto legibles
TEXT_EXTS = {".py", ".js", ".jsx", ".ts", ".tsx", ".css", ".html",
             ".md", ".json", ".yml", ".yaml", ".toml", ".sh", ".conf", ".env"}
SKIP_DIRS = {"node_modules", "__pycache__", ".git", "build", "dist",
             "venv", ".venv", "coverage", ".nyc_output"}
MAX_FILE_CHARS = 40_000  # limite por archivo al enviar a la IA


def set_db(db) -> None:
    _db_ref["db"] = db


def _require_admin(user: dict) -> None:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Solo admin")


# ============================================================
# HELPERS: lectura de archivos fuente
# ============================================================
def _is_inside_source(path: Path) -> bool:
    try:
        path.resolve().relative_to(SOURCE_DIR.resolve())
        return True
    except ValueError:
        return False


def _list_source_tree(root: Path, max_files: int = 150) -> list[str]:
    """Devuelve lista de rutas relativas a SOURCE_DIR, sin dirs bloqueados."""
    result = []
    for p in sorted(root.rglob("*")):
        if any(skip in p.parts for skip in SKIP_DIRS):
            continue
        if p.is_file() and p.suffix in TEXT_EXTS:
            result.append(str(p.relative_to(SOURCE_DIR)))
        if len(result) >= max_files:
            break
    return result


def _read_source_file(rel_path: str) -> str:
    """Lee un archivo fuente por path relativo a SOURCE_DIR. Seguro contra path-traversal."""
    clean = re.sub(r"\.\./", "", rel_path).lstrip("/")
    full = (SOURCE_DIR / clean).resolve()
    if not _is_inside_source(full):
        return "ERROR: path fuera de SOURCE_DIR"
    if not full.exists():
        return f"ERROR: archivo no existe: {clean}"
    if full.stat().st_size > 500_000:
        return "ERROR: archivo demasiado grande para leer"
    try:
        content = full.read_text(encoding="utf-8", errors="replace")
        return content[:MAX_FILE_CHARS]
    except Exception as e:
        return f"ERROR leyendo archivo: {e}"


def _compute_diff(original: str, new_content: str, filename: str) -> str:
    """Genera unified diff entre contenido original y nuevo."""
    original_lines = original.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    diff = difflib.unified_diff(
        original_lines, new_lines,
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
        lineterm="",
    )
    return "".join(diff)[:20_000]


# ============================================================
# HELPERS: checkpoints (git + file backup)
# ============================================================
async def _create_checkpoint(proposal_id: str, description: str) -> dict:
    """
    Crea checkpoint en dos capas:
    1. Git commit en SOURCE_DIR (si hay cambios sin commitear)
    2. Copia física de los archivos que la propuesta va a tocar a BACKUPS_DIR
    Devuelve metadata del checkpoint guardada en MongoDB.
    """
    db = _db_ref["db"]
    cid = f"cp_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    backup_path = BACKUPS_DIR / cid
    backup_path.mkdir(parents=True, exist_ok=True)

    # Git checkpoint
    git_ref = None
    try:
        proc = await asyncio.create_subprocess_shell(
            f"cd {SOURCE_DIR} && git add -A && git commit -m '[devops-checkpoint] {description}' --allow-empty",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await proc.communicate()
        git_ref = out.decode("utf-8", "ignore").strip()[:300]
    except Exception as e:
        git_ref = f"git error: {e}"

    doc = {
        "id": cid,
        "proposal_id": proposal_id,
        "description": description,
        "backup_path": str(backup_path),
        "git_ref": git_ref,
        "files_backed_up": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.devops_checkpoints.insert_one(doc)
    doc.pop("_id", None)
    return doc


async def _backup_files(checkpoint: dict, file_paths: list[str]) -> dict:
    """Copia los archivos originales al backup del checkpoint antes de modificarlos."""
    db = _db_ref["db"]
    backup_path = Path(checkpoint["backup_path"])
    backed_up = []
    for rel in file_paths:
        clean = re.sub(r"\.\./", "", rel).lstrip("/")
        src = (SOURCE_DIR / clean).resolve()
        if not _is_inside_source(src) or not src.exists():
            continue
        dst = backup_path / clean
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(src, dst)
            backed_up.append(rel)
        except Exception as e:
            logger.warning(f"[devops] No se pudo hacer backup de {rel}: {e}")
    await db.devops_checkpoints.update_one(
        {"id": checkpoint["id"]},
        {"$set": {"files_backed_up": backed_up}},
    )
    checkpoint["files_backed_up"] = backed_up
    return checkpoint


async def _rollback_from_checkpoint(checkpoint: dict) -> dict:
    """Restaura archivos desde el backup del checkpoint."""
    backup_path = Path(checkpoint["backup_path"])
    if not backup_path.exists():
        return {"ok": False, "error": "Directorio de backup no encontrado"}
    restored = []
    errors = []
    for rel in checkpoint.get("files_backed_up", []):
        src = backup_path / rel
        dst = SOURCE_DIR / rel
        if not src.exists():
            errors.append(f"backup no encontrado: {rel}")
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            restored.append(rel)
        except Exception as e:
            errors.append(f"{rel}: {e}")
    return {"ok": len(errors) == 0, "restored": restored, "errors": errors}


# ============================================================
# HELPERS: ejecución post-aprobación (solo lista blanca)
# ============================================================
async def _run_whitelisted(command_key: str, timeout_sec: int = 120) -> dict:
    """Ejecuta solo comandos de ALLOWED_COMMANDS. NUNCA comandos arbitrarios."""
    cmd = ALLOWED_COMMANDS.get(command_key)
    if not cmd:
        return {"ok": False, "error": f"Comando '{command_key}' no está en la lista blanca"}
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
        output = out.decode("utf-8", "ignore")[:5000]
        ok = proc.returncode == 0
        return {"ok": ok, "command": command_key, "output": output, "returncode": proc.returncode}
    except asyncio.TimeoutError:
        return {"ok": False, "error": f"Timeout ({timeout_sec}s)", "command": command_key}
    except Exception as e:
        return {"ok": False, "error": str(e), "command": command_key}


BACKEND_CONTAINER = os.environ.get("BACKEND_CONTAINER", "lluvia_backend")


async def _deploy_backend_files(changed_files: list[str]) -> dict:
    """Copia archivos .py modificados al contenedor via docker cp."""
    results = []
    for rel in changed_files:
        if not rel.startswith("backend/") or not rel.endswith(".py"):
            continue
        src = SOURCE_DIR / rel
        filename = Path(rel).name
        if not src.exists():
            results.append({"file": rel, "ok": False, "error": "No existe en source"})
            continue
        # Primero a /opt/lluvia/backend/ en host, luego docker cp al contenedor
        dst_host = PROD_BACKEND / filename
        try:
            shutil.copy2(src, dst_host)
        except Exception as e:
            results.append({"file": rel, "ok": False, "error": f"copy host: {e}"})
            continue
        try:
            proc = await asyncio.create_subprocess_shell(
                f"docker cp {dst_host} {BACKEND_CONTAINER}:/app/{filename}",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
            ok = proc.returncode == 0
            results.append({"file": rel, "ok": ok,
                            "output": out.decode("utf-8", "ignore")[:200] if not ok else ""})
        except Exception as e:
            results.append({"file": rel, "ok": False, "error": f"docker cp: {e}"})
    return {"ok": all(r["ok"] for r in results) if results else True, "files": results}


# ============================================================
# HELPERS: análisis con IA
# ============================================================
DEVOPS_SYSTEM = """Eres el AI DevOps Architect de Lluvia App Studio.
Tu única función es analizar requests y generar propuestas estructuradas de cambio de código.

PROYECTO:
- Backend: FastAPI + MongoDB en /opt/lluvia-studio/backend/
- Frontend: React en /opt/lluvia-studio/frontend/src/
- Producción backend: /opt/lluvia/backend/
- Producción frontend: /opt/lluvia/frontend-build/
- Deploy: docker compose en /opt/lluvia/

REGLAS ESTRICTAS:
1. SIEMPRE usa las tools para leer archivos antes de proponer cambios.
2. NUNCA inventes contenido de archivos que no hayas leído.
3. NUNCA propongas eliminar módulos, tabs, routes o features existentes.
4. Toda propuesta debe ser incremental y retrocompatible.
5. Si el cambio toca el frontend, siempre marca requires_build: true.
6. Si el cambio toca backend Python, marca el archivo en requires_deploy_backend.
7. Responde SOLO con JSON válido en el formato indicado. Sin texto extra.

FORMATO DE RESPUESTA (JSON estricto):
{
  "analysis": "descripción breve del análisis (máximo 200 chars)",
  "changes": [
    {
      "file": "backend/nombre.py",
      "action": "modify",
      "new_content": "...contenido completo del archivo modificado...",
      "rationale": "por qué se hace este cambio"
    }
  ],
  "requires_build": false,
  "requires_deploy_backend": ["archivo1.py"],
  "requires_restart": ["backend"],
  "risk": "low",
  "risk_detail": "descripción del riesgo",
  "rollback_plan": "descripción del rollback"
}

NIVELES DE RIESGO:
- low: cambios aditivos, nuevos features, no toca flujos existentes
- medium: modifica flujos existentes pero es retrocompatible
- high: toca auth, pagos, datos críticos o requiere migración

Si necesitas más información antes de proponer, usa las tools para leer archivos.
"""

DEVOPS_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_source_files",
            "description": "Lista archivos fuente del proyecto. dir puede ser 'backend', 'frontend/src', o '' para la raíz.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dir": {"type": "string", "description": "Subdirectorio relativo a SOURCE_DIR. Ej: 'backend', 'frontend/src/components'"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_source_file",
            "description": "Lee el contenido de un archivo fuente. Path relativo a /opt/lluvia-studio/",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path relativo. Ej: 'backend/agent_builder.py'"},
                },
                "required": ["path"],
            },
        },
    },
]


async def _execute_devops_tool(name: str, args: dict) -> str:
    if name == "list_source_files":
        subdir = args.get("dir", "")
        root = (SOURCE_DIR / subdir).resolve() if subdir else SOURCE_DIR.resolve()
        if not _is_inside_source(root):
            return json.dumps({"error": "path fuera de SOURCE_DIR"})
        files = _list_source_tree(root)
        return json.dumps({"files": files, "count": len(files)})
    elif name == "read_source_file":
        path = args.get("path", "")
        content = _read_source_file(path)
        return json.dumps({"path": path, "content": content})
    return json.dumps({"error": f"tool desconocida: {name}"})


async def _analyze_with_ai(request_text: str) -> dict:
    """Llama al LLM con tools para analizar el request y generar propuesta estructurada."""
    if not llm_router.llm_available():
        raise HTTPException(503, "Motor IA no configurado.")

    client, _llm_model = llm_router.get_client("low")
    messages = [
        {"role": "system", "content": DEVOPS_SYSTEM},
        {"role": "user", "content": f"REQUEST: {request_text}"},
    ]

    for iteration in range(8):  # max 8 vueltas de tool-calling
        response = await client.chat.completions.create(
            model=_llm_model,
            messages=messages,
            tools=DEVOPS_TOOLS,
            tool_choice="auto",
            temperature=0.1,
            max_tokens=4000,
        )
        msg = response.choices[0].message

        if not msg.tool_calls:
            # Respuesta final — debe ser JSON
            raw = (msg.content or "").strip()
            # Extraer JSON si viene envuelto en ```json
            m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
            if m:
                raw = m.group(1)
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                raise HTTPException(500, f"IA no devolvió JSON válido: {raw[:300]}")

        # Ejecutar tool calls
        messages.append({
            "role": "assistant",
            "content": msg.content,
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls
            ],
        })
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}
            result = await _execute_devops_tool(tc.function.name, args)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

    raise HTTPException(500, "IA no convergió después de 8 iteraciones")


# ============================================================
# MODELOS PYDANTIC
# ============================================================
class AnalyzeIn(BaseModel):
    request: str = Field(min_length=5, max_length=2000)


class RejectIn(BaseModel):
    reason: Optional[str] = Field(None, max_length=500)


# ============================================================
# ENDPOINTS
# ============================================================

@router.get("/status")
async def devops_status(user: dict = Depends(get_current_user)):
    """Estado actual: git, containers, disco."""
    _require_admin(user)
    results = {}
    for key in ("git_status", "git_log"):
        r = await _run_whitelisted(key, timeout_sec=10)
        results[key] = r.get("output", r.get("error", ""))

    # Docker ps
    try:
        proc = await asyncio.create_subprocess_shell(
            f"docker compose -f {DOCKER_COMPOSE} ps --format 'table {{{{.Name}}}}\\t{{{{.Status}}}}'",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        results["containers"] = out.decode("utf-8", "ignore")
    except Exception as e:
        results["containers"] = f"error: {e}"

    # Disco
    try:
        proc = await asyncio.create_subprocess_shell(
            "df -h /opt | tail -1",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        results["disk"] = out.decode("utf-8", "ignore").strip()
    except Exception as e:
        results["disk"] = f"error: {e}"

    return {"ok": True, "status": results}


@router.post("/analyze")
async def analyze_request(data: AnalyzeIn, user: dict = Depends(get_current_user)):
    """
    Analiza un request en lenguaje natural y genera una propuesta de cambio.
    NO aplica ningún cambio — solo genera la propuesta para revisión.
    """
    _require_admin(user)
    db = _db_ref["db"]

    # Llamar a IA para análisis
    try:
        ai_result = await _analyze_with_ai(data.request)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Error en análisis IA: {e}")

    # Computar diffs para cada cambio propuesto
    changes = ai_result.get("changes", [])
    enriched_changes = []
    for ch in changes:
        rel = ch.get("file", "")
        action = ch.get("action", "modify")
        new_content = ch.get("new_content", "")

        original_content = ""
        if action != "create":
            original_content = _read_source_file(rel)
            if original_content.startswith("ERROR:"):
                original_content = ""

        diff = _compute_diff(original_content, new_content, rel) if new_content else ""
        enriched_changes.append({
            **ch,
            "original_content": original_content[:5000],  # solo primeros 5k para la UI
            "diff": diff,
        })

    pid = f"dp_{uuid.uuid4().hex[:12]}"
    doc = {
        "id": pid,
        "request": data.request,
        "analysis": ai_result.get("analysis", ""),
        "changes": enriched_changes,
        "requires_build": bool(ai_result.get("requires_build", False)),
        "requires_deploy_backend": ai_result.get("requires_deploy_backend", []),
        "requires_restart": ai_result.get("requires_restart", []),
        "risk": ai_result.get("risk", "medium"),
        "risk_detail": ai_result.get("risk_detail", ""),
        "rollback_plan": ai_result.get("rollback_plan", "Restaurar archivos desde checkpoint"),
        "status": "pending",
        "checkpoint_id": None,
        "created_by": user["id"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.devops_proposals.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("/proposals")
async def list_proposals(user: dict = Depends(get_current_user)):
    _require_admin(user)
    db = _db_ref["db"]
    cur = db.devops_proposals.find({}, {"_id": 0, "changes": 0}).sort("created_at", -1).limit(50)
    return {"proposals": [p async for p in cur]}


@router.get("/proposals/{pid}")
async def get_proposal(pid: str, user: dict = Depends(get_current_user)):
    _require_admin(user)
    db = _db_ref["db"]
    p = await db.devops_proposals.find_one({"id": pid}, {"_id": 0})
    if not p:
        raise HTTPException(404, "Propuesta no encontrada")
    return p


@router.post("/proposals/{pid}/approve")
async def approve_proposal(pid: str, user: dict = Depends(get_current_user)):
    """
    Aprueba y ejecuta una propuesta DevOps.
    Secuencia garantizada:
      1. Crear checkpoint (git + file backup)
      2. Escribir archivos modificados en source
      3. Deploy backend si hay cambios .py
      4. Build frontend si requires_build
      5. Deploy frontend si requires_build
      6. Restart servicios indicados
    Si cualquier paso falla, el checkpoint queda disponible para rollback.
    """
    _require_admin(user)
    db = _db_ref["db"]
    p = await db.devops_proposals.find_one({"id": pid}, {"_id": 0})
    if not p:
        raise HTTPException(404, "Propuesta no encontrada")
    if p["status"] != "pending":
        raise HTTPException(400, f"Propuesta ya está '{p['status']}'")

    log: list[dict] = []

    # 1. Crear checkpoint
    checkpoint = await _create_checkpoint(pid, p["request"][:100])
    file_paths = [ch["file"] for ch in p.get("changes", []) if ch.get("file")]
    checkpoint = await _backup_files(checkpoint, file_paths)
    log.append({"step": "checkpoint", "ok": True, "id": checkpoint["id"]})

    await db.devops_proposals.update_one(
        {"id": pid},
        {"$set": {"status": "applying", "checkpoint_id": checkpoint["id"],
                  "approved_by": user["id"],
                  "approved_at": datetime.now(timezone.utc).isoformat()}},
    )

    # 2. Escribir archivos en source
    write_errors = []
    for ch in p.get("changes", []):
        rel = ch.get("file", "")
        new_content = ch.get("new_content", "")
        action = ch.get("action", "modify")
        if not rel or not new_content:
            continue
        clean = re.sub(r"\.\./", "", rel).lstrip("/")
        full_path = (SOURCE_DIR / clean).resolve()
        if not _is_inside_source(full_path):
            write_errors.append(f"path inseguro: {rel}")
            continue
        try:
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(new_content, encoding="utf-8")
            log.append({"step": f"write:{rel}", "ok": True})
        except Exception as e:
            write_errors.append(f"{rel}: {e}")
            log.append({"step": f"write:{rel}", "ok": False, "error": str(e)})

    if write_errors:
        await db.devops_proposals.update_one(
            {"id": pid},
            {"$set": {"status": "failed", "apply_log": log,
                      "apply_error": write_errors,
                      "finished_at": datetime.now(timezone.utc).isoformat()}},
        )
        return {"ok": False, "error": "Errores escribiendo archivos", "details": write_errors,
                "checkpoint_id": checkpoint["id"], "log": log}

    # 3. Deploy backend files si hay .py modificados
    if p.get("requires_deploy_backend"):
        r = await _deploy_backend_files(p["requires_deploy_backend"])
        log.append({"step": "deploy_backend", **r})

    # 4. Build frontend
    if p.get("requires_build"):
        r = await _run_whitelisted("build_frontend", timeout_sec=180)
        log.append({"step": "build_frontend", **r})
        if not r["ok"]:
            await db.devops_proposals.update_one(
                {"id": pid},
                {"$set": {"status": "failed", "apply_log": log,
                          "finished_at": datetime.now(timezone.utc).isoformat()}},
            )
            return {"ok": False, "error": "npm build falló", "checkpoint_id": checkpoint["id"],
                    "log": log, "hint": "Usa el checkpoint para rollback"}

        # 5. Deploy frontend
        r = await _run_whitelisted("deploy_frontend", timeout_sec=30)
        log.append({"step": "deploy_frontend", **r})

    # 6. Restart servicios
    for svc in p.get("requires_restart", []):
        key = f"restart_{svc}"
        if key in ALLOWED_COMMANDS:
            r = await _run_whitelisted(key, timeout_sec=30)
            log.append({"step": f"restart_{svc}", **r})

    await db.devops_proposals.update_one(
        {"id": pid},
        {"$set": {"status": "applied", "apply_log": log,
                  "finished_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"ok": True, "status": "applied", "checkpoint_id": checkpoint["id"], "log": log}


@router.post("/proposals/{pid}/reject")
async def reject_proposal(pid: str, data: RejectIn, user: dict = Depends(get_current_user)):
    _require_admin(user)
    db = _db_ref["db"]
    p = await db.devops_proposals.find_one({"id": pid}, {"_id": 0, "status": 1})
    if not p:
        raise HTTPException(404, "Propuesta no encontrada")
    if p["status"] != "pending":
        raise HTTPException(400, f"Propuesta ya está '{p['status']}'")
    await db.devops_proposals.update_one(
        {"id": pid},
        {"$set": {"status": "rejected", "rejected_by": user["id"],
                  "rejected_reason": data.reason,
                  "rejected_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"ok": True}


@router.get("/checkpoints")
async def list_checkpoints(user: dict = Depends(get_current_user)):
    _require_admin(user)
    db = _db_ref["db"]
    cur = db.devops_checkpoints.find({}, {"_id": 0}).sort("created_at", -1).limit(50)
    return {"checkpoints": [c async for c in cur]}


@router.post("/checkpoints/{cid}/rollback")
async def rollback_checkpoint(cid: str, user: dict = Depends(get_current_user)):
    """
    Restaura el estado de los archivos al momento del checkpoint.
    IMPORTANTE: Solo restaura los archivos que estaban en el backup.
    Después del rollback, el admin debe triggear restart manual si es necesario.
    """
    _require_admin(user)
    db = _db_ref["db"]
    checkpoint = await db.devops_checkpoints.find_one({"id": cid}, {"_id": 0})
    if not checkpoint:
        raise HTTPException(404, "Checkpoint no encontrado")

    result = await _rollback_from_checkpoint(checkpoint)

    # Re-deploy los archivos backend restaurados → docker cp al contenedor
    backend_files = [f for f in checkpoint.get("files_backed_up", []) if f.startswith("backend/")]
    if backend_files:
        deploy_result = await _deploy_backend_files(backend_files)
        result["deploy_backend"] = deploy_result

    # Marcar el checkpoint como usado para rollback
    await db.devops_checkpoints.update_one(
        {"id": cid},
        {"$set": {"rolled_back_at": datetime.now(timezone.utc).isoformat(),
                  "rolled_back_by": user["id"]}},
    )

    # Si se restauraron archivos backend, reiniciar el backend
    if backend_files and result.get("ok"):
        r = await _run_whitelisted("restart_backend", timeout_sec=30)
        result["restart_backend"] = r

    return {
        "ok": result.get("ok", False),
        "checkpoint_id": cid,
        "restored": result.get("restored", []),
        "errors": result.get("errors", []),
        "deploy_backend": result.get("deploy_backend"),
        "restart_backend": result.get("restart_backend"),
        "note": "Si había cambios de frontend, ejecuta build + deploy frontend manualmente desde el panel DevOps.",
    }
