"""
Call Center Mode (v10) — loop voz continuo.

Flujo por turno:
  1. Cliente envia audio (webm/opus) + agent_id (o session_id)
  2. Whisper transcribe -> texto del usuario
  3. Agente responde via OpenAI con su system prompt
  4. TTS genera audio -> devolvemos mp3 base64 al cliente
  5. Cliente reproduce y vuelve a grabar (loop continuo)

Persistimos cada turno en chat_sessions para historial.

Pricing por turno:
  - Whisper: 10 oros/min (estimado)
  - Chat: 1 oro
  - TTS: 2 oros / 100 chars
Total tipico: 5-15 oros por turno.
"""

import io
import base64
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Request

import config
import llm_router
import agents_catalog
import credits as credits_mod
from auth import get_current_user
from rate_limit import limiter

logger = logging.getLogger("call_center")
router = APIRouter(prefix="/voice/call-center", tags=["call-center"])

_db_ref: dict = {"db": None}


def set_db(db) -> None:
    _db_ref["db"] = db


def _client():
    if not llm_router.llm_available():
        raise HTTPException(status_code=503, detail="Motor IA no configurado")
    return llm_router.get_client("low")


async def _resolve_agent(agent_id: str) -> dict:
    ag = agents_catalog.get_agent(agent_id)
    if ag:
        return ag
    db = _db_ref.get("db")
    if db is None:
        raise HTTPException(status_code=400, detail=f"Agente desconocido: {agent_id}")
    custom = await db.custom_agents.find_one({"id": agent_id}, {"_id": 0})
    if not custom:
        raise HTTPException(status_code=400, detail=f"Agente desconocido: {agent_id}")
    return custom


