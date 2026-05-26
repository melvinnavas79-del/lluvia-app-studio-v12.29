"""
Observabilidad centralizada — Lluvia App Studio.

  1. JSON structured logs con contextvars (request_id, tenant_id, call_sid)
  2. RequestIdMiddleware — X-Request-ID en cada request/response
  3. Circuit breakers por proveedor IA (groq, openai, twilio)
  4. Health scorer: success rate + latencias P50/P95 por ventana deslizante
  5. Registro de alertas operacionales → MongoDB obs_audit + e9_alerts
  6. API: GET /obs/health  /obs/providers  /obs/audit  /obs/circuit-reset
"""

import collections
import contextvars
import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from auth import get_current_user

logger = logging.getLogger("observability")

# ══════════════════════════════════════════════════════════════════════════════
# Contextvars — propagados por todo el request/llamada
# ══════════════════════════════════════════════════════════════════════════════

_req_id:    contextvars.ContextVar[str] = contextvars.ContextVar("req_id",    default="")
_tenant_id: contextvars.ContextVar[str] = contextvars.ContextVar("tenant_id", default="")
_call_sid:  contextvars.ContextVar[str] = contextvars.ContextVar("call_sid",  default="")


def set_trace_context(*, request_id: str = "", tenant_id: str = "", call_sid: str = "") -> None:
    """Inyecta contexto en el hilo/coroutine actual. Llama desde endpoints o middleware."""
    if request_id: _req_id.set(request_id)
    if tenant_id:  _tenant_id.set(tenant_id)
    if call_sid:   _call_sid.set(call_sid)


def get_trace_context() -> dict:
    return {
        "request_id": _req_id.get(""),
        "tenant_id":  _tenant_id.get(""),
        "call_sid":   _call_sid.get(""),
    }

# ══════════════════════════════════════════════════════════════════════════════
# JSON Formatter — structured logs con contexto automático
# ══════════════════════════════════════════════════════════════════════════════

class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        msg = record.getMessage()
        if record.exc_info:
            msg += "\n" + self.formatException(record.exc_info)
        payload: dict = {
            "ts":         datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level":      record.levelname,
            "logger":     record.name,
            "msg":        msg,
            "request_id": _req_id.get(""),
            "tenant_id":  _tenant_id.get(""),
            "call_sid":   _call_sid.get(""),
        }
        # Campos extra pasados con logger.info("...", extra={"latency_ms": 42})
        for key, val in record.__dict__.items():
            if key not in logging.LogRecord.__dict__ and not key.startswith("_"):
                payload[key] = val
        return json.dumps(payload, ensure_ascii=False, default=str)

# ══════════════════════════════════════════════════════════════════════════════
# Middleware — X-Request-ID en cada HTTP request
# ══════════════════════════════════════════════════════════════════════════════

class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        req_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        _req_id.set(req_id)
        # Intenta extraer tenant_id del query param o header
        tid = request.query_params.get("tenant_id") or request.headers.get("X-Tenant-ID", "")
        if tid:
            _tenant_id.set(tid)
        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = req_id
        return response

# ══════════════════════════════════════════════════════════════════════════════
# Circuit Breaker + Health Scorer por proveedor
# ══════════════════════════════════════════════════════════════════════════════

CIRCUIT_FAILURE_THRESHOLD = int(os.environ.get("CIRCUIT_FAILURE_THRESHOLD", "5"))
CIRCUIT_RESET_TIMEOUT_SEC = int(os.environ.get("CIRCUIT_RESET_TIMEOUT_SEC", "60"))
PROVIDER_WINDOW_SIZE      = int(os.environ.get("PROVIDER_WINDOW_SIZE", "100"))


class _CircuitState(str, Enum):
    CLOSED    = "closed"     # operación normal
    OPEN      = "open"       # rechazando requests
    HALF_OPEN = "half_open"  # probando recuperación


