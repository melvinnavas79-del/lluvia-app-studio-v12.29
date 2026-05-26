"""
E5 — White Label / Licencias / SaaS Management
Sub-orquestador especializado en tenants multi-tenant, licencias, branding por cliente
y preparación enterprise para billing (E7) y resellers.
Aislamiento total entre tenants. Audit logs inmutables.
No toca console.py ni E1.
"""
import logging
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

import auth
from e9_emitters import track_call

logger = logging.getLogger("e5_whitelabel")
router = APIRouter(prefix="/e5", tags=["E5-WhiteLabel"])
_db_ref: dict = {"db": None}


def set_db(db) -> None:
    _db_ref["db"] = db


def _db():
    return _db_ref["db"]


# ─── Planes y límites ─────────────────────────────────────────────────────────

PLAN_DEFS: dict = {
    "starter": {
        "max_agents": 3,
        "max_chats_month": 500,
        "max_domains": 1,
        "max_vps": 0,
        "max_storage_mb": 500,
        "max_seats": 1,
        "allow_whitelabel": False,
        "allow_custom_domain": False,
        "allow_api_access": False,
    },
    "pro": {
        "max_agents": 10,
        "max_chats_month": 5000,
        "max_domains": 3,
        "max_vps": 1,
        "max_storage_mb": 5000,
        "max_seats": 5,
        "allow_whitelabel": True,
        "allow_custom_domain": True,
        "allow_api_access": True,
    },
    "agency": {
        "max_agents": 50,
        "max_chats_month": 50000,
        "max_domains": 10,
        "max_vps": 5,
        "max_storage_mb": 50000,
        "max_seats": 25,
        "allow_whitelabel": True,
        "allow_custom_domain": True,
        "allow_api_access": True,
    },
    "enterprise": {
        "max_agents": -1,
        "max_chats_month": -1,
        "max_domains": -1,
        "max_vps": -1,
        "max_storage_mb": -1,
        "max_seats": -1,
        "allow_whitelabel": True,
        "allow_custom_domain": True,
        "allow_api_access": True,
    },
    "custom": {
        "max_agents": 10,
        "max_chats_month": 10000,
        "max_domains": 5,
        "max_vps": 2,
        "max_storage_mb": 10000,
        "max_seats": 10,
        "allow_whitelabel": True,
        "allow_custom_domain": True,
        "allow_api_access": True,
    },
}

TENANT_STATUSES = ["trial", "active", "suspended", "expired", "cancelled"]
LICENSE_STATUSES = ["pending", "active", "revoked", "expired"]


# ─── Modelos ──────────────────────────────────────────────────────────────────

class BrandingConfig(BaseModel):
    product_name: Optional[str] = None
    tagline: Optional[str] = None
    logo_data_url: Optional[str] = None
    favicon_url: Optional[str] = None
    primary_color: Optional[str] = None
    accent_color: Optional[str] = None
    bg_color: Optional[str] = None
    text_color: Optional[str] = None
    login_bg: Optional[str] = None
    footer_text: Optional[str] = None
    support_email: Optional[str] = None
    custom_css: Optional[str] = None


class TenantIn(BaseModel):
    name: str = Field(..., max_length=100)
    slug: str = Field(..., max_length=50, pattern=r"^[a-z0-9\-]+$")
    owner_email: str
    plan: str = "starter"
    branding: dict = Field(default_factory=dict)
    expires_days: Optional[int] = 30

    @field_validator("plan")
    @classmethod
    def valid_plan(cls, v: str) -> str:
        if v not in PLAN_DEFS:
            raise ValueError(f"Plan inválido: {v}. Válidos: {list(PLAN_DEFS.keys())}")
        return v


class TenantUpdateIn(BaseModel):
    name: Optional[str] = None
    plan: Optional[str] = None
    expires_days: Optional[int] = None
    limits: Optional[dict] = None


class LicenseIn(BaseModel):
    plan: str = "pro"
    seats: int = 1
    expires_days: int = 365
    note: Optional[str] = None
    tenant_id: Optional[str] = None

    @field_validator("plan")
    @classmethod
    def valid_plan(cls, v: str) -> str:
        if v not in PLAN_DEFS:
            raise ValueError(f"Plan inválido: {v}")
        return v


# ─── Audit log inmutable ──────────────────────────────────────────────────────

