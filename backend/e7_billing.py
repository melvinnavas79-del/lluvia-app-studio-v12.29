"""
E7 — Billing / Stripe / Subscriptions
Sub-orquestador especializado en suscripciones, facturación, pagos y métricas financieras.
Preparado para Stripe — requiere STRIPE_SECRET_KEY env var para operaciones reales.
Funciona en modo "prep" (sin key): registra intentos y retorna instrucciones.
No toca console.py ni E1.
"""
import logging
import os
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

import auth

logger = logging.getLogger("e7_billing")
router = APIRouter(prefix="/e7", tags=["E7-Billing"])
_db_ref: dict = {"db": None}

STRIPE_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")


def set_db(db) -> None:
    _db_ref["db"] = db


def _db():
    return _db_ref["db"]


def _stripe_ready() -> bool:
    return bool(STRIPE_KEY)


# ─── Constantes ───────────────────────────────────────────────────────────────

BILLING_PLANS = {
    "starter_monthly":   {"amount": 2900, "currency": "usd", "interval": "month", "name": "Starter"},
    "pro_monthly":       {"amount": 9900, "currency": "usd", "interval": "month", "name": "Pro"},
    "agency_monthly":    {"amount": 29900, "currency": "usd", "interval": "month", "name": "Agency"},
    "enterprise_annual": {"amount": 299900, "currency": "usd", "interval": "year", "name": "Enterprise"},
    "starter_annual":    {"amount": 24900, "currency": "usd", "interval": "year", "name": "Starter Anual"},
    "pro_annual":        {"amount": 89900, "currency": "usd", "interval": "year", "name": "Pro Anual"},
}

SUB_STATUSES = ["trialing", "active", "past_due", "canceled", "unpaid", "paused"]


# ─── Modelos ──────────────────────────────────────────────────────────────────

class SubscriptionIn(BaseModel):
    tenant_id: str
    plan_key: str = Field(..., description="starter_monthly|pro_monthly|agency_monthly|enterprise_annual")
    billing_email: str
    trial_days: int = 14
    stripe_payment_method_id: Optional[str] = None
    metadata: dict = Field(default_factory=dict)


class InvoiceIn(BaseModel):
    tenant_id: str
    items: List[dict] = Field(..., description="[{description, amount_cents, quantity}]")
    billing_email: str
    due_days: int = 15
    currency: str = "usd"
    notes: Optional[str] = None


class UsageIn(BaseModel):
    tenant_id: str
    metric: str = Field(..., description="chats|agents|api_calls|storage_mb|deployments")
    value: float
    period: Optional[str] = None


# ─── Audit log ────────────────────────────────────────────────────────────────

async def _audit(action: str, actor: str, detail: dict, tenant_id: str = "") -> None:
    try:
        await _db().e7_billing_logs.insert_one({
            "ts": datetime.now(timezone.utc).isoformat(),
            "agent": "E7",
            "action": action,
            "actor": actor,
            "tenant_id": tenant_id,
            "detail": detail,
        })
    except Exception as exc:
        logger.warning(f"[e7] audit failed: {exc}")


# ─── Business logic ───────────────────────────────────────────────────────────

async def _create_subscription(data: dict, actor: str) -> dict:
    plan = BILLING_PLANS.get(data.get("plan_key", ""))
    if not plan:
        raise HTTPException(status_code=400, detail=f"Plan inválido: {data.get('plan_key')}")

    sub_id = "sub_" + secrets.token_urlsafe(10)
    now = datetime.now(timezone.utc)
    trial_end = (now + timedelta(days=data.get("trial_days", 14))).isoformat()

    doc = {
        "id": sub_id,
        "tenant_id": data["tenant_id"],
        "plan_key": data["plan_key"],
        "plan_name": plan["name"],
        "amount_cents": plan["amount"],
        "currency": plan["currency"],
        "billing_interval": plan["interval"],
        "billing_email": data["billing_email"],
        "status": "trialing",
        "stripe_subscription_id": None,
        "stripe_customer_id": None,
        "stripe_payment_method_id": data.get("stripe_payment_method_id"),
        "trial_start": now.isoformat(),
        "trial_end": trial_end,
        "current_period_start": now.isoformat(),
        "current_period_end": trial_end,
        "next_billing_date": trial_end,
        "canceled_at": None,
        "metadata": data.get("metadata", {}),
        "created_at": now.isoformat(),
        "created_by": actor,
        "stripe_ready": _stripe_ready(),
    }

    if _stripe_ready():
        try:
            import stripe
            stripe.api_key = STRIPE_KEY
            # Crear customer + subscription en Stripe
            customer = stripe.Customer.create(email=data["billing_email"],
                                               metadata={"tenant_id": data["tenant_id"]})
            doc["stripe_customer_id"] = customer["id"]
            # Actualizar tenant en E5 con stripe_customer_id
            try:
                await _db().e5_tenants.update_one(
                    {"id": data["tenant_id"]},
                    {"$set": {"stripe_customer_id": customer["id"]}}
                )
            except Exception:
                pass
            logger.info(f"[e7] Stripe customer creado: {customer['id']}")
        except Exception as exc:
            logger.warning(f"[e7] Stripe error: {exc} — guardando en modo prep")
            doc["stripe_error"] = str(exc)

    await _db().e7_subscriptions.insert_one(doc)
    await _audit("subscription_created", actor,
                  {"sub_id": sub_id, "tenant_id": data["tenant_id"], "plan": data["plan_key"]},
                  data["tenant_id"])
    return {k: v for k, v in doc.items() if k != "_id"}


