"""
E4 — Email Engine  (additive to e4_sales.py)
Proveedores: SendGrid | Resend | SES | stub

Status por provider:
  sendgrid  REAL   requiere SENDGRID_API_KEY + SENDGRID_FROM_EMAIL
  resend    REAL   requiere RESEND_API_KEY   + RESEND_FROM_EMAIL
  ses       PARCIAL requiere boto3 + AWS_ACCESS_KEY_ID + SES_FROM_EMAIL
  stub      STUB   log only — default si nada está configurado

ENV vars:
  EMAIL_PROVIDER         sendgrid|resend|ses|stub  (default: stub)
  SENDGRID_API_KEY / SENDGRID_FROM_EMAIL
  RESEND_API_KEY   / RESEND_FROM_EMAIL
  AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / SES_FROM_EMAIL / SES_REGION
  EMAIL_UNSUB_SECRET     HMAC key para tokens de unsubscribe (generar con secrets.token_hex(32))
  EMAIL_RATE_HOURLY      max emails/hora por tenant (default: 100)
  EMAIL_RATE_DAILY       max emails/día  por tenant (default: 1000)
  APP_BASE_URL           para links de unsubscribe (default: https://lluvia.app)

Colecciones MongoDB (todas con tenant_id):
  e4_email_log       registro inmutable de cada envío
  e4_email_dlq       emails que fallaron tras todos los reintentos
  e4_suppressions    lista de supresión (bounces / unsubscribes)
  e4_rate_limits     ventanas de rate limit con TTL
"""

import os
import re
import hmac
import json
import time
import base64
import hashlib
import logging
import asyncio
import secrets
from html import escape as _html_escape
from html.parser import HTMLParser
from typing import Optional, List
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError as _DuplicateKeyError

import auth
from e9_emitters import track_call
from rate_limit import limiter

logger = logging.getLogger("e4_email")
router = APIRouter(prefix="/e4/email", tags=["E4-Email"])
_db_ref: dict = {"db": None}


def set_db(db) -> None:
    _db_ref["db"] = db


def _db():
    return _db_ref["db"]


# ─── Constants ────────────────────────────────────────────────────────────────

EMAIL_PROVIDER   = os.getenv("EMAIL_PROVIDER", "stub")
MAX_SUBJECT_LEN  = 200
MAX_HTML_BYTES   = 500_000
MAX_RETRY        = 3
RATE_HOURLY      = int(os.getenv("EMAIL_RATE_HOURLY", "100"))
RATE_DAILY       = int(os.getenv("EMAIL_RATE_DAILY",  "1000"))

# Leído en tiempo de ejecución (no en import) para sobrevivir reinicios sin env
def _unsub_secret() -> bytes:
    val = os.getenv("EMAIL_UNSUB_SECRET", "")
    if not val:
        logger.warning("[e4/email] EMAIL_UNSUB_SECRET no configurado — tokens no persistirán tras restart")
        val = "default-insecure-key-set-EMAIL_UNSUB_SECRET"
    return val.encode()


# ─── HTML Sanitizer ───────────────────────────────────────────────────────────

_BLOCKED_TAGS = frozenset({
    "script", "style", "iframe", "object", "embed", "form",
    "input", "button", "textarea", "select", "link", "meta",
    "base", "applet", "canvas", "svg", "math", "noscript",
})
_BLOCKED_ATTR_RE = re.compile(r"^on\w+$", re.IGNORECASE)
_JS_URL_RE       = re.compile(r"^\s*javascript\s*:", re.IGNORECASE)


