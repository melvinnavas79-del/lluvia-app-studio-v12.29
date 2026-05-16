"""
PayPal Checkout integration para vender oros.
- POST /api/paypal/create-order -> devuelve order_id y approve_url
- POST /api/paypal/capture/{order_id} -> captura y acredita oros
- POST /api/paypal/webhook -> opcional, para confirmacion async
"""

import os
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import requests
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

import credits as credits_mod
from auth import get_current_user
from rate_limit import limiter

logger = logging.getLogger("paypal")
router = APIRouter(prefix="/paypal", tags=["paypal"])

_db_ref: dict = {"db": None}


def set_db(db) -> None:
    _db_ref["db"] = db


# Paquetes de oros disponibles
PACKS = {
    "starter":  {"oros": 1000,  "price_usd": "10.00", "label": "Starter - 1.000 oros"},
    "growth":   {"oros": 5000,  "price_usd": "45.00", "label": "Growth - 5.000 oros"},
    "scale":    {"oros": 10000, "price_usd": "80.00", "label": "Scale - 10.000 oros"},
}


def _paypal_env() -> tuple[str, str, str]:
    """Devuelve (base_url, client_id, secret). Soporta sandbox y live."""
    mode = os.environ.get("PAYPAL_MODE", "live").lower()
    base = "https://api-m.sandbox.paypal.com" if mode == "sandbox" else "https://api-m.paypal.com"
    cid = os.environ.get("PAYPAL_CLIENT_ID", "")
    secret = os.environ.get("PAYPAL_SECRET", "")
    return base, cid, secret


def _access_token() -> str:
    base, cid, secret = _paypal_env()
    if not cid or not secret:
        raise HTTPException(status_code=503, detail="PayPal no configurado (PAYPAL_CLIENT_ID/SECRET)")
    r = requests.post(
        f"{base}/v1/oauth2/token",
        data={"grant_type": "client_credentials"},
        auth=(cid, secret),
        timeout=15,
    )
    if r.status_code != 200:
        logger.error(f"PayPal token error: {r.status_code} {r.text[:200]}")
        raise HTTPException(status_code=502, detail="PayPal auth fallo")
    return r.json()["access_token"]


class CreateOrderIn(BaseModel):
    pack: str = Field(description="starter|growth|scale")


@router.get("/packs")
async def list_packs():
    from promos import current_discount_pct
    pct, desc = await current_discount_pct()
    factor = (100 - pct) / 100.0
    packs_out = {}
    for k, p in PACKS.items():
        price = float(p["price_usd"])
        promo_price = round(price * factor, 2)
        packs_out[k] = {
            **p,
            "price_usd_original": p["price_usd"],
            "price_usd": f"{promo_price:.2f}",
            "discount_pct": pct,
            "promo_label": desc if pct > 0 else None,
        }
    return {"packs": packs_out, "configured": bool(os.environ.get("PAYPAL_CLIENT_ID")),
            "active_promo": {"discount_pct": pct, "description": desc} if pct > 0 else None}


