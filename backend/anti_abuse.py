"""
Anti-abuse: rate limiting multi-capa para Lluvia App Studio.

Capas implementadas:
  1. Cuota diaria de llamadas por tenant (MongoDB, atómica)
  2. Budget diario y mensual en USD por tenant (MongoDB)
  3. Cooldown outbound — mismo número no puede recibir dos llamadas en N segundos
  4. Detección de flood en /gather — call_sid demasiado activo (in-memory, <1ms)
  5. Límite de tamaño de campaña outbound
  6. Registro de costos por llamada → alimenta E9 / dashboard de costos

Todos los límites se configuran vía env vars (sin reiniciar requiere reimport).
"""

import os
import time
import collections
import logging
from datetime import datetime, timezone
from fastapi import HTTPException

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# Configuración — todo override vía env
# ══════════════════════════════════════════════════════════════════════════════

TENANT_VOICE_DAILY_CALLS    = int(os.environ.get("TENANT_VOICE_DAILY_CALLS", "100"))
TENANT_VOICE_DAILY_BUDGET   = float(os.environ.get("TENANT_VOICE_DAILY_BUDGET_USD", "10.0"))
TENANT_VOICE_MONTHLY_BUDGET = float(os.environ.get("TENANT_VOICE_MONTHLY_BUDGET_USD", "200.0"))

CAMPAIGN_MAX_NUMBERS    = int(os.environ.get("CAMPAIGN_MAX_NUMBERS", "500"))
OUTBOUND_COOLDOWN_SEC   = int(os.environ.get("OUTBOUND_COOLDOWN_SEC", "3600"))  # 1 hora

GATHER_FLOOD_WINDOW_SEC = float(os.environ.get("GATHER_FLOOD_WINDOW_SEC", "2.0"))
GATHER_FLOOD_MAX_HITS   = int(os.environ.get("GATHER_FLOOD_MAX_HITS", "4"))

# ══════════════════════════════════════════════════════════════════════════════
# Helpers de fecha
# ══════════════════════════════════════════════════════════════════════════════

def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def _month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")

# ══════════════════════════════════════════════════════════════════════════════
# Capa 1 — Cuota diaria de llamadas por tenant
# ══════════════════════════════════════════════════════════════════════════════

async def check_and_increment_daily_calls(db, tenant_id: str) -> None:
    """
    Verifica cuota diaria e incrementa el contador de forma atómica.
    Raise 429 si el tenant ya superó TENANT_VOICE_DAILY_CALLS hoy.
    """
    doc = await db.tenant_quotas.find_one_and_update(
        {"tenant_id": tenant_id, "date": _today()},
        {
            "$inc": {"calls": 1},
            "$setOnInsert": {"tenant_id": tenant_id, "date": _today(), "cost_usd": 0.0},
        },
        upsert=True,
        return_document=True,  # devuelve el doc DESPUÉS del update
    )
    calls = (doc or {}).get("calls", 1)
    if calls > TENANT_VOICE_DAILY_CALLS:
        import observability as obs  # import late para evitar circular
        await obs.emit_obs_alert(db, "quota_daily_exceeded", {
            "tenant_id": tenant_id, "calls": calls, "limit": TENANT_VOICE_DAILY_CALLS,
        }, severity="warning")
        raise HTTPException(
            status_code=429,
            detail=(
                f"Tenant {tenant_id!r} superó la cuota diaria de "
                f"{TENANT_VOICE_DAILY_CALLS} llamadas. Reinicio: 00:00 UTC."
            ),
        )

# ══════════════════════════════════════════════════════════════════════════════
# Capa 2 — Budget diario y mensual en USD
# ══════════════════════════════════════════════════════════════════════════════

