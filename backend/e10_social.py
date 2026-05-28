"""
E10 — Social Automation Agent
Lluvia App Studio — Enterprise ecosystem

Canal social desacoplado, igual que Twilio Voice.
E1 coordina, E10 ejecuta. Additive sobre E4 (no modifica tools existentes).

Plataformas soportadas Phase 1:
  instagram, facebook, tiktok, twitter, linkedin, threads, youtube_shorts

Capacidades:
  - Publicación y programación de contenido (queue → MongoDB)
  - Campañas multi-red con scheduler
  - AI caption / copy gen (Groq)
  - Respuestas IA a DMs/comentarios
  - OAuth por plataforma por tenant (stubs activables con credenciales reales)
  - Analytics y métricas de engagement
  - Anti-abuse: rate limits por plataforma y tenant
  - Integración futura con E4 (campaigns), E7 (paid ads), E9 (analytics)
"""

import logging
import os
import re
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import auth
from rate_limit import limiter
from llm_router import get_client
from e9_emitters import track_call, track_llm_call

logger = logging.getLogger("e10_social")
router = APIRouter(prefix="/e10", tags=["e10-social"])

_db_ref: dict = {"db": None}


def set_db(db) -> None:
    _db_ref["db"] = db


def _db():
    if _db_ref["db"] is None:
        raise RuntimeError("E10: DB no inicializado")
    return _db_ref["db"]

# ══════════════════════════════════════════════════════════════════════════════
# Plataformas soportadas y sus límites de rate
# ══════════════════════════════════════════════════════════════════════════════

SUPPORTED_PLATFORMS = {
    "instagram":     {"max_posts_day": 25,  "dm_reply": True,  "stories": True},
    "facebook":      {"max_posts_day": 25,  "dm_reply": True,  "stories": True},
    "tiktok":        {"max_posts_day": 10,  "dm_reply": False, "stories": False},
    "twitter":       {"max_posts_day": 100, "dm_reply": True,  "stories": False},
    "linkedin":      {"max_posts_day": 5,   "dm_reply": True,  "stories": False},
    "threads":       {"max_posts_day": 25,  "dm_reply": False, "stories": False},
    "youtube_shorts":{"max_posts_day": 3,   "dm_reply": False, "stories": False},
}

# Límites por tenant/día configurables
TENANT_POSTS_DAILY = int(os.environ.get("E10_TENANT_POSTS_DAILY", "50"))

# ══════════════════════════════════════════════════════════════════════════════
# OAuth placeholder — activar con credenciales reales por plataforma
# ══════════════════════════════════════════════════════════════════════════════

async def _get_platform_credentials(db, platform: str, tenant_id: str) -> dict:
    """
    Retorna el connection doc completo (token + platform_user_id + extras).
    Retorna {} si no está conectado.
    """
    conn = await db.e10_connections.find_one(
        {"platform": platform, "tenant_id": tenant_id, "active": True},
        {"_id": 0},
    )
    return conn or {}


async def _get_platform_token(db, platform: str, tenant_id: str) -> Optional[str]:
    """Backward-compat: retorna solo el access_token."""
    creds = await _get_platform_credentials(db, platform, tenant_id)
    return creds.get("access_token")


async def _post_to_platform_api(platform: str, token: str, content: str,
                                  media_url: str = "", hashtags: list = None,
                                  platform_user_id: str = "") -> dict:
    """
    STATUS: REAL (instagram/facebook/twitter/linkedin) via e10_platform_apis.
    STATUS: PARCIAL (tiktok — video only)
    STATUS: STUB (youtube_shorts)
    STATUS: QUEUED (no token — OAuth not configured)
    """
    import e10_platform_apis
    result = await e10_platform_apis.post_to_platform(
        platform=platform,
        token=token,
        content=content,
        media_url=media_url,
        hashtags=hashtags or [],
        platform_user_id=platform_user_id,
    )
    logger.info(f"[E10] post to {platform}: status={result.get('status')} token={bool(token)}")
    return result

# ══════════════════════════════════════════════════════════════════════════════
# Caption & copy generation (Groq)
# ══════════════════════════════════════════════════════════════════════════════