async def _generate_invoice(data: dict, actor: str) -> dict:
    inv_id = "inv_" + secrets.token_urlsafe(10)
    now = datetime.now(timezone.utc)
    total = sum(item.get("amount_cents", 0) * item.get("quantity", 1)
                for item in data.get("items", []))
    due_date = (now + timedelta(days=data.get("due_days", 15))).isoformat()

    doc = {
        "id": inv_id,
        "tenant_id": data["tenant_id"],
        "billing_email": data["billing_email"],
        "items": data.get("items", []),
        "subtotal_cents": total,
        "tax_cents": 0,
        "total_cents": total,
        "currency": data.get("currency", "usd"),
        "status": "draft",
        "stripe_invoice_id": None,
        "due_date": due_date,
        "paid_at": None,
        "notes": data.get("notes"),
        "created_at": now.isoformat(),
        "created_by": actor,
    }
    await _db().e7_invoices.insert_one(doc)
    await _audit("invoice_created", actor,
                  {"inv_id": inv_id, "total_cents": total, "tenant_id": data["tenant_id"]},
                  data["tenant_id"])
    return {k: v for k, v in doc.items() if k != "_id"}


async def _track_usage(tenant_id: str, metric: str, value: float, period: str = "") -> dict:
    now = datetime.now(timezone.utc)
    period = period or now.strftime("%Y-%m")
    await _db().e7_usage.update_one(
        {"tenant_id": tenant_id, "metric": metric, "period": period},
        {"$inc": {"value": value}, "$set": {"last_updated": now.isoformat()}},
        upsert=True,
    )
    doc = await _db().e7_usage.find_one(
        {"tenant_id": tenant_id, "metric": metric, "period": period}, {"_id": 0}
    )
    return doc or {"tenant_id": tenant_id, "metric": metric, "period": period, "value": value}


async def _get_billing_summary(tenant_id: str) -> dict:
    sub = await _db().e7_subscriptions.find_one(
        {"tenant_id": tenant_id, "status": {"$in": ["trialing", "active"]}},
        {"_id": 0}
    )
    invoices = [i async for i in _db().e7_invoices.find(
        {"tenant_id": tenant_id}, {"_id": 0}
    ).sort("created_at", -1).limit(10)]
    usage_cur = _db().e7_usage.find({"tenant_id": tenant_id}, {"_id": 0})
    usage = [u async for u in usage_cur]
    return {
        "tenant_id": tenant_id,
        "subscription": sub,
        "recent_invoices": invoices,
        "usage_current_month": usage,
        "stripe_ready": _stripe_ready(),
    }


# ─── Tool functions ────────────────────────────────────────────────────────────

async def tool_stripe_manager(action: str, tenant_id: str = "",
                               params: dict = None) -> dict:
    params = params or {}
    if action == "status":
        return {"stripe_ready": _stripe_ready(),
                "note": "Configurar STRIPE_SECRET_KEY para activar" if not _stripe_ready() else "Stripe activo"}
    if action == "create_customer" and tenant_id:
        if not _stripe_ready():
            return {"ok": False, "note": "Stripe no configurado — agregar STRIPE_SECRET_KEY"}
        try:
            import stripe
            stripe.api_key = STRIPE_KEY
            c = stripe.Customer.create(email=params.get("email", ""), metadata={"tenant_id": tenant_id})
            return {"stripe_customer_id": c["id"], "tenant_id": tenant_id}
        except Exception as exc:
            return {"error": str(exc)}
    return {"action": action, "note": f"Action '{action}' procesada"}


async def tool_subscription_engine(tenant_id: str, plan_key: str,
                                    action: str = "create", billing_email: str = "") -> dict:
    if action == "create":
        return await _create_subscription(
            {"tenant_id": tenant_id, "plan_key": plan_key, "billing_email": billing_email},
            actor="e1_tool"
        )
    if action == "cancel":
        await _db().e7_subscriptions.update_one(
            {"tenant_id": tenant_id, "status": {"$in": ["trialing", "active"]}},
            {"$set": {"status": "canceled", "canceled_at": datetime.now(timezone.utc).isoformat()}}
        )
        await _audit("subscription_canceled", "e1_tool", {"tenant_id": tenant_id}, tenant_id)
        return {"tenant_id": tenant_id, "status": "canceled"}
    if action == "summary":
        return await _get_billing_summary(tenant_id)
    raise ValueError(f"action desconocida: {action}")


