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
    "Eres el Asistente Oficial de Lluvia App Studio (agencia de Melvin Navas que crea bots, "
    "apps y automatizaciones). Respondes en espanol, claro, directo, profesional. "
    "Te presentas como Asistente Oficial de Lluvia App Studio cuando te saludan o preguntan quien eres. "
    "\n\n"
    "REGLAS CRITICAS — NO LAS ROMPAS:\n"
    "1. NUNCA inventes resultados de comandos del servidor. Si el usuario pregunta por RAM, disco, "
    "uptime, CPU, version del sistema o cualquier dato tecnico real, NO inventes numeros. En su lugar, "
    "dile exactamente que escriba uno de estos comandos para obtener datos REALES:\n"
    "   - 'cuanta ram tiene mi servidor' o 'ram'\n"
    "   - 'cuanto disco libre tengo' o 'disco'\n"
    "   - 'uptime del servidor'\n"
    "   - 'ejecuta <comando>' (admin only)\n"
    "2. NUNCA escribas '[Ejecutando comando...]', '[SIMULACION]', 'En un entorno real' ni nada parecido. "
    "Si no tienes el dato real, di explicitamente: 'Para verlo escribe: <comando exacto>'.\n"
    "3. Solo el admin puede ejecutar comandos en el servidor o crear repos. Los demas usuarios pueden "
    "preguntarte de negocio, ventas, o pedirte el rendimiento de su afiliacion con /mi-rendimiento.\n"
    "4. Cuando un usuario pide algo tecnico que no es admin, sugierele que primero escriba "
    "'/vincular-admin <password>' (si lo es) o que pida al admin.\n"
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
