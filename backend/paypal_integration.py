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
    return {"packs": PACKS, "configured": bool(os.environ.get("PAYPAL_CLIENT_ID"))}


@router.post("/create-order")
async def create_order(data: CreateOrderIn, user: dict = Depends(get_current_user)):
    pack = PACKS.get(data.pack)
    if not pack:
        raise HTTPException(status_code=400, detail=f"Pack invalido. Validos: {list(PACKS.keys())}")
    base, _, _ = _paypal_env()
    token = _access_token()
    order_payload = {
        "intent": "CAPTURE",
        "purchase_units": [{
            "reference_id": f"oros-{user['id']}-{uuid.uuid4().hex[:8]}",
            "description": pack["label"],
            "custom_id": f"{user['id']}:{data.pack}",
            "amount": {"currency_code": "USD", "value": pack["price_usd"]},
        }],
        "application_context": {
            "brand_name": "Lluvia App Studio",
            "shipping_preference": "NO_SHIPPING",
            "user_action": "PAY_NOW",
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
