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
import base64
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
    repo: Optional[str] = None      # override: pushear a otro repo distinto al default
    branch: Optional[str] = None    # override: usar otra rama
    auto_create_repo: bool = False  # crear el repo si no existe (con scope repo)


async def do_push(user: dict, app_name: Optional[str] = None,
                  commit_message: Optional[str] = None,
                  repo_override: Optional[str] = None,
                  branch_override: Optional[str] = None,
                  auto_create_repo: bool = False) -> dict:
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
    if not settings or not settings.get("github_token"):
        return {
            "ok": False,
            "needs_setup": True,
            "message": "Necesitas configurar tu GITHUB_TOKEN en Mi cuenta -> Settings antes de hacer push.",
            "settings_url": "/dashboard/settings",
        }

    token = settings["github_token"]
    # Override de repo/branch (push de UNA app a un repo dedicado, sin tocar
    # el default global del usuario). Asi cada app generada puede ir a su
    # propio repo sin sobrescribir las anteriores.
    if repo_override:
        repo = _safe_repo(repo_override)
        if not repo:
            return {"ok": False, "error": "repo_override invalido (formato esperado owner/repo)"}
    else:
        repo = settings.get("github_repo")
    if not repo:
        return {
            "ok": False,
            "needs_setup": True,
            "message": "Necesitas configurar tu repositorio destino en Mi cuenta -> Settings, o pasarlo en la llamada.",
            "settings_url": "/dashboard/settings",
        }
    branch = (branch_override or settings.get("github_branch") or "main").strip() or "main"

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
    # Tambien podemos forzar la creacion via auto_create_repo=True aunque el
    # validation diga not_found (caso: pushear app1 a repo-app1 nuevo).
    if validation.get("repo_access") == "not_found" or (auto_create_repo and validation.get("repo_access") in (None, "not_found")):
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
            # REPO VACIO - bootstrap con Contents API primero, asi luego el
            # flujo normal de blobs/tree/commit funciona. La Git Data API NO
            # acepta blobs en repos sin commits previos.
            bootstrap_readme = base64.b64encode(
                f"# {repo.split('/')[-1]}\n\n"
                f"Repo inicializado por Lluvia App Studio. "
                f"El contenido real llega en el siguiente commit.\n".encode("utf-8")
            ).decode("ascii")
            boot_resp = await cli.put(
                f"{api_base}/contents/README.md",
                json={
                    "message": "init: bootstrap del repo vacio",
                    "content": bootstrap_readme,
                    "branch": branch,
                },
            )
            if boot_resp.status_code not in (200, 201):
                steps.append({"step": "bootstrap_fail", "rc": boot_resp.status_code, "out": boot_resp.text[:200]})
                return {
                    "ok": False, "repo": repo, "repo_url": repo_url, "branch": branch,
                    "app_name": app_name, "commit_message": commit_msg, "steps": steps,
                    "error": f"No pude inicializar el repo vacio: {boot_resp.text[:200]}",
                    "auth_failed": boot_resp.status_code == 401,
                }
            parent_sha = boot_resp.json()["commit"]["sha"]
            base_tree_sha = boot_resp.json()["commit"]["tree"]["sha"]
            steps.append({"step": "bootstrap", "rc": 0, "out": f"Repo inicializado, HEAD={parent_sha[:7]}"})
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
        tree_items: list[dict] = []
        for rel_path, raw in files_to_push:
            content_b64 = base64.b64encode(raw).decode("ascii")
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
    result = await do_push(
        user,
        app_name=data.app_name,
        commit_message=data.commit_message,
        repo_override=data.repo,
        branch_override=data.branch,
        auto_create_repo=bool(data.auto_create_repo),
    )
    if result.get("needs_setup"):
        raise HTTPException(status_code=400, detail=result["message"])
    return result


class PushAppIn(BaseModel):
    """Payload del Push-One-App: empuja UNA app del workspace a UN repo
    dedicado (existente o nuevo). El backend decide si crea el repo o no
    segun el flag create_new. Esto evita que apps generadas se sobreescriban
    entre si en el mismo repo del usuario."""
    app_slug: str = Field(..., min_length=1, max_length=80)
    repo_name: Optional[str] = None       # solo el slug (sin owner/). Si vacio = pedir
    create_new: bool = True                # si True y repo_name no existe, lo crea
    target_owner_repo: Optional[str] = None  # alternativo: owner/repo existente del user (NO crear)
    commit_message: Optional[str] = None
    private: bool = False
    set_as_default: bool = False           # actualizar github_repo en user_settings tambien


