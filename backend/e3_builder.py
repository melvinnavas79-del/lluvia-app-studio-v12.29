"""
E3 — AI Builder / Apps / Agents
Sub-orquestador especializado en generación de apps, templates y diseño de agentes.
Reutiliza workspace_files.py y app_builder.py. No toca console.py ni E1.
"""
import asyncio
import logging
import os
import secrets
from datetime import datetime, timezone
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import auth
from e9_emitters import track_call

logger = logging.getLogger("e3_builder")
router = APIRouter(prefix="/e3", tags=["E3-Builder"])
_db_ref: dict = {"db": None}


def set_db(db) -> None:
    _db_ref["db"] = db


def _db():
    return _db_ref["db"]


# ─── Constantes ───────────────────────────────────────────────────────────────

APP_TYPES = ["web_app", "api_backend", "chatbot", "landing_page", "dashboard", "mobile_pwa"]
BUILD_STATUSES = ["draft", "building", "ready", "failed", "archived"]
STACKS = ["fastapi", "react", "vue", "vanilla_js", "nextjs", "flask"]


# ─── Modelos ──────────────────────────────────────────────────────────────────

class AppTemplateIn(BaseModel):
    name: str
    description: str
    app_type: str = "web_app"
    stack: str = "fastapi"
    tags: List[str] = Field(default_factory=list)
    files: dict = Field(default_factory=dict, description="filename → content")
    preview_url: Optional[str] = None
    price_oros: int = 0
    public: bool = False


class GenerateAppIn(BaseModel):
    template_id: str
    app_name: str
    brand_color: str = "#2563eb"
    tenant_id: Optional[str] = None
    deploy_target: str = Field("local", description="local|render|railway|fly|vps|docker")
    custom_vars: dict = Field(default_factory=dict)
    ai_generate: bool = Field(False, description="Si True y template sin files, genera código vía LLM real")
    ai_provider: str = Field("auto", description="auto|groq|openrouter — provider LLM para generación")
    ai_description: str = Field("", description="Descripción libre de la app para el LLM")


class AgentConfigIn(BaseModel):
    name: str
    emoji: str = "🤖"
    color: str = "#2563eb"
    tagline: str
    system_prompt: str
    tools: List[str] = Field(default_factory=list)
    voice: str = "alloy"
    tenant_id: Optional[str] = None
    model_complexity: str = Field("low", description="low=Groq, high=GPT-4")


# ─── Audit log ────────────────────────────────────────────────────────────────

async def _audit(action: str, actor: str, detail: dict, tenant_id: str = "") -> None:
    try:
        await _db().e3_builder_logs.insert_one({
            "ts": datetime.now(timezone.utc).isoformat(),
            "agent": "E3",
            "action": action,
            "actor": actor,
            "tenant_id": tenant_id,
            "detail": detail,
        })
    except Exception as exc:
        logger.warning(f"[e3] audit failed: {exc}")


# ─── AI Generation constants ──────────────────────────────────────────────────

AI_GEN_TIMEOUT_SECS  = int(os.getenv("E3_AI_GEN_TIMEOUT", "90"))
AI_GEN_QUOTA_MONTHLY = int(os.getenv("E3_AI_GEN_QUOTA_MONTHLY", "50"))  # per tenant

# Prompt version — increment when prompt logic changes to re-train or A/B test
_PROMPT_VERSION = "v2"

_STACK_STARTERS = {
    "fastapi":    ("main.py", "requirements.txt", "README.md"),
    "react":      ("src/App.jsx", "src/index.js", "package.json", "public/index.html"),
    "vue":        ("src/App.vue", "src/main.js", "package.json"),
    "nextjs":     ("pages/index.js", "pages/api/hello.js", "package.json"),
    "vanilla_js": ("index.html", "app.js", "style.css"),
    "flask":      ("app.py", "requirements.txt", "templates/index.html"),
}


async def _check_ai_quota(tenant_id: str, actor: str) -> None:
    """Raises 429 if tenant exceeded monthly AI generation quota."""
    if not tenant_id:
        return
    period = datetime.now(timezone.utc).strftime("%Y-%m")
    doc = await _db().e3_ai_quotas.find_one_and_update(
        {"tenant_id": tenant_id, "period": period},
        {"$inc": {"count": 1}, "$setOnInsert": {"tenant_id": tenant_id, "period": period, "count": 0}},
        upsert=True,
        return_document=True,
    )
    count = (doc or {}).get("count", 1)
    if count > AI_GEN_QUOTA_MONTHLY:
        raise HTTPException(
            status_code=429,
            detail=f"Cuota de generación AI excedida: {AI_GEN_QUOTA_MONTHLY}/mes (tenant={tenant_id})"
        )