async def _generate_caption(topic: str, platform: str, tone: str = "engaging",
                              lang: str = "es", max_chars: int = 300) -> str:
    client, model = get_client("low")
    platform_rules = {
        "instagram": "Incluye 5-8 hashtags relevantes al final. Tono visual.",
        "tiktok":    "Ultra corto, gancho en primera línea. Incluye 3-5 hashtags trending.",
        "linkedin":  "Tono profesional. Sin hashtags excesivos (max 3). Incluye CTA.",
        "twitter":   f"Máximo {max_chars} caracteres. Conciso e impactante.",
        "facebook":  "Conversacional. Puede ser más largo. Incluye pregunta para engagement.",
        "threads":   "Corto y conversacional. Sin hashtags.",
        "youtube_shorts": "Descripción optimizada para SEO. Incluye timestamps si aplica.",
    }
    rule = platform_rules.get(platform, "Contenido relevante para redes sociales.")
    prompt = (
        f"Crea un caption para {platform} sobre: {topic}\n"
        f"Tono: {tone}\n"
        f"Idioma: {lang}\n"
        f"Regla de plataforma: {rule}\n"
        f"Máximo {max_chars} caracteres.\n"
        f"Responde SOLO con el caption, sin explicaciones."
    )
    try:
        import time as _time
        _t0 = _time.monotonic()
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.7,
        )
        _elapsed = int((_time.monotonic() - _t0) * 1000)
        if hasattr(resp, "usage") and resp.usage:
            await track_llm_call(
                module="e10_social", provider="groq", model=model,
                prompt_tokens=resp.usage.prompt_tokens,
                completion_tokens=resp.usage.completion_tokens,
                elapsed_ms=_elapsed,
            )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        logger.error(f"Caption gen error: {e}")
        return f"✨ {topic} — descubre más en nuestro perfil."


async def _generate_dm_reply(platform: str, sender: str, message: str,
                               agent_persona: str = "") -> str:
    client, model = get_client("low")
    persona = agent_persona or (
        "Eres el agente de atención al cliente en redes sociales. "
        "Responde de forma amigable, breve y profesional."
    )
    prompt = (
        f"{persona}\n\n"
        f"Plataforma: {platform}\n"
        f"Mensaje de @{sender}: {message}\n\n"
        f"Responde en máximo 2 oraciones, en el mismo idioma del mensaje."
    )
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100,
            temperature=0.5,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        logger.error(f"DM reply gen error: {e}")
        return "Gracias por tu mensaje. Te contactamos pronto. 🙌"

# ══════════════════════════════════════════════════════════════════════════════
# Anti-abuse: cuota diaria por tenant
# ══════════════════════════════════════════════════════════════════════════════

async def _check_tenant_post_quota(db, tenant_id: str) -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    doc = await db.e10_quotas.find_one_and_update(
        {"tenant_id": tenant_id, "date": today},
        {"$inc": {"posts": 1}, "$setOnInsert": {"tenant_id": tenant_id, "date": today}},
        upsert=True,
        return_document=True,
    )
    posts = (doc or {}).get("posts", 1)
    if posts > TENANT_POSTS_DAILY:
        raise HTTPException(
            status_code=429,
            detail=f"Tenant {tenant_id!r} excedió cuota diaria de {TENANT_POSTS_DAILY} posts."
        )

# ══════════════════════════════════════════════════════════════════════════════
# Tool functions — expuestas a E1 via console.py dispatch
# ══════════════════════════════════════════════════════════════════════════════

@track_call(module="e10_social", event_prefix="e10.social_post")
async def tool_social_post(content: str, platforms: list = None,
                            tenant_id: str = "default", media_url: str = "",
                            hashtags: list = None, schedule_at: str = "") -> dict:
    """
    Publica (o encola) contenido en una o varias plataformas sociales.
    Si hay token OAuth → intenta publicar real. Sin token → queda en 'queued'.
    """
    db = _db()
    await _check_tenant_post_quota(db, tenant_id)

    platforms = platforms or ["instagram"]
    for p in platforms:
        if p not in SUPPORTED_PLATFORMS:
            raise HTTPException(status_code=400, detail=f"Plataforma {p!r} no soportada. Válidas: {list(SUPPORTED_PLATFORMS)}")

    now = datetime.now(timezone.utc).isoformat()
    post_id = f"P-{uuid.uuid4().hex[:10].upper()}"
    results = {}

    for platform in platforms:
        creds  = await _get_platform_credentials(db, platform, tenant_id)
        token  = creds.get("access_token", "")
        puid   = creds.get("platform_user_id", "")
        api_result = await _post_to_platform_api(
            platform, token, content, media_url, hashtags or [], puid
        )
        results[platform] = api_result

    doc = {
        "post_id":     post_id,
        "tenant_id":   tenant_id,
        "content":     content,
        "platforms":   platforms,
        "media_url":   media_url,
        "hashtags":    hashtags or [],
        "schedule_at": schedule_at or now,
        "status":      "published" if all(r["status"] == "published" for r in results.values()) else "queued",
        "platform_results": results,
        "created_at":  now,
    }
    await db.e10_posts.insert_one(doc)
    return {k: v for k, v in doc.items() if k != "_id"}