@router.post("/create-order")
@limiter.limit("15/hour")
async def create_order(request: Request, data: CreateOrderIn, user: dict = Depends(get_current_user)):
    pack = PACKS.get(data.pack)
    if not pack:
        raise HTTPException(status_code=400, detail=f"Pack invalido. Validos: {list(PACKS.keys())}")
    # Aplicar descuento de promo activa
    from promos import current_discount_pct
    pct, desc = await current_discount_pct()
    factor = (100 - pct) / 100.0
    final_price = round(float(pack["price_usd"]) * factor, 2)
    base, _, _ = _paypal_env()
    token = _access_token()
    # URLs de retorno: PayPal redirige al frontend con ?paypal=success&token=ORDER_ID
    # o ?paypal=cancel. El RechargeTab detecta el query string y llama capture.
    public = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/") or str(request.base_url).rstrip("/")
    return_url = f"{public}/?paypal=success#/recharge"
    cancel_url = f"{public}/?paypal=cancel#/recharge"
    order_payload = {
        "intent": "CAPTURE",
        "purchase_units": [{
            "reference_id": f"oros-{user['id']}-{uuid.uuid4().hex[:8]}",
            "description": f"{pack['label']}" + (f" ({pct}% OFF)" if pct > 0 else ""),
            "custom_id": f"{user['id']}:{data.pack}",
            "amount": {"currency_code": "USD", "value": f"{final_price:.2f}"},
        }],
        "application_context": {
            "brand_name": "Lluvia App Studio",
            "shipping_preference": "NO_SHIPPING",
            "user_action": "PAY_NOW",
            "return_url": return_url,
            "cancel_url": cancel_url,
        },
    }
    r = requests.post(
        f"{base}/v2/checkout/orders",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=order_payload,
        timeout=20,
    )
    if r.status_code not in (200, 201):
        logger.error(f"PayPal create-order: {r.status_code} {r.text[:300]}")
        raise HTTPException(status_code=502, detail="PayPal create-order fallo")
    j = r.json()
    approve = next((lk["href"] for lk in j.get("links", []) if lk["rel"] == "approve"), None)
    # Persistir intencion
    await _db_ref["db"].paypal_orders.insert_one({
        "order_id": j["id"], "user_id": user["id"], "pack": data.pack,
        "oros": pack["oros"], "amount_usd": pack["price_usd"],
        "status": "CREATED", "approve_url": approve,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return {"order_id": j["id"], "approve_url": approve, "pack": pack}


@router.post("/capture/{order_id}")
async def capture_order(order_id: str, user: dict = Depends(get_current_user)):
    base, _, _ = _paypal_env()
    token = _access_token()
    r = requests.post(
        f"{base}/v2/checkout/orders/{order_id}/capture",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=20,
    )
    if r.status_code not in (200, 201):
        logger.error(f"PayPal capture: {r.status_code} {r.text[:300]}")
        raise HTTPException(status_code=502, detail="PayPal capture fallo")
    j = r.json()
    status = j.get("status", "")
    db = _db_ref["db"]
    order = await db.paypal_orders.find_one({"order_id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Orden no encontrada")
    if order["user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Orden ajena")
    if order.get("status") == "COMPLETED":
        return {"ok": True, "already_processed": True, "balance": await credits_mod.get_balance(user["id"])}
    if status != "COMPLETED":
        await db.paypal_orders.update_one({"order_id": order_id}, {"$set": {"status": status}})
        raise HTTPException(status_code=400, detail=f"Estado de orden: {status}")
    # Acreditar oros
    new_balance = await credits_mod.topup(user["id"], int(order["oros"]),
                                          reason=f"paypal:{order_id}")
    await db.paypal_orders.update_one(
        {"order_id": order_id},
        {"$set": {"status": "COMPLETED", "completed_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"ok": True, "credited_oros": order["oros"], "balance": new_balance}


@router.get("/orders/me")
async def my_orders(user: dict = Depends(get_current_user)):
    db = _db_ref["db"]
    cur = db.paypal_orders.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).limit(30)
    return {"orders": [o async for o in cur]}


# ============================================================
# WEBHOOK PAYPAL — validacion firma via API oficial
# ============================================================
def _verify_paypal_signature(headers: dict, body: bytes) -> bool:
    """Valida la firma del webhook via la API oficial de PayPal.
    Requiere PAYPAL_WEBHOOK_ID en .env. Si no esta seteado, rechaza."""
    webhook_id = os.environ.get("PAYPAL_WEBHOOK_ID", "").strip()
    if not webhook_id:
        logger.error("PAYPAL_WEBHOOK_ID no configurado: rechazando webhook")
        return False
    try:
        import json as _json
        base, _, _ = _paypal_env()
        token = _access_token()
        payload = {
            "auth_algo": headers.get("paypal-auth-algo", ""),
            "cert_url": headers.get("paypal-cert-url", ""),
            "transmission_id": headers.get("paypal-transmission-id", ""),
            "transmission_sig": headers.get("paypal-transmission-sig", ""),
            "transmission_time": headers.get("paypal-transmission-time", ""),
            "webhook_id": webhook_id,
            "webhook_event": _json.loads(body.decode("utf-8")),
        }
        r = requests.post(
            f"{base}/v1/notifications/verify-webhook-signature",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload, timeout=15,
        )
        return r.status_code == 200 and r.json().get("verification_status") == "SUCCESS"
    except Exception as e:
        logger.exception(f"verify webhook fallo: {e}")
        return False


@router.post("/webhook")
@limiter.limit("60/minute")
async def paypal_webhook(request: Request):
    """Recibe eventos PAYMENT.CAPTURE.COMPLETED y acredita oros si la orden
    aun no fue procesada. Blindado con verify-webhook-signature de PayPal."""
    body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}
    if not _verify_paypal_signature(headers, body):
        raise HTTPException(status_code=403, detail="Firma webhook invalida")
    try:
        import json as _json
        event = _json.loads(body.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="JSON invalido")
    etype = event.get("event_type", "")
    if etype != "PAYMENT.CAPTURE.COMPLETED":
        return {"ok": True, "ignored": etype}
    resource = event.get("resource", {}) or {}
    # PayPal mete order_id en supplementary_data.related_ids.order_id
    rel = (resource.get("supplementary_data", {}) or {}).get("related_ids", {}) or {}
    order_id = rel.get("order_id") or resource.get("invoice_id") or ""
    if not order_id:
        return {"ok": True, "no_order_id": True}
    db = _db_ref["db"]
    order = await db.paypal_orders.find_one({"order_id": order_id}, {"_id": 0})
    if not order:
        logger.warning(f"webhook: orden no encontrada {order_id}")
        return {"ok": True, "order_not_found": order_id}
    if order.get("status") == "COMPLETED":
        return {"ok": True, "already_processed": True}
    # Acreditar oros (idempotente)
    await credits_mod.topup(order["user_id"], int(order["oros"]),
                             reason=f"paypal_webhook:{order_id}")
    await db.paypal_orders.update_one(
        {"order_id": order_id},
        {"$set": {"status": "COMPLETED",
                  "completed_at": datetime.now(timezone.utc).isoformat(),
                  "via_webhook": True}},
    )
    return {"ok": True, "credited": True, "oros": order["oros"]}

