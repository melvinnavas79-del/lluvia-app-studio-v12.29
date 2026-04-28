"""
========================================
MOTOR DE IA (GPT) - CONEXION DIRECTA OPENAI
========================================

Conexion directa a la API de OpenAI usando el SDK oficial.
La API Key se configura en config.py (OPENAI_API_KEY).
"""

import logging
from openai import AsyncOpenAI

import config
import memory

logger = logging.getLogger(__name__)


SYSTEM_MESSAGE = (
    "Eres el Asistente Oficial de Lluvia App Studio, una agencia que crea bots, apps y "
    "automatizaciones para negocios. Respondes claro, directo, profesional y con tono "
    "convincente de ventas. Te presentas como Asistente Oficial de Lluvia App Studio "
    "cuando alguien te saluda o pregunta quien eres. "
    "Tienes acceso tecnico para: crear apps y landings, gestionar GitHub del admin, "
    "ejecutar comandos en el servidor cuando el admin lo ordene, y atender clientes. "
    "Si te piden algo tecnico que requiera permisos de admin y el usuario no lo es, "
    "explica con claridad que solo el admin puede ordenar esa accion."
)


def is_ready() -> bool:
    """Indica si el motor de IA esta listo para responder."""
    return bool(config.OPENAI_API_KEY)


def _client() -> AsyncOpenAI:
    """Crea un cliente de OpenAI con la API Key configurada."""
    return AsyncOpenAI(api_key=config.OPENAI_API_KEY)


def _build_messages(user: str, text: str) -> list:
    """Construye la lista de mensajes incluyendo el historial del usuario."""
    history = memory.get(user)
    messages = [{"role": "system", "content": SYSTEM_MESSAGE}]
    # Recortar historial al limite configurado
    for entry in history[-(memory.MAX_HISTORY * 2):]:
        role = entry.get("role", "user")
        if role not in ("user", "assistant"):
            role = "user"
        messages.append({"role": role, "content": entry.get("content", "")})
    messages.append({"role": "user", "content": text})
    return messages


async def generate(user: str, text: str) -> str:
    """Genera una respuesta de OpenAI con historial del usuario."""
    if not config.OPENAI_API_KEY:
        return (
            "El motor de IA no esta configurado. "
            "Por favor agrega OPENAI_API_KEY en backend/.env"
        )

    try:
        client = _client()
        messages = _build_messages(user, text)

        response = await client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=messages,
        )

        reply = response.choices[0].message.content or ""

        # Guardar en memoria
        memory.save(user, "user", text)
        memory.save(user, "assistant", reply)

        return reply

    except Exception as e:
        logger.error(f"Error generando respuesta IA: {e}")
        return f"Error generando respuesta: {str(e)}"
