"""
E9 — Analytics / Monitoring / Intelligence
Sub-orquestador especializado en métricas, uptime, costos de IA, alertas
y reportes ejecutivos de toda la plataforma.
No toca console.py ni E1.
"""
import logging
import os
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field

import auth

logger = logging.getLogger("e9_analytics")
router = APIRouter(prefix="/e9", tags=["E9-Analytics"])
_db_ref: dict = {"db": None}

OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")
GROQ_KEY   = os.getenv("GROQ_API_KEY", "")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")


def set_db(db) -> None:
    _db_ref["db"] = db


def _db():
    return _db_ref["db"]


# ─── Constantes ───────────────────────────────────────────────────────────────

EVENT_TYPES = [
    "chat_started", "chat_completed", "agent_invoked", "tool_called",
    "app_generated", "deploy_triggered", "login", "api_call",
    "payment_received", "ticket_created", "ticket_resolved",
    "tenant_activated", "license_generated", "error",
]

ALERT_SEVERITIES = ["info", "warning", "critical"]
METRIC_NAMES = ["active_users", "chats_per_hour", "avg_response_ms",
                "error_rate", "uptime_pct", "api_cost_usd", "revenue_usd"]

REPORT_TYPES = ["daily_summary", "weekly_digest", "monthly_executive",
                "cost_analysis", "growth_report", "security_audit"]


# ─── Modelos ──────────────────────────────────────────────────────────────────

class EventIn(BaseModel):
    event_type: str
    tenant_id: Optional[str] = None
    user_id: Optional[str] = None
    payload: dict = Field(default_factory=dict)
    session_id: Optional[str] = None


class MetricIn(BaseModel):
    metric_name: str
    value: float
    tenant_id: Optional[str] = None
    tags: dict = Field(default_factory=dict)
    period: Optional[str] = None


class AlertIn(BaseModel):
    name: str
    metric: str
    threshold: float
    severity: str = "warning"
    tenant_id: Optional[str] = None
    notify_email: Optional[str] = None
    condition: str = Field("gt", description="gt=mayor que, lt=menor que, eq=igual")


class ReportIn(BaseModel):
    report_type: str
    tenant_id: Optional[str] = None
    period_days: int = 30
    include_costs: bool = True
    include_growth: bool = True


# ─── Audit log ────────────────────────────────────────────────────────────────

async def _audit(action: str, actor: str, detail: dict, tenant_id: str = "") -> None:
    try:
        await _db().e9_analytics_logs.insert_one({
            "ts": datetime.now(timezone.utc).isoformat(),
            "agent": "E9",
            "action": action,
            "actor": actor,
            "tenant_id": tenant_id,
            "detail": detail,
        })
    except Exception as exc:
        logger.warning(f"[e9] audit failed: {exc}")


# ─── Business logic: Eventos ──────────────────────────────────────────────────

async def _track_event(data: dict, actor: str = "system") -> dict:
    event_id = "evt_" + secrets.token_urlsafe(8)
    doc = {
        "id": event_id,
        "event_type": data.get("event_type", "unknown"),
        "tenant_id": data.get("tenant_id", ""),
        "user_id": data.get("user_id"),
        "session_id": data.get("session_id"),
        "payload": data.get("payload", {}),
        "ts": datetime.now(timezone.utc).isoformat(),
        "actor": actor,
    }
    await _db().e9_events.insert_one(doc)
    return {k: v for k, v in doc.items() if k != "_id"}


async def _record_metric(data: dict) -> dict:
    now = datetime.now(timezone.utc)
    period = data.get("period") or now.strftime("%Y-%m-%d")

    await _db().e9_metrics.update_one(
        {
            "metric_name": data["metric_name"],
            "tenant_id": data.get("tenant_id", ""),
            "period": period,
        },
        {
            "$set": {
                "value": data["value"],
                "tags": data.get("tags", {}),
                "last_updated": now.isoformat(),
            }
        },
        upsert=True,
    )
    return {"metric_name": data["metric_name"], "value": data["value"],
            "period": period, "tenant_id": data.get("tenant_id", "")}


