"""
Sistema de Propuestas de Auto-Update (Opcion A SEGURA).
- Agentes proponen cambios (config, promos, branding, agentes nuevos)
- Admin revisa y aprueba con 1 click
- Nada se aplica sin approve manual
- Cada propuesta queda auditada
"""

import uuid
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import get_current_user

router = APIRouter(prefix="/proposals", tags=["proposals"])
_db_ref: dict = {"db": None}


def set_db(db):
    _db_ref["db"] = db


# Tipos de propuestas validos. Cada uno tiene un handler conocido.
VALID_TYPES = {"branding_update", "promo_create", "agent_create", "agent_update", "pricing_update"}


class ProposalIn(BaseModel):
    type: str = Field(description="branding_update|promo_create|agent_create|agent_update|pricing_update")
    title: str = Field(max_length=200)
    rationale: str = Field(max_length=1000)
    payload: dict  # contenido del cambio propuesto
    proposed_by_agent: Optional[str] = None


@router.get("")
async def list_proposals(user: dict = Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="solo admin")
    cur = _db_ref["db"].proposals.find({}, {"_id": 0}).sort("created_at", -1).limit(100)
    return {"proposals": [p async for p in cur]}


@router.post("")
async def create_proposal(data: ProposalIn, user: dict = Depends(get_current_user)):
    if data.type not in VALID_TYPES:
        raise HTTPException(status_code=400, detail=f"type invalido. Validos: {VALID_TYPES}")
    pid = str(uuid.uuid4())
    doc = {
        "id": pid,
        "type": data.type,
        "title": data.title,
        "rationale": data.rationale,
        "payload": data.payload,
        "proposed_by_agent": data.proposed_by_agent,
        "proposed_by_user": user["id"],
        "status": "pending",  # pending|approved|rejected|applied|failed
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await _db_ref["db"].proposals.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.post("/{pid}/approve")
async def approve_proposal(pid: str, user: dict = Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="solo admin")
    db = _db_ref["db"]
    p = await db.proposals.find_one({"id": pid}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404, detail="propuesta no encontrada")
    if p["status"] != "pending":
        raise HTTPException(status_code=400, detail=f"propuesta ya esta '{p['status']}'")
    # Aplicar segun tipo
    result = await _apply_proposal(p, db)
    new_status = "applied" if result["ok"] else "failed"
    await db.proposals.update_one(
        {"id": pid},
        {"$set": {"status": new_status,
                  "applied_at": datetime.now(timezone.utc).isoformat(),
                  "approved_by": user["id"],
                  "apply_result": result}},
    )
    return {"ok": result["ok"], "status": new_status, "result": result}


@router.post("/{pid}/reject")
async def reject_proposal(pid: str, user: dict = Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="solo admin")
    await _db_ref["db"].proposals.update_one(
        {"id": pid},
        {"$set": {"status": "rejected", "rejected_by": user["id"],
                  "rejected_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"ok": True}


async def _apply_proposal(p: dict, db) -> dict:
    """Aplica una propuesta segun su tipo. Cada tipo es un handler conocido y SEGURO.
    JAMAS ejecuta codigo arbitrario."""
    try:
        ptype = p["type"]
        payload = p.get("payload", {}) or {}
        if ptype == "branding_update":
            # actualizar coleccion branding
            await db.branding.update_one(
                {"_id": "default"},
                {"$set": {k: v for k, v in payload.items() if k in
                          {"display", "tagline", "primary", "accent", "background",
                           "text_color", "logo_url", "product_name"}}},
                upsert=True,
            )
            return {"ok": True, "applied": "branding"}
        elif ptype == "promo_create":
            # crear/actualizar promo
            rule = {**payload, "active": True,
                    "created_at": datetime.now(timezone.utc).isoformat()}
            await db.promos.update_one({"rule_id": payload.get("rule_id")},
                                       {"$set": rule}, upsert=True)
            return {"ok": True, "applied": "promo"}
        elif ptype == "agent_create":
            payload["is_custom"] = True
            payload["created_at"] = datetime.now(timezone.utc).isoformat()
            await db.custom_agents.update_one({"id": payload.get("id")},
                                              {"$set": payload}, upsert=True)
            return {"ok": True, "applied": "agent_create"}
        elif ptype == "agent_update":
            await db.custom_agents.update_one({"id": payload.get("id")},
                                              {"$set": payload})
            return {"ok": True, "applied": "agent_update"}
        elif ptype == "pricing_update":
            # ajustes a costos por tool/voice (no aplicado, solo logged)
            await db.pricing_overrides.update_one({"_id": "current"},
                                                  {"$set": payload}, upsert=True)
            return {"ok": True, "applied": "pricing"}
        else:
            return {"ok": False, "error": f"tipo no soportado: {ptype}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
