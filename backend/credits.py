"""
========================================
SISTEMA DE CREDITOS ("OROS")
========================================

Cada usuario tiene un balance. Cada accion (chat, tool, provision)
descuenta una cantidad. Admin puede recargar manualmente.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("credits")

_db_ref: dict = {"db": None}


def set_db(db) -> None:
    _db_ref["db"] = db


async def get_balance(user_id: str) -> int:
    db = _db_ref["db"]
    doc = await db.credits.find_one({"user_id": user_id}, {"_id": 0})
    if not doc:
        # Bootstrapping: admin arranca con 10000 oros, otros con 100
        from auth import _db_ref as auth_db
        user = await auth_db["db"].users.find_one({"id": user_id}, {"_id": 0, "role": 1})
        initial = 10000 if (user and user.get("role") == "admin") else 100
        await db.credits.insert_one({
            "user_id": user_id,
            "balance": initial,
            "lifetime_topup": initial,
            "lifetime_spent": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        return initial
    return int(doc.get("balance", 0))


async def charge(user_id: str, amount: int, reason: str, meta: Optional[dict] = None) -> bool:
    """Descuenta `amount` oros. Devuelve True si OK, False si saldo insuficiente.
    ADMINS no se cobran a si mismos."""
    if amount <= 0:
        return True
    db = _db_ref["db"]
    # Admin acceso gratis a la consola
    from auth import _db_ref as auth_db
    udoc = await auth_db["db"].users.find_one({"id": user_id}, {"_id": 0, "role": 1})
    if udoc and udoc.get("role") == "admin":
        # registrar txn como "admin_free" pero no descontar
        await db.credit_txns.insert_one({
            "user_id": user_id, "type": "admin_free", "amount": 0,
            "reason": reason, "meta": meta or {},
            "ts": datetime.now(timezone.utc).isoformat(),
        })
        return True
    balance = await get_balance(user_id)
    if balance < amount:
        return False
    await db.credits.update_one(
        {"user_id": user_id},
        {"$inc": {"balance": -amount, "lifetime_spent": amount}},
    )
    await db.credit_txns.insert_one({
        "user_id": user_id,
        "type": "charge",
        "amount": -amount,
        "reason": reason,
        "meta": meta or {},
        "ts": datetime.now(timezone.utc).isoformat(),
    })
    return True


async def topup(user_id: str, amount: int, reason: str = "manual_topup") -> int:
    """Recarga `amount` oros. Devuelve balance nuevo."""
    db = _db_ref["db"]
    await get_balance(user_id)  # asegura doc
    await db.credits.update_one(
        {"user_id": user_id},
        {"$inc": {"balance": amount, "lifetime_topup": amount}},
    )
    await db.credit_txns.insert_one({
        "user_id": user_id,
        "type": "topup",
        "amount": amount,
        "reason": reason,
        "ts": datetime.now(timezone.utc).isoformat(),
    })
    return await get_balance(user_id)


async def history(user_id: str, limit: int = 50) -> list:
    db = _db_ref["db"]
    cur = db.credit_txns.find({"user_id": user_id}, {"_id": 0}).sort("ts", -1).limit(limit)
    return [t async for t in cur]