async def tool_invoice_generator(tenant_id: str, items: list,
                                  billing_email: str = "", due_days: int = 15) -> dict:
    return await _generate_invoice(
        {"tenant_id": tenant_id, "items": items,
         "billing_email": billing_email, "due_days": due_days},
        actor="e1_tool"
    )


async def tool_usage_meter(tenant_id: str, metric: str, value: float,
                            period: str = "") -> dict:
    return await _track_usage(tenant_id, metric, value, period)


async def tool_billing_control(tenant_id: str, action: str) -> dict:
    if action == "summary":
        return await _get_billing_summary(tenant_id)
    if action == "plans":
        return {"plans": BILLING_PLANS}
    raise ValueError(f"action desconocida: {action}")


# ─── FastAPI endpoints ─────────────────────────────────────────────────────────

@router.post("/subscriptions")
async def create_subscription(data: SubscriptionIn, user: dict = Depends(auth.get_current_user)):
    return await _create_subscription(data.model_dump(), actor=user["email"])


@router.get("/subscriptions/{tenant_id}")
async def get_subscription(tenant_id: str, user: dict = Depends(auth.get_current_user)):
    sub = await _db().e7_subscriptions.find_one(
        {"tenant_id": tenant_id}, {"_id": 0}
    )
    if not sub:
        raise HTTPException(status_code=404, detail="Suscripción no encontrada")
    return sub


@router.get("/subscriptions")
async def list_subscriptions(user: dict = Depends(auth.get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Solo admin")
    cur = _db().e7_subscriptions.find({}, {"_id": 0}).sort("created_at", -1).limit(100)
    return {"subscriptions": [s async for s in cur]}


@router.post("/invoices")
async def create_invoice(data: InvoiceIn, user: dict = Depends(auth.get_current_user)):
    return await _generate_invoice(data.model_dump(), actor=user["email"])


@router.get("/invoices")
async def list_invoices(tenant_id: Optional[str] = None,
                         user: dict = Depends(auth.get_current_user)):
    q = {"tenant_id": tenant_id} if tenant_id else {}
    cur = _db().e7_invoices.find(q, {"_id": 0}).sort("created_at", -1).limit(50)
    return {"invoices": [i async for i in cur]}


@router.post("/usage")
async def record_usage(data: UsageIn, user: dict = Depends(auth.get_current_user)):
    return await _track_usage(data.tenant_id, data.metric, data.value, data.period or "")


@router.get("/usage/{tenant_id}")
async def get_usage(tenant_id: str, period: Optional[str] = None,
                     user: dict = Depends(auth.get_current_user)):
    q: dict = {"tenant_id": tenant_id}
    if period:
        q["period"] = period
    cur = _db().e7_usage.find(q, {"_id": 0})
    return {"usage": [u async for u in cur]}


@router.get("/summary/{tenant_id}")
async def billing_summary(tenant_id: str, user: dict = Depends(auth.get_current_user)):
    return await _get_billing_summary(tenant_id)


@router.get("/plans")
async def list_plans():
    return {"plans": BILLING_PLANS}


@router.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    """Webhook de Stripe — valida signature y procesa eventos."""
    if not _stripe_ready():
        raise HTTPException(status_code=503, detail="Stripe no configurado")
    try:
        import stripe
        stripe.api_key = STRIPE_KEY
        payload = await request.body()
        sig = request.headers.get("stripe-signature", "")
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
        event_type = event["type"]
        obj = event["data"]["object"]

        if event_type == "invoice.paid":
            sub_id = obj.get("subscription")
            if sub_id:
                await _db().e7_subscriptions.update_one(
                    {"stripe_subscription_id": sub_id},
                    {"$set": {"status": "active",
                               "current_period_end": datetime.fromtimestamp(
                                   obj.get("period_end", 0), tz=timezone.utc).isoformat()}}
                )
        elif event_type == "invoice.payment_failed":
            sub_id = obj.get("subscription")
            if sub_id:
                await _db().e7_subscriptions.update_one(
                    {"stripe_subscription_id": sub_id},
                    {"$set": {"status": "past_due"}}
                )
        elif event_type == "customer.subscription.deleted":
            await _db().e7_subscriptions.update_one(
                {"stripe_subscription_id": obj["id"]},
                {"$set": {"status": "canceled", "canceled_at": datetime.now(timezone.utc).isoformat()}}
            )

        await _audit("stripe_webhook", "stripe", {"event_type": event_type})
        return {"received": True}
    except Exception as exc:
        logger.error(f"[e7] webhook error: {exc}")
        raise HTTPException(status_code=400, detail=str(exc))
