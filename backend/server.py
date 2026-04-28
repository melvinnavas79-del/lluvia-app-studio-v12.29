"""
========================================
SERVIDOR FASTAPI - BOT MULTIPLATAFORMA
========================================

Webhooks para Telegram, WhatsApp e Instagram.
Endpoint /api/command para uso directo.

NOTA INFRAESTRUCTURA:
- Este servicio corre en el puerto 8001 (gestionado por supervisor).
- Externamente accesible via la URL publica configurada con prefijo /api.
"""

import logging
from pathlib import Path

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, APIRouter, Request, HTTPException
from fastapi.responses import PlainTextResponse
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

import config
from agent import process_command
from actions import apps as ap
import memory


# ----------------------- LOGGING -----------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("bot")


# ----------------------- DB -----------------------
mongo_client = AsyncIOMotorClient(config.MONGO_URL)
db = mongo_client[config.DB_NAME]


# ----------------------- APP -----------------------
app = FastAPI(title="Bot Multiplataforma", version="1.0.0")
api_router = APIRouter(prefix="/api")


# ============================================================
# RUTAS BASICAS
# ============================================================
@api_router.get("/")
async def root():
    return {
        "service": "Bot Multiplataforma",
        "status": "running",
        "platforms": ["whatsapp", "telegram", "instagram"],
    }


@api_router.get("/status")
async def status():
    """Estado del bot y de las credenciales configuradas."""
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
    """Envia un comando directo al bot (para pruebas o integracion propia)."""
    message = data.get("message") or data.get("text") or ""
    user = str(data.get("user", "default"))
    if not message:
        raise HTTPException(status_code=400, detail="message es obligatorio")
    response = await process_command(message, user)
    return {"response": response, "user": user}


# ============================================================
# WHATSAPP (Meta Cloud API)
# ============================================================
@api_router.get("/webhook/whatsapp")
async def whatsapp_verify(request: Request):
    params = request.query_params
    if params.get("hub.verify_token") == config.VERIFY_TOKEN:
        challenge = params.get("hub.challenge", "")
        return PlainTextResponse(content=str(challenge))
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
    if not config.WHATSAPP_TOKEN or config.WHATSAPP_TOKEN == "TOKEN_META":
        logger.info(f"[WhatsApp simulado] to={to} msg={msg[:80]}")
        return
    url = f"https://graph.facebook.com/v18.0/{config.PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {config.WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": msg[:4000]},
    }
    try:
        requests.post(url, headers=headers, json=payload, timeout=10)
    except Exception as e:
        logger.error(f"Error enviando WhatsApp: {e}")


# ============================================================
# TELEGRAM
# ============================================================
@api_router.post("/webhook/telegram/{token}")
async def telegram_webhook(token: str, request: Request):
    if token != config.TELEGRAM_TOKEN:
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
    if not config.TELEGRAM_TOKEN or config.TELEGRAM_TOKEN == "BOT_TOKEN":
        logger.info(f"[Telegram simulado] chat_id={chat_id} msg={msg[:80]}")
        return
    url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": msg[:4000]}, timeout=10)
    except Exception as e:
        logger.error(f"Error enviando Telegram: {e}")


# ============================================================
# INSTAGRAM (Meta)
# ============================================================
@api_router.get("/webhook/instagram")
async def instagram_verify(request: Request):
    params = request.query_params
    if params.get("hub.verify_token") == config.VERIFY_TOKEN:
        challenge = params.get("hub.challenge", "")
        return PlainTextResponse(content=str(challenge))
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
    if not config.INSTAGRAM_TOKEN or config.INSTAGRAM_TOKEN == "TOKEN_META":
        logger.info(f"[Instagram simulado] user_id={user_id} msg={msg[:80]}")
        return
    url = f"https://graph.facebook.com/v18.0/{config.IG_ID}/messages"
    headers = {
        "Authorization": f"Bearer {config.INSTAGRAM_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "recipient": {"id": user_id},
        "message": {"text": msg[:1000]},
    }
    try:
        requests.post(url, headers=headers, json=payload, timeout=10)
    except Exception as e:
        logger.error(f"Error enviando Instagram: {e}")


# ============================================================
# REGISTRAR ROUTER + CORS
# ============================================================
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def shutdown_db_client():
    mongo_client.close()
