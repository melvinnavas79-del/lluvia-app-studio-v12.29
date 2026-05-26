"""
Twilio Voice Agents — llamadas telefónicas PSTN con IA.

Phase 1: TwiML Gather-loop (Twilio STT + Polly TTS + Groq LLM)
  Flujo inbound:
    Twilio → POST /inbound → <Gather speech> → POST /gather → Groq → <Say+Gather> → loop
    Goodbye / max_turns → <Say farewell> + <Hangup>
    3x silencio → fallback → optional <Dial human_handoff_number>

  Flujo outbound:
    POST /outbound → Twilio REST API → mismo flujo inbound

Phase 2 ready: VoiceStreamAdapter (Media Streams WebSocket, barge-in, <500ms latency)

Hooks E4/E9:
  lead_detected, appointment_requested, payment_intent,
  escalation_requested, high_value_lead → e4_leads + e9_events

Protecciones:
  max_turns, max_silence_retries, max_call_duration_seconds, max_tokens_per_turn
  Twilio HMAC-SHA1 signature validation con replay-attack prevention

Colecciones MongoDB:
  voice_calls, voice_agent_configs, voice_workflows, voice_campaigns
"""

import asyncio
import base64
import hashlib
import hmac
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlencode
from xml.sax.saxutils import escape as xml_escape

import requests as http_req
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from auth import get_current_user
from llm_router import get_client, GROQ_API_KEY as _GROQ_KEY
from rate_limit import limiter
import anti_abuse
import observability as obs

logger = logging.getLogger("twilio_voice")
router = APIRouter(prefix="/twilio-voice", tags=["twilio-voice"])

_db_ref: dict = {"db": None}


def set_db(db) -> None:
    _db_ref["db"] = db


def _db():
    db = _db_ref.get("db")
    if db is None:
        raise HTTPException(status_code=503, detail="DB no inicializada")
    return db


# ──────────────────────────────────────────────────────────
# Configuración (leída desde env — sin importar config.py)
# ──────────────────────────────────────────────────────────

import os
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_VOICE_FROM = os.environ.get("TWILIO_VOICE_FROM", "")
TWILIO_VOICE_WEBHOOK_URL = os.environ.get("TWILIO_VOICE_WEBHOOK_URL", "")
TWILIO_VALIDATE_REQUESTS = os.environ.get("TWILIO_VALIDATE_REQUESTS", "true").lower() == "true"

_TWILIO_API_BASE = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}"

# Groq llama-3.1-8b-instant: $0.27 / 1M tokens
_GROQ_COST_PER_TOKEN = 0.00000027

# ──────────────────────────────────────────────────────────
# Defaults de agente de voz
# ──────────────────────────────────────────────────────────

DEFAULT_AGENT: dict = {
    "agent_id": "lluvia-default",
    "tenant_id": "default",
    "name": "Lluvia",
    "greeting": (
        "Hola, soy Lluvia, tu asistente de inteligencia artificial. "
        "¿En qué puedo ayudarte hoy?"
    ),
    "farewell": "Muchas gracias por llamar. ¡Hasta pronto!",
    "silence_fallback_phrase": "Parece que no puedo escucharte bien. ¿Sigues ahí?",
    "human_handoff_phrase": (
        "Voy a transferirte con un agente humano. Un momento por favor."
    ),
    "system_prompt": (
        "Eres Lluvia, una asistente de voz IA profesional y amigable. "
        "Respondes en español de forma clara, natural y concisa. "
        "Máximo 2-3 oraciones por respuesta. Hablas para ser escuchado por teléfono, no leído. "
        "Evita listas, viñetas, markdown o caracteres especiales. "
        "Si no entiendes algo, pide que lo repitan educadamente."
    ),
    "voice": "Polly.Conchita",          # Twilio Polly — incluido sin costo extra
    "language": "es-MX",
    "max_turns": 20,
    "max_call_duration_seconds": 600,   # 10 minutos máximo
    "max_tokens_per_turn": 150,         # respuestas cortas para voz
    "max_silence_retries": 3,
    "human_handoff_number": "",
    "recording_enabled": False,         # opt-in por tenant — no automático
    "recording_disclaimer": "",
    "workflow_id": "",
}

# Frases de despedida para detectar fin de llamada
_GOODBYE_PHRASES = [
    "adiós", "hasta luego", "hasta pronto", "chao", "chau", "bye",
    "gracias adiós", "gracias hasta luego", "nos vemos", "que tengas",
    "goodbye", "hasta mañana",
]

# Intent patterns → hooks E4/E9
_INTENT_PATTERNS: dict[str, list[str]] = {
    "lead_detected": [
        "me interesa", "estoy interesado", "quiero saber más", "cuéntame más",
        "más información", "cómo funciona", "quiero probarlo", "me gustaría",
    ],
    "appointment_requested": [
        "agendar", "cita", "reunión", "llamada", "demo", "demostración",
        "cuándo podemos", "programar", "calendario", "disponibilidad",
    ],
    "payment_intent": [
        "precio", "costo", "cuánto", "pagar", "comprar", "plan", "suscripción",
        "tarjeta", "factura", "contratar", "cuánto vale", "cuánto cuesta",
    ],
    "escalation_requested": [
        "hablar con", "agente humano", "persona real", "supervisor",
        "representante", "alguien real", "quiero un humano",
    ],
    "high_value_lead": [
        "empresa", "corporativo", "multinacional", "equipo grande",
        "muchos usuarios", "enterprise", "licencia empresarial",
        "personalizado", "a medida", "varias sedes",
    ],
}

