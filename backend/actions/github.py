"""
========================================
ACCIONES DE GITHUB
========================================

Crear repos, listar repos, leer archivos, buscar codigo.
"""

import re
import base64
import requests
import config


API = "https://api.github.com"


def _headers() -> dict:
    return {
        "Authorization": f"token {config.GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _ready() -> bool:
    return bool(config.GITHUB_TOKEN) and config.GITHUB_TOKEN != "TU_GITHUB"


_user_cache = {"login": None}


def _get_user_login() -> str:
    """Devuelve el login del usuario autenticado (cacheado)."""
    if _user_cache["login"]:
        return _user_cache["login"]
    if not _ready():
        return ""
    try:
        r = requests.get(f"{API}/user", headers=_headers(), timeout=10)
        if r.status_code == 200:
            _user_cache["login"] = r.json().get("login", "")
            return _user_cache["login"]
    except Exception:
        pass
    return config.GITHUB_USER or ""


def create_repo(text: str = "") -> str:
    if not _ready():
        return "GitHub no esta configurado. Agrega GITHUB_TOKEN en .env"

    name = "bot-generated-repo"
    STOPWORDS = {
        "crear", "crea", "nuevo", "nueva", "repo", "repos", "repositorio",
        "repositorios", "github", "llamado", "llamada", "para", "como",
        "favor", "ahora", "por", "que", "una", "uno", "los", "las", "del",
    }
    candidates = []
    for tok in text.split():
        clean = tok.strip(".,;:!?\"'`").strip()
        if not clean or not re.match(r"^[a-zA-Z0-9._-]+$", clean):
            continue
        if clean.lower() in STOPWORDS:
            continue
        if "-" in clean or "_" in clean or len(clean) >= 4:
            candidates.append(clean)
    if candidates:
        name = candidates[-1]

    payload = {
        "name": name,
        "description": "Repositorio creado por el Asistente de Lluvia App Studio",
        "private": False,
        "auto_init": True,
    }
    try:
        r = requests.post(f"{API}/user/repos", headers=_headers(), json=payload, timeout=15)
        if r.status_code in (200, 201):
            data = r.json()
            return f"Repositorio creado: {data.get('html_url', name)}"
        return f"Error GitHub ({r.status_code}): {r.text[:200]}"
    except Exception as e:
        return f"Error conectando con GitHub: {e}"


def list_repos() -> str:
    if not _ready():
        return "GitHub no esta configurado."
    try:
        r = requests.get(f"{API}/user/repos?per_page=20&sort=updated", headers=_headers(), timeout=15)
        if r.status_code != 200:
            return f"Error GitHub ({r.status_code}): {r.text[:200]}"
        repos = r.json()
        if not repos:
            return "No tienes repositorios."
        lines = [f"- {repo['name']}: {repo['html_url']}" for repo in repos[:20]]
        return "Tus repositorios recientes:\n" + "\n".join(lines)
    except Exception as e:
        return f"Error conectando con GitHub: {e}"


# ============================================================
# TOOLS PARA EL AGENTE IA (function calling)
# ============================================================
def tool_list_files(repo: str, path: str = "") -> dict:
    """Lista archivos y carpetas dentro de un repositorio."""
    if not _ready():
        return {"error": "GitHub no configurado"}
    owner = _get_user_login()
    if not owner:
        return {"error": "No pude resolver el owner del token"}
    url = f"{API}/repos/{owner}/{repo}/contents/{path.lstrip('/')}"
    try:
        r = requests.get(url, headers=_headers(), timeout=15)
        if r.status_code == 404:
            return {"error": f"Repo o ruta no encontrada: {owner}/{repo}/{path}"}
        if r.status_code != 200:
            return {"error": f"GitHub {r.status_code}: {r.text[:200]}"}
        items = r.json()
        if isinstance(items, dict):
            items = [items]
        out = []
        for it in items[:200]:
            out.append({
                "name": it.get("name"),
                "type": it.get("type"),
                "size": it.get("size"),
                "path": it.get("path"),
            })
        return {"repo": f"{owner}/{repo}", "path": path or "/", "items": out}
    except Exception as e:
        return {"error": str(e)}


def tool_read_file(repo: str, file_path: str, max_bytes: int = 80000) -> dict:
    """Lee el contenido de un archivo del repo."""
    if not _ready():
        return {"error": "GitHub no configurado"}
    owner = _get_user_login()
    if not owner:
        return {"error": "No pude resolver el owner"}
    url = f"{API}/repos/{owner}/{repo}/contents/{file_path.lstrip('/')}"
    try:
        r = requests.get(url, headers=_headers(), timeout=20)
        if r.status_code == 404:
            return {"error": f"Archivo no encontrado: {owner}/{repo}/{file_path}"}
        if r.status_code != 200:
            return {"error": f"GitHub {r.status_code}: {r.text[:200]}"}
        data = r.json()
        if isinstance(data, list):
            return {"error": f"{file_path} es una carpeta, no un archivo"}
        if data.get("encoding") != "base64":
            return {"error": f"Encoding no soportado: {data.get('encoding')}"}
        try:
            content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        except Exception as e:
            return {"error": f"No es texto decodificable: {e}", "size": data.get("size")}
        truncated = False
        if len(content) > max_bytes:
            content = content[:max_bytes]
            truncated = True
        return {
            "repo": f"{owner}/{repo}",
            "path": file_path,
            "size": data.get("size"),
            "content": content,
            "truncated": truncated,
        }
    except Exception as e:
        return {"error": str(e)}


def tool_search_code(repo: str, query: str) -> dict:
    """Busca codigo o texto dentro de un repositorio."""
    if not _ready():
        return {"error": "GitHub no configurado"}
    owner = _get_user_login()
    if not owner:
        return {"error": "No pude resolver el owner"}
    q = f"{query} repo:{owner}/{repo}"
    try:
        r = requests.get(
            f"{API}/search/code",
            params={"q": q, "per_page": 20},
            headers=_headers(),
            timeout=20,
        )
        if r.status_code != 200:
            return {"error": f"GitHub search {r.status_code}: {r.text[:200]}"}
        data = r.json()
        hits = []
        for it in data.get("items", [])[:20]:
            hits.append({
                "path": it.get("path"),
                "name": it.get("name"),
                "html_url": it.get("html_url"),
            })
        return {"repo": f"{owner}/{repo}", "query": query, "total": data.get("total_count", 0), "hits": hits}
    except Exception as e:
        return {"error": str(e)}


def tool_list_repos_short() -> list:
    """Lista repos del usuario en formato corto para el agente."""
    if not _ready():
        return []
    try:
        r = requests.get(f"{API}/user/repos?per_page=50&sort=updated", headers=_headers(), timeout=15)
        if r.status_code != 200:
            return []
        return [{"name": x["name"], "default_branch": x.get("default_branch", "main"),
                 "description": x.get("description", "")} for x in r.json()]
    except Exception:
        return []
