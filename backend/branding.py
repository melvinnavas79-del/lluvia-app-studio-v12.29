"""
========================================
BRANDING - WHITE LABEL PERSONALIZABLE
========================================

Permite al admin personalizar logo, colores y nombre del producto
sin tocar codigo. Una sola coleccion 'branding' con un unico documento.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import datetime, timezone
import re

import auth

HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

router = APIRouter(prefix="/branding")
_db_ref = {"db": None}


def set_db(db):
    _db_ref["db"] = db


def _db():
    return _db_ref["db"]


DEFAULT_BRANDING = {
    "product_name": "Lluvia App Studio",
    "tagline": "Agentes inteligentes que trabajan por ti 24/7.",
    "primary_color": "#0f172a",      # charcoal navy premium
    "accent_color": "#2563eb",       # azul corporativo
    "background_color": "#fdfbf7",   # warm off-white premium
    "text_color": "#111827",         # texto charcoal
    "default_theme": "light",        # tema por defecto (light | dark)
    "logo_data_url": "",
    "company_name": "Lluvia App Studio",
    "support_email": "melvinnavas79@gmail.com",
}


class BrandingIn(BaseModel):
    product_name: Optional[str] = Field(default=None, max_length=80)
    tagline: Optional[str] = Field(default=None, max_length=200)
    primary_color: Optional[str] = Field(default=None, max_length=20)
    accent_color: Optional[str] = Field(default=None, max_length=20)
    background_color: Optional[str] = Field(default=None, max_length=20)
    text_color: Optional[str] = Field(default=None, max_length=20)
    default_theme: Optional[str] = Field(default=None, max_length=10)
    logo_data_url: Optional[str] = Field(default=None, max_length=2_000_000)  # ~1.5MB base64
    company_name: Optional[str] = Field(default=None, max_length=120)
    support_email: Optional[str] = Field(default=None, max_length=120)

    @field_validator("primary_color", "accent_color", "background_color", "text_color")
    @classmethod
    def validate_hex(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return v
        if not HEX_RE.match(v):
            raise ValueError("Color invalido. Usa formato #RRGGBB (6 dig hex)")
        return v.lower()

    @field_validator("default_theme")
    @classmethod
    def validate_theme(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return v
        if v not in ("light", "dark"):
            raise ValueError("default_theme debe ser 'light' o 'dark'")
        return v


async def _get_branding_doc() -> dict:
    db = _db()
    doc = await db.branding.find_one({"_id": "main"}, {"_id": 0})
    if not doc:
        return dict(DEFAULT_BRANDING)
    # Merge sobre defaults (asegura todos los campos presentes)
    merged = dict(DEFAULT_BRANDING)
    merged.update(doc)
    return merged


@router.get("")
async def get_branding():
    """Publico: la pantalla de login y dashboards lo leen sin auth."""
    return await _get_branding_doc()


@router.put("")
async def update_branding(
    payload: BrandingIn,
    admin: dict = Depends(auth.require_admin),
):
    db = _db()
    update = {k: v for k, v in payload.model_dump(exclude_none=True).items()}
    if not update:
        raise HTTPException(status_code=400, detail="Nada para actualizar")

    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    update["updated_by"] = admin["email"]

    await db.branding.update_one(
        {"_id": "main"},
        {"$set": update},
        upsert=True,
    )
    return await _get_branding_doc()


@router.post("/reset")
async def reset_branding(admin: dict = Depends(auth.require_admin)):
    db = _db()
    await db.branding.delete_one({"_id": "main"})
    return await _get_branding_doc()