# Frases directas que disparan escalación
_ESCALATION_TRIGGERS = [
    "hablar con un agente", "hablar con una persona", "necesito un humano",
    "quiero hablar con alguien real", "ponme con un representante",
    "quiero hablar contigo no", "no quiero hablar con un robot",
]


# ──────────────────────────────────────────────────────────
# Phase 2 adapter hook — Media Streams / WebSocket
# ──────────────────────────────────────────────────────────

class VoiceStreamAdapter:
    """
    Phase 2: Twilio Media Streams — audio real-time sobre WebSocket.
    Interfaz definida para extensión futura, no implementada en Phase 1.

    Cuando se active:
      - WebSocket en /api/twilio-voice/stream/{call_sid}
      - Recibe frames μ-law 8kHz desde Twilio
      - STT: Deepgram streaming / AssemblyAI streaming
      - LLM: Groq tokens en streaming con detección de barge-in
      - TTS: ElevenLabs / Google TTS streaming
      - Envía audio μ-law de vuelta por WebSocket (<500ms latencia)
    Features Phase 2: interrupciones naturales, barge-in, latencia ultra-baja
    """
    async def handle_stream(self, websocket, call_sid: str) -> None:
        raise NotImplementedError("Phase 2: Twilio Media Streams no implementado aún")


# ──────────────────────────────────────────────────────────
# TwiML builders (XML manual — sin dependencia del SDK Twilio)
# ──────────────────────────────────────────────────────────

def _gather_url(call_sid: str, tenant_id: str, agent_id: str) -> str:
    base = TWILIO_VOICE_WEBHOOK_URL.rstrip("/")
    qs = urlencode({"call_sid": call_sid, "tenant_id": tenant_id, "agent_id": agent_id})
    return f"{base}/api/twilio-voice/gather?{qs}"


def _twiml_gather(action_url: str, say_text: str, voice: str, language: str,
                  timeout: int = 5) -> str:
    t = xml_escape(say_text)
    a = xml_escape(action_url)
    v = xml_escape(voice)
    lang = xml_escape(language)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<Response>\n'
        f'  <Gather input="speech" action="{a}" method="POST"\n'
        f'          speechTimeout="auto" language="{lang}" enhanced="true"\n'
        f'          timeout="{timeout}">\n'
        f'    <Say voice="{v}" language="{lang}">{t}</Say>\n'
        f'  </Gather>\n'
        f'  <Redirect method="POST">{a}&amp;silence=1</Redirect>\n'
        '</Response>'
    )


def _twiml_say_hangup(text: str, voice: str, language: str) -> str:
    t = xml_escape(text)
    v = xml_escape(voice)
    lang = xml_escape(language)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<Response>\n'
        f'  <Say voice="{v}" language="{lang}">{t}</Say>\n'
        '  <Hangup/>\n</Response>'
    )


def _twiml_transfer(say_text: str, voice: str, language: str, transfer_to: str) -> str:
    t = xml_escape(say_text)
    v = xml_escape(voice)
    lang = xml_escape(language)
    num = xml_escape(transfer_to)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<Response>\n'
        f'  <Say voice="{v}" language="{lang}">{t}</Say>\n'
        f'  <Dial>{num}</Dial>\n'
        '</Response>'
    )


def _prepend_disclaimer(disclaimer: str, twiml: str, voice: str, language: str) -> str:
    """Inserta <Say> de disclaimer + <Record/> antes del contenido principal."""
    d = xml_escape(disclaimer)
    v = xml_escape(voice)
    lang = xml_escape(language)
    inner = (twiml
             .replace('<?xml version="1.0" encoding="UTF-8"?>\n<Response>\n', '')
             .rstrip('\n').rstrip('</Response>'))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<Response>\n'
        f'  <Say voice="{v}" language="{lang}">{d}</Say>\n'
        f'  <Record/>\n'
        + inner
        + '\n</Response>'
    )


# ──────────────────────────────────────────────────────────
# Twilio request signature validation (HMAC-SHA1)
# ──────────────────────────────────────────────────────────

def _validate_twilio_signature(request: Request, params: dict) -> bool:
    """
    Valida firma Twilio para prevenir spoofing.
    Algoritmo: HMAC-SHA1(auth_token, URL + sorted_params)
    """
    if not TWILIO_VALIDATE_REQUESTS or not TWILIO_AUTH_TOKEN:
        return True

    sig = request.headers.get("X-Twilio-Signature", "")
    if not sig:
        logger.warning("Twilio webhook sin X-Twilio-Signature")
        return False

    # URL canónica: detrás de un reverse proxy el scheme puede llegar como http.
    # Usamos TWILIO_VOICE_WEBHOOK_URL como base si está configurado, porque
    # Twilio firma contra la URL pública (https), no contra la interna del container.
    url = str(request.url)
    if TWILIO_VOICE_WEBHOOK_URL:
        path = request.url.path
        query = f"?{request.url.query}" if request.url.query else ""
        url = TWILIO_VOICE_WEBHOOK_URL.rstrip("/") + path + query
    canonical = url + "".join(k + (params.get(k) or "") for k in sorted(params))
    mac = hmac.new(TWILIO_AUTH_TOKEN.encode(), canonical.encode(), hashlib.sha1)
    expected = base64.b64encode(mac.digest()).decode()

    valid = hmac.compare_digest(expected, sig)
    if not valid:
        logger.warning(f"Twilio signature mismatch para {url}")
    return valid