@router.post("/turn")
@limiter.limit("20/minute")
async def call_turn(
    request: Request,
    audio: UploadFile = File(...),
    agent_id: str = Form(...),
    session_id: str = Form(default=""),
    user: dict = Depends(get_current_user),
):
    """Un turno completo: audio_in -> texto_user -> texto_agente -> audio_out."""
    agent = await _resolve_agent(agent_id)
    client, _cc_model = _client()
    db = _db_ref.get("db")
    if db is None:
        raise HTTPException(status_code=503, detail="DB no inicializada")

    # 1) Cargar o crear sesion
    if session_id:
        sess = await db.chat_sessions.find_one({"id": session_id, "user_id": user["id"]}, {"_id": 0})
        if not sess:
            raise HTTPException(status_code=404, detail="Sesion no encontrada")
    else:
        sid = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        sess = {
            "id": sid, "user_id": user["id"], "agent_id": agent["id"],
            "title": f"📞 Call {agent['name']}",
            "created_at": now, "updated_at": now, "messages": [],
            "mode": "call_center",
        }
        await db.chat_sessions.insert_one(dict(sess))
        sess.pop("_id", None)

    # 2) Leer audio y validar
    raw = await audio.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Audio vacio")
    if len(raw) > 8 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Audio demasiado grande (max 8MB/turno)")

    estimated_sec = max(1, len(raw) // 16000)
    cost_in = max(1, round(estimated_sec * 10 / 60))

    # 3) Cobrar voz-in
    if not await credits_mod.charge(user["id"], cost_in, "call_voice_in",
                                     {"sec": estimated_sec, "agent": agent["id"]}):
        raise HTTPException(status_code=402, detail="Saldo insuficiente para audio entrante")

    # 4) Whisper
    file_tuple = (audio.filename or "turn.webm", io.BytesIO(raw), audio.content_type or "audio/webm")
    try:
        wres = await client.audio.transcriptions.create(
            model="whisper-1", file=file_tuple, language="es",
        )
        user_text = (getattr(wres, "text", "") or "").strip()
    except Exception as e:
        logger.exception(f"Whisper fallo: {e}")
        raise HTTPException(status_code=502, detail=f"Whisper error: {str(e)[:200]}")

    if not user_text:
        return {
            "user_text": "",
            "assistant_text": "No te escuche bien, repite por favor.",
            "audio_base64": None,
            "session_id": sess["id"],
            "cost_oros": cost_in,
            "balance": await credits_mod.get_balance(user["id"]),
        }

    # 5) Cobrar chat
    if not await credits_mod.charge(user["id"], agents_catalog.COST_CHAT_MESSAGE,
                                     "call_chat", {"session_id": sess["id"]}):
        raise HTTPException(status_code=402, detail="Saldo insuficiente para la respuesta")

    # 6) Construir historial (ultimos 10 turnos) + contexto temporal
    now_utc = datetime.now(timezone.utc)
    weekdays_es = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
    date_ctx = (f"\n\n[FECHA ACTUAL] {now_utc.strftime('%Y-%m-%d %H:%M')} UTC "
                f"({weekdays_es[now_utc.weekday()]}). Usa esta fecha como 'hoy'.")
    history = sess.get("messages", [])[-10:]
    messages = [{"role": "system", "content": agent["system"] + date_ctx
                 + "\n\nEstas en modo Call Center: respuestas MAX 2 frases, naturales para leer en voz alta."}]
    for m in history:
        if m["role"] in ("user", "assistant") and m.get("content"):
            messages.append({"role": m["role"], "content": m["content"]})
    messages.append({"role": "user", "content": user_text})

    # 7) GPT
    try:
        resp = await client.chat.completions.create(
            model=_cc_model,
            messages=messages,
            temperature=0.4,
            max_tokens=180,  # respuestas cortas para voz
        )
        assistant_text = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        logger.exception(f"OpenAI fallo: {e}")
        raise HTTPException(status_code=502, detail=f"OpenAI error: {str(e)[:200]}")

    if not assistant_text:
        assistant_text = "Disculpa, no puedo responder eso ahora."

    # 8) TTS
    voice = agent.get("voice", "alloy")
    if voice not in {"alloy", "echo", "fable", "onyx", "nova", "shimmer"}:
        voice = "alloy"
    cost_out = max(1, len(assistant_text) // 100 * 2)
    if not await credits_mod.charge(user["id"], cost_out, "call_voice_out",
                                     {"voice": voice, "len": len(assistant_text)}):
        # Sin saldo para TTS pero ya tenemos texto: devolvemos sin audio
        audio_b64 = None
    else:
        try:
            tts_resp = await client.audio.speech.create(
                model="tts-1", voice=voice, input=assistant_text[:1500],
                response_format="mp3",
            )
            audio_bytes = tts_resp.content if hasattr(tts_resp, "content") else await tts_resp.aread()
            audio_b64 = base64.b64encode(audio_bytes).decode("ascii")
        except Exception as e:
            logger.exception(f"TTS fallo: {e}")
            audio_b64 = None

    # 9) Persistir turno
    now = datetime.now(timezone.utc).isoformat()
    user_msg = {"id": str(uuid.uuid4()), "role": "user",
                "content": user_text, "ts": now, "mode": "voice"}
    asst_msg = {"id": str(uuid.uuid4()), "role": "assistant",
                "content": assistant_text, "ts": now, "agent_id": agent["id"],
                "mode": "voice", "voice": voice}
    await db.chat_sessions.update_one(
        {"id": sess["id"]},
        {"$push": {"messages": {"$each": [user_msg, asst_msg]}},
         "$set": {"updated_at": now, "last_message_preview": assistant_text[:160]}},
    )

    total_cost = cost_in + agents_catalog.COST_CHAT_MESSAGE + cost_out
    return {
        "session_id": sess["id"],
        "user_text": user_text,
        "assistant_text": assistant_text,
        "audio_base64": audio_b64,
        "voice": voice,
        "cost_oros": total_cost,
        "balance": await credits_mod.get_balance(user["id"]),
    }
