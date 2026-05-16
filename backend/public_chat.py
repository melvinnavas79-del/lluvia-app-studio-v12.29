"""
Public Chat (v11.1) — Landing publica 24/7

Permite que cualquier visitante (sin login) hable con los agentes
publicados. Los oros se descuentan de la cuenta del owner (Melvin),
no del visitante.

Endpoints:
  GET  /api/public/agents              -> lista de agentes publicados
  GET  /api/public/branding            -> branding del sitio (publico)
  POST /api/public/chat                -> envia mensaje y recibe respuesta

Seguridad:
  - Rate limit: 20 msgs/min/IP (anti-abuso)
  - Limite de longitud: 1000 chars por mensaje
  - El owner decide que agentes son publicos (flag is_public)
  - Sin acceso a tools (solo conversacion)
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from openai import AsyncOpenAI

import config
import agents_catalog
import credits as credits_mod
from rate_limit import limiter

logger = logging.getLogger("public_chat")
router = APIRouter(prefix="/public", tags=["public_chat"])

_db_ref: dict = {"db": None}


def set_db(db) -> None:
    _db_ref["db"] = db


async def _get_owner_id() -> Optional[str]:
    """El owner = primer admin del sistema (Melvin)."""
    db = _db_ref["db"]
    if db is None:
        return None
    u = await db.users.find_one({"role": "admin"}, {"_id": 0, "id": 1})
    return u["id"] if u else None


async def _resolve_agent(agent_id: str) -> Optional[dict]:
    ag = agents_catalog.get_agent(agent_id)
    if ag:
        return {**ag, "is_custom": False}
    db = _db_ref["db"]
    if db is None:
        return None
    custom = await db.custom_agents.find_one({"id": agent_id}, {"_id": 0})
    return custom


@router.get("/agents")
async def list_public_agents():
    """Lista agentes marcados como publicos."""
    db = _db_ref["db"]
    out = []

    # Agentes custom marcados public
    if db is not None:
        async for a in db.custom_agents.find({"is_public": True},
                                              {"_id": 0, "system": 0}):
            out.append({**a, "type": "custom"})

    # Built-in: por defecto incluimos los principales (vendedor, sexologo,
    # psicologo, contador, app_builder) excepto los privilegiados
    # (devops, arquitecto que requieren admin)
    public_builtin_ids = {"vendedor", "sexologo", "psicologo",
                           "contador", "app_builder"}
    for aid, a in agents_catalog.AGENTS.items():
        if aid in public_builtin_ids:
            out.append({
                "id": a["id"], "name": a["name"],
                "emoji": a["emoji"], "color": a["color"],
                "tagline": a["tagline"], "voice": a["voice"],
                "type": "builtin",
            })
    return {"agents": out}


@router.get("/branding")
async def public_branding():
    """Branding del sitio (visible a visitantes)."""
    db = _db_ref["db"]
    if db is None:
        return {}
    doc = await db.branding.find_one({"_id": "main"}, {"_id": 0})
    return doc or {}


class PublicChatIn(BaseModel):
    agent_id: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=1000)
    session_id: Optional[str] = Field(default=None, max_length=80)
    visitor_name: Optional[str] = Field(default=None, max_length=60)


@router.post("/chat")
@limiter.limit("20/minute")
async def public_chat(request: Request, data: PublicChatIn):
    """Endpoint principal: visitante chatea con un agente.
    Los oros los paga el owner del sitio."""
    if not config.OPENAI_API_KEY:
        raise HTTPException(status_code=503, detail="Chat no disponible (LLM no configurado)")

    db = _db_ref["db"]
    if db is None:
        raise HTTPException(status_code=503, detail="DB no inicializada")

    agent = await _resolve_agent(data.agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agente no encontrado")

    # Si es custom y no es publico, rechazar
    if agent.get("is_custom") and not agent.get("is_public"):
        raise HTTPException(status_code=403, detail="Agente no publico")

    owner_id = await _get_owner_id()
    if not owner_id:
        raise HTTPException(status_code=503, detail="Sin owner configurado")

    # Cargar o crear sesion publica
    sid = data.session_id or str(uuid.uuid4())
    sess = await db.public_chats.find_one({"id": sid}, {"_id": 0})
    if not sess:
        sess = {
            "id": sid, "agent_id": data.agent_id,
            "visitor_ip": request.client.host if request.client else "?",
            "visitor_name": data.visitor_name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "messages": [],
        }
        await db.public_chats.insert_one(dict(sess))
        sess.pop("_id", None)

    # Cobrar al owner (no al visitante)
    cost = agents_catalog.COST_CHAT_MESSAGE
    if not await credits_mod.charge(owner_id, cost, "public_chat",
                                     {"agent_id": data.agent_id, "sid": sid}):
        raise HTTPException(status_code=402,
                             detail="El servicio se encuentra temporalmente sin saldo. Vuelve luego.")

    # Historial reciente (ultimos 16 mensajes)
    history = sess.get("messages", [])[-16:]

    # Contexto temporal para que el LLM no invente fechas
    now_utc = datetime.now(timezone.utc)
    weekdays_es = ["lunes", "martes", "miercoles", "jueves",
                    "viernes", "sabado", "domingo"]
    date_ctx = (f"\n\n[FECHA ACTUAL] {now_utc.strftime('%Y-%m-%d %H:%M')} UTC "
                f"({weekdays_es[now_utc.weekday()]}). "
                f"Calcula 'hoy/manana' desde este valor.")

    public_directive = (
        "\n\n[MODO PUBLICO] Estas atendiendo a un VISITANTE de la web "
        f"({sess.get('visitor_name') or 'sin nombre'}). Se profesional, "
        "responde corto (2-4 frases), pregunta su nombre si todavia no lo "
        "tienes, y al final invitalo a dejar telefono o email para que el "
        "dueno se contacte. NO uses tools, NO inventes datos, NO prometas "
        "agendamientos reales (solo informativos)."
    )

    messages = [
        {"role": "system", "content": (agent.get("system") or "") + date_ctx + public_directive},
    ]
    for m in history:
        if m["role"] in ("user", "assistant") and m.get("content"):
            messages.append({"role": m["role"], "content": m["content"]})
    messages.append({"role": "user", "content": data.text})

    # Llamada al LLM
    client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
    try:
        resp = await client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=messages,
            temperature=0.5,
            max_tokens=500,
        )
        assistant_text = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        logger.exception(f"LLM fallo en public_chat: {e}")
        raise HTTPException(status_code=502, detail=f"Error del agente: {str(e)[:120]}")

    # Persistir turno
    now = datetime.now(timezone.utc).isoformat()
    user_msg = {"id": str(uuid.uuid4()), "role": "user",
                "content": data.text, "ts": now}
    asst_msg = {"id": str(uuid.uuid4()), "role": "assistant",
                "content": assistant_text, "ts": now,
                "agent_id": data.agent_id}
    await db.public_chats.update_one(
        {"id": sid},
        {"$push": {"messages": {"$each": [user_msg, asst_msg]}},
         "$set": {"updated_at": now,
                  "last_preview": assistant_text[:160]}},
    )

    return {
        "session_id": sid,
        "agent": {"id": agent["id"], "name": agent.get("name"),
                  "emoji": agent.get("emoji"), "color": agent.get("color")},
        "response": assistant_text,
    }
