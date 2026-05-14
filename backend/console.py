"""
========================================
CHAT MULTI-AGENTE CON TOOLS Y CREDITOS (v9)
========================================
"""

import json
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from openai import AsyncOpenAI

import config
import credits as credits_mod
import agents_catalog
import appointments as appt_mod
from auth import get_current_user
from actions import github as gh
from actions import server as srv
from actions import client_provisioning
from security import is_command_safe

logger = logging.getLogger("chat_console")
router = APIRouter(prefix="/console", tags=["console"])

_db_ref: dict = {"db": None}


def set_db(db) -> None:
    _db_ref["db"] = db


async def _get_agent_any(agent_id: str) -> Optional[dict]:
    """Busca primero en built-in, luego en custom_agents de Mongo."""
    ag = agents_catalog.get_agent(agent_id)
    if ag:
        return ag
    db = _db_ref["db"]
    custom = await db.custom_agents.find_one({"id": agent_id}, {"_id": 0})
    return custom


# ============================================================
# OPENAI TOOLS (mismas que el bot Telegram)
# ============================================================
OPENAI_TOOLS = [
    {"type": "function", "function": {
        "name": "shell_run",
        "description": "Ejecuta un comando shell SEGURO en el servidor. Para RAM/disco/uptime/ps.",
        "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]},
    }},
    {"type": "function", "function": {
        "name": "github_list_repos",
        "description": "Lista los repos del usuario en GitHub.",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "github_list_files",
        "description": "Lista archivos de un repo en una ruta.",
        "parameters": {"type": "object", "properties": {
            "repo": {"type": "string"}, "path": {"type": "string", "default": ""},
        }, "required": ["repo"]},
    }},
    {"type": "function", "function": {
        "name": "github_read_file",
        "description": "Lee un archivo de texto de un repo.",
        "parameters": {"type": "object", "properties": {
            "repo": {"type": "string"}, "file_path": {"type": "string"},
        }, "required": ["repo", "file_path"]},
    }},
    {"type": "function", "function": {
        "name": "github_search_code",
        "description": "Busca un texto en un repo.",
        "parameters": {"type": "object", "properties": {
            "repo": {"type": "string"}, "query": {"type": "string"},
        }, "required": ["repo", "query"]},
    }},
    {"type": "function", "function": {
        "name": "provision_client_quick",
        "description": "Despliega un cliente nuevo con stack Lluvia. Para 'instala/crea X para Y'.",
        "parameters": {"type": "object", "properties": {
            "display_name": {"type": "string"},
            "admin_email": {"type": "string"},
        }, "required": ["display_name"]},
    }},
    {"type": "function", "function": {
        "name": "create_agent",
        "description": "Crea un agente custom NUEVO y lo registra en la plataforma. Aparece al instante en Boss Console.",
        "parameters": {"type": "object", "properties": {
            "id": {"type": "string", "description": "snake_case, 2-40 chars, ej: peluqueria_asistente"},
            "name": {"type": "string", "description": "Nombre visible, ej: Asistente Peluqueria"},
            "emoji": {"type": "string", "description": "1 emoji"},
            "color": {"type": "string", "description": "hex #rrggbb"},
            "voice": {"type": "string", "enum": ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]},
            "tagline": {"type": "string", "description": "max 120 chars"},
            "system": {"type": "string", "description": "prompt completo del agente, 200-2000 chars"},
            "tools": {"type": "array", "items": {"type": "string"}, "default": []},
        }, "required": ["id", "name", "emoji", "color", "voice", "tagline", "system"]},
    }},
    {"type": "function", "function": {
        "name": "update_agent",
        "description": "Modifica un agente custom existente (no built-in).",
        "parameters": {"type": "object", "properties": {
            "id": {"type": "string"},
            "name": {"type": "string"}, "emoji": {"type": "string"},
            "color": {"type": "string"}, "voice": {"type": "string"},
            "tagline": {"type": "string"}, "system": {"type": "string"},
        }, "required": ["id"]},
    }},
    {"type": "function", "function": {
        "name": "delete_agent",
        "description": "Borra un agente custom (no built-in) por id.",
        "parameters": {"type": "object", "properties": {
            "id": {"type": "string"},
        }, "required": ["id"]},
    }},
    {"type": "function", "function": {
        "name": "list_agents",
        "description": "Lista todos los agentes built-in y custom disponibles.",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "book_appointment",
        "description": "Reserva una cita real en la base de datos. Bloquea solapamiento. Devuelve confirmacion.",
        "parameters": {"type": "object", "properties": {
            "client_name": {"type": "string", "description": "Nombre del cliente"},
            "client_phone": {"type": "string", "description": "Telefono (opcional)"},
            "client_email": {"type": "string", "description": "Email (opcional)"},
            "service": {"type": "string", "description": "Servicio reservado"},
            "date": {"type": "string", "description": "Fecha YYYY-MM-DD"},
            "time": {"type": "string", "description": "Hora HH:MM 24h"},
            "notes": {"type": "string", "description": "Observaciones (opcional)"},
        }, "required": ["client_name", "service", "date", "time"]},
    }},
    {"type": "function", "function": {
        "name": "check_availability",
        "description": "Consulta disponibilidad real para una fecha. Devuelve horas ocupadas y libres.",
        "parameters": {"type": "object", "properties": {
            "date": {"type": "string", "description": "YYYY-MM-DD"},
        }, "required": ["date"]},
    }},
    {"type": "function", "function": {
        "name": "list_appointments",
        "description": "Lista citas reservadas del agente actual. Filtrable por client_email o client_phone.",
        "parameters": {"type": "object", "properties": {
            "client_email": {"type": "string"},
            "client_phone": {"type": "string"},
        }},
    }},
    {"type": "function", "function": {
        "name": "cancel_appointment",
        "description": "Cancela una cita por id.",
        "parameters": {"type": "object", "properties": {
            "id": {"type": "string"},
        }, "required": ["id"]},
    }},
    {"type": "function", "function": {
        "name": "paypal_invoice_card",
        "description": "Genera una Rich Card visual con boton PayPal para cobrarle al cliente. Devuelve un objeto card que se renderiza inline en el chat.",
        "parameters": {"type": "object", "properties": {
            "amount_usd": {"type": "number", "description": "Monto en USD"},
            "description": {"type": "string", "description": "Concepto del cobro"},
            "client_name": {"type": "string", "description": "Cliente que recibira el cobro"},
        }, "required": ["amount_usd", "description"]},
    }},
    {"type": "function", "function": {
        "name": "service_card",
        "description": "Renderiza una tarjeta visual de servicio/producto en el chat. Util para mostrar opciones al cliente.",
        "parameters": {"type": "object", "properties": {
            "title": {"type": "string"},
            "description": {"type": "string"},
            "price_usd": {"type": "number"},
            "image_url": {"type": "string"},
            "cta_label": {"type": "string", "description": "Texto del boton, ej: 'Reservar'"},
            "cta_action": {"type": "string", "description": "Accion sugerida, ej: 'book' | 'info'"},
        }, "required": ["title"]},
    }},
]