# ──────────────────────────────────────────────────────────
# Intent detection → hooks E4 + E9
# ──────────────────────────────────────────────────────────

def _detect_intents(text: str) -> list[str]:
    lower = text.lower()
    return [intent for intent, patterns in _INTENT_PATTERNS.items()
            if any(p in lower for p in patterns)]


def _is_goodbye(text: str) -> bool:
    lower = text.lower().strip()
    return any(g in lower for g in _GOODBYE_PHRASES)


def _is_escalation(text: str) -> bool:
    lower = text.lower()
    return any(t in lower for t in _ESCALATION_TRIGGERS)


async def _emit_event(db, call_sid: str, tenant_id: str, event_type: str, data: dict):
    """Emite evento a e9_events y a e4_leads si es evento de lead/venta."""
    ts = datetime.now(timezone.utc).isoformat()
    doc = {
        "source": "voice", "call_sid": call_sid, "tenant_id": tenant_id,
        "event_type": event_type, "data": data, "ts": ts,
    }
    try:
        await db.e9_events.insert_one({**doc})
    except Exception:
        pass

    lead_events = {"lead_detected", "appointment_requested", "payment_intent", "high_value_lead"}
    if event_type in lead_events:
        try:
            await db.e4_leads.update_one(
                {"call_sid": call_sid},
                {"$push": {"voice_events": {"event_type": event_type, "data": data, "ts": ts}},
                 "$setOnInsert": {
                     "call_sid": call_sid, "tenant_id": tenant_id,
                     "source": "voice", "created_at": ts,
                 }},
                upsert=True,
            )
        except Exception:
            pass


# ──────────────────────────────────────────────────────────
# DB helpers
# ──────────────────────────────────────────────────────────

async def _get_call(db, call_sid: str) -> Optional[dict]:
    return await db.voice_calls.find_one({"call_sid": call_sid}, {"_id": 0})


async def _get_agent_config(db, agent_id: str, tenant_id: str = "default") -> dict:
    doc = await db.voice_agent_configs.find_one(
        {"agent_id": agent_id, "tenant_id": tenant_id}, {"_id": 0}
    )
    return {**DEFAULT_AGENT, **doc} if doc else DEFAULT_AGENT.copy()


async def _get_workflow(db, workflow_id: str) -> Optional[dict]:
    if not workflow_id:
        return None
    return await db.voice_workflows.find_one({"workflow_id": workflow_id}, {"_id": 0})


async def _append_turn(db, call_sid: str, user_text: str, assistant_text: str,
                       tokens: int, cost_usd: float, latency_ms: int):
    ts = datetime.now(timezone.utc).isoformat()
    await db.voice_calls.update_one(
        {"call_sid": call_sid},
        {"$push": {"turns": {
            "user": user_text, "assistant": assistant_text,
            "tokens": tokens, "cost_usd": cost_usd,
            "latency_ms": latency_ms, "ts": ts,
        }},
         "$inc": {"total_tokens": tokens, "ai_cost_usd": cost_usd},
         "$set": {"updated_at": ts}},
    )


async def _close_call(db, call_sid: str, status: str, transferred_to: str = ""):
    now = datetime.now(timezone.utc).isoformat()
    update: dict = {"status": status, "ended_at": now}
    if transferred_to:
        update["transferred_to"] = transferred_to
    await db.voice_calls.update_one({"call_sid": call_sid}, {"$set": update})
    anti_abuse.clear_gather_tracker(call_sid)  # libera memoria del flood tracker


# ──────────────────────────────────────────────────────────
# LLM voice reply — Groq optimizado para velocidad
# ──────────────────────────────────────────────────────────

async def _llm_voice_reply(agent: dict, workflow: Optional[dict],
                           turns: list[dict], user_text: str) -> tuple[str, int]:
    """
    Genera respuesta LLM optimizada para voz: corta, natural, sin markdown.
    Usa Groq llama-3.1-8b-instant (objetivo <500ms).
    Retorna (texto_respuesta, tokens_usados).
    """
    client, model = get_client("low")
    max_tokens = agent.get("max_tokens_per_turn", 150)

    system = agent["system_prompt"]
    if workflow:
        system += (
            f"\n\nWorkflow activo: {workflow.get('name', '')}. "
            f"{workflow.get('instructions', '')}"
        )
    system += (
        "\n\nREGLAS DE VOZ: Máximo 2-3 oraciones. Habla de forma natural para ser "
        "escuchado por teléfono. Cero listas, cero markdown, cero asteriscos, cero "
        "caracteres especiales. Si mencionas números, escríbelos en palabras."
    )

    messages = [{"role": "system", "content": system}]
    for turn in turns[-8:]:
        if turn.get("user"):
            messages.append({"role": "user", "content": turn["user"]})
        if turn.get("assistant"):
            messages.append({"role": "assistant", "content": turn["assistant"]})
    messages.append({"role": "user", "content": user_text})

    primary_provider = "groq" if _GROQ_KEY else "openai"
    t0 = time.monotonic()
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.4,
        )
        lat = int((time.monotonic() - t0) * 1000)
        obs.record_provider_call(primary_provider, lat, True)
        text = (resp.choices[0].message.content or "").strip()
        tokens = resp.usage.total_tokens if resp.usage else 0
        return text, tokens
    except Exception as e:
        lat = int((time.monotonic() - t0) * 1000)
        obs.record_provider_call(primary_provider, lat, False)
        logger.warning(f"LLM voice {primary_provider} error ({e}), intentando fallback OpenAI")
        t1 = time.monotonic()
        try:
            fallback_client, fallback_model = get_client("high")
            resp2 = await fallback_client.chat.completions.create(
                model=fallback_model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=0.4,
            )
            lat2 = int((time.monotonic() - t1) * 1000)
            obs.record_provider_call("openai", lat2, True)
            text2 = (resp2.choices[0].message.content or "").strip()
            tokens2 = resp2.usage.total_tokens if resp2.usage else 0
            return text2, tokens2
        except Exception as e2:
            lat2 = int((time.monotonic() - t1) * 1000)
            obs.record_provider_call("openai", lat2, False)
            logger.error(f"LLM voice fallback también falló: {e2}")
            return "Disculpa, hubo un problema técnico. ¿Podrías repetir eso?", 0


