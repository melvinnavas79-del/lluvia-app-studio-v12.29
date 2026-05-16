"""
============================================================
SITE CONTENT — contenido editable de la landing
============================================================
Base para Panel Admin Maestro 2.0:
- hero (titulo, subtitulo, CTA)
- pillars (3 tarjetas grandes)
- links externos (TikTok, IG, Facebook, etc)
- streaming config (urls de radio/video live)

Todo se guarda en un solo doc Mongo con _id="main" y el admin
lo edita desde el panel sin redeploy.

Endpoints:
  GET  /api/site/content           -> publico (lee landing)
  PUT  /api/site/content           -> admin (edita)
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import get_current_user

logger = logging.getLogger("site_content")
router = APIRouter(prefix="/site", tags=["site-content"])

_db_ref: dict = {"db": None}


def set_db(db) -> None:
    _db_ref["db"] = db


# ============================================================
# Modelo de contenido (todo opcional para editar parcial)
# ============================================================
class PillarIn(BaseModel):
    icon: Optional[str] = None        # nombre de icono lucide (Video / Bot / Radio / etc)
    tag: Optional[str] = None         # ej "01 · Multimedia"
    title: Optional[str] = None
    description: Optional[str] = None
    bullets: Optional[list[str]] = None
    accent: Optional[str] = None      # hex color


class StreamingIn(BaseModel):
    radio_stream_url: Optional[str] = None       # url HLS/icecast
    radio_now_playing_url: Optional[str] = None  # metadata endpoint
    video_live_url: Optional[str] = None
    enabled: bool = False


class SocialLinksIn(BaseModel):
    tiktok: Optional[str] = None
    instagram: Optional[str] = None
    facebook: Optional[str] = None
    youtube: Optional[str] = None
    twitter: Optional[str] = None
    linkedin: Optional[str] = None


class SiteContentIn(BaseModel):
    hero_tag: Optional[str] = Field(default=None, max_length=120)
    hero_title: Optional[str] = Field(default=None, max_length=300)
    hero_title_accent: Optional[str] = Field(default=None, max_length=200)  # parte italic
    hero_sub: Optional[str] = Field(default=None, max_length=800)
    hero_cta_primary: Optional[str] = Field(default=None, max_length=80)
    hero_cta_secondary: Optional[str] = Field(default=None, max_length=80)
    trial_oros: Optional[int] = Field(default=None, ge=0, le=500)
    pillars: Optional[list[PillarIn]] = None
    streaming: Optional[StreamingIn] = None
    social: Optional[SocialLinksIn] = None


DEFAULT_CONTENT = {
    "_id": "main",
    "hero_tag": "★ Apps multimedia + Agentes IA · Lanza en minutos",
    "hero_title": "Crea Aplicaciones Profesionales y",
    "hero_title_accent": "Agentes de IA que trabajan por ti 24/7",
    "hero_sub": (
        "Lanza plataformas completas con interfaces avanzadas al estilo de TikTok, "
        "Kwai o sistemas de radio en vivo, mientras configuras agentes de IA "
        "especializados para automatizar peluquerías, tiendas o soporte por WhatsApp. "
        "Todo programado, desplegado y gestionado por IA sin tocar una sola línea de código."
    ),
    "hero_cta_primary": "Empezar gratis con 15 oros →",
    "hero_cta_secondary": "Ya tengo cuenta",
    "trial_oros": 15,  # oros gratis al registrarse (configurable desde SuperAdmin)
    "pillars": [
        {
            "icon": "Video", "tag": "01 · Multimedia",
            "title": "Apps complejas y multimedia",
            "description": (
                "Desarrolla aplicaciones profesionales con feeds de video corto, salas de "
                "streaming en vivo y perfiles dinámicos inspirados en plataformas como TikTok o Likee."
            ),
            "bullets": [
                "Feeds verticales tipo TikTok / Kwai",
                "Streaming en vivo + chats de sala",
                "Perfiles, follows y monetización",
            ],
            "accent": "#EC4899",
        },
        {
            "icon": "Bot", "tag": "02 · Negocios",
            "title": "Agentes personalizados para negocios",
            "description": (
                "Clona empleados virtuales inteligentes entrenados para cualquier nicho: "
                "agendar citas en peluquerías, cerrar ventas, dar soporte y automatizar tu WhatsApp."
            ),
            "bullets": [
                "Citas reales en base de datos",
                "Cobros con PayPal en automático",
                "WhatsApp · Telegram · DM Web",
            ],
            "accent": "#10B981",
        },
        {
            "icon": "Radio", "tag": "03 · Audio Live",
            "title": "Sistemas de radio y audio live",
            "description": (
                "Monta emisoras digitales y plataformas de streaming de audio completas, "
                "monitoreadas y administradas por IA en tiempo real."
            ),
            "bullets": [
                "Emisora 24/7 con DJ-IA",
                "Programación, anuncios y jingles",
                "Estadísticas en vivo y moderación",
            ],
            "accent": "#F59E0B",
        },
    ],
    "streaming": {
        "radio_stream_url": "",
        "radio_now_playing_url": "",
        "video_live_url": "",
        "enabled": False,
    },
    "social": {
        "tiktok": "", "instagram": "", "facebook": "",
        "youtube": "", "twitter": "", "linkedin": "",
    },
    "updated_at": datetime.now(timezone.utc).isoformat(),
}


# ============================================================
# Endpoints
# ============================================================
@router.get("/content")
async def get_content():
    """Publico: cualquier visitante puede leer el contenido."""
    db = _db_ref["db"]
    doc = await db.site_content.find_one({"_id": "main"}, {"_id": 0})
    if not doc:
        # Sembrar default y devolver
        await db.site_content.insert_one(DEFAULT_CONTENT.copy())
        d = DEFAULT_CONTENT.copy()
        d.pop("_id", None)
        return d
    return doc


@router.put("/content")
async def update_content(data: SiteContentIn, user: dict = Depends(get_current_user)):
    """Admin: edita cualquier campo del contenido."""
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="admin only")
    db = _db_ref["db"]
    update = {k: v for k, v in data.model_dump(exclude_none=True).items()}
    if not update:
        raise HTTPException(status_code=400, detail="Nada que actualizar")
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    update["updated_by"] = user.get("email", "admin")
    await db.site_content.update_one({"_id": "main"}, {"$set": update}, upsert=True)
    doc = await db.site_content.find_one({"_id": "main"}, {"_id": 0})
    return doc