async def check_daily_budget(db, tenant_id: str) -> None:
    """Raise 429 si el tenant ya consumió su budget diario en USD."""
    doc = await db.tenant_quotas.find_one({"tenant_id": tenant_id, "date": _today()})
    cost = (doc or {}).get("cost_usd", 0.0)
    if cost >= TENANT_VOICE_DAILY_BUDGET:
        import observability as obs
        await obs.emit_obs_alert(db, "budget_daily_exceeded", {
            "tenant_id": tenant_id, "cost_usd": cost, "limit_usd": TENANT_VOICE_DAILY_BUDGET,
        }, severity="error")
        raise HTTPException(
            status_code=429,
            detail=(
                f"Tenant {tenant_id!r} superó el budget diario de "
                f"${TENANT_VOICE_DAILY_BUDGET:.2f} USD (consumido: ${cost:.4f})."
            ),
        )

async def check_monthly_budget(db, tenant_id: str) -> None:
    """Raise 429 si el tenant ya consumió su budget mensual en USD."""
    doc = await db.tenant_monthly_costs.find_one({"tenant_id": tenant_id, "month": _month()})
    cost = (doc or {}).get("cost_usd", 0.0)
    if cost >= TENANT_VOICE_MONTHLY_BUDGET:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Tenant {tenant_id!r} superó el budget mensual de "
                f"${TENANT_VOICE_MONTHLY_BUDGET:.2f} USD (consumido: ${cost:.4f})."
            ),
        )

# ══════════════════════════════════════════════════════════════════════════════
# Capa 6 — Registro de costo por llamada (alimenta E9)
# ══════════════════════════════════════════════════════════════════════════════

async def record_call_cost(db, tenant_id: str, cost_usd: float) -> None:
    """
    Suma el costo de una llamada finalizada a los contadores diario y mensual.
    Se llama desde el status callback cuando Twilio notifica 'completed'.
    """
    if cost_usd <= 0:
        return
    today = _today()
    month = _month()
    await db.tenant_quotas.update_one(
        {"tenant_id": tenant_id, "date": today},
        {"$inc": {"cost_usd": cost_usd}},
        upsert=True,
    )
    await db.tenant_monthly_costs.update_one(
        {"tenant_id": tenant_id, "month": month},
        {"$inc": {"cost_usd": cost_usd}, "$setOnInsert": {"tenant_id": tenant_id, "month": month}},
        upsert=True,
    )
    logger.debug(f"Costo registrado tenant={tenant_id!r} +${cost_usd:.6f} USD")

# ══════════════════════════════════════════════════════════════════════════════
# Capa 3 — Cooldown outbound (mismo número, mismo tenant)
# ══════════════════════════════════════════════════════════════════════════════

async def check_outbound_cooldown(db, to_number: str, tenant_id: str) -> None:
    """
    Raise 429 si el número fue contactado en los últimos OUTBOUND_COOLDOWN_SEC segundos
    por el mismo tenant (evita spam/double-dial en campañas con retry agresivo).
    """
    if OUTBOUND_COOLDOWN_SEC <= 0:
        return  # desactivado por configuración
    cutoff_iso = (
        datetime.fromtimestamp(
            time.time() - OUTBOUND_COOLDOWN_SEC, tz=timezone.utc
        ).isoformat()
    )
    recent = await db.voice_calls.find_one({
        "to": to_number,
        "tenant_id": tenant_id,
        "direction": "outbound",
        "started_at": {"$gte": cutoff_iso},
    })
    if recent:
        elapsed = int(time.time() - OUTBOUND_COOLDOWN_SEC)
        remaining = OUTBOUND_COOLDOWN_SEC - elapsed if elapsed < OUTBOUND_COOLDOWN_SEC else 0
        raise HTTPException(
            status_code=429,
            detail=(
                f"Número {to_number} ya fue contactado por tenant {tenant_id!r} "
                f"recientemente. Cooldown: {OUTBOUND_COOLDOWN_SEC}s "
                f"(intenta en ~{remaining}s)."
            ),
        )

# ══════════════════════════════════════════════════════════════════════════════
# Capa 4 — Flood detection en /gather (in-memory, sin latencia)
# ══════════════════════════════════════════════════════════════════════════════

# call_sid → deque de timestamps (monotonic)
_gather_hits: dict[str, collections.deque] = {}


