"""
Voz: Whisper (audio -> texto) y OpenAI TTS (texto -> audio).
"""

import io
import logging
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from openai import AsyncOpenAI

import config
import credits as credits_mod
import agents_catalog
from auth import get_current_user

logger = logging.getLogger("voice")
router = APIRouter(prefix="/voice", tags=["voice"])


def _client():
    if not config.OPENAI_API_KEY:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY no configurada")
    return AsyncOpenAI(api_key=config.OPENAI_API_KEY)


@router.post("/transcribe")
async def transcribe(audio: UploadFile = File(...), user: dict = Depends(get_current_user)):
    if not await credits_mod.charge(user["id"], agents_catalog.COST_VOICE_IN,
                                     "voice_in", {"filename": audio.filename}):
        raise HTTPException(status_code=402, detail="Saldo insuficiente para audio.")
    client = _client()
    raw = await audio.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Audio vacio")
    # OpenAI espera (filename, fileobj, content_type)
    file_tuple = (audio.filename or "audio.webm", io.BytesIO(raw), audio.content_type or "audio/webm")
    try:
        result = await client.audio.transcriptions.create(
            model="whisper-1",
            file=file_tuple,
            language="es",
        )
    except Exception as e:
        logger.exception(f"Whisper fallo: {e}")
        raise HTTPException(status_code=502, detail=f"Whisper error: {str(e)[:200]}")
    return {"text": getattr(result, "text", "") or "",
            "balance": await credits_mod.get_balance(user["id"])}


class TtsIn(BaseModel):
    text: str
    voice: str = "alloy"  # alloy|echo|fable|onyx|nova|shimmer


@router.post("/tts")
async def text_to_speech(data: TtsIn, user: dict = Depends(get_current_user)):
    text = (data.text or "").strip()[:1500]
    if not text:
        raise HTTPException(status_code=400, detail="Texto vacio")
    if data.voice not in {"alloy", "echo", "fable", "onyx", "nova", "shimmer"}:
        data.voice = "alloy"
    if not await credits_mod.charge(user["id"], agents_catalog.COST_VOICE_OUT,
                                     "voice_out", {"voice": data.voice, "len": len(text)}):
        raise HTTPException(status_code=402, detail="Saldo insuficiente para voz.")
    client = _client()
    try:
        # OpenAI TTS - genera audio mp3
        resp = await client.audio.speech.create(
            model="tts-1",
            voice=data.voice,
            input=text,
            response_format="mp3",
        )
        audio_bytes = resp.content if hasattr(resp, "content") else await resp.aread()
    except Exception as e:
        logger.exception(f"TTS fallo: {e}")
        raise HTTPException(status_code=502, detail=f"TTS error: {str(e)[:200]}")
    return StreamingResponse(
        io.BytesIO(audio_bytes),
        media_type="audio/mpeg",
        headers={"Content-Disposition": 'inline; filename="speech.mp3"',
                 "X-Balance-After": str(await credits_mod.get_balance(user["id"]))},
    )