async def _audit(action: str, actor: str, detail: dict,
                  tenant_id: str = "", ip: str = "") -> None:
    try:
        await _db().e5_audit_logs.insert_one({
            "ts": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "actor": actor,
            "tenant_id": tenant_id,
            "detail": detail,
            "ip": ip,
        })
    except Exception as exc:
        logger.warning(f"[e5] audit failed: {exc}")


# ─── Business logic: Tenants ──────────────────────────────────────────────────

def _build_limits(plan: str, overrides: dict = None) -> dict:
    limits = dict(PLAN_DEFS.get(plan, PLAN_DEFS["starter"]))
    if overrides:
        limits.update(overrides)
    return limits


async def _assert_slug_unique(slug: str, exclude_id: str = "") -> None:
    q: dict = {"slug": slug}
    if exclude_id:
        q["id"] = {"$ne": exclude_id}
    existing = await _db().e5_tenants.find_one(q)
    if existing:
        raise HTTPException(status_code=409, detail=f"Slug '{slug}' ya está en uso")


async def _create_tenant(data: dict, actor: str, ip: str = "") -> dict:
    await _assert_slug_unique(data["slug"])
    tid = "ten_" + secrets.token_urlsafe(10)
    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(days=data.get("expires_days", 30))).isoformat() if data.get("expires_days") else None

    doc = {
        "id": tid,
        "name": data["name"],
        "slug": data["slug"],
        "owner_email": data["owner_email"],
        "plan": data.get("plan", "starter"),
        "status": "trial",
        # Branding aislado por tenant
        "branding": {
            "product_name": data.get("branding", {}).get("product_name", data["name"]),
            "tagline": data.get("branding", {}).get("tagline", ""),
            "logo_data_url": data.get("branding", {}).get("logo_data_url", ""),
            "favicon_url": data.get("branding", {}).get("favicon_url", ""),
            "primary_color": data.get("branding", {}).get("primary_color", "#2563eb"),
            "accent_color": data.get("branding", {}).get("accent_color", "#7c3aed"),
            "bg_color": data.get("branding", {}).get("bg_color", "#ffffff"),
            "text_color": data.get("branding", {}).get("text_color", "#111827"),
            "login_bg": data.get("branding", {}).get("login_bg", ""),
            "footer_text": data.get("branding", {}).get("footer_text", ""),
            "support_email": data.get("branding", {}).get("support_email", data["owner_email"]),
            "custom_css": data.get("branding", {}).get("custom_css", ""),
        },
        "domains": [],
        "limits": _build_limits(data.get("plan", "starter")),
        # Billing prep (E7)
        "stripe_customer_id": None,
        "stripe_subscription_id": None,
        "stripe_plan_id": None,
        "billing_cycle": "monthly",
        "next_billing_date": None,
        # Reseller prep
        "parent_tenant_id": data.get("parent_tenant_id"),
        "reseller_mode": data.get("reseller_mode", False),
        "subtenant_ids": [],
        # Control
        "created_at": now.isoformat(),
        "created_by": actor,
        "updated_at": now.isoformat(),
        "expires_at": expires_at,
        "activated_at": None,
        "suspended_at": None,
    }
    await _db().e5_tenants.insert_one(doc)
    await _audit("tenant_created", actor, {"tenant_id": tid, "slug": data["slug"], "plan": doc["plan"]}, tid, ip)
    return {k: v for k, v in doc.items() if k != "_id"}


