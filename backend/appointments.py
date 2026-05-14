"""
Appointments (v11) - Sistema real de agendamiento por agente.

Cada agente (peluquero, dentista, etc.) puede:
- book_appointment(...)
- check_availability(date)
- list_appointments(client_email?)
- cancel_appointment(id)

Las tools del agente llaman estas funciones via console._exec_tool.
"""

import logging
import uuid
import re
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import get_current_user

logger = logging.getLogger("appointments")
router = APIRouter(prefix="/appointments", tags=["appointments"])
_db_ref: dict = {"db": None}


def set_db(db) -> None:
    _db_ref["db"] = db


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^\d{2}:\d{2}$")


def _validate_dt(date: str, time: str) -> Optional[datetime]:
    if not DATE_RE.match(date) or not TIME_RE.match(time):
        return None
    try:
        return datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# === API ENDPOINTS (admin/owner ve sus propias citas) ===
@router.get("")
async def list_my_appointments(
    agent_id: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    db = _db_ref["db"]
    q = {"owner_id": user["id"]}
    if agent_id:
        q["agent_id"] = agent_id
    cur = db.appointments.find(q, {"_id": 0}).sort("when_iso", 1).limit(200)
    return {"appointments": [a async for a in cur]}


@router.delete("/{aid}")
async def cancel_appointment(aid: str, user: dict = Depends(get_current_user)):
    db = _db_ref["db"]
    res = await db.appointments.update_one(
        {"id": aid, "owner_id": user["id"]},
        {"$set": {"status": "cancelled",
                  "cancelled_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"cancelled": res.matched_count > 0}


# === TOOL HANDLERS (los llama console._exec_tool) ===
async def tool_book(owner_id: str, agent_id: str, args: dict) -> dict:
    db = _db_ref["db"]
    client_name = (args.get("client_name") or "").strip()[:80]
    client_phone = (args.get("client_phone") or "").strip()[:40]
    client_email = (args.get("client_email") or "").strip()[:120]
    service = (args.get("service") or "").strip()[:120]
    date = (args.get("date") or "").strip()
    time = (args.get("time") or "").strip()
    notes = (args.get("notes") or "").strip()[:400]

    if not client_name or not service or not date or not time:
        return {"error": "Faltan datos: client_name, service, date(YYYY-MM-DD), time(HH:MM)"}

    when = _validate_dt(date, time)
    if not when:
        return {"error": "Formato invalido. date=YYYY-MM-DD, time=HH:MM (24h)"}
    if when < datetime.now(timezone.utc) - timedelta(minutes=5):
        return {"error": "No puedes agendar en el pasado"}

    # Bloquear solapamientos del mismo agente (mismo owner)
    clash = await db.appointments.find_one({
        "owner_id": owner_id, "agent_id": agent_id,
        "when_iso": when.isoformat(), "status": {"$ne": "cancelled"},
    })
    if clash:
        return {"error": f"Ya hay una cita en {date} {time}. Elige otro horario."}

    aid = str(uuid.uuid4())
    doc = {
        "id": aid, "owner_id": owner_id, "agent_id": agent_id,
        "client_name": client_name, "client_phone": client_phone,
        "client_email": client_email,
        "service": service,
        "when_iso": when.isoformat(),
        "date": date, "time": time,
        "notes": notes, "status": "confirmed",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.appointments.insert_one(doc)
    doc.pop("_id", None)
    return {"booked": True, "appointment": doc}


async def tool_check_availability(owner_id: str, agent_id: str, args: dict) -> dict:
    db = _db_ref["db"]
    date = (args.get("date") or "").strip()
    if not DATE_RE.match(date):
        return {"error": "date debe ser YYYY-MM-DD"}
    busy = []
    cur = db.appointments.find(
        {"owner_id": owner_id, "agent_id": agent_id, "date": date,
         "status": {"$ne": "cancelled"}},
        {"_id": 0, "time": 1, "service": 1, "client_name": 1},
    ).sort("time", 1)
    async for a in cur:
        busy.append({"time": a["time"], "service": a.get("service", ""),
                     "client": a.get("client_name", "")})
    # Slots libres entre 09:00 y 19:00 cada hora
    busy_times = {b["time"] for b in busy}
    all_slots = [f"{h:02d}:00" for h in range(9, 19)]
    free = [s for s in all_slots if s not in busy_times]
    return {"date": date, "busy": busy, "free_slots": free}


async def tool_list_appointments(owner_id: str, agent_id: str, args: dict) -> dict:
    db = _db_ref["db"]
    q = {"owner_id": owner_id, "agent_id": agent_id,
         "status": {"$ne": "cancelled"}}
    if args.get("client_email"):
        q["client_email"] = args["client_email"]
    if args.get("client_phone"):
        q["client_phone"] = args["client_phone"]
    out = []
    cur = db.appointments.find(q, {"_id": 0}).sort("when_iso", 1).limit(30)
    async for a in cur:
        out.append(a)
    return {"appointments": out, "count": len(out)}


async def tool_cancel_appointment(owner_id: str, agent_id: str, args: dict) -> dict:
    db = _db_ref["db"]
    aid = (args.get("id") or "").strip()
    if not aid:
        return {"error": "id requerido"}
    res = await db.appointments.update_one(
        {"id": aid, "owner_id": owner_id, "agent_id": agent_id},
        {"$set": {"status": "cancelled",
                  "cancelled_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"cancelled": res.matched_count > 0, "id": aid}