# ──────────────────────────────────────────────────────────
# Twilio REST — llamadas salientes
# ──────────────────────────────────────────────────────────

_MAX_CALL_DURATION_SECONDS = int(os.environ.get("VOICE_MAX_CALL_DURATION", "600"))  # 10 min default


async def _twilio_create_call(to: str, from_: str, url: str, status_callback: str) -> dict:
    payload = {
        "To": to, "From": from_, "Url": url,
        "StatusCallback": status_callback, "StatusCallbackMethod": "POST",
        "TimeLimit": str(_MAX_CALL_DURATION_SECONDS),  # previene llamadas infinitas y costo runaway
    }
    t0 = time.monotonic()
    try:
        resp = await asyncio.to_thread(
            http_req.post,
            f"{_TWILIO_API_BASE}/Calls.json",
            data=payload,
            auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
            timeout=10,
        )
        lat = int((time.monotonic() - t0) * 1000)
        obs.record_provider_call("twilio", lat, resp.status_code < 400)
        return resp.json()
    except Exception as e:
        lat = int((time.monotonic() - t0) * 1000)
        obs.record_provider_call("twilio", lat, False)
        raise HTTPException(status_code=502, detail=f"Twilio API error: {str(e)[:200]}")


# ══════════════════════════════════════════════════════════
# ENDPOINTS WEBHOOKS TWILIO (sin autenticación JWT)
# ══════════════════════════════════════════════════════════

@router.post("/inbound", response_class=PlainTextResponse)
async def inbound_call(request: Request):
    """
    Twilio llama aquí cuando entra una llamada nueva.
    Crea el registro en voice_calls y responde con TwiML de saludo + Gather.
    """
    form = dict(await request.form())

    if not _validate_twilio_signature(request, form):
        raise HTTPException(status_code=403, detail="Twilio signature inválida")

    call_sid = form.get("CallSid", str(uuid.uuid4()))
    caller = form.get("From", "unknown")
    tenant_id = request.query_params.get("tenant_id", "default")
    agent_id = request.query_params.get("agent_id", "lluvia-default")
    is_retry = request.query_params.get("retry", "0") != "0"

    db = _db()
    agent = await _get_agent_config(db, agent_id, tenant_id)
    ts = datetime.now(timezone.utc).isoformat()

    if not is_retry:
        await db.voice_calls.insert_one({
            "call_sid": call_sid,
            "tenant_id": tenant_id,
            "agent_id": agent_id,
            "workflow_id": agent.get("workflow_id", ""),
            "caller": caller,
            "direction": "inbound",
            "status": "active",
            "turns": [],
            "silence_retries": 0,
            "total_tokens": 0,
            "ai_cost_usd": 0.0,
            "started_at": ts,
            "created_at": ts,
        })
        await _emit_event(db, call_sid, tenant_id, "voice_call_started",
                          {"caller": caller, "agent_id": agent_id, "direction": "inbound"})

    gather_url = _gather_url(call_sid, tenant_id, agent_id)
    twiml = _twiml_gather(gather_url, agent["greeting"], agent["voice"], agent["language"])

    if agent.get("recording_enabled") and agent.get("recording_disclaimer"):
        twiml = _prepend_disclaimer(agent["recording_disclaimer"], twiml,
                                    agent["voice"], agent["language"])

    logger.info(f"Inbound call {call_sid} from {caller} → agent {agent_id}")
    return PlainTextResponse(twiml, media_type="application/xml")