class _Sanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._out: list = []
        self._depth = 0  # nesting depth inside blocked tags

    def _safe_attrs(self, attrs):
        result = []
        for name, value in attrs:
            # Strip null bytes and control chars before matching — prevents bypass via
            # o\x00nerror= which wouldn't match ^on\w+$ but becomes onerror in browsers
            n = re.sub(r"[\x00-\x1f\x7f]", "", name).lower()
            if _BLOCKED_ATTR_RE.match(n):
                continue
            if value and _JS_URL_RE.match(value):
                continue
            result.append((name, value))
        return result

    def _attr_str(self, attrs) -> str:
        return "".join(
            f' {n}="{v}"' if v is not None else f' {n}'
            for n, v in self._safe_attrs(attrs)
        )

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        if self._depth > 0:
            if t in _BLOCKED_TAGS:
                self._depth += 1
            return
        if t in _BLOCKED_TAGS:
            self._depth += 1
            return
        self._out.append(f"<{tag}{self._attr_str(attrs)}>")

    def handle_endtag(self, tag):
        t = tag.lower()
        if self._depth > 0:
            if t in _BLOCKED_TAGS:
                self._depth -= 1
            return
        self._out.append(f"</{tag}>")

    def handle_startendtag(self, tag, attrs):
        t = tag.lower()
        if self._depth > 0 or t in _BLOCKED_TAGS:
            return
        self._out.append(f"<{tag}{self._attr_str(attrs)}/>")

    def handle_data(self, data):
        if self._depth == 0:
            # Must re-escape: convert_charrefs=True decodes &lt;script&gt; → <script>
            # which would output literal markup if not re-escaped here.
            self._out.append(_html_escape(data, quote=False))

    def result(self) -> str:
        return "".join(self._out)


def _sanitize_html(html: str) -> str:
    if len(html.encode()) > MAX_HTML_BYTES:
        raise ValueError(f"HTML body supera {MAX_HTML_BYTES // 1000}KB")
    s = _Sanitizer()
    s.feed(html)
    return s.result()


def _html_to_text(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html).strip()


# ─── Header injection prevention ─────────────────────────────────────────────

def _check_header(value: str, field: str) -> None:
    if "\r" in value or "\n" in value:
        raise ValueError(f"Header injection detectada en campo '{field}'")


# ─── Unsubscribe tokens (HMAC-SHA256, \x00-delimited) ─────────────────────────

def _gen_unsub_token(email: str, tenant_id: str) -> str:
    ts  = str(int(time.time()))
    msg = f"{email}\x00{tenant_id}\x00{ts}".encode()
    sig = hmac.digest(_unsub_secret(), msg, "sha256").hex()
    raw = f"{email}\x00{tenant_id}\x00{ts}\x00{sig}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _verify_unsub_token(token: str) -> tuple:
    """Returns (email, tenant_id) or raises ValueError."""
    try:
        pad    = token + "=" * (-len(token) % 4)
        raw    = base64.urlsafe_b64decode(pad.encode()).decode()
        parts  = raw.split("\x00")
        if len(parts) != 4:
            raise ValueError("malformed")
        email, tenant_id, ts_str, sig = parts
        msg      = f"{email}\x00{tenant_id}\x00{ts_str}".encode()
        expected = hmac.digest(_unsub_secret(), msg, "sha256").hex()
        if not hmac.compare_digest(sig, expected):
            raise ValueError("firma inválida")
        if int(time.time()) - int(ts_str) > 86400 * 90:
            raise ValueError("token expirado")
        return email, tenant_id
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"token inválido: {exc}")


# ─── Suppression list ─────────────────────────────────────────────────────────

async def _is_suppressed(email: str, tenant_id: str) -> bool:
    em = email.lower()
    return bool(await _db().e4_suppressions.find_one({
        "email": em,
        "$or": [{"tenant_id": tenant_id}, {"global": True}],
    }))


