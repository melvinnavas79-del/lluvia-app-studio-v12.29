"""
E11 — Customer Support / Gmail Agent
Lluvia App Studio — Enterprise ecosystem

Wraps gmail_integration + gmail_maestro existentes SIN MODIFICARLOS.
Añade la capa enterprise:
  - Sistema de tickets (e11_tickets)
  - Urgency detection
  - Escalation + handoff humano
  - Followups programados (e11_followups)
  - CRM sync → E4 leads
  - Multi-tenant (admin Gmail sirve múltiples tenants por dominio/label)
  - Tool functions para E1 orchestrator

Dependencias externas: ninguna nueva (reutiliza google OAuth ya instalado).
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
from e9_emitters import track_call, track_error as e9_track_error

logger = logging.getLogger("e11_gmail_support")
router = APIRouter(prefix="/e11", tags=["e11-gmail-support"])

_db_ref: dict = {"db": None}


def set_db(db) -> None:
    _db_ref["db"] = db


def _db():
    if _db_ref["db"] is None:
        raise RuntimeError("E11: DB no inicializado")
    return _db_ref["db"]

# ══════════════════════════════════════════════════════════════════════════════
# Urgency detection
# ══════════════════════════════════════════════════════════════════════════════

_URGENCY_PATTERNS = [
    r"\burgent\b", r"\basap\b", r"\bcrítico\b", r"\bcritico\b",
    r"\bdown\b", r"\bcaído\b", r"\bcaido\b", r"\bbroken\b", r"\bbroken\b",
    r"\bno funciona\b", r"\bno puedo acceder\b", r"\bpérdida de datos\b",
    r"\bperdida de datos\b", r"\bsistema caído\b", r"\bproducción caída\b",
    r"\bproduccion caida\b", r"\bsecurity breach\b", r"\bdata loss\b",
    r"\bimmediate\b", r"\binmediato\b", r"\bemergencia\b",
]
_URGENCY_RE = re.compile("|".join(_URGENCY_PATTERNS), re.IGNORECASE)


def _detect_priority(subject: str, body: str) -> str:
    text = f"{subject} {body}"
    if _URGENCY_RE.search(text):
        return "urgent"
    if any(w in text.lower() for w in ["importante", "importante:", "follow up", "seguimiento"]):
        return "high"
    return "normal"

# ══════════════════════════════════════════════════════════════════════════════
# Ticket helpers
# ══════════════════════════════════════════════════════════════════════════════

async def _create_ticket_doc(db, *, from_addr: str, subject: str, body: str,
                              category: str, tenant_id: str, source_msg_id: str = "",
                              gmail_processed_id: str = "") -> dict:
    now = datetime.now(timezone.utc).isoformat()
    priority = _detect_priority(subject, body)
    tid = f"T-{uuid.uuid4().hex[:8].upper()}"
    doc = {
        "ticket_id":           tid,
        "tenant_id":           tenant_id,
        "from":                from_addr,
        "subject":             subject,
        "body":                body[:2000],
        "category":            category,
        "priority":            priority,
        "status":              "open",
        "source_msg_id":       source_msg_id,
        "gmail_processed_id":  gmail_processed_id,
        "history":             [],
        "tags":                [],
        "assignee":            None,
        "crm_synced":          False,
        "followup_scheduled":  False,
        "escalated":           False,
        "created_at":          now,
        "updated_at":          now,
    }
    await db.e11_tickets.insert_one(doc)
    logger.info(f"Ticket {tid} creado | tenant={tenant_id} priority={priority} category={category}")
    return {k: v for k, v in doc.items() if k != "_id"}


async def _get_ticket(db, ticket_id: str) -> Optional[dict]:
    return await db.e11_tickets.find_one({"ticket_id": ticket_id}, {"_id": 0})


async def _append_history(db, ticket_id: str, action: str, notes: str, actor: str = "system"):
    now = datetime.now(timezone.utc).isoformat()
    await db.e11_tickets.update_one(
        {"ticket_id": ticket_id},
        {
            "$push": {"history": {"action": action, "notes": notes, "actor": actor, "ts": now}},
            "$set":  {"updated_at": now},
        },
    )

# ══════════════════════════════════════════════════════════════════════════════
# Tool functions — expuestas a E1 via console.py dispatch
# ══════════════════════════════════════════════════════════════════════════════

@track_call(module="e11_gmail_support", event_prefix="e11.inbox_process", emit_start=True)
async def tool_gmail_inbox_process(user_id: str = "", tenant_id: str = "default",
                                    max_msgs: int = 10) -> dict:
    """
    Dispara el procesamiento del inbox Gmail para un usuario.
    Wraps gmail_maestro._process_inbox_for_user y convierte resultados en tickets E11.
    """
    db = _db()
    # Importa en runtime para evitar import circular
    from gmail_maestro import _process_inbox_for_user
    # Resuelve user_id: si no se pasa, usa el admin (single-tenant) o busca por tenant
    if not user_id:
        admin = await db.users.find_one({"role": "admin"}, {"id": 1})
        user_id = admin["id"] if admin else ""
    if not user_id:
        return {"ok": False, "error": "No hay usuario Gmail configurado"}

    result = await _process_inbox_for_user(user_id, max_msgs)
    if not result.get("ok"):
        return result

    # Crear tickets para emails recién procesados que no tienen ticket aún
    recent_cur = db.gmail_processed.find(
        {"user_id": user_id},
        {"_id": 0}
    ).sort("processed_at", -1).limit(max_msgs)
    recent = await recent_cur.to_list(length=max_msgs)

    tickets_created = []
    for email in recent:
        # Saltar spam y los que ya tienen ticket
        if email.get("category") == "spam":
            continue
        existing = await db.e11_tickets.find_one({"source_msg_id": email.get("message_id", "")})
        if existing:
            continue
        t = await _create_ticket_doc(
            db,
            from_addr=email.get("from", ""),
            subject=email.get("subject", ""),
            body=email.get("snippet", ""),
            category=email.get("category", "soporte"),
            tenant_id=tenant_id,
            source_msg_id=email.get("message_id", ""),
            gmail_processed_id=email.get("id", ""),
        )
        tickets_created.append(t["ticket_id"])

    return {
        **result,
        "tickets_created": tickets_created,
        "tenant_id": tenant_id,
    }


async def tool_gmail_ticket_create(from_addr: str, subject: str, body: str = "",
                                    category: str = "soporte",
                                    tenant_id: str = "default") -> dict:
    """Crea un ticket de soporte manualmente (sin pasar por inbox)."""
    db = _db()
    return await _create_ticket_doc(db, from_addr=from_addr, subject=subject,
                                     body=body, category=category, tenant_id=tenant_id)


async def tool_gmail_ticket_list(tenant_id: str = "default", status: str = "",
                                  priority: str = "", limit: int = 50) -> dict:
    """Lista tickets de soporte con filtros opcionales."""
    db = _db()
    q: dict = {"tenant_id": tenant_id}
    if status:
        q["status"] = status
    if priority:
        q["priority"] = priority
    cur = db.e11_tickets.find(q, {"_id": 0}).sort("created_at", -1).limit(limit)
    tickets = await cur.to_list(length=limit)
    return {
        "tickets": tickets,
        "total": len(tickets),
        "filters": {"tenant_id": tenant_id, "status": status, "priority": priority},
    }


async def tool_gmail_ticket_update(ticket_id: str, status: str = "",
                                    notes: str = "", assignee: str = "") -> dict:
    """Actualiza estado, notas o asignado de un ticket."""
    db = _db()
    ticket = await _get_ticket(db, ticket_id)
    if not ticket:
        return {"ok": False, "error": f"Ticket {ticket_id!r} no encontrado"}

    now = datetime.now(timezone.utc).isoformat()
    update: dict = {"updated_at": now}
    if status:
        update["status"] = status
    if assignee:
        update["assignee"] = assignee
    await db.e11_tickets.update_one({"ticket_id": ticket_id}, {"$set": update})
    await _append_history(db, ticket_id, f"update:{status or 'notes'}", notes or f"→ {status}")
    return {"ok": True, "ticket_id": ticket_id, "updated": update}


async def tool_gmail_escalate(ticket_id: str, reason: str = "",
                               notify_email: str = "", tenant_id: str = "default") -> dict:
    """
    Escala un ticket a soporte humano.
    Marca status=escalated, emite evento a E8 y E9.
    """
    db = _db()
    ticket = await _get_ticket(db, ticket_id)
    if not ticket:
        return {"ok": False, "error": f"Ticket {ticket_id!r} no encontrado"}

    now = datetime.now(timezone.utc).isoformat()
    await db.e11_tickets.update_one(
        {"ticket_id": ticket_id},
        {"$set": {"status": "escalated", "escalated": True, "updated_at": now}},
    )
    await _append_history(db, ticket_id, "escalation", reason or "Escalación solicitada")

    # Emite evento a E8 (support/CRM)
    await db.e8_tickets.insert_one({
        "source": "e11_gmail",
        "ticket_id": ticket_id,
        "tenant_id": tenant_id,
        "from": ticket.get("from", ""),
        "subject": ticket.get("subject", ""),
        "reason": reason,
        "notify_email": notify_email,
        "priority": ticket.get("priority", "normal"),
        "created_at": now,
        "status": "open",
    })

    # Emite evento a E9 (analytics)
    await db.e9_events.insert_one({
        "type": "gmail_escalation",
        "source": "e11",
        "tenant_id": tenant_id,
        "ticket_id": ticket_id,
        "reason": reason,
        "ts": now,
    })

    logger.warning(f"Ticket {ticket_id} ESCALADO | tenant={tenant_id} reason={reason[:80]}")
    return {"ok": True, "ticket_id": ticket_id, "status": "escalated", "notify": notify_email}


@track_call(module="e11_gmail_support", event_prefix="e11.followup_schedule")
async def tool_gmail_followup(ticket_id: str, message: str = "",
                               delay_hours: int = 24, tenant_id: str = "default") -> dict:
    """Programa un followup automático para el ticket en N horas."""
    db = _db()
    ticket = await _get_ticket(db, ticket_id)
    if not ticket:
        return {"ok": False, "error": f"Ticket {ticket_id!r} no encontrado"}

    now = datetime.now(timezone.utc)
    send_at = (now + timedelta(hours=delay_hours)).isoformat()
    fid = f"FU-{uuid.uuid4().hex[:8].upper()}"
    doc = {
        "followup_id":  fid,
        "ticket_id":    ticket_id,
        "tenant_id":    tenant_id,
        "to":           ticket.get("from", ""),
        "subject":      f"Re: {ticket.get('subject', '')}",
        "message":      message or "Seguimiento de tu consulta anterior. ¿Pudiste resolverlo?",
        "delay_hours":  delay_hours,
        "send_at":      send_at,
        "status":       "pending",
        "created_at":   now.isoformat(),
    }
    await db.e11_followups.insert_one(doc)
    await db.e11_tickets.update_one(
        {"ticket_id": ticket_id},
        {"$set": {"followup_scheduled": True, "updated_at": now.isoformat()}},
    )
    await _append_history(db, ticket_id, "followup_scheduled", f"Envío en {delay_hours}h")
    return {"ok": True, "followup_id": fid, "ticket_id": ticket_id, "send_at": send_at}


async def tool_gmail_crm_sync(ticket_id: str, tenant_id: str = "default") -> dict:
    """
    Sincroniza ticket category='lead-caliente' como Lead en E4.
    Solo actúa si category es lead, no duplica si ya sincronizado.
    """
    db = _db()
    ticket = await _get_ticket(db, ticket_id)
    if not ticket:
        return {"ok": False, "error": f"Ticket {ticket_id!r} no encontrado"}
    if ticket.get("crm_synced"):
        return {"ok": True, "note": "Ya sincronizado", "ticket_id": ticket_id}
    if ticket.get("category") not in ("lead-caliente", "comercial"):
        return {"ok": False, "note": f"Categoría {ticket['category']!r} no sincronizable como lead"}

    from e4_sales import _create_lead
    lead = await _create_lead({
        "email":       ticket.get("from", ""),
        "name":        ticket.get("from", "").split("<")[0].strip() or "Lead Gmail",
        "source":      "gmail_e11",
        "product":     ticket.get("subject", "")[:100],
        "tenant_id":   tenant_id,
        "notes":       f"Auto-sync desde ticket {ticket_id}",
        "stage":       "new",
    }, actor="e11_auto")

    await db.e11_tickets.update_one(
        {"ticket_id": ticket_id},
        {"$set": {"crm_synced": True, "crm_lead_id": lead.get("id", "")}},
    )
    await _append_history(db, ticket_id, "crm_sync", f"Lead {lead.get('id', '')} creado en E4")
    return {"ok": True, "ticket_id": ticket_id, "lead_id": lead.get("id", ""), "crm": "e4"}


async def tool_gmail_autoresponder_config(tenant_id: str = "default",
                                           enabled: bool = True,
                                           categories: list = None,
                                           confidence_threshold: float = 0.85,
                                           template: str = "") -> dict:
    """Configura las reglas de autorespuesta por tenant."""
    db = _db()
    now = datetime.now(timezone.utc).isoformat()
    config = {
        "tenant_id":             tenant_id,
        "enabled":               enabled,
        "autosend_categories":   categories or ["soporte", "lead-caliente"],
        "confidence_threshold":  confidence_threshold,
        "custom_template":       template,
        "updated_at":            now,
    }
    await db.e11_autoresponder_configs.update_one(
        {"tenant_id": tenant_id}, {"$set": config}, upsert=True
    )
    return {"ok": True, "config": config}


async def tool_gmail_metrics(tenant_id: str = "default", period_days: int = 7) -> dict:
    """Métricas de soporte Gmail: tickets por estado, prioridad, tiempo de resolución."""
    db = _db()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=period_days)).isoformat()
    q = {"tenant_id": tenant_id, "created_at": {"$gte": cutoff}}

    tickets = await db.e11_tickets.find(q, {"_id": 0}).to_list(length=1000)
    total = len(tickets)
    by_status:   dict = {}
    by_priority: dict = {}
    by_category: dict = {}
    escalated = 0
    synced = 0
    for t in tickets:
        by_status[t.get("status", "?")] = by_status.get(t.get("status", "?"), 0) + 1
        by_priority[t.get("priority", "?")] = by_priority.get(t.get("priority", "?"), 0) + 1
        by_category[t.get("category", "?")] = by_category.get(t.get("category", "?"), 0) + 1
        if t.get("escalated"):
            escalated += 1
        if t.get("crm_synced"):
            synced += 1

    followups = await db.e11_followups.count_documents({"tenant_id": tenant_id, "created_at": {"$gte": cutoff}})

    return {
        "tenant_id":          tenant_id,
        "period_days":        period_days,
        "total_tickets":      total,
        "by_status":          by_status,
        "by_priority":        by_priority,
        "by_category":        by_category,
        "escalated":          escalated,
        "crm_synced":         synced,
        "followups_scheduled": followups,
        "escalation_rate":    round(escalated / max(1, total), 3),
        "crm_conversion_rate": round(synced / max(1, total), 3),
    }

# ══════════════════════════════════════════════════════════════════════════════
# FastAPI endpoints REST
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/tickets")
async def list_tickets(tenant_id: str = "default", status: str = "",
                        priority: str = "", limit: int = 50,
                        user: dict = Depends(auth.get_current_user)):
    return await tool_gmail_ticket_list(tenant_id, status, priority, limit)


@router.post("/tickets/{ticket_id}/update")
async def update_ticket(ticket_id: str, status: str = "", notes: str = "",
                         assignee: str = "",
                         user: dict = Depends(auth.get_current_user)):
    return await tool_gmail_ticket_update(ticket_id, status, notes, assignee)


@router.post("/tickets/{ticket_id}/escalate")
async def escalate_ticket(ticket_id: str, reason: str = "", notify_email: str = "",
                           tenant_id: str = "default",
                           user: dict = Depends(auth.get_current_user)):
    return await tool_gmail_escalate(ticket_id, reason, notify_email, tenant_id)


@router.post("/tickets/{ticket_id}/followup")
async def schedule_followup(ticket_id: str, message: str = "", delay_hours: int = 24,
                             tenant_id: str = "default",
                             user: dict = Depends(auth.get_current_user)):
    return await tool_gmail_followup(ticket_id, message, delay_hours, tenant_id)


@router.post("/tickets/{ticket_id}/crm-sync")
async def crm_sync(ticket_id: str, tenant_id: str = "default",
                    user: dict = Depends(auth.get_current_user)):
    return await tool_gmail_crm_sync(ticket_id, tenant_id)


@router.get("/metrics")
async def metrics(tenant_id: str = "default", period_days: int = 7,
                   user: dict = Depends(auth.get_current_user)):
    return await tool_gmail_metrics(tenant_id, period_days)


@router.post("/autoresponder")
async def autoresponder_config(tenant_id: str = "default", enabled: bool = True,
                                confidence_threshold: float = 0.85,
                                user: dict = Depends(auth.get_current_user)):
    return await tool_gmail_autoresponder_config(tenant_id, enabled,
                                                  confidence_threshold=confidence_threshold)


@router.post("/process-inbox")
@limiter.limit("5/minute")
async def trigger_inbox(request, tenant_id: str = "default", max_msgs: int = 10,
                         user: dict = Depends(auth.get_current_user)):
    return await tool_gmail_inbox_process(tenant_id=tenant_id, max_msgs=max_msgs)


@router.get("/followups")
async def list_followups(tenant_id: str = "default", status: str = "pending",
                          user: dict = Depends(auth.get_current_user)):
    db = _db()
    q: dict = {"tenant_id": tenant_id}
    if status:
        q["status"] = status
    cur = db.e11_followups.find(q, {"_id": 0}).sort("send_at", 1).limit(100)
    fus = await cur.to_list(length=100)
    return {"followups": fus, "total": len(fus)}


@router.get("/status")
async def e11_status(user: dict = Depends(auth.get_current_user)):
    db = _db()
    total_tickets = await db.e11_tickets.count_documents({})
    open_tickets  = await db.e11_tickets.count_documents({"status": "open"})
    escalated     = await db.e11_tickets.count_documents({"status": "escalated"})
    pending_fu    = await db.e11_followups.count_documents({"status": "pending"})
    return {
        "agent":           "E11 — Customer Support / Gmail Agent",
        "version":         "1.0",
        "capabilities":    [
            "inbox_monitoring", "ai_classification", "ticket_management",
            "escalation", "followups", "crm_sync", "multi_tenant", "autoresponder",
        ],
        "stats": {
            "total_tickets": total_tickets,
            "open":          open_tickets,
            "escalated":     escalated,
            "pending_followups": pending_fu,
        },
        "gmail_integration": "gmail_integration.py + gmail_maestro.py (reutilizados)",
    }
