"""
Generación de Before/After con OpenAI image edit (gpt-image-1) usando la
OPENAI_API_KEY del admin. NO depende de EMERGENT_LLM_KEY.

El modelo gpt-image-1 acepta image edit con un prompt textual y preserva
mejor la identidad facial que DALL-E 3. Reemplaza el uso anterior de
Gemini Nano Banana via emergentintegrations.
"""

import os
import base64
import io
import uuid
import logging
from pathlib import Path
from typing import Optional

import httpx
from openai import OpenAI

logger = logging.getLogger("image_gen")

UPLOAD_DIR = Path(__file__).parent / "uploads" / "ai_generated"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

CHAT_IMAGES_DIR = Path(__file__).parent / "uploads" / "chat_images"


def _openai_client() -> OpenAI:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY no configurada")
    return OpenAI(api_key=key)


async def _fetch_image_bytes(image_url: str) -> Optional[bytes]:
    """Devuelve los bytes de la imagen original. Soporta URLs absolutas (https://...)
    y URLs relativas tipo /api/uploads/chat_images/X.png (lee del disco)."""
    if not image_url:
        return None
    if image_url.startswith("/api/uploads/chat_images/"):
        fname = image_url.rsplit("/", 1)[-1]
        fpath = CHAT_IMAGES_DIR / fname
        if fpath.exists():
            return fpath.read_bytes()
        return None
    if image_url.startswith("http://") or image_url.startswith("https://"):
        try:
            async with httpx.AsyncClient(timeout=20.0) as cli:
                r = await cli.get(image_url)
                if r.status_code == 200:
                    return r.content
        except Exception as e:
            logger.warning(f"No pude bajar la imagen original: {e}")
            return None
    return None


def _sync_edit(image_bytes: bytes, prompt: str) -> Optional[bytes]:
    """Llamada bloqueante a OpenAI images.edit con gpt-image-1."""
    client = _openai_client()
    # gpt-image-1 acepta hasta 4MB y formatos png/jpg/webp
    bio = io.BytesIO(image_bytes)
    bio.name = "input.png"
    resp = client.images.edit(
        model="gpt-image-1",
        image=bio,
        prompt=prompt,
        size="1024x1024",
        n=1,
    )
    if not resp.data:
        return None
    # gpt-image-1 devuelve b64_json (no url) por default
    b64 = resp.data[0].b64_json
    if not b64:
        # Fallback si vino url
        url = getattr(resp.data[0], "url", None)
        if url:
            r = httpx.get(url, timeout=30.0)
            return r.content if r.status_code == 200 else None
        return None
    return base64.b64decode(b64)


async def generate_haircut_preview(
    original_image_url: str,
    look_description: str,
    user_id: str,
) -> dict:
    """Genera una imagen "after" con el nuevo corte/color usando OpenAI gpt-image-1."""
    import asyncio
    raw = await _fetch_image_bytes(original_image_url)
    if not raw:
        return {"ok": False, "error": "No pude leer la imagen original"}

    prompt = (
        f"Edit this person to show the new hairstyle: {look_description}. "
        "Keep the EXACT same face, identity, skin tone, eyes, and facial proportions. "
        "Only modify the hair (length, color, style, texture). "
        "Professional salon-style lighting, neutral background, photorealistic magazine quality. "
        "No text overlays, no watermarks."
    )

    try:
        img_bytes = await asyncio.to_thread(_sync_edit, raw, prompt)
    except Exception as e:
        logger.exception(f"OpenAI image edit fallo: {e}")
        err = str(e)
        if "insufficient_quota" in err.lower() or "billing" in err.lower():
            err = "Tu cuenta de OpenAI no tiene saldo. Recargá en https://platform.openai.com/settings/organization/billing"
        elif "model_not_found" in err.lower() or "does not have access" in err.lower():
            err = "Tu cuenta de OpenAI no tiene acceso a gpt-image-1. Verificá tu tier en platform.openai.com"
        return {"ok": False, "error": err[:300]}

    if not img_bytes:
        return {"ok": False, "error": "OpenAI no devolvio imagen"}

    fname = f"{user_id}_after_{uuid.uuid4().hex}.png"
    fpath = UPLOAD_DIR / fname
    fpath.write_bytes(img_bytes)

    return {
        "ok": True,
        "after_url": f"/api/uploads/ai_generated/{fname}",
        "before_url": original_image_url,
        "look": look_description,
        "size": len(img_bytes),
        "mime_type": "image/png",
    }
