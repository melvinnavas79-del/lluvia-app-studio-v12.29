"""
========================================
SERVIDOR FASTAPI - BOT MULTIPLATAFORMA
========================================

Webhooks para Telegram, WhatsApp e Instagram.
Endpoint /api/command para uso directo.
Auth JWT propia + Modo Afiliado.

NOTA INFRAESTRUCTURA:
- Este servicio corre en el puerto 8001 (gestionado por supervisor).
- Externamente accesible via la URL publica configurada con prefijo /api.
"""

import logging
import os
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

from fastapi import FastAPI, APIRouter, Request, HTTPException
from fastapi.responses import PlainTextResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient

import config
import auth as auth_module
import affiliates as affiliates_module
import branding as branding_module
from agent import process_command
from actions import apps as ap
from actions import affiliate_stats as affiliate_stats_module
from actions import admin_link as admin_link_module
import memory
import telegram_poller
import telegram_unified
import telegram_unified as telegram_unified_module
import credits as credits_module
import console as console_module
import paypal_integration
import voice as voice_module
import agent_builder
import agency_view
import promos as promos_module
import proposals as proposals_module
import call_center as call_center_module
import super_admin as super_admin_module
import appointments as appointments_module
import public_chat as public_chat_module
import user_workspace as user_workspace_module
import legal as legal_module
import gmail_integration as gmail_module
import gmail_maestro as gmail_maestro_module
import gmail_scheduler as gmail_scheduler_module
import site_content as site_content_module
import video_gen as video_gen_module
import vps_manager as vps_manager_module
import workspace_files as workspace_files_module
import workspace_preview as workspace_preview_module
import ws_streams as ws_streams_module
from rate_limit import limiter, rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware


# ----------------------- LOGGING -----------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("bot")


# ----------------------- DB -----------------------
mongo_client = AsyncIOMotorClient(config.MONGO_URL)
db = mongo_client[config.DB_NAME]
auth_module.set_db(db)
affiliates_module.set_db(db)
branding_module.set_db(db)
affiliate_stats_module.set_db(db)
admin_link_module.set_db(db)
credits_module.set_db(db)
console_module.set_db(db)
paypal_integration.set_db(db)
agent_builder.set_db(db)
agency_view.set_db(db)
promos_module.set_db(db)
proposals_module.set_db(db)
telegram_unified.set_db(db)
call_center_module.set_db(db)
super_admin_module.set_db(db)
appointments_module.set_db(db)
public_chat_module.set_db(db)
user_workspace_module.set_db(db)
gmail_module.set_db(db)
gmail_maestro_module.set_db(db)
gmail_scheduler_module.set_db(db)
site_content_module.set_db(db)
video_gen_module.set_db(db)
vps_manager_module.set_db(db)
workspace_files_module.set_db(db)
workspace_preview_module.set_db(db)
ws_streams_module.set_db(db)


