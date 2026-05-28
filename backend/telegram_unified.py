"""
Telegram - menu unificado de agentes especializados.
Comandos:
  /agente -> menu inline con los 7+ agentes
  /agente_<id> -> selecciona ese agente para el chat actual
  /miagente -> ver agente actual
  /saldo -> consulta oros (saldo de la cuenta WEB si esta vinculada)
  /recargar -> link a la tienda PayPal
  /vincular <codigo> -> conecta este chat_id a una cuenta web
  /desvincular -> rompe el vinculo
Cualquier mensaje normal va al agente seleccionado (default: arquitecto).
Si el chat esta vinculado a una cuenta web, usa los oros + tools de esa cuenta.
"""

import logging
import secrets
import uuid
from datetime import datetime, timezone
from typing import Optional

import agents_catalog
import credits as credits_mod
import llm_router
import config

logger = logging.getLogger("tg_unified")

_db_ref: dict = {"db": None}


def set_db(db) -> None:
    _db_ref["db"] = db


async def get_linked_user(chat_id: str) -> Optional[dict]:
    """Si este chat_id de Telegram esta vinculado a una cuenta web,
    devuelve el doc de user. Si no, None."""
    db = _db_ref.get("db")
    if db is None:
        return None
    link = await db.tg_links.find_one({"chat_id": str(chat_id)}, {"_id": 0})
    if not link:
        return None
    return await db.users.find_one({"id": link["user_id"]}, {"_id": 0})


async def get_selected_agent(user_key: str) -> str:
    db = _db_ref.get("db")
    if db is None:
        return "arquitecto"
    doc = await db.tg_user_pref.find_one({"user": user_key}, {"_id": 0, "agent_id": 1})
    return (doc or {}).get("agent_id") or "arquitecto"


async def set_selected_agent(user_key: str, agent_id: str) -> None:
    db = _db_ref.get("db")
    if db is None:
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
    lines.append("\n_Vincula tu cuenta web con_ `/vincular <codigo>`")
    return "\n".join(lines)


async def handle_special_command(text: str, user_key: str) -> Optional[str]:
    """Si el text es un comando especial, devuelve la respuesta. Si no, None.
    user_key aqui es el chat_id de Telegram."""
    t = text.strip()
    low = t.lower()
    db = _db_ref.get("db")

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
        linked = await get_linked_user(user_key)
        if linked:
            bal = await credits_mod.get_balance(linked["id"])
            return (f"Saldo de tu cuenta web ({linked.get('email','')}): "
                    f"*{bal} oros* ⚜")
        bal = await credits_mod.get_balance(user_key)
        return f"Saldo actual: *{bal} oros* ⚜\n\n_Vincula tu cuenta web con_ `/vincular <codigo>` _para usar tus oros._"
    if low == "/recargar":
        return ("Recarga oros en el panel web:\n"
                "https://ai-bot-cost-calc.preview.emergentagent.com\n"
                "Tab Boss Console -> boton '+ Recargar'.")

    # /vincular <codigo>
    if low.startswith("/vincular"):
        parts = t.split()
        if len(parts) < 2:
            return ("Uso: `/vincular <codigo>`\n\nGenera tu codigo en la web: "
                    "panel → Mi Cuenta → 'Vincular Telegram'.")
        code = parts[1].strip()
        if db is None:
            return "DB no lista."
        link_req = await db.tg_link_codes.find_one({"code": code}, {"_id": 0})
        if not link_req:
            return "Codigo invalido o expirado. Genera uno nuevo en la web."
        exp = link_req.get("expires_at", "")
        if exp and exp < datetime.now(timezone.utc).isoformat():
            await db.tg_link_codes.delete_one({"code": code})
            return "Codigo expirado. Genera uno nuevo en la web."
        # Vincular
        await db.tg_links.update_one(
            {"chat_id": str(user_key)},
            {"$set": {
                "chat_id": str(user_key),
                "user_id": link_req["user_id"],
                "linked_at": datetime.now(timezone.utc).isoformat(),
            }},
            upsert=True,
        )
        await db.tg_link_codes.delete_one({"code": code})
        u = await db.users.find_one({"id": link_req["user_id"]}, {"_id": 0, "email": 1})
        return (f"✓ Vinculado a *{(u or {}).get('email','tu cuenta')}*\n\n"
                f"Ahora cada mensaje descuenta de tus oros web y los agentes "
                f"pueden hacer push a tu GitHub, agendar citas reales, etc.")

    if low == "/desvincular":
        if db is not None:
            await db.tg_links.delete_one({"chat_id": str(user_key)})
        return "Vinculacion eliminada. Tus oros web ya no se descuentan desde Telegram."

    return None