async def _create_alert(data: dict, actor: str) -> dict:
    alert_id = "alr_" + secrets.token_urlsafe(8)
    doc = {
        "id": alert_id,
        "name": data["name"],
        "metric": data["metric"],
        "threshold": data["threshold"],
        "severity": data.get("severity", "warning"),
        "condition": data.get("condition", "gt"),
        "tenant_id": data.get("tenant_id", ""),
        "notify_email": data.get("notify_email"),
        "active": True,
        "triggered_count": 0,
        "last_triggered": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": actor,
    }
    await _db().e9_alerts.insert_one(doc)
    await _audit("alert_created", actor, {"alert_id": alert_id, "metric": data["metric"]},
                  data.get("tenant_id", ""))
    return {k: v for k, v in doc.items() if k != "_id"}


async def _check_alerts(metric_name: str, value: float, tenant_id: str = "") -> list:
    """Evalúa alertas activas para un metric y dispara las que correspondan."""
    q = {"metric": metric_name, "active": True}
    if tenant_id:
        q["tenant_id"] = tenant_id
    alerts = [a async for a in _db().e9_alerts.find(q, {"_id": 0})]
    triggered = []
    for alert in alerts:
        condition = alert.get("condition", "gt")
        threshold = alert.get("threshold", 0)
        fire = (condition == "gt" and value > threshold) or \
               (condition == "lt" and value < threshold) or \
               (condition == "eq" and value == threshold)
        if fire:
            now = datetime.now(timezone.utc).isoformat()
            await _db().e9_alerts.update_one(
                {"id": alert["id"]},
                {"$inc": {"triggered_count": 1}, "$set": {"last_triggered": now}}
            )
            await _audit("alert_triggered", "system",
                          {"alert_id": alert["id"], "metric": metric_name, "value": value,
                           "threshold": threshold, "severity": alert["severity"]},
                          tenant_id)
            triggered.append(alert)
    return triggered


async def _ai_cost_summary(tenant_id: str = "", period_days: int = 30) -> dict:
    """Calcula costos estimados de IA basándose en eventos de la plataforma."""
    since = (datetime.now(timezone.utc) - timedelta(days=period_days)).isoformat()
    q: dict = {"event_type": "chat_completed", "ts": {"$gte": since}}
    if tenant_id:
        q["tenant_id"] = tenant_id

    events = [e async for e in _db().e9_events.find(q, {"payload": 1, "_id": 0})]
    total_tokens = sum(e.get("payload", {}).get("tokens", 0) for e in events)

    # Costos estimados por modelo (USD por 1M tokens)
    cost_per_million = {
        "openai": 5.0,    # GPT-4o aprox
        "groq": 0.27,     # llama-3.1-8b
        "anthropic": 15.0, # Claude Sonnet
    }

    # Estimar distribución (basado en configuración actual)
    openai_active = bool(OPENAI_KEY)
    groq_active = bool(GROQ_KEY)

    model_used = "groq" if groq_active else "openai"
    estimated_cost = (total_tokens / 1_000_000) * cost_per_million.get(model_used, 5.0)

    return {
        "tenant_id": tenant_id,
        "period_days": period_days,
        "total_events": len(events),
        "total_tokens_estimated": total_tokens,
        "model_used": model_used,
        "estimated_cost_usd": round(estimated_cost, 4),
        "openai_active": openai_active,
        "groq_active": groq_active,
        "anthropic_active": bool(ANTHROPIC_KEY),
        "note": "Costo estimado — configurar tracking de tokens en cada tool call para precisión real",
    }


