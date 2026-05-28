"""
========================================
CHAT MULTI-AGENTE CON TOOLS Y CREDITOS (v9)
========================================
"""

import json
import os
import uuid
import re
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import config
import credits as credits_mod
import llm_router
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
            "repo": {"type": "string", "description": "(Opcional) owner/repo destino. Si se omite, usa el repo configurado en Settings."},
            "auto_create_repo": {"type": "boolean", "description": "(Opcional) Si true y el repo no existe, lo crea automaticamente."},
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
        "name": "generate_audio_room_app",
        "description": (
            "MATERIALIZA en el workspace del usuario una app completa de Salas de Audio "
            "en vivo (estilo Clubhouse / Twitter Spaces) lista para deployar. Copia un "
            "template pre-construido y testeado (FastAPI + Socket.IO + WebRTC + SQLite, "
            "4 pantallas: Inicio, Tendencias, Sala Activa, Perfil) reemplazando el nombre "
            "y color de la marca. Despues el cliente puede usar push_to_my_github para "
            "subirlo a su propio repo. Costo: 40 oros fijos. Usar SOLO despues de que el "
            "cliente confirmo nombre + color."
        ),
        "parameters": {"type": "object", "properties": {
            "app_name": {"type": "string", "description": "Nombre visible de la app (ej: Talkly, AudioPro). 1-60 chars."},
            "brand_color": {"type": "string", "description": "Color hex (ej: #5B8DEF) o vacio para default azul Lluvia."},
            "app_slug": {"type": "string", "description": "(Opcional) slug-de-carpeta. Si se omite, se deriva del app_name."},
            "deploy_target": {
                "type": "string",
                "enum": ["render", "railway", "heroku", "fly", "vps", "docker", "local"],
                "description": "Donde el cliente va a deployar la app. Determina que README y archivos quedan destacados (render.yaml, railway.toml, Dockerfile, install.sh, etc).",
            },
        }, "required": ["app_name"]},
    }},
    {"type": "function", "function": {
        "name": "generate_tiktok_app",
        "description": (
            "MATERIALIZA en el workspace del usuario una app de VIDEO VERTICAL en vivo "
            "estilo TikTok / Bigo Live / Kuaishou, lista para deployar. Copia un template "
            "pre-construido (FastAPI + SQLite + Vanilla JS + HLS) con 4 pantallas: Feed "
            "vertical con scroll-snap, Descubrir/Trending, Subir video, Perfil. Incluye "
            "likes, comentarios en vivo, follows, regalos virtuales y monetizacion. "
            "Despues el cliente puede usar push_to_my_github para subirlo a su repo. "
            "Usar SOLO despues de que el cliente confirmo nombre + color de marca."
        ),
        "parameters": {"type": "object", "properties": {
            "app_name": {"type": "string", "description": "Nombre visible de la app (ej: VibeShort, LiveStar)."},
            "brand_color": {"type": "string", "description": "Color hex (ej: #FF0050). Default: rosa TikTok."},
            "app_slug": {"type": "string", "description": "(Opcional) slug-de-carpeta."},
            "deploy_target": {
                "type": "string",
                "enum": ["render", "railway", "heroku", "fly", "vps", "docker", "local"],
                "description": "Donde el cliente va a deployar.",
            },
        }, "required": ["app_name"]},
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
    # ============================================================
    # Lluvia Studio tools — operaciones sobre workspace + VPS del usuario
    # ============================================================
    {"type": "function", "function": {
        "name": "list_workspace_files",
        "description": "Lista el arbol de archivos de una app en el workspace del usuario. Usar antes de leer/editar.",
        "parameters": {"type": "object", "properties": {
            "app_slug": {"type": "string", "description": "Slug de la app (ej: 'mi-tiktok')."},
        }, "required": ["app_slug"]},
    }},
    {"type": "function", "function": {
        "name": "read_workspace_file",
        "description": "Lee el contenido de un archivo del workspace. Usar antes de editarlo. Limite 2MB.",
        "parameters": {"type": "object", "properties": {
            "app_slug": {"type": "string"},
            "path": {"type": "string", "description": "Path relativo desde la raiz de la app (ej: 'backend/server.py')."},
        }, "required": ["app_slug", "path"]},
    }},
    {"type": "function", "function": {
        "name": "write_workspace_file",
        "description": (
            "Escribe contenido completo a un archivo del workspace. Para edits chicos usar search_replace_workspace. "
            "Guarda diff automaticamente para rollback. Crea el archivo si no existe."
        ),
        "parameters": {"type": "object", "properties": {
            "app_slug": {"type": "string"},
            "path": {"type": "string"},
            "content": {"type": "string", "description": "Contenido nuevo completo del archivo."},
        }, "required": ["app_slug", "path", "content"]},
    }},
    {"type": "function", "function": {
        "name": "search_replace_workspace",
        "description": (
            "Reemplaza una cadena exacta en un archivo del workspace. old_str debe coincidir EXACTAMENTE "
            "(incluyendo whitespace) y debe ser unico en el archivo (incluir contexto alrededor)."
        ),
        "parameters": {"type": "object", "properties": {
            "app_slug": {"type": "string"},
            "path": {"type": "string"},
            "old_str": {"type": "string"},
            "new_str": {"type": "string"},
        }, "required": ["app_slug", "path", "old_str", "new_str"]},
    }},
    {"type": "function", "function": {
        "name": "list_my_vps",
        "description": "Lista los VPS conectados del usuario actual. Devuelve nombre, host, status.",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "run_vps_command",
        "description": (
            "Ejecuta un comando shell en uno de los VPS conectados del usuario. "
            "Devuelve stdout/stderr/exit_code. Comandos destructivos (rm -rf /, mkfs, shutdown) bloqueados."
        ),
        "parameters": {"type": "object", "properties": {
            "vps_id": {"type": "string", "description": "ID del VPS (de list_my_vps)."},
            "command": {"type": "string", "description": "Comando shell a ejecutar."},
            "timeout_sec": {"type": "integer", "description": "Timeout en segundos (default 60).", "default": 60},
        }, "required": ["vps_id", "command"]},
    }},
    {"type": "function", "function": {
        "name": "deploy_app_to_vps",
        "description": (
            "Despliega una app del workspace a un VPS via SSH. Hace git clone, pip install, "
            "crea systemd service, opcionalmente configura nginx + certbot si se da domain. "
            "Devuelve URL final y deploy_id."
        ),
        "parameters": {"type": "object", "properties": {
            "vps_id": {"type": "string"},
            "app_slug": {"type": "string", "description": "Slug de la app a deployar."},
            "repo_url": {"type": "string", "description": "URL del repo GitHub (https://github.com/user/repo)."},
            "domain": {"type": "string", "description": "(Opcional) Dominio para nginx + HTTPS (ej: tiktok.midominio.com)."},
        }, "required": ["vps_id", "app_slug", "repo_url"]},
    }},
    {"type": "function", "function": {
        "name": "tail_vps_logs",
        "description": "Lee las ultimas N lineas del journal de un systemd service en el VPS. Util para debugging deploys.",
        "parameters": {"type": "object", "properties": {
            "vps_id": {"type": "string"},
            "service": {"type": "string", "description": "Nombre del service (ej: 'lluvia-mi-tiktok')."},
            "lines": {"type": "integer", "default": 100},
        }, "required": ["vps_id", "service"]},
    }},
    {"type": "function", "function": {
        "name": "restart_vps_service",
        "description": "Reinicia un systemd service en el VPS (solo services con prefijo 'lluvia-').",
        "parameters": {"type": "object", "properties": {
            "vps_id": {"type": "string"},
            "service": {"type": "string"},
        }, "required": ["vps_id", "service"]},
    }},
    # ── Ojos: búsqueda web y navegación ──────────────────────────────────────
    {"type": "function", "function": {
        "name": "web_search",
        "description": (
            "Busca en internet con DuckDuckGo. Usar cuando no sabes algo, necesitas "
            "documentación de una API, quieres verificar un error, o el usuario pregunta "
            "algo que requiere información actualizada o externa."
        ),
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "Consulta de búsqueda en lenguaje natural"},
        }, "required": ["query"]},
    }},
    {"type": "function", "function": {
        "name": "web_browse",
        "description": (
            "Navega y lee el contenido de una URL. Usar para leer documentación, "
            "ver el contenido de un repositorio en GitHub, leer un error en una página, "
            "o analizar cualquier recurso web que el usuario o una búsqueda previa indique."
        ),
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string", "description": "URL completa a navegar (debe empezar con http:// o https://)"},
        }, "required": ["url"]},
    }},
    # ── Plataforma: estado, jobs, stats ──────────────────────────────────────
    {"type": "function", "function": {
        "name": "get_platform_status",
        "description": "Estado general de la plataforma: jobs activos, errores 24h, módulos E2-E11, worker.",
        "parameters": {"type": "object", "properties": {
            "tenant_id": {"type": "string"},
        }, "required": []},
    }},
    {"type": "function", "function": {
        "name": "list_jobs",
        "description": "Lista background jobs de la cola. Filtra por status (pending/running/done/failed).",
        "parameters": {"type": "object", "properties": {
            "status": {"type": "string", "enum": ["pending", "running", "done", "failed"]},
            "job_type": {"type": "string"},
            "limit": {"type": "integer"},
        }, "required": []},
    }},
    {"type": "function", "function": {
        "name": "get_agent_stats",
        "description": "Métricas de uso de un agente: llamadas, errores, ms promedio, últimos N días.",
        "parameters": {"type": "object", "properties": {
            "agent_id": {"type": "string"},
            "days": {"type": "integer"},
        }, "required": ["agent_id"]},
    }},
    # ── Comunicación directa ──────────────────────────────────────────────────
    {"type": "function", "function": {
        "name": "send_notification",
        "description": "Envía notificación in-app a un usuario. Aparece en su panel.",
        "parameters": {"type": "object", "properties": {
            "user_id": {"type": "string"},
            "message": {"type": "string"},
            "type": {"type": "string", "enum": ["info", "success", "warning", "error"]},
            "title": {"type": "string"},
        }, "required": ["user_id", "message"]},
    }},
    {"type": "function", "function": {
        "name": "send_quick_email",
        "description": "Envía un email puntual sin pasar por campañas E4.",
        "parameters": {"type": "object", "properties": {
            "to_email": {"type": "string"},
            "subject": {"type": "string"},
            "body": {"type": "string"},
            "from_name": {"type": "string"},
        }, "required": ["to_email", "subject", "body"]},
    }},
    # ── Generadores: contenido / negocio ─────────────────────────────────────
    {"type": "function", "function": {
        "name": "generate_social_post",
        "description": "Genera copy + hashtags para RRSS usando IA.",
        "parameters": {"type": "object", "properties": {
            "topic": {"type": "string"},
            "platform": {"type": "string", "enum": ["instagram", "twitter", "linkedin", "tiktok", "threads"]},
            "tone": {"type": "string"},
            "language": {"type": "string"},
        }, "required": ["topic", "platform"]},
    }},
    {"type": "function", "function": {
        "name": "generate_qr_card",
        "description": "Genera tarjeta con QR code. Devuelve URL del QR y HTML embeddable.",
        "parameters": {"type": "object", "properties": {
            "data": {"type": "string"},
            "title": {"type": "string"},
            "description": {"type": "string"},
            "size": {"type": "integer"},
        }, "required": ["data", "title"]},
    }},
    {"type": "function", "function": {
        "name": "generate_landing_page",
        "description": "Genera HTML de landing page para un negocio usando IA.",
        "parameters": {"type": "object", "properties": {
            "business_name": {"type": "string"},
            "tagline": {"type": "string"},
            "cta_text": {"type": "string"},
            "cta_url": {"type": "string"},
            "color": {"type": "string"},
            "language": {"type": "string"},
        }, "required": ["business_name", "tagline", "cta_text"]},
    }},
    {"type": "function", "function": {
        "name": "create_intake_form",
        "description": "Crea formulario de captura de leads/contacto. Guarda en DB, retorna embed code.",
        "parameters": {"type": "object", "properties": {
            "title": {"type": "string"},
            "fields": {"type": "array", "items": {"type": "object"}},
            "redirect_url": {"type": "string"},
            "notify_email": {"type": "string"},
        }, "required": ["title", "fields"]},
    }},
    # ── Awareness: codebase / infra / DB ─────────────────────────────────────
    {"type": "function", "function": {
        "name": "search_codebase",
        "description": "Grep en archivos del workspace. Devuelve líneas que coinciden con el patrón.",
        "parameters": {"type": "object", "properties": {
            "app_slug": {"type": "string"},
            "pattern": {"type": "string"},
            "file_ext": {"type": "string", "description": "py, js, ts, etc."},
        }, "required": ["app_slug", "pattern"]},
    }},
    {"type": "function", "function": {
        "name": "inspect_database",
        "description": "Stats de colecciones MongoDB: docs, tamaño, índices. Sin exponer datos de usuarios.",
        "parameters": {"type": "object", "properties": {
            "collection": {"type": "string"},
        }, "required": []},
    }},
    {"type": "function", "function": {
        "name": "get_openapi_schema",
        "description": "Obtiene el schema OpenAPI del backend: rutas, métodos, parámetros.",
        "parameters": {"type": "object", "properties": {
            "filter_path": {"type": "string"},
        }, "required": []},
    }},
    {"type": "function", "function": {
        "name": "list_containers",
        "description": "Lista contenedores Docker activos (docker ps). Solo admin.",
        "parameters": {"type": "object", "properties": {
            "all": {"type": "boolean"},
        }, "required": []},
    }},
    # ── DevOps / Git ──────────────────────────────────────────────────────────
    {"type": "function", "function": {
        "name": "create_checkpoint",
        "description": "Crea checkpoint git (git add + commit). Para rollback seguro antes de cambios.",
        "parameters": {"type": "object", "properties": {
            "message": {"type": "string"},
            "path": {"type": "string"},
        }, "required": ["message"]},
    }},
    {"type": "function", "function": {
        "name": "docker_exec",
        "description": "Ejecuta comando dentro de un contenedor Docker (docker exec). Solo admin.",
        "parameters": {"type": "object", "properties": {
            "container": {"type": "string"},
            "command": {"type": "string"},
        }, "required": ["container", "command"]},
    }},
    {"type": "function", "function": {
        "name": "run_tests",
        "description": "Ejecuta suite de tests del proyecto. Devuelve pass/fail y output. Solo admin.",
        "parameters": {"type": "object", "properties": {
            "test_path": {"type": "string"},
            "framework": {"type": "string", "enum": ["pytest", "jest", "npm_test"]},
        }, "required": []},
    }},
    {"type": "function", "function": {
        "name": "benchmark_endpoint",
        "description": "Mide latencia de un endpoint HTTP: p50/p95/p99 con N requests.",
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string"},
            "n": {"type": "integer"},
            "method": {"type": "string", "enum": ["GET", "POST"]},
        }, "required": ["url"]},
    }},
    # ── Generadores: código / UI ──────────────────────────────────────────────
    {"type": "function", "function": {
        "name": "generate_component",
        "description": "Genera código de componente React/Vue/HTML usando IA.",
        "parameters": {"type": "object", "properties": {
            "description": {"type": "string"},
            "framework": {"type": "string", "enum": ["react", "vue", "html"]},
            "style": {"type": "string"},
        }, "required": ["description"]},
    }},
    {"type": "function", "function": {
        "name": "generate_crud",
        "description": "Genera código CRUD completo (API + modelo) para una entidad.",
        "parameters": {"type": "object", "properties": {
            "entity": {"type": "string"},
            "fields": {"type": "array", "items": {"type": "object"}},
            "stack": {"type": "string", "enum": ["fastapi_mongo", "express_mongo", "django_postgres"]},
        }, "required": ["entity", "fields"]},
    }},
    {"type": "function", "function": {
        "name": "generate_api_route",
        "description": "Genera una ruta FastAPI completa (schema + handler) usando IA.",
        "parameters": {"type": "object", "properties": {
            "route_description": {"type": "string"},
            "method": {"type": "string", "enum": ["GET", "POST", "PUT", "DELETE", "PATCH"]},
            "path": {"type": "string"},
        }, "required": ["route_description", "method", "path"]},
    }},
    {"type": "function", "function": {
        "name": "generate_agent_config",
        "description": "Genera config de un agente AI (nombre, personalidad, tools) y lo crea. Solo admin.",
        "parameters": {"type": "object", "properties": {
            "agent_purpose": {"type": "string"},
            "tools": {"type": "array", "items": {"type": "string"}},
            "language": {"type": "string"},
        }, "required": ["agent_purpose"]},
    }},
    # ── Business / Agency Brain ───────────────────────────────────────────────
    {"type": "function", "function": {
        "name": "generate_proposal",
        "description": "Genera propuesta de negocio/proyecto profesional en Markdown usando IA.",
        "parameters": {"type": "object", "properties": {
            "project": {"type": "string"},
            "client": {"type": "string"},
            "budget_range": {"type": "string"},
            "timeline": {"type": "string"},
        }, "required": ["project", "client"]},
    }},
    {"type": "function", "function": {
        "name": "generate_pricing",
        "description": "Genera estrategia de precios o tabla de planes SaaS usando IA.",
        "parameters": {"type": "object", "properties": {
            "product": {"type": "string"},
            "model": {"type": "string", "enum": ["saas", "agency", "freelance", "ecommerce"]},
            "currency": {"type": "string"},
        }, "required": ["product", "model"]},
    }},
    {"type": "function", "function": {
        "name": "generate_report",
        "description": "Genera reporte de analytics delegando a E9. Tipos: agent_usage, revenue, leads, errors.",
        "parameters": {"type": "object", "properties": {
            "report_type": {"type": "string", "enum": ["agent_usage", "revenue", "leads", "errors", "full"]},
            "tenant_id": {"type": "string"},
            "days": {"type": "integer"},
        }, "required": ["report_type"]},
    }},
    {"type": "function", "function": {
        "name": "crm_lookup",
        "description": "Busca contacto/cliente en el CRM (E8). Retorna historial e interacciones.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"},
        }, "required": ["query"]},
    }},
    {"type": "function", "function": {
        "name": "track_lead",
        "description": "Crea o actualiza lead en el CRM (E8).",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string"},
            "email": {"type": "string"},
            "source": {"type": "string"},
            "notes": {"type": "string"},
        }, "required": ["name", "email"]},
    }},
    # ── Memoria / Razonamiento ────────────────────────────────────────────────
    {"type": "function", "function": {
        "name": "memory_write",
        "description": "Guarda fact/contexto en memoria persistente del agente. Recuperable después.",
        "parameters": {"type": "object", "properties": {
            "key": {"type": "string"},
            "content": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
        }, "required": ["key", "content"]},
    }},
    {"type": "function", "function": {
        "name": "memory_search",
        "description": "Busca en memoria persistente del agente por clave, tag o contenido.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer"},
        }, "required": ["query"]},
    }},
    {"type": "function", "function": {
        "name": "task_planner",
        "description": "Descompone un objetivo complejo en pasos accionables con prioridades usando IA.",
        "parameters": {"type": "object", "properties": {
            "goal": {"type": "string"},
            "context": {"type": "string"},
            "max_steps": {"type": "integer"},
        }, "required": ["goal"]},
    }},
    {"type": "function", "function": {
        "name": "summarize_context",
        "description": "Comprime texto largo manteniendo puntos clave. Útil para resumir conversaciones.",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string"},
            "max_tokens": {"type": "integer"},
            "format": {"type": "string", "enum": ["bullets", "paragraph", "outline"]},
        }, "required": ["text"]},
    }},
    # ── Estabilidad, seguridad y observabilidad (CTO layer) ──────────────────
    {"type": "function", "function": {
        "name": "self_diagnostic",
        "description": "E1 se inspecciona solo: métricas, jobs, módulos, errores recientes. Devuelve health_score + issues + recomendaciones. Solo admin.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    }},
    {"type": "function", "function": {
        "name": "smart_rollback",
        "description": "Rollback inteligente: lista checkpoints, revierte al target (git reset --hard), verifica salud. Solo admin.",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["list", "execute"], "description": "list=ver checkpoints, execute=ejecutar rollback"},
            "target": {"type": "string", "description": "Hash o HEAD~N (requerido si action=execute)"},
            "path": {"type": "string", "description": "Path del repo (default: /opt/lluvia-studio)"},
            "restart_service": {"type": "string", "description": "Nombre del contenedor a reiniciar post-rollback (ej: lluvia_backend)"},
        }, "required": ["action"]},
    }},
    {"type": "function", "function": {
        "name": "analyze_architecture",
        "description": "Mapea módulos backend, rutas API, dependencias y cuellos de botella. Retorna recomendaciones de arquitectura.",
        "parameters": {"type": "object", "properties": {
            "focus": {"type": "string", "description": "Aspecto a analizar: modules, routes, performance (default: modules)"},
        }, "required": []},
    }},
    {"type": "function", "function": {
        "name": "auto_fix_build",
        "description": "Detecta errores de compilación Python en workspace/backend y propone fix via IA. NO auto-aplica (devuelve propuesta). Solo admin.",
        "parameters": {"type": "object", "properties": {
            "app_slug": {"type": "string", "description": "Workspace a revisar (opcional, default: backend del servidor)"},
            "file_path": {"type": "string", "description": "Archivo específico a revisar (opcional)"},
        }, "required": []},
    }},
    {"type": "function", "function": {
        "name": "dependency_audit",
        "description": "Audita vulnerabilidades y packages desactualizados en Python (pip) y frontend (npm).",
        "parameters": {"type": "object", "properties": {
            "target": {"type": "string", "enum": ["python", "frontend", "both"], "description": "Qué auditar (default: both)"},
        }, "required": []},
    }},
    {"type": "function", "function": {
        "name": "security_scan_basic",
        "description": "Escaneo de seguridad básico: secrets hardcodeados, permisos de archivos, puertos expuestos. Solo admin.",
        "parameters": {"type": "object", "properties": {
            "scope": {"type": "string", "enum": ["secrets", "ports", "permissions", "all"], "description": "Qué escanear (default: all)"},
        }, "required": []},
    }},
    {"type": "function", "function": {
        "name": "audit_log_search",
        "description": "Busca en el audit trail de Master Console: acciones, IPs, resultados. Solo admin.",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "description": "Filtrar por acción (opcional, regex)"},
            "since": {"type": "string", "description": "Desde ISO datetime (opcional)"},
            "limit": {"type": "integer", "description": "Max entradas (default 20)"},
        }, "required": []},
    }},
    {"type": "function", "function": {
        "name": "service_health_check",
        "description": "HTTP health check de todos los servicios: backend, MongoDB, job worker. Devuelve status por servicio.",
        "parameters": {"type": "object", "properties": {
            "urls": {"type": "array", "items": {"type": "string"}, "description": "URLs adicionales a verificar (opcional)"},
        }, "required": []},
    }},
    {"type": "function", "function": {
        "name": "queue_monitor",
        "description": "Estado detallado de la cola de background jobs: stats por tipo/estado, DLQ, worker activo.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    }},
    {"type": "function", "function": {
        "name": "git_diff_summary",
        "description": "Muestra cambios pendientes en git y los resume con IA. Para revisar antes de commit.",
        "parameters": {"type": "object", "properties": {
            "staged": {"type": "boolean", "description": "Solo cambios staged (default: false = all changes)"},
            "path": {"type": "string", "description": "Path del repo (default: /opt/lluvia-studio)"},
        }, "required": []},
    }},
    {"type": "function", "function": {
        "name": "process_manager",
        "description": "Lista procesos activos por CPU/RAM. Puede terminar un proceso por PID (action=kill). Solo admin.",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["list", "kill"], "description": "list=ver procesos, kill=terminar PID"},
            "pid": {"type": "integer", "description": "PID a terminar (requerido si action=kill)"},
        }, "required": ["action"]},
    }},
    {"type": "function", "function": {
        "name": "inspect_config",
        "description": "Muestra qué variables de config están seteadas vs faltantes. Sanitizado (no expone valores secretos). Solo admin.",
        "parameters": {"type": "object", "properties": {
            "filter": {"type": "string", "description": "Filtrar por nombre de variable (opcional)"},
        }, "required": []},
    }},
    # ── Master Console / Ejecución interna ───────────────────────────────────
    {"type": "function", "function": {
        "name": "run_python",
        "description": "Ejecuta Python en sandbox seguro (sin I/O, sin red). Para cálculos, scripts, análisis. Solo admin.",
        "parameters": {"type": "object", "properties": {
            "code": {"type": "string", "description": "Código Python a ejecutar"},
            "timeout": {"type": "integer", "description": "Timeout en segundos (default 10, max 30)"},
        }, "required": ["code"]},
    }},
    {"type": "function", "function": {
        "name": "system_metrics",
        "description": "Snapshot de CPU, RAM, disco, procesos y estado del worker. Vista operacional del servidor.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    }},
    {"type": "function", "function": {
        "name": "get_logs",
        "description": "Obtiene logs de un contenedor Docker o servicio systemd. Últimas N líneas.",
        "parameters": {"type": "object", "properties": {
            "target": {"type": "string", "description": "Nombre del contenedor o servicio (ej: lluvia_backend, nginx)"},
            "lines": {"type": "integer", "description": "Líneas a obtener (default 50, max 500)"},
            "source": {"type": "string", "enum": ["docker", "journald"], "description": "Fuente de logs (default: docker)"},
        }, "required": ["target"]},
    }},
    {"type": "function", "function": {
        "name": "list_services",
        "description": "Lista servicios systemd activos y su estado. Equivalente a systemctl status. Solo admin.",
        "parameters": {"type": "object", "properties": {
            "filter": {"type": "string", "description": "Filtrar por nombre (opcional)"},
        }, "required": []},
    }},
    {"type": "function", "function": {
        "name": "list_env_vars",
        "description": "Lista variables de entorno del servidor, sanitizadas (oculta secrets/tokens). Solo admin.",
        "parameters": {"type": "object", "properties": {
            "filter": {"type": "string", "description": "Filtrar vars que contengan este string (opcional)"},
        }, "required": []},
    }},
    # ── Generadores: código avanzado ──────────────────────────────────────────
    {"type": "function", "function": {
        "name": "generate_changelog",
        "description": "Genera CHANGELOG.md profesional desde git log usando IA.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Path del repo (default: /opt/lluvia-studio)"},
            "since": {"type": "string", "description": "Desde qué commit/tag (ej: v1.0.0 o HEAD~20)"},
            "language": {"type": "string", "description": "Idioma (default: español)"},
        }, "required": []},
    }},
    {"type": "function", "function": {
        "name": "generate_backend_module",
        "description": "Genera módulo FastAPI completo: router, modelos Pydantic, handlers, índices Mongo.",
        "parameters": {"type": "object", "properties": {
            "module_name": {"type": "string", "description": "Nombre del módulo (ej: inventory, payments)"},
            "description": {"type": "string", "description": "Qué hace el módulo"},
            "entities": {"type": "array", "items": {"type": "string"}, "description": "Entidades principales (ej: [Product, Category])"},
        }, "required": ["module_name", "description"]},
    }},
    {"type": "function", "function": {
        "name": "generate_dashboard",
        "description": "Genera componente dashboard con gráficas y métricas usando IA (React o HTML).",
        "parameters": {"type": "object", "properties": {
            "title": {"type": "string", "description": "Título del dashboard"},
            "metrics": {"type": "array", "items": {"type": "string"}, "description": "Métricas a mostrar (ej: ['Ventas', 'Usuarios', 'Tickets'])"},
            "framework": {"type": "string", "enum": ["react", "html"], "description": "Framework (default: react)"},
        }, "required": ["title", "metrics"]},
    }},
    {"type": "function", "function": {
        "name": "generate_mobile_screen",
        "description": "Genera screen de React Native (Expo) usando IA.",
        "parameters": {"type": "object", "properties": {
            "screen_name": {"type": "string", "description": "Nombre de la pantalla (ej: HomeScreen, ProfileScreen)"},
            "description": {"type": "string", "description": "Qué debe mostrar y hacer la pantalla"},
            "navigation": {"type": "boolean", "description": "Incluir navegación (default: true)"},
        }, "required": ["screen_name", "description"]},
    }},
    # ── Generadores: negocio/marketing ────────────────────────────────────────
    {"type": "function", "function": {
        "name": "generate_pitch",
        "description": "Genera elevator pitch o estructura de pitch deck en Markdown usando IA.",
        "parameters": {"type": "object", "properties": {
            "product": {"type": "string", "description": "Nombre del producto/startup"},
            "problem": {"type": "string", "description": "Problema que resuelve"},
            "audience": {"type": "string", "description": "Audiencia objetivo (ej: inversionistas, clientes B2B)"},
            "format": {"type": "string", "enum": ["elevator_30s", "elevator_2min", "deck_outline"], "description": "Formato del pitch"},
        }, "required": ["product", "problem"]},
    }},
    {"type": "function", "function": {
        "name": "generate_sales_copy",
        "description": "Genera copy de ventas/marketing (headline, beneficios, CTA) usando IA.",
        "parameters": {"type": "object", "properties": {
            "product": {"type": "string", "description": "Producto o servicio"},
            "audience": {"type": "string", "description": "Audiencia objetivo"},
            "format": {"type": "string", "enum": ["landing_hero", "email_subject", "ad_copy", "product_description"], "description": "Formato del copy"},
            "language": {"type": "string", "description": "Idioma (default: español)"},
        }, "required": ["product", "audience", "format"]},
    }},
    # ── Comunicación adicional ────────────────────────────────────────────────
    {"type": "function", "function": {
        "name": "send_telegram",
        "description": "Envía mensaje via el bot Telegram configurado en la plataforma. Solo admin.",
        "parameters": {"type": "object", "properties": {
            "chat_id": {"type": "string", "description": "Chat ID o username del destinatario"},
            "message": {"type": "string", "description": "Mensaje a enviar (max 4000 chars)"},
        }, "required": ["chat_id", "message"]},
    }},
    {"type": "function", "function": {
        "name": "send_webhook",
        "description": "Dispara una llamada POST a una URL externa con payload JSON. Para integraciones.",
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string", "description": "URL del webhook (debe ser https://)"},
            "payload": {"type": "object", "description": "Datos a enviar como JSON"},
            "headers": {"type": "object", "description": "Headers HTTP adicionales (opcional)"},
        }, "required": ["url", "payload"]},
    }},
    # ── Agent management avanzado ─────────────────────────────────────────────
    {"type": "function", "function": {
        "name": "clone_agent",
        "description": "Clona la configuración de un agente existente con un nuevo ID. Solo admin.",
        "parameters": {"type": "object", "properties": {
            "source_id": {"type": "string", "description": "ID del agente a clonar"},
            "new_id": {"type": "string", "description": "ID del nuevo agente (snake_case)"},
            "new_name": {"type": "string", "description": "Nombre del nuevo agente"},
        }, "required": ["source_id", "new_id", "new_name"]},
    }},
    {"type": "function", "function": {
        "name": "create_workflow",
        "description": "Crea un workflow automatizado (job_scheduler): trigger + pasos + schedule. Solo admin.",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "Nombre del workflow"},
            "job_type": {"type": "string", "description": "Tipo de job (ej: social_post_publish, campaign_dispatch)"},
            "payload": {"type": "object", "description": "Payload del workflow"},
            "run_at": {"type": "string", "description": "ISO datetime para ejecución única (opcional)"},
            "tenant_id": {"type": "string", "description": "Tenant ID (opcional)"},
        }, "required": ["name", "job_type", "payload"]},
    }},
    # ── Meta-tool E1→E2-E9 (additive) ────────────────────────────────────────
    {"type": "function", "function": {
        "name": "call_specialist_tool",
        "description": (
            "Delega una acción a un agente especialista del ecosistema enterprise (E2-E11 + voice). "
            "Usar cuando la tarea requiere capacidades especializadas que están en un sub-orquestador. "
            "E2=infra/deploy, E3=builder/apps, E4=sales/marketing, E5=whitelabel/licencias, "
            "E6=legal/contratos, E7=billing/pagos, E8=soporte/CRM, E9=analytics/monitoreo, "
            "voice=llamadas PSTN/Twilio, "
            "e10=social automation (instagram/tiktok/linkedin/twitter/threads/youtube_shorts), "
            "e11=customer support/Gmail (tickets/escalation/followups/CRM sync)."
        ),
        "parameters": {"type": "object", "properties": {
            "agent": {"type": "string",
                      "enum": ["e2", "e3", "e4", "e5", "e6", "e7", "e8", "e9", "voice", "e10", "e11"],
                      "description": "Sub-orquestador a invocar"},
            "tool": {"type": "string", "description": "Nombre de la tool del agente especialista"},
            "params": {"type": "object", "description": "Parámetros para la tool", "default": {}},
        }, "required": ["agent", "tool"]},
    }},
    # ─────────────────────────────────────────────────────────────────────────
]


