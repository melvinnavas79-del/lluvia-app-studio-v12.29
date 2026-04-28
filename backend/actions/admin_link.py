"""
========================================
VINCULACION DEL CHAT_ID DEL ADMIN
========================================

Permite al admin auto-registrarse via Telegram con su password,
sin tener que editar .env ni reiniciar el servidor.
"""

import os
from datetime import datetime, timezone

import auth as auth_module

_db_ref = {"db": None}


def set_db(db):
    _db_ref["db"] = db


async def link_admin(chat_id: str, password: str) -> str:
    """
    /vincular-admin <password>
    Si la password coincide con ADMIN_PASSWORD, registra este chat_id como admin.
    Tolerante a artefactos de Telegram (backticks, comillas, espacios).
    """
    db = _db_ref["db"]
    if db is None:
        return "Servicio temporalmente no disponible."

    expected = os.environ.get("ADMIN_PASSWORD", "")
    if not expected:
        return "Vinculacion deshabilitada (ADMIN_PASSWORD no configurada)."

    # Limpiar artefactos comunes de Telegram: backticks, comillas, espacios, markdown
    received = (password or "").strip().strip("`").strip("'").strip('"').strip("*").strip()

    if received != expected:
        return "Password incorrecta. Intenta nuevamente."

    chat_id = str(chat_id)
    await db.admin_chats.update_one(
        {"chat_id": chat_id},
        {"$set": {
            "chat_id": chat_id,
            "linked_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )
    return (
        "Listo. Este Telegram quedo vinculado como admin de Lluvia App Studio.\n\n"
        "Ya puedes pedirme cosas como:\n"
        "  cuanta ram tiene mi servidor\n"
        "  cuanto disco libre tengo\n"
        "  ejecuta uname -a\n"
        "  crear repo mi-proyecto\n"
        "  listar repos"
    )


async def is_admin_chat(chat_id: str) -> bool:
    """True si el chat esta autorizado (env o DB)."""
    raw = os.environ.get("ADMIN_TELEGRAM_CHAT_IDS", "")
    env_ids = [x.strip() for x in raw.split(",") if x.strip()]
    if str(chat_id) in env_ids:
        return True

    db = _db_ref["db"]
    if db is None:
        return False
    found = await db.admin_chats.find_one({"chat_id": str(chat_id)})
    return found is not None