async def _get_tenant(tid: str, actor: str = "", admin_bypass: bool = False) -> dict:
    doc = await _db().e5_tenants.find_one({"id": tid}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Tenant {tid} no encontrado")
    if not admin_bypass and actor and doc.get("owner_email") != actor:
        raise HTTPException(status_code=403, detail="Acceso denegado: no es el owner del tenant")
    return doc


async def _activate_tenant(tid: str, actor: str, ip: str = "") -> dict:
    doc = await _get_tenant(tid, admin_bypass=True)
    now = datetime.now(timezone.utc).isoformat()
    await _db().e5_tenants.update_one(
        {"id": tid},
        {"$set": {"status": "active", "activated_at": now, "updated_at": now}}
    )
    await _audit("tenant_activated", actor, {"tenant_id": tid}, tid, ip)
    return await _get_tenant(tid, admin_bypass=True)


async def _suspend_tenant(tid: str, actor: str, reason: str = "", ip: str = "") -> dict:
    doc = await _get_tenant(tid, admin_bypass=True)
    now = datetime.now(timezone.utc).isoformat()
    await _db().e5_tenants.update_one(
        {"id": tid},
        {"$set": {"status": "suspended", "suspended_at": now, "updated_at": now}}
    )
    await _audit("tenant_suspended", actor, {"tenant_id": tid, "reason": reason}, tid, ip)
    return await _get_tenant(tid, admin_bypass=True)


async def _upgrade_plan(tid: str, new_plan: str, actor: str, ip: str = "") -> dict:
    if new_plan not in PLAN_DEFS:
        raise HTTPException(status_code=400, detail=f"Plan inválido: {new_plan}")
    doc = await _get_tenant(tid, admin_bypass=True)
    old_plan = doc["plan"]
    new_limits = _build_limits(new_plan)
    now = datetime.now(timezone.utc).isoformat()
    await _db().e5_tenants.update_one(
        {"id": tid},
        {"$set": {"plan": new_plan, "limits": new_limits, "updated_at": now}}
    )
    await _audit("plan_changed", actor, {"tenant_id": tid, "old_plan": old_plan, "new_plan": new_plan}, tid, ip)
    return await _get_tenant(tid, admin_bypass=True)


async def _update_branding(tid: str, branding: dict, actor: str, ip: str = "") -> dict:
    await _get_tenant(tid, admin_bypass=True)
    now = datetime.now(timezone.utc).isoformat()
    update_fields = {f"branding.{k}": v for k, v in branding.items() if v is not None}
    update_fields["updated_at"] = now
    await _db().e5_tenants.update_one({"id": tid}, {"$set": update_fields})
    await _audit("branding_updated", actor, {"tenant_id": tid, "fields": list(branding.keys())}, tid, ip)
    return await _get_tenant(tid, admin_bypass=True)


async def _add_domain(tid: str, domain: str, actor: str, ip: str = "") -> dict:
    domain = domain.lower().strip()
    # Unicidad global: ningún otro tenant puede tener este dominio
    conflict = await _db().e5_tenants.find_one({"domains": domain, "id": {"$ne": tid}})
    if conflict:
        raise HTTPException(status_code=409, detail=f"Dominio '{domain}' ya está asignado a otro tenant")

    doc = await _get_tenant(tid, admin_bypass=True)
    if domain in doc.get("domains", []):
        raise HTTPException(status_code=409, detail=f"Dominio '{domain}' ya está en este tenant")

    limits = doc.get("limits", {})
    max_domains = limits.get("max_domains", 1)
    current = len(doc.get("domains", []))
    if max_domains != -1 and current >= max_domains:
        raise HTTPException(status_code=403, detail=f"Límite de dominios alcanzado ({max_domains})")

    now = datetime.now(timezone.utc).isoformat()
    await _db().e5_tenants.update_one(
        {"id": tid},
        {"$push": {"domains": domain}, "$set": {"updated_at": now}}
    )
    await _audit("domain_added", actor, {"tenant_id": tid, "domain": domain}, tid, ip)
    return await _get_tenant(tid, admin_bypass=True)


async def _remove_domain(tid: str, domain: str, actor: str, ip: str = "") -> dict:
    await _get_tenant(tid, admin_bypass=True)
    await _db().e5_tenants.update_one(
        {"id": tid},
        {"$pull": {"domains": domain}, "$set": {"updated_at": datetime.now(timezone.utc).isoformat()}}
    )
    await _audit("domain_removed", actor, {"tenant_id": tid, "domain": domain}, tid, ip)
    return await _get_tenant(tid, admin_bypass=True)


# ─── Business logic: Licencias ────────────────────────────────────────────────

async def _generate_license(data: dict, actor: str, ip: str = "") -> dict:
    # Genera key única con reintentos en caso de colisión
    for _ in range(5):
        key = "LUV-" + secrets.token_urlsafe(18).upper()
        if not await _db().e5_licenses.find_one({"key": key}):
            break
    else:
        raise HTTPException(status_code=500, detail="No se pudo generar clave única")

    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(days=data.get("expires_days", 365))).isoformat()
    doc = {
        "key": key,
        "plan": data.get("plan", "pro"),
        "seats": data.get("seats", 1),
        "tenant_id": data.get("tenant_id"),
        "status": "pending",
        "issued_at": now.isoformat(),
        "expires_at": expires_at,
        "activated_at": None,
        "revoked_at": None,
        "metadata": {
            "note": data.get("note"),
            "issued_by": actor,
            "order_id": None,
        },
    }
    await _db().e5_licenses.insert_one(doc)
    await _audit("license_generated", actor, {"key": key[:12] + "***", "plan": doc["plan"]}, data.get("tenant_id", ""), ip)
    return {k: v for k, v in doc.items() if k != "_id"}