def _filter_tools(allowed: list) -> list:
    """Filtra OPENAI_TOOLS a las allowed para este agente."""
    return [t for t in OPENAI_TOOLS if t["function"]["name"] in allowed]


VOICES = {"alloy", "echo", "fable", "onyx", "nova", "shimmer"}


async def _tool_create_agent(args: dict, user_id: str) -> dict:
    """Crea un agente custom invocado por el Arquitecto."""
    import re
    db = _db_ref["db"]
    aid = re.sub(r"[^a-z0-9_-]", "", (args.get("id") or "").lower())[:40]
    if not aid or len(aid) < 2:
        return {"error": "id invalido (snake_case minimo 2 chars)"}
    if aid in agents_catalog.AGENTS:
        return {"error": f"id '{aid}' colisiona con built-in. Usa otro."}
    if await db.custom_agents.find_one({"id": aid}, {"_id": 0}):
        return {"error": f"ya existe agente con id '{aid}'"}
    voice = args.get("voice", "alloy")
    if voice not in VOICES:
        voice = "alloy"
    valid_tools = set(agents_catalog.TOOL_NAMES.keys())
    tools = [t for t in (args.get("tools") or []) if t in valid_tools]
    name = (args.get("name") or "").strip()[:40]
    emoji = (args.get("emoji") or "🤖").strip()[:4]
    color = (args.get("color") or "#5fb4ff").strip()[:20]
    tagline = (args.get("tagline") or "").strip()[:120]
    system = (args.get("system") or "").strip()[:2000]
    if not name or len(system) < 20:
        return {"error": "name y system son obligatorios (system min 20 chars)"}
    doc = {
        "id": aid, "name": name, "emoji": emoji, "color": color,
        "voice": voice, "tagline": tagline, "system": system,
        "tools": tools,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": user_id, "is_custom": True,
    }
    await db.custom_agents.insert_one(doc)
    doc.pop("_id", None)
    return {"created": True, "agent": doc}