# ----------------------- APP -----------------------
app = FastAPI(title="Bot Multiplataforma", version="1.1.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# Observabilidad: JSON logs + X-Request-ID middleware (nivel módulo, antes del startup)
import observability as _obs_boot
_obs_boot.add_middleware(app)

api_router = APIRouter(prefix="/api")


# ============================================================
# STARTUP: indices + seed admin
# ============================================================
@app.on_event("startup")
async def on_startup():
    await db.users.create_index("email", unique=True)
    await db.users.create_index("id", unique=True)
    await db.users.create_index("affiliate_code")
    await db.sales.create_index("id", unique=True)
    await db.sales.create_index("affiliate_id")
    await db.sales.create_index("created_at")
    await auth_module.seed_admin(db)
    logger.info("Startup OK: indices creados, admin seeded")

    # Observabilidad: inyecta db ref (middleware ya está activo desde nivel módulo)
    import observability as obs_module
    obs_module.set_db(db)

    # Telegram long polling (alternativa a webhook). Activar con TELEGRAM_POLLING=1
    if os.environ.get("TELEGRAM_POLLING", "0") == "1" and config.TELEGRAM_TOKEN:
        telegram_poller.start()
        logger.info("Telegram polling activado")

    # Gmail Maestro autopoll (cada 5 min). Activar con GMAIL_MAESTRO_AUTOPOLL=1
    gmail_scheduler_module.start_scheduler()

    # Job Scheduler — motor central de jobs/eventos/tareas
    await job_scheduler_module.create_indexes()
    job_scheduler_module.start_worker()

    # E9 Emitters — indexes para nuevas colecciones de instrumentación
    await e9_emitters_module.create_indexes()

    # E8 SLA Monitor — chequea breaches cada 5 min
    e8_module.start_sla_monitor()

    # E4 Email — indexes de log, supresiones, rate limits
    await e4_email_module.create_indexes()

    # E7 Billing — indexes de suscripciones, pagos, webhook dedup
    await e7_module.create_indexes()

    # Master Console — indexes del audit trail
    await master_console_module.create_indexes()

    # E10 Social — indexes de posts, campañas, conexiones OAuth, quotas
    await e10_module.create_indexes()

    # E3 Builder — indexes de templates, apps generadas, agent configs, quotas AI
    await e3_module.create_indexes()


@app.on_event("shutdown")
async def on_shutdown():
    gmail_scheduler_module.stop_scheduler()
    await job_scheduler_module.stop_worker()  # await: tasks finish their CancelledError cleanup
    e8_module.stop_sla_monitor()


# ============================================================
# RUTAS BASICAS
# ============================================================
@api_router.get("/")
async def root():
    return {
        "service": "Bot Multiplataforma",
        "status": "running",
        "platforms": ["whatsapp", "telegram", "instagram"],
        "version": "1.1.0",
    }


@api_router.get("/status")
async def status():
    return {
        "ok": True,
        "credentials": config.credentials_status(),
        "memory": memory.stats(),
        "generated_apps": ap.list_apps(),
    }


# ============================================================
# COMANDO DIRECTO (testing manual)
# ============================================================
@api_router.post("/command")
async def command_endpoint(data: dict):
    message = data.get("message") or data.get("text") or ""
    user = str(data.get("user", "default"))
    if not message:
        raise HTTPException(status_code=400, detail="message es obligatorio")
    response = await process_command(message, user)
    return {"response": response, "user": user}


# ============================================================
# DESCARGA DEL PAQUETE DE DESPLIEGUE (lluvia-deploy.tar.gz)
# Force-download para que ningun SPA / cache lo intercepte.
# ============================================================
_DEPLOY_PATH = Path("/app/frontend/public/lluvia-deploy.tar.gz")


@api_router.api_route("/download/lluvia-deploy", methods=["GET", "HEAD"])
async def download_deploy():
    if not _DEPLOY_PATH.exists():
        raise HTTPException(status_code=404, detail="Paquete no disponible")
    return FileResponse(
        path=str(_DEPLOY_PATH),
        media_type="application/gzip",
        filename="lluvia-deploy.tar.gz",
        headers={
            "Content-Disposition": 'attachment; filename="lluvia-deploy.tar.gz"',
            "Cache-Control": "no-store",
        },
    )


# Alias con version en el path para forzar bypass de cualquier CDN cache
@api_router.api_route("/download/lluvia-deploy-v3.tar.gz", methods=["GET", "HEAD"])
async def download_deploy_v3():
    return await download_deploy()


@api_router.api_route("/download/lluvia-deploy/info", methods=["GET", "HEAD"])
async def download_info():
    import hashlib
    if not _DEPLOY_PATH.exists():
        raise HTTPException(status_code=404, detail="Paquete no disponible")
    sha = hashlib.sha256(_DEPLOY_PATH.read_bytes()).hexdigest()
    return {
        "filename": "lluvia-deploy.tar.gz",
        "size_bytes": _DEPLOY_PATH.stat().st_size,
        "sha256": sha,
        "version": "v11-superadmin-richcards-appointments",
        "fixes": [
            "v11: SuperAdmin Console - overview cross-tenant, takeover de cualquier sesion, control total",
            "v11: Appointments reales - book/check/list/cancel en MongoDB, validacion fechas, anti-solapamiento",
            "v11: Rich Cards PayPal - tarjetas visuales con boton 'Pagar', genera orden LIVE real",
            "v11: Service Cards - tarjetas de servicio/producto con imagen, precio, CTA",
            "v11: Push & Backup directo a GitHub desde panel - solo SuperAdmin",
            "v11: Marca blanca enterprise - avatares circulares, eliminados emojis grandes, colores dinamicos",
            "v11: Fix critico fecha actual - LLM ya no inventa 2023, recibe contexto temporal real del servidor",
            "v11: Fix create_session acepta agentes custom (no solo built-in)",
            "v11: Arquitecto refortalecido - crea agentes con tools de citas+pagos automaticamente",
            "v11: Tarball incluye docker-compose.yml master + Dockerfiles + quickstart-master.sh",
            "v10: Telegram bot unificado (/agente, /agente_<id>, /saldo, /recargar) — un solo bot para los 8 agentes",
            "v10: App Builder profesional — apps multi-pagina (Inicio/Popular/Explorar/Crear/Notif/Perfil/Detalle) estilo TikTok/Bigo",
            "v10: Call Center Mode — loop voz->texto->agente->TTS, endpoint /api/voice/call-center/turn",
            "v10: Sistema de Propuestas — agentes proponen cambios, admin aprueba con 1 click",
            "v10: Promos automaticas — descuento por dia de semana / dia del mes aplicado a packs PayPal",
            "v10: Branding extendido — fondo, texto, logo, product_name, tagline, theme",
            "v10: Blindaje seguridad — rate limiting (slowapi), validacion webhook PayPal HMAC, JWT/admin gates",
            "v10: Licencia propietaria + documentacion de migracion incluida (LICENSE, MIGRATION.md, SECURITY.md)",
            "v10: FIX voice.transcribe — _client() ahora se instancia correctamente",
            "v9: 7 agentes especializados (Sexologo/Psicologo/Contador/DevOps/App Builder/Vendedor/Arquitecto)",
            "v9: Voz - Whisper (audio in) + OpenAI TTS (voces por agente)",
            "v9: PayPal Checkout integrado (Starter/Growth/Scale)",
            "v9: Agency View con MRR estimado y lista de clientes",
            "v9: Arquitecto Maestro UI - crea/edita agentes custom desde panel",
            "v9: Boss Console rediseñado con mic, shop, play TTS por mensaje",
            "v7.1: FIX docker-compose.yml.tmpl 100% interpolado via sed (placeholders __SLUG__/__PUBLIC_URL__)",
            "v7.1: setup-cliente.sh con sanity check post-render que aborta si quedan placeholders",
            "v7: Boss Console multi-agente (Constructor/Vendedor/Psicologo/Ingeniero/Estratega)",
            "v7: Sistema de creditos 'oros' con descuento por tarea (chat=1, tools=2-50)",
            "v7: UI tipo Emergent: sidebar de hilos + chat + badge de oros",
            "v7: Healthchecks en backend (15s), frontend (30s), mongo (15s) + restart=always",
            "v7: depends_on con condition=service_healthy para alta disponibilidad",
            "v3.1: telegram_poller usa asyncio.to_thread() - NO bloquea event loop",
            "v3: api.js sanitiza REACT_APP_BACKEND_URL",
            "v3: MONGO_URL=mongodb://mongo:27017 por defecto",
            "v3: TELEGRAM_POLLING=1 -> bot funciona sin SSL/dominio",
            "v2: Dockerfile pineado a python:3.11.10-slim-bookworm (NO Trixie)",
            "v2: requirements-prod.txt minimo (13 paquetes vs 123)",
        ],
    }


# ============================================================
# WHATSAPP
# ============================================================
@api_router.get("/webhook/whatsapp")
async def whatsapp_verify(request: Request):
    params = request.query_params
    if params.get("hub.verify_token") == config.VERIFY_TOKEN:
        return PlainTextResponse(content=str(params.get("hub.challenge", "")))
    raise HTTPException(status_code=403, detail="verify token invalido")


@api_router.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request):
    data = await request.json()
    try:
        msg = data["entry"][0]["changes"][0]["value"]["messages"][0]
        text = msg["text"]["body"]
        user = msg["from"]
        reply = await process_command(text, user)
        send_whatsapp(user, reply)
    except (KeyError, IndexError, TypeError) as e:
        logger.warning(f"WhatsApp webhook sin mensaje procesable: {e}")
    except Exception as e:
        logger.exception(f"Error procesando webhook WhatsApp: {e}")
    return {"ok": True}


