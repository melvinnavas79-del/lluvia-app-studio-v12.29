"""
E4 — Sales / Marketing / Growth
Sub-orquestador especializado en leads, funnels, campañas y contenido viral.
Usa Groq (vía llm_router) para generación de copies y hooks — eficiente en costo.
No toca console.py ni E1.
"""
import logging
import secrets
from datetime import datetime, timezone
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import auth
import llm_router
from e9_emitters import track_call, track_llm_call

logger = logging.getLogger("e4_sales")
router = APIRouter(prefix="/e4", tags=["E4-Sales"])
_db_ref: dict = {"db": None}


def set_db(db) -> None:
    _db_ref["db"] = db


def _db():
    return _db_ref["db"]


# ─── Constantes ───────────────────────────────────────────────────────────────

LEAD_STAGES = ["new", "contacted", "qualified", "demo", "proposal", "negotiation", "won", "lost"]
CAMPAIGN_TYPES = ["email", "whatsapp", "telegram", "social", "ads", "seo"]
FUNNEL_STAGES_DEFAULT = ["awareness", "interest", "consideration", "intent", "purchase", "retention"]


# ─── Modelos ──────────────────────────────────────────────────────────────────

class LeadIn(BaseModel):
    email: str
    name: Optional[str] = None
    phone: Optional[str] = None
    source: str = "organic"
    product_interest: Optional[str] = None
    tenant_id: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    notes: Optional[str] = None


class CampaignIn(BaseModel):
    name: str
    campaign_type: str = "email"
    tenant_id: Optional[str] = None
    target_audience: Optional[str] = None
    content: Optional[str] = None
    schedule_at: Optional[str] = None
    budget_usd: float = 0.0


class FunnelIn(BaseModel):
    name: str
    tenant_id: Optional[str] = None
    stages: List[str] = Field(default_factory=list)
    product: Optional[str] = None
    goal: Optional[str] = None


class ContentIn(BaseModel):
    product: str
    platform: str = Field(..., description="tiktok|instagram|twitter|linkedin|email")
    tone: str = Field("professional", description="professional|casual|urgent|funny")
    tenant_id: Optional[str] = None


# ─── Audit log ────────────────────────────────────────────────────────────────

async def _audit(action: str, actor: str, detail: dict, tenant_id: str = "") -> None:
    try:
        await _db().e4_sales_logs.insert_one({
            "ts": datetime.now(timezone.utc).isoformat(),
            "agent": "E4",
            "action": action,
            "actor": actor,
            "tenant_id": tenant_id,
            "detail": detail,
        })
    except Exception as exc:
        logger.warning(f"[e4] audit failed: {exc}")


# ─── Business logic ───────────────────────────────────────────────────────────

async def _create_lead(data: dict, actor: str) -> dict:
    existing = await _db().e4_leads.find_one({"email": data["email"], "tenant_id": data.get("tenant_id", "")})
    if existing:
        raise HTTPException(status_code=409, detail=f"Lead con email {data['email']} ya existe en este tenant")

    lead_id = "lead_" + secrets.token_urlsafe(8)
    doc = {
        "id": lead_id,
        "email": data["email"],
        "name": data.get("name"),
        "phone": data.get("phone"),
        "source": data.get("source", "organic"),
        "product_interest": data.get("product_interest"),
        "tenant_id": data.get("tenant_id", ""),
        "tags": data.get("tags", []),
        "notes": data.get("notes"),
        "stage": "new",
        "score": 0,
        "converted": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": actor,
        "last_contact": None,
        "follow_up_at": None,
    }
    await _db().e4_leads.insert_one(doc)
    await _audit("lead_created", actor, {"lead_id": lead_id, "email": data["email"]}, data.get("tenant_id", ""))
    return {k: v for k, v in doc.items() if k != "_id"}


