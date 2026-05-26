"""
============================================================
JOB SCHEDULER — Motor central de jobs/eventos/tareas
STATUS: REAL

Mongo-backed asyncio worker unificado para todo el ecosistema.
Sin dependencias externas (no Celery/Redis/Kafka).
Preparado para escalar: worker_id único, locking atómico por
findOneAndUpdate, visibility timeout, heartbeat, DLQ.

Tipos de jobs soportados:
  social_post_publish   PARCIAL  — E10 infraestructura real, posting real sólo con OAuth token
  campaign_dispatch     PARCIAL  — E4 infraestructura real, posting real sólo con OAuth token
  gmail_followup_send   REAL     — envía email vía Gmail API si OAuth configurado
  webhook_retry         REAL     — HTTP POST con aiohttp, reintentos exponenciales
  workflow_step         STUB     — placeholder para E6/E3

Colección MongoDB: jobs / jobs_audit
Estados: queued → running → completed
         running → retrying (backoff exponencial) → queued
         running → failed (max_attempts) → dead_letter (manual)

Integración E9: todos los jobs emiten eventos automáticamente.
============================================================
"""

import asyncio
import logging
import os
import random
import re
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone, timedelta
from typing import Optional
from urllib.parse import urlparse

import aiohttp
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from pymongo.errors import DuplicateKeyError

import auth

logger = logging.getLogger("job_scheduler")

# ── DB ─────────────────────────────────────────────────────────────────────────
_db_ref: dict = {"db": None}


def set_db(db) -> None:
    _db_ref["db"] = db


def _db():
    if _db_ref["db"] is None:
        raise RuntimeError("job_scheduler: DB no inicializado")
    return _db_ref["db"]


router = APIRouter(prefix="/jobs", tags=["Jobs-Scheduler"])


# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

VISIBILITY_TIMEOUT_SECS   = int(os.environ.get("JOB_VISIBILITY_TIMEOUT", "120"))
HEARTBEAT_INTERVAL_SECS   = 15
POLL_INTERVAL_SECS        = 2
POLL_IDLE_SECS            = 10
BRIDGE_INTERVAL_SECS      = 30
STALE_CHECK_INTERVAL_SECS = 30
DEFAULT_MAX_ATTEMPTS      = 3
BACKOFF_BASE_SECS         = 30
BACKOFF_MAX_SECS          = 3600
# Per-job execution timeout — prevents a hung handler from blocking the work loop forever.
# Without this, the heartbeat keeps extending locked_until for a stuck job indefinitely.
JOB_EXECUTION_TIMEOUT_SECS = int(os.environ.get("JOB_EXECUTION_TIMEOUT", "300"))

# Anti-flood: max jobs executed per tenant per FLOOD_WINDOW_SECS
# NOTE: In-process only — not safe across multiple worker processes.
# For multi-process deployments, replace with a Redis/Mongo-backed counter.
FLOOD_MAX_JOBS    = int(os.environ.get("JOB_FLOOD_MAX", "10"))
FLOOD_WINDOW_SECS = 60

# Max total active-queue depth. Backpressure: reject new jobs when exceeded.
# Protects against runaway bridge loops or buggy callers flooding the queue.
MAX_QUEUE_DEPTH = int(os.environ.get("JOB_MAX_QUEUE_DEPTH", "10000"))

# Webhook SSRF: private/loopback address prefixes to block
_SSRF_BLOCKED = re.compile(
    r"^(localhost|127\.|0\.|169\.254\.|10\.|"
    r"172\.(1[6-9]|2[0-9]|3[01])\.|192\.168\.|"
    r"\[::1\]|\[fc|fd|fe80)",
    re.IGNORECASE,
)

VALID_JOB_TYPES = frozenset({
    "social_post_publish",
    "campaign_dispatch",
    "gmail_followup_send",
    "webhook_retry",
    "workflow_step",
})


# ══════════════════════════════════════════════════════════════════════════════
# ANTI-FLOOD — sliding window per tenant (in-memory)
# ══════════════════════════════════════════════════════════════════════════════

_flood_windows: dict[str, deque] = defaultdict(deque)


def _check_flood(tenant_id: str) -> bool:
    """True = within limits and slot consumed. False = throttled."""
    now    = time.monotonic()
    window = _flood_windows[tenant_id]
    while window and window[0] < now - FLOOD_WINDOW_SECS:
        window.popleft()
    if len(window) >= FLOOD_MAX_JOBS:
        return False
    window.append(now)
    return True