def send_whatsapp(to: str, msg: str) -> None:
    if not config.WHATSAPP_TOKEN:
        logger.info(f"[WhatsApp simulado] to={to} msg={msg[:80]}")
        return
    url = f"https://graph.facebook.com/v18.0/{config.PHONE_ID}/messages"
    headers = {"Authorization": f"Bearer {config.WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    payload = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": msg[:4000]}}
    try:
        requests.post(url, headers=headers, json=payload, timeout=10)
    except Exception as e:
        logger.error(f"Error enviando WhatsApp: {e}")


# ============================================================
# TELEGRAM
# ============================================================
@api_router.post("/webhook/telegram/{token}")
async def telegram_webhook(token: str, request: Request):
    if not config.is_valid_telegram_token(token):
        raise HTTPException(status_code=403, detail="Telegram token invalido")
    data = await request.json()
    try:
        text = data["message"]["text"]
        chat_id = data["message"]["chat"]["id"]
        reply = await process_command(text, str(chat_id))
        send_telegram(chat_id, reply, token=token)
    except (KeyError, TypeError) as e:
        logger.warning(f"Telegram webhook sin mensaje procesable: {e}")
    except Exception as e:
        logger.exception(f"Error procesando webhook Telegram: {e}")
    return {"ok": True}


def send_telegram(chat_id, msg: str, token: Optional[str] = None) -> None:
    """Envia mensaje usando el token que recibio el update (multi-bot).
    Si token es None, usa el TELEGRAM_TOKEN principal (compat. con codigo legacy)."""
    use_token = token or config.TELEGRAM_TOKEN
    if not use_token:
        logger.info(f"[Telegram simulado] chat_id={chat_id} msg={msg[:80]}")
        return
    url = f"https://api.telegram.org/bot{use_token}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": msg[:4000]}, timeout=10)
    except Exception as e:
        logger.error(f"Error enviando Telegram: {e}")