@router.post("/gather", response_class=PlainTextResponse)
async def gather_result(request: Request):
    """
    Twilio POST con transcripción de voz.
    Ejecuta turno LLM → responde TwiML.
    """
    t_start = time.monotonic()
    form = dict(await request.form())

    if not _validate_twilio_signature(request, form):
        raise HTTPException(status_code=403, detail="Twilio signature inválida")

    call_sid = request.query_params.get("call_sid") or form.get("CallSid", "")
    tenant_id = request.query_params.get("tenant_id", "default")
    agent_id = request.query_params.get("agent_id", "lluvia-default")
    silence_flag = request.query_params.get("silence", "0") == "1"

    # ── Anti-flood: detecta POST /gather anómalos en la misma llamada ──
    anti_abuse.check_gather_flood(call_sid)

    speech = (form.get("SpeechResult", "") or "").strip()

    db = _db()
    agent = await _get_agent_config(db, agent_id, tenant_id)
    workflow = await _get_workflow(db, agent.get("workflow_id", ""))

    call = await _get_call(db, call_sid)
    if not call:
        ts_now = datetime.now(timezone.utc).isoformat()
        await db.voice_calls.insert_one({
            "call_sid": call_sid, "tenant_id": tenant_id, "agent_id": agent_id,
            "status": "active", "turns": [], "silence_retries": 0,
            "total_tokens": 0, "ai_cost_usd": 0.0,
            "started_at": ts_now, "created_at": ts_now,
        })
        call = {"turns": [], "silence_retries": 0, "total_tokens": 0, "ai_cost_usd": 0.0}

    turns = call.get("turns", [])
    silence_retries = call.get("silence_retries", 0)
    voice = agent["voice"]
    language = agent["language"]
    max_turns = agent.get("max_turns", 20)
    max_silence = agent.get("max_silence_retries", 3)
    handoff_number = agent.get("human_handoff_number", "")
    gather_url = _gather_url(call_sid, tenant_id, agent_id)

    # ── Protección de costo: max_turns ──────────────────────
    if len(turns) >= max_turns:
        await _close_call(db, call_sid, "max_turns")
        await _emit_event(db, call_sid, tenant_id, "voice_call_completed",
                          {"reason": "max_turns", "turns": len(turns)})
        return PlainTextResponse(
            _twiml_say_hangup(agent.get("farewell", DEFAULT_AGENT["farewell"]), voice, language),
            media_type="application/xml",
        )

    # ── Silencio / sin transcripción ────────────────────────
    if not speech or silence_flag:
        new_retries = silence_retries + 1
        await db.voice_calls.update_one({"call_sid": call_sid},
                                        {"$set": {"silence_retries": new_retries}})

        if new_retries >= max_silence:
            # Máximo silencio → transferir o colgar
            if handoff_number:
                phrase = agent.get("human_handoff_phrase", DEFAULT_AGENT["human_handoff_phrase"])
                await _close_call(db, call_sid, "transferred", handoff_number)
                await _emit_event(db, call_sid, tenant_id, "voice_transfer",
                                  {"to": handoff_number, "reason": "max_silence"})
                return PlainTextResponse(
                    _twiml_transfer(phrase, voice, language, handoff_number),
                    media_type="application/xml",
                )
            else:
                await _close_call(db, call_sid, "silence_timeout")
                await _emit_event(db, call_sid, tenant_id, "voice_call_completed",
                                  {"reason": "silence_timeout"})
                return PlainTextResponse(
                    _twiml_say_hangup("Parece que perdimos la conexión. ¡Hasta pronto!", voice, language),
                    media_type="application/xml",
                )

        fallback = agent.get("silence_fallback_phrase", DEFAULT_AGENT["silence_fallback_phrase"])
        return PlainTextResponse(
            _twiml_gather(gather_url, fallback, voice, language),
            media_type="application/xml",
        )

    # ── Reset contador de silencio ──────────────────────────
    if silence_retries > 0:
        await db.voice_calls.update_one({"call_sid": call_sid},
                                        {"$set": {"silence_retries": 0}})

    # ── Despedida ───────────────────────────────────────────
    if _is_goodbye(speech):
        farewell = agent.get("farewell", DEFAULT_AGENT["farewell"])
        await _append_turn(db, call_sid, speech, farewell, 0, 0.0, 0)
        await _close_call(db, call_sid, "completed")
        await _emit_event(db, call_sid, tenant_id, "voice_call_completed",
                          {"reason": "goodbye", "turns": len(turns) + 1})
        return PlainTextResponse(
            _twiml_say_hangup(farewell, voice, language),
            media_type="application/xml",
        )

    # ── Escalación a humano ─────────────────────────────────
    if handoff_number and _is_escalation(speech):
        phrase = agent.get("human_handoff_phrase", DEFAULT_AGENT["human_handoff_phrase"])
        await _close_call(db, call_sid, "transferred", handoff_number)
        await _emit_event(db, call_sid, tenant_id, "escalation_requested",
                          {"text": speech, "to": handoff_number})
        return PlainTextResponse(
            _twiml_transfer(phrase, voice, language, handoff_number),
            media_type="application/xml",
        )

    # ── Turno LLM ───────────────────────────────────────────
    reply, tokens = await _llm_voice_reply(agent, workflow, turns, speech)
    latency_ms = int((time.monotonic() - t_start) * 1000)
    turn_cost = tokens * _GROQ_COST_PER_TOKEN

    await _append_turn(db, call_sid, speech, reply, tokens, turn_cost, latency_ms)

    # ── Hooks E4/E9 — intent detection ──────────────────────
    intents = set(_detect_intents(speech) + _detect_intents(reply))
    for intent in intents:
        await _emit_event(db, call_sid, tenant_id, intent,
                          {"user_text": speech, "turn": len(turns) + 1})
    await _emit_event(db, call_sid, tenant_id, "voice_turn", {
        "turn": len(turns) + 1,
        "tokens": tokens,
        "latency_ms": latency_ms,
        "cost_usd": round(turn_cost, 6),
    })

    logger.info(f"Voice turn {call_sid}: {tokens}tok, {latency_ms}ms, intents={intents}")
    return PlainTextResponse(
        _twiml_gather(gather_url, reply, voice, language),
        media_type="application/xml",
    )


