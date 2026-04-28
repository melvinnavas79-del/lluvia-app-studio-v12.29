"""
========================================
PROVISIONING - /cliente nuevo desde Telegram
========================================

State machine que recolecta datos paso a paso y luego ejecuta
setup-cliente.sh con LLUVIA_NI=1 para desplegar el cliente.
"""

import os
import re
import json
import asyncio
import subprocess
from pathlib import Path
from typing import Optional

# Sesiones activas en memoria: {chat_id: {"step": int, "data": {}}}
_sessions: dict = {}

SCRIPT_PATH = os.environ.get(
    "LLUVIA_SETUP_SCRIPT",
    str(Path(__file__).parent.parent.parent / "scripts" / "setup-cliente.sh"),
)

# Pasos del flujo
STEPS = [
    {
        "key": "display",
        "ask": "1/6 - Como se llama el cliente? (ej: Acme Corp)",
        "validate": lambda v: bool(v.strip()) and len(v) <= 80,
        "error": "Nombre invalido. Intenta de nuevo.",
    },
    {
        "key": "logo",
        "ask": "2/6 - URL del logo del cliente (https://...) o escribe 'omitir' si no tiene aun",
        "validate": lambda v: v.lower() == "omitir" or v.startswith("http"),
        "transform": lambda v: "" if v.lower() == "omitir" else v.strip(),
        "error": "Debe ser una URL https o 'omitir'.",
    },
    {
        "key": "primary",
        "ask": "3/6 - Color primario en hex (#RRGGBB) - ej: #5fb4ff (lluvia)",
        "validate": lambda v: bool(re.match(r"^#[0-9a-fA-F]{6}$", v.strip())),
        "transform": lambda v: v.strip().lower(),
        "error": "Color invalido. Formato: #RRGGBB (ej: #5fb4ff)",
    },
    {
        "key": "accent",
        "ask": "4/6 - Color de acento en hex (#RRGGBB) - ej: #5fdbc4",
        "validate": lambda v: bool(re.match(r"^#[0-9a-fA-F]{6}$", v.strip())),
        "transform": lambda v: v.strip().lower(),
        "error": "Color invalido. Formato: #RRGGBB",
    },
    {
        "key": "email",
        "ask": "5/6 - Email del admin del cliente",
        "validate": lambda v: "@" in v and "." in v,
        "transform": lambda v: v.strip().lower(),
        "error": "Email invalido.",
    },
    {
        "key": "confirm",
        "ask": None,  # Se construye dinamicamente
        "validate": lambda v: v.lower().strip() in ("si", "sí", "yes", "y", "no", "n", "cancelar"),
        "error": "Responde 'si' para confirmar o 'no' para cancelar.",
    },
]


def _summary(data: dict) -> str:
    return (
        "6/6 - Resumen para confirmar:\n\n"
        f"  Cliente:   {data['display']}\n"
        f"  Slug:      {_slug(data['display'])}\n"
        f"  URL:       https://{_slug(data['display'])}.{os.environ.get('LLUVIA_ROOT_DOMAIN', 'lluvia.app')}\n"
        f"  Logo:      {data['logo'] or '(sin logo)'}\n"
        f"  Primario:  {data['primary']}\n"
        f"  Acento:    {data['accent']}\n"
        f"  Email:     {data['email']}\n\n"
        "Confirmas el despliegue? (si / no)"
    )