# Tools que SOLO admins pueden invocar (shell, provisioning, agent CRUD,
# github_* del catalogo de la plataforma). El resto de tools son seguras
# para cualquier usuario registrado (book_appointment, push_to_my_github,
# paypal_invoice_card, service_card, etc).
ADMIN_ONLY_TOOLS = {
    "shell_run",
    "provision_client_quick",
    "create_agent", "update_agent", "delete_agent",
    "github_list_repos", "github_list_files", "github_read_file", "github_search_code",
    # Platform internals
    "get_platform_status", "list_jobs", "inspect_database", "list_containers",
    # Comms (anti-spam)
    "send_notification", "send_quick_email",
    # DevOps
    "create_checkpoint", "docker_exec", "run_tests",
    # Agent generation / management
    "generate_agent_config", "clone_agent", "create_workflow",
    # Master Console
    "run_python", "list_services", "list_env_vars", "get_logs",
    # Comms externos
    "send_telegram", "send_webhook",
    # CTO stability layer
    "self_diagnostic", "smart_rollback", "auto_fix_build",
    "security_scan_basic", "audit_log_search", "process_manager", "inspect_config",
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



def _suggest_repo_name(app_slug: str) -> str:
    """Genera un nombre de repo unico sugerido para que cada app generada
    vaya a su propio repositorio en GitHub. Asi el usuario no sobrescribe
    apps anteriores. Ejemplo: 'mi-audio-room' -> 'mi-audio-room-x9k4'."""
    import secrets
    base = re.sub(r"[^a-z0-9-]+", "-", (app_slug or "app").lower()).strip("-")[:40] or "lluvia-app"
    return f"{base}-{secrets.token_hex(2)}"


def _build_next_step_text(target: str, slug: str) -> str:
    """Devuelve el next step adaptado al provider que eligió el cliente."""
    target = (target or "render").lower()
    common = (
        "Aprieta + → ⬆ Push a GitHub para subir tu repo. "
        "Si no tenes repo, andá a Mi Cuenta → 📦 Crear repo nuevo. "
    )
    extras = {
        "render": (
            f"Despues, en https://dashboard.render.com → New → Blueprint y conecta tu repo: "
            f"Render lee render.yaml y deploya solo (~5 min). Tu app va a quedar en "
            f"{slug}.onrender.com."
        ),
        "railway": (
            "Despues, en https://railway.app → New Project → Deploy from GitHub. "
            "Railway detecta railway.toml automaticamente (~3 min)."
        ),
        "heroku": (
            "Despues: heroku create && git push heroku main (Procfile ya esta listo)."
        ),
        "fly": (
            "Despues: fly launch en tu repo, te genera fly.toml y deploya."
        ),
        "vps": (
            "Despues, clona el repo en tu VPS y corre: sudo bash install.sh "
            "(instala Python + systemd + arranca en puerto 8001). El README tiene "
            "los pasos para HTTPS con certbot."
        ),
        "docker": (
            "Despues: docker compose up -d (Dockerfile y docker-compose.yml listos)."
        ),
        "local": (
            "Despues: cd backend && pip install -r requirements.txt && python server.py "
            "para correrla local en http://localhost:8001."
        ),
    }
    return common + extras.get(target, extras["render"])



async def _dispatch_to_specialist(agent: str, tool: str, params: dict) -> dict:
    """E1 delega a un sub-orquestador E2-E9. Additive — no modifica tools existentes."""
    try:
        if agent == "e2":
            import e2_infra as m
            fn_map = {
                "deploy_manager": m.tool_deploy_manager,
                "ci_cd_pipeline": m.tool_ci_cd_pipeline,
                "infra_health": m.tool_infra_health,
                "service_monitor": m.tool_service_monitor,
                "rollback_trigger": m.tool_rollback_trigger,
                "ssl_manager": m.tool_ssl_manager,
                "docker_manager": m.tool_docker_manager,
            }
        elif agent == "e3":
            import e3_builder as m
            fn_map = {
                "app_generator": m.tool_app_generator,
                "template_manager": m.tool_template_manager,
                "agent_designer": m.tool_agent_designer,
                "preview_builder": m.tool_preview_builder,
                "build_validator": m.tool_build_validator,
                "hot_reload_trigger": m.tool_hot_reload_trigger,
            }
        elif agent == "e4":
            import e4_sales as m
            fn_map = {
                "lead_manager": m.tool_lead_manager,
                "campaign_builder": m.tool_campaign_builder,
                "funnel_designer": m.tool_funnel_designer,
                "viral_hook_gen": m.tool_viral_hook_gen,
                "seo_optimizer": m.tool_seo_optimizer,
                "social_scheduler": m.tool_social_scheduler,
            }
        elif agent == "e5":
            import e5_whitelabel as m
            fn_map = {
                "license_generator": m.tool_license_generator,
                "tenant_manager": m.tool_tenant_manager,
                "branding_mapper": m.tool_branding_mapper,
                "domain_connector": m.tool_domain_connector,
                "saas_plan_limits": m.tool_saas_plan_limits,
                "white_label_manager": m.tool_white_label_manager,
                "client_activation": m.tool_client_activation,
            }
        elif agent == "e6":
            import e6_legal as m
            fn_map = {
                "tos_generator": m.tool_tos_generator,
                "privacy_builder": m.tool_privacy_builder,
                "contract_builder": m.tool_contract_builder,
                "compliance_checker": m.tool_compliance_checker,
                "gdpr_audit": m.tool_gdpr_audit,
            }
        elif agent == "e7":
            import e7_billing as m
            fn_map = {
                "stripe_manager": m.tool_stripe_manager,
                "subscription_engine": m.tool_subscription_engine,
                "invoice_generator": m.tool_invoice_generator,
                "usage_meter": m.tool_usage_meter,
                "billing_control": m.tool_billing_control,
            }
        elif agent == "e8":
            import e8_support as m
            fn_map = {
                "ticket_manager": m.tool_ticket_manager,
                "crm_contact": m.tool_crm_contact,
                "kb_search": m.tool_kb_search,
                "escalation_handler": m.tool_escalation_handler,
                "support_analytics": m.tool_support_analytics,
            }
        elif agent == "e9":
            import e9_analytics as m
            fn_map = {
                "analytics_dashboard": m.tool_analytics_dashboard,
                "uptime_monitor": m.tool_uptime_monitor,
                "ai_cost_tracker": m.tool_ai_cost_tracker,
                "alert_system": m.tool_alert_system,
                "report_generator": m.tool_report_generator,
            }
        elif agent == "voice":
            import twilio_voice as m
            fn_map = {
                "voice_call_start":    m.tool_voice_call_start,
                "voice_metrics":       m.tool_voice_metrics,
                "voice_agent_config":  m.tool_voice_agent_config,
                "voice_campaign_create": m.tool_voice_campaign_create,
            }
        elif agent == "e10":
            import e10_social as m
            fn_map = {
                "social_post":        m.tool_social_post,
                "social_campaign":    m.tool_social_campaign,
                "social_caption_gen": m.tool_social_caption_gen,
                "social_dm_respond":  m.tool_social_dm_respond,
                "social_analytics":   m.tool_social_analytics,
                "social_connect":     m.tool_social_connect,
            }
        elif agent == "e11":
            import e11_gmail_support as m
            fn_map = {
                "gmail_inbox_process":  m.tool_gmail_inbox_process,
                "gmail_ticket_create":  m.tool_gmail_ticket_create,
                "gmail_ticket_update":  m.tool_gmail_ticket_update,
                "gmail_escalate":       m.tool_gmail_escalate,
                "gmail_followup":       m.tool_gmail_followup,
                "gmail_crm_sync":       m.tool_gmail_crm_sync,
                "gmail_metrics":        m.tool_gmail_metrics,
            }
        else:
            return {"error": f"Agente desconocido: {agent}. Válidos: e2-e11, voice"}

        fn = fn_map.get(tool)
        if not fn:
            return {"error": f"Tool '{tool}' no encontrada en {agent}. Disponibles: {list(fn_map.keys())}"}

        result = await fn(**params) if params else await fn()
        return result if isinstance(result, dict) else {"result": result}
    except Exception as exc:
        return {"error": f"Error en {agent}.{tool}: {str(exc)}"}


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
                    repo_override=args.get("repo"),
                    auto_create_repo=bool(args.get("auto_create_repo")),
                )
                # Refund automatico si el push fallo (token mal, repo no existe, etc).
                # NO refundamos si:
                #   - El cliente solo necesita configurar (needs_setup): la tool ni se ejecuto.
                #   - El push esta bloqueado por candado de exportacion (export_locked):
                #     el cliente no llego a ejecutar push real, refundamos igual para
                #     que vea el modal y no quede sin oros.
                refunded_oros = 0
                if not result.get("ok") and not result.get("needs_setup") and not is_admin:
                    import credits as credits_mod
                    refund_amt = agents_catalog.TOOL_NAMES.get("push_to_my_github", 8)
                    await credits_mod.refund(
                        user_id, refund_amt, "github_push_failed",
                        {"error": str(result.get("error") or result.get("message") or "")[:200],
                         "export_locked": bool(result.get("export_locked"))},
                    )
                    refunded_oros = refund_amt
                # Wrap como rich card para que el frontend lo renderice
                data = {
                    "card_type": "github_push",
                    "ok": result.get("ok", False),
                    "needs_setup": result.get("needs_setup", False),
                    "auth_failed": result.get("auth_failed", False),
                    "export_locked": result.get("export_locked", False),
                    "balance": result.get("balance"),
                    "required": result.get("required"),
                    "missing": result.get("missing"),
                    "recharge_url": result.get("recharge_url"),
                    "message": result.get("message"),
                    "repo": result.get("repo"),
                    "repo_url": result.get("repo_url"),
                    "branch": result.get("branch"),
                    "app_name": result.get("app_name"),
                    "commit_message": result.get("commit_message"),
                    "error": result.get("error"),
                    "help_url": result.get("help_url"),
                    "refunded_oros": refunded_oros,
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
        elif name == "generate_audio_room_app":
            import app_builder
            import user_workspace as uw
            import pricing as pricing_mod
            # Precio dinamico desde el panel admin (sobrescribe TOOL_NAMES)
            cost = await pricing_mod.get_tool_price("generate_audio_room_app")
            app_name_in = (args.get("app_name") or "Mi App").strip()
            brand_color = (args.get("brand_color") or "#5B8DEF").strip()
            deploy_target = (args.get("deploy_target") or "render").strip().lower()
            if deploy_target not in {"render", "railway", "heroku", "fly", "vps", "docker", "local"}:
                deploy_target = "render"
            app_slug = app_builder._slugify(args.get("app_slug") or app_name_in)
            target_dir = os.path.join(uw._user_apps_dir(user_id), app_slug)
            result = app_builder.materialize_template(
                template_id="audio_room",
                target_dir=target_dir,
                app_name=app_name_in,
                brand_color=brand_color,
            )
            # Refund automatico si falla la materializacion
            if not result.get("ok") and not is_admin:
                await credits_mod.refund(
                    user_id, cost, "app_builder_failed",
                    {"error": str(result.get("error"))[:200], "template": "audio_room"},
                )
                result["refunded_oros"] = cost
            data = {
                "card_type": "app_built",
                "ok": result.get("ok", False),
                "template_id": "audio_room",
                "template_name": result.get("template_name", "Audio Room"),
                "app_name": result.get("app_name", app_name_in),
                "app_slug": result.get("app_slug", app_slug),
                "brand_color": result.get("brand_color", brand_color),
                "deploy_target": deploy_target,
                "files_written": result.get("files_written", 0),
                "bytes_written": result.get("bytes_written", 0),
                "screens": ["Inicio", "Tendencias", "Sala Activa", "Perfil"],
                "stack": "FastAPI + Socket.IO + SQLite + Vanilla JS",
                "next_step": _build_next_step_text(deploy_target, result.get("app_slug", app_slug)),
                "repo_suggestion": _suggest_repo_name(result.get("app_slug", app_slug)),
                "error": result.get("error"),
                "refunded_oros": result.get("refunded_oros", 0),
            }
        elif name == "generate_tiktok_app":
            import app_builder
            import user_workspace as uw
            import pricing as pricing_mod
            cost = await pricing_mod.get_tool_price("generate_tiktok_app")
            app_name_in = (args.get("app_name") or "Mi TikTok").strip()
            brand_color = (args.get("brand_color") or "#FF0050").strip()
            deploy_target = (args.get("deploy_target") or "render").strip().lower()
            if deploy_target not in {"render", "railway", "heroku", "fly", "vps", "docker", "local"}:
                deploy_target = "render"
            app_slug = app_builder._slugify(args.get("app_slug") or app_name_in)
            target_dir = os.path.join(uw._user_apps_dir(user_id), app_slug)
            result = app_builder.materialize_template(
                template_id="tiktok_clone",
                target_dir=target_dir,
                app_name=app_name_in,
                brand_color=brand_color,
            )
            if not result.get("ok") and not is_admin:
                await credits_mod.refund(
                    user_id, cost, "app_builder_failed",
                    {"error": str(result.get("error"))[:200], "template": "tiktok_clone"},
                )
                result["refunded_oros"] = cost
            data = {
                "card_type": "app_built",
                "ok": result.get("ok", False),
                "template_id": "tiktok_clone",
                "template_name": result.get("template_name", "TikTok / Bigo Live Clone"),
                "app_name": result.get("app_name", app_name_in),
                "app_slug": result.get("app_slug", app_slug),
                "brand_color": result.get("brand_color", brand_color),
                "deploy_target": deploy_target,
                "files_written": result.get("files_written", 0),
                "bytes_written": result.get("bytes_written", 0),
                "screens": ["Feed Vertical", "Descubrir", "Subir Video", "Perfil"],
                "stack": "FastAPI + SQLite + Vanilla JS + HLS Player",
                "next_step": _build_next_step_text(deploy_target, result.get("app_slug", app_slug)),
                "repo_suggestion": _suggest_repo_name(result.get("app_slug", app_slug)),
                "error": result.get("error"),
                "refunded_oros": result.get("refunded_oros", 0),
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
        # ============================================================
        # Lluvia Studio tools (workspace + VPS)
        # ============================================================
        elif name == "list_workspace_files":
            import workspace_files as wf
            from pathlib import Path
            slug = re.sub(r"[^a-zA-Z0-9_.-]", "", args.get("app_slug", ""))[:80]
            base = wf._user_apps_dir(user_id) / slug
            if not base.exists():
                data = {"error": f"App '{slug}' no existe en el workspace"}
            else:
                data = {"tree": wf._build_tree(base), "app_slug": slug}
        elif name == "read_workspace_file":
            import workspace_files as wf
            slug = re.sub(r"[^a-zA-Z0-9_.-]", "", args.get("app_slug", ""))[:80]
            base = wf._user_apps_dir(user_id) / slug
            try:
                f = wf._safe_path(base, args.get("path", ""))
                if not f.exists() or not f.is_file():
                    data = {"error": "Archivo no encontrado"}
                elif f.stat().st_size > 2_000_000:
                    data = {"error": "Archivo >2MB"}
                else:
                    try:
                        data = {"path": args.get("path"), "content": f.read_text(encoding="utf-8")}
                    except UnicodeDecodeError:
                        data = {"path": args.get("path"), "is_binary": True}
            except Exception as e:
                data = {"error": str(e)}
        elif name == "write_workspace_file":
            import workspace_files as wf
            import difflib
            slug = re.sub(r"[^a-zA-Z0-9_.-]", "", args.get("app_slug", ""))[:80]
            base = wf._user_apps_dir(user_id) / slug
            base.mkdir(parents=True, exist_ok=True)
            try:
                f = wf._safe_path(base, args.get("path", ""))
                f.parent.mkdir(parents=True, exist_ok=True)
                old = f.read_text(encoding="utf-8") if f.exists() else ""
                new_content = args.get("content", "")
                f.write_text(new_content, encoding="utf-8")
                diff = "\n".join(difflib.unified_diff(
                    old.splitlines(), new_content.splitlines(),
                    fromfile=f"a/{args.get('path')}", tofile=f"b/{args.get('path')}", lineterm="",
                ))
                edit_id = str(uuid.uuid4())
                await _db_ref["db"].file_edits.insert_one({
                    "id": edit_id, "user_id": user_id, "app_slug": slug,
                    "file_path": args.get("path"), "diff": diff[:50000],
                    "previous_content": old[:500_000], "applied_by": "agent",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                })
                data = {"ok": True, "edit_id": edit_id, "size": len(new_content), "diff_lines": diff.count("\n")}
            except Exception as e:
                data = {"error": str(e)}
        elif name == "search_replace_workspace":
            import workspace_files as wf
            import difflib
            slug = re.sub(r"[^a-zA-Z0-9_.-]", "", args.get("app_slug", ""))[:80]
            base = wf._user_apps_dir(user_id) / slug
            try:
                f = wf._safe_path(base, args.get("path", ""))
                if not f.exists():
                    data = {"error": "Archivo no encontrado"}
                else:
                    old_content = f.read_text(encoding="utf-8")
                    old_str = args.get("old_str", "")
                    new_str = args.get("new_str", "")
                    if old_str not in old_content:
                        data = {"error": "old_str no encontrado en el archivo"}
                    elif old_content.count(old_str) > 1:
                        data = {"error": f"old_str aparece {old_content.count(old_str)} veces, debe ser unico"}
                    else:
                        new_content = old_content.replace(old_str, new_str)
                        f.write_text(new_content, encoding="utf-8")
                        edit_id = str(uuid.uuid4())
                        await _db_ref["db"].file_edits.insert_one({
                            "id": edit_id, "user_id": user_id, "app_slug": slug,
                            "file_path": args.get("path"), "applied_by": "agent",
                            "previous_content": old_content[:500_000],
                            "created_at": datetime.now(timezone.utc).isoformat(),
                        })
                        data = {"ok": True, "edit_id": edit_id, "replaced": True}
            except Exception as e:
                data = {"error": str(e)}
        elif name == "list_my_vps":
            db = _db_ref["db"]
            cur = db.vps_servers.find(
                {"user_id": user_id},
                {"_id": 0, "ssh_key_encrypted": 0, "password_encrypted": 0},
            )
            data = {"vps": [v async for v in cur]}
        elif name == "run_vps_command":
            import vps_manager as vm
            db = _db_ref["db"]
            vps = await db.vps_servers.find_one({"id": args.get("vps_id"), "user_id": user_id})
            if not vps:
                data = {"error": "VPS no encontrado o no es tuyo"}
            else:
                blocked = ["rm -rf /", "mkfs", "shutdown", "reboot", ":(){:|:&};:"]
                if any(b in args.get("command", "") for b in blocked):
                    data = {"error": "Comando bloqueado por seguridad"}
                else:
                    data = await vm._ssh_run(vps, args.get("command", ""),
                                              timeout=int(args.get("timeout_sec", 60)))
        elif name == "deploy_app_to_vps":
            import vps_manager as vm
            from vps_manager import DeployIn
            db = _db_ref["db"]
            vps = await db.vps_servers.find_one({"id": args.get("vps_id"), "user_id": user_id})
            if not vps:
                data = {"error": "VPS no encontrado"}
            else:
                udoc = await db.users.find_one({"id": user_id}, {"_id": 0})
                try:
                    payload = DeployIn(**{k: v for k, v in args.items() if k != "vps_id"})
                    data = await vm.deploy_app_to_vps(args.get("vps_id"), payload, udoc)
                    data["card_type"] = "vps_deploy"
                except Exception as e:
                    data = {"error": str(e)}
        elif name == "tail_vps_logs":
            import vps_manager as vm
            db = _db_ref["db"]
            vps = await db.vps_servers.find_one({"id": args.get("vps_id"), "user_id": user_id})
            if not vps:
                data = {"error": "VPS no encontrado"}
            else:
                service = re.sub(r"[^a-z0-9._-]", "", args.get("service", ""))
                n = max(10, min(int(args.get("lines", 100)), 1000))
                data = await vm._ssh_run(vps, f"sudo journalctl -u {service} -n {n} --no-pager", timeout=15)
        elif name == "restart_vps_service":
            import vps_manager as vm
            db = _db_ref["db"]
            vps = await db.vps_servers.find_one({"id": args.get("vps_id"), "user_id": user_id})
            if not vps:
                data = {"error": "VPS no encontrado"}
            else:
                service = re.sub(r"[^a-z0-9._-]", "", args.get("service", ""))
                if not service.startswith("lluvia-"):
                    data = {"error": "Solo se pueden reiniciar services con prefijo 'lluvia-'"}
                else:
                    data = await vm._ssh_run(vps, f"sudo systemctl restart {service} && sudo systemctl is-active {service}", timeout=30)
        elif name == "call_specialist_tool":
            data = await _dispatch_to_specialist(
                args.get("agent", ""), args.get("tool", ""), args.get("params", {})
            )
        elif name == "web_search":
            query = args.get("query", "")
            if not query:
                data = {"error": "query requerido"}
            else:
                result = await _web_search(query)
                data = {"query": query, "results": result}
        elif name == "web_browse":
            url = args.get("url", "")
            if not url:
                data = {"error": "url requerido"}
            elif not url.startswith(("http://", "https://")):
                data = {"error": "URL debe empezar con http:// o https://"}
            else:
                result = await _web_browse(url)
                data = {"url": url, "content": result}
        # ── 9 nuevas tools (plataforma + comms + generadores) ────────────────
        elif name == "get_platform_status":
            if not is_admin:
                return json.dumps({"error": "requiere admin"}), 0
            data = await _tool_get_platform_status(args)
        elif name == "list_jobs":
            if not is_admin:
                return json.dumps({"error": "requiere admin"}), 0
            data = await _tool_list_jobs(args)
        elif name == "get_agent_stats":
            data = await _tool_get_agent_stats(args)
        elif name == "send_notification":
            if not is_admin:
                return json.dumps({"error": "requiere admin"}), 0
            data = await _tool_send_notification(args)
        elif name == "send_quick_email":
            if not is_admin:
                return json.dumps({"error": "requiere admin"}), 0
            data = await _tool_send_quick_email(args, user_id)
        elif name == "generate_social_post":
            data = await _tool_generate_social_post(args)
        elif name == "generate_qr_card":
            data = _tool_generate_qr_card(args)
        elif name == "generate_landing_page":
            data = await _tool_generate_landing_page(args)
        elif name == "create_intake_form":
            data = await _tool_create_intake_form(args, user_id)
        # ── Awareness / infra ────────────────────────────────────────────────
        elif name == "search_codebase":
            data = await _tool_search_codebase(args, user_id)
        elif name == "inspect_database":
            if not is_admin:
                return json.dumps({"error": "requiere admin"}), 0
            data = await _tool_inspect_database(args)
        elif name == "get_openapi_schema":
            data = await _tool_get_openapi_schema(args)
        elif name == "list_containers":
            if not is_admin:
                return json.dumps({"error": "requiere admin"}), 0
            data = await _tool_list_containers(args)
        # ── DevOps / Git ─────────────────────────────────────────────────────
        elif name == "create_checkpoint":
            if not is_admin:
                return json.dumps({"error": "requiere admin"}), 0
            data = await _tool_create_checkpoint(args)
        elif name == "docker_exec":
            if not is_admin:
                return json.dumps({"error": "requiere admin"}), 0
            data = await _tool_docker_exec(args)
        elif name == "run_tests":
            if not is_admin:
                return json.dumps({"error": "requiere admin"}), 0
            data = await _tool_run_tests(args)
        elif name == "benchmark_endpoint":
            data = await _tool_benchmark_endpoint(args)
        # ── Generadores: código / UI ─────────────────────────────────────────
        elif name == "generate_component":
            data = await _tool_generate_code(args, "component")
        elif name == "generate_crud":
            data = await _tool_generate_code(args, "crud")
        elif name == "generate_api_route":
            data = await _tool_generate_code(args, "api_route")
        elif name == "generate_agent_config":
            if not is_admin:
                return json.dumps({"error": "requiere admin"}), 0
            data = await _tool_generate_agent_config(args, user_id)
        # ── Business / Agency Brain ──────────────────────────────────────────
        elif name == "generate_proposal":
            data = await _tool_generate_doc(args, "proposal")
        elif name == "generate_pricing":
            data = await _tool_generate_doc(args, "pricing")
        elif name == "generate_report":
            data = await _tool_generate_report(args)
        elif name == "crm_lookup":
            data = await _dispatch_to_specialist("e8", "contact_list", {"search": args.get("query", "")})
        elif name == "track_lead":
            data = await _dispatch_to_specialist("e8", "contact_create", args)
        # ── Memoria / Razonamiento ───────────────────────────────────────────
        elif name == "memory_write":
            data = await _tool_memory_write(args, user_id)
        elif name == "memory_search":
            data = await _tool_memory_search(args, user_id)
        elif name == "task_planner":
            data = await _tool_task_planner(args)
        elif name == "summarize_context":
            data = await _tool_summarize_context(args)
        # ── Master Console / Ejecución interna ──────────────────────────────
        elif name == "run_python":
            if not is_admin:
                return json.dumps({"error": "requiere admin"}), 0
            data = await _tool_run_python(args)
        elif name == "system_metrics":
            data = await _tool_system_metrics()
        elif name == "get_logs":
            if not is_admin:
                return json.dumps({"error": "requiere admin"}), 0
            data = await _tool_get_logs(args)
        elif name == "list_services":
            if not is_admin:
                return json.dumps({"error": "requiere admin"}), 0
            data = await _tool_list_services(args)
        elif name == "list_env_vars":
            if not is_admin:
                return json.dumps({"error": "requiere admin"}), 0
            data = _tool_list_env_vars(args)
        # ── Generadores avanzados ────────────────────────────────────────────
        elif name == "generate_changelog":
            data = await _tool_generate_changelog(args)
        elif name == "generate_backend_module":
            data = await _tool_generate_advanced_code(args, "backend_module")
        elif name == "generate_dashboard":
            data = await _tool_generate_advanced_code(args, "dashboard")
        elif name == "generate_mobile_screen":
            data = await _tool_generate_advanced_code(args, "mobile_screen")
        elif name == "generate_pitch":
            data = await _tool_generate_advanced_code(args, "pitch")
        elif name == "generate_sales_copy":
            data = await _tool_generate_advanced_code(args, "sales_copy")
        # ── Comunicación adicional ───────────────────────────────────────────
        elif name == "send_telegram":
            if not is_admin:
                return json.dumps({"error": "requiere admin"}), 0
            data = await _tool_send_telegram(args)
        elif name == "send_webhook":
            if not is_admin:
                return json.dumps({"error": "requiere admin"}), 0
            data = await _tool_send_webhook(args)
        # ── Agent management avanzado ────────────────────────────────────────
        elif name == "clone_agent":
            if not is_admin:
                return json.dumps({"error": "requiere admin"}), 0
            data = await _tool_clone_agent(args, user_id)
        elif name == "create_workflow":
            if not is_admin:
                return json.dumps({"error": "requiere admin"}), 0
            data = await _tool_create_workflow(args, user_id)
        # ── CTO: Estabilidad, seguridad y observabilidad ─────────────────────
        elif name == "self_diagnostic":
            if not is_admin:
                return json.dumps({"error": "requiere admin"}), 0
            data = await _tool_self_diagnostic()
        elif name == "smart_rollback":
            if not is_admin:
                return json.dumps({"error": "requiere admin"}), 0
            data = await _tool_smart_rollback(args)
        elif name == "analyze_architecture":
            data = await _tool_analyze_architecture(args)
        elif name == "auto_fix_build":
            if not is_admin:
                return json.dumps({"error": "requiere admin"}), 0
            data = await _tool_auto_fix_build(args, user_id)
        elif name == "dependency_audit":
            data = await _tool_dependency_audit(args)
        elif name == "security_scan_basic":
            if not is_admin:
                return json.dumps({"error": "requiere admin"}), 0
            data = await _tool_security_scan_basic(args)
        elif name == "audit_log_search":
            if not is_admin:
                return json.dumps({"error": "requiere admin"}), 0
            data = await _tool_audit_log_search(args)
        elif name == "service_health_check":
            data = await _tool_service_health_check(args)
        elif name == "queue_monitor":
            data = await _tool_queue_monitor()
        elif name == "git_diff_summary":
            data = await _tool_git_diff_summary(args)
        elif name == "process_manager":
            if not is_admin:
                return json.dumps({"error": "requiere admin"}), 0
            data = await _tool_process_manager(args)
        elif name == "inspect_config":
            if not is_admin:
                return json.dumps({"error": "requiere admin"}), 0
            data = _tool_inspect_config(args)
        else:
            return json.dumps({"error": f"Tool desconocida: {name}"}), 0
        return json.dumps(data, ensure_ascii=False)[:30000], cost
    except Exception as e:
        return json.dumps({"error": str(e)}), 0


async def _web_search(query: str) -> str:
    import httpx, html as _html
    try:
        async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
            r = await client.get(
                "https://api.duckduckgo.com/",
                params={"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"},
                headers={"User-Agent": "LluviaAppStudio/12.55"},
            )
            data = r.json()
    except Exception as e:
        return f"Error buscando: {e}"
    lines = []
    if data.get("Answer"):
        lines.append(f"Respuesta directa: {data['Answer']}")
    if data.get("AbstractText"):
        lines.append(f"Resumen: {data['AbstractText'][:800]}")
        if data.get("AbstractURL"):
            lines.append(f"Fuente: {data['AbstractURL']}")
    for topic in data.get("RelatedTopics", [])[:8]:
        if isinstance(topic, dict) and "Text" in topic:
            url = topic.get("FirstURL", "")
            lines.append(f"• {topic['Text'][:250]}" + (f" — {url}" if url else ""))
    return "\n".join(lines) if lines else f"Sin resultados para: {query}"


async def _web_browse(url: str) -> str:
    import httpx, html as _html, re
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            r = await client.get(url, headers={"User-Agent": "LluviaAppStudio/12.55"})
            r.raise_for_status()
            text = r.text
    except Exception as e:
        return f"Error obteniendo URL: {e}"
    text = re.sub(r"<script[^>]*>[\s\S]*?</script>", "", text, flags=re.I)
    text = re.sub(r"<style[^>]*>[\s\S]*?</style>", "", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = _html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:8000] or "(página vacía)"


# ============================================================
# IMPLEMENTACIONES — 30 nuevas tools E1
# ============================================================

async def _tool_get_platform_status(args: dict) -> dict:
    db = _db_ref["db"]
    import job_scheduler as js
    tenant_id = args.get("tenant_id", "")
    q = {"tenant_id": tenant_id} if tenant_id else {}
    pipeline = [{"$match": q}, {"$group": {"_id": "$status", "count": {"$sum": 1}}}]
    job_rows = [doc async for doc in db.jobs.aggregate(pipeline)]
    job_stats = {r["_id"]: r["count"] for r in job_rows}
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    errors_24h = await db.e9_events.count_documents({
        "event_type": {"$regex": "error", "$options": "i"},
        "ts": {"$gte": cutoff},
        **({"tenant_id": tenant_id} if tenant_id else {}),
    })
    active_modules: set = set()
    async for doc in db.e9_counters.find(
        {"module": {"$in": ["e2", "e3", "e4", "e5", "e6", "e7", "e8", "e9", "e10", "e11"]}},
        {"_id": 0, "module": 1},
    ):
        active_modules.add(doc["module"])
    worker = js._worker.status() if hasattr(js, "_worker") else {}
    return {
        "worker": worker, "jobs": job_stats,
        "errors_24h": errors_24h, "active_modules": sorted(active_modules),
        "ts": datetime.now(timezone.utc).isoformat(),
    }


async def _tool_list_jobs(args: dict) -> dict:
    db = _db_ref["db"]
    q: dict = {}
    if args.get("status"):
        q["status"] = args["status"]
    if args.get("job_type"):
        q["job_type"] = args["job_type"]
    limit = max(1, min(int(args.get("limit", 20)), 100))
    jobs = [doc async for doc in db.jobs.find(q, {"_id": 0}).sort("created_at", -1).limit(limit)]
    return {"jobs": jobs, "count": len(jobs)}


async def _tool_get_agent_stats(args: dict) -> dict:
    db = _db_ref["db"]
    agent_id = (args.get("agent_id") or "").strip()
    if not agent_id:
        return {"error": "agent_id requerido"}
    from datetime import timedelta
    days = max(1, min(int(args.get("days", 7)), 90))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = [doc async for doc in db.e9_counters.aggregate([
        {"$match": {"module": agent_id, "day": {"$gte": cutoff}}},
        {"$group": {"_id": None, "calls": {"$sum": "$call_count"},
                    "errors": {"$sum": "$error_count"}, "ms": {"$sum": "$total_elapsed_ms"}}},
    ])]
    s = rows[0] if rows else {"calls": 0, "errors": 0, "ms": 0}
    s.pop("_id", None)
    if s.get("calls"):
        s["avg_ms"] = round(s["ms"] / s["calls"])
    s["agent_id"] = agent_id
    s["period_days"] = days
    return s


async def _tool_send_notification(args: dict) -> dict:
    db = _db_ref["db"]
    user_id = (args.get("user_id") or "").strip()
    message = (args.get("message") or "").strip()[:500]
    if not user_id or not message:
        return {"error": "user_id y message requeridos"}
    ntype = args.get("type", "info")
    if ntype not in {"info", "success", "warning", "error"}:
        ntype = "info"
    doc = {
        "id": str(uuid.uuid4()), "user_id": user_id,
        "title": (args.get("title") or "Notificación").strip()[:80],
        "message": message, "type": ntype, "read": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.e1_notifications.insert_one(doc)
    doc.pop("_id", None)
    return {"sent": True, "notification": doc}


async def _tool_send_quick_email(args: dict, user_id: str) -> dict:
    to_email = (args.get("to_email") or "").strip().lower()
    subject = (args.get("subject") or "").strip()[:150]
    body = (args.get("body") or "").strip()[:8000]
    if not to_email or not subject or not body:
        return {"error": "to_email, subject y body requeridos"}
    import e4_email
    html_body = body if "<" in body else body.replace("\n", "<br>")
    return await e4_email.send_email(
        tenant_id=user_id, to_email=to_email, subject=subject,
        html_body=html_body, text_body=body,
        idempotency_key=f"quick_{user_id}_{abs(hash(to_email + subject)) % 0xFFFFFF:06x}",
        include_unsub=False,
    )


async def _tool_generate_social_post(args: dict) -> dict:
    topic = (args.get("topic") or "").strip()[:300]
    platform = args.get("platform", "instagram")
    if not topic:
        return {"error": "topic requerido"}
    hints = {
        "instagram": "≤2200 chars, 5-10 hashtags, emojis",
        "twitter": "≤280 chars, 1-3 hashtags",
        "linkedin": "profesional, ≤700 chars",
        "tiktok": "viral, ≤150 chars, 3-5 hashtags trending",
        "threads": "conversacional, ≤500 chars",
    }
    prompt = (f"Post para {platform} ({hints.get(platform, '')}) en {args.get('language','español')}. "
              f"Tono: {args.get('tone','casual')}. Tema: {topic}\nDevuelve SOLO el copy del post.")
    client, model = llm_router.get_client("low")
    resp = await client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}],
        max_tokens=300, temperature=0.8,
    )
    return {"platform": platform, "post": resp.choices[0].message.content.strip(), "topic": topic}


