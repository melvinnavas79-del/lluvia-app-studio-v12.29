"""
E8 — Support / CRM / Tickets
Sub-orquestador especializado en soporte al cliente, CRM, base de conocimiento
y analytics de soporte enterprise.
Usa Groq para búsqueda semántica en KB y respuestas automáticas.
No toca console.py ni E1.
"""
import logging
import secrets
from datetime import datetime, timezone
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import asyncio
import auth
import llm_router
from e9_emitters import track_call, track_llm_call

logger = logging.getLogger("e8_support")

# ── SLA targets in hours per priority ─────────────────────────────────────────
SLA_RESOLUTION_HOURS = {
    "critical": 1,
    "high":     4,
    "medium":   24,
    "low":      72,
}
SLA_FIRST_RESPONSE_HOURS = {
    "critical": 0.25,   # 15 min
    "high":     1,
    "medium":   4,
    "low":      8,
}

# ── Background SLA monitor task ────────────────────────────────────────────────
_sla_task = None
router = APIRouter(prefix="/e8", tags=["E8-Support"])
_db_ref: dict = {"db": None}


def set_db(db) -> None:
    _db_ref["db"] = db


def _db():
    return _db_ref["db"]


# ─── Constantes ───────────────────────────────────────────────────────────────

TICKET_PRIORITIES = ["low", "medium", "high", "critical"]
TICKET_STATUSES = ["open", "in_progress", "waiting_customer", "resolved", "closed"]
TICKET_CHANNELS = ["chat", "email", "whatsapp", "telegram", "phone", "api"]
TICKET_CATEGORIES = ["technical", "billing", "feature_request", "bug", "onboarding", "other"]
CSAT_OPTIONS = [1, 2, 3, 4, 5]


# ─── Modelos ──────────────────────────────────────────────────────────────────

class TicketIn(BaseModel):
    subject: str = Field(..., max_length=200)
    description: str
    tenant_id: Optional[str] = None
    contact_email: str
    priority: str = "medium"
    channel: str = "chat"
    category: str = "technical"
    tags: List[str] = Field(default_factory=list)


class ContactIn(BaseModel):
    email: str
    name: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    tenant_id: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    notes: Optional[str] = None


class KBArticleIn(BaseModel):
    title: str
    content: str
    tenant_id: Optional[str] = None
    category: str = "general"
    tags: List[str] = Field(default_factory=list)
    public: bool = True


class TicketMessageIn(BaseModel):
    content: str
    author_type: str = Field("agent", description="agent|customer")


# ─── Audit log ────────────────────────────────────────────────────────────────

async def _audit(action: str, actor: str, detail: dict, tenant_id: str = "") -> None:
    try:
        await _db().e8_support_logs.insert_one({
            "ts": datetime.now(timezone.utc).isoformat(),
            "agent": "E8",
            "action": action,
            "actor": actor,
            "tenant_id": tenant_id,
            "detail": detail,
        })
    except Exception as exc:
        logger.warning(f"[e8] audit failed: {exc}")


# ─── Business logic: Tickets ──────────────────────────────────────────────────

def _compute_sla_deadlines(priority: str, created_at: str) -> dict:
    """Computes SLA resolution and first-response deadlines from priority."""
    from datetime import timedelta
    try:
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except Exception:
        created = datetime.now(timezone.utc)
    res_h  = SLA_RESOLUTION_HOURS.get(priority, 24)
    resp_h = SLA_FIRST_RESPONSE_HOURS.get(priority, 4)
    return {
        "sla_resolution_deadline":       (created + timedelta(hours=res_h)).isoformat(),
        "sla_first_response_deadline":   (created + timedelta(hours=resp_h)).isoformat(),
        "sla_resolution_hours":          res_h,
        "sla_first_response_hours":      resp_h,
        "sla_breached":                  False,
        "sla_first_response_breached":   False,
    }


async def _auto_assign(db, ticket_id: str, tenant_id: str, priority: str) -> Optional[str]:
    """Atomic round-robin auto-assignment from e8_agents pool for the tenant.
    Uses find_one_and_update to prevent two concurrent tickets from claiming the same agent."""
    now = datetime.now(timezone.utc).isoformat()
    agent = await db.e8_agents.find_one_and_update(
        {"tenant_id": tenant_id, "active": True},
        {"$set": {"last_assigned": now}},
        sort=[("last_assigned", 1)],
        return_document=True,
        projection={"agent_id": 1, "email": 1, "_id": 0},
    )
    if not agent:
        return None
    agent_id = agent.get("agent_id") or agent.get("email", "")
    await db.e8_tickets.update_one(
        {"id": ticket_id},
        {"$set": {"assigned_to": agent_id, "assigned_at": now}},
    )
    return agent_id


