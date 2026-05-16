"""
========================================
CHAT MULTI-AGENTE CON TOOLS Y CREDITOS (v9)
========================================
"""

import json
import os
import uuid
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request
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
    {"type": "function", "function": {
        "name": "push_to_my_github",
        "description": (
            "Hace git push del workspace del usuario actual a SU repositorio de GitHub. "
            "Usa el token + repo que el cliente configuro en Mi Cuenta -> Settings. "
            "Devuelve una rich card con el estado del push, URL del repo y steps detallados. "
            "Si el cliente NO configuro su token todavia, devuelve needs_setup=true y el agente "
            "debe pedirle al cliente que lo configure (no es un error, es un setup pendiente). "
            "Despues de un push exitoso, mostrarle al cliente la URL del repo."
        ),
        "parameters": {"type": "object", "properties": {
            "commit_message": {"type": "string", "description": "Mensaje del commit (opcional)"},
            "app_name": {"type": "string", "description": "Nombre de la subcarpeta a pushear. Si se omite, empuja todo el workspace del usuario."},
        }},
    }},
    {"type": "function", "function": {
        "name": "generate_haircut_preview",
        "description": (
            "Genera una imagen visual 'Before/After' mostrando como se veria el cliente "
            "con el nuevo corte/color de cabello. Usa Gemini Nano Banana (img2img) con la "
            "ULTIMA foto que el cliente envio en este chat. Devuelve una rich card visual con "
            "ambas imagenes lado a lado. SOLO llamar despues de haber analizado la foto del "
            "cliente y haber propuesto opciones de corte. La descripcion debe ser detallada y "
            "en INGLES (el modelo entiende mejor): nombre del corte, largo, color, textura, "
            "movimiento. Ejemplo: 'Long bob (lob) cut to collarbone, caramel balayage with "
            "soft face-framing layers, slight wave texture, side-swept fringe'."
        ),
        "parameters": {"type": "object", "properties": {
            "look_description": {
                "type": "string",
                "description": "Descripcion en INGLES del nuevo corte/color, 30-300 chars."
            },
            "look_name": {
                "type": "string",
                "description": "Nombre corto del look en español para mostrar al cliente."
            },
        }, "required": ["look_description", "look_name"]},
    }},
    {"type": "function", "function": {
        "name": "generate_promo_video",
        "description": (
            "Genera un VIDEO real con Sora 2 a partir de un prompt cinematografico. "
            "El video se genera en background (2-5 minutos) y la rich card del frontend "
            "hace polling automatico hasta tenerlo listo. Usar SOLO despues de haber "
            "consensuado con el cliente: a) el prompt detallado en INGLES, b) la duracion "
            "(4, 8 o 12 segundos), c) el formato (vertical 9:16 para TikTok/Reels/Shorts, "
            "horizontal 16:9 para YouTube, o cuadrado). El prompt debe ser visual y "
            "cinematografico (ej: 'A professional barber shop, slow motion close-up of "
            "scissors cutting hair, warm golden light, depth of field, 4k commercial style'). "
            "AVISO al cliente: la generacion cuesta 30-55 oros segun duracion y tarda "
            "varios minutos. Confirmar antes de llamar la tool."
        ),
        "parameters": {"type": "object", "properties": {
            "prompt": {
                "type": "string",
                "description": "Prompt cinematografico en INGLES, 50-1500 chars. Describe vision, accion, luz, camara, estilo."
            },
            "duration": {
                "type": "integer",
                "enum": [4, 8, 12],
                "description": "Duracion en segundos. 4=fast (30 oros), 8=medium (40 oros), 12=long (55 oros)."
            },
            "aspect": {
                "type": "string",
                "enum": ["vertical", "horizontal"],
                "description": "vertical=720x1280 (TikTok/Reels/Shorts/IG), horizontal=1280x720 (YouTube). Sora 2 solo soporta estos dos."
            },
            "quality": {
                "type": "string",
                "enum": ["standard", "pro"],
                "description": "standard=sora-2 (mas rapido), pro=sora-2-pro (mas calidad, mas lento)."
            },
        }, "required": ["prompt", "duration", "aspect"]},
    }},
    {"type": "function", "function": {
        "name": "video_script_card",
        "description": (
            "Genera una rich card visual con el GUION COMPLETO para grabar un video corto de "
            "marketing (TikTok/Reels/Shorts) sobre una funcionalidad de Lluvia App Studio o "
            "del cliente. Devuelve la tarjeta lista para que el equipo grabe y publique. "
            "Llamar SIEMPRE despues de haber preguntado: que feature, que plataforma, que tono "
            "(divertido/serio/inspiracional). Generar copy en ESPAÑOL neutro."
        ),
        "parameters": {"type": "object", "properties": {
            "title": {"type": "string", "description": "Titulo del video (max 80 chars)"},
            "platform": {
                "type": "string",
                "enum": ["tiktok", "reels", "shorts", "todos"],
                "description": "Plataforma destino. 'todos' = formato 9:16 universal."
            },
            "duration_sec": {"type": "integer", "description": "Duracion total en segundos (15-90)"},
            "hook": {"type": "string", "description": "Frase de gancho que aparece en pantalla los primeros 1-3 segundos. Genera curiosidad."},
            "scenes": {
                "type": "array",
                "description": "Lista de 3-7 escenas con timecode, lo que se ve y lo que se dice/escribe en pantalla.",
                "items": {
                    "type": "object",
                    "properties": {
                        "t": {"type": "string", "description": "Timecode tipo '0:00-0:03'"},
                        "visual": {"type": "string", "description": "Que se ve en pantalla (cinematografia)"},
                        "voiceover": {"type": "string", "description": "Texto que dice el creador o sale en pantalla"},
                    },
                    "required": ["t", "visual", "voiceover"],
                },
            },
            "caption": {"type": "string", "description": "Caption/descripcion lista para publicar (max 300 chars)"},
            "hashtags": {
                "type": "array",
                "description": "8-15 hashtags relevantes mezclando nicho + amplio + trending. Incluir el #",
                "items": {"type": "string"},
            },
            "music_suggestion": {"type": "string", "description": "Genero / vibe musical sugerido (no nombres comerciales). Ej: 'beat trap chill con drop al final'"},
            "cta": {"type": "string", "description": "Llamado a la accion final (ej: 'Comenta APP y te paso el link')"},
        }, "required": ["title", "platform", "duration_sec", "hook", "scenes", "caption", "hashtags", "cta"]},
    }},
]


