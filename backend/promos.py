"""
Promociones automaticas para PayPal packs.
- Admin crea reglas (ej: 20% off sabados, 50% off dia 15).
- /paypal/packs aplica el descuento mas grande activo al precio.
"""

from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import get_current_user

router = APIRouter(prefix="/promos", tags=["promos"])
_db_ref: dict = {"db": None}


def set_db(db):
    _db_ref["db"] = db


class PromoIn(BaseModel):
    rule_id: str = Field(min_length=2, max_length=40)
    description: str = Field(max_length=200)
    discount_pct: int = Field(ge=1, le=80)
    days_of_week: list[int] = Field(default_factory=list)  # 0=lun..6=dom
    days_of_month: list[int] = Field(default_factory=list)
    active: bool = True


@router.get("")
async def list_promos(_=Depends(get_current_user)):
    cur = _db_ref["db"].promos.find({}, {"_id": 0}).sort("created_at", -1)
    return {"promos": [p async for p in cur]}


@router.post("")
async def create_promo(data: PromoIn, user: dict = Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="solo admin")
    doc = data.model_dump()
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    doc["created_by"] = user["id"]
    db = _db_ref["db"]
    await db.promos.update_one({"rule_id": data.rule_id}, {"$set": doc}, upsert=True)
    return {"ok": True, "rule_id": data.rule_id}


@router.delete("/{rule_id}")
async def delete_promo(rule_id: str, user: dict = Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="solo admin")
    res = await _db_ref["db"].promos.delete_one({"rule_id": rule_id})
    return {"deleted": res.deleted_count}


async def current_discount_pct() -> tuple[int, Optional[str]]:
    """Devuelve (descuento%, descripcion) de la promo activa con mayor %."""
    now = datetime.now(timezone.utc)
    dow = now.weekday()  # 0=lun..6=dom
    dom = now.day
    best = 0
    best_desc = None
    async for p in _db_ref["db"].promos.find({"active": True}, {"_id": 0}):
        applies = False
        if p.get("days_of_week") and dow in p["days_of_week"]:
            applies = True
        if p.get("days_of_month") and dom in p["days_of_month"]:
            applies = True
        if not p.get("days_of_week") and not p.get("days_of_month"):
            applies = True  # promo permanente
        if applies and p.get("discount_pct", 0) > best:
            best = p["discount_pct"]
            best_desc = p.get("description")
    return best, best_desc