# ============================================================
# INSTAGRAM
# ============================================================
@api_router.get("/webhook/instagram")
async def instagram_verify(request: Request):
    params = request.query_params
    if params.get("hub.verify_token") == config.VERIFY_TOKEN:
        return PlainTextResponse(content=str(params.get("hub.challenge", "")))
    raise HTTPException(status_code=403, detail="verify token invalido")


@api_router.post("/webhook/instagram")
async def instagram_webhook(request: Request):
    data = await request.json()
    try:
        entry = data["entry"][0]["messaging"][0]
        sender = entry["sender"]["id"]
        text = entry["message"]["text"]
        reply = await process_command(text, sender)
        send_instagram(sender, reply)
    except (KeyError, IndexError, TypeError) as e:
        logger.warning(f"Instagram webhook sin mensaje procesable: {e}")
    except Exception as e:
        logger.exception(f"Error procesando webhook Instagram: {e}")
    return {"ok": True}


def send_instagram(user_id: str, msg: str) -> None:
    if not config.INSTAGRAM_TOKEN:
        logger.info(f"[Instagram simulado] user_id={user_id} msg={msg[:80]}")
        return
    url = f"https://graph.facebook.com/v18.0/{config.IG_ID}/messages"
    headers = {"Authorization": f"Bearer {config.INSTAGRAM_TOKEN}", "Content-Type": "application/json"}
    payload = {"recipient": {"id": user_id}, "message": {"text": msg[:1000]}}
    try:
        requests.post(url, headers=headers, json=payload, timeout=10)
    except Exception as e:
        logger.error(f"Error enviando Instagram: {e}")


# ============================================================
# HEALTH CHECK (para UptimeRobot / monitoring)
# ============================================================
@api_router.get("/healthz")
async def health_check():
    """Endpoint público liviano para monitoring (UptimeRobot, BetterStack, etc).
    Verifica que el backend responde y que Mongo está accesible."""
    try:
        await db.command("ping")
        mongo_ok = True
    except Exception:
        mongo_ok = False
    return {
        "ok": True,
        "service": "lluvia-app-studio",
        "mongo": mongo_ok,
        "telegram_bots": len(config.TELEGRAM_TOKENS),
        "ts": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
    }