async def _ai_generate_files(stack: str, app_name: str, description: str,
                              brand_color: str, provider_hint: str = "auto") -> dict:
    """
    Llama al LLM para generar los archivos starter de la app.
    Retorna dict filename → content.
    Timeout protegido. Falla de LLM → devuelve plantilla mínima funcional.
    """
    from llm_router import get_client
    from e9_emitters import track_llm_call

    target_files = _STACK_STARTERS.get(stack, ("main.py",))
    files_list   = ", ".join(target_files)
    prompt = (
        f"Genera una app de {stack} llamada '{app_name}'.\n"
        f"Descripción: {description or 'App web funcional con buenas prácticas.'}\n"
        f"Color de marca: {brand_color}\n"
        f"Genera estos archivos: {files_list}\n\n"
        f"Responde SOLO con un objeto JSON válido donde las claves son los nombres de archivo "
        f"y los valores son el contenido completo del archivo. Sin explicaciones fuera del JSON.\n"
        f"Ejemplo: {{\"main.py\": \"# contenido...\", \"requirements.txt\": \"fastapi\\n\"}}"
    )

    import json as _json
    import time as _time
    import re as _re

    _hint = "" if provider_hint == "auto" else provider_hint
    client, model = get_client("high" if provider_hint in ("openrouter",) else "low",
                               provider_hint=_hint)
    t0 = _time.monotonic()
    try:
        resp = await asyncio.wait_for(
            client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=3000,
                temperature=0.3,
            ),
            timeout=AI_GEN_TIMEOUT_SECS,
        )
        elapsed_ms = int((_time.monotonic() - t0) * 1000)
        if hasattr(resp, "usage") and resp.usage:
            await track_llm_call(
                module="e3_builder", provider=model.split("/")[0],
                model=model,
                prompt_tokens=resp.usage.prompt_tokens,
                completion_tokens=resp.usage.completion_tokens,
                elapsed_ms=elapsed_ms,
                metadata={"prompt_version": _PROMPT_VERSION, "stack": stack},
            )
        raw = (resp.choices[0].message.content or "").strip()
        # Extract JSON block — LLM sometimes adds markdown fences
        m = _re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, _re.DOTALL)
        if m:
            raw = m.group(1)
        generated = _json.loads(raw)
        if not isinstance(generated, dict):
            raise ValueError("LLM no devolvió dict")
        # Sanitize: solo archivos en la lista esperada
        return {f: str(generated[f]) for f in target_files if f in generated}
    except asyncio.TimeoutError:
        logger.warning(f"[e3] AI gen timeout ({AI_GEN_TIMEOUT_SECS}s) stack={stack} — usando fallback mínimo")
    except Exception as exc:
        logger.warning(f"[e3] AI gen error: {exc} — usando fallback mínimo")

    # Fallback mínimo funcional si LLM falla
    fallback: dict[str, str] = {}
    for fname in target_files:
        fallback[fname] = f"# {app_name} — {fname}\n# Generated by Lluvia App Studio\n"
    return fallback


# ─── Business logic ───────────────────────────────────────────────────────────

async def _create_template(data: dict, actor: str) -> dict:
    tid = "tpl_" + secrets.token_urlsafe(8)
    doc = {
        "id": tid,
        "name": data["name"],
        "description": data.get("description", ""),
        "app_type": data.get("app_type", "web_app"),
        "stack": data.get("stack", "fastapi"),
        "tags": data.get("tags", []),
        "files": data.get("files", {}),
        "preview_url": data.get("preview_url"),
        "price_oros": data.get("price_oros", 0),
        "public": data.get("public", False),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": actor,
        "downloads": 0,
    }
    await _db().e3_app_templates.insert_one(doc)
    await _audit("template_created", actor, {"template_id": tid, "name": data["name"]})
    return {k: v for k, v in doc.items() if k != "_id"}