# Tools que SOLO admins pueden invocar (shell, provisioning, agent CRUD,
# github_* del catalogo de la plataforma). El resto de tools son seguras
# para cualquier usuario registrado (book_appointment, push_to_my_github,
# paypal_invoice_card, service_card, etc).
ADMIN_ONLY_TOOLS = {
    "shell_run",
    "provision_client_quick",
    "create_agent",
    "update_agent",
    "delete_agent",
    "github_list_repos",
    "github_list_files",
    "github_read_file",
    "github_search_code",
}


def _filter_tools(allowed: list, is_admin: bool = True) -> list:
    """Filtra OPENAI_TOOLS a las allowed para este agente.
    Si is_admin=False, ademas excluye las tools admin-only."""
    return [
        t for t in OPENAI_TOOLS
        if t["function"]["name"] in allowed
        and (is_admin or t["function"]["name"] not in ADMIN_ONLY_TOOLS)
    ]


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
            if not is_admin:
                return json.dumps({"error": "github_list_repos requiere admin"}), 0
            data = gh.tool_list_repos_short()
        elif name == "github_list_files":
            if not is_admin:
                return json.dumps({"error": "github_list_files requiere admin"}), 0
            data = gh.tool_list_files(args.get("repo", ""), args.get("path", ""))
        elif name == "github_read_file":
            if not is_admin:
                return json.dumps({"error": "github_read_file requiere admin"}), 0
            data = gh.tool_read_file(args.get("repo", ""), args.get("file_path", ""))
        elif name == "github_search_code":
            if not is_admin:
                return json.dumps({"error": "github_search_code requiere admin"}), 0
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
        elif name == "push_to_my_github":
            import user_workspace as uw
            udoc = await _db_ref["db"].users.find_one({"id": user_id}, {"_id": 0})
            if not udoc:
                data = {"error": "Usuario no encontrado"}
            else:
                result = await uw.do_push(
                    udoc,
                    app_name=args.get("app_name"),
                    commit_message=args.get("commit_message"),
                )
                # Wrap como rich card para que el frontend lo renderice
                data = {
                    "card_type": "github_push",
                    "ok": result.get("ok", False),
                    "needs_setup": result.get("needs_setup", False),
                    "message": result.get("message"),
                    "repo": result.get("repo"),
                    "repo_url": result.get("repo_url"),
                    "branch": result.get("branch"),
                    "app_name": result.get("app_name"),
                    "commit_message": result.get("commit_message"),
                    "error": result.get("error"),
                }
        elif name == "generate_haircut_preview":
            import image_gen
            last_img = (args.get("_last_image_url") or "").strip()
            if not last_img:
                data = {
                    "card_type": "before_after",
                    "ok": False,
                    "error": "El cliente no ha enviado todavia una foto. Pedile que adjunte una foto de su rostro de frente con buena luz.",
                }
            else:
                result = await image_gen.generate_haircut_preview(
                    original_image_url=last_img,
                    look_description=args.get("look_description", ""),
                    user_id=user_id,
                )
                # Refund automatico si Nano Banana fallo
                if not result.get("ok") and not is_admin:
                    import credits as credits_mod
                    refund_amt = agents_catalog.TOOL_NAMES.get("generate_haircut_preview", 15)
                    await credits_mod.refund(
                        user_id, refund_amt, "nano_banana_failed",
                        {"error": str(result.get("error"))[:200]},
                    )
                    result["refunded_oros"] = refund_amt
                data = {
                    "card_type": "before_after",
                    "ok": result.get("ok", False),
                    "look_name": args.get("look_name", ""),
                    "look_description": args.get("look_description", ""),
                    "before_url": result.get("before_url"),
                    "after_url": result.get("after_url"),
                    "error": result.get("error"),
                    "refunded_oros": result.get("refunded_oros", 0),
                }
        elif name == "video_script_card":
            data = {
                "card_type": "video_script",
                "title": args.get("title", "").strip(),
                "platform": args.get("platform", "todos"),
                "duration_sec": int(args.get("duration_sec") or 30),
                "hook": args.get("hook", "").strip(),
                "scenes": args.get("scenes") or [],
                "caption": args.get("caption", "").strip(),
                "hashtags": args.get("hashtags") or [],
                "music_suggestion": (args.get("music_suggestion") or "").strip(),
                "cta": (args.get("cta") or "").strip(),
            }
        elif name == "generate_promo_video":
            import video_gen
            duration = int(args.get("duration") or 8)
            if duration not in (4, 8, 12):
                duration = 8
            aspect = (args.get("aspect") or "vertical").lower()
            size = {
                "vertical": "720x1280",
                "horizontal": "1280x720",
                "square": "720x1280",  # Sora 2 no soporta square; usamos vertical
            }.get(aspect, "720x1280")
            quality = "sora-2-pro" if (args.get("quality") or "").lower() == "pro" else "sora-2"
            # Cost dinamico por duracion (sobrescribe el del catalogo)
            cost = video_gen.COST_BY_DURATION.get(duration, 40)
            # Guardamos el cargo dentro del job para que el refund automatico
            # (en caso de fallo de Sora 2) sepa cuanto devolver.
            job = await video_gen.enqueue_video(
                user_id=user_id,
                prompt=args.get("prompt", ""),
                duration=duration,
                size=size,
                model=quality,
                charged_oros=(0 if is_admin else cost),
            )
            data = {
                "card_type": "video_job",
                "job_id": job["id"],
                "status": job["status"],
                "model": job["model"],
                "aspect": aspect,
                "size": job["size"],
                "duration": job["duration"],
                "estimated_wait_sec": job["estimated_wait_sec"],
                "prompt": args.get("prompt", "")[:300],
            }
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
    image_urls: Optional[List[str]] = None  # Lista de URLs de imagenes adjuntas (max 4)