@router.post("/status", response_class=PlainTextResponse)
async def call_status_callback(request: Request):
    """Twilio notifica cambios de estado (completed/failed/busy/no-answer)."""
    form = dict(await request.form())
    call_sid = form.get("CallSid", "")
    status = form.get("CallStatus", "")
    duration = int(form.get("CallDuration", 0) or 0)
    recording_url = form.get("RecordingUrl", "")

    db = _db()
    now = datetime.now(timezone.utc).isoformat()
    update: dict = {"ended_at": now, "duration_seconds": duration}
    if status:
        update["status"] = status
    if recording_url:
        update["recording_url"] = recording_url

    await db.voice_calls.update_one({"call_sid": call_sid}, {"$set": update})

    call = await _get_call(db, call_sid)
    if call:
        tenant_id = call.get("tenant_id", "default")
        ai_cost = round(call.get("ai_cost_usd", 0.0), 6)
        await _emit_event(db, call_sid, tenant_id, "voice_call_completed", {
            "status": status,
            "duration_seconds": duration,
            "turns": len(call.get("turns", [])),
            "total_tokens": call.get("total_tokens", 0),
            "ai_cost_usd": ai_cost,
        })
        # Registra costo real en contadores de tenant (alimenta budget guardrails + E9)
        if status in ("completed", "in-progress"):
            await anti_abuse.record_call_cost(db, tenant_id, ai_cost)

    logger.info(f"Call {call_sid} status={status} duration={duration}s")
    return PlainTextResponse('<?xml version="1.0"?><Response/>', media_type="application/xml")


# ══════════════════════════════════════════════════════════
# ENDPOINTS AUTENTICADOS
# ══════════════════════════════════════════════════════════

# ── Llamadas salientes ────────────────────────────────────

class OutboundIn(BaseModel):
    to: str
    agent_id: str = "lluvia-default"
    tenant_id: str = "default"
    campaign_id: str = ""
    call_batch_id: str = ""


@router.post("/outbound")
@limiter.limit("10/minute")
async def outbound_call(request: Request, data: OutboundIn,
                        user: dict = Depends(get_current_user)):
    """Inicia una llamada saliente vía Twilio REST API."""
    if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_VOICE_FROM]):
        raise HTTPException(status_code=503, detail="Twilio Voice no configurado (SID/AUTH/FROM)")
    if not TWILIO_VOICE_WEBHOOK_URL:
        raise HTTPException(status_code=503, detail="TWILIO_VOICE_WEBHOOK_URL no configurado")

    db = _db()
    # ── Anti-abuse: cuota diaria + budget + cooldown por número ──
    await anti_abuse.check_daily_budget(db, data.tenant_id)
    await anti_abuse.check_monthly_budget(db, data.tenant_id)
    await anti_abuse.check_and_increment_daily_calls(db, data.tenant_id)
    await anti_abuse.check_outbound_cooldown(db, data.to, data.tenant_id)

    base = TWILIO_VOICE_WEBHOOK_URL.rstrip("/")
    qs = urlencode({
        "tenant_id": data.tenant_id,
        "agent_id": data.agent_id,
        "campaign_id": data.campaign_id,
        "call_batch_id": data.call_batch_id,
    })
    inbound_url = f"{base}/api/twilio-voice/inbound?{qs}"
    status_url = f"{base}/api/twilio-voice/status"

    result = await _twilio_create_call(data.to, TWILIO_VOICE_FROM, inbound_url, status_url)
    real_sid = result.get("sid", f"mock-{uuid.uuid4().hex[:8]}")

    ts = datetime.now(timezone.utc).isoformat()
    await db.voice_calls.insert_one({
        "call_sid": real_sid,
        "tenant_id": data.tenant_id,
        "agent_id": data.agent_id,
        "called": data.to,
        "caller": TWILIO_VOICE_FROM,
        "direction": "outbound",
        "campaign_id": data.campaign_id,
        "call_batch_id": data.call_batch_id,
        "status": "initiated",
        "turns": [],
        "silence_retries": 0,
        "total_tokens": 0,
        "ai_cost_usd": 0.0,
        "initiated_by": user.get("id", ""),
        "started_at": ts,
        "created_at": ts,
    })
    await _emit_event(db, real_sid, data.tenant_id, "voice_call_started", {
        "direction": "outbound",
        "to": data.to,
        "campaign_id": data.campaign_id,
    })
    return {"call_sid": real_sid, "status": result.get("status", "initiated"), "to": data.to}


# ── Historial de llamadas ─────────────────────────────────

@router.get("/calls")
async def list_calls(tenant_id: str = "default", limit: int = 50, skip: int = 0,
                     user: dict = Depends(get_current_user)):
    db = _db()
    cursor = db.voice_calls.find(
        {"tenant_id": tenant_id}, {"_id": 0}
    ).sort("created_at", -1).skip(skip).limit(limit)
    calls = await cursor.to_list(length=limit)
    total = await db.voice_calls.count_documents({"tenant_id": tenant_id})
    return {"calls": calls, "total": total, "skip": skip, "limit": limit}


@router.get("/calls/{call_sid}")
async def get_call_detail(call_sid: str, user: dict = Depends(get_current_user)):
    db = _db()
    call = await _get_call(db, call_sid)
    if not call:
        raise HTTPException(status_code=404, detail="Llamada no encontrada")
    return call


# ── Configuración de agentes de voz ──────────────────────

class AgentConfigIn(BaseModel):
    agent_id: str
    tenant_id: str = "default"
    name: str
    greeting: str = DEFAULT_AGENT["greeting"]
    farewell: str = DEFAULT_AGENT["farewell"]
    system_prompt: str = DEFAULT_AGENT["system_prompt"]
    voice: str = "Polly.Conchita"
    language: str = "es-MX"
    max_turns: int = 20
    max_call_duration_seconds: int = 600
    max_tokens_per_turn: int = 150
    max_silence_retries: int = 3
    silence_fallback_phrase: str = DEFAULT_AGENT["silence_fallback_phrase"]
    human_handoff_number: str = ""
    human_handoff_phrase: str = DEFAULT_AGENT["human_handoff_phrase"]
    recording_enabled: bool = False
    recording_disclaimer: str = ""
    workflow_id: str = ""


