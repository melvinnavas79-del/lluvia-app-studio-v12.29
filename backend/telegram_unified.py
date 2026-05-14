"""
Telegram - menu unificado de agentes especializados.
Comandos:
  /agente -> menu inline con los 7+ agentes
  /agente_<id> -> selecciona ese agente para el chat actual
  /saldo -> consulta oros
  /recargar -> link a la tienda PayPal
Cualquier mensaje normal va al agente seleccionado (default: arquitecto).
"""

import logging
from typing import Optional

import agents_catalog
import credits as credits_mod
from openai import AsyncOpenAI
import config

logger = logging.getLogger("tg_unified")

_db_ref: dict = {"db": None}


def set_db(db) -> None:
    _db_ref["db"] = db


async def get_selected_agent(user_key: str) -> str:
    db = _db_ref.get("db")
    if not db:
        return "arquitecto"
    doc = await db.tg_user_pref.find_one({"user": user_key}, {"_id": 0, "agent_id": 1})
    return (doc or {}).get("agent_id") or "arquitecto"


async def set_selected_agent(user_key: str, agent_id: str) -> None:
    db = _db_ref.get("db")
    if not db:
        return
    await db.tg_user_pref.update_one({"user": user_key},
                                     {"$set": {"agent_id": agent_id}}, upsert=True)


def build_agent_menu_text() -> str:
    """Texto + lista de comandos para el menu de agentes."""
    builtins = agents_catalog.list_agents()
    lines = ["*Agentes disponibles:*\n"]
    for a in builtins:
        lines.append(f"{a['emoji']} *{a['name']}* — _{a['tagline']}_\n"
                     f"   /agente\\_{a['id']}")
    lines.append("\nTu agente actual: usa /miagente para verlo.")
    return "\n".join(lines)


async def handle_special_command(text: str, user_key: str) -> Optional[str]:
    """Si el text es un comando especial de menu, devuelve la respuesta. Si no, None."""
    t = text.strip()
    low = t.lower()
    if low in ("/agente", "/agentes", "/menu", "/start"):
        return build_agent_menu_text()
    if low == "/miagente":
        aid = await get_selected_agent(user_key)
        ag = agents_catalog.get_agent(aid)
        if ag:
            return f"Tu agente actual es {ag['emoji']} *{ag['name']}* ({ag['tagline']})"
        return "No tienes agente seleccionado. Usa /agente para elegir."
    if low.startswith("/agente_"):
        aid = low.replace("/agente_", "").strip()
        ag = agents_catalog.get_agent(aid)
        if not ag:
            return f"Agente desconocido: `{aid}`. Usa /agente para ver la lista."
        await set_selected_agent(user_key, aid)
        return f"Seleccionado: {ag['emoji']} *{ag['name']}*\n_{ag['tagline']}_\n\nAhora escribe y te respondera."
    if low == "/saldo":
        bal = await credits_mod.get_balance(user_key)
        return f"Saldo actual: *{bal} oros* ⚜"
    if low == "/recargar":
        return ("Recarga oros en el panel web:\n"
                "https://ai-bot-cost-calc.preview.emergentagent.com\n"
                "Tab Boss Console -> boton '+ Recargar'.")
    return None


async def run_with_selected_agent(text: str, user_key: str, is_admin: bool) -> str:
    """Ejecuta `text` con el agente seleccionado del usuario."""
    aid = await get_selected_agent(user_key)
    agent = agents_catalog.get_agent(aid)
    if not agent:
        return "Agente invalido. Usa /agente para elegir."
    if not config.OPENAI_API_KEY:
        return "OPENAI_API_KEY no configurada en backend."
    # Cobrar 1 oro (admin gratis vive en credits.charge)
    if not await credits_mod.charge(user_key, agents_catalog.COST_CHAT_MESSAGE,
                                     f"telegram_chat:{aid}"):
        return "Saldo insuficiente. Usa /recargar."
    client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
    try:
        resp = await client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=[
                {"role": "system", "content": agent["system"]},
                {"role": "user", "content": text},
            ],
            temperature=0.3,
            max_tokens=600,
        )
        return resp.choices[0].message.content or ""
    except Exception as e:
        logger.exception(f"OpenAI fallo: {e}")
        return f"Error: {str(e)[:200]}"