class _ProviderTracker:
    """Sliding window de salud + circuit breaker por proveedor IA."""

    def __init__(self, name: str):
        self.name  = name
        self.window: collections.deque = collections.deque(maxlen=PROVIDER_WINDOW_SIZE)
        self.state  = _CircuitState.CLOSED
        self.consecutive_failures = 0
        self._opened_at: float = 0.0

    # ── Circuit breaker ───────────────────────────────────────

    def is_open(self) -> bool:
        if self.state == _CircuitState.OPEN:
            if time.monotonic() - self._opened_at >= CIRCUIT_RESET_TIMEOUT_SEC:
                self.state = _CircuitState.HALF_OPEN
                logger.info(f"[circuit] {self.name} → HALF_OPEN (probando recuperación)")
                return False
            return True
        return False

    def _trip(self) -> None:
        self.state = _CircuitState.OPEN
        self._opened_at = time.monotonic()
        logger.warning(
            f"[circuit] {self.name} → OPEN "
            f"({self.consecutive_failures} fallas consecutivas)"
        )

    # ── Recording ─────────────────────────────────────────────

    def record(self, latency_ms: float, success: bool) -> None:
        self.window.append({"ms": latency_ms, "ok": success, "t": time.time()})
        if success:
            if self.state in (_CircuitState.HALF_OPEN, _CircuitState.OPEN):
                self.state = _CircuitState.CLOSED
                self.consecutive_failures = 0
                logger.info(f"[circuit] {self.name} → CLOSED (recuperado)")
            else:
                self.consecutive_failures = 0
        else:
            self.consecutive_failures += 1
            if self.state == _CircuitState.CLOSED and self.consecutive_failures >= CIRCUIT_FAILURE_THRESHOLD:
                self._trip()
            elif self.state == _CircuitState.HALF_OPEN:
                self._trip()

    # ── Stats ─────────────────────────────────────────────────

    def stats(self) -> dict:
        w = list(self.window)
        if not w:
            return {"samples": 0, "success_rate": 1.0, "p50_ms": 0, "p95_ms": 0, "avg_ms": 0}
        latencies = sorted(e["ms"] for e in w)
        n  = len(latencies)
        ok = sum(1 for e in w if e["ok"])
        return {
            "samples":      n,
            "success_rate": round(ok / n, 3),
            "p50_ms":       int(latencies[int(n * 0.50)]),
            "p95_ms":       int(latencies[min(int(n * 0.95), n - 1)]),
            "avg_ms":       int(sum(latencies) / n),
        }

    def as_dict(self) -> dict:
        return {
            "state":                self.state.value,
            "consecutive_failures": self.consecutive_failures,
            **self.stats(),
        }


# Registro global de proveedores
_providers: dict[str, _ProviderTracker] = {
    "groq":   _ProviderTracker("groq"),
    "openai": _ProviderTracker("openai"),
    "twilio": _ProviderTracker("twilio"),
}


def record_provider_call(provider: str, latency_ms: float, success: bool) -> None:
    """
    Registra el resultado de una llamada a un proveedor externo.
    Llama desde twilio_voice.py tras cada LLM call y Twilio API call.
    """
    t = _providers.get(provider)
    if t:
        t.record(latency_ms, success)


def check_circuit(provider: str) -> None:
    """Raise 503 si el circuit breaker del proveedor está OPEN."""
    t = _providers.get(provider)
    if t and t.is_open():
        raise HTTPException(
            status_code=503,
            detail=(
                f"Proveedor {provider!r} no disponible (circuit OPEN, "
                f"{t.consecutive_failures} fallas). Reinicia en {CIRCUIT_RESET_TIMEOUT_SEC}s."
            ),
        )

# ══════════════════════════════════════════════════════════════════════════════
# Alertas operacionales → obs_audit + e9_alerts
# ══════════════════════════════════════════════════════════════════════════════

_db_ref: dict = {"db": None}


async def emit_obs_alert(db, alert_type: str, details: dict, severity: str = "warning") -> None:
    """
    Persiste una alerta operacional.
    Escribe en obs_audit (operacional) y en e9_alerts (visible en E9 dashboard).
    """
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "alert_type": alert_type,
        "severity":   severity,
        "details":    details,
        "ts":         now,
        **get_trace_context(),
    }
    try:
        await db.obs_audit.insert_one({**doc})
        await db.e9_alerts.insert_one({
            "type":       alert_type,
            "source":     "observability",
            "severity":   severity,
            "details":    details,
            "created_at": now,
            "status":     "open",
        })
    except Exception as exc:
        logger.error(f"emit_obs_alert DB error: {exc}")

    level = logging.ERROR if severity == "error" else logging.WARNING
    logger.log(level, f"[OBS ALERT] {alert_type}", extra={"alert_details": details})