async def _tool_update_agent(args: dict) -> dict:
    db = _db_ref["db"]
    aid = (args.get("id") or "").strip()
    if not aid:
        return {"error": "id requerido"}
    if aid in agents_catalog.AGENTS:
        return {"error": "no se puede modificar un agente built-in"}
    updates = {k: v for k, v in args.items()
               if k in {"name", "emoji", "color", "voice", "tagline", "system"} and v}
    if "voice" in updates and updates["voice"] not in VOICES:
        updates["voice"] = "alloy"
    if not updates:
        return {"error": "nada para actualizar"}
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    res = await db.custom_agents.update_one({"id": aid}, {"$set": updates})
    if res.matched_count == 0:
        return {"error": f"agente '{aid}' no encontrado"}
    return {"updated": True, "id": aid, "fields": list(updates.keys())}


async def _tool_delete_agent(args: dict) -> dict:
    db = _db_ref["db"]
    aid = (args.get("id") or "").strip()
    if not aid:
        return {"error": "id requerido"}
    if aid in agents_catalog.AGENTS:
        return {"error": "no se puede borrar un agente built-in"}
    res = await db.custom_agents.delete_one({"id": aid})
    return {"deleted": res.deleted_count > 0, "id": aid}


async def _tool_list_agents() -> dict:
    builtins = [{"id": a["id"], "name": a["name"], "type": "built-in"}
                for a in agents_catalog.AGENTS.values()]
    db = _db_ref["db"]
    customs = []
    async for a in db.custom_agents.find({}, {"_id": 0, "id": 1, "name": 1}):
        customs.append({"id": a["id"], "name": a["name"], "type": "custom"})
    return {"builtin": builtins, "custom": customs, "total": len(builtins) + len(customs)}


