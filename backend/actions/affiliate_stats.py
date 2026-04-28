"""
========================================
ACCION: /mi-rendimiento del afiliado por Telegram
========================================
"""

# DB se inyecta desde server.py via set_db
_db_ref = {"db": None}


def set_db(db):
    _db_ref["db"] = db


async def my_performance(telegram_chat_id: str) -> str:
    """Devuelve el resumen de stats del afiliado vinculado a este chat de Telegram."""
    db = _db_ref["db"]
    if db is None:
        return "Servicio temporalmente no disponible. Intenta en un momento."

    chat_id = str(telegram_chat_id)
    user = await db.users.find_one(
        {"telegram_chat_id": chat_id, "role": "affiliate"},
        {"_id": 0, "password_hash": 0},
    )
    if not user:
        return (
            "No encontre tu cuenta de afiliado vinculada a este Telegram.\n\n"
            f"Pidele al admin que registre tu chat_id ({chat_id}) en tu perfil. "
            "Una vez vinculado, escribe /mi-rendimiento para ver tus numeros."
        )

    if not user.get("active", True):
        return "Tu cuenta de afiliado esta desactivada. Contacta al admin."

    # Calcular stats
    sales = await db.sales.find(
        {"affiliate_id": user["id"]},
        {"_id": 0},
    ).sort("created_at", -1).to_list(1000)

    total_sales = len(sales)
    total_amount = round(sum(s["amount"] for s in sales), 2)
    total_commission = round(sum(s["commission"] for s in sales), 2)
    paid = round(sum(s["commission"] for s in sales if s.get("paid")), 2)
    pending = round(total_commission - paid, 2)

    name = user.get("name", "")
    code = user.get("affiliate_code", "—")
    pct = user.get("commission_pct", 0)

    last = sales[0] if sales else None

    msg = [
        f"Hola {name}!",
        "",
        f"Codigo: {code}  ·  Comision: {pct}%",
        "",
        "Tus numeros:",
        f"  Ventas:        {total_sales}",
        f"  Facturado:     ${total_amount:,.2f}",
        f"  Comision tot.: ${total_commission:,.2f}",
        f"  Pagada:        ${paid:,.2f}",
        f"  Pendiente:     ${pending:,.2f}",
    ]
    if last:
        msg += [
            "",
            "Ultima venta:",
            f"  {last['product']} · ${last['amount']:,.2f}"
            f" → comision ${last['commission']:,.2f}"
            f" ({'PAGADA' if last.get('paid') else 'PENDIENTE'})",
        ]
    return "\n".join(msg)