async def _update_lead_stage(lead_id: str, stage: str, actor: str, score_delta: int = 0) -> dict:
    if stage not in LEAD_STAGES:
        raise HTTPException(status_code=400, detail=f"Stage inválido: {stage}")
    update: dict = {"stage": stage, "last_contact": datetime.now(timezone.utc).isoformat()}
    if stage == "won":
        update["converted"] = True
    await _db().e4_leads.update_one({"id": lead_id}, {"$set": update, "$inc": {"score": score_delta}})
    await _audit("lead_stage_updated", actor, {"lead_id": lead_id, "stage": stage})
    doc = await _db().e4_leads.find_one({"id": lead_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    return doc


async def _create_campaign(data: dict, actor: str) -> dict:
    camp_id = "camp_" + secrets.token_urlsafe(8)
    doc = {
        "id": camp_id,
        "name": data["name"],
        "campaign_type": data.get("campaign_type", "email"),
        "tenant_id": data.get("tenant_id", ""),
        "target_audience": data.get("target_audience"),
        "content": data.get("content"),
        "schedule_at": data.get("schedule_at"),
        "budget_usd": data.get("budget_usd", 0.0),
        "status": "draft",
        "sent_count": 0,
        "open_rate": 0.0,
        "conversion_rate": 0.0,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": actor,
    }
    await _db().e4_campaigns.insert_one(doc)
    await _audit("campaign_created", actor, {"camp_id": camp_id}, data.get("tenant_id", ""))
    return {k: v for k, v in doc.items() if k != "_id"}


async def _generate_viral_hook(product: str, platform: str, tone: str = "professional") -> dict:
    """Usa Groq (llama rápido) para generar hooks virales — eficiente en costo."""
    client, model = llm_router.get_client("low")
    prompt = (
        f"Genera 3 hooks virales cortos y poderosos para {platform} sobre el producto: '{product}'. "
        f"Tono: {tone}. "
        f"Cada hook debe tener máximo 2 oraciones. Formato: lista numerada. Sin emojis excesivos. "
        f"Enfócate en beneficios concretos y urgencia."
    )
    try:
        import time as _time
        _t0 = _time.monotonic()
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
            temperature=0.8,
        )
        _elapsed = int((_time.monotonic() - _t0) * 1000)
        if hasattr(resp, "usage") and resp.usage:
            await track_llm_call(
                module="e4_sales", provider="groq", model=model,
                prompt_tokens=resp.usage.prompt_tokens,
                completion_tokens=resp.usage.completion_tokens,
                elapsed_ms=_elapsed,
            )
        hooks_text = resp.choices[0].message.content or ""
        hooks = [h.strip() for h in hooks_text.split("\n") if h.strip() and h.strip()[0].isdigit()]
        return {"product": product, "platform": platform, "tone": tone, "hooks": hooks, "model": model}
    except Exception as exc:
        logger.warning(f"[e4] viral hook generation failed: {exc}")
        return {"product": product, "platform": platform, "hooks": [
            f"¿Querés automatizar tu negocio con IA? {product} lo hace por vos.",
            f"En menos de 5 minutos tenés {product} trabajando 24/7.",
            f"Los negocios que usan IA como {product} crecen 3x más rápido.",
        ], "model": "fallback"}


async def _seo_optimize(content: str, keywords: list) -> dict:
    """Usa Groq para sugerencias SEO — bajo costo."""
    client, model = llm_router.get_client("low")
    kw_str = ", ".join(keywords[:10])
    prompt = (
        f"Analiza el siguiente contenido y dame 5 sugerencias concretas de SEO "
        f"para rankear con las keywords: {kw_str}.\n\nContenido:\n{content[:500]}\n\n"
        f"Sé específico y accionable. Máximo 2 líneas por sugerencia."
    )
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400,
        )
        return {"keywords": keywords, "suggestions": resp.choices[0].message.content, "model": model}
    except Exception as exc:
        return {"keywords": keywords, "suggestions": "SEO analysis unavailable", "error": str(exc)}


# ─── Tool functions ────────────────────────────────────────────────────────────

async def tool_lead_manager(action: str, email: str = "", stage: str = "",
                             lead_id: str = "", tenant_id: str = "",
                             data: dict = None) -> dict:
    if action == "create" and email:
        payload = data or {}
        payload["email"] = email
        payload["tenant_id"] = tenant_id
        return await _create_lead(payload, actor="e1_tool")
    if action == "update_stage" and lead_id and stage:
        return await _update_lead_stage(lead_id, stage, "e1_tool")
    if action == "list":
        q = {"tenant_id": tenant_id} if tenant_id else {}
        cur = _db().e4_leads.find(q, {"_id": 0}).sort("created_at", -1).limit(100)
        return {"leads": [l async for l in cur]}
    raise ValueError(f"action desconocida o parámetros faltantes: {action}")