async def _tool_paypal_card(args: dict, user_id: str) -> dict:
    """Genera una orden real de PayPal y devuelve metadatos de Rich Card.
    El frontend renderiza <PaymentCard /> usando este resultado."""
    import os
    import requests
    amount = float(args.get("amount_usd") or 0)
    if amount <= 0 or amount > 10000:
        return {"error": "amount_usd debe estar entre 0.01 y 10000"}
    description = (args.get("description") or "Pago").strip()[:120]
    client_name = (args.get("client_name") or "").strip()[:80]

    cid = os.environ.get("PAYPAL_CLIENT_ID", "").strip()
    secret = os.environ.get("PAYPAL_SECRET", "").strip()
    mode = os.environ.get("PAYPAL_MODE", "live").lower()
    base = "https://api-m.sandbox.paypal.com" if mode == "sandbox" else "https://api-m.paypal.com"
    if not cid or not secret:
        return {"error": "PayPal no configurado"}

    # Obtener token
    try:
        tk = requests.post(f"{base}/v1/oauth2/token",
                            data={"grant_type": "client_credentials"},
                            auth=(cid, secret), timeout=15)
        if tk.status_code != 200:
            return {"error": f"PayPal auth fallo: {tk.status_code}"}
        access_token = tk.json()["access_token"]
    except Exception as e:
        return {"error": f"PayPal red: {str(e)[:120]}"}

    # Crear orden
    payload = {
        "intent": "CAPTURE",
        "purchase_units": [{
            "reference_id": f"card-{user_id[:8]}",
            "description": description[:120],
            "amount": {"currency_code": "USD", "value": f"{amount:.2f}"},
        }],
        "application_context": {
            "brand_name": "Lluvia App Studio",
            "shipping_preference": "NO_SHIPPING",
            "user_action": "PAY_NOW",
        },
    }
    try:
        r = requests.post(f"{base}/v2/checkout/orders",
                          headers={"Authorization": f"Bearer {access_token}",
                                   "Content-Type": "application/json"},
                          json=payload, timeout=20)
        if r.status_code not in (200, 201):
            return {"error": f"PayPal create-order: {r.status_code} {r.text[:200]}"}
        j = r.json()
        approve = next((lk["href"] for lk in j.get("links", []) if lk["rel"] == "approve"), None)
    except Exception as e:
        return {"error": f"PayPal exception: {str(e)[:120]}"}

    # Persistir
    await _db_ref["db"].paypal_orders.insert_one({
        "order_id": j["id"], "user_id": user_id, "pack": "custom_card",
        "amount_usd": f"{amount:.2f}", "description": description,
        "client_name": client_name,
        "status": "CREATED", "approve_url": approve,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    return {
        "card_type": "payment",
        "order_id": j["id"],
        "amount_usd": f"{amount:.2f}",
        "description": description,
        "client_name": client_name,
        "approve_url": approve,
        "brand": "Lluvia App Studio",
    }


def _tool_service_card(args: dict) -> dict:
    """Devuelve un objeto card con datos del servicio para renderizar inline."""
    return {
        "card_type": "service",
        "title": (args.get("title") or "").strip()[:120],
        "description": (args.get("description") or "").strip()[:400],
        "price_usd": args.get("price_usd"),
        "image_url": (args.get("image_url") or "").strip()[:500],
        "cta_label": (args.get("cta_label") or "Reservar").strip()[:40],
        "cta_action": (args.get("cta_action") or "info").strip()[:20],
    }


async def _exec_tool(name: str, args: dict, user_id: str, is_admin: bool) -> tuple[str, int]:
    """Ejecuta una tool. Devuelve (resultado_json, costo_oros)."""
    cost = agents_catalog.TOOL_NAMES.get(name, 1)
    try:
        if name == "shell_run":
            if not is_admin:
                return json.dumps({"error": "shell requiere admin"}), 0
            cmd = args.get("command", "")
            safe, reason = is_command_safe(cmd)
            if not safe:
                return json.dumps({"error": f"Comando bloqueado: {reason}"}), 0
            data = {"command": cmd, "output": srv.run_command(cmd)}
        elif name == "github_list_repos":
            data = gh.tool_list_repos_short()
        elif name == "github_list_files":
            data = gh.tool_list_files(args.get("repo", ""), args.get("path", ""))
        elif name == "github_read_file":
            data = gh.tool_read_file(args.get("repo", ""), args.get("file_path", ""))
        elif name == "github_search_code":
            data = gh.tool_search_code(args.get("repo", ""), args.get("query", ""))
        elif name == "provision_client_quick":
            if not is_admin:
                return json.dumps({"error": "provision requiere admin"}), 0
            output = await client_provisioning.quick_provision(
                display_name=args.get("display_name", ""),
                admin_email=args.get("admin_email", ""),
            )
            data = {"result": output}
        elif name == "create_agent":
            if not is_admin:
                return json.dumps({"error": "create_agent requiere admin"}), 0
            data = await _tool_create_agent(args, user_id)
        elif name == "update_agent":
            if not is_admin:
                return json.dumps({"error": "update_agent requiere admin"}), 0
            data = await _tool_update_agent(args)
        elif name == "delete_agent":
            if not is_admin:
                return json.dumps({"error": "delete_agent requiere admin"}), 0
            data = await _tool_delete_agent(args)
        elif name == "list_agents":
            data = await _tool_list_agents()
        elif name == "book_appointment":
            agent_id = (args.get("_agent_id") or "").strip() or "default"
            data = await appt_mod.tool_book(user_id, agent_id, args)
        elif name == "check_availability":
            agent_id = (args.get("_agent_id") or "").strip() or "default"
            data = await appt_mod.tool_check_availability(user_id, agent_id, args)
        elif name == "list_appointments":
            agent_id = (args.get("_agent_id") or "").strip() or "default"
            data = await appt_mod.tool_list_appointments(user_id, agent_id, args)
        elif name == "cancel_appointment":
            agent_id = (args.get("_agent_id") or "").strip() or "default"
            data = await appt_mod.tool_cancel_appointment(user_id, agent_id, args)
        elif name == "paypal_invoice_card":
            data = await _tool_paypal_card(args, user_id)
        elif name == "service_card":
            data = _tool_service_card(args)
        else:
            return json.dumps({"error": f"Tool desconocida: {name}"}), 0
        return json.dumps(data, ensure_ascii=False)[:30000], cost
    except Exception as e:
        return json.dumps({"error": str(e)}), 0


# ============================================================
# MODELOS
# ============================================================
class SessionCreateIn(BaseModel):
    agent_id: str
    title: Optional[str] = None


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


# ============================================================
# ENDPOINTS
# ============================================================
@router.get("/agents")
async def list_agents(_=Depends(get_current_user)):
    builtins = agents_catalog.list_agents()
    db = _db_ref["db"]
    customs = []
    async for a in db.custom_agents.find({}, {"_id": 0}):
        customs.append({
            "id": a["id"], "name": a["name"], "emoji": a["emoji"],
            "color": a["color"], "voice": a.get("voice", "alloy"),
            "tagline": a.get("tagline", ""), "tools": a.get("tools", []),
            "is_custom": True,
        })
    return {"agents": builtins + customs}


@router.get("/credits/me")
async def my_credits(user: dict = Depends(get_current_user)):
    balance = await credits_mod.get_balance(user["id"])
    return {"user_id": user["id"], "balance": balance}


@router.get("/credits/history")
async def my_credit_history(user: dict = Depends(get_current_user)):
    return {"history": await credits_mod.history(user["id"])}


class TopupIn(BaseModel):
    user_id: str
    amount: int = Field(gt=0, le=1_000_000)
    reason: Optional[str] = "admin_topup"


@router.post("/credits/topup")
async def admin_topup(data: TopupIn, user: dict = Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="solo admin")
    new_balance = await credits_mod.topup(data.user_id, data.amount, data.reason or "admin_topup")
    return {"ok": True, "new_balance": new_balance}


@router.get("/sessions")
async def list_sessions(user: dict = Depends(get_current_user)):
    db = _db_ref["db"]
    cur = db.chat_sessions.find(
        {"user_id": user["id"]}, {"_id": 0, "messages": 0}
    ).sort("updated_at", -1).limit(100)
    return {"sessions": [s async for s in cur]}


@router.post("/sessions")
async def create_session(data: SessionCreateIn, user: dict = Depends(get_current_user)):
    agent = await _get_agent_any(data.agent_id)
    if not agent:
        raise HTTPException(status_code=400, detail=f"Agente desconocido: {data.agent_id}")
    sid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": sid,
        "user_id": user["id"],
        "agent_id": data.agent_id,
        "title": data.title or f"{agent.get('emoji','💬')} {agent['name']} - nuevo hilo",
        "created_at": now,
        "updated_at": now,
        "messages": [],
    }
    db = _db_ref["db"]
    await db.chat_sessions.insert_one(doc)
    doc.pop("_id", None)
    doc.pop("messages", None)
    return doc


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, user: dict = Depends(get_current_user)):
    db = _db_ref["db"]
    doc = await db.chat_sessions.find_one(
        {"id": session_id, "user_id": user["id"]}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Sesion no encontrada")
    return doc


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, user: dict = Depends(get_current_user)):
    db = _db_ref["db"]
    res = await db.chat_sessions.delete_one({"id": session_id, "user_id": user["id"]})
    return {"deleted": res.deleted_count}


