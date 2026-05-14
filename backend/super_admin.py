"""
SuperAdmin Module (v11) - Consola del Dueno.

- Bypass total de costos (heredado del flag role='admin' en credits.py)
- Overview cross-user: todos los hilos, todos los usuarios, todos los agentes
- Takeover: el SuperAdmin puede inyectar mensajes como assistant en cualquier sesion
- Push & Backup: dispara git add/commit/push contra el repo configurado en .env
"""

import os
import subprocess
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import get_current_user

logger = logging.getLogger("super_admin")
router = APIRouter(prefix="/super", tags=["super_admin"])

_db_ref: dict = {"db": None}


def set_db(db) -> None:
    _db_ref["db"] = db


def _require_super(user: dict) -> None:
    """SuperAdmin == role admin. En el futuro podriamos agregar is_super_admin flag."""
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Solo SuperAdmin")


@router.get("/overview")
async def overview(user: dict = Depends(get_current_user)):
    """Resumen global: usuarios, sesiones activas, mensajes, oros emitidos."""
    _require_super(user)
    db = _db_ref["db"]
    users_count = await db.users.count_documents({})
    sessions_count = await db.chat_sessions.count_documents({})
    custom_agents = await db.custom_agents.count_documents({})
    appointments = await db.appointments.count_documents({})
    proposals_pending = await db.proposals.count_documents({"status": "pending"})

    # Top 10 sesiones recientes con metadata
    recent = []
    cur = db.chat_sessions.find({}, {"_id": 0, "messages": 0}).sort("updated_at", -1).limit(10)
    async for s in cur:
        # Trae nombre del usuario
        u = await db.users.find_one({"id": s.get("user_id")}, {"_id": 0, "email": 1, "name": 1})
        recent.append({
            **s,
            "user_email": u.get("email") if u else "?",
            "user_name": u.get("name") if u else "?",
        })

    return {
        "users": users_count,
        "sessions": sessions_count,
        "custom_agents": custom_agents,
        "appointments": appointments,
        "proposals_pending": proposals_pending,
        "recent_sessions": recent,
    }


@router.get("/sessions/all")
async def all_sessions(user: dict = Depends(get_current_user)):
    """Lista TODAS las sesiones de TODOS los usuarios (cross-tenant)."""
    _require_super(user)
    db = _db_ref["db"]
    cur = db.chat_sessions.find({}, {"_id": 0, "messages": 0}).sort("updated_at", -1).limit(200)
    out = []
    async for s in cur:
        u = await db.users.find_one({"id": s.get("user_id")}, {"_id": 0, "email": 1})
        out.append({**s, "user_email": u.get("email") if u else "?"})
    return {"sessions": out}


