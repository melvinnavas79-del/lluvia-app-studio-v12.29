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
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

from fastapi import FastAPI, APIRouter, Request, HTTPException
from fastapi.responses import PlainTextResponse, FileResponse
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


# ----------------------- APP -----------------------
app = FastAPI(title="Bot Multiplataforma", version="1.1.0")
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

    # Telegram long polling (alternativa a webhook). Activar con TELEGRAM_POLLING=1
    import os
    if os.environ.get("TELEGRAM_POLLING", "0") == "1" and config.TELEGRAM_TOKEN:
        telegram_poller.start()
        logger.info("Telegram polling activado")


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
        "version": "operario-3.1",
        "fixes": [
            "v3.1: telegram_poller usa asyncio.to_thread() - NO bloquea event loop de uvicorn",
            "v3: api.js sanitiza REACT_APP_BACKEND_URL (acepta con o sin /api, sin duplicar)",
            "v3: .env.example trae MONGO_URL=mongodb://mongo:27017 por defecto (Docker DNS)",
            "v3: TELEGRAM_POLLING=1 -> bot funciona sin SSL ni dominio publico",
            "v2: Dockerfile pineado a python:3.11.10-slim-bookworm (NO Trixie)",
            "v2: requirements-prod.txt minimo (13 paquetes vs 123)",
            "v2: Healthcheck cada 15s en backend/frontend",
            "v2: setup-cliente.sh con logs visibles",
            "v2: scripts/diagnose.sh para troubleshoot",
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
    if not config.TELEGRAM_TOKEN or token != config.TELEGRAM_TOKEN:
        raise HTTPException(status_code=403, detail="Telegram token invalido")
    data = await request.json()
    try:
        text = data["message"]["text"]
        chat_id = data["message"]["chat"]["id"]
        reply = await process_command(text, str(chat_id))
        send_telegram(chat_id, reply)
    except (KeyError, TypeError) as e:
        logger.warning(f"Telegram webhook sin mensaje procesable: {e}")
    except Exception as e:
        logger.exception(f"Error procesando webhook Telegram: {e}")
    return {"ok": True}


def send_telegram(chat_id, msg: str) -> None:
    if not config.TELEGRAM_TOKEN:
        logger.info(f"[Telegram simulado] chat_id={chat_id} msg={msg[:80]}")
        return
    url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage"
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
# REGISTRAR ROUTERS + CORS
# ============================================================
api_router.include_router(affiliates_module.router)
api_router.include_router(branding_module.router)
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=False,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def shutdown_db_client():
    mongo_client.close()
