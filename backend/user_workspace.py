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

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import get_current_user

logger = logging.getLogger("user_workspace")
router = APIRouter(prefix="/me", tags=["user_workspace"])

_db_ref: dict = {"db": None}


def set_db(db) -> None:
    _db_ref["db"] = db


async def _validate_github_token(token: str, repo: Optional[str] = None) -> dict:
    """Pre-valida que el token de GitHub funcione consultando la API REST.
    Retorna {ok, login, scopes, repo_access, error} sin hacer git push real.
    Asi evitamos cobrarle al cliente 9 oros por un push que va a fallar."""
    if not token or len(token) < 10:
        return {"ok": False, "error": "Token vacio o invalido (muy corto)."}
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    async with httpx.AsyncClient(timeout=10.0) as cli:
        # 1) /user para validar el token
        r = await cli.get("https://api.github.com/user", headers=headers)
        if r.status_code == 401:
            return {
                "ok": False,
                "error": (
                    "Token rechazado por GitHub. Crealo nuevo en "
                    "https://github.com/settings/tokens/new con scope 'repo' "
                    "y pegalo en Mi Cuenta → GITHUB_TOKEN."
                ),
            }
        if r.status_code >= 400:
            return {"ok": False, "error": f"GitHub respondio {r.status_code}: {r.text[:200]}"}
        login = r.json().get("login")
        scopes = r.headers.get("X-OAuth-Scopes", "")
        # Verificar que tenga scope repo (fine-grained o classic)
        has_repo_scope = "repo" in scopes
        # 2) Si dieron repo, verificar acceso de escritura
        repo_access = None
        if repo:
            r2 = await cli.get(f"https://api.github.com/repos/{repo}", headers=headers)
            if r2.status_code == 404:
                # Puede ser repo nuevo a crear automaticamente
                repo_access = "not_found"
            elif r2.status_code == 200:
                perms = r2.json().get("permissions", {})
                if perms.get("push") or perms.get("admin"):
                    repo_access = "writable"
                else:
                    repo_access = "read_only"
            else:
                repo_access = f"error_{r2.status_code}"
        return {
            "ok": True,
            "login": login,
            "scopes": scopes,
            "has_repo_scope": has_repo_scope,
            "repo_access": repo_access,
        }


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