async def _validate_license(key: str) -> dict:
    doc = await _db().e5_licenses.find_one({"key": key}, {"_id": 0})
    if not doc:
        return {"valid": False, "reason": "clave no encontrada"}
    if doc["status"] == "revoked":
        return {"valid": False, "reason": "clave revocada"}
    if doc["status"] == "expired":
        return {"valid": False, "reason": "clave expirada"}
    # Verificar expiración real
    if doc.get("expires_at"):
        exp = datetime.fromisoformat(doc["expires_at"].replace("Z", "+00:00"))
        if exp < datetime.now(timezone.utc):
            await _db().e5_licenses.update_one({"key": key}, {"$set": {"status": "expired"}})
            return {"valid": False, "reason": "clave expirada"}
    return {"valid": True, "plan": doc["plan"], "seats": doc["seats"],
            "expires_at": doc.get("expires_at"), "tenant_id": doc.get("tenant_id")}


async def _activate_license(key: str, tenant_id: str, actor: str, ip: str = "") -> dict:
    validation = await _validate_license(key)
    if not validation["valid"]:
        raise HTTPException(status_code=400, detail=f"Licencia inválida: {validation['reason']}")
    now = datetime.now(timezone.utc).isoformat()
    await _db().e5_licenses.update_one(
        {"key": key},
        {"$set": {"status": "active", "tenant_id": tenant_id, "activated_at": now}}
    )
    await _audit("license_activated", actor, {"key": key[:12] + "***", "tenant_id": tenant_id}, tenant_id, ip)
    return await _db().e5_licenses.find_one({"key": key}, {"_id": 0})


async def _revoke_license(key: str, actor: str, ip: str = "") -> dict:
    doc = await _db().e5_licenses.find_one({"key": key})
    if not doc:
        raise HTTPException(status_code=404, detail="Licencia no encontrada")
    now = datetime.now(timezone.utc).isoformat()
    await _db().e5_licenses.update_one(
        {"key": key},
        {"$set": {"status": "revoked", "revoked_at": now}}
    )
    await _audit("license_revoked", actor, {"key": key[:12] + "***"}, doc.get("tenant_id", ""), ip)
    return {"ok": True, "key": key[:12] + "***", "revoked_at": now}


# ─── Tool functions (llamadas por E1 / E5 AI) ─────────────────────────────────

@track_call(module="e5_whitelabel", event_prefix="e5.license_generator")
async def tool_license_generator(plan: str = "pro", seats: int = 1,
                                   expires_days: int = 365, note: str = "",
                                   tenant_id: str = "") -> dict:
    return await _generate_license(
        {"plan": plan, "seats": seats, "expires_days": expires_days,
         "note": note, "tenant_id": tenant_id or None},
        actor="e1_tool"
    )


@track_call(module="e5_whitelabel", event_prefix="e5.tenant_manager")
async def tool_tenant_manager(action: str, tenant_id: str = "", data: dict = None) -> dict:
    if action == "create" and data:
        return await _create_tenant(data, actor="e1_tool")
    if action == "get" and tenant_id:
        return await _get_tenant(tenant_id, admin_bypass=True)
    if action == "list":
        cur = _db().e5_tenants.find({}, {"_id": 0}).sort("created_at", -1).limit(100)
        return {"tenants": [t async for t in cur]}
    if action == "activate" and tenant_id:
        return await _activate_tenant(tenant_id, "e1_tool")
    if action == "suspend" and tenant_id:
        return await _suspend_tenant(tenant_id, "e1_tool")
    raise ValueError(f"action desconocida o parámetros faltantes: {action}")


async def tool_branding_mapper(tenant_id: str, branding: dict) -> dict:
    return await _update_branding(tenant_id, branding, actor="e1_tool")