def _tool_generate_qr_card(args: dict) -> dict:
    import urllib.parse
    data = (args.get("data") or "").strip()
    title = (args.get("title") or "").strip()[:80]
    if not data or not title:
        return {"error": "data y title requeridos"}
    size = max(100, min(int(args.get("size", 200)), 500))
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size={size}x{size}&data={urllib.parse.quote(data)}"
    desc = (args.get("description") or "").strip()[:200]
    html = (f'<div style="text-align:center;font-family:sans-serif;padding:20px">'
            f'<h2>{title}</h2>{"<p>" + desc + "</p>" if desc else ""}'
            f'<img src="{qr_url}" style="margin:10px auto;display:block"/>'
            f'<p style="font-size:12px;color:#888">{data}</p></div>')
    return {"title": title, "qr_url": qr_url, "html": html}


async def _tool_generate_landing_page(args: dict) -> dict:
    biz = (args.get("business_name") or "").strip()[:80]
    tagline = (args.get("tagline") or "").strip()[:200]
    cta = (args.get("cta_text") or "").strip()[:60]
    if not biz or not tagline or not cta:
        return {"error": "business_name, tagline y cta_text requeridos"}
    color = re.sub(r"[^#a-fA-F0-9]", "", args.get("color", "#5fb4ff"))[:7] or "#5fb4ff"
    cta_url = (args.get("cta_url") or "#").strip()
    prompt = (f"HTML body de landing page para '{biz}' en {args.get('language','español')}. "
              f"Tagline: '{tagline}'. Botón: '{cta}' → '{cta_url}'. Color: {color}. "
              "Incluye: hero, 3 beneficios, CTA. Sin <html>/<head>/<body>. Solo el contenido.")
    client, model = llm_router.get_client("low")
    resp = await client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}],
        max_tokens=700, temperature=0.5,
    )
    return {"business_name": biz, "html": resp.choices[0].message.content.strip(), "color": color}


