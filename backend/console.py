"""
========================================
CHAT MULTI-AGENTE CON TOOLS Y CREDITOS
========================================

- Cada sesion tiene un agente asociado
- Cada mensaje cuesta oros (chat + tools que se ejecuten)
- Mensajes y tool_calls quedan persistidos
"""

import json
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from openai import AsyncOpenAI

import config
import credits as credits_mod
import agents_catalog
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
]


def _filter_tools(allowed: list) -> list:
    """Filtra OPENAI_TOOLS a las allowed para este agente."""
    return [t for t in OPENAI_TOOLS if t["function"]["name"] in allowed]


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
    return {"agents": agents_catalog.list_agents()}


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
    agent = agents_catalog.get_agent(data.agent_id)
    if not agent:
        raise HTTPException(status_code=400, detail=f"Agente desconocido: {data.agent_id}")
    sid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": sid,
        "user_id": user["id"],
        "agent_id": data.agent_id,
        "title": data.title or f"{agent['emoji']} {agent['name']} - nuevo hilo",
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

    agent = agents_catalog.get_agent(sess["agent_id"])
    if not agent:
        raise HTTPException(status_code=400, detail="Agente invalido en sesion")

    # 1. Cobrar coste base del mensaje
    if not await credits_mod.charge(user["id"], agents_catalog.COST_CHAT_MESSAGE,
                                     "chat_message", {"session_id": session_id}):
        raise HTTPException(status_code=402, detail="Saldo de oros insuficiente. Recarga.")

    # 2. Construir mensajes para OpenAI
    system = agent["system"]
    history = sess.get("messages", [])[-20:]
    messages = [{"role": "system", "content": system}]
    for m in history:
        if m["role"] in ("user", "assistant") and m.get("content"):
            messages.append({"role": m["role"], "content": m["content"]})
    messages.append({"role": "user", "content": data.text})

    is_admin = user.get("role") == "admin"
    tools = _filter_tools(agent["tools"]) if (is_admin and agent["tools"]) else None
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
