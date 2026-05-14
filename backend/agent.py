"""
========================================
AGENTE - INTERPRETACION DE COMANDOS
========================================
"""

import logging
import ai
from executor import execute_action
from actions import affiliate_stats
from actions import admin_link
from actions import client_provisioning
import telegram_unified

logger = logging.getLogger(__name__)


# Frases naturales que el usuario agrega al final/inicio del comando.
FILLER_SUFFIXES = [
    " en el servidor", " en mi servidor", " en el server", " en mi server",
    " del servidor", " de mi servidor", " en la maquina", " en la vps",
    " en mi vps", " por favor", " porfavor", " ahora", " ya",
    " gracias", " plis", " please",
]

FILLER_PREFIXES = [
    "el comando ", "comando ", "este comando ", "el ", "este ",
]


def clean_shell_command(cmd: str) -> str:
    """Limpia muletillas naturales del comando antes de ejecutarlo."""
    if not cmd:
        return ""
    cmd = cmd.strip().strip("`").strip("'").strip('"').strip()

    changed = True
    while changed:
        changed = False
        low = cmd.lower()
        for suf in FILLER_SUFFIXES:
            if low.endswith(suf):
                cmd = cmd[: len(cmd) - len(suf)].rstrip()
                changed = True
                break

    changed = True
    while changed:
        changed = False
        low = cmd.lower()
        for pre in FILLER_PREFIXES:
            if low.startswith(pre):
                cmd = cmd[len(pre):].lstrip()
                changed = True
                break

    cmd = cmd.rstrip(".?!,;:").strip()
    return cmd


def interpret(text: str) -> dict:
    if not text:
        return {"action": "business_reply", "raw": text}

    t = text.lower().strip()

    if t.startswith("/vincular-admin ") or t.startswith("vincular-admin ") or t.startswith("vincular admin "):
        parts = text.split(None, 1)
        if len(parts) > 1:
            return {"action": "link_admin", "password": parts[1], "raw": text}
        return {"action": "link_admin", "password": "", "raw": text}

    if t in ("/start", "/inicio", "hola", "buenas", "buenos dias", "buenas tardes", "buenas noches"):
        return {"action": "greeting", "raw": text}

    if t in ("/mi-rendimiento", "/mirendimiento", "/mis-stats", "mi rendimiento", "mis ventas"):
        return {"action": "my_performance", "raw": text}

    # /cliente nuevo
    if t in ("/cliente nuevo", "/cliente-nuevo", "cliente nuevo", "/nuevocliente", "nuevo cliente"):
        return {"action": "client_new", "raw": text}

    if any(k in t for k in ["ram", "memoria"]) and any(k in t for k in ["servidor", "tiene", "cuanta", "muestra", "ver", "dame"]):
        return {"action": "server_cmd", "cmd": "free -h", "raw": text, "label": "Memoria del servidor"}
    if t in ("ram", "memoria", "/ram", "/memoria"):
        return {"action": "server_cmd", "cmd": "free -h", "raw": text, "label": "Memoria del servidor"}

    if any(k in t for k in ["disco", "almacenamiento", "espacio"]) and any(k in t for k in ["servidor", "libre", "tiene", "cuanto", "muestra", "ver", "dame"]):
        return {"action": "server_cmd", "cmd": "df -h /", "raw": text, "label": "Espacio en disco"}
    if t in ("disco", "/disco", "espacio"):
        return {"action": "server_cmd", "cmd": "df -h /", "raw": text, "label": "Espacio en disco"}

    if any(k in t for k in ["uptime", "encendido", "carga del servidor", "tiempo activo"]):
        return {"action": "server_cmd", "cmd": "uptime", "raw": text, "label": "Uptime del servidor"}

    if "cpu" in t and any(k in t for k in ["servidor", "info", "muestra", "cuantos"]):
        return {"action": "server_cmd", "cmd": "nproc && cat /proc/cpuinfo | grep 'model name' | head -1", "raw": text, "label": "CPU"}

    if any(k in t for k in ["uname", "version del sistema", "kernel", "que sistema"]):
        return {"action": "server_cmd", "cmd": "uname -a", "raw": text, "label": "Sistema operativo"}

    # GitHub - patrones amplios en lenguaje natural
    GH_KEYWORDS = ["repo", "repos", "repositorio", "repositorios", "github"]
    GH_LIST_HINTS = ["cuantos", "cuántos", "cuales", "cuáles", "lista", "listar", "ver", "revisar",
                     "muestrame", "muéstrame", "dame", "que tengo", "qué tengo", "tenemos", "mis "]
    GH_CREATE_HINTS = ["crear", "nuevo", "nueva", "crea ", "crea "]

    has_gh = any(k in t for k in GH_KEYWORDS)
    if has_gh:
        if any(h in t for h in GH_CREATE_HINTS):
            return {"action": "github_create", "raw": text}
        if any(h in t for h in GH_LIST_HINTS) or t in ("repos", "/repos", "github"):
            return {"action": "github_list", "raw": text}

    if "crear repo" in t or "crear repositorio" in t or "nuevo repo" in t:
        return {"action": "github_create", "raw": text}
    if "listar repos" in t or "mis repos" in t:
        return {"action": "github_list", "raw": text}

    if "crear app" in t or "crear aplicacion" in t or "crear pagina" in t or "crear web" in t:
        return {"action": "create_app", "raw": text}

    # Comando shell explicito - limpiamos muletillas
    if t.startswith("ejecuta ") or t.startswith("comando ") or t.startswith("/run ") or t.startswith("corre "):
        cmd_raw = text.split(" ", 1)[1] if " " in text else ""
        cmd = clean_shell_command(cmd_raw)
        return {"action": "server_cmd", "cmd": cmd, "raw": text, "label": f"$ {cmd}"}

    if "cliente" in t or "ventas" in t or "vender" in t:
        return {"action": "business_reply", "raw": text}

    if t in ("/help", "ayuda"):
        return {"action": "help", "raw": text}
    if t == "/status" or t == "estado":
        return {"action": "status", "raw": text}

    return {"action": "business_reply", "raw": text}