@router.get("/sessions/{session_id}")
async def get_any_session(session_id: str, user: dict = Depends(get_current_user)):
    """Lee CUALQUIER sesion sin importar de quien sea."""
    _require_super(user)
    db = _db_ref["db"]
    doc = await db.chat_sessions.find_one({"id": session_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="sesion no encontrada")
    u = await db.users.find_one({"id": doc.get("user_id")}, {"_id": 0, "email": 1, "name": 1})
    doc["user_email"] = u.get("email") if u else "?"
    doc["user_name"] = u.get("name") if u else "?"
    return doc


class TakeoverIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    as_role: str = "assistant"  # 'assistant' o 'system_note'


@router.post("/sessions/{session_id}/takeover")
async def takeover_message(session_id: str, data: TakeoverIn,
                            user: dict = Depends(get_current_user)):
    """SuperAdmin inyecta un mensaje en cualquier sesion (como agente o nota).
    Quedan marcados con `superadmin_takeover: true` para auditoria."""
    _require_super(user)
    db = _db_ref["db"]
    sess = await db.chat_sessions.find_one({"id": session_id}, {"_id": 0, "agent_id": 1})
    if not sess:
        raise HTTPException(status_code=404, detail="sesion no encontrada")
    now = datetime.now(timezone.utc).isoformat()
    msg = {
        "id": str(uuid.uuid4()),
        "role": data.as_role if data.as_role in ("assistant", "system_note") else "assistant",
        "content": data.text,
        "ts": now,
        "agent_id": sess.get("agent_id"),
        "superadmin_takeover": True,
        "by": user["email"],
    }
    await db.chat_sessions.update_one(
        {"id": session_id},
        {"$push": {"messages": msg},
         "$set": {"updated_at": now, "last_message_preview": data.text[:160]}},
    )
    return {"ok": True, "message": msg}


@router.get("/users")
async def all_users(user: dict = Depends(get_current_user)):
    """Lista de TODOS los usuarios (con balance y stats)."""
    _require_super(user)
    db = _db_ref["db"]
    users = []
    async for u in db.users.find({}, {"_id": 0, "password_hash": 0}):
        cred = await db.credits.find_one({"user_id": u["id"]}, {"_id": 0, "balance": 1, "lifetime_spent": 1})
        u["balance"] = (cred or {}).get("balance", 0)
        u["lifetime_spent"] = (cred or {}).get("lifetime_spent", 0)
        users.append(u)
    return {"users": users}


# ============================================================
# GITHUB PUSH & BACKUP — solo SuperAdmin
# ============================================================
class GithubPushIn(BaseModel):
    commit_message: Optional[str] = None
    branch: Optional[str] = None


@router.post("/github/push")
async def github_push(data: GithubPushIn, user: dict = Depends(get_current_user)):
    """Hace add/commit/push contra el repo configurado en .env.
    Requiere GITHUB_TOKEN + GITHUB_BACKUP_REPO + GITHUB_USER en .env.
    NO expone token al cliente. NO permite que otros usuarios accedan."""
    _require_super(user)
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    repo = os.environ.get("GITHUB_BACKUP_REPO", "").strip()  # formato: owner/repo
    gh_user = os.environ.get("GITHUB_USER", "").strip()
    if not token or not repo:
        raise HTTPException(
            status_code=503,
            detail="GITHUB_TOKEN y GITHUB_BACKUP_REPO requeridos en backend/.env",
        )
    branch = (data.branch or "main").strip()
    commit_msg = data.commit_message or f"backup: SuperAdmin push {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}"
    app_dir = "/app"
    remote_url = f"https://{gh_user or 'x-access-token'}:{token}@github.com/{repo}.git"

    def _run(cmd: list[str], cwd: str = app_dir) -> tuple[int, str]:
        try:
            r = subprocess.run(cmd, cwd=cwd, capture_output=True,
                                text=True, timeout=90)
            out = (r.stdout + r.stderr)[-4000:]
            return r.returncode, out
        except Exception as e:
            return -1, str(e)

    steps = []
    # Asegurar repo git
    _run(["git", "init"])
    _run(["git", "config", "user.email", user.get("email", "admin@lluvia.app")])
    _run(["git", "config", "user.name", "Lluvia SuperAdmin"])

    # Remoto
    rc, out = _run(["git", "remote", "set-url", "origin", remote_url])
    if rc != 0:
        rc, out = _run(["git", "remote", "add", "origin", remote_url])
    steps.append({"step": "remote", "rc": rc, "out": out[-300:]})

    # Add + commit
    rc, out = _run(["git", "add", "-A"])
    steps.append({"step": "add", "rc": rc, "out": out[-300:]})
    rc, out = _run(["git", "commit", "-m", commit_msg])
    steps.append({"step": "commit", "rc": rc, "out": out[-300:]})

    # Push
    rc, out = _run(["git", "push", "-u", "origin", branch, "--force"])
    steps.append({"step": "push", "rc": rc, "out": out[-500:]})

    # Persistir bitacora (sin token)
    await _db_ref["db"].github_backups.insert_one({
        "id": str(uuid.uuid4()),
        "by": user["email"],
        "repo": repo,
        "branch": branch,
        "commit_message": commit_msg,
        "steps": steps,
        "success": steps[-1]["rc"] == 0,
        "ts": datetime.now(timezone.utc).isoformat(),
    })
    return {
        "ok": steps[-1]["rc"] == 0,
        "repo": repo,
        "branch": branch,
        "commit_message": commit_msg,
        "steps": steps,
    }


@router.get("/github/history")
async def github_history(user: dict = Depends(get_current_user)):
    _require_super(user)
    cur = _db_ref["db"].github_backups.find({}, {"_id": 0}).sort("ts", -1).limit(20)
    return {"backups": [b async for b in cur]}