async def run_with_selected_agent(text: str, user_key: str, is_admin: bool) -> str:
    """Ejecuta `text` con el agente seleccionado del usuario.
    Si el chat_id esta vinculado a una cuenta web, redirige al console.py
    (con tools + cobros + history). Si no, modo simple sin tools."""
    aid = await get_selected_agent(user_key)
    agent = agents_catalog.get_agent(aid)
    if not agent:
        return "Agente invalido. Usa /agente para elegir."
    if not config.OPENAI_API_KEY:
        return "OPENAI_API_KEY no configurada en backend."

    # Si esta vinculado, delegar a console.py (con tools)
    linked_user = await get_linked_user(user_key)
    if linked_user:
        return await _run_via_console(text, linked_user, aid)

    # Modo simple (no vinculado) - cobra al chat_id, sin tools
    if not await credits_mod.charge(user_key, agents_catalog.COST_CHAT_MESSAGE,
                                     f"telegram_chat:{aid}"):
        return ("Saldo insuficiente. Usa /recargar o vincula tu cuenta web "
                "con /vincular <codigo>.")
    client, _tg_model = llm_router.get_client("low")
    now_utc = datetime.now(timezone.utc)
    weekdays_es = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
    date_ctx = (f"\n\n[FECHA ACTUAL] {now_utc.strftime('%Y-%m-%d %H:%M')} UTC "
                f"({weekdays_es[now_utc.weekday()]}). Usa esta fecha como 'hoy'.")
    try:
        resp = await client.chat.completions.create(
            model=_tg_model,
            messages=[
                {"role": "system", "content": agent["system"] + date_ctx},
                {"role": "user", "content": text},
            ],
            temperature=0.3,
            max_tokens=600,
        )
        return resp.choices[0].message.content or ""
    except Exception as e:
        logger.exception(f"OpenAI fallo: {e}")
        return f"Error: {str(e)[:200]}"


async def _run_via_console(text: str, user: dict, agent_id: str) -> str:
    """Crea/reusa una session de console.py para este user+agent y
    procesa el mensaje (asi obtiene tools + cobros + history)."""
    db = _db_ref["db"]
    sess = await db.chat_sessions.find_one(
        {"user_id": user["id"], "agent_id": agent_id, "from_telegram": True},
        {"_id": 0}, sort=[("created_at", -1)],
    )
    if not sess:
        sess_id = str(uuid.uuid4())
        sess = {
            "id": sess_id, "user_id": user["id"], "agent_id": agent_id,
            "title": "Telegram", "from_telegram": True,
            "messages": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.console_sessions.insert_one(sess.copy())
    try:
        import console as console_mod
        result = await console_mod._send_message(sess["id"], text, user)
        am = result.get("assistant_message") or {}
        out = am.get("content") or "(sin respuesta)"
        # Si hubo tool calls relevantes, añadir resumen
        tc = am.get("tool_calls") or []
        for c in tc:
            if c.get("name") == "push_to_my_github":
                try:
                    import json as _json
                    r = _json.loads(c.get("result_preview") or "{}")
                    if r.get("ok"):
                        out += f"\n\n📦 Push exitoso: https://github.com/{r.get('repo')}"
                    elif r.get("needs_setup"):
                        out += "\n\n⚠ Configura tu GitHub token en la web (Mi Cuenta → Settings)."
                except Exception:
                    pass
        return out
    except Exception as e:
        logger.exception(f"console fallo: {e}")
        return f"Error al procesar: {str(e)[:200]}"


# ============================================================
# Endpoints publicos (web) para que el usuario genere su codigo
# ============================================================
from fastapi import APIRouter, Depends
from auth import get_current_user
router_link = APIRouter(prefix="/me/telegram", tags=["telegram-link"])


@router_link.post("/code")
async def generate_link_code(user: dict = Depends(get_current_user)):
    """Genera un codigo de 6 digitos (valido 15 min) para que el usuario lo
    pegue en Telegram con /vincular <codigo>."""
    db = _db_ref["db"]
    code = secrets.token_hex(3).upper()  # 6 chars hex
    from datetime import timedelta
    await db.tg_link_codes.delete_many({"user_id": user["id"]})
    await db.tg_link_codes.insert_one({
        "code": code,
        "user_id": user["id"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
    })
    return {"code": code, "expires_in_minutes": 15,
            "instructions": f"En Telegram, abre tu bot y envia: /vincular {code}"}


@router_link.get("/status")
async def telegram_link_status(user: dict = Depends(get_current_user)):
    db = _db_ref["db"]
    links = [d async for d in db.tg_links.find({"user_id": user["id"]}, {"_id": 0})]
    return {"linked_chats": links, "count": len(links)}


@router_link.delete("/unlink/{chat_id}")
async def unlink_chat(chat_id: str, user: dict = Depends(get_current_user)):
    db = _db_ref["db"]
    r = await db.tg_links.delete_one({"chat_id": chat_id, "user_id": user["id"]})
    return {"ok": True, "deleted": r.deleted_count}
