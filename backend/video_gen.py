"""
Generación de videos cortos con Sora 2 (OpenAI Video Generation) vía
emergentintegrations + EMERGENT_LLM_KEY.

Estrategia: los videos tardan 2-5 minutos en generar, así que la tool
encola un job en MongoDB (collection: video_jobs), lanza la generación
en background con asyncio.create_task, y el frontend hace polling al
endpoint GET /api/console/video-jobs/{id} hasta status=ready|error.
"""

import os
import asyncio
import uuid
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from emergentintegrations.llm.openai.video_generation import OpenAIVideoGeneration

# Patch del whitelist del SDK: la API real solo acepta 720x1280 y 1280x720,
# pero el SDK local valida contra una lista antigua. Reescribimos SIZES.
OpenAIVideoGeneration.SIZES = {
    "720x1280": {"width": 720, "height": 1280},
    "1280x720": {"width": 1280, "height": 720},
}

logger = logging.getLogger("video_gen")

UPLOAD_DIR = Path(__file__).parent / "uploads" / "ai_videos"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Combinaciones soportadas por Sora 2 (verificado contra API real)
ALLOWED_DURATIONS = {4, 8, 12}
ALLOWED_SIZES = {"720x1280", "1280x720"}
DEFAULT_SIZE = "720x1280"  # vertical 9:16 ideal para TikTok/Reels/Shorts
DEFAULT_DURATION = 8

# Tarifa en oros segun duracion (cobramos al cliente cubriendo el costo + margen)
COST_BY_DURATION = {4: 30, 8: 40, 12: 55}

_db_ref: dict = {"db": None}

# Mantenemos referencia a tasks activos para evitar que el GC los mate
# (asyncio.create_task con fire-and-forget puede ser recolectado).
_ACTIVE_TASKS: set = set()


def set_db(db) -> None:
    _db_ref["db"] = db


def _sync_generate(prompt: str, model: str, size: str, duration: int, output_path: str) -> Optional[str]:
    """Llamada bloqueante a Sora 2. Se ejecuta en asyncio.to_thread."""
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        raise RuntimeError("EMERGENT_LLM_KEY no configurada")
    video_gen = OpenAIVideoGeneration(api_key=api_key)
    video_bytes = video_gen.text_to_video(
        prompt=prompt,
        model=model,
        size=size,
        duration=duration,
        max_wait_time=900 if duration >= 12 else 600,
    )
    if not video_bytes:
        return None
    video_gen.save_video(video_bytes, output_path)
    return output_path


async def _run_job(job_id: str, prompt: str, model: str, size: str, duration: int) -> None:
    """Worker async que actualiza el job en mongo: queued -> generating -> ready/error."""
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
            raise RuntimeError("Sora 2 no devolvio video (archivo vacio)")
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
        await db.video_jobs.update_one(
            {"id": job_id},
            {"$set": {
                "status": "error",
                "error": str(e)[:300],
                "finished_at": datetime.now(timezone.utc).isoformat(),
            }},
        )


async def enqueue_video(
    user_id: str,
    prompt: str,
    duration: int = DEFAULT_DURATION,
    size: str = DEFAULT_SIZE,
    model: str = "sora-2",
) -> dict:
    """Encola un job de video, lo dispara en background y retorna metadatos."""
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
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.video_jobs.insert_one(doc)
    # Disparar background (no await). Guardamos referencia para que el GC no
    # mate el task antes de que termine la generación.
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
    """Obtiene el estado del job (solo para el dueño)."""
    db = _db_ref["db"]
    doc = await db.video_jobs.find_one({"id": job_id, "user_id": user_id}, {"_id": 0})
    return doc