async def _tool_create_intake_form(args: dict, user_id: str) -> dict:
    db = _db_ref["db"]
    title = (args.get("title") or "").strip()[:120]
    fields = args.get("fields") or []
    if not title or not isinstance(fields, list) or not fields:
        return {"error": "title y fields (lista) requeridos"}
    form_id = str(uuid.uuid4())[:12].replace("-", "")
    doc = {
        "id": form_id, "title": title, "fields": fields[:20],
        "redirect_url": (args.get("redirect_url") or "").strip()[:300],
        "notify_email": (args.get("notify_email") or "").strip().lower()[:100],
        "owner_id": user_id, "submissions": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.e1_forms.insert_one(doc)
    doc.pop("_id", None)
    embed = f'<iframe src="/forms/{form_id}" width="100%" height="600" frameborder="0"></iframe>'
    return {"created": True, "form_id": form_id, "embed_code": embed, "form": doc}


async def _tool_search_codebase(args: dict, user_id: str) -> dict:
    import subprocess, os as _os
    app_slug = re.sub(r"[^a-zA-Z0-9_.-]", "", (args.get("app_slug") or "").strip())[:80]
    pattern = (args.get("pattern") or "").strip()[:200]
    if not app_slug or not pattern:
        return {"error": "app_slug y pattern requeridos"}
    base_dir = _os.environ.get("LLUVIA_HOME", "/app")
    base = _os.path.join(base_dir, "user_apps", user_id, app_slug)
    if not _os.path.isdir(base):
        return {"error": f"Workspace '{app_slug}' no encontrado"}
    ext = (args.get("file_ext") or "").strip().lstrip(".")
    include = [f"--include=*.{ext}"] if ext else []
    try:
        r = subprocess.run(
            ["grep", "-rn", "--max-count=3"] + include + [pattern, base],
            capture_output=True, text=True, timeout=10,
        )
        lines = r.stdout.strip().splitlines()[:50]
        return {"pattern": pattern, "matches": lines, "total": len(lines)}
    except Exception as e:
        return {"error": str(e)}


async def _tool_inspect_database(args: dict) -> dict:
    db = _db_ref["db"]
    target = (args.get("collection") or "").strip()
    if target:
        stats = await db.command("collStats", target)
        return {
            "collection": target,
            "count": stats.get("count", 0),
            "size_mb": round(stats.get("size", 0) / 1024 / 1024, 3),
            "indexes": stats.get("nindexes", 0),
        }
    names = await db.list_collection_names()
    result = []
    for name in sorted(names)[:30]:
        try:
            c = await db[name].count_documents({})
            result.append({"collection": name, "count": c})
        except Exception:
            result.append({"collection": name, "count": "?"})
    return {"collections": result}


async def _tool_get_openapi_schema(args: dict) -> dict:
    import httpx
    filter_path = (args.get("filter_path") or "").strip().lower()
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get("http://localhost:8000/openapi.json")
            schema = r.json()
    except Exception as e:
        return {"error": f"No se pudo obtener schema: {e}"}
    paths = schema.get("paths", {})
    if filter_path:
        paths = {k: v for k, v in paths.items() if filter_path in k.lower()}
    summary = []
    for path, methods in list(paths.items())[:60]:
        for method, detail in methods.items():
            summary.append({
                "path": path, "method": method.upper(),
                "summary": (detail.get("summary") or detail.get("description") or "")[:80],
            })
    return {"routes": summary, "total": len(summary)}


async def _tool_list_containers(args: dict) -> dict:
    import asyncio
    flag = ["-a"] if args.get("all") else []
    proc = await asyncio.create_subprocess_exec(
        "docker", "ps", *flag, "--format", "{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
    lines = stdout.decode().strip().splitlines()
    containers = []
    for line in lines:
        parts = line.split("\t")
        containers.append({
            "name": parts[0] if len(parts) > 0 else "",
            "image": parts[1] if len(parts) > 1 else "",
            "status": parts[2] if len(parts) > 2 else "",
            "ports": parts[3] if len(parts) > 3 else "",
        })
    return {"containers": containers, "count": len(containers)}


async def _tool_create_checkpoint(args: dict) -> dict:
    message = (args.get("message") or "").strip()[:200]
    if not message:
        return {"error": "message requerido"}
    path = re.sub(r"[^a-zA-Z0-9_./-]", "", (args.get("path") or "/opt/lluvia-studio").strip())
    import asyncio
    async def _git(cmd: list) -> str:
        p = await asyncio.create_subprocess_exec(
            *cmd, cwd=path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, err = await asyncio.wait_for(p.communicate(), timeout=30)
        return (out + err).decode().strip()
    add_out = await _git(["git", "add", "-A"])
    commit_out = await _git(["git", "commit", "-m", f"[checkpoint] {message}"])
    hash_out = await _git(["git", "rev-parse", "--short", "HEAD"])
    return {"checkpoint": hash_out, "message": message, "git_output": commit_out[:400]}


async def _tool_docker_exec(args: dict) -> dict:
    container = re.sub(r"[^a-zA-Z0-9_.-]", "", (args.get("container") or "").strip())[:80]
    command = (args.get("command") or "").strip()[:500]
    if not container or not command:
        return {"error": "container y command requeridos"}
    safe, reason = is_command_safe(command)
    if not safe:
        return {"error": f"Comando bloqueado: {reason}"}
    import asyncio
    proc = await asyncio.create_subprocess_exec(
        "docker", "exec", container, "sh", "-c", command,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
    return {
        "container": container, "command": command,
        "output": (stdout + stderr).decode().strip()[:5000],
        "exit_code": proc.returncode,
    }


async def _tool_run_tests(args: dict) -> dict:
    import asyncio
    framework = args.get("framework", "pytest")
    test_path = re.sub(r"[^a-zA-Z0-9_./-]", "", (args.get("test_path") or "tests/").strip())
    if framework == "pytest":
        cmd = ["python", "-m", "pytest", test_path, "-v", "--tb=short", "-q"]
        cwd = "/opt/lluvia-studio/backend"
    elif framework == "jest":
        cmd = ["npx", "jest", test_path, "--no-coverage"]
        cwd = "/opt/lluvia-studio/frontend"
    else:
        cmd = ["npm", "test", "--", "--watchAll=false"]
        cwd = "/opt/lluvia-studio/frontend"
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=cwd,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
    except asyncio.TimeoutError:
        proc.kill()
        return {"error": "Tests timeout (120s)"}
    output = (stdout + stderr).decode().strip()[-4000:]
    return {"framework": framework, "exit_code": proc.returncode,
            "passed": proc.returncode == 0, "output": output}


async def _tool_benchmark_endpoint(args: dict) -> dict:
    import httpx, statistics, time
    url = (args.get("url") or "").strip()
    if not url or not url.startswith(("http://", "https://")):
        return {"error": "url valida requerida (http/https)"}
    n = max(1, min(int(args.get("n", 10)), 50))
    method = args.get("method", "GET").upper()
    if method not in {"GET", "POST"}:
        method = "GET"
    times_ms = []
    async with httpx.AsyncClient(timeout=10) as client:
        for _ in range(n):
            t0 = time.perf_counter()
            try:
                fn = client.get if method == "GET" else client.post
                r = await fn(url)
                times_ms.append(round((time.perf_counter() - t0) * 1000, 2))
            except Exception as e:
                return {"error": str(e)}
    times_ms.sort()
    return {
        "url": url, "n": n, "method": method,
        "p50_ms": times_ms[len(times_ms) // 2],
        "p95_ms": times_ms[int(len(times_ms) * 0.95)],
        "p99_ms": times_ms[int(len(times_ms) * 0.99)],
        "avg_ms": round(statistics.mean(times_ms), 2),
        "min_ms": times_ms[0], "max_ms": times_ms[-1],
    }


async def _tool_generate_code(args: dict, code_type: str) -> dict:
    client, model = llm_router.get_client("low")
    if code_type == "component":
        desc = (args.get("description") or "").strip()[:400]
        fw = args.get("framework", "react")
        style = args.get("style", "")
        if not desc:
            return {"error": "description requerido"}
        prompt = (f"Genera componente {fw} en español. {('Estilos: ' + style) if style else ''}. "
                  f"Función: {desc}\nDevuelve SOLO el código, sin explicaciones.")
        max_tok = 600
    elif code_type == "crud":
        entity = (args.get("entity") or "").strip()[:60]
        fields = args.get("fields") or []
        stack = args.get("stack", "fastapi_mongo")
        if not entity or not fields:
            return {"error": "entity y fields requeridos"}
        fields_str = json.dumps(fields[:10])
        prompt = (f"Genera CRUD completo {stack} para entidad '{entity}'. "
                  f"Campos: {fields_str}. Include: modelo, rutas GET/POST/PUT/DELETE, validación. "
                  "Devuelve SOLO el código.")
        max_tok = 900
    else:  # api_route
        route_desc = (args.get("route_description") or "").strip()[:400]
        method = args.get("method", "GET").upper()
        path = (args.get("path") or "/api/items").strip()[:100]
        if not route_desc:
            return {"error": "route_description requerido"}
        prompt = (f"Genera ruta FastAPI {method} {path}: {route_desc}. "
                  "Incluye Pydantic schema, handler async, manejo de errores. Solo el código.")
        max_tok = 500
    resp = await client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tok, temperature=0.3,
    )
    return {"type": code_type, "code": resp.choices[0].message.content.strip()}


async def _tool_generate_agent_config(args: dict, user_id: str) -> dict:
    purpose = (args.get("agent_purpose") or "").strip()[:300]
    if not purpose:
        return {"error": "agent_purpose requerido"}
    lang = args.get("language", "español")
    client, model = llm_router.get_client("low")
    prompt = (f"Genera config JSON para agente AI en {lang}. Propósito: {purpose}. "
              "Responde SOLO JSON con campos: id (snake_case), name, emoji, tagline (≤80 chars), "
              "system (≤500 chars). Sin texto extra.")
    resp = await client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}],
        max_tokens=300, temperature=0.5,
    )
    raw = resp.choices[0].message.content.strip()
    try:
        m = re.search(r"\{[\s\S]+\}", raw)
        config = json.loads(m.group() if m else raw)
    except Exception:
        return {"error": "No se pudo parsear JSON del agente", "raw": raw}
    tools_override = args.get("tools")
    if tools_override and isinstance(tools_override, list):
        config["tools"] = tools_override
    return await _tool_create_agent(config, user_id)


async def _tool_generate_doc(args: dict, doc_type: str) -> dict:
    client, model = llm_router.get_client("low")
    if doc_type == "proposal":
        project = (args.get("project") or "").strip()[:300]
        client_name = (args.get("client") or "").strip()[:80]
        if not project or not client_name:
            return {"error": "project y client requeridos"}
        budget = args.get("budget_range", "A definir")
        timeline = args.get("timeline", "A definir")
        prompt = (f"Genera propuesta profesional en Markdown para cliente '{client_name}'. "
                  f"Proyecto: {project}. Presupuesto: {budget}. Timeline: {timeline}. "
                  "Incluye: resumen ejecutivo, alcance, entregables, inversión, next steps.")
        max_tok = 800
    else:  # pricing
        product = (args.get("product") or "").strip()[:200]
        model_type = args.get("model", "saas")
        currency = args.get("currency", "USD")
        if not product:
            return {"error": "product requerido"}
        prompt = (f"Genera tabla de precios en Markdown para '{product}' ({model_type}, {currency}). "
                  "Incluye 3 planes con features, precios y CTA. Formato: tabla Markdown clara.")
        max_tok = 500
    llm_client, llm_model = llm_router.get_client("low")
    resp = await llm_client.chat.completions.create(
        model=llm_model, messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tok, temperature=0.4,
    )
    return {"type": doc_type, "content": resp.choices[0].message.content.strip()}


async def _tool_generate_report(args: dict) -> dict:
    import e9_analytics
    report_type = args.get("report_type", "full")
    tenant_id = args.get("tenant_id", "")
    days = max(1, min(int(args.get("days", 30)), 365))
    try:
        return await e9_analytics.tool_report_generator(
            report_type=report_type, tenant_id=tenant_id, period_days=days
        )
    except Exception as e:
        return {"error": f"Error generando reporte: {e}"}


async def _tool_memory_write(args: dict, user_id: str) -> dict:
    db = _db_ref["db"]
    key = re.sub(r"[^a-zA-Z0-9_.-]", "_", (args.get("key") or "").strip())[:80]
    content = (args.get("content") or "").strip()[:4000]
    if not key or not content:
        return {"error": "key y content requeridos"}
    tags = [str(t)[:40] for t in (args.get("tags") or [])[:10]]
    doc = {
        "user_id": user_id, "key": key, "content": content, "tags": tags,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.e1_memories.update_one(
        {"user_id": user_id, "key": key},
        {"$set": doc},
        upsert=True,
    )
    return {"saved": True, "key": key, "tags": tags}


async def _tool_memory_search(args: dict, user_id: str) -> dict:
    db = _db_ref["db"]
    query = (args.get("query") or "").strip()[:200]
    if not query:
        return {"error": "query requerido"}
    limit = max(1, min(int(args.get("limit", 5)), 20))
    q = {"user_id": user_id, "$or": [
        {"key": {"$regex": query, "$options": "i"}},
        {"content": {"$regex": query, "$options": "i"}},
        {"tags": {"$regex": query, "$options": "i"}},
    ]}
    docs = [d async for d in db.e1_memories.find(q, {"_id": 0}).limit(limit)]
    return {"memories": docs, "count": len(docs)}


async def _tool_task_planner(args: dict) -> dict:
    goal = (args.get("goal") or "").strip()[:400]
    if not goal:
        return {"error": "goal requerido"}
    ctx = (args.get("context") or "").strip()[:300]
    max_steps = max(3, min(int(args.get("max_steps", 7)), 15))
    prompt = (f"Descompón el objetivo en ≤{max_steps} pasos accionables con prioridad. "
              f"{'Contexto: ' + ctx + '. ' if ctx else ''}"
              f"Objetivo: {goal}\n"
              "Responde SOLO JSON: {\"steps\": [{\"step\": 1, \"action\": \"...\", \"priority\": \"high/medium/low\"}]}")
    client, model = llm_router.get_client("low")
    resp = await client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}],
        max_tokens=400, temperature=0.3,
    )
    raw = resp.choices[0].message.content.strip()
    try:
        m = re.search(r"\{[\s\S]+\}", raw)
        result = json.loads(m.group() if m else raw)
    except Exception:
        result = {"raw": raw}
    result["goal"] = goal
    return result


