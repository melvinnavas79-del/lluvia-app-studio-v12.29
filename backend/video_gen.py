"""
Generación de videos con Sora 2 usando OpenAI SDK DIRECTO (cuenta del admin).
NO depende de EMERGENT_LLM_KEY: usa OPENAI_API_KEY del admin para que el
costo se cargue a SU billing de OpenAI (no al Universal Key de Emergent).
"""

import os
import asyncio
import uuid
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from openai import OpenAI

logger = logging.getLogger("video_gen")

UPLOAD_DIR = Path(__file__).parent / "uploads" / "ai_videos"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Combinaciones soportadas por Sora 2 (verificado contra API real)
ALLOWED_DURATIONS = {4, 8, 12}
ALLOWED_SIZES = {"720x1280", "1280x720"}
DEFAULT_SIZE = "720x1280"  # vertical 9:16 ideal para TikTok/Reels/Shorts
DEFAULT_DURATION = 8

# Tarifa en oros segun duracion (cubre costo OpenAI + margen del admin)
COST_BY_DURATION = {4: 30, 8: 40, 12: 55}

_db_ref: dict = {"db": None}
_ACTIVE_TASKS: set = set()


def set_db(db) -> None:
    _db_ref["db"] = db


def _openai_client() -> OpenAI:
    """Crea cliente OpenAI usando la API key del admin (NO la Universal Key)."""
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY no configurada en backend/.env")
    return OpenAI(api_key=key)


def _sync_generate(prompt: str, model: str, size: str, duration: int, output_path: str) -> Optional[str]:
    """Llamada bloqueante a Sora 2 via OpenAI SDK directo. Hace polling cada
    5 seg hasta status=completed|failed. Descarga el mp4 al disco."""
    client = _openai_client()
    # Crear video job
    video = client.videos.create(
        model=model,
        prompt=prompt,
        seconds=str(duration),
        size=size,
    )
    job_id = video.id
    logger.info(f"Sora 2 job created: {job_id} status={video.status}")
    # Polling
    deadline = time.time() + (900 if duration >= 12 else 600)
    while video.status in ("queued", "in_progress"):
        if time.time() > deadline:
            raise RuntimeError(f"Sora 2 timeout despues de {int(time.time()-deadline+600)}s")
        time.sleep(6)
        video = client.videos.retrieve(job_id)
    if video.status != "completed":
        err = getattr(video, "error", None) or "Sora 2 status=" + video.status
        raise RuntimeError(f"Sora 2 fallo: {err}")
    # Descargar el contenido (devuelve binary)
    content = client.videos.download_content(job_id, variant="video")
    # `content` es un HttpxBinaryResponseContent: usar write_to_file
    if hasattr(content, "write_to_file"):
        content.write_to_file(output_path)
    else:
        # Fallback por si el SDK devuelve bytes
        with open(output_path, "wb") as f:
            f.write(content.content if hasattr(content, "content") else content)
    return output_path


async def _run_job(job_id: str, prompt: str, model: str, size: str, duration: int) -> None:
    db = _db_ref["db"]
    fname = f"{job_id}.mp4"
    fpath = UPLOAD_DIR / fname
    started_at = time.time()
    try:
        await db.video_jobs.update_one(
            {"id": job_id},
            {"$set": {"status": "generating", "started_at": datetime.now(timezone.utc).isoformat()}},
        )
        await asyncio.to_thread(_sync_generate, prompt, model, size, duration, str(fpath))
        if not fpath.exists() or fpath.stat().st_size < 1024:
            raise RuntimeError("OpenAI no devolvio video (archivo vacio)")
        await db.video_jobs.update_one(
            {"id": job_id},
            {"$set": {
                "status": "ready",
                "video_url": f"/api/uploads/ai_videos/{fname}",
                "size_bytes": fpath.stat().st_size,
                "duration_ms": int((time.time() - started_at) * 1000),
                "finished_at": datetime.now(timezone.utc).isoformat(),
            }},
        )
        logger.info(f"video_job {job_id} READY ({fpath.stat().st_size} bytes)")
    except Exception as e:
        logger.exception(f"video_job {job_id} FAILED: {e}")
        err_text = str(e)
        if "insufficient_quota" in err_text.lower() or "billing" in err_text.lower():
            err_text = (
                "Tu cuenta de OpenAI no tiene saldo o no tiene acceso a Sora 2. "
                "Recargá en https://platform.openai.com/settings/organization/billing. "
                "Detalle: " + err_text[:200]
            )
        elif "model_not_found" in err_text.lower() or "does not have access" in err_text.lower():
            err_text = (
                "Tu cuenta de OpenAI no tiene acceso a Sora 2 todavía. "
                "Pedí acceso en https://platform.openai.com/. "
                "Detalle: " + err_text[:200]
            )
        # Refund automatico
        try:
            import credits as credits_mod
            job_doc = await db.video_jobs.find_one(
                {"id": job_id}, {"_id": 0, "charged_oros": 1, "user_id": 1}
            )
            charged = int((job_doc or {}).get("charged_oros") or 0)
            uid = (job_doc or {}).get("user_id")
            refunded = False
            if charged > 0 and uid:
                await credits_mod.refund(
                    uid, charged, "sora2_failed",
                    {"job_id": job_id, "error": err_text[:200]},
                )
                refunded = True
                logger.info(f"video_job {job_id} REFUNDED {charged} oros")
        except Exception as re:
            logger.exception(f"video_job {job_id} REFUND FAILED: {re}")
            refunded = False
        await db.video_jobs.update_one(
            {"id": job_id},
            {"$set": {
                "status": "error",
                "error": err_text[:400],
                "refunded": refunded,
                "finished_at": datetime.now(timezone.utc).isoformat(),
            }},
        )


async def enqueue_video(
    user_id: str,
    prompt: str,
    duration: int = DEFAULT_DURATION,
    size: str = DEFAULT_SIZE,
    model: str = "sora-2",
    charged_oros: int = 0,
) -> dict:
    db = _db_ref["db"]
    if duration not in ALLOWED_DURATIONS:
        duration = DEFAULT_DURATION
    if size not in ALLOWED_SIZES:
        size = DEFAULT_SIZE
    if model not in {"sora-2", "sora-2-pro"}:
        model = "sora-2"
    job_id = str(uuid.uuid4())
    doc = {
        "id": job_id,
        "user_id": user_id,
        "prompt": prompt[:2000],
        "model": model,
        "size": size,
        "duration": duration,
        "status": "queued",
        "video_url": None,
        "error": None,
        "charged_oros": int(charged_oros),
        "refunded": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.video_jobs.insert_one(doc)
    task = asyncio.create_task(_run_job(job_id, prompt, model, size, duration))
    _ACTIVE_TASKS.add(task)
    task.add_done_callback(_ACTIVE_TASKS.discard)
    return {
        "id": job_id,
        "status": "queued",
        "model": model,
        "size": size,
        "duration": duration,
        "estimated_wait_sec": 180 if duration == 4 else (300 if duration == 8 else 480),
    }


async def get_job(user_id: str, job_id: str) -> Optional[dict]:
    db = _db_ref["db"]
    doc = await db.video_jobs.find_one({"id": job_id, "user_id": user_id}, {"_id": 0})
    return doc
