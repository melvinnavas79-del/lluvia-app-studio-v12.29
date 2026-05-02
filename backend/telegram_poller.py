"""
========================================
TELEGRAM LONG POLLING - tarea de background
========================================

Saca actualizaciones via getUpdates en lugar de webhook.
Util cuando:
- El servidor no tiene SSL todavia
- El dominio publico no resuelve
- El webhook esta dando errores

Activacion: variable de entorno TELEGRAM_POLLING=1 en backend/.env
"""

import asyncio
import logging
from typing import Optional

import requests

import config
from agent import process_command

logger = logging.getLogger("telegram_poller")

_task: Optional[asyncio.Task] = None
_offset: int = 0


def _api(method: str) -> str:
    return f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/{method}"


def _delete_webhook() -> None:
    """Telegram NO permite webhook + polling al mismo tiempo."""
    try:
        r = requests.post(_api("deleteWebhook"), json={"drop_pending_updates": False}, timeout=10)
        logger.info(f"deleteWebhook -> {r.status_code} {r.text[:120]}")
    except Exception as e:
        logger.error(f"deleteWebhook fallo: {e}")


def _send_sync(chat_id: int, text: str) -> None:
    if not text:
        return
    try:
        # Telegram limita 4096 chars por mensaje; cortamos por seguridad
        for chunk in [text[i:i + 4000] for i in range(0, len(text), 4000)]:
            requests.post(
                _api("sendMessage"),
                json={"chat_id": chat_id, "text": chunk},
                timeout=10,
            )
    except Exception as e:
        logger.error(f"sendMessage fallo: {e}")


async def _send(chat_id: int, text: str) -> None:
    """Wrapper async para no bloquear el event loop al enviar a Telegram."""
    await asyncio.to_thread(_send_sync, chat_id, text)


async def _process_update(update: dict) -> None:
    msg = update.get("message") or update.get("edited_message") or {}
    text = msg.get("text") or ""
    chat_id = (msg.get("chat") or {}).get("id")
    if not text or not chat_id:
        return
    logger.info(f"[poll] chat={chat_id} text={text[:80]}")
    try:
        reply = await process_command(text, str(chat_id))
        await _send(chat_id, reply)
    except Exception as e:
        logger.exception(f"process_command fallo: {e}")
        await _send(chat_id, f"Error interno: {str(e)[:200]}")


async def _loop() -> None:
    global _offset
    if not config.TELEGRAM_TOKEN:
        logger.warning("TELEGRAM_TOKEN vacio, polling deshabilitado")
        return

    # 1. Asegurar que NO hay webhook competente
    await asyncio.to_thread(_delete_webhook)

    logger.info("Telegram polling iniciado")
    while True:
        try:
            # CRITICO: requests.get es bloqueante. Lo corremos en thread aparte
            # para NO bloquear el event loop de uvicorn (todos los demas endpoints
            # se cuelgan si esto bloquea).
            r = await asyncio.to_thread(
                requests.get,
                _api("getUpdates"),
                params={"offset": _offset, "timeout": 25, "allowed_updates": '["message"]'},
                timeout=35,
            )
            if r.status_code != 200:
                logger.warning(f"getUpdates {r.status_code}: {r.text[:200]}")
                await asyncio.sleep(5)
                continue
            data = r.json()
            for upd in data.get("result", []):
                _offset = upd["update_id"] + 1
                await _process_update(upd)
        except requests.exceptions.Timeout:
            # Long-poll timeout normal, seguir
            continue
        except Exception as e:
            logger.exception(f"Error en loop polling: {e}")
            await asyncio.sleep(5)


def start() -> None:
    """Arranca el polling como tarea de background del event loop actual."""
    global _task
    if _task and not _task.done():
        logger.info("Polling ya en marcha")
        return
    _task = asyncio.create_task(_loop())
    logger.info("Tarea de polling registrada")


def stop() -> None:
    global _task
    if _task and not _task.done():
        _task.cancel()
        logger.info("Polling cancelado")