async def tool_domain_connector(tenant_id: str, domain: str, action: str = "add") -> dict:
    if action == "add":
        return await _add_domain(tenant_id, domain, "e1_tool")
    if action == "remove":
        return await _remove_domain(tenant_id, domain, "e1_tool")
    raise ValueError(f"action desconocida: {action}")


async def tool_saas_plan_limits(tenant_id: str = "", plan: str = "",
                                 action: str = "get", overrides: dict = None) -> dict:
    if action == "get_plan_defs":
        return {"plans": PLAN_DEFS}
    if action == "get" and tenant_id:
        doc = await _get_tenant(tenant_id, admin_bypass=True)
        return {"tenant_id": tenant_id, "plan": doc["plan"], "limits": doc["limits"]}
    if action == "upgrade" and tenant_id and plan:
        return await _upgrade_plan(tenant_id, plan, "e1_tool")
    raise ValueError(f"action desconocida o parámetros faltantes: {action}")


async def tool_white_label_manager(tenant_id: str, enable: bool = True,
                                    config: dict = None) -> dict:
    doc = await _get_tenant(tenant_id, admin_bypass=True)
    if enable and not doc["limits"].get("allow_whitelabel"):
        raise HTTPException(status_code=403, detail="Plan del tenant no incluye white-label")
    if config:
        return await _update_branding(tenant_id, config, "e1_tool")
    return {"tenant_id": tenant_id, "whitelabel_enabled": enable, "branding": doc["branding"]}


@track_call(module="e5_whitelabel", event_prefix="e5.client_activation")
async def tool_client_activation(tenant_id: str, action: str = "activate",
                                   reason: str = "") -> dict:
    if action == "activate":
        return await _activate_tenant(tenant_id, "e1_tool")
    if action == "suspend":
        return await _suspend_tenant(tenant_id, "e1_tool", reason)
    if action == "expire":
        now = datetime.now(timezone.utc).isoformat()
        await _db().e5_tenants.update_one(
            {"id": tenant_id},
            {"$set": {"status": "expired", "updated_at": now}}
        )
        await _audit("tenant_expired", "e1_tool", {"tenant_id": tenant_id})
        return {"tenant_id": tenant_id, "status": "expired"}
    raise ValueError(f"action desconocida: {action}")


# ─── FastAPI endpoints ─────────────────────────────────────────────────────────

def _is_admin(user: dict) -> bool:
    return user.get("role") == "admin"


@router.post("/tenants")
async def create_tenant(data: TenantIn, request: Request,
                         user: dict = Depends(auth.get_current_user)):
    return await _create_tenant(data.model_dump(), actor=user["email"],
                                  ip=request.client.host if request.client else "")


@router.get("/tenants")
async def list_tenants(user: dict = Depends(auth.get_current_user)):
    if not _is_admin(user):
        cur = _db().e5_tenants.find({"owner_email": user["email"]}, {"_id": 0})
    else:
        cur = _db().e5_tenants.find({}, {"_id": 0}).sort("created_at", -1).limit(200)
    return {"tenants": [t async for t in cur]}


@router.get("/tenants/{tid}")
async def get_tenant(tid: str, user: dict = Depends(auth.get_current_user)):
    return await _get_tenant(tid, actor=user["email"], admin_bypass=_is_admin(user))


@router.patch("/tenants/{tid}")
async def update_tenant(tid: str, data: TenantUpdateIn, request: Request,
                         user: dict = Depends(auth.get_current_user)):
    doc = await _get_tenant(tid, actor=user["email"], admin_bypass=_is_admin(user))
    update: dict = {"updated_at": datetime.now(timezone.utc).isoformat()}
    if data.name:
        update["name"] = data.name
    if data.plan:
        if data.plan not in PLAN_DEFS:
            raise HTTPException(status_code=400, detail="Plan inválido")
        update["plan"] = data.plan
        update["limits"] = _build_limits(data.plan, data.limits)
        await _audit("plan_changed", user["email"],
                      {"tenant_id": tid, "old_plan": doc["plan"], "new_plan": data.plan},
                      tid, request.client.host if request.client else "")
    if data.expires_days:
        update["expires_at"] = (datetime.now(timezone.utc) + timedelta(days=data.expires_days)).isoformat()
    if data.limits and not data.plan:
        update["limits"] = {**doc.get("limits", {}), **data.limits}
    await _db().e5_tenants.update_one({"id": tid}, {"$set": update})
    return await _get_tenant(tid, admin_bypass=True)