async def tool_social_caption_gen(topic: str, platform: str = "instagram",
                                   tone: str = "engaging", lang: str = "es",
                                   tenant_id: str = "default") -> dict:
    """Genera caption optimizado para la plataforma con Groq."""
    if platform not in SUPPORTED_PLATFORMS:
        return {"ok": False, "error": f"Plataforma {platform!r} no soportada"}
    caption = await _generate_caption(topic, platform, tone, lang)
    return {
        "ok":       True,
        "platform": platform,
        "topic":    topic,
        "tone":     tone,
        "caption":  caption,
        "chars":    len(caption),
    }


@track_call(module="e10_social", event_prefix="e10.social_campaign")
async def tool_social_campaign(name: str, posts: list = None, platforms: list = None,
                                schedule: list = None, tenant_id: str = "default",
                                workflow_type: str = "awareness") -> dict:
    """
    Crea una campaña de contenido multi-plataforma.
    posts: lista de {content, media_url, hashtags}
    schedule: lista de ISO datetimes (uno por post)
    """
    db = _db()
    cid = f"C-{uuid.uuid4().hex[:8].upper()}"
    now = datetime.now(timezone.utc).isoformat()
    platforms = platforms or ["instagram"]
    posts = posts or []
    schedule = schedule or []

    # Enqueues cada post de la campaña
    queued = []
    for i, post in enumerate(posts):
        sched = schedule[i] if i < len(schedule) else now
        p_doc = {
            "post_id":     f"{cid}-P{i+1:02d}",
            "campaign_id": cid,
            "tenant_id":   tenant_id,
            "content":     post.get("content", ""),
            "media_url":   post.get("media_url", ""),
            "hashtags":    post.get("hashtags", []),
            "platforms":   platforms,
            "schedule_at": sched,
            "status":      "queued",
            "created_at":  now,
        }
        await db.e10_posts.insert_one(p_doc)
        queued.append(p_doc["post_id"])

    campaign = {
        "campaign_id":   cid,
        "name":          name,
        "tenant_id":     tenant_id,
        "platforms":     platforms,
        "workflow_type": workflow_type,
        "total_posts":   len(posts),
        "queued_posts":  queued,
        "status":        "active",
        "created_at":    now,
        "updated_at":    now,
    }
    await db.e10_campaigns.insert_one(campaign)
    return {k: v for k, v in campaign.items() if k != "_id"}


async def tool_social_dm_respond(platform: str, sender: str, message: str,
                                  tenant_id: str = "default",
                                  agent_persona: str = "") -> dict:
    """
    Genera y (en Phase 2) envía una respuesta IA a un DM/comentario.
    """
    if platform not in SUPPORTED_PLATFORMS:
        return {"ok": False, "error": f"Plataforma {platform!r} no soportada"}
    if not SUPPORTED_PLATFORMS[platform]["dm_reply"]:
        return {"ok": False, "error": f"{platform!r} no soporta DM reply en Phase 1"}

    reply = await _generate_dm_reply(platform, sender, message, agent_persona)
    db = _db()
    now = datetime.now(timezone.utc).isoformat()
    log_doc = {
        "platform": platform, "tenant_id": tenant_id,
        "sender": sender, "incoming": message, "reply": reply,
        "sent": False,  # Phase 2: True cuando se envíe via API real
        "ts": now,
    }
    await db.e10_dm_logs.insert_one(log_doc)
    return {"ok": True, "platform": platform, "sender": sender, "reply": reply, "sent": False}