@router.post("/github/push-app")
async def my_github_push_app(data: PushAppIn, user: dict = Depends(get_current_user)):
    """Empuja UNA app especifica del workspace a un repo DEDICADO. Si
    create_new=True, se crea el repo bajo el usuario logueado en GitHub.
    Si target_owner_repo viene seteado, lo usa directamente (sin crear)."""
    db = _db_ref["db"]
    settings = await db.user_settings.find_one({"user_id": user["id"]}, {"_id": 0})
    if not settings or not settings.get("github_token"):
        raise HTTPException(
            status_code=400,
            detail="No tenés token de GitHub configurado. Andá a Mi Cuenta → Settings.",
        )
    token = settings["github_token"]

    # Sanity check de la carpeta de la app
    apps_root = _user_apps_dir(user["id"])
    app_dir = os.path.join(apps_root, data.app_slug)
    if not os.path.isdir(app_dir):
        raise HTTPException(
            status_code=404,
            detail=f"La app '{data.app_slug}' no existe en tu workspace. Generá una primero.",
        )

    # Determinar el repo destino
    final_repo: Optional[str] = None
    created_new = False
    if data.target_owner_repo:
        repo = _safe_repo(data.target_owner_repo)
        if not repo:
            raise HTTPException(status_code=400, detail="target_owner_repo invalido (owner/repo)")
        final_repo = repo
    else:
        # Necesitamos el login del usuario para armar owner/repo
        val = await _validate_github_token(token)
        if not val.get("ok"):
            raise HTTPException(status_code=401, detail=val.get("error") or "Token invalido")
        login = val.get("login")
        if not login:
            raise HTTPException(status_code=500, detail="No pude obtener tu username de GitHub.")
        # Sanitizar el nombre propuesto
        raw_name = (data.repo_name or data.app_slug or "").strip()
        name = re.sub(r"[^a-zA-Z0-9_.-]", "-", raw_name).strip("-")
        name = re.sub(r"-+", "-", name)[:80]
        if not name or len(name) < 2:
            raise HTTPException(status_code=400, detail="Nombre de repo invalido.")
        final_repo = f"{login}/{name}"

        # Si create_new, crear el repo (o aceptarlo si ya existe).
        if data.create_new:
            if not val.get("has_repo_scope"):
                raise HTTPException(
                    status_code=403,
                    detail="Tu token no tiene scope 'repo'. Regeneralo en https://github.com/settings/tokens/new",
                )
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
            async with httpx.AsyncClient(timeout=15.0, headers=headers) as cli:
                r_check = await cli.get(f"https://api.github.com/repos/{final_repo}")
                if r_check.status_code == 200:
                    pass  # ya existe - usamos y pusheamos
                elif r_check.status_code == 404:
                    create_resp = await cli.post(
                        "https://api.github.com/user/repos",
                        json={
                            "name": name,
                            "description": f"App '{data.app_slug}' generada por Lluvia App Studio para {user.get('email','user')}.",
                            "private": bool(data.private),
                            "auto_init": False,
                            "has_issues": True,
                            "has_wiki": False,
                            "has_projects": False,
                        },
                    )
                    if create_resp.status_code not in (200, 201):
                        try:
                            err = create_resp.json().get("message") or create_resp.text[:160]
                        except Exception:
                            err = create_resp.text[:160]
                        raise HTTPException(status_code=400, detail=f"No pude crear el repo '{final_repo}': {err}")
                    created_new = True

    # Ejecutar push apuntando a final_repo. Pasamos auto_create_repo=True por las dudas.
    result = await do_push(
        user,
        app_name=data.app_slug,
        commit_message=data.commit_message or f"deploy: {data.app_slug} {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}",
        repo_override=final_repo,
        branch_override="main",
        auto_create_repo=True,
    )
    result["created_new_repo"] = created_new
    result["repo"] = final_repo
    result["repo_url"] = f"https://github.com/{final_repo}"

    # Si el cliente quiere, guardamos este repo como el "default" para futuros push genericos.
    if data.set_as_default and result.get("ok"):
        await db.user_settings.update_one(
            {"user_id": user["id"]},
            {"$set": {"github_repo": final_repo, "github_branch": "main",
                      "updated_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )
        result["default_updated"] = True

    # Generar URL de "1-click deploy to Render" como bonus
    if result.get("ok"):
        result["render_deploy_url"] = f"https://render.com/deploy?repo=https://github.com/{final_repo}"

    return result


class CreateRepoIn(BaseModel):
    name: str
    private: bool = False
    description: Optional[str] = None
    set_as_default: bool = True


@router.post("/github/create-repo")
async def create_my_github_repo(
    data: CreateRepoIn, user: dict = Depends(get_current_user)
):
    """Crea un repo nuevo en GitHub usando el token del usuario. Si el flag
    set_as_default=True, queda guardado en user_settings.github_repo asi el
    proximo push apunta solo. Tomo el slug y lo sanitizo, devolvemos un error
    claro si ya existe o si el token no tiene permisos.
    """
    db = _db_ref["db"]
    settings = await db.user_settings.find_one({"user_id": user["id"]}, {"_id": 0})
    if not settings or not settings.get("github_token"):
        raise HTTPException(
            status_code=400,
            detail="No tenes token de GitHub configurado. Andá a Mi Cuenta -> Settings y pegá tu PAT antes de crear repos.",
        )
    token = settings["github_token"]
    # Validar token primero (rapido + barato)
    val = await _validate_github_token(token, repo=None)
    if not val.get("ok"):
        raise HTTPException(status_code=401, detail=val.get("error") or "Token invalido")
    if not val.get("has_repo_scope"):
        raise HTTPException(
            status_code=403,
            detail="Tu token no tiene scope 'repo'. Regeneralo en https://github.com/settings/tokens/new con esa caja marcada.",
        )

    # Sanitizar el nombre del repo (GitHub: solo alphanumeric, -, _, .)
    raw_name = (data.name or "").strip()
    name = re.sub(r"[^a-zA-Z0-9_.-]", "-", raw_name).strip("-")
    name = re.sub(r"-+", "-", name)[:80]
    if not name or len(name) < 2:
        raise HTTPException(status_code=400, detail="Nombre de repo invalido. Probá con algo tipo 'mi-app-audio'.")

    login = val.get("login")
    if not login:
        raise HTTPException(status_code=500, detail="No pude obtener tu username de GitHub")

    description = (
        data.description
        or f"Repositorio creado por Lluvia App Studio para {user.get('email','user')}."
    )[:240]

    # Pedir creacion del repo a GitHub
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    async with httpx.AsyncClient(timeout=15.0, headers=headers) as cli:
        # Chequeo preventivo: existe ya?
        r_check = await cli.get(f"https://api.github.com/repos/{login}/{name}")
        if r_check.status_code == 200:
            full_name = f"{login}/{name}"
            # Ya existe - solo guardamos como default y devolvemos OK con flag
            if data.set_as_default:
                await db.user_settings.update_one(
                    {"user_id": user["id"]},
                    {"$set": {"github_repo": full_name,
                              "updated_at": datetime.now(timezone.utc).isoformat()}},
                    upsert=True,
                )
            return {
                "ok": True,
                "already_existed": True,
                "repo": full_name,
                "html_url": f"https://github.com/{full_name}",
                "default_branch": r_check.json().get("default_branch", "main"),
                "message": f"El repo '{full_name}' ya existia. Lo dejamos seleccionado como destino default.",
            }

        # Crearlo
        create_resp = await cli.post(
            "https://api.github.com/user/repos",
            json={
                "name": name,
                "description": description,
                "private": bool(data.private),
                "auto_init": False,   # lo inicializa do_push si hace falta
                "has_issues": True,
                "has_wiki": False,
                "has_projects": False,
            },
        )
        if create_resp.status_code not in (200, 201):
            try:
                err_body = create_resp.json()
                gh_msg = err_body.get("message") or str(err_body)
                errors = err_body.get("errors") or []
                if errors:
                    gh_msg += " - " + "; ".join(str(e.get("message", e)) for e in errors)
            except Exception:
                gh_msg = create_resp.text[:200]
            raise HTTPException(
                status_code=400,
                detail=f"GitHub rechazo crear el repo: {gh_msg}",
            )
        body = create_resp.json()

    full_name = body.get("full_name") or f"{login}/{name}"
    html_url = body.get("html_url") or f"https://github.com/{full_name}"

    # Setearlo como default destino si el cliente lo pidio
    if data.set_as_default:
        await db.user_settings.update_one(
            {"user_id": user["id"]},
            {"$set": {
                "github_repo": full_name,
                "github_branch": body.get("default_branch") or "main",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }},
            upsert=True,
        )

    logger.info(f"Repo creado: {full_name} para user {user.get('email')}")
    return {
        "ok": True,
        "already_existed": False,
        "repo": full_name,
        "html_url": html_url,
        "default_branch": body.get("default_branch") or "main",
        "private": bool(body.get("private")),
        "message": f"✅ Repo '{full_name}' creado. Ya esta seleccionado como destino: tu proximo Push lo va a llenar con los archivos.",
    }


@router.get("/github/history")
async def my_push_history(user: dict = Depends(get_current_user)):
    db = _db_ref["db"]
    cur = db.user_github_pushes.find(
        {"user_id": user["id"]},
        {"_id": 0, "steps": 0},  # No mostramos los steps por compactitud
    ).sort("ts", -1).limit(20)
    return {"history": [b async for b in cur]}
