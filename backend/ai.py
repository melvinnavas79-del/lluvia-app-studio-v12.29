"""
========================================
MOTOR DE IA (GPT) - CONEXION DIRECTA OPENAI
========================================
"""

import logging
from openai import AsyncOpenAI

import config
import memory

logger = logging.getLogger(__name__)


SYSTEM_MESSAGE_BASE = (
    "Eres el Asistente Oficial de Lluvia App Studio (agencia de Melvin Navas que crea bots, "
    "apps y automatizaciones). Respondes en espanol, claro, directo, profesional. "
    "Te presentas como Asistente Oficial de Lluvia App Studio cuando te saludan o preguntan quien eres. "
    "\n\n"
    "REGLAS CRITICAS — NUNCA LAS ROMPAS:\n"
    "1. NUNCA inventes resultados de comandos, listas de archivos, repositorios, RAM, disco, "
    "uptime, CPU, version del sistema, ni ningun dato real del servidor o de GitHub. "
    "Si no tienes el dato real, dile al usuario que ESCRIBA el comando exacto:\n"
    "   - Para repositorios: 'listar repos'\n"
    "   - Para crear un repo: 'crear repo <nombre>'\n"
    "   - Para RAM: 'cuanta ram tiene mi servidor'\n"
    "   - Para disco: 'cuanto disco libre tengo'\n"
    "   - Para uptime: 'uptime del servidor'\n"
    "   - Para crear app: 'crear app <nombre>'\n"
    "   - Para comandos shell arbitrarios: 'ejecuta <comando>'\n"
    "2. NUNCA escribas '[Ejecutando comando...]', '[SIMULACION]', 'En un entorno real' ni nada parecido.\n"
    "3. NUNCA respondas con discursos de seguridad inventados como 'solo el admin puede'. "
    "El backend hace el control de permisos automaticamente; tu solo guia al usuario al comando correcto.\n"
)

ADMIN_HINT = (
    "\nNOTA DE CONTEXTO: Este usuario YA esta vinculado como administrador autorizado. "
    "Cuando te pida algo tecnico (repos, RAM, comandos), responde con CONFIANZA y "
    "dile el comando exacto que debe escribir para obtener el resultado real. "
    "NO le digas que contacte al admin: el ES el admin."
)

NON_ADMIN_HINT = (
    "\nNOTA DE CONTEXTO: Este usuario NO esta vinculado como admin. "
    "Si te pide algo tecnico (repos, comandos shell), dile amablemente que primero "
    "escriba '/vincular-admin <password>' si lo es, o que pida la accion al admin."
)


def is_ready() -> bool:
    return bool(config.OPENAI_API_KEY)


def _client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=config.OPENAI_API_KEY)


def _build_messages(user: str, text: str, is_admin: bool = False) -> list:
    history = memory.get(user)
    system = SYSTEM_MESSAGE_BASE + (ADMIN_HINT if is_admin else NON_ADMIN_HINT)
    messages = [{"role": "system", "content": system}]
    for entry in history[-(memory.MAX_HISTORY * 2):]:
        role = entry.get("role", "user")
        if role not in ("user", "assistant"):
            role = "user"
        messages.append({"role": role, "content": entry.get("content", "")})
    messages.append({"role": "user", "content": text})
    return messages


async def generate(user: str, text: str, is_admin: bool = False) -> str:
    if not config.OPENAI_API_KEY:
        return (
            "El motor de IA no esta configurado. "
            "Por favor agrega OPENAI_API_KEY en backend/.env"
        )
    try:
        client = _client()
        messages = _build_messages(user, text, is_admin=is_admin)

        response = await client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=messages,
        )
        reply = response.choices[0].message.content or ""

        memory.save(user, "user", text)
        memory.save(user, "assistant", reply)
        return reply

    except Exception as e:
        logger.error(f"Error generando respuesta IA: {e}")
        return f"Error generando respuesta: {str(e)}"
