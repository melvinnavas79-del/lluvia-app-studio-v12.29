"""
============================================================
GMAIL MAESTRO SCHEDULER · poll cada 5 min
============================================================
Usa asyncio.create_task para correr en background dentro del
mismo event loop de FastAPI (sin agregar workers).

Activado solo si GMAIL_MAESTRO_AUTOPOLL=1 en .env.
"""
import asyncio
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger("gmail_scheduler")

_task: asyncio.Task | None = None
_db_ref = {"db": None}


def set_db(db) -> None:
    _db_ref["db"] = db


async def _poll_loop(interval_seconds: int = 300):
    """Loop infinito que procesa el inbox de cada admin vinculado cada 5 min."""
    from gmail_maestro import _process_inbox_for_user

    logger.info(f"Gmail Maestro autopoll INICIADO (cada {interval_seconds}s)")
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            db = _db_ref["db"]
            if db is None:
                continue
            # Procesar todos los usuarios con Gmail vinculado
            cur = db.gmail_accounts.find({}, {"_id": 0, "user_id": 1})
            user_ids = [d["user_id"] async for d in cur]
            for uid in user_ids:
                try:
                    r = await _process_inbox_for_user(uid, max_msgs=10)
                    if r.get("ok") and r.get("newly_processed", 0) > 0:
                        logger.info(
                            f"[{datetime.now(timezone.utc).isoformat()}] "
                            f"user={uid[:8]} new={r['newly_processed']} unread={r.get('total_unread', 0)}"
                        )
                    elif not r.get("ok"):
                        # No fallar silencioso: si la Gmail API esta dando error
                        # (token expirado, API disabled, quota, etc) lo logueamos
                        # bien visible asi el admin lo ve en /var/log/supervisor.
                        err = str(r.get("error", "unknown"))[:300]
                        logger.warning(
                            f"Gmail poll FAIL user={uid[:8]} error={err}"
                        )
                    # Bitacora en DB para visualizar en panel
                    await db.gmail_poll_log.insert_one({
                        "user_id": uid,
                        "ok": r.get("ok", False),
                        "newly_processed": r.get("newly_processed", 0),
                        "total_unread": r.get("total_unread", 0),
                        "error": r.get("error"),
                        "ts": datetime.now(timezone.utc).isoformat(),
                    })
                except Exception as e:
                    logger.exception(f"poll user {uid}: {e}")
        except asyncio.CancelledError:
            logger.info("Gmail Maestro autopoll CANCELADO")
            raise
        except Exception as e:
            logger.exception(f"poll loop error: {e}")
            # No salir del loop ante errores transitorios
            await asyncio.sleep(30)


def start_scheduler() -> None:
    """Arranca el scheduler. Idempotente."""
    global _task
    if os.environ.get("GMAIL_MAESTRO_AUTOPOLL", "1") != "1":
        logger.info("Gmail Maestro autopoll DESACTIVADO (GMAIL_MAESTRO_AUTOPOLL!=1)")
        return
    if _task is not None and not _task.done():
        return
    interval = int(os.environ.get("GMAIL_MAESTRO_INTERVAL_SECONDS", "300"))
    _task = asyncio.create_task(_poll_loop(interval))


def stop_scheduler() -> None:
    global _task
    if _task and not _task.done():
        _task.cancel()
        _task = None
