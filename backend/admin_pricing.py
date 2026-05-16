"""
Admin endpoints para gestionar precios de templates + threshold de exportacion.
GET  /api/admin/pricing
PUT  /api/admin/pricing
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

from auth import get_current_user
import pricing as pricing_mod

router = APIRouter(prefix="/admin/pricing", tags=["admin-pricing"])


def _require_admin(user: dict) -> None:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="admin only")


class PricingIn(BaseModel):
    tool_prices: Optional[dict] = Field(default=None, description="Map tool_id -> oros (int >=0)")
    min_balance_for_export: Optional[int] = Field(default=None, ge=0, le=10000)


@router.get("")
async def get_pricing(user: dict = Depends(get_current_user)):
    _require_admin(user)
    return await pricing_mod.get_all_pricing()


@router.put("")
async def update_pricing(data: PricingIn, user: dict = Depends(get_current_user)):
    _require_admin(user)
    return await pricing_mod.set_pricing(
        tool_prices=data.tool_prices,
        min_balance_for_export=data.min_balance_for_export,
        updated_by=user.get("email", "admin"),
    )
