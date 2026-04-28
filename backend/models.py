"""
========================================
MODELOS PYDANTIC
========================================
"""

from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, Literal
from datetime import datetime, timezone
import uuid


# Email simple (mas permisivo que EmailStr para soportar dominios raros como .local)
EmailStr = str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ----------- AUTH -----------
class LoginIn(BaseModel):
    email: EmailStr
    password: str


class LoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


class UserPublic(BaseModel):
    id: str
    email: EmailStr
    name: str
    role: Literal["admin", "affiliate"]
    active: bool = True
    affiliate_code: Optional[str] = None
    commission_pct: Optional[float] = None
    telegram_chat_id: Optional[str] = None
    created_at: str


# ----------- AFFILIATES -----------
class AffiliateCreateIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: EmailStr
    password: str = Field(min_length=6, max_length=80)
    commission_pct: float = Field(ge=0, le=100, default=20.0)
    telegram_chat_id: Optional[str] = None


class AffiliateUpdateIn(BaseModel):
    name: Optional[str] = None
    commission_pct: Optional[float] = Field(default=None, ge=0, le=100)
    active: Optional[bool] = None
    telegram_chat_id: Optional[str] = None


# ----------- SALES -----------
class SaleCreateIn(BaseModel):
    affiliate_code: str
    amount: float = Field(gt=0)
    product: str = Field(min_length=1, max_length=120)
    customer: Optional[str] = None
    platform: Optional[Literal["whatsapp", "telegram", "instagram", "web", "manual"]] = "manual"
    notes: Optional[str] = None


class Sale(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    affiliate_id: str
    affiliate_code: str
    amount: float
    commission_pct: float
    commission: float
    product: str
    customer: Optional[str] = None
    platform: str = "manual"
    notes: Optional[str] = None
    paid: bool = False
    paid_at: Optional[str] = None
    created_at: str = Field(default_factory=_now_iso)


class SaleMarkPaidIn(BaseModel):
    paid: bool = True


# ----------- STATS -----------
class AffiliateStats(BaseModel):
    affiliate_id: str
    affiliate_code: str
    name: str
    total_sales: int
    total_amount: float
    total_commission: float
    pending_commission: float
    paid_commission: float
    last_sale_at: Optional[str] = None