def _prune_flood_windows() -> None:
    """Remove idle tenant entries from _flood_windows to prevent unbounded growth.
    Called periodically from _stale_lock_loop. Safe to call any time."""
    now = time.monotonic()
    cutoff = now - FLOOD_WINDOW_SECS
    idle = [k for k, v in _flood_windows.items() if not v or v[-1] < cutoff]
    for k in idle:
        del _flood_windows[k]
    if idle:
        logger.debug("[JOB] Pruned %d idle flood-window entries", len(idle))


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC ENQUEUE — callable from any module
# ══════════════════════════════════════════════════════════════════════════════

async def enqueue_job(
    job_type: str,
    payload: dict,
    tenant_id: str = "default",
    run_at: Optional[datetime] = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    priority: int = 5,
    idempotency_key: Optional[str] = None,
) -> dict:
    """
    Encola un job. Retorna {"ok": True, "duplicate": bool, "job": {...}}.
    idempotency_key: si ya existe un job con esa key en {queued,running,retrying}
    devuelve el existente sin duplicar.
    """
    if job_type not in VALID_JOB_TYPES:
        raise ValueError(f"job_type {job_type!r} inválido. Válidos: {sorted(VALID_JOB_TYPES)}")

    db = _db()

    if idempotency_key:
        existing = await db.jobs.find_one(
            {
                "idempotency_key": idempotency_key,
                "status": {"$in": ["queued", "running", "retrying"]},
            },
            {"_id": 0},
        )
        if existing:
            return {"ok": True, "duplicate": True, "job": existing}

    # Backpressure: reject if active queue is at capacity
    active_depth = await db.jobs.count_documents(
        {"status": {"$in": ["queued", "retrying"]}}
    )
    if active_depth >= MAX_QUEUE_DEPTH:
        logger.warning("[JOB] Queue at capacity (%d/%d), rejecting %s", active_depth, MAX_QUEUE_DEPTH, job_type)
        return {"ok": False, "error": f"Queue at capacity: {active_depth}/{MAX_QUEUE_DEPTH}", "queue_full": True}

    now    = datetime.now(timezone.utc)
    run_at = run_at or now
    job_id = f"J-{uuid.uuid4().hex[:12].upper()}"

    doc = {
        "job_id":          job_id,
        "job_type":        job_type,
        "status":          "queued",
        "tenant_id":       tenant_id,
        "payload":         payload,
        "priority":        priority,
        "run_at":          run_at.isoformat(),
        "locked_until":    now.isoformat(),
        "worker_id":       None,
        "heartbeat_at":    None,
        "attempts":        0,
        "max_attempts":    max_attempts,
        "last_error":      None,
        "idempotency_key": idempotency_key,
        "created_at":      now.isoformat(),
        "updated_at":      now.isoformat(),
        "completed_at":    None,
        "result":          None,
    }
    try:
        await db.jobs.insert_one(doc)
    except DuplicateKeyError:
        # Race: another caller inserted the same idempotency_key between our check and insert.
        # Return the existing job rather than propagating the exception.
        existing = await db.jobs.find_one({"idempotency_key": idempotency_key}, {"_id": 0})
        if existing:
            return {"ok": True, "duplicate": True, "job": existing}
        raise  # different unique key collision — should not happen
    logger.info(f"[JOB] enqueued {job_id} type={job_type} tenant={tenant_id} run_at={run_at.isoformat()}")

    await _emit_job("job.created", job_id, job_type, tenant_id)

    return {"ok": True, "duplicate": False, "job": {k: v for k, v in doc.items() if k != "_id"}}


# ══════════════════════════════════════════════════════════════════════════════
# E9 INTEGRATION — via e9_emitters (non-blocking)
# ══════════════════════════════════════════════════════════════════════════════

async def _emit_job(
    event_type: str,
    job_id: str,
    job_type: str,
    tenant_id: str = "default",
    worker_id: str = "",
    attempt: int = 0,
    elapsed_ms: int = 0,
    error: str = "",
    queue_depth: int = -1,
) -> None:
    try:
        import e9_emitters
        await e9_emitters.track_job_event(
            event_type=event_type,
            job_id=job_id,
            job_type=job_type,
            tenant_id=tenant_id,
            worker_id=worker_id,
            attempt=attempt,
            elapsed_ms=elapsed_ms,
            error=error,
            queue_depth=queue_depth,
        )
    except Exception as exc:
        logger.debug(f"[JOB] E9 emit skipped: {exc}")


# ══════════════════════════════════════════════════════════════════════════════
# JOB HANDLERS
# ══════════════════════════════════════════════════════════════════════════════