async def process_command(text: str, user: str = "default") -> str:
    # Si hay un provisioning activo para este chat, todos los mensajes van al state machine
    if client_provisioning.has_session(user):
        # Excepcion: permitir vincular admin / start fuera del flujo si lo intentan
        if text.strip().lower() in ("/cancelar", "cancelar"):
            return client_provisioning.cancel(user)
        # Solo el admin puede manejar el flujo (defensa)
        if not await admin_link.is_admin_chat(user):
            client_provisioning.cancel(user)
            return "Provisioning solo para admins. Sesion cancelada."
        return await client_provisioning.handle(user, text)

    # === MENU UNIFICADO DE AGENTES (v10) ===
    # Si el mensaje es un comando especial del menu (/agente, /agente_xxx,
    # /miagente, /saldo, /recargar), lo manejamos aqui mismo.
    special = await telegram_unified.handle_special_command(text, user)
    if special is not None:
        return special

    intent = interpret(text)
    action = intent["action"]
    logger.info(f"[{user}] intent: {action} | text: {text[:80]}")

    if action == "link_admin":
        return await admin_link.link_admin(user, intent.get("password", ""))

    if action == "my_performance":
        return await affiliate_stats.my_performance(user)

    # /cliente nuevo - iniciar provisioning
    if action == "client_new":
        if not await admin_link.is_admin_chat(user):
            return (
                "Solo el admin puede crear clientes. "
                "Si lo eres, escribe primero: /vincular-admin <password>"
            )
        return client_provisioning.start(user)

    PRIVILEGED = {"server_cmd", "github_create", "github_list", "create_app", "install_radio"}
    if action in PRIVILEGED:
        if not await admin_link.is_admin_chat(user):
            return (
                "Esta accion solo la puede ordenar el administrador de Lluvia App Studio.\n\n"
                "Si tu eres el admin, escribe primero:\n"
                "  /vincular-admin <tu password>\n\n"
                "y vuelve a intentarlo."
            )

    if action == "business_reply":
        is_admin = await admin_link.is_admin_chat(user)
        # Si el usuario tiene un agente especializado seleccionado, usarlo
        # (en lugar del prompt generico de Lluvia)
        try:
            selected = await telegram_unified.get_selected_agent(user)
        except Exception:
            selected = None
        if selected and selected != "arquitecto":
            return await telegram_unified.run_with_selected_agent(text, user, is_admin)
        return await ai.generate(user, text, is_admin=is_admin)

    result = execute_action(intent, user=user)
    label = intent.get("label")
    if label and action == "server_cmd":
        return f"📊 {label}:\n\n{result}"
    return result
