"""
============================================================
GMAIL MAESTRO AGENT — Soporte 24/7 automatizado
============================================================
Polling de Gmail cada 5 min. Para cada email NUEVO no leido:
  1. Lo clasifica con GPT en: lead-caliente / soporte / comercial / spam / personal
  2. Genera un BORRADOR de respuesta profesional en tu marca
  3. Lo guarda como draft en el Gmail del cliente (NO lo envia solo)
  4. Te notifica en el SuperAdmin Panel

Endpoints:
  POST /api/integrations/gmail/maestro/process-inbox -> dispara ciclo manual
  GET  /api/integrations/gmail/maestro/recent        -> ultimos correos procesados
  GET  /api/integrations/gmail/maestro/metrics       -> dashboard
"""

import base64
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

import requests
from fastapi import APIRouter, Depends, HTTPException

from auth import get_current_user
from gmail_integration import _client_id, _client_secret, GOOGLE_TOKEN_URL

logger = logging.getLogger("gmail_maestro")
router = APIRouter(prefix="/integrations/gmail/maestro", tags=["gmail-maestro"])

_db_ref: dict = {"db": None}


def set_db(db) -> None:
    _db_ref["db"] = db


GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"


# ============================================================
# Auth helper: refresh access_token si expiro
# ============================================================
async def _get_valid_access_token(user_id: str) -> Optional[str]:
    db = _db_ref["db"]
    acc = await db.gmail_accounts.find_one({"user_id": user_id}, {"_id": 0})
    if not acc:
        return None
    # Si tenemos refresh_token, pedimos uno nuevo siempre (mas seguro)
    rt = acc.get("refresh_token")
    if not rt:
        return acc.get("access_token")
    try:
        r = requests.post(GOOGLE_TOKEN_URL, data={
            "client_id": _client_id(),
            "client_secret": _client_secret(),
            "refresh_token": rt,
            "grant_type": "refresh_token",
        }, timeout=15)
        if r.status_code != 200:
            logger.error(f"Refresh Gmail token fallo: {r.status_code} {r.text[:200]}")
            return acc.get("access_token")
        tk = r.json()
        new_access = tk.get("access_token")
        # actualizar en DB
        await db.gmail_accounts.update_one(
            {"user_id": user_id},
            {"$set": {"access_token": new_access,
                      "refreshed_at": datetime.now(timezone.utc).isoformat()}},
        )
        return new_access
    except Exception as e:
        logger.exception(f"Refresh fallo: {e}")
        return acc.get("access_token")


def _gmail_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _decode_body(payload: dict) -> str:
    """Extrae texto plano del body del mensaje Gmail."""
    if not payload:
        return ""
    if "parts" in payload:
        for p in payload["parts"]:
            if p.get("mimeType") == "text/plain":
                data = p.get("body", {}).get("data", "")
                if data:
                    try:
                        return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore")
                    except Exception:
                        pass
        for p in payload["parts"]:
            r = _decode_body(p)
            if r:
                return r
    data = payload.get("body", {}).get("data", "")
    if data:
        try:
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore")
        except Exception:
            return ""
    return ""


def _header(headers: list, name: str) -> str:
    name = name.lower()
    for h in headers or []:
        if h.get("name", "").lower() == name:
            return h.get("value", "")
    return ""


