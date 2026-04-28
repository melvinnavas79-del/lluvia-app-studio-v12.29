"""
========================================
MOTOR DE IA (GPT)
========================================

Conexion al modelo LLM via emergentintegrations.
Soporta OpenAI directo (con OPENAI_API_KEY) o Emergent LLM Key universal.
"""

import logging
from emergentintegrations.llm.chat import LlmChat, UserMessage

import config
import memory

logger = logging.getLogger(__name__)


SYSTEM_MESSAGE = (
    "Eres un asistente experto en ventas, automatizacion y negocios online. "
    "Respondes claro, directo y convincente. "
    "Tambien puedes ejecutar comandos: crear apps, crear repos en GitHub, "
    "instalar software en el servidor, y responder a clientes. "
    "Cuando un usuario pida una accion tecnica, confirma de forma profesional."
)


def _get_api_key() -> str:
    """Devuelve la API key disponible (OpenAI personal o Emergent LLM Key)."""
    if config.OPENAI_API_KEY:
        return config.OPENAI_API_KEY
    if config.EMERGENT_LLM_KEY:
        return config.EMERGENT_LLM_KEY
    return ""


def is_ready() -> bool:
    """Indica si el motor de IA esta listo para responder."""
    return bool(_get_api_key())


async def generate(user: str, text: str) -> str:
    """Genera una respuesta del LLM con historial del usuario."""
    api_key = _get_api_key()
    if not api_key:
        return (
            "El motor de IA no esta configurado. "
            "Por favor agrega OPENAI_API_KEY o EMERGENT_LLM_KEY en el archivo .env"
        )

    try:
        # Crear nueva instancia por cada conversacion (recomendado por playbook)
        chat = LlmChat(
            api_key=api_key,
            session_id=f"bot-user-{user}",
            system_message=SYSTEM_MESSAGE,
        ).with_model(config.LLM_PROVIDER, config.LLM_MODEL)

        # Inyectar historial reciente como contexto
        history_text = memory.get_text_history(user, limit=8)
        full_prompt = (
            f"Historial reciente:\n{history_text}\n\n"
            f"Usuario actual dice: {text}"
        )

        user_message = UserMessage(text=full_prompt)
        response = await chat.send_message(user_message)

        # Guardar en memoria
        memory.save(user, "user", text)
        memory.save(user, "assistant", response)

        return response

    except Exception as e:
        logger.error(f"Error generando respuesta IA: {e}")
        return f"Error generando respuesta: {str(e)}"