async def tool_social_connect(platform: str, tenant_id: str = "default",
                               access_token: str = "", token_type: str = "bearer",
                               expires_at: str = "", metadata: dict = None) -> dict:
    """
    Registra credenciales OAuth para una plataforma/tenant.
    En producción este flujo inicia con el redirect OAuth de la plataforma.
    """
    if platform not in SUPPORTED_PLATFORMS:
        raise HTTPException(status_code=400, detail=f"Plataforma {platform!r} no soportada")
    db = _db()
    now = datetime.now(timezone.utc).isoformat()
    conn = {
        "platform":    platform,
        "tenant_id":   tenant_id,
        "access_token": access_token,
        "token_type":  token_type,
        "expires_at":  expires_at,
        "metadata":    metadata or {},
        "active":      bool(access_token),
        "connected_at": now,
        "updated_at":  now,
    }
    await db.e10_connections.update_one(
        {"platform": platform, "tenant_id": tenant_id},
        {"$set": conn}, upsert=True
    )
    return {"ok": True, "platform": platform, "tenant_id": tenant_id, "active": conn["active"]}


async def tool_social_analytics(tenant_id: str = "default", platform: str = "",
                                  period_days: int = 7) -> dict:
    """Métricas de actividad social: posts publicados, campañas, DMs respondidos."""
    db = _db()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=period_days)).isoformat()
    q_base: dict = {"tenant_id": tenant_id, "created_at": {"$gte": cutoff}}
    if platform:
        q_base["platforms"] = platform

    posts = await db.e10_posts.find(q_base, {"_id": 0}).to_list(length=2000)
    campaigns = await db.e10_campaigns.find({"tenant_id": tenant_id, "created_at": {"$gte": cutoff}},
                                             {"_id": 0}).to_list(length=100)
    dms = await db.e10_dm_logs.count_documents(
        {"tenant_id": tenant_id, "ts": {"$gte": cutoff}}
    )

    by_platform: dict = {}
    by_status:   dict = {}
    for p in posts:
        for plt in (p.get("platforms") or []):
            by_platform[plt] = by_platform.get(plt, 0) + 1
        s = p.get("status", "?")
        by_status[s] = by_status.get(s, 0) + 1

    return {
        "tenant_id":          tenant_id,
        "period_days":        period_days,
        "total_posts":        len(posts),
        "total_campaigns":    len(campaigns),
        "dm_responses":       dms,
        "by_platform":        by_platform,
        "by_status":          by_status,
        "published_rate":     round(by_status.get("published", 0) / max(1, len(posts)), 3),
    }

# ══════════════════════════════════════════════════════════════════════════════
# FastAPI endpoints REST
# ══════════════════════════════════════════════════════════════════════════════

class PostIn(BaseModel):
    content: str
    platforms: list[str] = ["instagram"]
    tenant_id: str = "default"
    media_url: str = ""
    hashtags: list[str] = []
    schedule_at: str = ""


class CampaignIn(BaseModel):
    name: str
    tenant_id: str = "default"
    platforms: list[str] = ["instagram"]
    posts: list[dict] = []
    schedule: list[str] = []
    workflow_type: str = "awareness"


