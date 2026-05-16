"""
Generación de imágenes con Gemini Nano Banana (gemini-3.1-flash-image-preview)
vía emergentintegrations + EMERGENT_LLM_KEY.

Usado por la tool `generate_haircut_preview` del agente Estilista Visual:
recibe la foto original del cliente + descripción del nuevo look y devuelve
una imagen "After" guardada en /app/backend/uploads/ai_generated/.
"""

import os
import base64
import uuid
import logging
import mimetypes
from pathlib import Path
from typing import Optional

import httpx
from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent

logger = logging.getLogger("image_gen")

UPLOAD_DIR = Path(__file__).parent / "uploads" / "ai_generated"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

CHAT_IMAGES_DIR = Path(__file__).parent / "uploads" / "chat_images"


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


async def generate_haircut_preview(
    original_image_url: str,
    look_description: str,
    user_id: str,
) -> dict:
    """Genera una imagen "after" con el nuevo corte/color.

    Retorna dict con:
      ok: bool
      after_url: '/api/uploads/ai_generated/...' (URL pública relativa)
      before_url: la original (echo)
      look: el prompt usado
      error: si falla
    """
    api_key = os.getenv("EMERGENT_LLM_KEY")
    if not api_key:
        return {"ok": False, "error": "EMERGENT_LLM_KEY no configurada"}

    raw = await _fetch_image_bytes(original_image_url)
    if not raw:
        return {"ok": False, "error": "No pude leer la imagen original"}

    image_b64 = base64.b64encode(raw).decode("utf-8")

    prompt = (
        f"Edit the person in this photo to show how they would look with this new hairstyle: "
        f"{look_description}. "
        "Keep the EXACT same face, identity, skin tone, eyes, and facial proportions. "
        "Only modify the hair (length, color, style, texture) according to the description. "
        "Use clean, professional salon-style lighting and a neutral background. "
        "Photorealistic, magazine-quality result. No text overlays, no watermarks."
    )

    try:
        chat = LlmChat(
            api_key=api_key,
            session_id=f"haircut-{user_id}-{uuid.uuid4().hex[:8]}",
            system_message="You are a professional hairstyle visualizer.",
        ).with_model("gemini", "gemini-3.1-flash-image-preview").with_params(
            modalities=["image", "text"]
        )

        msg = UserMessage(text=prompt, file_contents=[ImageContent(image_b64)])
        _text, images = await chat.send_message_multimodal_response(msg)
    except Exception as e:
        logger.exception(f"Nano Banana fallo: {e}")
        return {"ok": False, "error": f"Generacion fallo: {str(e)[:200]}"}

    if not images:
        return {"ok": False, "error": "Nano Banana no devolvio imagenes"}

    first = images[0]
    img_bytes = base64.b64decode(first["data"])
    mime = first.get("mime_type", "image/png")
    ext = mimetypes.guess_extension(mime) or ".png"
    if ext == ".jpe":
        ext = ".jpg"
    fname = f"{user_id}_after_{uuid.uuid4().hex}{ext}"
    fpath = UPLOAD_DIR / fname
    fpath.write_bytes(img_bytes)

    return {
        "ok": True,
        "after_url": f"/api/uploads/ai_generated/{fname}",
        "before_url": original_image_url,
        "look": look_description,
        "size": len(img_bytes),
        "mime_type": mime,
    }
