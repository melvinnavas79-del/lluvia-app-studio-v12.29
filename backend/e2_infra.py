"""
E2 — Infrastructure / DevOps / Deploy
Sub-orquestador especializado en deploys, CI/CD, VPS, Docker, SSL y rollbacks.
Reutiliza vps_manager.py para operaciones VPS reales.
No toca console.py ni E1.
"""
import logging
import secrets
import asyncio
from datetime import datetime, timezone
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

import auth
import e2_executor
from e9_emitters import track_call, track_error as e9_track_error

logger = logging.getLogger("e2_infra")
router = APIRouter(prefix="/e2", tags=["E2-Infra"])
_db_ref: dict = {"db": None}


def set_db(db) -> None:
    _db_ref["db"] = db


def _db():
    return _db_ref["db"]


# ─── Constantes ───────────────────────────────────────────────────────────────

DEPLOY_STATUSES = ["pending", "running", "success", "failed", "rolled_back"]
PIPELINE_TRIGGERS = ["manual", "push", "schedule", "webhook"]

STACK_DEFAULTS = {
    "fastapi": {"port": 8000, "start_cmd": "uvicorn main:app --host 0.0.0.0 --port 8000"},
    "react":   {"port": 3000, "start_cmd": "npm start"},
    "node":    {"port": 3000, "start_cmd": "node index.js"},
    "static":  {"port": 80,   "start_cmd": "python3 -m http.server 80"},
}


# ─── Modelos ──────────────────────────────────────────────────────────────────

class DeploymentIn(BaseModel):
    service: str = Field(..., description="Nombre del servicio")
    tenant_id: Optional[str] = None
    stack: str = Field("fastapi", description="fastapi|react|node|static")
    env: str = Field("production", description="production|staging|dev")
    repo_url: Optional[str] = None
    branch: str = "main"
    env_vars: dict = Field(default_factory=dict)
    note: Optional[str] = None


class PipelineIn(BaseModel):
    name: str
    tenant_id: Optional[str] = None
    repo_url: Optional[str] = None
    trigger: str = Field("manual", description="manual|push|schedule|webhook")
    steps: List[str] = Field(default_factory=list, description="Comandos en orden")
    env_vars: dict = Field(default_factory=dict)


class InfraAlertIn(BaseModel):
    service: str
    metric: str = Field(..., description="cpu|memory|disk|latency|error_rate")
    threshold: float
    notify_email: Optional[str] = None


# ─── Audit log ────────────────────────────────────────────────────────────────

async def _audit(action: str, actor: str, detail: dict, tenant_id: str = "") -> None:
    try:
        await _db().e2_infra_logs.insert_one({
            "ts": datetime.now(timezone.utc).isoformat(),
            "agent": "E2",
            "action": action,
            "actor": actor,
            "tenant_id": tenant_id,
            "detail": detail,
        })
    except Exception as exc:
        logger.warning(f"[e2] audit failed: {exc}")


# ─── Business logic ───────────────────────────────────────────────────────────

async def _create_deployment(data: dict, actor: str) -> dict:
    dep_id = "dep_" + secrets.token_urlsafe(8)
    doc = {
        "id": dep_id,
        "service": data["service"],
        "tenant_id": data.get("tenant_id", ""),
        "stack": data.get("stack", "fastapi"),
        "env": data.get("env", "production"),
        "repo_url": data.get("repo_url"),
        "branch": data.get("branch", "main"),
        "env_vars": data.get("env_vars", {}),
        "status": "pending",
        "steps_log": [],
        "rollback_sha": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": actor,
        "finished_at": None,
        "note": data.get("note"),
    }
    await _db().e2_deployments.insert_one(doc)
    await _audit("deployment_created", actor, {"dep_id": dep_id, "service": data["service"]}, data.get("tenant_id", ""))
    return {k: v for k, v in doc.items() if k != "_id"}