# ============================================================
# Clasificador y generador de borrador con GPT
# ============================================================
async def _classify_and_draft(subject: str, from_addr: str, body: str) -> dict:
    """Devuelve {category, confidence, reply_draft, reasoning}."""
    from openai import AsyncOpenAI
    # Priorizar la API key propia del admin (no depender del Universal Key)
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        return {"category": "soporte", "confidence": 0.0,
                "reply_draft": "(LLM key no configurada)",
                "reasoning": "Sin LLM"}
    # Si usamos OPENAI_API_KEY directo, NO usar el base_url de Emergent.
    if os.environ.get("OPENAI_API_KEY"):
        client = AsyncOpenAI(api_key=api_key)
    else:
        base_url = os.environ.get("EMERGENT_LLM_BASE_URL", "https://integrations.emergentagent.com/llm")
        client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    body_short = (body or "")[:3000]
    sys_prompt = (
        "Eres el Agente Maestro de Soporte de Lluvia App Studio, una plataforma SaaS "
        "que ofrece agentes de IA personalizados y construccion de apps multimedia "
        "(tipo TikTok, radios, ecommerce) para PyMEs. Tu trabajo es clasificar el "
        "correo entrante y redactar un BORRADOR de respuesta profesional en espanol "
        "neutro, tono calido pero corporativo, maximo 6 lineas, firmado 'Equipo "
        "Lluvia App Studio · soporte@lluvia-app-studio.com'.\n\n"
        "Categorias posibles:\n"
        "- lead-caliente: prospecto interesado en comprar, pide demo, precios.\n"
        "- soporte: CLIENTE EXISTENTE con duda tecnica o de uso REAL (no automatica).\n"
        "- comercial: oferta de proveedor, colaboracion, partnership.\n"
        "- spam: irrelevante, scam, masivo.\n"
        "- personal: correos personales no relacionados al negocio.\n\n"
        "REGLAS IMPORTANTES (no las violes):\n"
        "1. Toda notificacion AUTOMATICA de redes sociales (Facebook, Instagram, "
        "TikTok, LinkedIn, Twitter, YouTube), de plataformas (Google, Microsoft, "
        "Apple, Amazon, GitHub), de newsletters, de marketing masivo, de "
        "confirmaciones automaticas de login, de 'tienes X notificaciones', de "
        "ofertas de productos, o cualquier email cuyo remitente termine en "
        "'@facebookmail.com', '@accounts.google.com', '@noreply', '@no-reply', "
        "'@mail.instagram.com', '@em.tiktok.com', '@notifications.', '@notify.', "
        "'@info.', '@newsletter.', '@marketing.': SIEMPRE category='spam', "
        "reply_draft='', confidence>=0.9. NO clasificar como 'soporte'.\n"
        "2. 'Soporte' es SOLO cuando un humano real escribe pidiendo ayuda con "
        "Lluvia App Studio o un cliente nuestro escribe con una duda especifica.\n"
        "3. Si dudas entre soporte y spam, elige spam (es mas seguro no crear "
        "drafts innecesarios).\n\n"
        "Devuelve SOLO JSON valido: "
        '{"category": "...", "confidence": 0.0-1.0, "reply_draft": "...", "reasoning": "..."}.\n'
        'Para spam o personal, reply_draft DEBE ser cadena vacia "".'
    )
    user_prompt = (
        f"De: {from_addr}\nAsunto: {subject}\n\nCuerpo:\n{body_short}"
    )
    try:
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.4,
        )
        raw = resp.choices[0].message.content
        data = json.loads(raw)
        return {
            "category": data.get("category", "soporte"),
            "confidence": float(data.get("confidence", 0.5)),
            "reply_draft": data.get("reply_draft", ""),
            "reasoning": data.get("reasoning", ""),
        }
    except Exception as e:
        logger.exception(f"Clasificacion fallo: {e}")
        return {"category": "soporte", "confidence": 0.0,
                "reply_draft": "", "reasoning": f"error: {e}"}


# ============================================================
# Crear draft en Gmail usando API
# ============================================================
def _build_raw_reply(to_addr: str, subject: str, body: str,
                     in_reply_to: str, references: str) -> str:
    """Construye un MIME RFC822 y lo encodea base64url."""
    reply_subj = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    mime = (
        f"To: {to_addr}\r\n"
        f"Subject: {reply_subj}\r\n"
        f"In-Reply-To: {in_reply_to}\r\n"
        f"References: {references}\r\n"
        f"Content-Type: text/plain; charset=UTF-8\r\n"
        f"\r\n"
        f"{body}"
    )
    return base64.urlsafe_b64encode(mime.encode("utf-8")).decode("ascii")


async def _create_gmail_draft(token: str, raw_b64: str, thread_id: str) -> Optional[str]:
    try:
        r = requests.post(
            f"{GMAIL_API}/drafts",
            headers={**_gmail_headers(token), "Content-Type": "application/json"},
            json={"message": {"raw": raw_b64, "threadId": thread_id}},
            timeout=20,
        )
        if r.status_code in (200, 201):
            return r.json().get("id")
        logger.error(f"Crear draft fallo: {r.status_code} {r.text[:300]}")
    except Exception as e:
        logger.exception(f"Draft creation exception: {e}")
    return None


async def _send_gmail_draft(token: str, draft_id: str) -> Optional[str]:
    """Envia un draft creado previamente. Devuelve el message_id si OK."""
    try:
        r = requests.post(
            f"{GMAIL_API}/drafts/send",
            headers={**_gmail_headers(token), "Content-Type": "application/json"},
            json={"id": draft_id},
            timeout=20,
        )
        if r.status_code in (200, 201):
            return r.json().get("id")
        logger.error(f"Enviar draft fallo: {r.status_code} {r.text[:300]}")
    except Exception as e:
        logger.exception(f"Send draft exception: {e}")
    return None


# Umbral de auto-envio. Encima de esto, el agente envia solo. Debajo,
# queda como draft para revision manual.
AUTOSEND_CONFIDENCE_THRESHOLD = 0.9
# Categorias que califican para auto-envio (lead/soporte = clientes reales).
AUTOSEND_CATEGORIES = {"lead-caliente", "soporte"}


