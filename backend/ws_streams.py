"""
ws_streams.py - WebSocket endpoints para Lluvia Studio (terminal + logs en vivo).

Endpoints:
  WS /api/me/vps/{vps_id}/terminal       PTY interactivo via SSH (xterm.js)
  WS /api/me/vps/{vps_id}/logs/{service}  Stream de journalctl -u {service} -f

Auth: el token JWT viaja en el query param ?token=... (los browsers no permiten
custom headers en WebSockets nativos).
"""

import asyncio
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, HTTPException

from auth import decode_token as _decode_jwt  # helper interno

logger = logging.getLogger("ws_streams")
router = APIRouter(prefix="/me/vps", tags=["ws_streams"])

_db_ref: dict = {"db": None}


def set_db(db) -> None:
    _db_ref["db"] = db


async def _ws_auth_user(token: str) -> dict:
    """Decodifica el JWT del query param y devuelve el user doc."""
    if not token:
        raise WebSocketDisconnect(code=4401)
    try:
        payload = _decode_jwt(token)
    except Exception:
        raise WebSocketDisconnect(code=4401)
    uid = payload.get("sub") or payload.get("user_id") or payload.get("id")
    if not uid:
        raise WebSocketDisconnect(code=4401)
    user = await _db_ref["db"].users.find_one({"id": uid}, {"_id": 0})
    if not user:
        raise WebSocketDisconnect(code=4401)
    return user


# ============================================================
# WS: Terminal PTY interactivo
# ============================================================
@router.websocket("/{vps_id}/terminal")
async def vps_terminal(ws: WebSocket, vps_id: str, token: str = Query("")):
    await ws.accept()
    import vps_manager as vm
    try:
        user = await _ws_auth_user(token)
    except WebSocketDisconnect:
        await ws.send_text("\r\n\x1b[31mAuth requerida\x1b[0m\r\n")
        await ws.close(code=4401)
        return

    db = _db_ref["db"]
    vps = await db.vps_servers.find_one({"id": vps_id, "user_id": user["id"]})
    if not vps:
        await ws.send_text("\r\n\x1b[31mVPS no encontrado\x1b[0m\r\n")
        await ws.close(code=4404)
        return

    import asyncssh
    try:
        conn = await vm._connect_ssh(vps)
    except Exception as e:
        await ws.send_text(f"\r\n\x1b[31mSSH error: {e}\x1b[0m\r\n")
        await ws.close(code=4500)
        return

    process = None
    try:
        # PTY interactivo: shell con terminal de 80x24 (xterm.js redimensiona despues)
        process = await conn.create_process(
            term_type="xterm-256color", term_size=(80, 24),
            encoding="utf-8",
        )
        await ws.send_text(f"\x1b[32m✓ Conectado a {vps['host']}\x1b[0m\r\n")

        async def stdout_to_ws():
            try:
                async for chunk in process.stdout:
                    if chunk:
                        await ws.send_text(chunk)
            except Exception:
                pass

        async def stderr_to_ws():
            try:
                async for chunk in process.stderr:
                    if chunk:
                        await ws.send_text(chunk)
            except Exception:
                pass

        out_task = asyncio.create_task(stdout_to_ws())
        err_task = asyncio.create_task(stderr_to_ws())

        # Forward stdin del browser -> proceso ssh
        try:
            while True:
                msg = await ws.receive()
                if msg.get("type") == "websocket.disconnect":
                    break
                data = msg.get("text")
                if data is None and "bytes" in msg:
                    data = msg["bytes"].decode("utf-8", errors="ignore")
                if data is None:
                    continue
                # Convencion: si empieza con \x1bRESIZE: -> cambio de tamano "\x1bRESIZE:cols,rows"
                if isinstance(data, str) and data.startswith("\x1bRESIZE:"):
                    try:
                        cols, rows = data[9:].split(",")
                        process.change_terminal_size(int(cols), int(rows))
                    except Exception:
                        pass
                    continue
                process.stdin.write(data)
        except WebSocketDisconnect:
            pass

        out_task.cancel()
        err_task.cancel()
    except Exception as e:
        logger.exception("Error en terminal WS")
        try:
            await ws.send_text(f"\r\n\x1b[31mError: {e}\x1b[0m\r\n")
        except Exception:
            pass
    finally:
        try:
            if process:
                process.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass
        try:
            await ws.close()
        except Exception:
            pass


# ============================================================
# WS: Logs streaming (journalctl -f)
# ============================================================
@router.websocket("/{vps_id}/logs/{service}")
async def vps_logs_stream(ws: WebSocket, vps_id: str, service: str, token: str = Query("")):
    await ws.accept()
    import re
    import vps_manager as vm
    try:
        user = await _ws_auth_user(token)
    except WebSocketDisconnect:
        await ws.send_text("[error] Auth requerida\n")
        await ws.close(code=4401)
        return

    db = _db_ref["db"]
    vps = await db.vps_servers.find_one({"id": vps_id, "user_id": user["id"]})
    if not vps:
        await ws.send_text("[error] VPS no encontrado\n")
        await ws.close(code=4404)
        return

    safe = re.sub(r"[^a-z0-9._-]", "", service)
    if not safe:
        await ws.send_text("[error] nombre de service invalido\n")
        await ws.close(code=4400)
        return

    try:
        conn = await vm._connect_ssh(vps)
    except Exception as e:
        await ws.send_text(f"[error] SSH: {e}\n")
        await ws.close(code=4500)
        return

    process = None
    try:
        # `-n 100` muestra las ultimas 100 lineas y luego sigue (-f)
        cmd = f"sudo journalctl -u {safe} -n 100 -f --no-pager 2>&1"
        process = await conn.create_process(cmd, encoding="utf-8")
        await ws.send_text(f"[connected] {safe}\n")

        # Tarea que reenvia stdout a WS
        async def pump():
            try:
                async for chunk in process.stdout:
                    if chunk:
                        await ws.send_text(chunk)
            except Exception:
                pass

        pump_task = asyncio.create_task(pump())

        # Esperar disconnect del cliente
        try:
            while True:
                msg = await ws.receive()
                if msg.get("type") == "websocket.disconnect":
                    break
        except WebSocketDisconnect:
            pass
        pump_task.cancel()
    except Exception as e:
        try:
            await ws.send_text(f"[error] {e}\n")
        except Exception:
            pass
    finally:
        try:
            if process:
                process.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass
        try:
            await ws.close()
        except Exception:
            pass