class ConnectIn(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: str = ""
    metadata: dict = {}


@router.post("/posts")
@limiter.limit("30/minute")
async def create_post(request, data: PostIn, user: dict = Depends(auth.get_current_user)):
    return await tool_social_post(data.content, data.platforms, data.tenant_id,
                                   data.media_url, data.hashtags, data.schedule_at)


@router.get("/posts")
async def list_posts(tenant_id: str = "default", platform: str = "",
                      status: str = "", limit: int = 50,
                      user: dict = Depends(auth.get_current_user)):
    db = _db()
    q: dict = {"tenant_id": tenant_id}
    if platform:
        q["platforms"] = platform
    if status:
        q["status"] = status
    cur = db.e10_posts.find(q, {"_id": 0}).sort("created_at", -1).limit(limit)
    posts = await cur.to_list(length=limit)
    return {"posts": posts, "total": len(posts)}


@router.post("/campaigns")
async def create_campaign(data: CampaignIn, user: dict = Depends(auth.get_current_user)):
    return await tool_social_campaign(data.name, data.posts, data.platforms,
                                       data.schedule, data.tenant_id, data.workflow_type)


@router.get("/campaigns")
async def list_campaigns(tenant_id: str = "default",
                          user: dict = Depends(auth.get_current_user)):
    db = _db()
    cur = db.e10_campaigns.find({"tenant_id": tenant_id}, {"_id": 0}).sort("created_at", -1).limit(50)
    return {"campaigns": await cur.to_list(length=50)}


@router.post("/caption")
async def gen_caption(topic: str, platform: str = "instagram", tone: str = "engaging",
                       lang: str = "es", user: dict = Depends(auth.get_current_user)):
    return await tool_social_caption_gen(topic, platform, tone, lang)


@router.post("/connect/{platform}")
async def connect_platform(platform: str, data: ConnectIn, tenant_id: str = "default",
                            user: dict = Depends(auth.get_current_user)):
    return await tool_social_connect(platform, tenant_id, data.access_token,
                                      data.token_type, data.expires_at, data.metadata)


@router.get("/connections")
async def list_connections(tenant_id: str = "default",
                            user: dict = Depends(auth.get_current_user)):
    db = _db()
    cur = db.e10_connections.find({"tenant_id": tenant_id}, {"_id": 0, "access_token": 0})
    conns = await cur.to_list(length=20)
    return {"connections": conns, "supported_platforms": list(SUPPORTED_PLATFORMS)}


@router.get("/analytics")
async def analytics(tenant_id: str = "default", platform: str = "", period_days: int = 7,
                     user: dict = Depends(auth.get_current_user)):
    return await tool_social_analytics(tenant_id, platform, period_days)


async def create_indexes() -> None:
    db = _db()
    # e10_connections — (platform, tenant_id) is effectively the PK for OAuth creds
    await db.e10_connections.create_index(
        [("platform", 1), ("tenant_id", 1)], unique=True,
        name="idx_e10_conn_platform_tenant"
    )
    await db.e10_connections.create_index("tenant_id")

    # e10_posts — primary access pattern: by tenant ordered by date, with optional status filter
    await db.e10_posts.create_index(
        [("tenant_id", 1), ("created_at", -1)],
        name="idx_e10_posts_tenant_date"
    )
    await db.e10_posts.create_index(
        [("tenant_id", 1), ("status", 1), ("created_at", -1)],
        name="idx_e10_posts_tenant_status_date"
    )
    # campaign_id for batch lookups; post_id for dedup / external references
    await db.e10_posts.create_index("campaign_id", sparse=True)
    await db.e10_posts.create_index("post_id", unique=True, sparse=True)

    # e10_campaigns — list by tenant, count active
    await db.e10_campaigns.create_index(
        [("tenant_id", 1), ("created_at", -1)],
        name="idx_e10_campaigns_tenant_date"
    )
    await db.e10_campaigns.create_index("status")
    await db.e10_campaigns.create_index("campaign_id", unique=True, sparse=True)

    # e10_dm_logs — analytics count: {tenant_id, ts≥cutoff}
    await db.e10_dm_logs.create_index(
        [("tenant_id", 1), ("ts", -1)],
        name="idx_e10_dm_logs_tenant_ts"
    )

    # e10_quotas — upsert key: (tenant_id, date)
    await db.e10_quotas.create_index(
        [("tenant_id", 1), ("date", 1)], unique=True,
        name="idx_e10_quotas_tenant_date"
    )

    logger.info("[e10] Indexes OK")


@router.get("/status")
async def e10_status(user: dict = Depends(auth.get_current_user)):
    db = _db()
    total_posts     = await db.e10_posts.count_documents({})
    active_campaigns = await db.e10_campaigns.count_documents({"status": "active"})
    connections      = await db.e10_connections.count_documents({"active": True})
    return {
        "agent":        "E10 — Social Automation Agent",
        "version":      "1.0",
        "phase":        1,
        "platforms":    list(SUPPORTED_PLATFORMS),
        "capabilities": [
            "content_scheduling", "multi_platform_campaigns",
            "ai_caption_gen", "dm_ai_responses",
            "oauth_connect", "analytics", "anti_abuse",
        ],
        "phase_2_roadmap": [
            "real_instagram_graph_api", "real_twitter_api_v2",
            "real_linkedin_ugc_api", "real_tiktok_content_api",
            "comment_monitoring", "paid_ads_integration_e7",
        ],
        "stats": {
            "total_posts":        total_posts,
            "active_campaigns":   active_campaigns,
            "active_connections": connections,
        },
    }