async def _uptime_monitor(service: str, tenant_id: str = "") -> dict:
    # Consulta los últimos eventos de error/success para calcular uptime
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    errors = await _db().e9_events.count_documents(
        {"event_type": "error", "payload.service": service, "ts": {"$gte": since}}
    )
    total = await _db().e9_events.count_documents(
        {"event_type": {"$in": ["chat_completed", "api_call"]}, "ts": {"$gte": since}}
    )
    uptime = 100.0 if total == 0 else max(0, (1 - errors / max(total, 1)) * 100)
    return {
        "service": service,
        "period_hours": 24,
        "total_requests": total,
        "errors": errors,
        "uptime_pct": round(uptime, 2),
        "status": "healthy" if uptime >= 99 else "degraded" if uptime >= 95 else "critical",
    }


async def _generate_report(report_type: str, tenant_id: str, period_days: int,
                            include_costs: bool, include_growth: bool, actor: str) -> dict:
    report_id = "rep_" + secrets.token_urlsafe(8)
    since = (datetime.now(timezone.utc) - timedelta(days=period_days)).isoformat()
    q: dict = {"ts": {"$gte": since}}
    if tenant_id:
        q["tenant_id"] = tenant_id

    # Datos base
    total_events = await _db().e9_events.count_documents(q)
    chats = await _db().e9_events.count_documents({**q, "event_type": "chat_completed"})
    deploys = await _db().e9_events.count_documents({**q, "event_type": "deploy_triggered"})
    errors = await _db().e9_events.count_documents({**q, "event_type": "error"})
    new_tenants = await _db().e5_tenants.count_documents({"created_at": {"$gte": since}}) if not tenant_id else 0
    tickets = await _db().e8_tickets.count_documents({"created_at": {"$gte": since}, **({"tenant_id": tenant_id} if tenant_id else {})})

    report = {
        "id": report_id,
        "report_type": report_type,
        "tenant_id": tenant_id,
        "period_days": period_days,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": actor,
        "summary": {
            "total_events": total_events,
            "chats_completed": chats,
            "deployments": deploys,
            "errors": errors,
            "support_tickets": tickets,
            "new_tenants": new_tenants,
        },
    }

    if include_costs:
        report["costs"] = await _ai_cost_summary(tenant_id, period_days)

    if include_growth:
        prev_since = (datetime.now(timezone.utc) - timedelta(days=period_days * 2)).isoformat()
        prev_q: dict = {"ts": {"$gte": prev_since, "$lt": since}}
        if tenant_id:
            prev_q["tenant_id"] = tenant_id
        prev_chats = await _db().e9_events.count_documents({**prev_q, "event_type": "chat_completed"})
        growth = ((chats - prev_chats) / max(prev_chats, 1)) * 100 if prev_chats else 0
        report["growth"] = {
            "chats_vs_prev_period": round(growth, 1),
            "prev_period_chats": prev_chats,
        }

    await _db().e9_reports.insert_one({**report, "_id_str": report_id})
    await _audit("report_generated", actor, {"report_id": report_id, "type": report_type}, tenant_id)
    return report


# ─── Tool functions ────────────────────────────────────────────────────────────

async def tool_analytics_dashboard(tenant_id: str = "", period_days: int = 30) -> dict:
    since = (datetime.now(timezone.utc) - timedelta(days=period_days)).isoformat()
    q: dict = {"ts": {"$gte": since}}
    if tenant_id:
        q["tenant_id"] = tenant_id

    total = await _db().e9_events.count_documents(q)
    by_type = {}
    async for event in _db().e9_events.find(q, {"event_type": 1, "_id": 0}):
        t = event.get("event_type", "unknown")
        by_type[t] = by_type.get(t, 0) + 1

    metrics_cur = _db().e9_metrics.find(
        {"tenant_id": tenant_id} if tenant_id else {}, {"_id": 0}
    ).sort("last_updated", -1).limit(20)
    metrics = [m async for m in metrics_cur]

    return {
        "tenant_id": tenant_id,
        "period_days": period_days,
        "total_events": total,
        "events_by_type": by_type,
        "latest_metrics": metrics,
    }


async def tool_uptime_monitor(service: str, tenant_id: str = "") -> dict:
    return await _uptime_monitor(service, tenant_id)


async def tool_ai_cost_tracker(tenant_id: str = "", period_days: int = 30) -> dict:
    return await _ai_cost_summary(tenant_id, period_days)