async def _handle_social_post_publish(payload: dict, tenant_id: str) -> dict:
    """
    STATUS: PARCIAL
    Infraestructura real. Posting real sólo si hay OAuth token en e10_connections.
    Procesa un post de e10_posts (status=queued) ya encolado.
    """
    import e10_social

    post_id = payload.get("post_id")
    db      = _db()

    if post_id:
        post_doc = await db.e10_posts.find_one({"post_id": post_id})
        if not post_doc:
            return {"ok": False, "error": f"Post {post_id!r} no encontrado en e10_posts"}
        if post_doc.get("status") == "published":
            return {"ok": True, "note": "already published", "post_id": post_id}
    else:
        post_doc = payload

    content   = post_doc.get("content", "")
    platforms = post_doc.get("platforms", ["instagram"])
    media_url = post_doc.get("media_url", "")
    hashtags  = post_doc.get("hashtags", [])

    results: dict = {}
    for platform in platforms:
        creds  = await e10_social._get_platform_credentials(db, platform, tenant_id)
        token  = creds.get("access_token", "")
        puid   = creds.get("platform_user_id", "")
        result = await e10_social._post_to_platform_api(
            platform, token, content, media_url, hashtags, puid
        )
        results[platform] = result

    all_ok = all(r.get("status") in ("published", "processing") for r in results.values())

    if post_id:
        await db.e10_posts.update_one(
            {"post_id": post_id},
            {"$set": {
                "status":           "published" if all_ok else "queued",
                "platform_results": results,
                "published_at":     datetime.now(timezone.utc).isoformat(),
            }},
        )

    return {"ok": all_ok, "post_id": post_id, "results": results}


async def _handle_campaign_dispatch(payload: dict, tenant_id: str) -> dict:
    """
    STATUS: PARCIAL
    Infraestructura real. Posting real sólo si hay OAuth token.
    Procesa un ítem de e4_scheduled_content (status=scheduled).
    """
    import e10_social

    sched_id = payload.get("sched_id")
    db       = _db()

    if sched_id:
        sched_doc = await db.e4_scheduled_content.find_one({"id": sched_id})
        if not sched_doc:
            return {"ok": False, "error": f"Scheduled content {sched_id!r} no encontrado"}
        if sched_doc.get("status") in ("published", "failed"):
            return {"ok": True, "note": f"already {sched_doc['status']}", "sched_id": sched_id}
    else:
        sched_doc = payload

    content   = sched_doc.get("content", "")
    platforms = sched_doc.get("platforms", ["instagram"])

    results: dict = {}
    for platform in platforms:
        creds  = await e10_social._get_platform_credentials(db, platform, tenant_id)
        token  = creds.get("access_token", "")
        puid   = creds.get("platform_user_id", "")
        result = await e10_social._post_to_platform_api(
            platform, token, content, "", [], puid
        )
        results[platform] = result

    all_ok = all(r.get("status") in ("published", "processing") for r in results.values())

    if sched_id:
        await db.e4_scheduled_content.update_one(
            {"id": sched_id},
            {"$set": {
                "status":       "published" if all_ok else "failed",
                "results":      results,
                "processed_at": datetime.now(timezone.utc).isoformat(),
            }},
        )

    return {"ok": all_ok, "sched_id": sched_id, "results": results}


async def _handle_gmail_followup_send(payload: dict, tenant_id: str) -> dict:
    """
    STATUS: REAL si Gmail OAuth está configurado para el tenant.
    Envía el followup programado de e11_followups vía Gmail API.
    """
    import gmail_maestro

    followup_id = payload.get("followup_id")
    db          = _db()

    if followup_id:
        doc = await db.e11_followups.find_one({"followup_id": followup_id})
        if not doc:
            return {"ok": False, "error": f"Followup {followup_id!r} no encontrado"}
        if doc.get("status") in ("sent", "failed"):
            return {"ok": True, "note": f"already {doc['status']}", "followup_id": followup_id}
    else:
        doc = payload

    to_addr  = doc.get("to", "")
    subject  = doc.get("subject", "Seguimiento")
    message  = doc.get("message", "Seguimiento de tu consulta anterior. ¿Pudiste resolverlo?")

    if not to_addr:
        return {"ok": False, "error": "No recipient address in followup doc"}

    # Resolve Gmail user_id for this tenant
    user_id = doc.get("user_id") or payload.get("user_id", "")
    if not user_id:
        linked  = await db.gmail_accounts.find_one({"tenant_id": tenant_id}, {"user_id": 1})
        user_id = linked["user_id"] if linked else ""

    if not user_id:
        return {
            "ok":    False,
            "error": f"No Gmail account linked for tenant={tenant_id}. "
                     "Configure OAuth via /api/gmail/connect",
        }

    token = await gmail_maestro._get_valid_access_token(user_id)
    if not token:
        return {"ok": False, "error": f"Gmail OAuth token expirado/ausente para user={user_id}"}

    thread_id  = doc.get("thread_id", "")
    in_reply_to = doc.get("in_reply_to", "")
    references  = doc.get("references", "")
    raw_b64    = gmail_maestro._build_raw_reply(to_addr, subject, message, in_reply_to, references)

    draft_id = await gmail_maestro._create_gmail_draft(token, raw_b64, thread_id)
    if not draft_id:
        return {"ok": False, "error": "Falló crear Gmail draft"}

    msg_id = await gmail_maestro._send_gmail_draft(token, draft_id)
    ok     = bool(msg_id)

    if followup_id:
        await db.e11_followups.update_one(
            {"followup_id": followup_id},
            {"$set": {
                "status":       "sent" if ok else "failed",
                "sent_at":      datetime.now(timezone.utc).isoformat() if ok else None,
                "gmail_msg_id": msg_id or None,
            }},
        )

    return {"ok": ok, "followup_id": followup_id, "gmail_msg_id": msg_id}


