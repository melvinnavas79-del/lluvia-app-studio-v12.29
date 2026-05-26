"""
E3 — AI Builder / Apps / Agents
Sub-orquestador especializado en generación de apps, templates y diseño de agentes.
Reutiliza workspace_files.py y app_builder.py. No toca console.py ni E1.
"""
import logging
import secrets
from datetime import datetime, timezone
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import auth

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
    # Aplica customizaciones al template
    files = dict(template.get("files", {}))
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

async def tool_app_generator(template_id: str, app_name: str, brand_color: str = "#2563eb",
                              deploy_target: str = "local", tenant_id: str = "",
                              custom_vars: dict = None) -> dict:
    return await _generate_app(
        {"template_id": template_id, "app_name": app_name, "brand_color": brand_color,
         "deploy_target": deploy_target, "tenant_id": tenant_id, "custom_vars": custom_vars or {}},
        actor="e1_tool"
    )


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
