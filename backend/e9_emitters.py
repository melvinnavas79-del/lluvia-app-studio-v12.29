"""
============================================================
E9 EMITTERS — Instrumentación real additive
STATUS: REAL

Capa de instrumentación automática para todo el ecosistema.
No modifica lógica existente. Import additive en cualquier módulo.

API pública:
  emit(event_type, data, tenant_id, module)   — evento genérico
  track_call(module, event_prefix)            — decorador @track_call para async functions
  track_llm_call(module, provider, model, ...)— costos reales de IA por token
  track_error(module, error, tenant_id)       — errores con contexto de módulo
  track_job_event(event_type, job_id, ...)    — eventos del scheduler

Endpoints adicionales en /api/e9/:
  GET /live           — dashboard en vivo
  GET /live/modules   — métricas por módulo
  GET /live/costs     — costos IA reales
  GET /live/queue     — estado de la cola de jobs

Colecciones nuevas (additive, no toca colecciones existentes):
  e9_ai_costs    — LLM calls con tokens y costos reales
  e9_counters    — contadores por módulo/día para dashboards O(1)

Uso rápido:
  from e9_emitters import emit, track_call, track_llm_call

  @track_call(module="e10_social", event_prefix="social.post")
  async def tool_social_post(content, tenant_id="default"):
      ...

  await track_llm_call(module="e4_sales", provider="groq",
                        model="llama-3.1-8b-instant",
                        prompt_tokens=150, completion_tokens=80,
                        tenant_id="t1")
============================================================
"""

import asyncio
import functools
import inspect
import logging
import os
import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, Callable, Any

from fastapi import APIRouter, Depends, Query

import auth

logger = logging.getLogger("e9_emitters")

# ── DB ref (inicializado por server.py) ────────────────────────────────────────
_db_ref: dict = {"db": None}


def set_db(db) -> None:
    _db_ref["db"] = db


def _db():
    return _db_ref["db"]


router = APIRouter(prefix="/e9", tags=["E9-Live"])


# ══════════════════════════════════════════════════════════════════════════════
# PRICING — USD por 1M tokens (input / output)
# Actualizar cuando cambien los precios.
# ══════════════════════════════════════════════════════════════════════════════

_COST_PER_1M: dict[str, dict[str, float]] = {
    "gpt-4o":                      {"input": 5.0,    "output": 15.0},
    "gpt-4o-mini":                  {"input": 0.15,   "output": 0.60},
    "llama-3.1-8b-instant":         {"input": 0.05,   "output": 0.08},
    "llama-3.1-70b-versatile":      {"input": 0.59,   "output": 0.79},
    "llama-3.3-70b-versatile":      {"input": 0.59,   "output": 0.79},
    "claude-sonnet-4-6":            {"input": 3.0,    "output": 15.0},
    "claude-sonnet-4-5":            {"input": 3.0,    "output": 15.0},
    "claude-haiku-4-5-20251001":    {"input": 0.80,   "output": 4.0},
    "claude-opus-4-7":              {"input": 15.0,   "output": 75.0},
}