async def _handle_webhook_retry(payload: dict, tenant_id: str) -> dict:
    """
    STATUS: REAL
    Reintenta la entrega de un webhook vía HTTP POST.
    payload: {url, headers, body}
    """
    url     = payload.get("url", "")
    headers = payload.get("headers", {})
    body    = payload.get("body", {})

    if not url:
        return {"ok": False, "error": "payload.url vacío"}

    # SSRF protection: only https allowed; block private/loopback addresses
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return {"ok": False, "error": f"SSRF: solo HTTPS permitido (scheme={parsed.scheme!r})"}
    host = parsed.hostname or ""
    if _SSRF_BLOCKED.match(host):
        return {"ok": False, "error": f"SSRF: dirección privada/loopback bloqueada ({host})"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json=body,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                ok = 200 <= resp.status < 300
                return {"ok": ok, "status_code": resp.status, "url": url}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "url": url}


async def _handle_workflow_step(payload: dict, tenant_id: str) -> dict:
    """
    STATUS: STUB — placeholder para pasos de workflow (E6/E3).
    payload: {step_type, step_data, workflow_id}
    """
    step_type   = payload.get("step_type", "unknown")
    workflow_id = payload.get("workflow_id", "")
    logger.info(
        f"[JOB] workflow_step STUB tenant={tenant_id} step={step_type} workflow={workflow_id}"
    )
    return {
        "ok":    True,
        "note":  "STUB — workflow execution not yet implemented",
        "step":  step_type,
    }


_HANDLERS = {
    "social_post_publish": _handle_social_post_publish,
    "campaign_dispatch":   _handle_campaign_dispatch,
    "gmail_followup_send": _handle_gmail_followup_send,
    "webhook_retry":       _handle_webhook_retry,
    "workflow_step":       _handle_workflow_step,
}


# ══════════════════════════════════════════════════════════════════════════════
# JOB WORKER
# ══════════════════════════════════════════════════════════════════════════════