async def _create_ticket(data: dict, actor: str) -> dict:
    if data.get("priority") not in TICKET_PRIORITIES:
        data["priority"] = "medium"
    if data.get("channel") not in TICKET_CHANNELS:
        data["channel"] = "chat"
    if data.get("category") not in TICKET_CATEGORIES:
        data["category"] = "other"

    now       = datetime.now(timezone.utc).isoformat()
    ticket_id = "tkt_" + secrets.token_urlsafe(8)
    sla       = _compute_sla_deadlines(data.get("priority", "medium"), now)

    doc = {
        "id":            ticket_id,
        "subject":       data["subject"],
        "description":   data["description"],
        "tenant_id":     data.get("tenant_id", ""),
        "contact_email": data["contact_email"],
        "priority":      data.get("priority", "medium"),
        "channel":       data.get("channel", "chat"),
        "category":      data.get("category", "technical"),
        "tags":          data.get("tags", []),
        "status":        "open",
        "messages": [{
            "id":          "msg_" + secrets.token_urlsafe(6),
            "content":     data["description"],
            "author_type": "customer",
            "author":      data["contact_email"],
            "ts":          now,
        }],
        "assigned_to":                 None,
        "resolved_at":                 None,
        "csat":                        None,
        "first_response_at":           None,
        "created_at":                  now,
        "created_by":                  actor,
        **sla,
    }
    db = _db()
    await db.e8_tickets.insert_one(doc)
    await _audit("ticket_created", actor,
                  {"ticket_id": ticket_id, "priority": doc["priority"],
                   "channel": doc["channel"],
                   "sla_deadline": sla["sla_resolution_deadline"]},
                  data.get("tenant_id", ""))

    # Auto-assign to available agent
    assigned = await _auto_assign(db, ticket_id, data.get("tenant_id", ""), data.get("priority", "medium"))
    if assigned:
        doc["assigned_to"] = assigned

    return {k: v for k, v in doc.items() if k != "_id"}