# Constantes para uploads de imagenes
UPLOAD_DIR = Path(__file__).parent / "uploads" / "chat_images"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
MAX_IMAGE_BYTES = 8 * 1024 * 1024  # 8 MB
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/gif", "image/webp"}
COST_VISION_IMAGE = 3  # oros adicionales por imagen analizada con GPT-4o vision


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


@router.get("/video-jobs/{job_id}")
async def get_video_job(job_id: str, user: dict = Depends(get_current_user)):
    """Polling endpoint del frontend para conocer el estado del video Sora 2.
    Devuelve {id, status, video_url?, error?, duration, size, prompt}."""
    import video_gen
    doc = await video_gen.get_job(user["id"], job_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Video job no encontrado")
    return doc


@router.post("/sessions/{session_id}/upload-image")
async def upload_chat_image(
    session_id: str,
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    """Sube una imagen para usarla como adjunto en el siguiente mensaje del chat.
    Devuelve la URL publica (servida bajo /api/uploads/chat_images/...).
    El cobro de oros por vision se hace al enviar el mensaje, no aqui.
    """
    db = _db_ref["db"]
    sess = await db.chat_sessions.find_one(
        {"id": session_id, "user_id": user["id"]}, {"_id": 0, "messages": 0}
    )
    if not sess:
        raise HTTPException(status_code=404, detail="Sesion no encontrada")

    ctype = (file.content_type or "").lower()
    if ctype not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Tipo de imagen no soportado ({ctype}). Usa JPG, PNG, GIF o WebP.",
        )

    # Lectura por chunks para no romper proxies y limitar tamaño
    raw = bytearray()
    while True:
        chunk = await file.read(64 * 1024)
        if not chunk:
            break
        raw.extend(chunk)
        if len(raw) > MAX_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="Imagen demasiado grande (max 8MB)")

    if len(raw) < 16:
        raise HTTPException(status_code=400, detail="Archivo vacio o invalido")

    ext_map = {
        "image/jpeg": ".jpg", "image/jpg": ".jpg",
        "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp",
    }
    ext = ext_map.get(ctype, ".bin")
    fname = f"{user['id']}_{uuid.uuid4().hex}{ext}"
    fpath = UPLOAD_DIR / fname
    fpath.write_bytes(bytes(raw))

    # Construir URL publica accesible desde el frontend (servida con prefijo /api/uploads)
    public_url = f"/api/uploads/chat_images/{fname}"
    return {
        "url": public_url,
        "filename": fname,
        "size": len(raw),
        "content_type": ctype,
    }


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

    # Construir el mensaje del usuario: si hay imagenes adjuntas, usar formato multimodal
    image_urls = (data.image_urls or [])[:4]  # max 4 imagenes por mensaje
    # Resolver URL relativa a absoluta para que OpenAI pueda descargar la imagen
    public_base = (os.environ.get("PUBLIC_BASE_URL") or "").rstrip("/")
    resolved_image_urls: list[str] = []
    for u in image_urls:
        if not u:
            continue
        if u.startswith("http://") or u.startswith("https://"):
            resolved_image_urls.append(u)
        elif u.startswith("/api/uploads/"):
            if public_base:
                resolved_image_urls.append(public_base + u)
            else:
                # Sin PUBLIC_BASE_URL, OpenAI no puede descargar. Convertir a base64.
                try:
                    fname = u.rsplit("/", 1)[-1]
                    fpath = UPLOAD_DIR / fname
                    if fpath.exists():
                        import base64
                        import mimetypes
                        mime = mimetypes.guess_type(str(fpath))[0] or "image/jpeg"
                        b64 = base64.b64encode(fpath.read_bytes()).decode("ascii")
                        resolved_image_urls.append(f"data:{mime};base64,{b64}")
                except Exception:
                    pass

    if resolved_image_urls:
        content_parts = [{"type": "text", "text": data.text}]
        for url in resolved_image_urls:
            content_parts.append({"type": "image_url", "image_url": {"url": url, "detail": "auto"}})
        messages.append({"role": "user", "content": content_parts})
        # Cobrar visión adicional (3 oros por imagen)
        vision_cost = COST_VISION_IMAGE * len(resolved_image_urls)
        if not await credits_mod.charge(user["id"], vision_cost,
                                         "vision_image", {"session_id": session_id, "count": len(resolved_image_urls)}):
            raise HTTPException(status_code=402, detail="Saldo insuficiente para analizar imagenes.")
    else:
        messages.append({"role": "user", "content": data.text})
        vision_cost = 0

    is_admin = user.get("role") == "admin"
    agent_tools = agent.get("tools") or []
    # Ahora todos los usuarios pueden invocar tools "user-safe" (push_to_my_github,
    # book_appointment, paypal_invoice_card, service_card, etc). Los tools admin-only
    # son filtrados aqui y ademas re-validados dentro de _exec_tool.
    tools = _filter_tools(agent_tools, is_admin=is_admin) if agent_tools else None
    if tools is not None and len(tools) == 0:
        tools = None  # OpenAI rechaza tools=[]
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
            # Inyectar la ULTIMA imagen del chat (mensaje actual o historial) para
            # tools de vision/edicion como generate_haircut_preview.
            if "_last_image_url" not in args:
                last_img_url = ""
                if image_urls:
                    last_img_url = image_urls[-1]
                else:
                    for past in reversed(sess.get("messages", [])):
                        if past.get("role") == "user" and past.get("image_urls"):
                            last_img_url = past["image_urls"][-1]
                            break
                args["_last_image_url"] = last_img_url
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
            tool_calls_made.append({
                "name": tc.function.name,
                "args": args,
                # Mantener result completo para tools que generan rich cards (max 6000 chars).
                # Para tools opacas (shell, github), un preview corto es suficiente.
                "result_preview": result[:6000],
            })
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

    if not final_text:
        final_text = "No pude finalizar la respuesta. Reformula la peticion."

    # 4. Persistir mensajes
    now = datetime.now(timezone.utc).isoformat()
    user_msg = {"id": str(uuid.uuid4()), "role": "user", "content": data.text, "ts": now}
    if image_urls:
        user_msg["image_urls"] = image_urls  # guardamos las URLs publicas relativas
    assistant_msg = {
        "id": str(uuid.uuid4()),
        "role": "assistant",
        "content": final_text,
        "ts": now,
        "agent_id": agent["id"],
        "tool_calls": tool_calls_made,
        "cost_oros": agents_catalog.COST_CHAT_MESSAGE + extra_cost + vision_cost,
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
        "cost_oros": agents_catalog.COST_CHAT_MESSAGE + extra_cost + vision_cost,
        "balance": new_balance,
    }