async def _tool_summarize_context(args: dict) -> dict:
    text = (args.get("text") or "").strip()[:12000]
    if not text:
        return {"error": "text requerido"}
    fmt = args.get("format", "bullets")
    max_tok = max(50, min(int(args.get("max_tokens", 200)), 500))
    fmt_hint = {"bullets": "lista con viñetas", "paragraph": "párrafo conciso", "outline": "outline numerado"}.get(fmt, "lista")
    prompt = f"Resume en {fmt_hint} (≤{max_tok} tokens): {text}"
    client, model = llm_router.get_client("low")
    resp = await client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tok, temperature=0.2,
    )
    return {"summary": resp.choices[0].message.content.strip(), "format": fmt}


# ── 15 nuevas tools (Master Console + Generadores + Comms + Agents) ─────────

async def _tool_run_python(args: dict) -> dict:
    import master_console as mc
    import asyncio
    code = (args.get("code") or "").strip()
    if not code:
        return {"error": "code requerido"}
    timeout = max(1, min(int(args.get("timeout", 10)), 30))
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, mc._run_python_sandbox, code, timeout)


async def _tool_system_metrics() -> dict:
    import asyncio, master_console as mc
    hw = await asyncio.get_event_loop().run_in_executor(None, _read_local_metrics)
    try:
        snapshot = await mc._live_monitor_snapshot()
    except Exception:
        snapshot = {}
    return {**hw, "platform": snapshot}