def _slug(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")[:30]


def has_session(chat_id: str) -> bool:
    return str(chat_id) in _sessions


def cancel(chat_id: str) -> str:
    _sessions.pop(str(chat_id), None)
    return "Provisioning cancelado."


def start(chat_id: str) -> str:
    chat_id = str(chat_id)
    _sessions[chat_id] = {"step": 0, "data": {}}
    return (
        "Vamos a desplegar un cliente nuevo. "
        "Te voy a pedir 5 datos. Puedes escribir 'cancelar' en cualquier momento.\n\n"
        + STEPS[0]["ask"]
    )


async def handle(chat_id: str, text: str) -> str:
    chat_id = str(chat_id)
    if text.strip().lower() in ("cancelar", "/cancelar", "cancel"):
        return cancel(chat_id)

    sess = _sessions.get(chat_id)
    if not sess:
        return "No hay provisioning activo. Inicia con: /cliente nuevo"

    step_idx = sess["step"]
    if step_idx >= len(STEPS):
        return "Provisioning ya finalizado."

    step = STEPS[step_idx]

    # Validar
    if not step["validate"](text):
        return step["error"] + "\n\n" + (step["ask"] or _summary(sess["data"]))

    # Caso especial: confirmacion final
    if step["key"] == "confirm":
        ans = text.lower().strip()
        if ans in ("no", "n", "cancelar"):
            return cancel(chat_id)
        # Confirmado -> ejecutar
        result = await _run_script(sess["data"])
        _sessions.pop(chat_id, None)
        return result

    # Guardar valor (con transform si existe)
    value = step.get("transform", lambda v: v.strip())(text)
    sess["data"][step["key"]] = value
    sess["step"] += 1

    # Siguiente prompt (o resumen)
    next_step = STEPS[sess["step"]]
    if next_step["key"] == "confirm":
        return _summary(sess["data"])
    return next_step["ask"]


async def quick_provision(display_name: str, admin_email: str = "", app_type: str = "default") -> str:
    """
    Aprovisionamiento de 1 disparo - asume stack Lluvia, sin preguntas.
    Usado por la tool `provision_client_quick` del bot.
    """
    if not display_name or not display_name.strip():
        return "Falta el nombre del cliente."
    display = display_name.strip()
    slug = _slug(display)
    if not slug:
        return f"No pude generar slug a partir de '{display}'."
    root = os.environ.get("LLUVIA_ROOT_DOMAIN", "lluvia.app")
    email = (admin_email or "").strip().lower() or f"admin@{slug}.{root}"
    if "@" not in email:
        email = f"admin@{slug}.{root}"
    data = {
        "display": display,
        "logo": "",
        "primary": "#5fb4ff",
        "accent": "#5fdbc4",
        "email": email,
    }
    return await _run_script(data)


async def _run_script(data: dict) -> str:
    """Ejecuta setup-cliente.sh con los datos recolectados."""
    if not Path(SCRIPT_PATH).exists():
        return f"Script no encontrado en {SCRIPT_PATH}"

    env = os.environ.copy()
    env["LLUVIA_NI"] = "1"
    env["LLUVIA_DISPLAY"] = data["display"]
    env["LLUVIA_SLUG"] = _slug(data["display"])
    env["LLUVIA_PRODUCT"] = data["display"]
    env["LLUVIA_TAGLINE"] = "Tu agencia inteligente de bots e IA"
    env["LLUVIA_LOGO"] = data.get("logo") or ""
    env["LLUVIA_PRIMARY"] = data["primary"]
    env["LLUVIA_ACCENT"] = data["accent"]
    env["LLUVIA_BG"] = env.get("LLUVIA_BG", "#0a1220")
    env["LLUVIA_TEXTC"] = env.get("LLUVIA_TEXTC", "#e7eef8")
    env["LLUVIA_EMAIL"] = data["email"]
    # Password vacia -> autogenera

    try:
        proc = await asyncio.create_subprocess_exec(
            "bash", SCRIPT_PATH,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
        except asyncio.TimeoutError:
            proc.kill()
            return "Timeout: el script tardo mas de 5 minutos. Revisa logs en el VPS."

        out = stdout.decode("utf-8", errors="replace")
        err = stderr.decode("utf-8", errors="replace")

        # Extraer JSON del output
        m = re.search(r"LLUVIA_RESULT_JSON_BEGIN\s*(.+?)\s*LLUVIA_RESULT_JSON_END", out, re.DOTALL)
        if not m:
            tail = (out + "\n" + err).strip()[-1500:]
            return f"Script ejecutado pero no encontre el resumen JSON. Output:\n\n{tail}"

        result = json.loads(m.group(1).strip())

        dry_run_note = ""
        if result.get("dry_run") == "1":
            dry_run_note = (
                "\n\nMODO DRY-RUN: archivos generados pero Docker no se levanto "
                "(falta Docker en este host).\n"
                f"Archivos en: {result.get('client_dir')}\n"
                "Cuando ejecutes esto en tu VPS con Docker, el cliente quedara "
                "completamente operativo en esa misma URL."
            )

        return (
            "✅ Cliente desplegado!\n\n"
            f"  Producto:  {result['product_name']}\n"
            f"  URL:       {result['url']}\n"
            f"  Admin:     {result['admin_email']}\n"
            f"  Password:  {result['admin_password']}\n"
            f"  Slug:      {result['slug']}\n"
            + dry_run_note
        )
    except Exception as e:
        return f"Error ejecutando el script: {e}"