# ============================================================
# REGISTRAR ROUTERS + CORS
# ============================================================
api_router.include_router(affiliates_module.router)
api_router.include_router(branding_module.router)
api_router.include_router(console_module.router)
api_router.include_router(paypal_integration.router)
api_router.include_router(voice_module.router)
api_router.include_router(agent_builder.router)
api_router.include_router(agency_view.router)
api_router.include_router(promos_module.router)
api_router.include_router(proposals_module.router)
api_router.include_router(call_center_module.router)
api_router.include_router(super_admin_module.router)
api_router.include_router(appointments_module.router)
api_router.include_router(public_chat_module.router)
api_router.include_router(user_workspace_module.router)
api_router.include_router(vps_manager_module.router)
api_router.include_router(workspace_files_module.router)
api_router.include_router(workspace_preview_module.router)
api_router.include_router(ws_streams_module.router)
api_router.include_router(legal_module.router)
api_router.include_router(gmail_module.router)
api_router.include_router(gmail_maestro_module.router)
api_router.include_router(site_content_module.router)
import demo_audio_room as demo_ar_module
api_router.include_router(demo_ar_module.router)
import devops_ai as devops_ai_module
devops_ai_module.set_db(db)
api_router.include_router(devops_ai_module.router)
import pricing as pricing_module
pricing_module.set_db(db)
import admin_pricing as admin_pricing_module
api_router.include_router(admin_pricing_module.router)
api_router.include_router(telegram_unified_module.router_link)

# ── E2-E9 Enterprise Architecture (additive) ──────────────────────────────────
import e2_infra as e2_module
import e3_builder as e3_module
import e4_sales as e4_module
import e4_email as e4_email_module
import e5_whitelabel as e5_module
import e6_legal as e6_legal_module
import e7_billing as e7_module
import e8_support as e8_module
import e9_analytics as e9_module

e2_module.set_db(db)
e3_module.set_db(db)
e4_module.set_db(db)
e4_email_module.set_db(db)
e5_module.set_db(db)
e6_legal_module.set_db(db)
e7_module.set_db(db)
e8_module.set_db(db)
e9_module.set_db(db)

api_router.include_router(e2_module.router)
api_router.include_router(e3_module.router)
api_router.include_router(e4_module.router)
api_router.include_router(e4_email_module.router)
api_router.include_router(e5_module.router)
api_router.include_router(e6_legal_module.router)
api_router.include_router(e7_module.router)
api_router.include_router(e8_module.router)
api_router.include_router(e9_module.router)

# ── Twilio Voice Agents (llamadas PSTN con IA) ────────────────────────────────
import twilio_voice as twilio_voice_module
twilio_voice_module.set_db(db)
api_router.include_router(twilio_voice_module.router)

# ── E10 — Social Automation Agent ────────────────────────────────────────────
import e10_social as e10_module
e10_module.set_db(db)
api_router.include_router(e10_module.router)

# ── E11 — Customer Support / Gmail Agent ──────────────────────────────────────
import e11_gmail_support as e11_module
e11_module.set_db(db)
api_router.include_router(e11_module.router)

# ── Job Scheduler — motor central de jobs/eventos/tareas ──────────────────────
import job_scheduler as job_scheduler_module
job_scheduler_module.set_db(db)
api_router.include_router(job_scheduler_module.router)

# ── E9 Emitters — instrumentación real additive ───────────────────────────────
import e9_emitters as e9_emitters_module
e9_emitters_module.set_db(db)
api_router.include_router(e9_emitters_module.router)

# ── Master Console — operaciones internas con MASTER_KEY ─────────────────────
import master_console as master_console_module
master_console_module.set_db(db)
api_router.include_router(master_console_module.router)

# ── Observabilidad centralizada ───────────────────────────────────────────────
import observability as observability_module
api_router.include_router(observability_module.router)
# ─────────────────────────────────────────────────────────────────────────────

app.include_router(api_router)

# Servir archivos subidos (imagenes de chat). Accesibles via /api/uploads/...
UPLOADS_DIR = ROOT_DIR / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/api/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")

# Servir el frontend del demo publico de Audio Room (template materializado).
# Asi el visitante navega las 4 pantallas reales sin registrarse.
from demo_audio_room import SERVE_DIR as DEMO_AR_DIR
app.mount("/api/demo/audio-room-static", StaticFiles(directory=str(DEMO_AR_DIR), html=True), name="demo_audio_room")

from config import ALLOWED_ORIGINS as _CORS_ORIGINS
app.add_middleware(
    CORSMiddleware,
    allow_credentials=False,
    allow_origins=_CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def shutdown_db_client():
    mongo_client.close()
