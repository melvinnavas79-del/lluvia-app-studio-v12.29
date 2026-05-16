"""
User Settings & Per-User GitHub Push (v11.2)

Cada cliente registrado puede:
- Guardar su propio GITHUB_TOKEN y repositorio destino
- Apretar boton "Push to GitHub" para empujar SU app generada

Cada usuario tiene su propio espacio: /opt/lluvia/user_apps/{user_id}/
donde el App Builder agent vuelca codigo generado. Ese folder es lo que
se sube al GitHub del usuario, no el codigo base de Melvin.

Endpoints:
  GET  /api/me/settings           -> config del usuario
  PUT  /api/me/settings           -> guardar github_token, repo, etc
  GET  /api/me/apps               -> apps generadas por este usuario
  POST /api/me/github/push        -> empuja user_apps/{user_id} al repo
  GET  /api/me/github/history     -> historial de sus propios pushes
"""

import os
import subprocess
import logging
import uuid
import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import get_current_user

logger = logging.getLogger("user_workspace")
router = APIRouter(prefix="/me", tags=["user_workspace"])

_db_ref: dict = {"db": None}


def set_db(db) -> None:
    _db_ref["db"] = db


def _safe_repo(s: str) -> str:
    """Valida formato owner/repo."""
    s = (s or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+", s):
        return ""
    return s


# ============================================================
# Settings
# ============================================================
class UserSettingsIn(BaseModel):
    github_token: Optional[str] = Field(default=None, max_length=300)
    github_repo: Optional[str] = Field(default=None, max_length=120)
    github_branch: Optional[str] = Field(default="main", max_length=60)
    project_name: Optional[str] = Field(default=None, max_length=80)
    notify_email: Optional[str] = Field(default=None, max_length=120)


@router.get("/settings")
async def get_settings(user: dict = Depends(get_current_user)):
    db = _db_ref["db"]
    doc = await db.user_settings.find_one({"user_id": user["id"]}, {"_id": 0}) or {}
    # NO devolvemos el token completo (seguridad). Solo si esta seteado.
    has_token = bool(doc.get("github_token"))
    safe = {k: v for k, v in doc.items() if k != "github_token"}
    safe["has_github_token"] = has_token
    return safe


@router.put("/settings")
async def put_settings(data: UserSettingsIn, user: dict = Depends(get_current_user)):
    db = _db_ref["db"]
    update = {}
    if data.github_token is not None:
        # Solo guardamos si NO viene vacio (preserva el anterior si lo dejan en blanco)
        if data.github_token.strip():
            update["github_token"] = data.github_token.strip()
    if data.github_repo is not None:
        repo = _safe_repo(data.github_repo)
        if data.github_repo and not repo:
            raise HTTPException(status_code=400, detail="Formato repo invalido (owner/repo)")
        update["github_repo"] = repo
    if data.github_branch is not None:
        update["github_branch"] = (data.github_branch or "main").strip()[:60]
    if data.project_name is not None:
        update["project_name"] = data.project_name.strip()[:80]
    if data.notify_email is not None:
        update["notify_email"] = data.notify_email.strip()[:120]

    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.user_settings.update_one(
        {"user_id": user["id"]},
        {"$set": {"user_id": user["id"], **update}},
        upsert=True,
    )
    return {"ok": True, "saved_fields": list(update.keys())}


# ============================================================
# Apps generadas
# ============================================================
def _user_apps_dir(user_id: str) -> str:
    base = os.environ.get("LLUVIA_HOME", "/app")
    return os.path.join(base, "user_apps", user_id)


@router.get("/apps")
async def list_my_apps(user: dict = Depends(get_current_user)):
    """Lista carpetas generadas por App Builder para este usuario."""
    d = _user_apps_dir(user["id"])
    if not os.path.isdir(d):
        return {"apps": []}
    out = []
    for name in sorted(os.listdir(d)):
        full = os.path.join(d, name)
        if not os.path.isdir(full):
            continue
        try:
            stat = os.stat(full)
            out.append({
                "name": name, "path": full,
                "size_bytes": sum(
                    os.path.getsize(os.path.join(dp, f))
                    for dp, _, files in os.walk(full)
                    for f in files
                ),
                "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            })
        except Exception:
            pass
    return {"apps": out}


# ============================================================
# Push to GitHub (del usuario, a SU repo, con SU token)
# ============================================================
class PushIn(BaseModel):
    commit_message: Optional[str] = None
    app_name: Optional[str] = None  # si es None empuja toda la carpeta user_apps/{user_id}


@router.post("/github/push")
async def my_github_push(data: PushIn, user: dict = Depends(get_current_user)):
    db = _db_ref["db"]
    settings = await db.user_settings.find_one({"user_id": user["id"]}, {"_id": 0})
    if not settings or not settings.get("github_token") or not settings.get("github_repo"):
        raise HTTPException(
            status_code=400,
            detail="Configura tu GITHUB_TOKEN y repositorio en Mi cuenta -> Settings antes de hacer push.",
        )

    token = settings["github_token"]
    repo = settings["github_repo"]
    branch = settings.get("github_branch") or "main"

    # Definir que directorio empujar
    base_dir = _user_apps_dir(user["id"])
    if data.app_name:
        push_dir = os.path.join(base_dir, data.app_name)
        if not os.path.isdir(push_dir):
            raise HTTPException(status_code=404, detail=f"App '{data.app_name}' no existe")
    else:
        push_dir = base_dir
        os.makedirs(push_dir, exist_ok=True)
        # Si esta vacio, agregar README para que git tenga algo
        readme = os.path.join(push_dir, "README.md")
        if not os.listdir(push_dir):
            with open(readme, "w") as f:
                f.write(f"# Mis apps de {user.get('email','')}\n\n"
                        f"Generadas con Lluvia App Studio.\n")

    commit_msg = data.commit_message or f"backup {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}"
    remote_url = f"https://x-access-token:{token}@github.com/{repo}.git"

    def _run(cmd: list[str]) -> tuple[int, str]:
        try:
            r = subprocess.run(cmd, cwd=push_dir, capture_output=True,
                                text=True, timeout=90)
            return r.returncode, (r.stdout + r.stderr)[-2000:]
        except Exception as e:
            return -1, str(e)

    steps = []
    _run(["git", "init"])
    _run(["git", "config", "user.email", user.get("email", "user@lluvia.app")])
    _run(["git", "config", "user.name", user.get("name", "Lluvia User")])

    rc, out = _run(["git", "remote", "set-url", "origin", remote_url])
    if rc != 0:
        rc, out = _run(["git", "remote", "add", "origin", remote_url])
    steps.append({"step": "remote", "rc": rc, "out": out[-200:]})

    rc, out = _run(["git", "add", "-A"])
    steps.append({"step": "add", "rc": rc, "out": out[-200:]})

    rc, out = _run(["git", "commit", "-m", commit_msg])
    steps.append({"step": "commit", "rc": rc, "out": out[-200:]})

    rc, out = _run(["git", "push", "-u", "origin", branch, "--force"])
    steps.append({"step": "push", "rc": rc, "out": out[-300:]})

    success = steps[-1]["rc"] == 0
    # Bitacora (sin token)
    await db.user_github_pushes.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": user["id"], "user_email": user.get("email"),
        "repo": repo, "branch": branch,
        "app_name": data.app_name or "(todo el workspace)",
        "commit_message": commit_msg,
        "success": success,
        "steps": steps,
        "ts": datetime.now(timezone.utc).isoformat(),
    })
    return {
        "ok": success, "repo": repo, "branch": branch,
        "app_name": data.app_name, "steps": steps,
    }


@router.get("/github/history")
async def my_push_history(user: dict = Depends(get_current_user)):
    db = _db_ref["db"]
    cur = db.user_github_pushes.find(
        {"user_id": user["id"]},
        {"_id": 0, "steps": 0},  # No mostramos los steps por compactitud
    ).sort("ts", -1).limit(20)
    return {"history": [b async for b in cur]}