async def _generate_app(data: dict, actor: str) -> dict:
    template = await _db().e3_app_templates.find_one({"id": data["template_id"]}, {"_id": 0})
    if not template:
        raise HTTPException(status_code=404, detail=f"Template {data['template_id']} no encontrado")

    app_id = "app_" + secrets.token_urlsafe(8)
    files  = dict(template.get("files", {}))

    # Si ai_generate=True y el template no tiene archivos → generación real vía LLM
    if data.get("ai_generate") and not files:
        tenant_id = data.get("tenant_id") or ""
        await _check_ai_quota(tenant_id, actor)
        files = await _ai_generate_files(
            stack=template.get("stack", "fastapi"),
            app_name=data["app_name"],
            description=data.get("ai_description") or template.get("description", ""),
            brand_color=data.get("brand_color", "#2563eb"),
            provider_hint=data.get("ai_provider", "auto"),
        )
        await _audit("ai_files_generated", actor,
                     {"app_id": app_id, "stack": template.get("stack"), "files": list(files.keys())},
                     tenant_id)

    # Aplica customizaciones al template
    for fname, content in files.items():
        content = content.replace("{{APP_NAME}}", data["app_name"])
        content = content.replace("{{BRAND_COLOR}}", data["brand_color"])
        content = content.replace("{{DEPLOY_TARGET}}", data["deploy_target"])
        for k, v in data.get("custom_vars", {}).items():
            content = content.replace(f"{{{{{k}}}}}", str(v))
        files[fname] = content

    doc = {
        "id": app_id,
        "app_name": data["app_name"],
        "template_id": data["template_id"],
        "template_name": template["name"],
        "tenant_id": data.get("tenant_id", ""),
        "stack": template["stack"],
        "brand_color": data["brand_color"],
        "deploy_target": data["deploy_target"],
        "files": files,
        "build_status": "ready",
        "preview_url": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": actor,
        "size_bytes": sum(len(v) for v in files.values()),
    }
    await _db().e3_generated_apps.insert_one(doc)
    # Incrementar contador del template
    await _db().e3_app_templates.update_one({"id": data["template_id"]}, {"$inc": {"downloads": 1}})
    await _audit("app_generated", actor, {"app_id": app_id, "template": data["template_id"]}, data.get("tenant_id", ""))

    return {k: v for k, v in doc.items() if k != "_id"}