async def do_push(user: dict, app_name: Optional[str] = None,
                  commit_message: Optional[str] = None) -> dict:
    """Funcion reusable: ejecuta el git push para el user. Usada tanto por
    el endpoint /me/github/push como por la tool push_to_my_github del chat.
    Devuelve dict con ok/repo/branch/url/steps. Si el user no tiene token
    o repo configurados devuelve ok=False con 'needs_setup': True (no lanza
    HTTPException, asi la tool puede sugerir la accion al cliente)."""
    db = _db_ref["db"]
    settings = await db.user_settings.find_one({"user_id": user["id"]}, {"_id": 0})
    if not settings or not settings.get("github_token") or not settings.get("github_repo"):
        return {
            "ok": False,
            "needs_setup": True,
            "message": "Necesitas configurar tu GITHUB_TOKEN y repositorio en Mi cuenta -> Settings antes de hacer push.",
            "settings_url": "/dashboard/settings",
        }

    token = settings["github_token"]
    repo = settings["github_repo"]
    branch = settings.get("github_branch") or "main"

    # PRE-VALIDACION: probar el token con la API de GitHub antes de gastar
    # ciclos de git. Si el token esta mal, devolvemos error claro al cliente
    # SIN cobrarle (la tool de oros refunda al ver ok=False con auth_failed).
    try:
        validation = await _validate_github_token(token, repo)
    except Exception as e:
        validation = {"ok": False, "error": f"No pude contactar a GitHub: {e}"}
    if not validation["ok"]:
        return {
            "ok": False,
            "auth_failed": True,
            "error": validation["error"],
            "help_url": "https://github.com/settings/tokens/new?scopes=repo&description=Lluvia%20App%20Studio",
        }
    if validation.get("repo_access") == "read_only":
        return {
            "ok": False,
            "auth_failed": True,
            "error": (
                f"El token funciona pero NO tiene permisos de escritura sobre "
                f"{repo}. Verifica que sos owner o que el token tiene scope 'repo'."
            ),
            "help_url": "https://github.com/settings/tokens/new?scopes=repo",
        }

    # Definir que directorio empujar
    base_dir = _user_apps_dir(user["id"])
    if app_name:
        push_dir = os.path.join(base_dir, app_name)
        if not os.path.isdir(push_dir):
            return {"ok": False, "error": f"App '{app_name}' no existe en tu workspace"}
    else:
        push_dir = base_dir
        os.makedirs(push_dir, exist_ok=True)
        # Si esta vacio, agregar README para que git tenga algo
        readme = os.path.join(push_dir, "README.md")
        if not os.listdir(push_dir):
            with open(readme, "w") as f:
                f.write(f"# Mis apps de {user.get('email','')}\n\n"
                        f"Generadas con Lluvia App Studio.\n")

    commit_msg = commit_message or f"backup {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}"
    remote_url = f"https://x-access-token:{token}@github.com/{repo}.git"
    # Mascara para nunca loggear el token en los steps que se persisten en mongo
    def _mask(s: str) -> str:
        if not s:
            return s
        return s.replace(token, "***").replace(remote_url, f"https://x-access-token:***@github.com/{repo}.git")

    def _run(cmd: list[str]) -> tuple[int, str]:
        try:
            r = subprocess.run(cmd, cwd=push_dir, capture_output=True,
                                text=True, timeout=90)
            return r.returncode, (r.stdout + r.stderr)[-2000:]
        except Exception as e:
            return -1, str(e)

    steps = []
    _run(["git", "init"])
    # Forzar el nombre de la rama local que va a coincidir con la rama destino.
    _run(["git", "checkout", "-B", branch])
    _run(["git", "config", "user.email", user.get("email", "user@lluvia.app")])
    _run(["git", "config", "user.name", user.get("name", "Lluvia User")])

    rc, out = _run(["git", "remote", "set-url", "origin", remote_url])
    if rc != 0:
        rc, out = _run(["git", "remote", "add", "origin", remote_url])
    steps.append({"step": "remote", "rc": rc, "out": _mask(out)[-200:]})

    rc, out = _run(["git", "add", "-A"])
    steps.append({"step": "add", "rc": rc, "out": _mask(out)[-200:]})

    rc, out = _run(["git", "commit", "-m", commit_msg])
    steps.append({"step": "commit", "rc": rc, "out": _mask(out)[-200:]})

    _run(["git", "branch", "-M", branch])
    rc, out = _run(["git", "push", "-u", "origin", branch, "--force"])
    steps.append({"step": "push", "rc": rc, "out": _mask(out)[-300:]})

    success = steps[-1]["rc"] == 0
    repo_url = f"https://github.com/{repo}"

    # Si el push fallo, traducir el error de git a algo claro en español
    user_facing_error = None
    if not success:
        last_out = steps[-1]["out"]
        if "Invalid username or token" in last_out or "Password authentication" in last_out:
            user_facing_error = (
                "GitHub rechazó tu token. Pasos:\n"
                "1) Andá a https://github.com/settings/tokens/new\n"
                "2) Tildá el scope 'repo' (completo)\n"
                "3) Generá el token, copialo (empieza con ghp_ o github_pat_)\n"
                "4) Pegalo en Mi Cuenta → GITHUB_TOKEN\n"
                "5) Tocá 'Guardar configuración' y reintentá el push."
            )
        elif "could not read Username" in last_out or "remote: Repository not found" in last_out:
            user_facing_error = (
                f"El repo '{repo}' no existe o tu token no lo ve. "
                "Verificá que el nombre sea owner/repo correcto y que sea público o que tu token tenga acceso."
            )
        elif "failed to push" in last_out or "rejected" in last_out:
            user_facing_error = (
                f"GitHub rechazó el push (puede ser por protección de rama o conflicto). "
                f"Detalle: {last_out[-200:]}"
            )

    # Bitacora (sin token)
    await db.user_github_pushes.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": user["id"], "user_email": user.get("email"),
        "repo": repo, "branch": branch,
        "app_name": app_name or "(todo el workspace)",
        "commit_message": commit_msg,
        "success": success,
        "steps": steps,
        "ts": datetime.now(timezone.utc).isoformat(),
    })

    return {
        "ok": success, "repo": repo, "repo_url": repo_url,
        "branch": branch, "app_name": app_name, "commit_message": commit_msg,
        "steps": steps,
        "auth_failed": (not success and user_facing_error and "rechazó tu token" in user_facing_error),
        "error": user_facing_error,
    }


@router.post("/github/validate")
async def validate_my_github(user: dict = Depends(get_current_user)):
    """Valida que el token de GitHub del usuario funcione SIN cobrar oros
    ni hacer push. Devuelve {ok, login, repo_access, error}."""
    db = _db_ref["db"]
    settings = await db.user_settings.find_one({"user_id": user["id"]}, {"_id": 0})
    if not settings or not settings.get("github_token"):
        raise HTTPException(status_code=400, detail="No tenés token configurado")
    try:
        result = await _validate_github_token(
            settings["github_token"], settings.get("github_repo"),
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error validando: {e}")


@router.post("/github/push")
async def my_github_push(data: PushIn, user: dict = Depends(get_current_user)):
    result = await do_push(user, app_name=data.app_name, commit_message=data.commit_message)
    if result.get("needs_setup"):
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@router.get("/github/history")
async def my_push_history(user: dict = Depends(get_current_user)):
    db = _db_ref["db"]
    cur = db.user_github_pushes.find(
        {"user_id": user["id"]},
        {"_id": 0, "steps": 0},  # No mostramos los steps por compactitud
    ).sort("ts", -1).limit(20)
    return {"history": [b async for b in cur]}