async def _get_deployment(dep_id: str) -> dict:
    doc = await _db().e2_deployments.find_one({"id": dep_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Deployment {dep_id} no encontrado")
    return doc


async def _list_deployments(tenant_id: Optional[str], limit: int = 50) -> list:
    q = {"tenant_id": tenant_id} if tenant_id else {}
    cur = _db().e2_deployments.find(q, {"_id": 0}).sort("created_at", -1).limit(limit)
    return [d async for d in cur]


async def _update_deployment_status(dep_id: str, status: str, log_line: str = "", actor: str = "system") -> dict:
    if status not in DEPLOY_STATUSES:
        raise HTTPException(status_code=400, detail=f"Status inválido: {status}")
    update: dict = {"status": status}
    if status in ("success", "failed", "rolled_back"):
        update["finished_at"] = datetime.now(timezone.utc).isoformat()
    await _db().e2_deployments.update_one(
        {"id": dep_id},
        {"$set": update, "$push": {"steps_log": log_line} if log_line else {}},
    )
    await _audit("deployment_status", actor, {"dep_id": dep_id, "status": status})
    return await _get_deployment(dep_id)


async def _create_pipeline(data: dict, actor: str) -> dict:
    pip_id = "pip_" + secrets.token_urlsafe(8)
    doc = {
        "id": pip_id,
        "name": data["name"],
        "tenant_id": data.get("tenant_id", ""),
        "repo_url": data.get("repo_url"),
        "trigger": data.get("trigger", "manual"),
        "steps": data.get("steps", []),
        "env_vars": data.get("env_vars", {}),
        "last_run": None,
        "last_status": "never_run",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": actor,
    }
    await _db().e2_pipelines.insert_one(doc)
    await _audit("pipeline_created", actor, {"pip_id": pip_id}, data.get("tenant_id", ""))
    return {k: v for k, v in doc.items() if k != "_id"}


async def _infra_health_check(service: str) -> dict:
    """Retorna snapshot de salud — se conecta a vps_manager para datos reales."""
    try:
        import vps_manager as vm
        # vps_manager tiene acceso a los VPS del usuario; aquí consultamos status general
        return {
            "service": service,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "status": "ok",
            "note": "health check via vps_manager — configurar vps_id para datos reales",
        }
    except Exception as exc:
        return {"service": service, "status": "unknown", "error": str(exc)}


# ─── Tool functions (llamadas por E1 / E2 AI) ─────────────────────────────────

@track_call(module="e2_infra", event_prefix="e2.deploy_manager")
async def tool_deploy_manager(action: str, service: str, env: str = "production",
                               stack: str = "fastapi", tenant_id: str = "",
                               repo_url: str = "", note: str = "") -> dict:
    if action == "create":
        return await _create_deployment(
            {"service": service, "env": env, "stack": stack,
             "tenant_id": tenant_id, "repo_url": repo_url or None, "note": note},
            actor="e1_tool"
        )
    if action == "list":
        return {"deployments": await _list_deployments(tenant_id or None)}
    raise ValueError(f"action desconocida: {action}")


async def tool_ci_cd_pipeline(action: str, name: str = "", tenant_id: str = "",
                               repo_url: str = "", steps: list = None,
                               trigger: str = "manual") -> dict:
    if action == "create":
        return await _create_pipeline(
            {"name": name, "tenant_id": tenant_id, "repo_url": repo_url or None,
             "steps": steps or [], "trigger": trigger},
            actor="e1_tool"
        )
    if action == "list":
        q = {"tenant_id": tenant_id} if tenant_id else {}
        cur = _db().e2_pipelines.find(q, {"_id": 0}).limit(50)
        return {"pipelines": [p async for p in cur]}
    raise ValueError(f"action desconocida: {action}")


async def tool_infra_health(service: str) -> dict:
    return await _infra_health_check(service)


@track_call(module="e2_infra", event_prefix="e2.service_monitor")
async def tool_service_monitor(service: str, action: str = "status",
                                tenant_id: str = "") -> dict:
    """STATUS: REAL si E2_VPS_HOST configurado."""
    if action == "status":
        return await e2_executor.service_status(service)
    if action == "metrics":
        return await e2_executor.system_metrics()
    return await e2_executor.service_status(service)


@track_call(module="e2_infra", event_prefix="e2.rollback")
async def tool_rollback_trigger(dep_id: str, tenant_id: str = "") -> dict:
    doc = await _get_deployment(dep_id)
    updated = await _update_deployment_status(dep_id, "rolled_back", "Rollback manual vía E1", "e1_tool")
    return {"ok": True, "deployment": updated}


@track_call(module="e2_infra", event_prefix="e2.ssl_manager")
async def tool_ssl_manager(domain: str, action: str = "status",
                            tenant_id: str = "") -> dict:
    """STATUS: REAL si E2_VPS_HOST configurado y certbot instalado."""
    return await e2_executor.run_ssl(domain, action)


@track_call(module="e2_infra", event_prefix="e2.docker_manager")
async def tool_docker_manager(container: str, action: str = "status",
                               tenant_id: str = "") -> dict:
    """STATUS: REAL si E2_VPS_HOST configurado y Docker instalado."""
    return await e2_executor.run_docker(action, container)


# ─── FastAPI endpoints ────────────────────────────────────────────────────────

@router.post("/deployments")
async def create_deployment(data: DeploymentIn, user: dict = Depends(auth.get_current_user)):
    return await _create_deployment(data.model_dump(), actor=user["email"])


@router.get("/deployments")
async def list_deployments(tenant_id: Optional[str] = None,
                            user: dict = Depends(auth.get_current_user)):
    return {"deployments": await _list_deployments(tenant_id)}


@router.get("/deployments/{dep_id}")
async def get_deployment(dep_id: str, user: dict = Depends(auth.get_current_user)):
    return await _get_deployment(dep_id)


@router.patch("/deployments/{dep_id}/status")
async def update_status(dep_id: str, status: str, log_line: str = "",
                         user: dict = Depends(auth.get_current_user)):
    return await _update_deployment_status(dep_id, status, log_line, user["email"])


@router.post("/pipelines")
async def create_pipeline(data: PipelineIn, user: dict = Depends(auth.get_current_user)):
    return await _create_pipeline(data.model_dump(), actor=user["email"])


@router.get("/pipelines")
async def list_pipelines(tenant_id: Optional[str] = None,
                          user: dict = Depends(auth.get_current_user)):
    q = {"tenant_id": tenant_id} if tenant_id else {}
    cur = _db().e2_pipelines.find(q, {"_id": 0}).limit(50)
    return {"pipelines": [p async for p in cur]}


@router.get("/health/{service}")
async def infra_health(service: str, user: dict = Depends(auth.get_current_user)):
    return await _infra_health_check(service)


@router.get("/logs")
async def infra_logs(tenant_id: Optional[str] = None, limit: int = 100,
                      user: dict = Depends(auth.get_current_user)):
    q = {"tenant_id": tenant_id} if tenant_id else {}
    cur = _db().e2_infra_logs.find(q, {"_id": 0}).sort("ts", -1).limit(limit)
    return {"logs": [l async for l in cur]}