class JobWorker:
    def __init__(self) -> None:
        self.worker_id       = f"W-{uuid.uuid4().hex[:8].upper()}"
        self._tasks: list[asyncio.Task] = []
        self._running        = False
        self._jobs_processed = 0
        self._jobs_failed    = 0
        self._started_at: Optional[datetime] = None

    # ── lifecycle ──────────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._running:
            return
        self._running    = True
        self._started_at = datetime.now(timezone.utc)
        self._tasks = [
            asyncio.create_task(self._work_loop(),       name="job_work_loop"),
            asyncio.create_task(self._heartbeat_loop(),  name="job_heartbeat"),
            asyncio.create_task(self._stale_lock_loop(), name="job_stale_locks"),
            asyncio.create_task(self._bridge_loop(),     name="job_bridge"),
        ]
        logger.info(f"[JOB] Worker {self.worker_id} started")

    async def stop(self) -> None:
        """Graceful stop: cancel all tasks and await their cleanup before returning.
        Must be awaited so shutdown handlers wait for task CancelledError cleanup."""
        self._running = False
        tasks = list(self._tasks)
        self._tasks.clear()
        for t in tasks:
            t.cancel()
        if tasks:
            # Wait for all tasks to finish handling their CancelledError.
            # return_exceptions=True prevents a secondary exception from hiding the shutdown.
            await asyncio.gather(*tasks, return_exceptions=True)
        logger.info(f"[JOB] Worker {self.worker_id} stopped cleanly")

    def status(self) -> dict:
        return {
            "worker_id":      self.worker_id,
            "running":        self._running,
            "started_at":     self._started_at.isoformat() if self._started_at else None,
            "jobs_processed": self._jobs_processed,
            "jobs_failed":    self._jobs_failed,
            "active_tasks":   len([t for t in self._tasks if not t.done()]),
        }

    # ── atomic claim ───────────────────────────────────────────────────────────

    async def _claim_next_job(self) -> Optional[dict]:
        db     = _db()
        now    = datetime.now(timezone.utc)
        locked = (now + timedelta(seconds=VISIBILITY_TIMEOUT_SECS)).isoformat()

        return await db.jobs.find_one_and_update(
            {
                "status":       {"$in": ["queued", "retrying"]},
                "run_at":       {"$lte": now.isoformat()},
                "locked_until": {"$lte": now.isoformat()},
            },
            {
                "$set": {
                    "status":       "running",
                    "worker_id":    self.worker_id,
                    "locked_until": locked,
                    "heartbeat_at": now.isoformat(),
                    "updated_at":   now.isoformat(),
                }
            },
            sort=[("priority", -1), ("run_at", 1)],
            return_document=True,
        )

    # ── work loop ──────────────────────────────────────────────────────────────

    async def _work_loop(self) -> None:
        logger.info(f"[JOB] Work loop active (worker={self.worker_id})")
        while self._running:
            try:
                doc = await self._claim_next_job()
                if doc is None:
                    await asyncio.sleep(POLL_IDLE_SECS)
                    continue
                await self._execute_job(doc)
                await asyncio.sleep(POLL_INTERVAL_SECS)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"[JOB] Work loop error: {exc}", exc_info=True)
                await asyncio.sleep(5)

    async def _execute_job(self, doc: dict) -> None:
        job_id    = doc["job_id"]
        job_type  = doc["job_type"]
        tenant_id = doc.get("tenant_id", "default")
        payload   = doc.get("payload", {})
        attempt   = doc.get("attempts", 0) + 1
        db        = _db()
        now       = datetime.now(timezone.utc)

        logger.info(f"[JOB] Executing {job_id} type={job_type} tenant={tenant_id} attempt={attempt}")
        await _emit_job("job.started", job_id, job_type, tenant_id,
                        worker_id=self.worker_id, attempt=attempt)

        # Anti-flood
        if not _check_flood(tenant_id):
            requeue_at = (now + timedelta(seconds=30)).isoformat()
            await db.jobs.update_one(
                {"job_id": job_id},
                {"$set": {
                    "status":       "queued",
                    "run_at":       requeue_at,
                    "worker_id":    None,
                    "updated_at":   now.isoformat(),
                }},
            )
            logger.warning(f"[JOB] Throttled tenant={tenant_id} — requeue in 30s")
            return

        handler = _HANDLERS.get(job_type)
        if not handler:
            await self._fail_job(doc, f"Unknown job_type: {job_type!r}", attempt)
            return

        start = time.monotonic()
        try:
            result     = await asyncio.wait_for(
                handler(payload, tenant_id),
                timeout=JOB_EXECUTION_TIMEOUT_SECS,
            )
            elapsed_ms = int((time.monotonic() - start) * 1000)

            if result.get("ok") is False:
                err = result.get("error", "Handler returned ok=False")
                await self._retry_or_fail(doc, err, attempt)
            else:
                await db.jobs.update_one(
                    {"job_id": job_id},
                    {"$set": {
                        "status":       "completed",
                        "attempts":     attempt,
                        "result":       result,
                        "completed_at": now.isoformat(),
                        "updated_at":   now.isoformat(),
                        "elapsed_ms":   elapsed_ms,
                    }},
                )
                self._jobs_processed += 1
                logger.info(f"[JOB] Completed {job_id} in {elapsed_ms}ms")

                await db.jobs_audit.insert_one({
                    "job_id":    job_id,
                    "event":     "completed",
                    "tenant_id": tenant_id,
                    "attempt":   attempt,
                    "elapsed_ms": elapsed_ms,
                    "at":        now.isoformat(),
                })
                await _emit_job("job.completed", job_id, job_type, tenant_id,
                               worker_id=self.worker_id, attempt=attempt, elapsed_ms=elapsed_ms)

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.error(f"[JOB] Exception in {job_id}: {exc}", exc_info=True)
            await self._retry_or_fail(doc, str(exc), attempt)

    async def _retry_or_fail(self, doc: dict, error: str, attempt: int) -> None:
        db           = _db()
        job_id       = doc["job_id"]
        max_attempts = doc.get("max_attempts", DEFAULT_MAX_ATTEMPTS)
        tenant_id    = doc.get("tenant_id", "default")
        now          = datetime.now(timezone.utc)

        if attempt >= max_attempts:
            await self._fail_job(doc, error, attempt)
            return

        # ±25% jitter prevents thundering herd when many jobs fail simultaneously
        delay_secs = min(BACKOFF_BASE_SECS * (2 ** attempt), BACKOFF_MAX_SECS)
        delay_secs = delay_secs * random.uniform(0.75, 1.25)
        run_at     = (now + timedelta(seconds=delay_secs)).isoformat()

        await db.jobs.update_one(
            {"job_id": job_id},
            {"$set": {
                "status":       "retrying",
                "attempts":     attempt,
                "last_error":   error,
                "run_at":       run_at,
                "locked_until": now.isoformat(),
                "worker_id":    None,
                "updated_at":   now.isoformat(),
            }},
        )
        logger.warning(
            f"[JOB] Retry {job_id} attempt={attempt}/{max_attempts} in {delay_secs}s"
        )
        await db.jobs_audit.insert_one({
            "job_id":     job_id,
            "event":      "retry_scheduled",
            "tenant_id":  tenant_id,
            "attempt":    attempt,
            "delay_secs": delay_secs,
            "error":      error,
            "at":         now.isoformat(),
        })
        await _emit_job("job.retry", job_id, doc["job_type"], tenant_id,
                       attempt=attempt, error=error)

    async def _fail_job(self, doc: dict, error: str, attempt: int) -> None:
        db        = _db()
        job_id    = doc["job_id"]
        tenant_id = doc.get("tenant_id", "default")
        now       = datetime.now(timezone.utc)

        await db.jobs.update_one(
            {"job_id": job_id},
            {"$set": {
                "status":     "failed",
                "attempts":   attempt,
                "last_error": error,
                "updated_at": now.isoformat(),
            }},
        )
        self._jobs_failed += 1
        logger.error(f"[JOB] Permanently failed {job_id} after {attempt} attempts: {error}")

        await db.jobs_audit.insert_one({
            "job_id":    job_id,
            "event":     "failed",
            "tenant_id": tenant_id,
            "attempt":   attempt,
            "error":     error,
            "at":        now.isoformat(),
        })
        await _emit_job("job.failed", job_id, doc["job_type"], tenant_id,
                       attempt=attempt, error=error)

    # ── heartbeat ──────────────────────────────────────────────────────────────

    async def _heartbeat_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(HEARTBEAT_INTERVAL_SECS)
                db     = _db()
                now    = datetime.now(timezone.utc)
                locked = (now + timedelta(seconds=VISIBILITY_TIMEOUT_SECS)).isoformat()

                result = await db.jobs.update_many(
                    {"status": "running", "worker_id": self.worker_id},
                    {"$set": {"heartbeat_at": now.isoformat(), "locked_until": locked}},
                )
                if result.modified_count > 0:
                    logger.debug(f"[JOB] Heartbeat {result.modified_count} jobs")
                    await _emit_job("worker.heartbeat", "bulk", "all",
                                   worker_id=self.worker_id,
                                   queue_depth=result.modified_count)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"[JOB] Heartbeat error: {exc}")

    # ── stale lock release ─────────────────────────────────────────────────────

    async def _stale_lock_loop(self) -> None:
        """Releases locks from workers that died without completing."""
        while self._running:
            try:
                await asyncio.sleep(STALE_CHECK_INTERVAL_SECS)
                db  = _db()
                now = datetime.now(timezone.utc).isoformat()

                result = await db.jobs.update_many(
                    {
                        "status":       "running",
                        "locked_until": {"$lte": now},
                        "worker_id":    {"$ne": self.worker_id},
                    },
                    {"$set": {
                        "status":       "queued",
                        "worker_id":    None,
                        "locked_until": now,
                        "updated_at":   now,
                        "last_error":   "Stale lock released — worker died",
                    }},
                )
                if result.modified_count > 0:
                    logger.warning(f"[JOB] Released {result.modified_count} stale locks")

                # Prune idle flood-window entries to prevent unbounded dict growth.
                # Entries whose deque is empty or fully expired are safe to remove.
                _prune_flood_windows()

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"[JOB] Stale lock error: {exc}")

    # ── bridge loops ───────────────────────────────────────────────────────────

    async def _bridge_loop(self) -> None:
        """
        Polls legacy collections and creates jobs for items ready to process.
        Idempotent: skips if a job with the same idempotency_key already exists.
        """
        await asyncio.sleep(10)  # let server fully initialize
        while self._running:
            try:
                await asyncio.gather(
                    self._bridge_e10_posts(),
                    self._bridge_e11_followups(),
                    self._bridge_e4_scheduled(),
                )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"[JOB] Bridge error: {exc}")
            await asyncio.sleep(BRIDGE_INTERVAL_SECS)

    async def _bridge_e10_posts(self) -> None:
        """e10_posts (status=queued, schedule_at<=now) → social_post_publish jobs."""
        db  = _db()
        now = datetime.now(timezone.utc).isoformat()

        async for post in db.e10_posts.find(
            {"status": "queued", "schedule_at": {"$lte": now}}
        ).limit(50):
            post_id = post.get("post_id")
            if not post_id:
                continue
            await enqueue_job(
                job_type="social_post_publish",
                payload={"post_id": post_id},
                tenant_id=post.get("tenant_id", "default"),
                max_attempts=3,
                idempotency_key=f"e10_post_{post_id}",
            )

    async def _bridge_e11_followups(self) -> None:
        """e11_followups (status=pending, send_at<=now) → gmail_followup_send jobs."""
        db  = _db()
        now = datetime.now(timezone.utc).isoformat()

        async for fu in db.e11_followups.find(
            {"status": "pending", "send_at": {"$lte": now}}
        ).limit(50):
            fid = fu.get("followup_id")
            if not fid:
                continue
            await enqueue_job(
                job_type="gmail_followup_send",
                payload={"followup_id": fid},
                tenant_id=fu.get("tenant_id", "default"),
                max_attempts=3,
                idempotency_key=f"e11_followup_{fid}",
            )

    async def _bridge_e4_scheduled(self) -> None:
        """e4_scheduled_content (status=scheduled, schedule_at<=now) → campaign_dispatch jobs."""
        db  = _db()
        now = datetime.now(timezone.utc).isoformat()

        async for item in db.e4_scheduled_content.find(
            {"status": "scheduled", "schedule_at": {"$lte": now}}
        ).limit(50):
            sid = item.get("id")
            if not sid:
                continue
            await enqueue_job(
                job_type="campaign_dispatch",
                payload={"sched_id": sid},
                tenant_id=item.get("tenant_id", "default"),
                max_attempts=3,
                idempotency_key=f"e4_sched_{sid}",
            )