# ============================================================
# Loop principal: procesa inbox
# ============================================================
async def _process_inbox_for_user(user_id: str, max_msgs: int = 10) -> dict:
    db = _db_ref["db"]
    token = await _get_valid_access_token(user_id)
    if not token:
        return {"ok": False, "error": "Gmail no vinculado"}

    # Listar mensajes UNREAD del inbox
    try:
        r = requests.get(
            f"{GMAIL_API}/messages",
            headers=_gmail_headers(token),
            params={"q": "is:unread in:inbox", "maxResults": max_msgs},
            timeout=20,
        )
        if r.status_code != 200:
            return {"ok": False, "error": f"list fallo: {r.status_code} {r.text[:200]}"}
        msg_ids = [m["id"] for m in r.json().get("messages", [])]
    except Exception as e:
        return {"ok": False, "error": str(e)}

    processed = 0
    for mid in msg_ids:
        # Saltar si ya lo procesamos
        if await db.gmail_processed.find_one({"user_id": user_id, "message_id": mid}, {"_id": 1}):
            continue
        try:
            m = requests.get(
                f"{GMAIL_API}/messages/{mid}",
                headers=_gmail_headers(token),
                params={"format": "full"},
                timeout=20,
            ).json()
            headers = m.get("payload", {}).get("headers", [])
            subject = _header(headers, "Subject")
            from_addr = _header(headers, "From")
            msg_id_hdr = _header(headers, "Message-ID")
            references = _header(headers, "References") or msg_id_hdr
            body = _decode_body(m.get("payload", {})) or m.get("snippet", "")
            thread_id = m.get("threadId")

            # Clasificar + draft
            r2 = await _classify_and_draft(subject, from_addr, body)
            draft_id = None
            sent_message_id = None
            auto_sent = False
            if r2["category"] not in ("spam", "personal") and r2["reply_draft"]:
                raw = _build_raw_reply(from_addr, subject, r2["reply_draft"],
                                       msg_id_hdr, references)
                draft_id = await _create_gmail_draft(token, raw, thread_id)
                # OPCION C: auto-envio si confianza > 0.9 y categoria es
                # lead-caliente o soporte. Las dudosas o comerciales se quedan
                # como draft para revision manual del admin.
                if (draft_id
                        and r2["confidence"] >= AUTOSEND_CONFIDENCE_THRESHOLD
                        and r2["category"] in AUTOSEND_CATEGORIES):
                    sent_message_id = await _send_gmail_draft(token, draft_id)
                    auto_sent = bool(sent_message_id)
                    if auto_sent:
                        logger.info(
                            f"AUTO-ENVIADO user={user_id[:8]} category={r2['category']} "
                            f"conf={r2['confidence']:.2f} to={from_addr[:40]}"
                        )

            doc = {
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "message_id": mid,
                "thread_id": thread_id,
                "from": from_addr,
                "subject": subject,
                "snippet": (m.get("snippet") or "")[:200],
                "category": r2["category"],
                "confidence": r2["confidence"],
                "reply_draft": r2["reply_draft"],
                "reasoning": r2["reasoning"],
                "draft_id": draft_id,
                "auto_sent": auto_sent,
                "sent_message_id": sent_message_id,
                "processed_at": datetime.now(timezone.utc).isoformat(),
            }
            await db.gmail_processed.insert_one(doc)
            processed += 1
        except Exception as e:
            logger.exception(f"Procesar mensaje {mid} fallo: {e}")

    return {"ok": True, "total_unread": len(msg_ids), "newly_processed": processed}


# ============================================================
# Endpoints publicos (admin only)
# ============================================================
@router.post("/process-inbox")
async def process_inbox(user: dict = Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="admin only")
    return await _process_inbox_for_user(user["id"])


@router.get("/recent")
async def recent(limit: int = 25, user: dict = Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="admin only")
    db = _db_ref["db"]
    cur = db.gmail_processed.find(
        {"user_id": user["id"]}, {"_id": 0}
    ).sort("processed_at", -1).limit(limit)
    return {"items": [d async for d in cur]}


@router.get("/metrics")
async def metrics(user: dict = Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="admin only")
    db = _db_ref["db"]
    pipeline = [
        {"$match": {"user_id": user["id"]}},
        {"$group": {"_id": "$category", "count": {"$sum": 1}}},
    ]
    by_cat = {}
    async for doc in db.gmail_processed.aggregate(pipeline):
        by_cat[doc["_id"]] = doc["count"]
    total = await db.gmail_processed.count_documents({"user_id": user["id"]})
    with_drafts = await db.gmail_processed.count_documents(
        {"user_id": user["id"], "draft_id": {"$ne": None}}
    )
    auto_sent = await db.gmail_processed.count_documents(
        {"user_id": user["id"], "auto_sent": True}
    )
    return {
        "total_processed": total,
        "with_drafts": with_drafts,
        "auto_sent": auto_sent,
        "by_category": by_cat,
        "estimated_minutes_saved": with_drafts * 3,  # 3 min por borrador
        "autosend_threshold": AUTOSEND_CONFIDENCE_THRESHOLD,
        "autosend_categories": list(AUTOSEND_CATEGORIES),
    }