def check_gather_flood(call_sid: str) -> None:
    """
    Detecta si un call_sid está enviando demasiados POST /gather en poco tiempo.
    Raise 429 si supera GATHER_FLOOD_MAX_HITS en GATHER_FLOOD_WINDOW_SEC.

    No usa async — la deque es thread-safe en CPython y 0 I/O.
    """
    now = time.monotonic()
    if call_sid not in _gather_hits:
        _gather_hits[call_sid] = collections.deque()
    dq = _gather_hits[call_sid]

    # Expira hits fuera de la ventana
    while dq and now - dq[0] > GATHER_FLOOD_WINDOW_SEC:
        dq.popleft()

    dq.append(now)

    if len(dq) > GATHER_FLOOD_MAX_HITS:
        logger.warning(
            f"Gather flood: call_sid={call_sid!r} "
            f"{len(dq)} hits en {GATHER_FLOOD_WINDOW_SEC}s"
        )
        raise HTTPException(
            status_code=429,
            detail=(
                f"Flood detectado en llamada {call_sid!r}: "
                f"{len(dq)} requests en {GATHER_FLOOD_WINDOW_SEC}s."
            ),
        )


def clear_gather_tracker(call_sid: str) -> None:
    """Limpia el tracker cuando la llamada termina (ahorra memoria)."""
    _gather_hits.pop(call_sid, None)

# ══════════════════════════════════════════════════════════════════════════════
# Capa 5 — Límite de tamaño de campaña
# ══════════════════════════════════════════════════════════════════════════════

def check_campaign_size(numbers: list[str]) -> None:
    """Raise 400 si la campaña supera el máximo de números permitidos."""
    if len(numbers) > CAMPAIGN_MAX_NUMBERS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"La campaña tiene {len(numbers)} números, "
                f"máximo permitido: {CAMPAIGN_MAX_NUMBERS}. "
                f"Divide en campañas más pequeñas o ajusta CAMPAIGN_MAX_NUMBERS."
            ),
        )

# ══════════════════════════════════════════════════════════════════════════════
# Summary — para dashboard / E9
# ══════════════════════════════════════════════════════════════════════════════

async def get_tenant_quota_summary(db, tenant_id: str) -> dict:
    """Retorna el estado actual de quotas y costos del tenant (para métricas/UI)."""
    today_doc = await db.tenant_quotas.find_one({"tenant_id": tenant_id, "date": _today()}) or {}
    month_doc = await db.tenant_monthly_costs.find_one({"tenant_id": tenant_id, "month": _month()}) or {}
    return {
        "tenant_id": tenant_id,
        "today": {
            "calls": today_doc.get("calls", 0),
            "cost_usd": round(today_doc.get("cost_usd", 0.0), 4),
            "limit_calls": TENANT_VOICE_DAILY_CALLS,
            "limit_cost_usd": TENANT_VOICE_DAILY_BUDGET,
            "calls_remaining": max(0, TENANT_VOICE_DAILY_CALLS - today_doc.get("calls", 0)),
            "budget_remaining_usd": round(
                max(0.0, TENANT_VOICE_DAILY_BUDGET - today_doc.get("cost_usd", 0.0)), 4
            ),
        },
        "month": {
            "cost_usd": round(month_doc.get("cost_usd", 0.0), 4),
            "limit_cost_usd": TENANT_VOICE_MONTHLY_BUDGET,
            "budget_remaining_usd": round(
                max(0.0, TENANT_VOICE_MONTHLY_BUDGET - month_doc.get("cost_usd", 0.0)), 4
            ),
        },
        "limits": {
            "daily_calls": TENANT_VOICE_DAILY_CALLS,
            "daily_budget_usd": TENANT_VOICE_DAILY_BUDGET,
            "monthly_budget_usd": TENANT_VOICE_MONTHLY_BUDGET,
            "campaign_max_numbers": CAMPAIGN_MAX_NUMBERS,
            "outbound_cooldown_sec": OUTBOUND_COOLDOWN_SEC,
            "gather_flood_window_sec": GATHER_FLOOD_WINDOW_SEC,
            "gather_flood_max_hits": GATHER_FLOOD_MAX_HITS,
        },
    }