async def _tool_get_logs(args: dict) -> dict:
    import asyncio
    target = re.sub(r"[^a-zA-Z0-9_.-]", "", (args.get("target") or "").strip())[:80]
    if not target:
        return {"error": "target requerido"}
    lines = max(10, min(int(args.get("lines", 50)), 500))
    source = args.get("source", "docker")
    if source == "journald":
        cmd = ["journalctl", "-u", target, "-n", str(lines), "--no-pager", "--output=short"]
    else:
        cmd = ["docker", "logs", target, "--tail", str(lines)]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
    except asyncio.TimeoutError:
        proc.kill()
        return {"error": "Timeout obteniendo logs"}
    output = (stdout + stderr).decode("utf-8", errors="replace").strip()
    return {"target": target, "lines": lines, "source": source, "output": output[-6000:]}


async def _tool_list_services(args: dict) -> dict:
    import asyncio
    filt = (args.get("filter") or "").strip()[:40]
    proc = await asyncio.create_subprocess_exec(
        "systemctl", "list-units", "--state=active", "--type=service", "--no-pager",
        "--output=json",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
    except asyncio.TimeoutError:
        return {"error": "Timeout listando servicios"}
    try:
        import json as _json
        services = _json.loads(stdout.decode())
        if filt:
            services = [s for s in services if filt.lower() in (s.get("unit", "") + s.get("description", "")).lower()]
        return {"services": services[:50], "count": len(services)}
    except Exception:
        output = stdout.decode().strip()[:3000]
        if filt:
            output = "\n".join(l for l in output.splitlines() if filt.lower() in l.lower())
        return {"output": output}


def _tool_list_env_vars(args: dict) -> dict:
    import os as _os
    filt = (args.get("filter") or "").strip().lower()
    SECRET_PATTERNS = {"TOKEN", "SECRET", "KEY", "PASSWORD", "PASS", "AUTH", "PRIVATE", "CERT"}
    result = {}
    for k, v in sorted(_os.environ.items()):
        if filt and filt not in k.lower():
            continue
        hidden = any(p in k.upper() for p in SECRET_PATTERNS)
        result[k] = "***HIDDEN***" if hidden else v[:200]
    return {"env_vars": result, "count": len(result)}


async def _tool_generate_changelog(args: dict) -> dict:
    import asyncio
    path = re.sub(r"[^a-zA-Z0-9_./-]", "", (args.get("path") or "/opt/lluvia-studio").strip())
    since = re.sub(r"[^a-zA-Z0-9_.~^-]", "", (args.get("since") or "HEAD~30").strip())[:40]
    lang = args.get("language", "español")
    proc = await asyncio.create_subprocess_exec(
        "git", "log", since + "..HEAD", "--oneline", "--no-merges",
        cwd=path, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
    except asyncio.TimeoutError:
        return {"error": "Timeout leyendo git log"}
    git_log = stdout.decode().strip()[:3000]
    if not git_log:
        return {"error": "Sin commits en el rango especificado"}
    prompt = (f"Genera un CHANGELOG.md profesional en {lang} agrupando por categoría "
              "(Features, Bug Fixes, DevOps, Improvements) desde este git log:\n{git_log}\n"
              "Formato Markdown. Solo el contenido del CHANGELOG.")
    client, model = llm_router.get_client("low")
    resp = await client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}],
        max_tokens=700, temperature=0.3,
    )
    return {"changelog": resp.choices[0].message.content.strip(), "commits_count": len(git_log.splitlines())}


async def _tool_generate_advanced_code(args: dict, code_type: str) -> dict:
    client, model = llm_router.get_client("low")
    if code_type == "backend_module":
        mod = (args.get("module_name") or "").strip()[:60]
        desc = (args.get("description") or "").strip()[:400]
        entities = args.get("entities") or []
        if not mod or not desc:
            return {"error": "module_name y description requeridos"}
        ents_str = ", ".join(str(e) for e in entities[:5])
        prompt = (f"Genera módulo FastAPI completo '{mod}' en Python. Función: {desc}. "
                  f"{'Entidades: ' + ents_str + '. ' if ents_str else ''}"
                  "Incluye: router, modelos Pydantic, endpoints CRUD, create_indexes(). Solo código.")
        max_tok = 1000
    elif code_type == "dashboard":
        title = (args.get("title") or "Dashboard").strip()[:80]
        metrics = args.get("metrics") or ["Usuarios", "Ventas", "Tickets"]
        fw = args.get("framework", "react")
        metrics_str = ", ".join(str(m) for m in metrics[:8])
        prompt = (f"Genera componente {fw} de dashboard '{title}' con métricas: {metrics_str}. "
                  "Incluye cards de stats y gráfica simple (Chart.js o Recharts). Solo código.")
        max_tok = 800
    elif code_type == "mobile_screen":
        screen = (args.get("screen_name") or "Screen").strip()[:60]
        desc = (args.get("description") or "").strip()[:300]
        nav = args.get("navigation", True)
        if not desc:
            return {"error": "description requerido"}
        prompt = (f"Genera screen React Native (Expo) '{screen}': {desc}. "
                  f"{'Con useNavigation hook. ' if nav else ''}"
                  "StyleSheet inline, sin dependencias externas. Solo código.")
        max_tok = 700
    elif code_type == "pitch":
        product = (args.get("product") or "").strip()[:80]
        problem = (args.get("problem") or "").strip()[:300]
        audience = args.get("audience", "inversionistas")
        fmt = args.get("format", "elevator_2min")
        fmt_hints = {
            "elevator_30s": "30 segundos, 3-4 frases",
            "elevator_2min": "2 minutos, estructura: problema/solución/mercado/CTA",
            "deck_outline": "estructura de 10 slides con bullet points",
        }
        if not product or not problem:
            return {"error": "product y problem requeridos"}
        prompt = (f"Genera pitch en español para {audience}. Formato: {fmt_hints.get(fmt, fmt)}. "
                  f"Producto: {product}. Problema: {problem}. Potente y convincente.")
        max_tok = 500
    else:  # sales_copy
        product = (args.get("product") or "").strip()[:100]
        audience = (args.get("audience") or "").strip()[:100]
        fmt = args.get("format", "landing_hero")
        lang = args.get("language", "español")
        fmt_hints = {
            "landing_hero": "headline + subtítulo + 3 beneficios + CTA",
            "email_subject": "5 subject lines A/B con emojis",
            "ad_copy": "copy de anuncio: headline + descripción + CTA (max 90 chars c/u)",
            "product_description": "descripción de producto 100-150 palabras con keywords",
        }
        if not product or not audience:
            return {"error": "product y audience requeridos"}
        prompt = (f"Genera copy en {lang} para '{product}', audiencia: {audience}. "
                  f"Formato: {fmt_hints.get(fmt, fmt)}. Persuasivo y orientado a conversión.")
        max_tok = 400
    resp = await client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tok, temperature=0.5,
    )
    return {"type": code_type, "content": resp.choices[0].message.content.strip()}


async def _tool_send_telegram(args: dict) -> dict:
    import config as cfg, httpx
    if not cfg.TELEGRAM_TOKEN:
        return {"error": "TELEGRAM_TOKEN no configurado"}
    chat_id = str(args.get("chat_id") or "").strip()
    message = (args.get("message") or "").strip()[:4000]
    if not chat_id or not message:
        return {"error": "chat_id y message requeridos"}
    api_url = f"https://api.telegram.org/bot{cfg.TELEGRAM_TOKEN}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(api_url, json={"chat_id": chat_id, "text": message})
            data = r.json()
            return {"sent": data.get("ok", False), "message_id": data.get("result", {}).get("message_id")}
    except Exception as e:
        return {"error": str(e)}


async def _tool_send_webhook(args: dict) -> dict:
    import httpx
    url = (args.get("url") or "").strip()
    if not url or not url.startswith("https://"):
        return {"error": "url debe ser https://"}
    payload = args.get("payload") or {}
    headers = {"Content-Type": "application/json", "User-Agent": "LluviaAppStudio/E1"}
    extra_headers = args.get("headers") or {}
    if isinstance(extra_headers, dict):
        safe_headers = {str(k)[:60]: str(v)[:200] for k, v in list(extra_headers.items())[:10]}
        headers.update(safe_headers)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(url, json=payload, headers=headers)
            return {
                "url": url, "status_code": r.status_code,
                "ok": 200 <= r.status_code < 300,
                "response": r.text[:500],
            }
    except Exception as e:
        return {"error": str(e)}