async def _save_agent_config(data: dict, actor: str) -> dict:
    cfg_id = "agcfg_" + secrets.token_urlsafe(8)
    doc = {
        "id": cfg_id,
        "name": data["name"],
        "emoji": data.get("emoji", "🤖"),
        "color": data.get("color", "#2563eb"),
        "tagline": data.get("tagline", ""),
        "system_prompt": data["system_prompt"],
        "tools": data.get("tools", []),
        "voice": data.get("voice", "alloy"),
        "tenant_id": data.get("tenant_id", ""),
        "model_complexity": data.get("model_complexity", "low"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": actor,
    }
    await _db().e3_agent_configs.insert_one(doc)
    await _audit("agent_config_saved", actor, {"cfg_id": cfg_id, "name": data["name"]}, data.get("tenant_id", ""))
    return {k: v for k, v in doc.items() if k != "_id"}


# ─── Tool functions ────────────────────────────────────────────────────────────

@track_call(module="e3_builder", event_prefix="e3.app_generator")
async def tool_app_generator(template_id: str, app_name: str, brand_color: str = "#2563eb",
                              deploy_target: str = "local", tenant_id: str = "",
                              custom_vars: dict = None) -> dict:
    return await _generate_app(
        {"template_id": template_id, "app_name": app_name, "brand_color": brand_color,
         "deploy_target": deploy_target, "tenant_id": tenant_id, "custom_vars": custom_vars or {}},
        actor="e1_tool"
    )


@track_call(module="e3_builder", event_prefix="e3.template_manager")
async def tool_template_manager(action: str, template_id: str = "", data: dict = None) -> dict:
    if action == "list":
        cur = _db().e3_app_templates.find({}, {"_id": 0, "files": 0}).limit(100)
        return {"templates": [t async for t in cur]}
    if action == "get" and template_id:
        doc = await _db().e3_app_templates.find_one({"id": template_id}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="Template no encontrado")
        return doc
    if action == "create" and data:
        return await _create_template(data, actor="e1_tool")
    raise ValueError(f"action desconocida o parámetros faltantes: {action}")


@track_call(module="e3_builder", event_prefix="e3.agent_designer")
async def tool_agent_designer(name: str, system_prompt: str, tagline: str = "",
                               tools: list = None, tenant_id: str = "",
                               model_complexity: str = "low") -> dict:
    return await _save_agent_config(
        {"name": name, "system_prompt": system_prompt, "tagline": tagline,
         "tools": tools or [], "tenant_id": tenant_id, "model_complexity": model_complexity},
        actor="e1_tool"
    )


async def tool_preview_builder(app_id: str) -> dict:
    doc = await _db().e3_generated_apps.find_one({"id": app_id}, {"_id": 0, "files": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="App no encontrada")
    return {"app_id": app_id, "stack": doc.get("stack"), "build_status": doc.get("build_status"),
            "note": "Preview via workspace_preview — configurar preview_url para live"}


async def tool_build_validator(app_id: str) -> dict:
    doc = await _db().e3_generated_apps.find_one({"id": app_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="App no encontrada")
    files = doc.get("files", {})
    issues = [f for f in files if not files[f].strip()]
    return {
        "app_id": app_id,
        "files_count": len(files),
        "empty_files": issues,
        "valid": len(issues) == 0,
        "size_bytes": doc.get("size_bytes", 0),
    }


async def tool_hot_reload_trigger(app_id: str) -> dict:
    await _db().e3_generated_apps.update_one(
        {"id": app_id}, {"$set": {"last_reload": datetime.now(timezone.utc).isoformat()}}
    )
    return {"app_id": app_id, "reloaded_at": datetime.now(timezone.utc).isoformat(), "ok": True}


# ─── FastAPI endpoints ─────────────────────────────────────────────────────────

@router.post("/templates")
async def create_template(data: AppTemplateIn, user: dict = Depends(auth.get_current_user)):
    return await _create_template(data.model_dump(), actor=user["email"])


@router.get("/templates")
async def list_templates(public_only: bool = False, user: dict = Depends(auth.get_current_user)):
    q = {"public": True} if public_only else {}
    cur = _db().e3_app_templates.find(q, {"_id": 0, "files": 0}).limit(100)
    return {"templates": [t async for t in cur]}


@router.get("/templates/{tid}")
async def get_template(tid: str, user: dict = Depends(auth.get_current_user)):
    doc = await _db().e3_app_templates.find_one({"id": tid}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Template no encontrado")
    return doc


@router.post("/apps/generate")
async def generate_app(data: GenerateAppIn, user: dict = Depends(auth.get_current_user)):
    return await _generate_app(data.model_dump(), actor=user["email"])


@router.get("/apps")
async def list_apps(tenant_id: Optional[str] = None, user: dict = Depends(auth.get_current_user)):
    q = {"tenant_id": tenant_id} if tenant_id else {}
    cur = _db().e3_generated_apps.find(q, {"_id": 0, "files": 0}).sort("created_at", -1).limit(50)
    return {"apps": [a async for a in cur]}


@router.get("/apps/{app_id}")
async def get_app(app_id: str, user: dict = Depends(auth.get_current_user)):
    doc = await _db().e3_generated_apps.find_one({"id": app_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="App no encontrada")
    return doc


@router.post("/agents")
async def save_agent_config(data: AgentConfigIn, user: dict = Depends(auth.get_current_user)):
    return await _save_agent_config(data.model_dump(), actor=user["email"])


@router.get("/agents")
async def list_agent_configs(tenant_id: Optional[str] = None,
                              user: dict = Depends(auth.get_current_user)):
    q = {"tenant_id": tenant_id} if tenant_id else {}
    cur = _db().e3_agent_configs.find(q, {"_id": 0}).limit(100)
    return {"agents": [a async for a in cur]}


async def create_indexes() -> None:
    db = _db()

    # e3_app_templates — lookups by id (every generate + get), public filter
    await db.e3_app_templates.create_index("id", unique=True)
    await db.e3_app_templates.create_index("public")

    # e3_generated_apps — lookup by id + list by tenant sorted by date
    await db.e3_generated_apps.create_index("id", unique=True)
    await db.e3_generated_apps.create_index(
        [("tenant_id", 1), ("created_at", -1)],
        name="idx_e3_apps_tenant_date"
    )
    await db.e3_generated_apps.create_index("template_id")

    # e3_agent_configs — lookup by id + per-tenant listing
    await db.e3_agent_configs.create_index("id", unique=True)
    await db.e3_agent_configs.create_index("tenant_id", sparse=True)

    # e3_builder_logs — audit queries by tenant/time
    await db.e3_builder_logs.create_index(
        [("tenant_id", 1), ("ts", -1)],
        name="idx_e3_logs_tenant_ts"
    )

    # e3_ai_quotas — upsert key: (tenant_id, period) — monthly quota enforcement
    await db.e3_ai_quotas.create_index(
        [("tenant_id", 1), ("period", 1)], unique=True,
        name="idx_e3_ai_quotas_tenant_period"
    )

    logger.info("[e3] Indexes OK")