async def _add_ticket_message(ticket_id: str, content: str, author_type: str,
                               author: str, actor: str) -> dict:
    msg = {
        "id": "msg_" + secrets.token_urlsafe(6),
        "content": content,
        "author_type": author_type,
        "author": author,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    update: dict = {"$push": {"messages": msg}}
    if author_type == "agent":
        update["$set"] = {"status": "in_progress",
                           "first_response_at": datetime.now(timezone.utc).isoformat()}
    await _db().e8_tickets.update_one({"id": ticket_id}, update)
    await _audit("ticket_message_added", actor, {"ticket_id": ticket_id, "author_type": author_type})
    doc = await _db().e8_tickets.find_one({"id": ticket_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")
    return doc


async def _resolve_ticket(ticket_id: str, csat: Optional[int], actor: str) -> dict:
    update = {
        "status": "resolved",
        "resolved_at": datetime.now(timezone.utc).isoformat(),
    }
    if csat and csat in CSAT_OPTIONS:
        update["csat"] = csat
    await _db().e8_tickets.update_one({"id": ticket_id}, {"$set": update})
    await _audit("ticket_resolved", actor, {"ticket_id": ticket_id, "csat": csat})
    return await _db().e8_tickets.find_one({"id": ticket_id}, {"_id": 0})


# ─── Business logic: CRM Contacts ─────────────────────────────────────────────

async def _upsert_contact(data: dict, actor: str) -> dict:
    existing = await _db().e8_contacts.find_one(
        {"email": data["email"], "tenant_id": data.get("tenant_id", "")}
    )
    if existing:
        update = {"updated_at": datetime.now(timezone.utc).isoformat()}
        for f in ("name", "phone", "company", "notes"):
            if data.get(f):
                update[f] = data[f]
        await _db().e8_contacts.update_one(
            {"email": data["email"], "tenant_id": data.get("tenant_id", "")},
            {"$set": update}
        )
        return await _db().e8_contacts.find_one(
            {"email": data["email"]}, {"_id": 0}
        )

    contact_id = "con_" + secrets.token_urlsafe(8)
    doc = {
        "id": contact_id,
        "email": data["email"],
        "name": data.get("name"),
        "phone": data.get("phone"),
        "company": data.get("company"),
        "tenant_id": data.get("tenant_id", ""),
        "tags": data.get("tags", []),
        "notes": data.get("notes"),
        "ticket_count": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": actor,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await _db().e8_contacts.insert_one(doc)
    await _audit("contact_created", actor, {"contact_id": contact_id, "email": data["email"]},
                  data.get("tenant_id", ""))
    return {k: v for k, v in doc.items() if k != "_id"}


# ─── Business logic: Knowledge Base ───────────────────────────────────────────

async def _create_kb_article(data: dict, actor: str) -> dict:
    art_id = "kb_" + secrets.token_urlsafe(8)
    doc = {
        "id": art_id,
        "title": data["title"],
        "content": data["content"],
        "tenant_id": data.get("tenant_id", ""),
        "category": data.get("category", "general"),
        "tags": data.get("tags", []),
        "public": data.get("public", True),
        "views": 0,
        "helpful_votes": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": actor,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await _db().e8_kb.insert_one(doc)
    await _audit("kb_article_created", actor, {"article_id": art_id, "title": data["title"]},
                  data.get("tenant_id", ""))
    return {k: v for k, v in doc.items() if k != "_id"}


async def _search_kb(query: str, tenant_id: str = "") -> dict:
    """Búsqueda en KB + respuesta automática con Groq si hay artículos relevantes."""
    # Buscar artículos que contengan palabras del query
    words = [w for w in query.lower().split() if len(w) > 3]
    if not words:
        return {"query": query, "articles": [], "ai_answer": None}

    q: dict = {"public": True}
    if tenant_id:
        q["tenant_id"] = tenant_id

    # Regex simple de búsqueda (MongoDB text search si se configura índice)
    import re
    regex = re.compile("|".join(re.escape(w) for w in words), re.IGNORECASE)
    cur = _db().e8_kb.find(
        {**q, "$or": [{"title": regex}, {"content": regex}, {"tags": {"$in": words}}]},
        {"_id": 0}
    ).limit(5)
    articles = [a async for a in cur]

    ai_answer = None
    if articles:
        context = "\n\n".join(f"## {a['title']}\n{a['content'][:500]}" for a in articles[:3])
        client, model = llm_router.get_client("low")
        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "Eres un agente de soporte. Responde usando SOLO la información del contexto proporcionado. Sé conciso y útil. En español."},
                    {"role": "user", "content": f"Contexto KB:\n{context}\n\nPregunta: {query}"},
                ],
                max_tokens=400,
                temperature=0.2,
            )
            ai_answer = resp.choices[0].message.content
            import time as _t
            if hasattr(resp, "usage") and resp.usage:
                await track_llm_call(
                    module="e8_support", provider="groq", model=model,
                    prompt_tokens=resp.usage.prompt_tokens,
                    completion_tokens=resp.usage.completion_tokens,
                )
        except Exception as exc:
            logger.warning(f"[e8] KB search AI failed: {exc}")

    return {"query": query, "articles": articles, "ai_answer": ai_answer,
            "articles_found": len(articles)}


async def _support_analytics(tenant_id: str, period_days: int = 30) -> dict:
    q: dict = {}
    if tenant_id:
        q["tenant_id"] = tenant_id

    total = await _db().e8_tickets.count_documents(q)
    open_t = await _db().e8_tickets.count_documents({**q, "status": "open"})
    resolved = await _db().e8_tickets.count_documents({**q, "status": "resolved"})
    critical = await _db().e8_tickets.count_documents({**q, "priority": "critical"})

    # Promedio CSAT
    csat_docs = [d async for d in _db().e8_tickets.find(
        {**q, "csat": {"$ne": None}}, {"csat": 1, "_id": 0}
    )]
    avg_csat = sum(d["csat"] for d in csat_docs) / len(csat_docs) if csat_docs else None

    return {
        "tenant_id": tenant_id,
        "period_days": period_days,
        "total_tickets": total,
        "open_tickets": open_t,
        "resolved_tickets": resolved,
        "critical_tickets": critical,
        "avg_csat": round(avg_csat, 2) if avg_csat else None,
        "csat_responses": len(csat_docs),
    }


# ─── Tool functions ────────────────────────────────────────────────────────────

@track_call(module="e8_support", event_prefix="e8.ticket_manager")
async def tool_ticket_manager(action: str, ticket_id: str = "", tenant_id: str = "",
                               data: dict = None) -> dict:
    if action == "create" and data:
        return await _create_ticket(data, "e1_tool")
    if action == "list":
        q = {"tenant_id": tenant_id} if tenant_id else {}
        cur = _db().e8_tickets.find(q, {"_id": 0, "messages": 0}).sort("created_at", -1).limit(50)
        return {"tickets": [t async for t in cur]}
    if action == "get" and ticket_id:
        doc = await _db().e8_tickets.find_one({"id": ticket_id}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="Ticket no encontrado")
        return doc
    if action == "resolve" and ticket_id:
        return await _resolve_ticket(ticket_id, data.get("csat") if data else None, "e1_tool")
    raise ValueError(f"action desconocida o parámetros faltantes: {action}")


async def tool_crm_contact(action: str, email: str = "", tenant_id: str = "",
                            data: dict = None) -> dict:
    if action == "upsert" and email:
        payload = data or {}
        payload["email"] = email
        payload["tenant_id"] = tenant_id
        return await _upsert_contact(payload, "e1_tool")
    if action == "list":
        q = {"tenant_id": tenant_id} if tenant_id else {}
        cur = _db().e8_contacts.find(q, {"_id": 0}).sort("created_at", -1).limit(100)
        return {"contacts": [c async for c in cur]}
    raise ValueError(f"action desconocida: {action}")


async def tool_kb_search(query: str, tenant_id: str = "") -> dict:
    return await _search_kb(query, tenant_id)


async def tool_escalation_handler(ticket_id: str, level: str = "high",
                                   reason: str = "") -> dict:
    await _db().e8_tickets.update_one(
        {"id": ticket_id},
        {"$set": {"priority": level, "status": "in_progress",
                   "escalated_at": datetime.now(timezone.utc).isoformat(),
                   "escalation_reason": reason}}
    )
    await _audit("ticket_escalated", "e1_tool", {"ticket_id": ticket_id, "level": level, "reason": reason})
    doc = await _db().e8_tickets.find_one({"id": ticket_id}, {"_id": 0})
    return doc or {"ticket_id": ticket_id, "escalated": True}


async def tool_support_analytics(tenant_id: str = "", period_days: int = 30) -> dict:
    return await _support_analytics(tenant_id, period_days)


# ─── FastAPI endpoints ─────────────────────────────────────────────────────────

@router.post("/tickets")
async def create_ticket(data: TicketIn, user: dict = Depends(auth.require_admin)):
    return await _create_ticket(data.model_dump(), actor=user["email"])


@router.get("/tickets")
async def list_tickets(tenant_id: Optional[str] = None, status: Optional[str] = None,
                        priority: Optional[str] = None,
                        user: dict = Depends(auth.require_admin)):
    q: dict = {}
    if tenant_id:
        q["tenant_id"] = tenant_id
    if status:
        q["status"] = status
    if priority:
        q["priority"] = priority
    cur = _db().e8_tickets.find(q, {"_id": 0, "messages": 0}).sort("created_at", -1).limit(100)
    return {"tickets": [t async for t in cur]}


@router.get("/tickets/{ticket_id}")
async def get_ticket(ticket_id: str, user: dict = Depends(auth.require_admin)):
    doc = await _db().e8_tickets.find_one({"id": ticket_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")
    return doc


@router.post("/tickets/{ticket_id}/messages")
async def add_message(ticket_id: str, data: TicketMessageIn,
                       user: dict = Depends(auth.require_admin)):
    return await _add_ticket_message(ticket_id, data.content, data.author_type,
                                      user["email"], user["email"])


@router.patch("/tickets/{ticket_id}/resolve")
async def resolve_ticket(ticket_id: str, csat: Optional[int] = None,
                          user: dict = Depends(auth.require_admin)):
    return await _resolve_ticket(ticket_id, csat, user["email"])


@router.post("/contacts")
async def upsert_contact(data: ContactIn, user: dict = Depends(auth.require_admin)):
    return await _upsert_contact(data.model_dump(), actor=user["email"])


@router.get("/contacts")
async def list_contacts(tenant_id: Optional[str] = None,
                         user: dict = Depends(auth.require_admin)):
    q = {"tenant_id": tenant_id} if tenant_id else {}
    cur = _db().e8_contacts.find(q, {"_id": 0}).sort("created_at", -1).limit(200)
    return {"contacts": [c async for c in cur]}


@router.post("/kb")
async def create_kb_article(data: KBArticleIn, user: dict = Depends(auth.require_admin)):
    return await _create_kb_article(data.model_dump(), actor=user["email"])


@router.get("/kb")
async def list_kb(tenant_id: Optional[str] = None, category: Optional[str] = None,
                   user: dict = Depends(auth.require_admin)):
    q: dict = {}
    if tenant_id:
        q["tenant_id"] = tenant_id
    if category:
        q["category"] = category
    cur = _db().e8_kb.find(q, {"_id": 0, "content": 0}).sort("views", -1).limit(100)
    return {"articles": [a async for a in cur]}


@router.post("/kb/search")
async def search_kb(query: str, tenant_id: Optional[str] = None,
                     user: dict = Depends(auth.require_admin)):
    return await _search_kb(query, tenant_id or "")


@router.get("/analytics")
async def support_analytics(tenant_id: Optional[str] = None, period_days: int = 30,
                              user: dict = Depends(auth.get_current_user)):
    return await _support_analytics(tenant_id or "", period_days)


# ── SLA Monitor — background asyncio task ─────────────────────────────────────

async def _sla_monitor_loop(interval: int = 300) -> None:
    """
    STATUS: REAL
    Checks every 5 min for SLA breaches and marks tickets accordingly.
    Emits E9 alerts on breach.
    """
    import e9_emitters
    while True:
        try:
            await asyncio.sleep(interval)
            db  = _db()
            now = datetime.now(timezone.utc).isoformat()

            # Resolution deadline breaches
            res = await db.e8_tickets.update_many(
                {
                    "status": {"$in": ["open", "in_progress", "waiting_customer"]},
                    "sla_resolution_deadline": {"$lte": now},
                    "sla_breached": False,
                },
                {"$set": {"sla_breached": True, "sla_breached_at": now}},
            )
            if res.modified_count > 0:
                logger.warning(f"[e8] SLA resolution breach: {res.modified_count} tickets")
                await e9_emitters.emit(
                    "e8.sla_breached",
                    {"count": res.modified_count, "type": "resolution"},
                )

            # First-response deadline breaches
            resp_res = await db.e8_tickets.update_many(
                {
                    "status": {"$in": ["open", "in_progress"]},
                    "first_response_at": None,
                    "sla_first_response_deadline": {"$lte": now},
                    "sla_first_response_breached": False,
                },
                {"$set": {"sla_first_response_breached": True}},
            )
            if resp_res.modified_count > 0:
                logger.warning(f"[e8] SLA first-response breach: {resp_res.modified_count} tickets")
                await e9_emitters.emit(
                    "e8.sla_first_response_breached",
                    {"count": resp_res.modified_count},
                )

        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error(f"[e8] SLA monitor error: {exc}")


_sla_task = None


def start_sla_monitor() -> None:
    global _sla_task
    if _sla_task is None or _sla_task.done():
        _sla_task = asyncio.create_task(_sla_monitor_loop(), name="e8_sla_monitor")
        logger.info("[e8] SLA monitor started")


def stop_sla_monitor() -> None:
    global _sla_task
    if _sla_task and not _sla_task.done():
        _sla_task.cancel()


# ── Agent registration endpoint (for auto-assignment pool) ────────────────────

class AgentIn(BaseModel):
    agent_id: str
    email: str
    tenant_id: str = ""
    active: bool = True


@router.post("/agents")
async def register_agent(data: AgentIn, user: dict = Depends(auth.get_current_user)):
    """Register an agent in the auto-assignment pool."""
    now = datetime.now(timezone.utc).isoformat()
    await _db().e8_agents.update_one(
        {"agent_id": data.agent_id, "tenant_id": data.tenant_id},
        {"$set": {**data.model_dump(), "last_assigned": None, "updated_at": now}},
        upsert=True,
    )
    return {"ok": True, "agent_id": data.agent_id}


@router.get("/agents")
async def list_agents(tenant_id: Optional[str] = None,
                       user: dict = Depends(auth.get_current_user)):
    q = {"tenant_id": tenant_id} if tenant_id else {}
    agents = [a async for a in _db().e8_agents.find(q, {"_id": 0})]
    return {"agents": agents}


@router.get("/sla/breached")
async def sla_breached_tickets(tenant_id: Optional[str] = None,
                                user: dict = Depends(auth.get_current_user)):
    """List all SLA-breached open tickets."""
    q: dict = {"sla_breached": True, "status": {"$nin": ["resolved", "closed"]}}
    if tenant_id:
        q["tenant_id"] = tenant_id
    tickets = [t async for t in _db().e8_tickets.find(q, {"_id": 0, "messages": 0}).sort("created_at", 1)]
    return {"breached_count": len(tickets), "tickets": tickets}