async def _tool_clone_agent(args: dict, user_id: str) -> dict:
    source_id = (args.get("source_id") or "").strip()
    new_id = re.sub(r"[^a-z0-9_-]", "", (args.get("new_id") or "").lower())[:40]
    new_name = (args.get("new_name") or "").strip()[:40]
    if not source_id or not new_id or not new_name:
        return {"error": "source_id, new_id y new_name requeridos"}
    source = await _get_agent_any(source_id)
    if not source:
        return {"error": f"Agente '{source_id}' no encontrado"}
    clone = dict(source)
    clone.pop("_id", None)
    clone["id"] = new_id
    clone["name"] = new_name
    clone["created_by"] = user_id
    clone["cloned_from"] = source_id
    clone["created_at"] = datetime.now(timezone.utc).isoformat()
    clone.pop("is_custom", None)
    clone["is_custom"] = True
    db = _db_ref["db"]
    if await db.custom_agents.find_one({"id": new_id}, {"_id": 0}):
        return {"error": f"Ya existe agente con id '{new_id}'"}
    if new_id in agents_catalog.AGENTS:
        return {"error": f"'{new_id}' colisiona con built-in"}
    await db.custom_agents.insert_one(clone)
    clone.pop("_id", None)
    return {"cloned": True, "agent": clone}


async def _tool_create_workflow(args: dict, user_id: str) -> dict:
    import job_scheduler as js
    name = (args.get("name") or "").strip()[:120]
    job_type = re.sub(r"[^a-z0-9_]", "_", (args.get("job_type") or "").strip().lower())[:60]
    payload = args.get("payload") or {}
    if not name or not job_type:
        return {"error": "name y job_type requeridos"}
    tenant_id = (args.get("tenant_id") or user_id).strip()
    run_at = (args.get("run_at") or "").strip()[:30]
    enqueue_args = dict(
        job_type=job_type,
        payload={**payload, "_workflow_name": name},
        tenant_id=tenant_id,
        priority=5,
    )
    if run_at:
        enqueue_args["run_after"] = run_at
    result = await js.enqueue_job(**enqueue_args)
    return {**result, "workflow_name": name, "job_type": job_type}


# ── CTO Layer: 12 tools de estabilidad, seguridad y observabilidad ───────────

def _read_local_metrics() -> dict:
    """Lee CPU/RAM/disco desde /proc y df. Sin psutil."""
    import subprocess as _sp
    # RAM desde /proc/meminfo
    try:
        with open("/proc/meminfo") as f:
            lines = f.readlines()
        mem = {}
        for line in lines:
            parts = line.split(":")
            if len(parts) == 2:
                mem[parts[0].strip()] = int(parts[1].strip().split()[0])
        total = mem.get("MemTotal", 0)
        avail = mem.get("MemAvailable", 0)
        ram_pct = round((total - avail) / total * 100, 1) if total else 0
        ram_used_mb = round((total - avail) / 1024)
        ram_total_mb = round(total / 1024)
    except Exception:
        ram_pct, ram_used_mb, ram_total_mb = "?", "?", "?"
    # CPU desde /proc/stat (snapshot puntual)
    try:
        with open("/proc/stat") as f:
            line = f.readline()
        vals = list(map(int, line.split()[1:8]))
        idle = vals[3] + vals[4]  # idle + iowait
        total_cpu = sum(vals)
        cpu_pct = round((1 - idle / total_cpu) * 100, 1) if total_cpu else 0
    except Exception:
        cpu_pct = "?"
    # Disco desde df -h /
    try:
        r = _sp.run(["df", "-h", "/"], capture_output=True, text=True, timeout=3)
        parts = r.stdout.strip().splitlines()[-1].split()
        disk_pct = parts[4] if len(parts) > 4 else "?"
        disk_used = parts[2] if len(parts) > 2 else "?"
        disk_total = parts[1] if len(parts) > 1 else "?"
    except Exception:
        disk_pct, disk_used, disk_total = "?", "?", "?"
    return {
        "cpu_pct": cpu_pct, "ram_pct": ram_pct,
        "ram_used_mb": ram_used_mb, "ram_total_mb": ram_total_mb,
        "disk_pct": disk_pct, "disk_used": disk_used, "disk_total": disk_total,
    }


async def _tool_self_diagnostic() -> dict:
    """Agrega datos del sistema y genera diagnóstico CTO via LLM."""
    import asyncio, master_console as mc
    # Gather en paralelo — tolerante a errores individuales
    hw_metrics = await asyncio.get_event_loop().run_in_executor(None, _read_local_metrics)
    platform_result, queue_result, snapshot_result = await asyncio.gather(
        _tool_get_platform_status({}),
        _tool_queue_monitor(),
        mc._live_monitor_snapshot(),
        return_exceptions=True,
    )
    platform = platform_result if not isinstance(platform_result, Exception) else {}
    queue = queue_result if not isinstance(queue_result, Exception) else {}
    snapshot = snapshot_result if not isinstance(snapshot_result, Exception) else {}

    db = _db_ref["db"]
    recent_failures = [
        d async for d in db.master_console_audit.find(
            {"result_ok": False}, {"_id": 0, "action": 1, "ts": 1}
        ).sort("ts", -1).limit(5)
    ]

    summary = {
        "cpu_pct": hw_metrics.get("cpu_pct"),
        "ram_pct": hw_metrics.get("ram_pct"),
        "disk_pct": hw_metrics.get("disk_pct"),
        "ram_used_mb": hw_metrics.get("ram_used_mb"),
        "ram_total_mb": hw_metrics.get("ram_total_mb"),
        "disk_used": hw_metrics.get("disk_used"),
        "disk_total": hw_metrics.get("disk_total"),
        "jobs": platform.get("jobs", {}),
        "errors_24h": platform.get("errors_24h", 0),
        "active_modules": platform.get("active_modules", []),
        "dlq": queue.get("dlq", 0),
        "worker_running": queue.get("worker", {}).get("running", False),
        "recent_errors": snapshot.get("recent_errors", [])[:3],
        "recent_failures": [f.get("action") for f in recent_failures],
    }
    prompt = (
        "Analiza el estado de producción y genera diagnóstico CTO. "
        f"Datos: {json.dumps(summary, ensure_ascii=False)[:1200]}\n"
        "Responde SOLO JSON: {\"health_score\": 0-100, \"status\": \"healthy|degraded|critical\", "
        "\"critical_issues\": [], \"warnings\": [], \"recommendations\": [], \"summary\": \"...\"}"
    )
    client, model = llm_router.get_client("low")
    resp = await client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}],
        max_tokens=400, temperature=0.2,
    )
    raw = resp.choices[0].message.content.strip()
    try:
        m = re.search(r"\{[\s\S]+\}", raw)
        diagnosis = json.loads(m.group() if m else raw)
    except Exception:
        diagnosis = {"raw": raw}
    diagnosis["raw_data"] = summary
    return diagnosis


async def _tool_smart_rollback(args: dict) -> dict:
    import asyncio
    action = args.get("action", "list")
    path = re.sub(r"[^a-zA-Z0-9_./-]", "", (args.get("path") or "/opt/lluvia-studio").strip())

    async def _git(cmd: list) -> tuple[str, int]:
        p = await asyncio.create_subprocess_exec(
            *cmd, cwd=path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, err = await asyncio.wait_for(p.communicate(), timeout=30)
        return (out + err).decode().strip(), p.returncode

    if action == "list":
        log_out, _ = await _git(["git", "log", "--oneline", "-15"])
        commits = [{"hash": l.split()[0], "msg": " ".join(l.split()[1:])}
                   for l in log_out.splitlines() if l]
        return {"available_checkpoints": commits, "hint": "Usa action=execute con target=<hash> para revertir"}

    # action == "execute"
    target = re.sub(r"[^a-zA-Z0-9_.~^-]", "", (args.get("target") or "").strip())[:40]
    if not target:
        return {"error": "target requerido para action=execute (hash o HEAD~N)"}

    # Safety: crear checkpoint ANTES de rollback
    safety = await _tool_create_checkpoint({"message": f"pre-rollback safety to {target}", "path": path})
    if "error" in safety:
        return {"error": f"No se pudo crear checkpoint de seguridad: {safety['error']}"}
    safety_hash = safety.get("checkpoint", "HEAD@{1}")

    # Ejecutar reset
    reset_out, rc = await _git(["git", "reset", "--hard", target])
    if rc != 0:
        await _git(["git", "reset", "--hard", safety_hash])
        return {"error": f"Rollback falló: {reset_out[:300]}", "reverted_to_safety": safety_hash}

    new_head, _ = await _git(["git", "rev-parse", "--short", "HEAD"])

    # Sincronizar archivos git → container via docker cp
    import os as _os
    backend_src = _os.path.join(path, "backend")
    SYNC_FILES = [
        "console.py", "agents_catalog.py", "llm_router.py", "server.py",
        "e2_infra.py", "e3_builder.py", "e4_email.py", "e4_sales.py",
        "e5_whitelabel.py", "e6_legal.py", "e7_billing.py", "e8_support.py",
        "e9_analytics.py", "e9_emitters.py", "e10_social.py", "e11_gmail_support.py",
        "job_scheduler.py", "master_console.py",
    ]
    synced, failed_sync = [], []
    for fname in SYNC_FILES:
        fpath = _os.path.join(backend_src, fname)
        if not _os.path.exists(fpath):
            continue
        cp_proc = await asyncio.create_subprocess_exec(
            "docker", "cp", fpath, f"lluvia_backend:/app/{fname}",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, _ = await asyncio.wait_for(cp_proc.communicate(), timeout=15)
        (synced if cp_proc.returncode == 0 else failed_sync).append(fname)

    # Reiniciar container (default: lluvia_backend)
    svc = re.sub(r"[^a-zA-Z0-9_.-]", "", (args.get("restart_service") or "lluvia_backend").strip())[:60]
    restart_proc = await asyncio.create_subprocess_exec(
        "docker", "restart", svc,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    await asyncio.wait_for(restart_proc.communicate(), timeout=45)
    restart_ok = restart_proc.returncode == 0

    # Esperar que el backend arranque
    await asyncio.sleep(7)

    # Health check post-rollback
    health = await _tool_service_health_check({})

    return {
        "rolled_back": True,
        "from_safety_checkpoint": safety_hash,
        "new_head": new_head,
        "target": target,
        "synced_files": synced,
        "failed_sync": failed_sync,
        "service_restarted": restart_ok,
        "health_after": health.get("overall"),
        "health_services": {k: v.get("status") for k, v in health.get("services", {}).items()},
        "undo_command": f"smart_rollback(action=execute, target={safety_hash})",
    }


async def _tool_analyze_architecture(args: dict) -> dict:
    import os as _os
    backend_path = "/opt/lluvia-studio/backend"
    modules = []
    for fname in sorted(_os.listdir(backend_path)):
        if not fname.endswith(".py") or fname.startswith("__"):
            continue
        fpath = _os.path.join(backend_path, fname)
        try:
            with open(fpath) as fp:
                lines = fp.readlines()
            imports = [l.strip()[:80] for l in lines if l.startswith(("import ", "from ")) ][:8]
            modules.append({"name": fname, "lines": len(lines), "imports": imports})
        except Exception:
            pass
    modules.sort(key=lambda x: -x["lines"])
    schema = await _tool_get_openapi_schema({})
    routes_count = schema.get("total", "?")
    top = modules[:15]
    context = {
        "top_modules": [{"name": m["name"], "lines": m["lines"]} for m in top],
        "total_modules": len(modules),
        "total_routes": routes_count,
        "focus": args.get("focus", "modules"),
    }
    prompt = (
        "Analiza la arquitectura de este sistema FastAPI/Python. "
        f"Datos: {json.dumps(context, ensure_ascii=False)[:1200]}\n"
        "Identifica: módulos críticos, posibles cuellos de botella, acoplamiento excesivo, oportunidades de mejora. "
        "Responde JSON: {\"key_modules\": [], \"bottlenecks\": [], \"recommendations\": [], \"summary\": \"...\"}"
    )
    client, model = llm_router.get_client("low")
    resp = await client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}],
        max_tokens=500, temperature=0.3,
    )
    raw = resp.choices[0].message.content.strip()
    try:
        m = re.search(r"\{[\s\S]+\}", raw)
        result = json.loads(m.group() if m else raw)
    except Exception:
        result = {"raw": raw}
    result["modules_overview"] = context["top_modules"]
    result["total_modules"] = len(modules)
    result["total_routes"] = routes_count
    return result


async def _tool_auto_fix_build(args: dict, user_id: str) -> dict:
    import subprocess, os as _os
    app_slug = re.sub(r"[^a-zA-Z0-9_.-]", "", (args.get("app_slug") or "").strip())[:80]
    file_arg = (args.get("file_path") or "").strip()

    if app_slug:
        base = _os.environ.get("LLUVIA_HOME", "/app")
        scan_path = _os.path.join(base, "user_apps", user_id, app_slug)
    else:
        scan_path = "/opt/lluvia-studio/backend"

    if not _os.path.isdir(scan_path):
        return {"error": f"Path no encontrado: {scan_path}"}

    files_to_check = []
    if file_arg:
        files_to_check = [_os.path.join(scan_path, file_arg)]
    else:
        files_to_check = [_os.path.join(scan_path, f)
                          for f in _os.listdir(scan_path) if f.endswith(".py")][:30]

    errors = []
    for fpath in files_to_check:
        r = subprocess.run(
            ["python3", "-m", "py_compile", fpath],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0:
            errors.append({"file": _os.path.basename(fpath), "error": r.stderr.strip()[:400]})

    if not errors:
        return {"status": "no_errors_found", "files_checked": len(files_to_check)}

    # Proponer fix via LLM (sin auto-aplicar)
    proposals = []
    client, model = llm_router.get_client("low")
    for err in errors[:3]:
        fpath_full = _os.path.join(scan_path, err["file"])
        try:
            with open(fpath_full) as fp:
                content = fp.read()[:2000]
        except Exception:
            content = ""
        prompt = (
            f"Archivo Python con error:\n{err['file']}\nError: {err['error']}\n"
            f"Código:\n{content}\n\n"
            "Propón el fix mínimo. Responde SOLO JSON: "
            "{\"fix_description\": \"...\", \"search\": \"línea exacta a reemplazar\", \"replace\": \"línea corregida\"}"
        )
        resp = await client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": prompt}],
            max_tokens=250, temperature=0.1,
        )
        raw = resp.choices[0].message.content.strip()
        try:
            m = re.search(r"\{[\s\S]+\}", raw)
            proposal = json.loads(m.group() if m else raw)
        except Exception:
            proposal = {"raw": raw}
        proposal["file"] = err["file"]
        proposals.append(proposal)

    return {
        "errors_found": len(errors),
        "errors": errors,
        "proposals": proposals,
        "apply_hint": "Usar search_replace_workspace para aplicar el fix propuesto.",
    }


