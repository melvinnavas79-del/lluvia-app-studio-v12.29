"""
========================================
ACCIONES DE GITHUB
========================================

Crear repos, listar repos, etc.
"""

import re
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


def create_repo(text: str = "") -> str:
    """Crea un repositorio en GitHub. Extrae el nombre del texto si existe."""
    if not _ready():
        return "GitHub no esta configurado. Agrega GITHUB_TOKEN en .env"

    # Extraer nombre del repo del texto: "crear repo mi-proyecto"
    name = "bot-generated-repo"
    match = re.search(r"(?:crear|nuevo)\s+repo(?:sitorio)?\s+([a-zA-Z0-9._-]+)", text, re.IGNORECASE)
    if match:
        name = match.group(1)

    payload = {
        "name": name,
        "description": "Repositorio creado por el bot multiplataforma",
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
    """Lista los repositorios del usuario."""
    if not _ready():
        return "GitHub no esta configurado. Agrega GITHUB_TOKEN en .env"

    try:
        r = requests.get(f"{API}/user/repos?per_page=10&sort=updated", headers=_headers(), timeout=15)
        if r.status_code != 200:
            return f"Error GitHub ({r.status_code}): {r.text[:200]}"
        repos = r.json()
        if not repos:
            return "No tienes repositorios."
        lines = [f"- {repo['name']}: {repo['html_url']}" for repo in repos[:10]]
        return "Tus repositorios recientes:\n" + "\n".join(lines)
    except Exception as e:
        return f"Error conectando con GitHub: {e}"
