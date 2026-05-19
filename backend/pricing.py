"""
Pricing centralizada para tools de ensamble + threshold de exportacion.
Lee de site_content.tool_prices con fallback a defaults. El admin la edita
desde el panel admin (tab Precios).

Por que aqui y no en agents_catalog.TOOL_NAMES?
- TOOL_NAMES es estatico, cargado al import del modulo. No se puede editar
  desde un panel en runtime sin reiniciar.
- Los precios de templates (Audio Room, futuros Radio/TikTok/etc) son
  decision comercial del admin, no del codigo. Tienen que ser editables.

DEFAULT_TOOL_PRICES funciona como fallback Y como source-of-truth de
"que templates conoce el sistema" para el panel de admin.
"""

import logging
from datetime import datetime, timezone

logger = logging.getLogger("pricing")

# Defaults conservadores - el admin puede subirlos/bajarlos desde el panel.
DEFAULT_TOOL_PRICES: dict = {
    "generate_audio_room_app": 40,
    "generate_tiktok_app": 50,
    # Agregar aqui cada nuevo template del App Builder Pro:
    # "generate_radio_online_app": 50,
}

# Saldo minimo (en oros) para desbloquear el push a GitHub.
# Idea: el visitor con 15 oros trial puede crear su app dentro de Lluvia y
# ver la rich card preview, pero para LLEVARSE el codigo a GitHub debe
# tener al menos esta cantidad. Asi monetizamos sin regalar el codigo.
DEFAULT_MIN_BALANCE_FOR_EXPORT: int = 50

# Metadatos visibles para el panel admin (id, nombre legible, screens)
TEMPLATE_METADATA = [
    {
        "tool_id": "generate_audio_room_app",
        "name": "Audio Room (Clubhouse / Twitter Spaces)",
        "screens": ["Inicio", "Tendencias", "Sala Activa", "Perfil"],
        "stack": "FastAPI + Socket.IO + SQLite + Vanilla JS",
        "default_price": 40,
    },
    {
        "tool_id": "generate_tiktok_app",
        "name": "TikTok / Bigo Live Clone (Feed Vertical)",
        "screens": ["Feed Vertical", "Descubrir", "Subir Video", "Perfil"],
        "stack": "FastAPI + SQLite + Socket.IO + Vanilla JS + HLS",
        "default_price": 50,
    },
    # Placeholders para futuros templates (los del backlog del PRD):
    {"tool_id": "generate_radio_online_app", "name": "Radio Online (en backlog)",
     "screens": ["Home", "Player", "Programación", "Locutor"],
     "stack": "FastAPI + HLS streaming", "default_price": 50, "coming_soon": True},
    {"tool_id": "generate_landing_peluqueria_app", "name": "Landing Peluquería + Booking (en backlog)",
     "screens": ["Landing", "Servicios", "Booking", "Mi turno"],
     "stack": "FastAPI + SQLite", "default_price": 35, "coming_soon": True},
    {"tool_id": "generate_ecommerce_simple_app", "name": "Ecommerce simple con Stripe (en backlog)",
     "screens": ["Catálogo", "Producto", "Carrito", "Checkout"],
     "stack": "FastAPI + SQLite + Stripe", "default_price": 80, "coming_soon": True},
]

_db_ref: dict = {"db": None}


def set_db(db) -> None:
    _db_ref["db"] = db


async def _read_doc() -> dict:
    db = _db_ref["db"]
    if db is None:
        return {}
    return await db.site_content.find_one({"_id": "main"}, {"_id": 0}) or {}


async def get_tool_price(tool_name: str) -> int:
    """Precio actual de una tool. Lee de DB con fallback a default."""
    doc = await _read_doc()
    prices = doc.get("tool_prices") or {}
    if tool_name in prices:
        try:
            return max(0, int(prices[tool_name]))
        except (TypeError, ValueError):
            pass
    return int(DEFAULT_TOOL_PRICES.get(tool_name, 0))


async def get_min_balance_for_export() -> int:
    """Threshold de saldo para desbloquear el push a GitHub."""
    doc = await _read_doc()
    try:
        return max(0, int(doc.get("min_balance_for_export", DEFAULT_MIN_BALANCE_FOR_EXPORT)))
    except (TypeError, ValueError):
        return DEFAULT_MIN_BALANCE_FOR_EXPORT


async def get_all_pricing() -> dict:
    """Estado completo para el panel admin."""
    doc = await _read_doc()
    custom_prices = doc.get("tool_prices") or {}
    # Merge: precios efectivos = default sobrescritos por custom
    effective = {**DEFAULT_TOOL_PRICES, **{k: v for k, v in custom_prices.items() if k in DEFAULT_TOOL_PRICES}}
    return {
        "tool_prices": effective,
        "min_balance_for_export": await get_min_balance_for_export(),
        "templates": TEMPLATE_METADATA,
        "updated_at": doc.get("pricing_updated_at"),
        "updated_by": doc.get("pricing_updated_by"),
    }


async def set_pricing(tool_prices: dict | None = None,
                      min_balance_for_export: int | None = None,
                      updated_by: str = "admin") -> dict:
    """Persiste cambios. Solo claves conocidas, valores enteros >= 0."""
    db = _db_ref["db"]
    if db is None:
        raise RuntimeError("DB not initialized in pricing module")
    update: dict = {}
    if tool_prices is not None:
        # Merge con el doc actual para no perder claves no enviadas
        doc = await _read_doc()
        current = dict(doc.get("tool_prices") or {})
        for k, v in tool_prices.items():
            if k not in DEFAULT_TOOL_PRICES:
                continue  # ignoramos keys desconocidas
            try:
                current[k] = max(0, int(v))
            except (TypeError, ValueError):
                continue
        update["tool_prices"] = current
    if min_balance_for_export is not None:
        try:
            update["min_balance_for_export"] = max(0, int(min_balance_for_export))
        except (TypeError, ValueError):
            pass
    if not update:
        return await get_all_pricing()
    update["pricing_updated_at"] = datetime.now(timezone.utc).isoformat()
    update["pricing_updated_by"] = updated_by
    await db.site_content.update_one({"_id": "main"}, {"$set": update}, upsert=True)
    logger.info(f"Pricing actualizada por {updated_by}: {update}")
    return await get_all_pricing()
