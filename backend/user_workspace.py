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
    # Sanity check del formato. PATs validos:
    #  - Classic:      ghp_  (40 chars total, comienza con 'ghp_')
    #  - Fine-grained: github_pat_  (mas largo, pero distinto API)
    #  - OAuth:        gho_  / ghu_  / ghs_  / ghr_
    token_clean = token.strip()
    token_prefix = token_clean[:11].lower()
    is_classic = token_prefix.startswith("ghp_")
    is_fine_grained = token_prefix.startswith("github_pat_")
    if not (is_classic or is_fine_grained or token_prefix.startswith(("gho_", "ghu_", "ghs_", "ghr_"))):
        return {
            "ok": False,
            "error": (
                "El token no tiene un formato de Personal Access Token de GitHub valido. "
                "Los Classic empiezan con 'ghp_' y los Fine-grained con 'github_pat_'. "
                "Verifica que copiaste el token completo y sin espacios desde "
                "https://github.com/settings/tokens"
            ),
        }
    if token_clean != token:
        # Limpiamos espacios al inicio/final para el resto de la validacion
        token = token_clean
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    async with httpx.AsyncClient(timeout=10.0) as cli:
        # 1) /user para validar el token
        r = await cli.get("https://api.github.com/user", headers=headers)
        if r.status_code == 401:
            # GitHub a veces incluye un sub-mensaje util en el body
            try:
                gh_msg = r.json().get("message", "")
            except Exception:
                gh_msg = r.text[:120]
            hint = ""
            if "bad credentials" in gh_msg.lower():
                hint = " (causa: token incorrecto, vencido o revocado)"
            elif "expired" in gh_msg.lower():
                hint = " (causa: el token expiro)"
            return {
                "ok": False,
                "error": (
                    f"GitHub rechazo el token con 401{hint}. GitHub dijo: '{gh_msg}'. "
                    "Posibles causas: (a) typo o espacio invisible al copiarlo, "
                    "(b) el token expiro, (c) lo revocaste. Crea uno NUEVO en "
                    "https://github.com/settings/tokens/new tipo Classic con scope 'repo' "
                    "y expiracion al menos 90 dias."
                ),
            }
        if r.status_code == 403:
            return {
                "ok": False,
                "error": (
                    f"GitHub bloqueo el token con 403 (rate limit o token sin permisos). "
                    f"GitHub dijo: '{r.text[:200]}'"
                ),
            }
        if r.status_code >= 400:
            return {"ok": False, "error": f"GitHub respondio {r.status_code}: {r.text[:200]}"}
        login = r.json().get("login")
        scopes = r.headers.get("X-OAuth-Scopes", "")
        # Verificar que tenga scope repo (fine-grained o classic).
        # Fine-grained tokens NO devuelven X-OAuth-Scopes; verificamos otra forma.
        has_repo_scope = "repo" in scopes if scopes else is_fine_grained
        if is_classic and scopes and "repo" not in scopes:
            return {
                "ok": False,
                "login": login,
                "scopes": scopes,
                "has_repo_scope": False,
                "error": (
                    f"El token es valido pero NO tiene el scope 'repo' marcado. "
                    f"Scopes actuales: '{scopes or '(ninguno)'}'. Crea uno nuevo en "
                    f"https://github.com/settings/tokens/new MARCANDO la casilla grande 'repo'."
                ),
            }
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
    # PUSH LOCK: candado de exportacion. Si el saldo del usuario esta por
    # debajo del threshold configurable, no puede llevarse el codigo a
    # GitHub. Admin bypasea el candado siempre. Asi el visitor que viene
    # del demo puede CONSTRUIR la app y ver la preview, pero solo puede
    # EXPORTAR si paga oros. La cifra la maneja el admin desde su panel.
    if user.get("role") != "admin":
        try:
            import pricing as pricing_mod
            import credits as credits_mod
            threshold = await pricing_mod.get_min_balance_for_export()
            balance_doc = await db.credits.find_one({"user_id": user["id"]}, {"_id": 0, "balance": 1})
            balance = int((balance_doc or {}).get("balance", 0))
            if balance < threshold:
                return {
                    "ok": False,
                    "export_locked": True,
                    "balance": balance,
                    "required": threshold,
                    "missing": threshold - balance,
                    "message": (
                        f"Has creado tu app con éxito. Para exportar el código fuente "
                        f"completo a tu GitHub y activar el backend para producción, "
                        f"adquiere un paquete de oros. Saldo actual: {balance} oros · "
                        f"Necesitas al menos {threshold} oros para desbloquear la exportación."
                    ),
                    "recharge_url": "/#/recharge",
                }
        except Exception as e:
            logger.warning(f"Push-lock check skipped por error: {e}")
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
                f"{repo}. Verifica que eres owner o que el token tiene scope 'repo'."
            ),
            "help_url": "https://github.com/settings/tokens/new?scopes=repo",
        }
    # Si el repo no existe, lo creamos automaticamente (UX: el cliente no
    # tiene que ir a github.com manualmente). Requiere scope 'repo'.
    if validation.get("repo_access") == "not_found":
        try:
            owner_repo = repo.split("/", 1)
            if len(owner_repo) == 2 and validation.get("has_repo_scope"):
                async with httpx.AsyncClient(timeout=15.0) as cli:
                    # Si el owner es el propio login del token, usar /user/repos.
                    # Si es una org, usar /orgs/{org}/repos.
                    headers = {
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    }
                    owner, reponame = owner_repo
                    if owner.lower() == (validation.get("login") or "").lower():
                        create_resp = await cli.post(
                            "https://api.github.com/user/repos",
                            headers=headers,
                            json={"name": reponame, "private": False,
                                  "description": f"Generado por Lluvia App Studio · workspace de {user.get('email','')}"},
                        )
                    else:
                        create_resp = await cli.post(
                            f"https://api.github.com/orgs/{owner}/repos",
                            headers=headers,
                            json={"name": reponame, "private": False,
                                  "description": f"Generado por Lluvia App Studio · workspace de {user.get('email','')}"},
                        )
                    if create_resp.status_code not in (200, 201):
                        return {
                            "ok": False, "auth_failed": True,
                            "error": (
                                f"El repo '{repo}' no existe y no pude crearlo automaticamente: "
                                f"{create_resp.status_code} {create_resp.text[:160]}. "
                                f"Crealo a mano en https://github.com/new (nombre exacto: {reponame})."
                            ),
                            "help_url": f"https://github.com/new?name={reponame}",
                        }
                    logger.info(f"Repo {repo} creado automaticamente para {user.get('email')}")
        except Exception as e:
            return {
                "ok": False, "auth_failed": True,
                "error": f"Error creando el repo {repo}: {e}",
                "help_url": "https://github.com/new",
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
    repo_url = f"https://github.com/{repo}"

    # Estrategia: usar la GitHub REST API directamente (NO binario git).
    # Asi funciona en cualquier contenedor (incluyendo el de produccion de
    # Emergent que NO trae git instalado). Ademas es mas rapido para repos
    # chicos (<100 archivos) que es el caso de las apps de App Builder Pro.
    #
    # Flujo:
    #  1. Listar todos los archivos locales del push_dir.
    #  2. Obtener el HEAD del branch (o crearlo si no existe).
    #  3. Crear un blob por cada archivo (PUT /repos/.../git/blobs).
    #  4. Crear un tree con todos los blobs (POST /repos/.../git/trees).
    #  5. Crear un commit apuntando al tree (POST /repos/.../git/commits).
    #  6. Actualizar la ref del branch (PATCH /repos/.../git/refs/heads/branch).
    steps: list[dict] = []
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    api_base = f"https://api.github.com/repos/{repo}"

    # Recolectar archivos respetando .gitignore basico
    SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv",
                 ".next", "dist", "build", ".DS_Store"}
    SKIP_EXTS = {".pyc", ".pyo", ".log", ".db", ".db-journal"}
    MAX_FILE_BYTES = 1_500_000  # 1.5 MB hard cap por archivo (limite api blobs)

    files_to_push: list[tuple[str, bytes]] = []
    for root, dirs, files in os.walk(push_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fname in files:
            if fname in {".DS_Store"}:
                continue
            if any(fname.endswith(ext) for ext in SKIP_EXTS):
                continue
            full = os.path.join(root, fname)
            rel = os.path.relpath(full, push_dir).replace(os.sep, "/")
            try:
                size = os.path.getsize(full)
                if size > MAX_FILE_BYTES:
                    steps.append({"step": "skip_large", "out": f"{rel} ({size} bytes)"})
                    continue
                with open(full, "rb") as fh:
                    files_to_push.append((rel, fh.read()))
            except Exception as e:
                steps.append({"step": "read_error", "out": f"{rel}: {e}"})

    if not files_to_push:
        return {
            "ok": False,
            "error": "No hay archivos para pushear en tu workspace. Genera una app primero.",
            "repo": repo, "branch": branch,
        }

    steps.append({"step": "collect", "rc": 0, "out": f"{len(files_to_push)} archivos a subir"})

    async with httpx.AsyncClient(timeout=30.0, headers=headers) as cli:
        # 1) Obtener SHA del HEAD del branch (puede no existir si el repo
        # esta vacio o si la rama es nueva).
        ref_resp = await cli.get(f"{api_base}/git/refs/heads/{branch}")
        parent_sha: Optional[str] = None
        base_tree_sha: Optional[str] = None
        if ref_resp.status_code == 200:
            parent_sha = ref_resp.json()["object"]["sha"]
            commit_resp = await cli.get(f"{api_base}/git/commits/{parent_sha}")
            if commit_resp.status_code == 200:
                base_tree_sha = commit_resp.json().get("tree", {}).get("sha")
            steps.append({"step": "ref_existing", "rc": 0, "out": f"HEAD={parent_sha[:7]}"})
        elif ref_resp.status_code == 404:
            # Rama nueva - tenemos que crear el primer commit "huerfano"
            steps.append({"step": "ref_new", "rc": 0, "out": f"Rama '{branch}' es nueva"})
        elif ref_resp.status_code == 409:
            # Repo vacio
            steps.append({"step": "ref_empty_repo", "rc": 0, "out": "Repo vacio, inicializando"})
        else:
            steps.append({"step": "ref_error", "rc": ref_resp.status_code, "out": ref_resp.text[:200]})
            return {
                "ok": False, "repo": repo, "repo_url": repo_url, "branch": branch,
                "app_name": app_name, "commit_message": commit_msg, "steps": steps,
                "error": f"No pude leer la rama '{branch}' del repo: HTTP {ref_resp.status_code}",
                "auth_failed": ref_resp.status_code == 401,
            }

        # 2) Crear blobs (en paralelo seria mejor, pero serial es mas seguro
        # para no saturar la API)
        import base64 as _b64
        tree_items: list[dict] = []
        for rel_path, raw in files_to_push:
            content_b64 = _b64.b64encode(raw).decode("ascii")
            blob_resp = await cli.post(
                f"{api_base}/git/blobs",
                json={"content": content_b64, "encoding": "base64"},
            )
            if blob_resp.status_code not in (200, 201):
                steps.append({"step": "blob_fail", "rc": blob_resp.status_code,
                              "out": f"{rel_path}: {blob_resp.text[:150]}"})
                return {
                    "ok": False, "repo": repo, "repo_url": repo_url, "branch": branch,
                    "app_name": app_name, "commit_message": commit_msg, "steps": steps,
                    "error": f"GitHub rechazo subir '{rel_path}': {blob_resp.text[:200]}",
                    "auth_failed": blob_resp.status_code == 401,
                }
            tree_items.append({
                "path": rel_path,
                "mode": "100644",
                "type": "blob",
                "sha": blob_resp.json()["sha"],
            })
        steps.append({"step": "blobs", "rc": 0, "out": f"{len(tree_items)} blobs creados"})

        # 3) Crear tree
        tree_body: dict = {"tree": tree_items}
        if base_tree_sha:
            # Reemplazo total (no merge) usando un tree NUEVO desde cero
            # (no pasamos base_tree porque queremos que el push reemplace 100%
            # como hacia git push --force antes).
            pass
        tree_resp = await cli.post(f"{api_base}/git/trees", json=tree_body)
        if tree_resp.status_code not in (200, 201):
            steps.append({"step": "tree_fail", "rc": tree_resp.status_code, "out": tree_resp.text[:200]})
            return {
                "ok": False, "repo": repo, "repo_url": repo_url, "branch": branch,
                "app_name": app_name, "commit_message": commit_msg, "steps": steps,
                "error": f"Crear tree fallo: {tree_resp.text[:200]}",
                "auth_failed": tree_resp.status_code == 401,
            }
        tree_sha = tree_resp.json()["sha"]
        steps.append({"step": "tree", "rc": 0, "out": f"tree={tree_sha[:7]}"})

        # 4) Crear commit
        commit_body: dict = {
            "message": commit_msg,
            "tree": tree_sha,
            "author": {
                "name": user.get("name") or "Lluvia User",
                "email": user.get("email") or "user@lluvia.app",
                "date": datetime.now(timezone.utc).isoformat(),
            },
        }
        if parent_sha:
            commit_body["parents"] = [parent_sha]
        commit_resp = await cli.post(f"{api_base}/git/commits", json=commit_body)
        if commit_resp.status_code not in (200, 201):
            steps.append({"step": "commit_fail", "rc": commit_resp.status_code, "out": commit_resp.text[:200]})
            return {
                "ok": False, "repo": repo, "repo_url": repo_url, "branch": branch,
                "app_name": app_name, "commit_message": commit_msg, "steps": steps,
                "error": f"Crear commit fallo: {commit_resp.text[:200]}",
                "auth_failed": commit_resp.status_code == 401,
            }
        commit_sha = commit_resp.json()["sha"]
        steps.append({"step": "commit", "rc": 0, "out": f"commit={commit_sha[:7]}"})

        # 5) Actualizar/crear ref del branch
        if parent_sha:
            # Rama existe - actualizar
            ref_update = await cli.patch(
                f"{api_base}/git/refs/heads/{branch}",
                json={"sha": commit_sha, "force": True},
            )
        else:
            # Rama nueva - crear
            ref_update = await cli.post(
                f"{api_base}/git/refs",
                json={"ref": f"refs/heads/{branch}", "sha": commit_sha},
            )
        if ref_update.status_code not in (200, 201):
            steps.append({"step": "ref_update_fail", "rc": ref_update.status_code, "out": ref_update.text[:200]})
            return {
                "ok": False, "repo": repo, "repo_url": repo_url, "branch": branch,
                "app_name": app_name, "commit_message": commit_msg, "steps": steps,
                "error": f"Actualizar branch fallo: {ref_update.text[:200]}",
                "auth_failed": ref_update.status_code == 401,
            }
        steps.append({"step": "push", "rc": 0, "out": f"Branch '{branch}' apuntando a {commit_sha[:7]}"})

    success = True
    user_facing_error = None

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