def compute_llm_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Costo en USD dado modelo y tokens. Retorna 0 si el modelo no está en tabla."""
    table = _COST_PER_1M.get(model)
    if not table:
        # Fallback: buscar por prefix
        for key in _COST_PER_1M:
            if model.startswith(key) or key.startswith(model.split("-")[0]):
                table = _COST_PER_1M[key]
                break
    if not table:
        table = {"input": 5.0, "output": 15.0}  # conservative fallback
    return (prompt_tokens / 1_000_000) * table["input"] \
         + (completion_tokens / 1_000_000) * table["output"]


# ══════════════════════════════════════════════════════════════════════════════
# INDEXES — llamar desde on_startup
# ══════════════════════════════════════════════════════════════════════════════

async def create_indexes() -> None:
    db = _db()
    if db is None:
        return
    await db.e9_ai_costs.create_index([("module", 1), ("day", 1)])
    await db.e9_ai_costs.create_index([("tenant_id", 1), ("day", 1)])
    await db.e9_ai_costs.create_index([("provider", 1), ("day", 1)])
    await db.e9_ai_costs.create_index("ts")
    await db.e9_counters.create_index([("module", 1), ("day", 1), ("tenant_id", 1)], unique=True)
    await db.e9_events.create_index([("event_type", 1), ("ts", -1)])
    await db.e9_events.create_index([("tenant_id", 1), ("ts", -1)])
    await db.e9_events.create_index([("module", 1), ("ts", -1)])
    logger.info("[e9_emitters] Indexes created")


# ══════════════════════════════════════════════════════════════════════════════
# CORE EMIT — fire-and-forget, never raises
# ══════════════════════════════════════════════════════════════════════════════

async def emit(
    event_type: str,
    data: dict,
    tenant_id: str = "default",
    module: str = "system",
) -> None:
    """
    Emite un evento a E9. Fire-and-forget: no bloquea, no propaga errores.
    """
    db = _db()
    if db is None:
        return
    try:
        now = datetime.now(timezone.utc)
        day = now.strftime("%Y-%m-%d")

        await db.e9_events.insert_one({
            "id":         f"evt_{uuid.uuid4().hex[:10]}",
            "event_type": event_type,
            "tenant_id":  tenant_id,
            "module":     module,
            "data":       data,
            "ts":         now.isoformat(),
        })

        await db.e9_counters.update_one(
            {"module": module, "day": day, "tenant_id": tenant_id},
            {
                "$inc":         {"event_count": 1},
                "$setOnInsert": {"created_at": now.isoformat()},
                "$set":         {"updated_at": now.isoformat()},
            },
            upsert=True,
        )
    except Exception as exc:
        logger.debug(f"[e9] emit({event_type}) failed (non-fatal): {exc}")


# ══════════════════════════════════════════════════════════════════════════════
# TRACK LLM CALL — costos reales de IA
# ══════════════════════════════════════════════════════════════════════════════

async def track_llm_call(
    *,
    module: str,
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    tenant_id: str = "default",
    request_id: str = "",
    elapsed_ms: int = 0,
) -> None:
    """
    STATUS: REAL
    Registra un LLM call con tokens y costos calculados en e9_ai_costs.
    Actualiza contadores e9_counters para dashboards.

    Llamar después de cada client.chat.completions.create():
        resp = await client.chat.completions.create(...)
        await track_llm_call(
            module="e10_social", provider="groq", model=model,
            prompt_tokens=resp.usage.prompt_tokens,
            completion_tokens=resp.usage.completion_tokens,
            tenant_id=tenant_id, elapsed_ms=elapsed_ms
        )
    """
    db = _db()
    if db is None:
        return
    try:
        now          = datetime.now(timezone.utc)
        total_tokens = prompt_tokens + completion_tokens
        cost_usd     = compute_llm_cost(model, prompt_tokens, completion_tokens)
        day          = now.strftime("%Y-%m-%d")

        await db.e9_ai_costs.insert_one({
            "id":                f"llm_{uuid.uuid4().hex[:10]}",
            "module":            module,
            "provider":          provider,
            "model":             model,
            "prompt_tokens":     prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens":      total_tokens,
            "cost_usd":          cost_usd,
            "tenant_id":         tenant_id,
            "request_id":        request_id,
            "elapsed_ms":        elapsed_ms,
            "ts":                now.isoformat(),
            "day":               day,
        })

        await db.e9_counters.update_one(
            {"module": module, "day": day, "tenant_id": tenant_id},
            {
                "$inc": {
                    "llm_calls":    1,
                    "total_tokens": total_tokens,
                    "cost_usd":     cost_usd,
                },
                "$set": {"updated_at": now.isoformat()},
            },
            upsert=True,
        )
    except Exception as exc:
        logger.debug(f"[e9] track_llm_call({module}) failed (non-fatal): {exc}")


# ══════════════════════════════════════════════════════════════════════════════
# TRACK ERROR
# ══════════════════════════════════════════════════════════════════════════════

async def track_error(
    module: str,
    error: str,
    tenant_id: str = "default",
    extra: Optional[dict] = None,
) -> None:
    """Registra un error con contexto de módulo en e9_events y contadores."""
    db = _db()
    if db is None:
        return
    try:
        now = datetime.now(timezone.utc)
        day = now.strftime("%Y-%m-%d")

        await db.e9_events.insert_one({
            "id":         f"err_{uuid.uuid4().hex[:10]}",
            "event_type": "error",
            "tenant_id":  tenant_id,
            "module":     module,
            "data":       {"error": error[:2000], **(extra or {})},
            "ts":         now.isoformat(),
        })
        await db.e9_counters.update_one(
            {"module": module, "day": day, "tenant_id": tenant_id},
            {
                "$inc": {"error_count": 1},
                "$set": {"updated_at": now.isoformat()},
            },
            upsert=True,
        )
    except Exception as exc:
        logger.debug(f"[e9] track_error({module}) failed (non-fatal): {exc}")


# ══════════════════════════════════════════════════════════════════════════════
# TRACK JOB EVENTS — scheduler-specific, granular
# ══════════════════════════════════════════════════════════════════════════════

async def track_job_event(
    event_type: str,
    job_id: str,
    job_type: str,
    tenant_id: str = "default",
    worker_id: str = "",
    attempt: int = 0,
    elapsed_ms: int = 0,
    error: str = "",
    queue_depth: int = -1,
) -> None:
    """
    STATUS: REAL
    Eventos específicos del job scheduler.
    event_type: job.created | job.started | job.completed | job.failed |
                job.retry | job.dead_letter | worker.heartbeat |
                worker.stalled | queue.overflow
    """
    db = _db()
    if db is None:
        return
    try:
        now = datetime.now(timezone.utc)
        day = now.strftime("%Y-%m-%d")

        await db.e9_events.insert_one({
            "id":         f"job_{uuid.uuid4().hex[:10]}",
            "event_type": event_type,
            "tenant_id":  tenant_id,
            "module":     "job_scheduler",
            "data": {
                "job_id":      job_id,
                "job_type":    job_type,
                "worker_id":   worker_id,
                "attempt":     attempt,
                "elapsed_ms":  elapsed_ms,
                "error":       error[:1000] if error else "",
                "queue_depth": queue_depth,
            },
            "ts": now.isoformat(),
        })

        inc_key  = f"job_{event_type.replace('.', '_')}"
        inc: dict = {inc_key: 1}
        if elapsed_ms > 0:
            inc["total_elapsed_ms"] = elapsed_ms
        if "fail" in event_type or "dead" in event_type:
            inc["error_count"] = 1

        await db.e9_counters.update_one(
            {"module": f"job_scheduler.{job_type}", "day": day, "tenant_id": tenant_id},
            {"$inc": inc, "$set": {"updated_at": now.isoformat()}},
            upsert=True,
        )
    except Exception as exc:
        logger.debug(f"[e9] track_job_event({event_type}) failed (non-fatal): {exc}")


# ══════════════════════════════════════════════════════════════════════════════
# @track_call DECORATOR
# ══════════════════════════════════════════════════════════════════════════════

def track_call(
    module: str,
    event_prefix: str = "",
    emit_start: bool = False,
):
    """
    Decorador para funciones async. Emite automáticamente:
      {event_prefix}.completed — con elapsed_ms, tenant_id
      {event_prefix}.failed    — con error, re-propaga la excepción
    Opcionalmente:
      {event_prefix}.started   — si emit_start=True

    Extrae tenant_id del argumento 'tenant_id' de la función (si existe).
    No altera el valor de retorno ni el flujo de excepciones.

    Uso:
        @track_call(module="e10_social", event_prefix="social.post")
        async def tool_social_post(content, tenant_id="default"):
            ...
    """
    def decorator(func: Callable) -> Callable:
        prefix = event_prefix or f"{module}.{func.__name__}"
        sig    = inspect.signature(func)

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                bound = sig.bind(*args, **kwargs)
                bound.apply_defaults()
                tenant_id = str(bound.arguments.get("tenant_id", "default"))
            except Exception:
                tenant_id = "default"

            if emit_start:
                try:
                    await emit(f"{prefix}.started",
                               {"function": func.__name__},
                               tenant_id, module)
                except BaseException:
                    pass

            start = time.monotonic()
            try:
                result     = await func(*args, **kwargs)
                elapsed_ms = int((time.monotonic() - start) * 1000)

                # Observability calls are fire-and-forget — they must never
                # interfere with delivering the function's result to the caller,
                # including during task cancellation (BaseException, not Exception).
                try:
                    await emit(
                        f"{prefix}.completed",
                        {"function": func.__name__, "elapsed_ms": elapsed_ms},
                        tenant_id, module,
                    )
                    db = _db()
                    if db is not None:
                        now = datetime.now(timezone.utc)
                        await db.e9_counters.update_one(
                            {"module": module,
                             "day":    now.strftime("%Y-%m-%d"),
                             "tenant_id": tenant_id},
                            {
                                "$inc": {"call_count": 1, "total_elapsed_ms": elapsed_ms},
                                "$set": {"updated_at": now.isoformat()},
                            },
                            upsert=True,
                        )
                except BaseException:
                    pass  # observability never blocks result delivery

                return result

            except Exception as exc:
                elapsed_ms = int((time.monotonic() - start) * 1000)
                try:
                    await track_error(
                        module, str(exc), tenant_id,
                        {"function": func.__name__, "elapsed_ms": elapsed_ms},
                    )
                except BaseException:
                    pass
                raise  # re-propaga siempre

        return wrapper
    return decorator


# ══════════════════════════════════════════════════════════════════════════════
# LIVE DASHBOARD ENDPOINTS — additive sobre /e9 existente
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/live")
async def live_dashboard(
    tenant_id: Optional[str] = Query(None),
    user: dict = Depends(auth.get_current_user),
):
    """
    STATUS: REAL
    Dashboard en vivo: queue depth, errores recientes, costos IA hoy,
    contadores por módulo, últimos 20 eventos.
    """
    db  = _db()
    now = datetime.now(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    since_1h  = (now - timedelta(hours=1)).isoformat()
    since_24h = (now - timedelta(hours=24)).isoformat()

    q_t = {"tenant_id": tenant_id} if tenant_id else {}

    # ── Queue depth by status ────────────────────────────────────────────────
    queue_agg = [r async for r in db.jobs.aggregate([
        {"$match": q_t},
        {"$group": {"_id": "$status", "count": {"$sum": 1}}},
    ])]
    queue = {r["_id"]: r["count"] for r in queue_agg}

    # ── Recent errors (last 1h) ──────────────────────────────────────────────
    errors_1h = await db.e9_events.count_documents(
        {"event_type": "error", "ts": {"$gte": since_1h}, **q_t}
    )

    # ── Jobs completed / failed ──────────────────────────────────────────────
    jobs_done_1h = await db.e9_events.count_documents(
        {"event_type": "job.completed", "ts": {"$gte": since_1h}, **q_t}
    )
    jobs_fail_24h = await db.e9_events.count_documents(
        {"event_type": "job.failed", "ts": {"$gte": since_24h}, **q_t}
    )

    # ── AI cost today ────────────────────────────────────────────────────────
    cost_agg = [r async for r in db.e9_ai_costs.aggregate([
        {"$match": {"day": day, **q_t}},
        {"$group": {
            "_id":    None,
            "cost":   {"$sum": "$cost_usd"},
            "tokens": {"$sum": "$total_tokens"},
            "calls":  {"$sum": 1},
        }},
    ])]
    cost_today = cost_agg[0] if cost_agg else {"cost": 0.0, "tokens": 0, "calls": 0}

    # ── Per-module counters today ────────────────────────────────────────────
    counters = [
        {k: v for k, v in c.items() if k != "_id"}
        async for c in db.e9_counters.find(
            {"day": day, **q_t}, {"_id": 0}
        ).sort("call_count", -1).limit(25)
    ]

    # ── Recent events (last 20) ──────────────────────────────────────────────
    recent = [
        {k: v for k, v in e.items() if k != "_id"}
        async for e in db.e9_events.find(
            {"ts": {"$gte": since_1h}, **q_t}, {"_id": 0}
        ).sort("ts", -1).limit(20)
    ]

    return {
        "as_of": now.isoformat(),
        "queue": {
            "queued":      queue.get("queued", 0),
            "running":     queue.get("running", 0),
            "retrying":    queue.get("retrying", 0),
            "completed":   queue.get("completed", 0),
            "failed":      queue.get("failed", 0),
            "dead_letter": queue.get("dead_letter", 0),
            "total_pending": queue.get("queued", 0) + queue.get("retrying", 0),
        },
        "last_1h": {
            "errors":         errors_1h,
            "jobs_completed": jobs_done_1h,
        },
        "last_24h": {
            "jobs_failed": jobs_fail_24h,
        },
        "ai_cost_today": {
            "cost_usd":     round(cost_today.get("cost", 0.0), 6),
            "total_tokens": cost_today.get("tokens", 0),
            "llm_calls":    cost_today.get("calls", 0),
        },
        "module_counters": counters,
        "recent_events":   recent,
    }


@router.get("/live/modules")
async def modules_stats(
    day: Optional[str] = Query(None),
    tenant_id: Optional[str] = Query(None),
    user: dict = Depends(auth.get_current_user),
):
    """
    STATUS: REAL
    Métricas por módulo: calls, errors, tokens, cost_usd, avg_ms para el día.
    """
    db      = _db()
    now     = datetime.now(timezone.utc)
    day_str = day or now.strftime("%Y-%m-%d")
    q: dict = {"day": day_str}
    if tenant_id:
        q["tenant_id"] = tenant_id

    counters = [
        {k: v for k, v in c.items() if k != "_id"}
        async for c in db.e9_counters.find(q, {"_id": 0}).sort("cost_usd", -1)
    ]
    for c in counters:
        calls    = c.get("call_count", 0)
        total_ms = c.get("total_elapsed_ms", 0)
        c["avg_ms"] = round(total_ms / calls, 1) if calls > 0 else 0

    ai_cost_by_module = {}
    async for r in db.e9_ai_costs.aggregate([
        {"$match": {**q}},
        {"$group": {
            "_id":    "$module",
            "cost":   {"$sum": "$cost_usd"},
            "tokens": {"$sum": "$total_tokens"},
            "calls":  {"$sum": 1},
        }},
    ]):
        ai_cost_by_module[r["_id"]] = {
            "cost_usd": round(r["cost"], 6),
            "tokens":   r["tokens"],
            "calls":    r["calls"],
        }

    return {
        "day":               day_str,
        "counters":          counters,
        "ai_cost_by_module": ai_cost_by_module,
    }


@router.get("/live/costs")
async def live_ai_costs(
    period_days: int = Query(7, le=90),
    tenant_id: Optional[str] = Query(None),
    user: dict = Depends(auth.get_current_user),
):
    """
    STATUS: REAL — costos reales desde e9_ai_costs.
    Datos disponibles sólo para módulos que usan track_llm_call().
    """
    db    = _db()
    since = (datetime.now(timezone.utc) - timedelta(days=period_days)).isoformat()
    q: dict = {"ts": {"$gte": since}}
    if tenant_id:
        q["tenant_id"] = tenant_id

    by_day = [r async for r in db.e9_ai_costs.aggregate([
        {"$match": q},
        {"$group": {
            "_id":    "$day",
            "cost":   {"$sum": "$cost_usd"},
            "tokens": {"$sum": "$total_tokens"},
            "calls":  {"$sum": 1},
        }},
        {"$sort": {"_id": 1}},
    ])]

    by_model = [r async for r in db.e9_ai_costs.aggregate([
        {"$match": q},
        {"$group": {
            "_id":    "$model",
            "cost":   {"$sum": "$cost_usd"},
            "tokens": {"$sum": "$total_tokens"},
            "calls":  {"$sum": 1},
        }},
        {"$sort": {"cost": -1}},
    ])]

    by_module = [r async for r in db.e9_ai_costs.aggregate([
        {"$match": q},
        {"$group": {
            "_id":     "$module",
            "cost":    {"$sum": "$cost_usd"},
            "tokens":  {"$sum": "$total_tokens"},
            "calls":   {"$sum": 1},
        }},
        {"$sort": {"cost": -1}},
    ])]

    total_cost = sum(r["cost"] for r in by_day)

    return {
        "period_days":    period_days,
        "total_cost_usd": round(total_cost, 6),
        "by_day": [
            {"day": r["_id"], "cost_usd": round(r["cost"], 6),
             "tokens": r["tokens"], "calls": r["calls"]}
            for r in by_day
        ],
        "by_model": [
            {"model": r["_id"], "cost_usd": round(r["cost"], 6),
             "tokens": r["tokens"], "calls": r["calls"]}
            for r in by_model
        ],
        "by_module": [
            {"module": r["_id"], "cost_usd": round(r["cost"], 6),
             "tokens": r["tokens"], "calls": r["calls"]}
            for r in by_module
        ],
        "instrumented_note": (
            "Datos reales sólo para módulos instrumentados con track_llm_call(). "
            "Módulos no instrumentados: E6-legal, E8-support, E3-builder."
        ),
    }


@router.get("/live/queue")
async def live_queue(
    tenant_id: Optional[str] = Query(None),
    user: dict = Depends(auth.get_current_user),
):
    """
    STATUS: REAL
    Estado de la cola de jobs con breakdown por job_type y status.
    Incluye DLQ count y job pendiente más antiguo.
    """
    db      = _db()
    q: dict = {"tenant_id": tenant_id} if tenant_id else {}

    rows = [r async for r in db.jobs.aggregate([
        {"$match": q},
        {"$group": {
            "_id":   {"status": "$status", "job_type": "$job_type"},
            "count": {"$sum": 1},
        }},
    ])]

    by_status:   dict = {}
    by_job_type: dict = {}
    for r in rows:
        st  = r["_id"]["status"]
        jt  = r["_id"]["job_type"]
        cnt = r["count"]
        by_status[st] = by_status.get(st, 0) + cnt
        by_job_type.setdefault(jt, {})[st] = by_job_type.get(jt, {}).get(st, 0) + cnt

    oldest = await db.jobs.find_one(
        {"status": {"$in": ["queued", "retrying"]}, **q},
        {"job_id": 1, "run_at": 1, "job_type": 1, "attempts": 1, "_id": 0},
        sort=[("run_at", 1)],
    )

    return {
        "by_status":      by_status,
        "by_job_type":    by_job_type,
        "dlq_count":      by_status.get("dead_letter", 0),
        "total_pending":  by_status.get("queued", 0) + by_status.get("retrying", 0),
        "oldest_pending": oldest,
    }


@router.get("/live/errors")
async def live_errors(
    hours: int = Query(24, le=168),
    module: Optional[str] = Query(None),
    tenant_id: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    user: dict = Depends(auth.get_current_user),
):
    """
    STATUS: REAL
    Errores recientes con contexto de módulo y tenant.
    """
    db    = _db()
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    q: dict = {"event_type": "error", "ts": {"$gte": since}}
    if module:    q["module"]    = module
    if tenant_id: q["tenant_id"] = tenant_id

    errors = [
        {k: v for k, v in e.items() if k != "_id"}
        async for e in db.e9_events.find(q, {"_id": 0}).sort("ts", -1).limit(limit)
    ]
    total = await db.e9_events.count_documents(q)

    return {"total": total, "hours": hours, "errors": errors}