async def tool_alert_system(action: str, alert_data: dict = None,
                             metric: str = "", value: float = 0) -> dict:
    if action == "create" and alert_data:
        return await _create_alert(alert_data, "e1_tool")
    if action == "check" and metric:
        triggered = await _check_alerts(metric, value)
        return {"metric": metric, "value": value, "alerts_triggered": triggered}
    if action == "list":
        cur = _db().e9_alerts.find({}, {"_id": 0}).sort("created_at", -1).limit(50)
        return {"alerts": [a async for a in cur]}
    raise ValueError(f"action desconocida: {action}")


async def tool_report_generator(report_type: str, tenant_id: str = "",
                                 period_days: int = 30) -> dict:
    return await _generate_report(report_type, tenant_id, period_days,
                                    include_costs=True, include_growth=True,
                                    actor="e1_tool")


# ─── FastAPI endpoints ─────────────────────────────────────────────────────────

@router.post("/events")
async def track_event(data: EventIn, user: dict = Depends(auth.get_current_user)):
    return await _track_event(data.model_dump(), actor=user["email"])


@router.get("/events")
async def list_events(tenant_id: Optional[str] = None, event_type: Optional[str] = None,
                       limit: int = 100, user: dict = Depends(auth.get_current_user)):
    q: dict = {}
    if tenant_id:
        q["tenant_id"] = tenant_id
    if event_type:
        q["event_type"] = event_type
    cur = _db().e9_events.find(q, {"_id": 0}).sort("ts", -1).limit(limit)
    return {"events": [e async for e in cur]}


@router.post("/metrics")
async def record_metric(data: MetricIn, user: dict = Depends(auth.get_current_user)):
    return await _record_metric(data.model_dump())


@router.get("/metrics")
async def list_metrics(tenant_id: Optional[str] = None,
                        user: dict = Depends(auth.get_current_user)):
    q = {"tenant_id": tenant_id} if tenant_id else {}
    cur = _db().e9_metrics.find(q, {"_id": 0}).sort("last_updated", -1).limit(100)
    return {"metrics": [m async for m in cur]}


@router.post("/alerts")
async def create_alert(data: AlertIn, user: dict = Depends(auth.get_current_user)):
    return await _create_alert(data.model_dump(), actor=user["email"])


@router.get("/alerts")
async def list_alerts(tenant_id: Optional[str] = None,
                       user: dict = Depends(auth.get_current_user)):
    q = {"tenant_id": tenant_id, "active": True} if tenant_id else {"active": True}
    cur = _db().e9_alerts.find(q, {"_id": 0}).limit(50)
    return {"alerts": [a async for a in cur]}


@router.post("/reports")
async def generate_report(data: ReportIn, user: dict = Depends(auth.get_current_user)):
    return await _generate_report(
        data.report_type, data.tenant_id or "", data.period_days,
        data.include_costs, data.include_growth, user["email"]
    )


@router.get("/reports")
async def list_reports(tenant_id: Optional[str] = None,
                        user: dict = Depends(auth.get_current_user)):
    q = {"tenant_id": tenant_id} if tenant_id else {}
    cur = _db().e9_reports.find(q, {"_id": 0, "costs": 0, "growth": 0}).sort("generated_at", -1).limit(50)
    return {"reports": [r async for r in cur]}


@router.get("/dashboard")
async def dashboard(tenant_id: Optional[str] = None, period_days: int = 30,
                     user: dict = Depends(auth.get_current_user)):
    return await tool_analytics_dashboard(tenant_id or "", period_days)


@router.get("/costs")
async def ai_costs(tenant_id: Optional[str] = None, period_days: int = 30,
                    user: dict = Depends(auth.get_current_user)):
    return await _ai_cost_summary(tenant_id or "", period_days)


@router.get("/uptime/{service}")
async def uptime(service: str, tenant_id: Optional[str] = None,
                  user: dict = Depends(auth.get_current_user)):
    return await _uptime_monitor(service, tenant_id or "")