async def _add_suppression(email: str, tenant_id: str, reason: str,
                            global_flag: bool = False) -> None:
    em = email.lower()
    await _db().e4_suppressions.update_one(
        {"email": em, "tenant_id": tenant_id},
        {"$set": {
            "email": em, "tenant_id": tenant_id,
            "reason": reason, "global": global_flag,
            "suppressed_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )


# ─── Rate limiting ────────────────────────────────────────────────────────────

async def _check_rate_limit(tenant_id: str) -> None:
    now  = datetime.now(timezone.utc)
    h_wn = now.strftime("%Y-%m-%dT%H")
    d_wn = now.strftime("%Y-%m-%d")

    for wn, wtype, limit in [
        (h_wn, "hourly", RATE_HOURLY),
        (d_wn, "daily",  RATE_DAILY),
    ]:
        doc = await _db().e4_rate_limits.find_one_and_update(
            {"tenant_id": tenant_id, "window": wn, "type": wtype},
            {"$inc": {"count": 1},
             "$setOnInsert": {"created_at": now}},  # datetime (not str) for TTL index
            upsert=True,
            return_document=True,
        )
        if doc and doc.get("count", 0) > limit:
            raise HTTPException(status_code=429,
                                detail=f"Rate limit excedido: {limit}/{wtype} (tenant={tenant_id})")


# ─── Email log ────────────────────────────────────────────────────────────────

async def _log(email_id: str, tenant_id: str, to_email: str,
               subject: str, provider: str, status: str,
               idempotency_key: str = "", error: str = "") -> None:
    await _db().e4_email_log.update_one(
        {"email_id": email_id},
        {"$set": {
            "email_id": email_id, "tenant_id": tenant_id,
            "to": to_email, "subject": subject,
            "provider": provider, "status": status,
            "idempotency_key": idempotency_key, "error": error,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, "$setOnInsert": {
            "created_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )


# ─── Provider implementations ─────────────────────────────────────────────────

async def _send_sendgrid(to_email: str, from_email: str, subject: str,
                          html_body: str, text_body: str, reply_to: str = "") -> str:
    api_key = os.getenv("SENDGRID_API_KEY", "")
    if not api_key:
        raise ValueError("SENDGRID_API_KEY no configurado")

    payload: dict = {
        "personalizations": [{"to": [{"email": to_email}]}],
        "from": {"email": from_email},
        "subject": subject,
        "content": [
            {"type": "text/plain", "value": text_body or _html_to_text(html_body)},
            {"type": "text/html",  "value": html_body},
        ],
        "tracking_settings": {
            "click_tracking": {"enable": True, "enable_text": False},
            "open_tracking": {"enable": True},
        },
    }
    if reply_to:
        payload["reply_to"] = {"email": reply_to}

    import aiohttp
    async with aiohttp.ClientSession() as sess:
        async with sess.post(
            "https://api.sendgrid.com/v3/mail/send",
            json=payload,
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            if resp.status not in (200, 202):
                body = await resp.text()
                raise ValueError(f"SendGrid {resp.status}: {body[:200]}")
            return resp.headers.get("X-Message-Id", "sg_" + secrets.token_hex(6))


async def _send_resend(to_email: str, from_email: str, subject: str,
                        html_body: str, text_body: str, reply_to: str = "") -> str:
    api_key = os.getenv("RESEND_API_KEY", "")
    if not api_key:
        raise ValueError("RESEND_API_KEY no configurado")

    payload: dict = {
        "from": from_email, "to": [to_email], "subject": subject,
        "html": html_body,
        "text": text_body or _html_to_text(html_body),
    }
    if reply_to:
        payload["reply_to"] = reply_to

    import aiohttp
    async with aiohttp.ClientSession() as sess:
        async with sess.post(
            "https://api.resend.com/emails",
            json=payload,
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            data = await resp.json()
            if resp.status not in (200, 201):
                raise ValueError(f"Resend {resp.status}: {data}")
            return data.get("id", "rs_" + secrets.token_hex(6))


async def _send_ses(to_email: str, from_email: str, subject: str,
                     html_body: str, text_body: str, reply_to: str = "") -> str:
    try:
        import boto3
    except ImportError:
        raise ValueError("boto3 no instalado — requerido para provider SES")

    client = boto3.client(
        "ses",
        region_name=os.getenv("SES_REGION", "us-east-1"),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    )
    kwargs: dict = {
        "Source": from_email,
        "Destination": {"ToAddresses": [to_email]},
        "Message": {
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body": {
                "Text": {"Data": text_body or _html_to_text(html_body), "Charset": "UTF-8"},
                "Html": {"Data": html_body, "Charset": "UTF-8"},
            },
        },
    }
    if reply_to:
        kwargs["ReplyToAddresses"] = [reply_to]

    resp = await asyncio.to_thread(client.send_email, **kwargs)
    return resp.get("MessageId", "ses_" + secrets.token_hex(6))


async def _send_stub(to_email: str, from_email: str, subject: str,
                      html_body: str, text_body: str, reply_to: str = "") -> str:
    logger.info(f"[e4/stub] EMAIL to={to_email} from={from_email} subject={subject!r}")
    return "stub_" + secrets.token_hex(8)


_PROVIDER_FNS = {
    "sendgrid": _send_sendgrid,
    "resend":   _send_resend,
    "ses":      _send_ses,
    "stub":     _send_stub,
}


# ─── Core send_email ──────────────────────────────────────────────────────────

async def send_email(
    tenant_id: str,
    to_email: str,
    subject: str,
    html_body: str,
    from_email: str = "",
    reply_to: str = "",
    text_body: str = "",
    idempotency_key: str = "",
    campaign_id: str = "",
    include_unsub: bool = True,
    provider_override: str = "",
) -> dict:
    """
    Envío de email production-grade.
    Garantías: idempotencia · supresión · rate limit · sanitización HTML ·
               anti-header-injection · retry × 3 · DLQ · unsubscribe link · E9 metrics.
    """
    # Normalize email address — lowercase for consistency across log/DLQ/suppression
    to_email = to_email.strip().lower()

    provider_name = provider_override or EMAIL_PROVIDER
    if provider_name not in _PROVIDER_FNS:
        provider_name = "stub"

    # Resolver from_email
    if not from_email:
        from_email = os.getenv(
            f"{provider_name.upper()}_FROM_EMAIL",
            os.getenv("EMAIL_FROM_ADDRESS", "noreply@lluvia.app"),
        )

    # email_id generated early — needed for atomic idempotency claim below
    email_id = "email_" + secrets.token_urlsafe(10)

    # ── Atomic idempotency claim ────────────────────────────────────────────────
    # Uses find_one_and_update with $setOnInsert: MongoDB guarantees atomicity of
    # findAndModify, so exactly one concurrent caller wins the insert.
    # return_document=False → returns doc *before* the update:
    #   None          → we won (new insert) — proceed with send
    #   existing doc  → another request already claimed this key
    if idempotency_key:
        now_iso = datetime.now(timezone.utc).isoformat()
        pre_existing = await _db().e4_email_log.find_one_and_update(
            {"idempotency_key": idempotency_key, "tenant_id": tenant_id},
            {"$setOnInsert": {
                "email_id":        email_id,
                "idempotency_key": idempotency_key,
                "tenant_id":       tenant_id,
                "to":              to_email,
                "subject":         subject,
                "provider":        provider_name,
                "status":          "sending",
                "created_at":      now_iso,
                "updated_at":      now_iso,
            }},
            upsert=True,
            return_document=False,
        )
        if pre_existing is not None:
            prev_status   = pre_existing.get("status", "")
            prev_email_id = pre_existing.get("email_id", "")
            if prev_status in ("sent", "delivered"):
                return {"ok": True, "duplicate": True, "email_id": prev_email_id}
            if prev_status == "sending":
                # Previous send is in-flight or server crashed mid-send.
                # Conservatively block to prevent double-send.
                return {"ok": True, "duplicate": True, "email_id": prev_email_id,
                        "note": "Concurrent send in progress — retry later if email not received"}
            # "failed" → allow retry; reuse existing email_id for log continuity
            if prev_email_id:
                email_id = prev_email_id

    # Supresión
    if await _is_suppressed(to_email, tenant_id):
        logger.info(f"[e4] email suprimido → {to_email} (tenant={tenant_id})")
        # Release idempotency slot so future calls aren't blocked as "in-flight"
        if idempotency_key:
            await _db().e4_email_log.update_one(
                {"email_id": email_id, "status": "sending"},
                {"$set": {"status": "suppressed",
                          "updated_at": datetime.now(timezone.utc).isoformat()}},
            )
        return {"ok": False, "suppressed": True, "email": to_email}

    # Rate limit
    await _check_rate_limit(tenant_id)

    # Anti-header injection
    for field, val in [("to", to_email), ("from", from_email), ("subject", subject)]:
        _check_header(val, field)
    if reply_to:
        _check_header(reply_to, "reply_to")

    if len(subject) > MAX_SUBJECT_LEN:
        raise ValueError(f"Subject demasiado largo (máx {MAX_SUBJECT_LEN})")

    # Sanitización HTML
    safe_html = _sanitize_html(html_body) if html_body else ""

    # Unsubscribe footer
    if include_unsub and safe_html:
        token   = _gen_unsub_token(to_email, tenant_id)
        base    = os.getenv("APP_BASE_URL", "https://lluvia.app").rstrip("/")
        unsub   = f"{base}/api/e4/email/unsubscribe?token={token}"
        safe_html += (
            '<br><hr style="margin:20px 0;border:none;border-top:1px solid #eee">'
            f'<p style="font-size:11px;color:#999;text-align:center">'
            f'<a href="{unsub}" style="color:#999">Cancelar suscripción</a></p>'
        )

    send_fn  = _PROVIDER_FNS[provider_name]
    last_err = ""

    for attempt in range(MAX_RETRY):
        try:
            msg_id = await send_fn(
                to_email=to_email, from_email=from_email,
                subject=subject, html_body=safe_html,
                text_body=text_body, reply_to=reply_to,
            )
            await _log(email_id, tenant_id, to_email, subject,
                       provider_name, "sent", idempotency_key)
            return {
                "ok": True, "email_id": email_id,
                "provider_message_id": msg_id, "provider": provider_name,
            }
        except Exception as exc:
            last_err = str(exc)
            logger.warning(f"[e4] intento {attempt + 1} fallido ({to_email}): {exc}")
            if attempt < MAX_RETRY - 1:
                # Exponential backoff con jitter
                delay = (2 ** attempt) * (0.5 + secrets.randbelow(100) / 100)
                await asyncio.sleep(delay)

    # DLQ
    await _db().e4_email_dlq.insert_one({
        "email_id": email_id, "tenant_id": tenant_id,
        "to": to_email, "subject": subject,
        "html_preview": safe_html[:500],
        "provider": provider_name, "error": last_err,
        "campaign_id": campaign_id, "idempotency_key": idempotency_key,
        "attempts": MAX_RETRY, "status": "failed",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    await _log(email_id, tenant_id, to_email, subject,
               provider_name, "failed", idempotency_key, last_err)

    logger.error(f"[e4] email {email_id} enviado a DLQ tras {MAX_RETRY} intentos: {last_err}")
    return {"ok": False, "email_id": email_id, "error": last_err, "dlq": True}


# ─── Webhook verification ─────────────────────────────────────────────────────

def _verify_sendgrid_webhook(headers: dict, body: bytes) -> bool:
    """Ed25519 signature verification para SendGrid Event Webhooks."""
    pub_key_b64 = os.getenv("SENDGRID_WEBHOOK_PUBLIC_KEY", "")
    if not pub_key_b64:
        return False
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.hazmat.primitives.serialization import load_der_public_key
        from cryptography.exceptions import InvalidSignature

        sig_b64 = headers.get("x-twilio-email-event-webhook-signature", "")
        ts      = headers.get("x-twilio-email-event-webhook-timestamp", "")
        if not sig_b64 or not ts:
            return False

        pub_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(pub_key_b64))
        payload = (ts + body.decode()).encode()
        pub_key.verify(base64.b64decode(sig_b64), payload)
        return True
    except Exception:
        return False


def _verify_resend_webhook(headers: dict, body: bytes) -> bool:
    """HMAC-SHA256 via Svix protocol para Resend webhooks."""
    secret = os.getenv("RESEND_WEBHOOK_SECRET", "")
    if not secret:
        return False
    try:
        svix_id  = headers.get("svix-id", "")
        svix_ts  = headers.get("svix-timestamp", "")
        svix_sig = headers.get("svix-signature", "")
        if not svix_id or not svix_ts or not svix_sig:
            return False

        # Strip "whsec_" prefix if present
        key = base64.b64decode(secret.removeprefix("whsec_"))
        msg = f"{svix_id}.{svix_ts}.{body.decode()}".encode()
        expected = "v1," + base64.b64encode(
            hmac.digest(key, msg, "sha256")
        ).decode()
        # svix-signature may contain multiple sigs separated by " "
        sigs = svix_sig.split(" ")
        return any(hmac.compare_digest(s.strip(), expected) for s in sigs)
    except Exception:
        return False


def _verify_webhook(provider: str, headers: dict, body: bytes) -> bool:
    if provider == "sendgrid":
        return _verify_sendgrid_webhook(headers, body)
    if provider == "resend":
        return _verify_resend_webhook(headers, body)
    return False


# ─── Webhook event processing ─────────────────────────────────────────────────

async def _process_webhook_event(provider: str, event: dict) -> None:
    """Procesa eventos de entrega: bounces → supresión, unsubscribes → supresión."""
    event_type = ""
    email      = ""
    tenant_id  = ""

    if provider == "sendgrid":
        event_type = event.get("event", "")
        email      = event.get("email", "").lower()
        tenant_id  = event.get("custom_args", {}).get("tenant_id", "")
    elif provider == "resend":
        event_type = event.get("type", "")
        email      = (event.get("data", {}).get("to") or [""])[0].lower()
        tenant_id  = event.get("data", {}).get("headers", {}).get("x-tenant-id", "")

    if not email:
        return

    if event_type in ("bounce", "blocked", "invalid", "dropped",
                      "email.bounced", "email.complained"):
        await _add_suppression(email, tenant_id or "_global",
                               f"bounce:{event_type}", global_flag=not bool(tenant_id))
        logger.info(f"[e4] suppressed {email} reason={event_type}")

    if event_type in ("unsubscribe", "group_unsubscribe", "spamreport",
                      "email.unsubscribed"):
        await _add_suppression(email, tenant_id or "_global", f"user:{event_type}")

    # Actualizar estado en e4_email_log si hay email_id
    email_id = event.get("custom_args", {}).get("email_id", "") or \
               event.get("data", {}).get("email_id", "")
    if email_id and event_type in ("delivered", "email.delivered"):
        await _db().e4_email_log.update_one(
            {"email_id": email_id},
            {"$set": {"status": "delivered",
                      "delivered_at": datetime.now(timezone.utc).isoformat()}},
        )


# ─── Tool functions (llamadas por E1) ─────────────────────────────────────────

@track_call(module="e4_email", event_prefix="e4.email_send")
async def tool_email_send(
    tenant_id: str,
    to_email: str,
    subject: str,
    html_body: str,
    from_email: str = "",
    idempotency_key: str = "",
    campaign_id: str = "",
) -> dict:
    return await send_email(
        tenant_id=tenant_id, to_email=to_email, subject=subject,
        html_body=html_body, from_email=from_email,
        idempotency_key=idempotency_key, campaign_id=campaign_id,
    )


@track_call(module="e4_email", event_prefix="e4.campaign_dispatch")
async def tool_campaign_email_dispatch(
    tenant_id: str,
    campaign_id: str,
    subject: str,
    html_body: str,
    from_email: str = "",
    max_send: int = 500,
) -> dict:
    """
    Despacha campaña de email a leads del tenant.
    Límite: max_send por llamada (para evitar timeouts).
    """
    db = _db()
    campaign = await db.e4_campaigns.find_one({"id": campaign_id, "tenant_id": tenant_id})
    if not campaign:
        return {"error": f"Campaña {campaign_id} no encontrada"}

    # Obtener leads activos con email
    leads = await db.e4_leads.find(
        {"tenant_id": tenant_id, "email": {"$exists": True, "$ne": ""}},
        {"email": 1, "name": 1, "_id": 0},
    ).limit(max_send).to_list(length=max_send)

    sent = 0
    failed = 0
    suppressed = 0

    for lead in leads:
        email = lead.get("email", "").strip()
        if not email:
            continue
        ikey = f"campaign_{campaign_id}_{email}"
        result = await send_email(
            tenant_id=tenant_id, to_email=email, subject=subject,
            html_body=html_body, from_email=from_email,
            idempotency_key=ikey, campaign_id=campaign_id,
        )
        if result.get("suppressed"):
            suppressed += 1
        elif result.get("ok"):
            sent += 1
        else:
            failed += 1

    # Actualizar stats de campaña
    await db.e4_campaigns.update_one(
        {"id": campaign_id},
        {"$inc": {"sent_count": sent, "failed_count": failed},
         "$set": {"last_dispatch": datetime.now(timezone.utc).isoformat()}},
    )

    return {
        "campaign_id": campaign_id, "tenant_id": tenant_id,
        "sent": sent, "failed": failed, "suppressed": suppressed,
        "total_processed": len(leads),
    }


# ─── Indexes ──────────────────────────────────────────────────────────────────

async def create_indexes() -> None:
    db = _db()

    # ── Migrate idempotency index to unique ────────────────────────────────────
    # Previous versions created a non-unique index on (idempotency_key, tenant_id).
    # We need unique=True for atomic idempotency guarantees. Safe to drop and recreate
    # because sparse=True excludes docs without idempotency_key from the constraint.
    try:
        idx_info = await db.e4_email_log.index_information()
        for idx_name, idx_data in idx_info.items():
            key_spec = [list(k) for k in idx_data.get("key", [])]
            if (key_spec == [["idempotency_key", 1], ["tenant_id", 1]]
                    and not idx_data.get("unique")):
                await db.e4_email_log.drop_index(idx_name)
                logger.info("[e4/email] Dropped non-unique idempotency index for migration")
                break
    except Exception as exc:
        logger.warning(f"[e4/email] Idempotency index migration warning (non-fatal): {exc}")

    await db.e4_email_log.create_index(
        [("idempotency_key", 1), ("tenant_id", 1)],
        unique=True, sparse=True,
        name="idx_e4_idem_unique",
    )
    await db.e4_email_log.create_index([("tenant_id", 1), ("created_at", -1)])
    await db.e4_suppressions.create_index(
        [("email", 1), ("tenant_id", 1)], unique=True
    )
    await db.e4_email_dlq.create_index([("tenant_id", 1), ("status", 1)])
    await db.e4_rate_limits.create_index(
        [("tenant_id", 1), ("window", 1), ("type", 1)], unique=True
    )
    # TTL: limpiar rate limit docs después de 2 días
    await db.e4_rate_limits.create_index(
        "created_at", expireAfterSeconds=86400 * 2
    )
    logger.info("[e4/email] Indexes OK")


# ─── FastAPI Endpoints ────────────────────────────────────────────────────────

class SendEmailIn(BaseModel):
    tenant_id: str
    to_email: str
    subject: str
    html_body: str
    from_email: str = ""
    reply_to: str = ""
    text_body: str = ""
    idempotency_key: str = ""
    campaign_id: str = ""
    include_unsub: bool = True
    provider_override: str = ""


class CampaignDispatchIn(BaseModel):
    subject: str
    html_body: str
    from_email: str = ""
    max_send: int = Field(500, le=5000)


class SuppressionIn(BaseModel):
    email: str
    reason: str = "manual"


@router.post("/send")
async def api_send_email(data: SendEmailIn,
                          user: dict = Depends(auth.require_admin)):
    return await send_email(
        tenant_id=data.tenant_id, to_email=data.to_email,
        subject=data.subject, html_body=data.html_body,
        from_email=data.from_email, reply_to=data.reply_to,
        text_body=data.text_body, idempotency_key=data.idempotency_key,
        campaign_id=data.campaign_id, include_unsub=data.include_unsub,
        provider_override=data.provider_override,
    )


@router.post("/campaign/{campaign_id}/dispatch")
async def api_campaign_dispatch(campaign_id: str, data: CampaignDispatchIn,
                                 user: dict = Depends(auth.require_admin)):
    tenant_id = user.get("tenant_id", "")
    return await tool_campaign_email_dispatch(
        tenant_id=tenant_id, campaign_id=campaign_id,
        subject=data.subject, html_body=data.html_body,
        from_email=data.from_email, max_send=data.max_send,
    )


@router.get("/log")
async def api_email_log(tenant_id: Optional[str] = None, limit: int = 50,
                         user: dict = Depends(auth.require_admin)):
    q: dict = {}
    if tenant_id:
        q["tenant_id"] = tenant_id
    docs = await _db().e4_email_log.find(q, {"_id": 0}) \
        .sort("created_at", -1).limit(limit).to_list(length=limit)
    return {"log": docs}


@router.get("/dlq")
async def api_dlq(tenant_id: Optional[str] = None,
                   user: dict = Depends(auth.require_admin)):
    q: dict = {"status": "failed"}
    if tenant_id:
        q["tenant_id"] = tenant_id
    docs = await _db().e4_email_dlq.find(q, {"_id": 0}) \
        .sort("created_at", -1).limit(100).to_list(length=100)
    return {"dlq": docs}


@router.post("/dlq/{email_id}/retry")
async def api_dlq_retry(email_id: str, user: dict = Depends(auth.require_admin)):
    doc = await _db().e4_email_dlq.find_one({"email_id": email_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Email DLQ no encontrado")
    # Re-intentar con el HTML guardado (preview)
    result = await send_email(
        tenant_id=doc["tenant_id"], to_email=doc["to"],
        subject=doc["subject"], html_body=doc.get("html_preview", ""),
        idempotency_key="", campaign_id=doc.get("campaign_id", ""),
        include_unsub=False,
    )
    if result.get("ok"):
        await _db().e4_email_dlq.update_one(
            {"email_id": email_id},
            {"$set": {"status": "retried",
                      "retried_at": datetime.now(timezone.utc).isoformat()}},
        )
    return result


@router.get("/suppressions")
async def api_list_suppressions(tenant_id: Optional[str] = None,
                                  user: dict = Depends(auth.require_admin)):
    q: dict = {}
    if tenant_id:
        q["tenant_id"] = tenant_id
    docs = await _db().e4_suppressions.find(q, {"_id": 0}) \
        .sort("suppressed_at", -1).limit(500).to_list(length=500)
    return {"suppressions": docs}


@router.post("/suppressions")
async def api_add_suppression(data: SuppressionIn, tenant_id: str,
                                user: dict = Depends(auth.require_admin)):
    await _add_suppression(data.email, tenant_id, data.reason)
    return {"ok": True, "email": data.email}


@router.delete("/suppressions/{email}")
async def api_remove_suppression(email: str, tenant_id: str,
                                   user: dict = Depends(auth.require_admin)):
    res = await _db().e4_suppressions.delete_one(
        {"email": email.lower(), "tenant_id": tenant_id}
    )
    return {"ok": True, "deleted": res.deleted_count}


@router.get("/unsubscribe")
async def api_unsubscribe(token: str):
    """Endpoint público — link de unsubscribe en emails."""
    try:
        email, tenant_id = _verify_unsub_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await _add_suppression(email, tenant_id, "user:unsubscribe_link")
    return {"ok": True, "message": "Has sido eliminado de la lista de emails.",
            "email": email}


_WEBHOOK_KEY_ENV = {
    "sendgrid": "SENDGRID_WEBHOOK_PUBLIC_KEY",
    "resend":   "RESEND_WEBHOOK_SECRET",
}


@router.post("/webhook/{provider}")
@limiter.limit("300/minute")
async def api_webhook(request: Request, provider: str):
    """
    Webhook de entrega — procesa bounces, unsubscribes, delivery events.

    Security model (default STRICT):
      - sendgrid: requiere SENDGRID_WEBHOOK_PUBLIC_KEY  → 503 si no configurado
      - resend:   requiere RESEND_WEBHOOK_SECRET         → 503 si no configurado
      - firma inválida → 403

    Proveedores desconocidos son rechazados (404).
    Rate limit: 300 req/min para absorber bursts legítimos de delivery events.
    """
    if provider not in _WEBHOOK_KEY_ENV:
        raise HTTPException(status_code=404, detail=f"Provider webhook '{provider}' no soportado")

    key_env    = _WEBHOOK_KEY_ENV[provider]
    secret_val = os.getenv(key_env, "")

    # Strict security: reject if no secret configured (prevents unauthenticated event injection)
    if not secret_val:
        raise HTTPException(
            status_code=503,
            detail=f"Webhook {provider} no configurado — definir {key_env} para activar",
        )

    body    = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}

    if not _verify_webhook(provider, headers, body):
        logger.warning(f"[e4/webhook/{provider}] firma inválida — request rechazado")
        raise HTTPException(status_code=403, detail="Firma webhook inválida")

    try:
        payload = json.loads(body)
    except Exception:
        raise HTTPException(status_code=400, detail="JSON inválido")

    # SendGrid envía una lista; Resend envía un objeto
    events = payload if isinstance(payload, list) else [payload]
    for event in events:
        try:
            await _process_webhook_event(provider, event)
        except Exception as exc:
            logger.warning(f"[e4/webhook/{provider}] error procesando evento: {exc}")

    return {"received": True, "count": len(events)}


@router.get("/status")
async def api_status():
    """Estado del módulo de email — qué provider está configurado."""
    provider = EMAIL_PROVIDER
    configured = False
    if provider == "sendgrid":
        configured = bool(os.getenv("SENDGRID_API_KEY"))
    elif provider == "resend":
        configured = bool(os.getenv("RESEND_API_KEY"))
    elif provider == "ses":
        configured = bool(os.getenv("AWS_ACCESS_KEY_ID"))
    elif provider == "stub":
        configured = True

    return {
        "module": "e4_email",
        "status": "REAL" if (configured and provider != "stub") else "STUB",
        "provider": provider,
        "configured": configured,
        "rate_limits": {"hourly": RATE_HOURLY, "daily": RATE_DAILY},
    }