@track_call(module="e4_sales", event_prefix="e4.campaign_builder")
async def tool_campaign_builder(name: str, campaign_type: str = "email",
                                 tenant_id: str = "", content: str = "",
                                 target_audience: str = "") -> dict:
    return await _create_campaign(
        {"name": name, "campaign_type": campaign_type, "tenant_id": tenant_id,
         "content": content, "target_audience": target_audience},
        actor="e1_tool"
    )


async def tool_funnel_designer(name: str, stages: list = None, product: str = "",
                                tenant_id: str = "", goal: str = "") -> dict:
    funnel_id = "fun_" + secrets.token_urlsafe(8)
    doc = {
        "id": funnel_id,
        "name": name,
        "stages": stages or FUNNEL_STAGES_DEFAULT,
        "product": product,
        "tenant_id": tenant_id,
        "goal": goal,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": "e1_tool",
    }
    await _db().e4_funnels.insert_one(doc)
    return {k: v for k, v in doc.items() if k != "_id"}


async def tool_viral_hook_gen(product: str, platform: str = "tiktok", tone: str = "professional") -> dict:
    return await _generate_viral_hook(product, platform, tone)


async def tool_seo_optimizer(content: str, keywords: list = None) -> dict:
    return await _seo_optimize(content, keywords or [])


@track_call(module="e4_sales", event_prefix="e4.social_scheduler")
async def tool_social_scheduler(content: str, platforms: list = None,
                                 schedule_at: str = "", tenant_id: str = "") -> dict:
    sched_id = "sched_" + secrets.token_urlsafe(8)
    doc = {
        "id": sched_id,
        "content": content,
        "platforms": platforms or ["instagram"],
        "tenant_id": tenant_id,
        "schedule_at": schedule_at or datetime.now(timezone.utc).isoformat(),
        "status": "scheduled",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await _db().e4_scheduled_content.insert_one(doc)
    return {k: v for k, v in doc.items() if k != "_id"}


# ─── FastAPI endpoints ─────────────────────────────────────────────────────────

@router.post("/leads")
async def create_lead(data: LeadIn, user: dict = Depends(auth.get_current_user)):
    return await _create_lead(data.model_dump(), actor=user["email"])


@router.get("/leads")
async def list_leads(tenant_id: Optional[str] = None, stage: Optional[str] = None,
                      user: dict = Depends(auth.get_current_user)):
    q: dict = {}
    if tenant_id:
        q["tenant_id"] = tenant_id
    if stage:
        q["stage"] = stage
    cur = _db().e4_leads.find(q, {"_id": 0}).sort("created_at", -1).limit(200)
    return {"leads": [l async for l in cur]}


@router.patch("/leads/{lead_id}/stage")
async def update_lead_stage(lead_id: str, stage: str, score_delta: int = 10,
                             user: dict = Depends(auth.get_current_user)):
    return await _update_lead_stage(lead_id, stage, user["email"], score_delta)


@router.post("/campaigns")
async def create_campaign(data: CampaignIn, user: dict = Depends(auth.get_current_user)):
    return await _create_campaign(data.model_dump(), actor=user["email"])


@router.get("/campaigns")
async def list_campaigns(tenant_id: Optional[str] = None, user: dict = Depends(auth.get_current_user)):
    q = {"tenant_id": tenant_id} if tenant_id else {}
    cur = _db().e4_campaigns.find(q, {"_id": 0}).sort("created_at", -1).limit(50)
    return {"campaigns": [c async for c in cur]}


@router.post("/funnels")
async def create_funnel(data: FunnelIn, user: dict = Depends(auth.get_current_user)):
    return await tool_funnel_designer(data.name, data.stages or FUNNEL_STAGES_DEFAULT,
                                       data.product or "", data.tenant_id or "", data.goal or "")


@router.get("/funnels")
async def list_funnels(tenant_id: Optional[str] = None, user: dict = Depends(auth.get_current_user)):
    q = {"tenant_id": tenant_id} if tenant_id else {}
    cur = _db().e4_funnels.find(q, {"_id": 0}).limit(50)
    return {"funnels": [f async for f in cur]}


@router.post("/content/hook")
async def generate_hook(data: ContentIn, user: dict = Depends(auth.get_current_user)):
    return await _generate_viral_hook(data.product, data.platform, data.tone)


@router.post("/content/seo")
async def seo_optimize(content: str, keywords: str = "", user: dict = Depends(auth.get_current_user)):
    kw_list = [k.strip() for k in keywords.split(",") if k.strip()]
    return await _seo_optimize(content, kw_list)
