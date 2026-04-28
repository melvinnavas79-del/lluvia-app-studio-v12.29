"""
========================================
AGENTE - INTERPRETACION DE COMANDOS
========================================

Decide que accion tomar segun el texto del usuario.
"""

import os
import logging
import ai
from executor import execute_action
from actions import affiliate_stats

logger = logging.getLogger(__name__)


def is_admin_chat(user: str) -> bool:
    """True si el chat_id pertenece a un admin autorizado (env ADMIN_TELEGRAM_CHAT_IDS)."""
    raw = os.environ.get("ADMIN_TELEGRAM_CHAT_IDS", "")
    ids = [x.strip() for x in raw.split(",") if x.strip()]
    return str(user) in ids


def interpret(text: str) -> dict:
    """Interpreta el texto del usuario y devuelve la accion a ejecutar."""
    if not text:
        return {"action": "business_reply", "raw": text}

    t = text.lower().strip()

    # Saludo / inicio
    if t in ("/start", "/inicio", "hola", "buenas", "buenos dias", "buenas tardes", "buenas noches"):
        return {"action": "greeting", "raw": text}

    # Afiliado: su rendimiento
    if t in ("/mi-rendimiento", "/mirendimiento", "/mis-stats", "mi rendimiento", "mis ventas"):
        return {"action": "my_performance", "raw": text}

    # GitHub
    if "crear repo" in t or "crear repositorio" in t or "nuevo repo" in t:
        return {"action": "github_create", "raw": text}

    if "listar repos" in t or "mis repos" in t:
        return {"action": "github_list", "raw": text}

    # Apps / Web
    if "crear app" in t or "crear aplicacion" in t or "crear pagina" in t or "crear web" in t:
        return {"action": "create_app", "raw": text}

    # Servidor
    if "instalar radio" in t or "radio online" in t:
        return {"action": "install_radio", "raw": text}

    if t.startswith("ejecuta ") or t.startswith("comando ") or t.startswith("/run "):
        # Extraer el comando real
        cmd = text.split(" ", 1)[1] if " " in text else ""
        return {"action": "server_cmd", "cmd": cmd, "raw": text}

    # Redes sociales / negocio
    if "publicar" in t or "post en" in t or "redes sociales" in t:
        return {"action": "social_post", "raw": text}

    if "cliente" in t or "ventas" in t or "vender" in t:
        return {"action": "business_reply", "raw": text}

    # Comandos del bot
    if t in ("/help", "ayuda"):
        return {"action": "help", "raw": text}

    if t == "/status" or t == "estado":
        return {"action": "status", "raw": text}

    return {"action": "business_reply", "raw": text}


async def process_command(text: str, user: str = "default") -> str:
    """Procesa un mensaje del usuario: interpreta + ejecuta."""
    intent = interpret(text)
    action = intent["action"]
    logger.info(f"[{user}] intent: {action} | text: {text[:80]}")

    # /mi-rendimiento: requiere DB
    if action == "my_performance":
        return await affiliate_stats.my_performance(user)

    # Comandos sensibles requieren admin
    PRIVILEGED = {"server_cmd", "github_create", "github_list", "create_app", "install_radio"}
    if action in PRIVILEGED and not is_admin_chat(user):
        return (
            "Este comando solo lo puede usar el administrador de Lluvia App Studio. "
            "Si tu eres el admin, agrega tu chat_id a ADMIN_TELEGRAM_CHAT_IDS en backend/.env."
        )

    # Las respuestas de negocio van por IA con historial
    if action == "business_reply":
        return await ai.generate(user, text)

    # El resto son acciones tecnicas
    return execute_action(intent, user=user)