@router.post("/agents")
@limiter.limit("30/minute")
async def create_agent_config(request: Request, data: AgentConfigIn,
                               user: dict = Depends(get_current_user)):
    db = _db()
    ts = datetime.now(timezone.utc).isoformat()
    doc = data.model_dump()
    doc.update({"created_at": ts, "updated_at": ts, "created_by": user.get("id", "")})
    await db.voice_agent_configs.update_one(
        {"agent_id": data.agent_id, "tenant_id": data.tenant_id},
        {"$set": doc},
        upsert=True,
    )
    return {"ok": True, "agent_id": data.agent_id, "tenant_id": data.tenant_id}


@router.get("/agents")
async def list_agent_configs(tenant_id: str = "default",
                              user: dict = Depends(get_current_user)):
    db = _db()
    cursor = db.voice_agent_configs.find({"tenant_id": tenant_id}, {"_id": 0})
    configs = await cursor.to_list(length=100)
    return {"agents": configs, "default_config": DEFAULT_AGENT}


# ── Workflows (persona separada de lógica de negocio) ─────

class WorkflowIn(BaseModel):
    workflow_id: str = ""
    tenant_id: str = "default"
    name: str
    description: str = ""
    type: str = "soporte"   # ventas|soporte|cobranza|onboarding|booking
    instructions: str = ""
    success_events: list[str] = []
    escalation_keywords: list[str] = []
    conversion_keywords: list[str] = []


@router.post("/workflows")
@limiter.limit("30/minute")
async def create_workflow(request: Request, data: WorkflowIn,
                          user: dict = Depends(get_current_user)):
    db = _db()
    ts = datetime.now(timezone.utc).isoformat()
    wid = data.workflow_id or f"wf-{uuid.uuid4().hex[:8]}"
    doc = data.model_dump()
    doc.update({"workflow_id": wid, "created_at": ts, "updated_at": ts})
    await db.voice_workflows.update_one(
        {"workflow_id": wid, "tenant_id": data.tenant_id},
        {"$set": doc},
        upsert=True,
    )
    return {"ok": True, "workflow_id": wid}


@router.get("/workflows")
async def list_workflows(tenant_id: str = "default",
                         user: dict = Depends(get_current_user)):
    db = _db()
    cursor = db.voice_workflows.find({"tenant_id": tenant_id}, {"_id": 0})
    wfs = await cursor.to_list(length=100)
    workflow_types = ["ventas", "soporte", "cobranza", "onboarding", "booking"]
    return {"workflows": wfs, "available_types": workflow_types}


# ── Campañas salientes ────────────────────────────────────

class CampaignIn(BaseModel):
    campaign_id: str = ""
    tenant_id: str = "default"
    name: str
    agent_id: str = "lluvia-default"
    workflow_id: str = ""
    numbers: list[str]
    scheduled_at: str = ""   # ISO datetime — vacío = inmediato
    retry_policy: dict = {"max_retries": 2, "retry_after_minutes": 30}


@router.post("/campaigns")
@limiter.limit("10/minute")
async def create_campaign(request: Request, data: CampaignIn,
                          user: dict = Depends(get_current_user)):
    anti_abuse.check_campaign_size(data.numbers)  # 400 si supera CAMPAIGN_MAX_NUMBERS
    db = _db()
    ts = datetime.now(timezone.utc).isoformat()
    cid = data.campaign_id or f"camp-{uuid.uuid4().hex[:8]}"
    batch_id = f"batch-{uuid.uuid4().hex[:8]}"
    doc = data.model_dump()
    doc.update({
        "campaign_id": cid,
        "call_batch_id": batch_id,
        "status": "draft",
        "created_at": ts,
        "updated_at": ts,
        "created_by": user.get("id", ""),
        "stats": {
            "total": len(data.numbers),
            "called": 0, "answered": 0, "converted": 0,
        },
    })
    await db.voice_campaigns.insert_one(doc)
    return {
        "ok": True,
        "campaign_id": cid,
        "call_batch_id": batch_id,
        "total_numbers": len(data.numbers),
        "status": "draft",
    }


@router.get("/campaigns")
async def list_campaigns(tenant_id: str = "default",
                         user: dict = Depends(get_current_user)):
    db = _db()
    cursor = db.voice_campaigns.find(
        {"tenant_id": tenant_id}, {"_id": 0}
    ).sort("created_at", -1)
    campaigns = await cursor.to_list(length=50)
    return {"campaigns": campaigns}


# ── Métricas E9 ───────────────────────────────────────────

@router.get("/metrics")
async def voice_metrics(tenant_id: str = "default", days: int = 7,
                        user: dict = Depends(get_current_user)):
    from datetime import timedelta
    db = _db()
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    calls = await db.voice_calls.find(
        {"tenant_id": tenant_id, "created_at": {"$gte": since}}, {"_id": 0}
    ).to_list(length=10000)

    total = len(calls)
    completed = sum(1 for c in calls if c.get("status") == "completed")
    transferred = sum(1 for c in calls if c.get("status") == "transferred")
    total_dur = sum(c.get("duration_seconds", 0) for c in calls)
    total_tokens = sum(c.get("total_tokens", 0) for c in calls)
    total_cost = sum(c.get("ai_cost_usd", 0.0) for c in calls)
    all_turns = [t for c in calls for t in c.get("turns", [])]
    latencies = [t["latency_ms"] for t in all_turns if t.get("latency_ms")]

    return {
        "period_days": days,
        "tenant_id": tenant_id,
        "total_calls": total,
        "completed_calls": completed,
        "transferred_to_human": transferred,
        "inbound_calls": sum(1 for c in calls if c.get("direction") == "inbound"),
        "outbound_calls": sum(1 for c in calls if c.get("direction") == "outbound"),
        "avg_call_duration_seconds": round(total_dur / max(1, total), 1),
        "avg_response_latency_ms": round(sum(latencies) / max(1, len(latencies))),
        "total_turns": len(all_turns),
        "total_tokens": total_tokens,
        "total_ai_cost_usd": round(total_cost, 4),
        "avg_ai_cost_per_call_usd": round(total_cost / max(1, total), 4),
        "successful_conversations": completed,
    }