@router.post("/sessions/{session_id}/messages")
async def send_message(
    session_id: str,
    data: MessageIn,
    user: dict = Depends(get_current_user),
):
    db = _db_ref["db"]
    sess = await db.chat_sessions.find_one({"id": session_id, "user_id": user["id"]}, {"_id": 0})
    if not sess:
        raise HTTPException(status_code=404, detail="Sesion no encontrada")

    agent = await _get_agent_any(sess["agent_id"])
    if not agent:
        raise HTTPException(status_code=400, detail="Agente invalido en sesion")

    # 1. Cobrar coste base del mensaje
    if not await credits_mod.charge(user["id"], agents_catalog.COST_CHAT_MESSAGE,
                                     "chat_message", {"session_id": session_id}):
        raise HTTPException(status_code=402, detail="Saldo de oros insuficiente. Recarga.")

    # 2. Construir mensajes para OpenAI
    # Inyectamos fecha actual del servidor para que el LLM no use su knowledge cutoff
    now_utc = datetime.now(timezone.utc)
    weekdays_es = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
    date_context = (
        f"\n\n[CONTEXTO TEMPORAL OBLIGATORIO]\n"
        f"Fecha y hora ACTUAL del servidor: {now_utc.strftime('%Y-%m-%d %H:%M')} UTC "
        f"({weekdays_es[now_utc.weekday()]}).\n"
        f"Cuando el cliente dice 'hoy', 'manana', 'el viernes', etc., calcula la fecha "
        f"a partir de este valor. NUNCA uses fechas del 2023, 2024 ni 2025 a menos que "
        f"el cliente las mencione explicitamente. Si el cliente no da fecha clara, "
        f"PREGUNTASELA, no la inventes."
    )
    system = (agent.get("system") or "") + date_context
    history = sess.get("messages", [])[-20:]
    messages = [{"role": "system", "content": system}]
    for m in history:
        if m["role"] in ("user", "assistant") and m.get("content"):
            messages.append({"role": m["role"], "content": m["content"]})
    messages.append({"role": "user", "content": data.text})

    is_admin = user.get("role") == "admin"
    agent_tools = agent.get("tools") or []
    tools = _filter_tools(agent_tools) if (is_admin and agent_tools) else None
    tool_calls_made = []
    extra_cost = 0

    if not config.OPENAI_API_KEY:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY no configurada en backend")

    client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)

    # 3. Loop de tool calling (max 5 vueltas)
    final_text = ""
    for _ in range(5):
        try:
            resp = await client.chat.completions.create(
                model=config.LLM_MODEL,
                messages=messages,
                tools=tools,
                tool_choice="auto" if tools else None,
                temperature=0.3,
                max_tokens=600,
            )
        except Exception as e:
            logger.exception(f"OpenAI fallo: {e}")
            raise HTTPException(status_code=502, detail=f"OpenAI error: {str(e)[:200]}")

        msg = resp.choices[0].message
        if not msg.tool_calls:
            final_text = msg.content or ""
            break

        # Tool calls
        messages.append({
            "role": "assistant",
            "content": msg.content,
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls
            ],
        })
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}
            # Inyectar agent_id para tools que lo necesitan (appointments)
            args["_agent_id"] = agent["id"]
            result, cost = await _exec_tool(tc.function.name, args, user["id"], is_admin)
            # cobrar el coste de la tool (si falla, abortamos)
            if cost > 0:
                charged = await credits_mod.charge(user["id"], cost,
                                                    f"tool:{tc.function.name}",
                                                    {"session_id": session_id})
                if not charged:
                    result = json.dumps({"error": "saldo insuficiente para esta tool"})
                else:
                    extra_cost += cost
            tool_calls_made.append({"name": tc.function.name, "args": args, "result_preview": result[:300]})
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

    if not final_text:
        final_text = "No pude finalizar la respuesta. Reformula la peticion."

    # 4. Persistir mensajes
    now = datetime.now(timezone.utc).isoformat()
    user_msg = {"id": str(uuid.uuid4()), "role": "user", "content": data.text, "ts": now}
    assistant_msg = {
        "id": str(uuid.uuid4()),
        "role": "assistant",
        "content": final_text,
        "ts": now,
        "agent_id": agent["id"],
        "tool_calls": tool_calls_made,
        "cost_oros": agents_catalog.COST_CHAT_MESSAGE + extra_cost,
    }
    await db.chat_sessions.update_one(
        {"id": session_id},
        {
            "$push": {"messages": {"$each": [user_msg, assistant_msg]}},
            "$set": {"updated_at": now, "last_message_preview": final_text[:160]},
        },
    )

    new_balance = await credits_mod.get_balance(user["id"])
    return {
        "user_message": user_msg,
        "assistant_message": assistant_msg,
        "cost_oros": agents_catalog.COST_CHAT_MESSAGE + extra_cost,
        "balance": new_balance,
    }
