"""
========================================
ROUTERS: AUTH + AFILIADOS + VENTAS
========================================
"""

import uuid
import string
import random
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Body, Request
from pydantic import BaseModel, EmailStr, Field
from typing import List, Optional

import auth
from models import (
    LoginIn, AffiliateCreateIn, AffiliateUpdateIn,
    SaleCreateIn, SaleMarkPaidIn,
)
from rate_limit import limiter

router = APIRouter()
_db_ref = {"db": None}


def set_db(db):
    _db_ref["db"] = db


def _db():
    return _db_ref["db"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gen_affiliate_code(name: str) -> str:
    base = "".join(c for c in name.upper() if c.isalpha())[:6] or "AFL"
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"{base}-{suffix}"


def _strip_user(u: dict) -> dict:
    u = dict(u)
    u.pop("_id", None)
    u.pop("password_hash", None)
    return u


# ============================================================
# AUTH
# ============================================================
auth_router = APIRouter(prefix="/auth")


@auth_router.post("/login")
@limiter.limit("8/minute")
async def login(request: Request, payload: LoginIn):
    db = _db()
    email = payload.email.lower().strip()
    user = await db.users.find_one({"email": email})
    if not user:
        raise HTTPException(status_code=401, detail="Credenciales invalidas")
    if not auth.verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Credenciales invalidas")
    if not user.get("active", True):
        raise HTTPException(status_code=403, detail="Usuario desactivado")

    token = auth.create_access_token(user["id"], user["email"], user["role"])
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": _strip_user(user),
    }


@auth_router.get("/me")
async def me(user: dict = Depends(auth.get_current_user)):
    return user


@auth_router.post("/logout")
async def logout(user: dict = Depends(auth.get_current_user)):
    # Bearer token: cliente borra su token. Server-side no hay sesion.
    return {"ok": True}


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=120)
    name: Optional[str] = Field(default=None, max_length=80)


@auth_router.post("/register")
@limiter.limit("6/minute")
async def register(request: Request, payload: RegisterIn):
    """Registro publico de usuarios. Crea un user con role='user' y
    le regala oros de trial (cantidad configurable desde SuperAdmin → Site Content).
    Anti-abuso: limitamos cuantos trials por IP/dia para evitar farming."""
    db = _db()
    email = payload.email.lower().strip()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=409, detail="Email ya registrado")
    if len(payload.password) < 6:
        raise HTTPException(status_code=400, detail="Password minimo 6 chars")

    # Anti-farming: limitar a 3 registros por IP por dia.
    client_ip = request.client.host if request.client else "unknown"
    since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    same_ip_count = await db.users.count_documents({
        "signup_ip": client_ip,
        "created_at": {"$gte": since},
    })
    if same_ip_count >= 3:
        raise HTTPException(
            status_code=429,
            detail="Demasiados registros desde tu red. Espera 24 horas o contáctanos.",
        )

    # Cantidad de oros del trial: configurable desde site_content (default 15)
    trial_oros = 15
    try:
        sc = await db.site_content.find_one({"_id": "main"}, {"_id": 0, "trial_oros": 1})
        if sc and isinstance(sc.get("trial_oros"), int):
            trial_oros = max(0, int(sc["trial_oros"]))
    except Exception:
        pass

    uid = str(uuid.uuid4())
    code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    now = datetime.now(timezone.utc).isoformat()
    user_doc = {
        "id": uid, "email": email,
        "name": (payload.name or email.split("@")[0])[:80],
        "password_hash": auth.hash_password(payload.password),
        "role": "user",
        "affiliate_code": code,
        "active": True,
        "created_at": now,
        "signup_ip": client_ip,
        "trial_oros_given": trial_oros,
    }
    await db.users.insert_one(user_doc)

    import credits as credits_mod
    if trial_oros > 0:
        await credits_mod.topup(uid, trial_oros, reason="trial_signup")

    token = auth.create_access_token(uid, email, "user")
    user_doc.pop("password_hash", None)
    user_doc.pop("_id", None)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": _strip_user(user_doc),
        "trial_oros": trial_oros,
    }


# ============================================================
# AFFILIATES (admin)
# ============================================================
aff_router = APIRouter(prefix="/affiliates")


@aff_router.post("")
async def create_affiliate(
    payload: AffiliateCreateIn,
    admin: dict = Depends(auth.require_admin),
):
    db = _db()
    email = payload.email.lower().strip()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=409, detail="Ese email ya esta registrado")

    code = _gen_affiliate_code(payload.name)
    # Asegurar unicidad
    while await db.users.find_one({"affiliate_code": code}):
        code = _gen_affiliate_code(payload.name)

    user_doc = {
        "id": str(uuid.uuid4()),
        "email": email,
        "password_hash": auth.hash_password(payload.password),
        "name": payload.name,
        "role": "affiliate",
        "active": True,
        "affiliate_code": code,
        "commission_pct": payload.commission_pct,
        "telegram_chat_id": payload.telegram_chat_id,
        "created_at": _now(),
    }
    await db.users.insert_one(user_doc)
    return _strip_user(user_doc)