# ── Singleton worker ────────────────────────────────────────────────────────────
_worker = JobWorker()


def start_worker() -> None:
    _worker.start()


async def stop_worker() -> None:
    await _worker.stop()


# ══════════════════════════════════════════════════════════════════════════════
# DB INDEXES — call from on_startup
# ══════════════════════════════════════════════════════════════════════════════

async def create_indexes() -> None:
    db = _db()
    # Primary claim index: covers the full _claim_next_job filter + sort.
    # Query: {status, run_at ≤ now, locked_until ≤ now}  sort: {priority -1, run_at 1}
    await db.jobs.create_index(
        [("status", 1), ("locked_until", 1), ("run_at", 1), ("priority", -1)],
        name="jobs_claim_idx",
    )
    await db.jobs.create_index([("status", 1), ("run_at", 1)])
    await db.jobs.create_index([("tenant_id", 1), ("status", 1)])
    await db.jobs.create_index("job_id", unique=True)
    await db.jobs.create_index("idempotency_key", sparse=True)
    await db.jobs.create_index([("job_type", 1), ("status", 1)])
    # Stale-lock query: {status=running, locked_until ≤ now, worker_id ≠ X}
    await db.jobs.create_index(
        [("status", 1), ("locked_until", 1), ("worker_id", 1)],
        name="jobs_stale_lock_idx",
    )
    await db.jobs_audit.create_index([("job_id", 1)])
    await db.jobs_audit.create_index([("tenant_id", 1), ("at", -1)])
    # Bridge source collection indexes — queried every BRIDGE_INTERVAL_SECS seconds
    await db.e10_posts.create_index(
        [("status", 1), ("schedule_at", 1)], name="e10_posts_bridge_idx"
    )
    await db.e11_followups.create_index(
        [("status", 1), ("send_at", 1)], name="e11_followups_bridge_idx"
    )
    await db.e4_scheduled_content.create_index(
        [("status", 1), ("schedule_at", 1)], name="e4_sched_bridge_idx"
    )
    logger.info("[JOB] MongoDB indexes created")


