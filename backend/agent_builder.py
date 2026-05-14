"""
Arquitecto Maestro: CRUD de agentes custom creados por admin.
Combina con agents_catalog.AGENTS para que aparezcan en UI.
"""

import re
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import agents_catalog
from auth import get_current_user

logger = logging.getLogger("agent_builder")
router = APIRouter(prefix="/agent-builder", tags=["agent_builder"])

_db_ref: dict = {"db": None}


def set_db(db) -> None:
    _db_ref["db"] = db


VOICES = {"alloy", "echo", "fable", "onyx", "nova", "shimmer"}
VALID_TOOLS = set(agents_catalog.TOOL_NAMES.keys())


class AgentIn(BaseModel):
    id: str = Field(min_length=2, max_length=40)
    name: str = Field(min_length=2, max_length=40)
    emoji: str = Field(min_length=1, max_length=4)
    color: str = Field(min_length=4, max_length=20)
    voice: str = "alloy"
    tagline: str = Field(max_length=120)
    system: str = Field(min_length=20, max_length=2000)
    tools: list[str] = []


@router.get("")
async def list_custom_agents(_=Depends(get_current_user)):
    """Devuelve agentes built-in + custom merged."""
    builtins = agents_catalog.list_agents()
    db = _db_ref["db"]
    customs = []
    async for a in db.custom_agents.find({}, {"_id": 0}):
        customs.append(a)
    return {"builtin": builtins, "custom": customs}


@router.post("")
async def create_custom_agent(data: AgentIn, user: dict = Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="solo admin")
    aid = re.sub(r"[^a-z0-9_-]", "", data.id.lower())[:40]
    if not aid:
        raise HTTPException(status_code=400, detail="id invalido")
    if aid in agents_catalog.AGENTS:
        raise HTTPException(status_code=409, detail=f"id '{aid}' colisiona con built-in")
    if data.voice not in VOICES:
        data.voice = "alloy"
    tools = [t for t in data.tools if t in VALID_TOOLS]
    db = _db_ref["db"]
    if await db.custom_agents.find_one({"id": aid}, {"_id": 0}):
        raise HTTPException(status_code=409, detail="ya existe un agente con ese id")
    doc = {
        "id": aid, "name": data.name, "emoji": data.emoji, "color": data.color,
        "voice": data.voice, "tagline": data.tagline, "system": data.system,
        "tools": tools, "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": user["id"], "is_custom": True,
    }
    await db.custom_agents.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.put("/{agent_id}")
async def update_custom_agent(agent_id: str, data: AgentIn, user: dict = Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="solo admin")
    db = _db_ref["db"]
    updates = data.model_dump()
    updates["tools"] = [t for t in updates["tools"] if t in VALID_TOOLS]
    if updates["voice"] not in VOICES:
        updates["voice"] = "alloy"
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    updates.pop("id", None)
    res = await db.custom_agents.update_one({"id": agent_id}, {"$set": updates})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="agente no encontrado")
    return {"ok": True}


@router.delete("/{agent_id}")
async def delete_custom_agent(agent_id: str, user: dict = Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="solo admin")
    res = await _db_ref["db"].custom_agents.delete_one({"id": agent_id})
    return {"deleted": res.deleted_count}


@router.get("/available-tools")
async def list_tools(_=Depends(get_current_user)):
    return {"tools": [{"id": t, "cost_oros": c} for t, c in agents_catalog.TOOL_NAMES.items()],
            "voices": sorted(VOICES)}