# ── Quotas y budget por tenant ───────────────────────────

@router.get("/quotas/{tenant_id}")
async def tenant_quota_summary(tenant_id: str,
                               user: dict = Depends(get_current_user)):
    """Retorna cuota diaria, costo acumulado y límites configurados para el tenant."""
    db = _db()
    return await anti_abuse.get_tenant_quota_summary(db, tenant_id)


# ── Estado del sistema ────────────────────────────────────

@router.get("/status")
async def voice_system_status():
    return {
        "phase": 1,
        "engine": "twiml_gather",
        "phase2_engine": "VoiceStreamAdapter (media_streams — not yet implemented)",
        "twilio_configured": bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN),
        "voice_from_configured": bool(TWILIO_VOICE_FROM),
        "webhook_url_configured": bool(TWILIO_VOICE_WEBHOOK_URL),
        "signature_validation": TWILIO_VALIDATE_REQUESTS,
        "llm": "groq/llama-3.1-8b-instant",
        "stt": "Twilio enhanced speech recognition",
        "tts": "Twilio Polly",
        "default_voice": DEFAULT_AGENT["voice"],
        "default_language": DEFAULT_AGENT["language"],
        "collections": [
            "voice_calls", "voice_agent_configs",
            "voice_workflows", "voice_campaigns",
        ],
        "e4_hooks": list(_INTENT_PATTERNS.keys()),
        "e9_events": [
            "voice_call_started", "voice_turn", "voice_call_completed",
            "voice_transfer", "escalation_requested",
        ],
    }


# ── Tool functions para E1 console.py ─────────────────────

async def tool_voice_call_start(to: str, agent_id: str = "lluvia-default",
                                tenant_id: str = "default",
                                campaign_id: str = "") -> dict:
    """E1 tool: inicia llamada saliente."""
    if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_VOICE_FROM, TWILIO_VOICE_WEBHOOK_URL]):
        return {"error": "Twilio Voice no completamente configurado"}
    base = TWILIO_VOICE_WEBHOOK_URL.rstrip("/")
    qs = urlencode({"tenant_id": tenant_id, "agent_id": agent_id, "campaign_id": campaign_id})
    url = f"{base}/api/twilio-voice/inbound?{qs}"
    status_url = f"{base}/api/twilio-voice/status"
    result = await _twilio_create_call(to, TWILIO_VOICE_FROM, url, status_url)
    return {"call_sid": result.get("sid"), "status": result.get("status"), "to": to}


async def tool_voice_metrics(tenant_id: str = "default", days: int = 7) -> dict:
    """E1 tool: métricas de Voice Agents."""
    from datetime import timedelta
    db = _db_ref.get("db")
    if not db:
        return {"error": "DB no disponible"}
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    calls = await db.voice_calls.find(
        {"tenant_id": tenant_id, "created_at": {"$gte": since}}, {"_id": 0}
    ).to_list(length=10000)
    total = len(calls)
    total_cost = sum(c.get("ai_cost_usd", 0.0) for c in calls)
    return {
        "total_calls": total,
        "completed": sum(1 for c in calls if c.get("status") == "completed"),
        "ai_cost_usd": round(total_cost, 4),
        "period_days": days,
    }


async def tool_voice_agent_config(agent_id: str, tenant_id: str = "default",
                                   **kwargs) -> dict:
    """E1 tool: configura un agente de voz."""
    db = _db_ref.get("db")
    if not db:
        return {"error": "DB no disponible"}
    ts = datetime.now(timezone.utc).isoformat()
    doc = {"agent_id": agent_id, "tenant_id": tenant_id, **kwargs,
           "updated_at": ts}
    await db.voice_agent_configs.update_one(
        {"agent_id": agent_id, "tenant_id": tenant_id},
        {"$set": doc, "$setOnInsert": {"created_at": ts}},
        upsert=True,
    )
    return {"ok": True, "agent_id": agent_id}


async def tool_voice_campaign_create(name: str, numbers: list,
                                      agent_id: str = "lluvia-default",
                                      tenant_id: str = "default",
                                      workflow_id: str = "") -> dict:
    """E1 tool: crea campaña de llamadas salientes."""
    db = _db_ref.get("db")
    if not db:
        return {"error": "DB no disponible"}
    ts = datetime.now(timezone.utc).isoformat()
    cid = f"camp-{uuid.uuid4().hex[:8]}"
    await db.voice_campaigns.insert_one({
        "campaign_id": cid, "name": name, "agent_id": agent_id,
        "tenant_id": tenant_id, "workflow_id": workflow_id,
        "numbers": numbers, "status": "draft",
        "stats": {"total": len(numbers), "called": 0, "answered": 0, "converted": 0},
        "created_at": ts,
    })
    return {"campaign_id": cid, "total_numbers": len(numbers), "status": "draft"}
