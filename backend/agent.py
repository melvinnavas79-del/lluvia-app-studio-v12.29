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

logger = logging.getLogger(__name__)


def interpret(text: str) -> dict:
    if not text:
        return {"action": "business_reply", "raw": text}

    t = text.lower().strip()

    # Vincular admin: /vincular-admin <password> (acepta variantes)
    if t.startswith("/vincular-admin ") or t.startswith("vincular-admin ") or t.startswith("vincular admin "):
        # Extraer todo lo que viene despues de la primera palabra
        parts = text.split(None, 1)
        if len(parts) > 1:
            return {"action": "link_admin", "password": parts[1], "raw": text}
        return {"action": "link_admin", "password": "", "raw": text}

    # Saludo / inicio
    if t in ("/start", "/inicio", "hola", "buenas", "buenos dias", "buenas tardes", "buenas noches"):
        return {"action": "greeting", "raw": text}

    # Afiliado: su rendimiento
    if t in ("/mi-rendimiento", "/mirendimiento", "/mis-stats", "mi rendimiento", "mis ventas"):
        return {"action": "my_performance", "raw": text}

    # === COMANDOS DE SERVIDOR EN LENGUAJE NATURAL ===
    # RAM / memoria
    if any(k in t for k in ["ram", "memoria"]) and any(k in t for k in ["servidor", "tiene", "cuanta", "muestra", "ver", "dame"]):
        return {"action": "server_cmd", "cmd": "free -h", "raw": text, "label": "Memoria del servidor"}
    if t in ("ram", "memoria", "/ram", "/memoria"):
        return {"action": "server_cmd", "cmd": "free -h", "raw": text, "label": "Memoria del servidor"}

    # Disco
    if any(k in t for k in ["disco", "almacenamiento", "espacio"]) and any(k in t for k in ["servidor", "libre", "tiene", "cuanto", "muestra", "ver", "dame"]):
        return {"action": "server_cmd", "cmd": "df -h /", "raw": text, "label": "Espacio en disco"}
    if t in ("disco", "/disco", "espacio"):
        return {"action": "server_cmd", "cmd": "df -h /", "raw": text, "label": "Espacio en disco"}

    # Uptime / carga
    if any(k in t for k in ["uptime", "encendido", "carga del servidor", "tiempo activo"]):
        return {"action": "server_cmd", "cmd": "uptime", "raw": text, "label": "Uptime del servidor"}

    # CPU
    if "cpu" in t and any(k in t for k in ["servidor", "info", "muestra", "cuantos"]):
        return {"action": "server_cmd", "cmd": "nproc && cat /proc/cpuinfo | grep 'model name' | head -1", "raw": text, "label": "CPU"}

    # Sistema
    if any(k in t for k in ["uname", "version del sistema", "kernel", "que sistema"]):
        return {"action": "server_cmd", "cmd": "uname -a", "raw": text, "label": "Sistema operativo"}

    # GitHub
    if "crear repo" in t or "crear repositorio" in t or "nuevo repo" in t:
        return {"action": "github_create", "raw": text}

    if "listar repos" in t or "mis repos" in t:
        return {"action": "github_list", "raw": text}

    # Apps
    if "crear app" in t or "crear aplicacion" in t or "crear pagina" in t or "crear web" in t:
        return {"action": "create_app", "raw": text}

    # Comando shell explicito
    if t.startswith("ejecuta ") or t.startswith("comando ") or t.startswith("/run "):
        cmd = text.split(" ", 1)[1] if " " in text else ""
        return {"action": "server_cmd", "cmd": cmd, "raw": text, "label": f"$ {cmd}"}

    # Negocio
    if "cliente" in t or "ventas" in t or "vender" in t:
        return {"action": "business_reply", "raw": text}

    # Comandos basicos
    if t in ("/help", "ayuda"):
        return {"action": "help", "raw": text}

    if t == "/status" or t == "estado":
        return {"action": "status", "raw": text}

    return {"action": "business_reply", "raw": text}


async def process_command(text: str, user: str = "default") -> str:
    intent = interpret(text)
    action = intent["action"]
    logger.info(f"[{user}] intent: {action} | text: {text[:80]}")

    # /vincular-admin: no requiere ser admin (auto-registro con password)
    if action == "link_admin":
        return await admin_link.link_admin(user, intent.get("password", ""))

    # /mi-rendimiento
    if action == "my_performance":
        return await affiliate_stats.my_performance(user)

    # Comandos sensibles requieren admin
    PRIVILEGED = {"server_cmd", "github_create", "github_list", "create_app", "install_radio"}
    if action in PRIVILEGED:
        if not await admin_link.is_admin_chat(user):
            return (
                "Esta accion solo la puede ordenar el administrador de Lluvia App Studio.\n\n"
                "Si tu eres el admin, escribe primero:\n"
                "  /vincular-admin <tu password>\n\n"
                "y vuelve a intentarlo."
            )

    # business_reply -> IA
    if action == "business_reply":
        return await ai.generate(user, text)

    # Resto: ejecucion sincrona
    result = execute_action(intent, user=user)
    # Si el intent traia un label, lo prependemos para que el output sea claro
    label = intent.get("label")
    if label and action == "server_cmd":
        return f"📊 {label}:\n\n{result}"
    return result