@router.post("/tenants/{tid}/activate")
async def activate_tenant(tid: str, request: Request,
                           user: dict = Depends(auth.get_current_user)):
    return await _activate_tenant(tid, user["email"], request.client.host if request.client else "")


@router.post("/tenants/{tid}/suspend")
async def suspend_tenant(tid: str, reason: str = "", request: Request = None,
                          user: dict = Depends(auth.get_current_user)):
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="Solo admin puede suspender tenants")
    return await _suspend_tenant(tid, user["email"], reason,
                                   request.client.host if request and request.client else "")


@router.post("/tenants/{tid}/upgrade")
async def upgrade_plan(tid: str, plan: str, request: Request,
                        user: dict = Depends(auth.get_current_user)):
    return await _upgrade_plan(tid, plan, user["email"],
                                 request.client.host if request.client else "")


@router.post("/tenants/{tid}/branding")
async def update_branding(tid: str, data: BrandingConfig, request: Request,
                           user: dict = Depends(auth.get_current_user)):
    doc = await _get_tenant(tid, actor=user["email"], admin_bypass=_is_admin(user))
    if not doc["limits"].get("allow_whitelabel") and not _is_admin(user):
        raise HTTPException(status_code=403, detail="Tu plan no incluye white-label")
    return await _update_branding(tid, data.model_dump(exclude_none=True), user["email"],
                                    request.client.host if request.client else "")


@router.post("/tenants/{tid}/domain")
async def add_domain(tid: str, domain: str, request: Request,
                      user: dict = Depends(auth.get_current_user)):
    return await _add_domain(tid, domain, user["email"],
                               request.client.host if request.client else "")


@router.delete("/tenants/{tid}/domain/{domain}")
async def remove_domain(tid: str, domain: str, request: Request,
                         user: dict = Depends(auth.get_current_user)):
    return await _remove_domain(tid, domain, user["email"],
                                  request.client.host if request.client else "")


@router.get("/tenants/{tid}/limits")
async def get_limits(tid: str, user: dict = Depends(auth.get_current_user)):
    doc = await _get_tenant(tid, actor=user["email"], admin_bypass=_is_admin(user))
    return {"tenant_id": tid, "plan": doc["plan"], "limits": doc["limits"],
            "status": doc["status"], "expires_at": doc.get("expires_at")}


@router.get("/tenants/{tid}/audit")
async def get_audit(tid: str, limit: int = 50,
                     user: dict = Depends(auth.get_current_user)):
    if not _is_admin(user):
        doc = await _db().e5_tenants.find_one({"id": tid})
        if not doc or doc.get("owner_email") != user["email"]:
            raise HTTPException(status_code=403, detail="Acceso denegado")
    cur = _db().e5_audit_logs.find({"tenant_id": tid}, {"_id": 0}).sort("ts", -1).limit(limit)
    return {"logs": [l async for l in cur]}


@router.post("/licenses/generate")
async def generate_license(data: LicenseIn, request: Request,
                             user: dict = Depends(auth.get_current_user)):
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="Solo admin puede generar licencias")
    return await _generate_license(data.model_dump(), actor=user["email"],
                                    ip=request.client.host if request.client else "")


@router.post("/licenses/validate")
async def validate_license(key: str):
    return await _validate_license(key)


@router.get("/licenses")
async def list_licenses(user: dict = Depends(auth.get_current_user)):
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="Solo admin")
    cur = _db().e5_licenses.find({}, {"_id": 0}).sort("issued_at", -1).limit(200)
    return {"licenses": [l async for l in cur]}


@router.patch("/licenses/{key}/activate")
async def activate_license(key: str, tenant_id: str, request: Request,
                             user: dict = Depends(auth.get_current_user)):
    return await _activate_license(key, tenant_id, user["email"],
                                    request.client.host if request.client else "")


@router.patch("/licenses/{key}/revoke")
async def revoke_license(key: str, request: Request,
                          user: dict = Depends(auth.get_current_user)):
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="Solo admin puede revocar licencias")
    return await _revoke_license(key, user["email"],
                                   request.client.host if request.client else "")