@aff_router.get("")
async def list_affiliates(admin: dict = Depends(auth.require_admin)):
    db = _db()
    users = await db.users.find(
        {"role": "affiliate"},
        {"_id": 0, "password_hash": 0},
    ).sort("created_at", -1).to_list(500)
    return users


@aff_router.patch("/{affiliate_id}")
async def update_affiliate(
    affiliate_id: str,
    payload: AffiliateUpdateIn,
    admin: dict = Depends(auth.require_admin),
):
    db = _db()
    update = {k: v for k, v in payload.model_dump(exclude_none=True).items()}
    if not update:
        raise HTTPException(status_code=400, detail="Nada para actualizar")
    res = await db.users.update_one(
        {"id": affiliate_id, "role": "affiliate"},
        {"$set": update},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Afiliado no encontrado")
    user = await db.users.find_one({"id": affiliate_id}, {"_id": 0, "password_hash": 0})
    return user


# ============================================================
# SALES
# ============================================================
sales_router = APIRouter(prefix="/sales")


@sales_router.post("")
async def create_sale(
    payload: SaleCreateIn,
    admin: dict = Depends(auth.require_admin),
):
    db = _db()
    code = payload.affiliate_code.strip().upper()
    aff = await db.users.find_one({"affiliate_code": code, "role": "affiliate"})
    if not aff:
        raise HTTPException(status_code=404, detail=f"No existe afiliado con codigo {code}")
    if not aff.get("active", True):
        raise HTTPException(status_code=400, detail=f"El afiliado {code} esta desactivado")

    pct = float(aff.get("commission_pct", 0) or 0)
    commission = round(payload.amount * pct / 100, 2)

    sale = {
        "id": str(uuid.uuid4()),
        "affiliate_id": aff["id"],
        "affiliate_code": code,
        "affiliate_name": aff["name"],
        "amount": payload.amount,
        "commission_pct": pct,
        "commission": commission,
        "product": payload.product,
        "customer": payload.customer,
        "platform": payload.platform or "manual",
        "notes": payload.notes,
        "paid": False,
        "paid_at": None,
        "created_at": _now(),
        "created_by": admin["id"],
    }
    await db.sales.insert_one(sale)
    sale.pop("_id", None)
    return sale


@sales_router.get("")
async def list_sales(user: dict = Depends(auth.get_current_user)):
    db = _db()
    query = {}
    if user["role"] != "admin":
        query["affiliate_id"] = user["id"]
    sales = await db.sales.find(query, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return sales


@sales_router.patch("/{sale_id}/pay")
async def mark_paid(
    sale_id: str,
    payload: SaleMarkPaidIn = Body(...),
    admin: dict = Depends(auth.require_admin),
):
    db = _db()
    update = {"paid": payload.paid, "paid_at": _now() if payload.paid else None}
    res = await db.sales.update_one({"id": sale_id}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Venta no encontrada")
    sale = await db.sales.find_one({"id": sale_id}, {"_id": 0})
    return sale


# ============================================================
# STATS
# ============================================================
stats_router = APIRouter(prefix="/stats")


async def _stats_for(query: dict) -> dict:
    db = _db()
    sales = await db.sales.find(query, {"_id": 0}).to_list(10000)
    total_sales = len(sales)
    total_amount = round(sum(s["amount"] for s in sales), 2)
    total_commission = round(sum(s["commission"] for s in sales), 2)
    paid_commission = round(sum(s["commission"] for s in sales if s.get("paid")), 2)
    pending_commission = round(total_commission - paid_commission, 2)
    last_sale_at = sales[0]["created_at"] if sales and "created_at" in sales[0] else None
    if sales:
        last_sale_at = max(s["created_at"] for s in sales)
    return {
        "total_sales": total_sales,
        "total_amount": total_amount,
        "total_commission": total_commission,
        "paid_commission": paid_commission,
        "pending_commission": pending_commission,
        "last_sale_at": last_sale_at,
    }


@stats_router.get("/me")
async def my_stats(user: dict = Depends(auth.get_current_user)):
    if user["role"] == "admin":
        # Admin no tiene "su" stats personal, devolvemos red entera
        return await _stats_for({})
    s = await _stats_for({"affiliate_id": user["id"]})
    s["affiliate_code"] = user.get("affiliate_code")
    s["name"] = user["name"]
    return s


@stats_router.get("/network")
async def network_stats(admin: dict = Depends(auth.require_admin)):
    """Total de la red + breakdown por afiliado."""
    db = _db()
    overall = await _stats_for({})

    affiliates = await db.users.find(
        {"role": "affiliate"},
        {"_id": 0, "password_hash": 0},
    ).to_list(500)

    breakdown = []
    for aff in affiliates:
        s = await _stats_for({"affiliate_id": aff["id"]})
        breakdown.append({
            "affiliate_id": aff["id"],
            "affiliate_code": aff.get("affiliate_code"),
            "name": aff["name"],
            "active": aff.get("active", True),
            "commission_pct": aff.get("commission_pct"),
            **s,
        })

    breakdown.sort(key=lambda x: x["total_amount"], reverse=True)
    return {
        "overall": overall,
        "affiliates_count": len(affiliates),
        "breakdown": breakdown,
    }


# Combinar todos
router.include_router(auth_router)
router.include_router(aff_router)
router.include_router(sales_router)
router.include_router(stats_router)