# ══════════════════════════════════════════════════════════════════════════════
# REST API
# ══════════════════════════════════════════════════════════════════════════════

class EnqueueIn(BaseModel):
    job_type:        str
    payload:         dict         = {}
    tenant_id:       str          = "default"
    run_at:          Optional[str] = None
    max_attempts:    int          = DEFAULT_MAX_ATTEMPTS
    priority:        int          = 5
    idempotency_key: Optional[str] = None


@router.post("")
async def api_enqueue(data: EnqueueIn, user: dict = Depends(auth.get_current_user)):
    run_at_dt: Optional[datetime] = None
    if data.run_at:
        try:
            run_at_dt = datetime.fromisoformat(data.run_at.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(400, f"run_at inválido: {data.run_at!r}")

    return await enqueue_job(
        job_type=data.job_type,
        payload=data.payload,
        tenant_id=data.tenant_id,
        run_at=run_at_dt,
        max_attempts=data.max_attempts,
        priority=data.priority,
        idempotency_key=data.idempotency_key,
    )


@router.get("")
async def api_list_jobs(
    tenant_id: Optional[str] = Query(None),
    status:    Optional[str] = Query(None),
    job_type:  Optional[str] = Query(None),
    limit:     int           = Query(50, le=200),
    user:      dict          = Depends(auth.get_current_user),
):
    db = _db()
    q: dict = {}
    if tenant_id: q["tenant_id"] = tenant_id
    if status:    q["status"]    = status
    if job_type:  q["job_type"]  = job_type

    cursor = db.jobs.find(q, {"_id": 0}).sort("created_at", -1).limit(limit)
    jobs   = [doc async for doc in cursor]
    return {"jobs": jobs, "count": len(jobs)}


@router.get("/stats")
async def api_stats(
    tenant_id: Optional[str] = Query(None),
    user:      dict          = Depends(auth.get_current_user),
):
    db       = _db()
    q: dict  = {"tenant_id": tenant_id} if tenant_id else {}
    pipeline = [
        {"$match": q},
        {"$group": {
            "_id":   {"status": "$status", "job_type": "$job_type"},
            "count": {"$sum": 1},
        }},
    ]
    rows  = [doc async for doc in db.jobs.aggregate(pipeline)]
    stats: dict = {}
    for row in rows:
        st  = row["_id"]["status"]
        jt  = row["_id"]["job_type"]
        cnt = row["count"]
        stats.setdefault(st, {})[jt] = cnt

    return {"stats": stats, "worker": _worker.status()}


@router.get("/worker")
async def api_worker_status(user: dict = Depends(auth.get_current_user)):
    return _worker.status()


@router.get("/{job_id}")
async def api_get_job(job_id: str, user: dict = Depends(auth.get_current_user)):
    db  = _db()
    doc = await db.jobs.find_one({"job_id": job_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, f"Job {job_id!r} no encontrado")
    return doc


@router.get("/{job_id}/audit")
async def api_job_audit(job_id: str, user: dict = Depends(auth.get_current_user)):
    db     = _db()
    trail  = [doc async for doc in db.jobs_audit.find(
        {"job_id": job_id}, {"_id": 0}
    ).sort("at", 1)]
    return {"job_id": job_id, "audit_trail": trail}


@router.post("/{job_id}/cancel")
async def api_cancel_job(job_id: str, user: dict = Depends(auth.get_current_user)):
    db  = _db()
    now = datetime.now(timezone.utc).isoformat()
    r   = await db.jobs.update_one(
        {"job_id": job_id, "status": {"$in": ["queued", "retrying"]}},
        {"$set": {"status": "failed", "last_error": "Cancelled by user", "updated_at": now}},
    )
    if r.modified_count == 0:
        raise HTTPException(400, f"Job {job_id!r} no está en queued/retrying")
    return {"ok": True, "job_id": job_id}


@router.post("/{job_id}/retry")
async def api_retry_job(job_id: str, user: dict = Depends(auth.get_current_user)):
    db  = _db()
    now = datetime.now(timezone.utc).isoformat()
    r   = await db.jobs.update_one(
        {"job_id": job_id, "status": {"$in": ["failed", "dead_letter"]}},
        {"$set": {
            "status":       "queued",
            "run_at":       now,
            "locked_until": now,
            "last_error":   None,
            "updated_at":   now,
        }},
    )
    if r.modified_count == 0:
        raise HTTPException(400, f"Job {job_id!r} no está en failed/dead_letter")
    return {"ok": True, "job_id": job_id, "status": "queued"}


@router.post("/{job_id}/dead_letter")
async def api_move_dlq(job_id: str, user: dict = Depends(auth.get_current_user)):
    db  = _db()
    now = datetime.now(timezone.utc).isoformat()
    doc = await db.jobs.find_one({"job_id": job_id, "status": "failed"},
                                  {"job_type": 1, "tenant_id": 1, "_id": 0})
    if not doc:
        raise HTTPException(400, f"Job {job_id!r} no está en failed")
    await db.jobs.update_one(
        {"job_id": job_id},
        {"$set": {"status": "dead_letter", "updated_at": now}},
    )
    await _emit_job("job.dead_letter", job_id,
                   doc.get("job_type", "unknown"),
                   doc.get("tenant_id", "default"))
    return {"ok": True, "job_id": job_id, "status": "dead_letter"}