async def _tool_dependency_audit(args: dict) -> dict:
    import asyncio, json as _json
    target = args.get("target", "both")
    results: dict = {}

    if target in ("python", "both"):
        proc = await asyncio.create_subprocess_exec(
            "pip3", "list", "--outdated", "--format=json",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            outdated = _json.loads(stdout.decode())[:20]
        except Exception:
            outdated = []
        results["python"] = {"outdated_packages": outdated, "count": len(outdated)}

    if target in ("frontend", "both"):
        proc = await asyncio.create_subprocess_exec(
            "npm", "audit", "--json",
            cwd="/opt/lluvia-studio/frontend",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
            data = _json.loads(stdout.decode())
            results["frontend"] = {
                "vulnerabilities": data.get("metadata", {}).get("vulnerabilities", {}),
                "packages_affected": list(data.get("vulnerabilities", {}).keys())[:15],
            }
        except Exception as e:
            results["frontend"] = {"error": str(e)[:100]}

    return results


async def _tool_security_scan_basic(args: dict) -> dict:
    import os as _os
    scope = args.get("scope", "all")
    issues: list = []
    SECRET_KEYS = {"TOKEN", "SECRET", "KEY", "PASSWORD", "PASSWD", "AUTH", "PRIVATE", "CERT", "CREDENTIAL"}
    SKIP = {"config.py"}  # config.py usa os.getenv, no hardcoded

    if scope in ("secrets", "all"):
        backend_path = "/opt/lluvia-studio/backend"
        pattern = re.compile(r'(?i)(password|secret|api_key|apikey|token|private_key)\s*=\s*["\'][^${\'"]{8,}["\']')
        for fname in _os.listdir(backend_path):
            if not fname.endswith(".py") or fname in SKIP:
                continue
            try:
                with open(_os.path.join(backend_path, fname)) as fp:
                    content = fp.read()
                if pattern.search(content):
                    issues.append({"type": "potential_hardcoded_secret", "file": fname, "severity": "high"})
            except Exception:
                pass

    if scope in ("permissions", "all"):
        for env_path in ["/opt/lluvia-studio/.env", "/app/.env", "/opt/lluvia/.env"]:
            if _os.path.exists(env_path):
                perms = oct(_os.stat(env_path).st_mode)[-3:]
                if perms not in ("600", "400"):
                    issues.append({"type": "insecure_file_permissions", "file": env_path,
                                   "perms": perms, "recommended": "600", "severity": "medium"})

    open_ports: list = []
    if scope in ("ports", "all"):
        import asyncio
        try:
            proc = await asyncio.create_subprocess_exec(
                "ss", "-tlnp",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            ports = re.findall(r":(\d{3,5})\s", stdout.decode())
            open_ports = sorted(set(ports))
            db_ports = [p for p in open_ports if p in {"3306", "5432", "27017", "6379", "9200"}]
            if db_ports:
                issues.append({"type": "exposed_db_ports", "ports": db_ports, "severity": "high",
                                "note": "Verificar que no estén expuestos públicamente"})
        except Exception:
            pass

    issues.sort(key=lambda x: {"high": 0, "medium": 1, "low": 2}.get(x.get("severity", "low"), 2))
    return {
        "issues": issues,
        "total": len(issues),
        "high_severity": sum(1 for i in issues if i.get("severity") == "high"),
        "open_ports": open_ports,
        "clean": len(issues) == 0,
    }


async def _tool_audit_log_search(args: dict) -> dict:
    db = _db_ref["db"]
    q: dict = {}
    action = (args.get("action") or "").strip()[:60]
    since = (args.get("since") or "").strip()[:30]
    limit = max(1, min(int(args.get("limit", 20)), 100))
    if action:
        q["action"] = {"$regex": action, "$options": "i"}
    if since:
        q["ts"] = {"$gte": since}
    entries = [d async for d in db.master_console_audit.find(q, {"_id": 0}).sort("ts", -1).limit(limit)]
    return {"entries": entries, "count": len(entries)}


async def _tool_service_health_check(args: dict) -> dict:
    import httpx, asyncio
    SERVICES = [
        ("backend_8000", "http://localhost:8000/health"),
        ("backend_8001", "http://localhost:8001/health"),
    ]
    for extra in (args.get("urls") or [])[:5]:
        SERVICES.append((extra, extra))

    async def _http_check(name: str, url: str) -> tuple[str, dict]:
        try:
            async with httpx.AsyncClient(timeout=4) as c:
                r = await c.get(url)
                return name, {"status": "up", "code": r.status_code,
                               "latency_ms": round(r.elapsed.total_seconds() * 1000, 1)}
        except Exception as e:
            return name, {"status": "down", "error": str(e)[:80]}

    checks = await asyncio.gather(*[_http_check(n, u) for n, u in SERVICES], return_exceptions=True)
    results: dict = {}
    for item in checks:
        if isinstance(item, tuple):
            results[item[0]] = item[1]

    # MongoDB
    try:
        await _db_ref["db"].command("ping")
        results["mongodb"] = {"status": "up"}
    except Exception as e:
        results["mongodb"] = {"status": "down", "error": str(e)[:80]}

    # Job worker
    try:
        import job_scheduler as js
        ws = js._worker.status() if hasattr(js, "_worker") else {}
        results["job_worker"] = {"status": "up" if ws.get("running") else "idle", **ws}
    except Exception:
        results["job_worker"] = {"status": "unknown"}

    up = sum(1 for v in results.values() if isinstance(v, dict) and v.get("status") in ("up", "idle"))
    total = len(results)
    return {
        "services": results, "healthy": up, "total": total,
        "overall": "healthy" if up >= total - 1 else ("degraded" if up > 0 else "critical"),
    }


async def _tool_queue_monitor() -> dict:
    import job_scheduler as js
    db = _db_ref["db"]
    rows = [d async for d in db.jobs.aggregate([
        {"$group": {"_id": {"status": "$status", "type": "$job_type"}, "count": {"$sum": 1}}}
    ])]
    stats: dict = {}
    for r in rows:
        stats.setdefault(r["_id"]["status"], {})[r["_id"]["type"]] = r["count"]
    dlq = await db.jobs.count_documents({"status": "dead_letter"})
    running = [d async for d in db.jobs.find(
        {"status": "running"}, {"_id": 0, "id": 1, "job_type": 1, "started_at": 1}
    ).limit(10)]
    worker = js._worker.status() if hasattr(js, "_worker") else {}
    return {
        "stats": stats, "dlq": dlq, "running": running, "worker": worker,
        "alert": dlq > 10 or not worker.get("running"),
    }


async def _tool_git_diff_summary(args: dict) -> dict:
    import asyncio
    path = re.sub(r"[^a-zA-Z0-9_./-]", "", (args.get("path") or "/opt/lluvia-studio").strip())
    staged = bool(args.get("staged", False))

    async def _git(cmd: list) -> str:
        p = await asyncio.create_subprocess_exec(
            *cmd, cwd=path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await asyncio.wait_for(p.communicate(), timeout=10)
        return out.decode().strip()

    stat = await _git(["git", "diff"] + (["--staged"] if staged else []) + ["--stat"])
    if not stat:
        return {"summary": "No hay cambios pendientes", "files": [], "staged": staged}

    diff_text = await _git(["git", "diff"] + (["--staged"] if staged else []) + ["--unified=2"])
    prompt = (f"Resume estos cambios git en ≤5 bullets concisos:\n{diff_text[:2000]}\n"
              "Solo lo que cambió y por qué importa.")
    client, model = llm_router.get_client("low")
    resp = await client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}],
        max_tokens=150, temperature=0.3,
    )
    files = [l.split("|")[0].strip() for l in stat.splitlines() if "|" in l]
    return {
        "summary": resp.choices[0].message.content.strip(),
        "files_changed": files,
        "stats": stat[-400:],
        "staged": staged,
    }


async def _tool_process_manager(args: dict) -> dict:
    import asyncio
    action = args.get("action", "list")
    if action == "list":
        proc = await asyncio.create_subprocess_exec(
            "ps", "aux", "--sort=-%cpu",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        lines = stdout.decode().strip().splitlines()
        processes = []
        for line in lines[1:26]:
            parts = line.split()
            if len(parts) >= 11:
                processes.append({
                    "pid": parts[1], "cpu": parts[2], "mem": parts[3],
                    "cmd": " ".join(parts[10:])[:80],
                })
        return {"processes": processes, "count": len(processes)}
    elif action == "kill":
        pid = str(args.get("pid", "")).strip()
        if not pid.isdigit() or pid in ("0", "1"):
            return {"error": "pid inválido o protegido"}
        proc = await asyncio.create_subprocess_exec(
            "kill", "-15", pid,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
        return {"killed": proc.returncode == 0, "pid": pid,
                "error": stderr.decode().strip()[:100] or None}
    return {"error": f"action debe ser list o kill"}


def _tool_inspect_config(args: dict) -> dict:
    import os as _os, re as _re
    filt = (args.get("filter") or "").strip().lower()
    SECRET_KEYS = {"TOKEN", "SECRET", "KEY", "PASSWORD", "PASSWD", "PRIVATE", "AUTH", "CERT"}
    config_path = "/opt/lluvia-studio/backend/config.py"
    try:
        with open(config_path) as fp:
            content = fp.read()
    except Exception as e:
        return {"error": str(e)}
    # Extract all os.environ.get("VAR_NAME", ...) patterns
    pattern = _re.compile(r'os\.environ\.get\(\s*["\']([A-Z0-9_]+)["\']\s*(?:,\s*([^)]+))?\)')
    matches = pattern.findall(content)
    result = []
    for var_name, default in matches:
        if filt and filt not in var_name.lower():
            continue
        is_secret = any(k in var_name for k in SECRET_KEYS)
        is_set = var_name in _os.environ
        has_default = bool(default.strip()) if default else False
        result.append({
            "var": var_name,
            "set": is_set,
            "has_default": has_default,
            "value": "***HIDDEN***" if is_secret else (_os.environ.get(var_name, "(not set)")[:80]),
            "required": not has_default,
        })
    missing_required = [r["var"] for r in result if not r["set"] and r["required"]]
    return {
        "config_vars": result,
        "total": len(result),
        "set_count": sum(1 for r in result if r["set"]),
        "missing_required": missing_required,
        "alert": len(missing_required) > 0,
    }


# ── Dynamic tool selector (token optimization for Llama 3.1 8B) ──────────────

_TOOL_BUNDLES: dict[str, set[str]] = {
    "devops":    {"shell_run", "list_my_vps", "run_vps_command", "deploy_app_to_vps",
                  "tail_vps_logs", "restart_vps_service", "create_checkpoint",
                  "docker_exec", "run_tests", "list_containers", "get_platform_status",
                  "list_jobs", "get_logs", "list_services", "system_metrics",
                  "create_workflow"},
    "workspace": {"list_workspace_files", "read_workspace_file", "write_workspace_file",
                  "search_replace_workspace", "search_codebase"},
    "github":    {"github_list_repos", "github_list_files", "github_read_file",
                  "github_search_code", "push_to_my_github", "generate_changelog"},
    "agents":    {"create_agent", "update_agent", "delete_agent", "list_agents",
                  "generate_agent_config", "clone_agent"},
    "business":  {"book_appointment", "check_availability", "list_appointments",
                  "cancel_appointment", "paypal_invoice_card", "service_card",
                  "provision_client_quick"},
    "comms":     {"send_notification", "send_quick_email", "send_telegram", "send_webhook"},
    "builder":   {"generate_social_post", "generate_qr_card", "generate_landing_page",
                  "create_intake_form", "generate_haircut_preview", "generate_promo_video",
                  "generate_audio_room_app", "generate_tiktok_app", "video_script_card",
                  "generate_component", "generate_crud", "generate_api_route",
                  "generate_backend_module", "generate_dashboard", "generate_mobile_screen"},
    "analytics": {"get_platform_status", "list_jobs", "get_agent_stats",
                  "inspect_database", "benchmark_endpoint", "get_openapi_schema",
                  "generate_report", "system_metrics"},
    "business2": {"generate_proposal", "generate_pricing", "crm_lookup", "track_lead",
                  "generate_pitch", "generate_sales_copy"},
    "memory":    {"memory_write", "memory_search", "task_planner", "summarize_context"},
    "master":    {"run_python", "system_metrics", "get_logs", "list_services",
                  "list_env_vars", "inspect_database"},
    "cto":       {"self_diagnostic", "smart_rollback", "analyze_architecture",
                  "auto_fix_build", "dependency_audit", "security_scan_basic",
                  "audit_log_search", "service_health_check", "queue_monitor",
                  "git_diff_summary", "process_manager", "inspect_config",
                  "get_platform_status"},
}

_BUNDLE_KEYWORDS: dict[str, list[str]] = {
    "devops":    ["deploy", "server", "docker", "vps", "ssh", "restart", "service",
                  "logs", "container", "checkpoint", "test", "migration", "git",
                  "workflow", "cron", "queue", "job"],
    "workspace": ["archivo", "file", "código", "code", "edita", "write", "read",
                  "search_code", "grep", "workspace"],
    "github":    ["github", "repo", "push", "repository", "branch", "changelog", "commit"],
    "agents":    ["agente", "agent", "crear agente", "delete agent", "list agent",
                  "clonar", "clone"],
    "business":  ["cita", "appointment", "reserva", "disponibilidad", "pago",
                  "factura", "invoice", "cliente", "provision"],
    "comms":     ["notif", "notify", "email", "correo", "aviso", "mensaje",
                  "telegram", "webhook", "whatsapp"],
    "builder":   ["genera", "generate", "landing", "social", "post", "qr",
                  "formulario", "form", "video", "app", "component", "crud",
                  "dashboard", "mobile", "screen", "módulo", "module"],
    "analytics": ["status", "jobs", "stats", "métricas", "platform", "dashboard",
                  "benchmark", "openapi", "schema", "report", "reporte", "metrics"],
    "business2": ["propuesta", "proposal", "precio", "pricing", "lead", "crm",
                  "contacto", "campaign", "pitch", "ventas", "copy", "marketing"],
    "memory":    ["recuerda", "memory", "tarea", "task", "plan", "resume",
                  "resumen", "compress", "contexto"],
    "master":    ["python", "sandbox", "ejecuta", "run", "monitor", "cpu", "ram",
                  "disco", "disk", "env", "environment", "proceso", "process"],
    "cto":       ["diagnós", "diagnostic", "salud", "health", "rollback", "revert",
                  "arquitectura", "architecture", "vulnerabilidad", "security", "audit",
                  "error de build", "import error", "fix build", "queue dlq", "diff",
                  "proceso", "process", "config", "scan", "seguridad", "dependencia"],
}

_ALWAYS_ON = {"call_specialist_tool", "web_search", "web_browse", "list_agents"}
_MAX_TOOLS_PER_REQUEST = 15


def _select_tools_for_message(message: str, filtered_tools: list) -> list:
    """Selecciona ≤MAX_TOOLS herramientas relevantes al mensaje. Token-efficient para Llama 8B."""
    msg_lower = message.lower()
    selected: set[str] = set(_ALWAYS_ON)
    pinned: set[str] = set()  # tools mencionadas por nombre → nunca se recortan
    for bundle, keywords in _BUNDLE_KEYWORDS.items():
        if any(kw in msg_lower for kw in keywords):
            selected |= _TOOL_BUNDLES.get(bundle, set())
    # Si el mensaje menciona un tool por nombre, incluirlo y fijarlo para que no sea recortado
    for t in filtered_tools:
        name = t["function"]["name"]
        if name in msg_lower or name.replace("_", " ") in msg_lower:
            selected.add(name)
            pinned.add(name)
    allowed_names = {t["function"]["name"] for t in filtered_tools}
    selected &= allowed_names
    result = [t for t in filtered_tools if t["function"]["name"] in selected]
    if len(result) < 5:
        result = filtered_tools[:_MAX_TOOLS_PER_REQUEST]
    elif len(result) > _MAX_TOOLS_PER_REQUEST:
        always = [t for t in result if t["function"]["name"] in _ALWAYS_ON or t["function"]["name"] in pinned]
        rest = [t for t in result if t["function"]["name"] not in _ALWAYS_ON and t["function"]["name"] not in pinned]
        result = (always + rest)[:_MAX_TOOLS_PER_REQUEST]
    return result


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
    # Token optimization: selecciona ≤20 tools relevantes al mensaje para Llama 3.1 8B
    if tools is not None:
        tools = _select_tools_for_message(data.text, tools)
    tool_calls_made = []
    extra_cost = 0

    if not llm_router.llm_available():
        raise HTTPException(status_code=503, detail="Motor IA no configurado en backend")

    client, _console_model = llm_router.get_console_client()

    # 3. Loop de tool calling (max 5 vueltas)
    final_text = ""
    for _ in range(5):
        try:
            resp = await client.chat.completions.create(
                model=_console_model,
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
            # cobrar el coste de la tool (si falla, abortamos); admin está exento
            if cost > 0 and not is_admin:
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

    # 4. Persistir mensajes. Para admin (admin_free) el cost real es 0
    # aunque internamente sumemos para que las metricas funcionen.
    nominal_cost = agents_catalog.COST_CHAT_MESSAGE + extra_cost + vision_cost
    real_cost = 0 if is_admin else nominal_cost
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
        "cost_oros": real_cost,
        "is_admin_free": is_admin,
        "nominal_cost_oros": nominal_cost,
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
        "cost_oros": real_cost,
        "balance": new_balance,
    }