# ══════════════════════════════════════════════════════════════════════════════
# API endpoints
# ══════════════════════════════════════════════════════════════════════════════

router = APIRouter(prefix="/obs", tags=["observability"])


def _overall_health() -> tuple[str, float]:
    rates = [t.stats()["success_rate"] for t in _providers.values() if t.stats()["samples"] > 0]
    score = round(sum(rates) / len(rates), 3) if rates else 1.0
    status = "healthy" if score >= 0.95 else "degraded" if score >= 0.80 else "critical"
    return status, score


@router.get("/health")
async def obs_health(user: dict = Depends(get_current_user)):
    """Estado operacional global + por proveedor."""
    status, score = _overall_health()
    return {
        "status":               status,
        "overall_success_rate": score,
        "providers":            {n: t.as_dict() for n, t in _providers.items()},
        "ts":                   datetime.now(timezone.utc).isoformat(),
    }


@router.get("/providers")
async def obs_providers(user: dict = Depends(get_current_user)):
    """Métricas detalladas de latencia y circuit breaker por proveedor."""
    return {"providers": {n: t.as_dict() for n, t in _providers.items()}}


@router.get("/audit")
async def obs_audit_log(
    limit: int = 50,
    severity: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    """Eventos de alerta recientes (circuit trips, quota exceeded, budget alerts)."""
    db = _db_ref["db"]
    if db is None:
        return {"events": [], "note": "DB no disponible"}
    query: dict = {}
    if severity:
        query["severity"] = severity
    cur = db.obs_audit.find(query, {"_id": 0}).sort("ts", -1).limit(limit)
    events = [e async for e in cur]
    return {"events": events, "total": len(events)}


@router.post("/circuit-reset/{provider}")
async def circuit_reset(provider: str, user: dict = Depends(get_current_user)):
    """Fuerza el reset manual de un circuit breaker (solo admin)."""
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Solo admin puede resetear circuits")
    t = _providers.get(provider)
    if not t:
        raise HTTPException(status_code=404, detail=f"Proveedor {provider!r} no encontrado")
    prev_state = t.state.value
    t.state = _CircuitState.CLOSED
    t.consecutive_failures = 0
    logger.info(f"[circuit] {provider} reseteado manualmente desde {prev_state}")
    return {"provider": provider, "prev_state": prev_state, "new_state": "closed"}


@router.get("/summary")
async def obs_summary(user: dict = Depends(get_current_user)):
    """Resumen operacional completo para el dashboard."""
    db = _db_ref["db"]
    status, score = _overall_health()
    open_circuits = [n for n, t in _providers.items() if t.state == _CircuitState.OPEN]

    recent_alerts = []
    if db is not None:
        cur = db.obs_audit.find({}, {"_id": 0}).sort("ts", -1).limit(10)
        recent_alerts = [a async for a in cur]

    return {
        "health": {"status": status, "score": score},
        "open_circuits": open_circuits,
        "providers":     {n: t.as_dict() for n, t in _providers.items()},
        "recent_alerts": recent_alerts,
        "ts":            datetime.now(timezone.utc).isoformat(),
    }

# ══════════════════════════════════════════════════════════════════════════════
# Setup — llamar desde server.py startup
# ══════════════════════════════════════════════════════════════════════════════

def add_middleware(app) -> None:
    """
    Fase 1 — llamar a nivel de módulo en server.py (ANTES del startup).
    Agrega RequestIdMiddleware y activa JSON structured logging.
    """
    # Aplica JSON formatter a handlers existentes del root logger
    fmt = _JsonFormatter()
    root = logging.getLogger()
    applied = False
    for handler in root.handlers:
        handler.setFormatter(fmt)
        applied = True
    if not applied:
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(fmt)
        root.addHandler(h)

    # Middleware debe registrarse antes de que la app arranque
    app.add_middleware(RequestIdMiddleware)


def set_db(db) -> None:
    """
    Fase 2 — llamar en el evento on_startup de FastAPI.
    Inyecta la referencia a MongoDB para emit_obs_alert y /obs/audit.
    """
    _db_ref["db"] = db
    logger.info("Observability: DB conectado, JSON logs + RequestIdMiddleware activos")


# Alias de compatibilidad por si algo llamó setup_observability
def setup_observability(app, db=None) -> None:
    add_middleware(app)
    if db is not None:
        set_db(db)
