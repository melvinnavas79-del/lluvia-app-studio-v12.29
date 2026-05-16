"""
{{APP_NAME}} - Backend FastAPI + Socket.IO para Salas de Audio en Vivo.

Arquitectura:
- FastAPI sirve la API REST + el frontend estatico.
- python-socketio (ASGI mode) provee signaling WebRTC.
- SQLite por defecto (cero config). Opcional: MONGO_URL para Mongo (no implementado en este template, solo placeholder).

Endpoints publicos:
  POST  /api/users/anonymous          -> crea usuario rapido + JWT
  GET   /api/users/{user_id}          -> perfil
  POST  /api/users/{user_id}/follow   -> seguir
  GET   /api/users/top                -> ranking creadores
  POST  /api/rooms                    -> crear sala (host = user actual)
  GET   /api/rooms                    -> listar salas (filtros)
  GET   /api/rooms/{id}               -> detalle (con speakers/listeners)
  DELETE /api/rooms/{id}              -> cerrar sala (solo host)
  POST  /api/rooms/{id}/purchase      -> comprar acceso a sala premium

Eventos Socket.IO:
  join-room {room_id, role}
  leave-room {room_id}
  offer {to, sdp}, answer {to, sdp}, ice-candidate {to, candidate}
  request-speak {room_id}
  reaction {room_id, emoji}
  Server emits: user-joined, user-left, offer, answer, ice-candidate, role-changed
"""

import os
import time
import uuid
import sqlite3
import secrets
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, List

import jwt
import socketio
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

# ============================================================
# CONFIG
# ============================================================
APP_NAME = os.environ.get("APP_NAME", "{{APP_NAME}}")
BRAND_COLOR = os.environ.get("BRAND_COLOR", "{{BRAND_COLOR}}")
JWT_SECRET = os.environ.get("JWT_SECRET") or secrets.token_hex(32)
DB_PATH = os.environ.get("DB_PATH", str(Path(__file__).parent / "data.db"))
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
PORT = int(os.environ.get("PORT", "8001"))

# ============================================================
# DB (SQLite, cero config)
# ============================================================
def init_db():
    con = sqlite3.connect(DB_PATH)
    con.executescript("""
    CREATE TABLE IF NOT EXISTS users (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      handle TEXT,
      bio TEXT,
      color TEXT,
      followers INTEGER DEFAULT 0,
      rooms_hosted INTEGER DEFAULT 0,
      total_listeners INTEGER DEFAULT 0,
      credits INTEGER DEFAULT 0,
      created_at INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS rooms (
      id TEXT PRIMARY KEY,
      host_id TEXT NOT NULL,
      title TEXT NOT NULL,
      description TEXT,
      category TEXT,
      language TEXT DEFAULT 'es',
      monetization TEXT DEFAULT 'free',
      price_credits INTEGER DEFAULT 0,
      is_live INTEGER DEFAULT 1,
      listeners_count INTEGER DEFAULT 0,
      speakers_count INTEGER DEFAULT 1,
      created_at INTEGER NOT NULL,
      ended_at INTEGER,
      FOREIGN KEY (host_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS follows (
      follower_id TEXT NOT NULL,
      followee_id TEXT NOT NULL,
      created_at INTEGER NOT NULL,
      PRIMARY KEY (follower_id, followee_id)
    );
    CREATE TABLE IF NOT EXISTS room_access (
      user_id TEXT NOT NULL,
      room_id TEXT NOT NULL,
      paid_at INTEGER NOT NULL,
      price INTEGER DEFAULT 0,
      PRIMARY KEY (user_id, room_id)
    );
    CREATE INDEX IF NOT EXISTS idx_rooms_live ON rooms(is_live, created_at);
    CREATE INDEX IF NOT EXISTS idx_rooms_host ON rooms(host_id);
    """)
    con.commit()
    con.close()


@contextmanager
def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


# ============================================================
# AUTH (JWT simple)
# ============================================================
def make_token(user_id: str) -> str:
    return jwt.encode({"sub": user_id, "iat": int(time.time())}, JWT_SECRET, algorithm="HS256")


def decode_token(token: str) -> Optional[str]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"]).get("sub")
    except Exception:
        return None


async def current_user(authorization: Optional[str] = Header(default=None)) -> dict:
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1]
    uid = decode_token(token)
    if not uid:
        raise HTTPException(status_code=401, detail="Token invalido")
    with db() as con:
        row = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="Usuario no existe")
    return dict(row)


# ============================================================
# FASTAPI APP
# ============================================================
api = FastAPI(title=f"{APP_NAME} API")
api.add_middleware(
    CORSMiddleware, allow_origins=["*"],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)


@api.get("/api/health")
def health():
    return {"ok": True, "app": APP_NAME, "ts": int(time.time())}


# --- Users ---------------------------------------------------
class AnonymousIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)


@api.post("/api/users/anonymous")
def create_anonymous(data: AnonymousIn):
    uid = str(uuid.uuid4())
    handle = data.name.lower().replace(" ", "") + str(uuid.uuid4())[:4]
    color = f"#{(hash(uid) & 0xFFFFFF):06x}"
    with db() as con:
        con.execute(
            "INSERT INTO users (id, name, handle, color, created_at, credits) VALUES (?,?,?,?,?,?)",
            (uid, data.name.strip(), handle, color, int(time.time()), 100),
        )
        row = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    return {"token": make_token(uid), "user": dict(row)}


@api.get("/api/users/top")
def top_users(limit: int = 10):
    with db() as con:
        rows = con.execute(
            "SELECT id, name, color, followers, rooms_hosted, total_listeners "
            "FROM users ORDER BY followers DESC, total_listeners DESC LIMIT ?",
            (max(1, min(50, limit)),),
        ).fetchall()
    return {"users": [dict(r) for r in rows]}


@api.get("/api/users/{user_id}")
def get_user(user_id: str):
    with db() as con:
        row = con.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Usuario no encontrado")
    return dict(row)


@api.post("/api/users/{user_id}/follow")
def follow_user(user_id: str, user: dict = Depends(current_user)):
    if user_id == user["id"]:
        raise HTTPException(400, "No puedes seguirte a ti mismo")
    with db() as con:
        exists = con.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone()
        if not exists:
            raise HTTPException(404, "Usuario no existe")
        try:
            con.execute(
                "INSERT INTO follows (follower_id, followee_id, created_at) VALUES (?,?,?)",
                (user["id"], user_id, int(time.time())),
            )
            con.execute("UPDATE users SET followers = followers + 1 WHERE id=?", (user_id,))
        except sqlite3.IntegrityError:
            pass  # ya lo seguia
    return {"ok": True}


# --- Rooms ---------------------------------------------------
class RoomIn(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    description: Optional[str] = Field(default="", max_length=240)
    category: Optional[str] = "Charlas"
    language: Optional[str] = "es"
    monetization: Optional[str] = "free"
    price_credits: Optional[int] = 0


@api.post("/api/rooms")
def create_room(data: RoomIn, user: dict = Depends(current_user)):
    rid = str(uuid.uuid4())
    with db() as con:
        con.execute(
            "INSERT INTO rooms (id, host_id, title, description, category, language, "
            " monetization, price_credits, is_live, listeners_count, speakers_count, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,1,0,1,?)",
            (rid, user["id"], data.title.strip(), (data.description or "").strip(),
             data.category, data.language, data.monetization,
             max(0, int(data.price_credits or 0)), int(time.time())),
        )
        con.execute("UPDATE users SET rooms_hosted = rooms_hosted + 1 WHERE id=?", (user["id"],))
    return {"id": rid, "ok": True}


@api.get("/api/rooms")
def list_rooms(
    category: Optional[str] = None,
    host_id: Optional[str] = None,
    sort: Optional[str] = None,
    limit: int = 20,
):
    q = "SELECT r.*, u.name AS host_name FROM rooms r LEFT JOIN users u ON r.host_id=u.id WHERE r.is_live=1"
    params: list = []
    if category and category.lower() != "todas":
        q += " AND r.category=?"; params.append(category)
    if host_id:
        q += " AND r.host_id=?"; params.append(host_id)
    if sort == "listeners":
        q += " ORDER BY r.listeners_count DESC, r.created_at DESC"
    else:
        q += " ORDER BY r.created_at DESC"
    q += " LIMIT ?"; params.append(max(1, min(100, limit)))
    with db() as con:
        rows = con.execute(q, params).fetchall()
    return {"rooms": [dict(r) for r in rows]}


@api.get("/api/rooms/{room_id}")
def get_room(room_id: str, authorization: Optional[str] = Header(default=None)):
    with db() as con:
        row = con.execute(
            "SELECT r.*, u.name AS host_name FROM rooms r "
            "LEFT JOIN users u ON r.host_id=u.id WHERE r.id=?",
            (room_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Sala no encontrada")
        d = dict(row)
        # membresia premium: chequear acceso del usuario actual si hay token
        d["has_access"] = True
        if d["monetization"] == "premium":
            uid = None
            if authorization and authorization.lower().startswith("bearer "):
                uid = decode_token(authorization.split(" ", 1)[1])
            if uid != d["host_id"]:
                paid = con.execute(
                    "SELECT 1 FROM room_access WHERE user_id=? AND room_id=?",
                    (uid or "", room_id),
                ).fetchone()
                d["has_access"] = bool(paid)
        # speakers/listeners en vivo desde Socket.IO state
        d["speakers"] = list(_room_speakers.get(room_id, {}).values())
        d["listeners"] = list(_room_listeners.get(room_id, {}).values())
    return d


@api.delete("/api/rooms/{room_id}")
def close_room(room_id: str, user: dict = Depends(current_user)):
    with db() as con:
        row = con.execute("SELECT host_id FROM rooms WHERE id=?", (room_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Sala no encontrada")
        if row["host_id"] != user["id"]:
            raise HTTPException(403, "Solo el host puede cerrar la sala")
        con.execute("UPDATE rooms SET is_live=0, ended_at=? WHERE id=?", (int(time.time()), room_id))
    return {"ok": True}


@api.post("/api/rooms/{room_id}/purchase")
def purchase_access(room_id: str, user: dict = Depends(current_user)):
    with db() as con:
        room = con.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
        if not room:
            raise HTTPException(404, "Sala no encontrada")
        if room["monetization"] != "premium":
            raise HTTPException(400, "Esta sala es gratis")
        price = int(room["price_credits"] or 0)
        user_row = con.execute("SELECT credits FROM users WHERE id=?", (user["id"],)).fetchone()
        if (user_row["credits"] or 0) < price:
            raise HTTPException(402, f"Necesitas {price} oros. Tienes {user_row['credits']}.")
        con.execute("UPDATE users SET credits = credits - ? WHERE id=?", (price, user["id"]))
        con.execute(
            "INSERT OR REPLACE INTO room_access (user_id, room_id, paid_at, price) VALUES (?,?,?,?)",
            (user["id"], room_id, int(time.time()), price),
        )
    return {"ok": True, "remaining_credits": (user_row["credits"] or 0) - price}


# ============================================================
# SOCKET.IO - Signaling WebRTC + presencia
# ============================================================
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")

# Estado en memoria (en produccion: usar Redis para multi-instancia)
_room_speakers: dict = {}   # room_id -> {user_id: {id,name,role,muted,is_speaking}}
_room_listeners: dict = {}  # room_id -> {user_id: {id,name}}
_sid_user: dict = {}        # sid -> {user_id, room_id, role}


@sio.event
async def connect(sid, environ, auth):
    token = (auth or {}).get("token", "")
    uid = decode_token(token)
    if not uid:
        return False
    _sid_user[sid] = {"user_id": uid, "room_id": None, "role": "listener"}
    return True


@sio.event
async def disconnect(sid):
    info = _sid_user.pop(sid, None)
    if not info or not info["room_id"]:
        return
    await _leave(sid, info["room_id"], info["user_id"])


async def _leave(sid, room_id, uid):
    sio.leave_room(sid, room_id) if False else None  # noop: la sala se libera sola
    _room_speakers.get(room_id, {}).pop(uid, None)
    _room_listeners.get(room_id, {}).pop(uid, None)
    await sio.emit("user-left", {"user_id": uid}, room=room_id, skip_sid=sid)
    # actualizar contadores
    with db() as con:
        con.execute(
            "UPDATE rooms SET listeners_count=?, speakers_count=? WHERE id=?",
            (len(_room_listeners.get(room_id, {})), max(1, len(_room_speakers.get(room_id, {}))), room_id),
        )


@sio.on("join-room")
async def join_room(sid, data):
    info = _sid_user.get(sid)
    if not info:
        return
    room_id = data.get("room_id")
    role = data.get("role", "listener")
    if not room_id:
        return
    uid = info["user_id"]
    info["room_id"] = room_id
    info["role"] = role
    await sio.enter_room(sid, room_id)
    with db() as con:
        row = con.execute("SELECT name, host_id FROM rooms r LEFT JOIN users u ON r.host_id=u.id WHERE r.id=?", (room_id,)).fetchone()
        user_row = con.execute("SELECT name FROM users WHERE id=?", (uid,)).fetchone()
    if not user_row:
        return
    name = user_row["name"]
    if role == "listener":
        _room_listeners.setdefault(room_id, {})[uid] = {"id": uid, "name": name}
    else:
        _room_speakers.setdefault(room_id, {})[uid] = {
            "id": uid, "name": name, "role": role, "muted": False, "is_speaking": False,
        }
    # notificar al resto
    await sio.emit("user-joined", {"user_id": uid, "name": name, "role": role}, room=room_id, skip_sid=sid)
    with db() as con:
        con.execute(
            "UPDATE rooms SET listeners_count=?, speakers_count=? WHERE id=?",
            (len(_room_listeners.get(room_id, {})), max(1, len(_room_speakers.get(room_id, {}))), room_id),
        )


@sio.on("leave-room")
async def leave_room_evt(sid, data):
    info = _sid_user.get(sid)
    if not info or not info["room_id"]:
        return
    await _leave(sid, info["room_id"], info["user_id"])
    info["room_id"] = None


@sio.on("offer")
async def on_offer(sid, data):
    info = _sid_user.get(sid)
    if not info:
        return
    # encontrar el sid del destinatario
    target = next((s for s, i in _sid_user.items() if i["user_id"] == data.get("to")), None)
    if target:
        await sio.emit("offer", {"from": info["user_id"], "sdp": data.get("sdp")}, to=target)


@sio.on("answer")
async def on_answer(sid, data):
    info = _sid_user.get(sid)
    if not info:
        return
    target = next((s for s, i in _sid_user.items() if i["user_id"] == data.get("to")), None)
    if target:
        await sio.emit("answer", {"from": info["user_id"], "sdp": data.get("sdp")}, to=target)


@sio.on("ice-candidate")
async def on_ice(sid, data):
    info = _sid_user.get(sid)
    if not info:
        return
    target = next((s for s, i in _sid_user.items() if i["user_id"] == data.get("to")), None)
    if target:
        await sio.emit("ice-candidate", {"from": info["user_id"], "candidate": data.get("candidate")}, to=target)


@sio.on("request-speak")
async def request_speak(sid, data):
    info = _sid_user.get(sid)
    if not info:
        return
    room_id = data.get("room_id")
    # avisar al host de la sala
    with db() as con:
        row = con.execute("SELECT host_id FROM rooms WHERE id=?", (room_id,)).fetchone()
    if not row:
        return
    host_sid = next((s for s, i in _sid_user.items() if i["user_id"] == row["host_id"]), None)
    if host_sid:
        await sio.emit("speak-request", {"user_id": info["user_id"]}, to=host_sid)


@sio.on("promote-speaker")
async def promote_speaker(sid, data):
    """El host promueve a un listener a speaker."""
    info = _sid_user.get(sid)
    if not info:
        return
    room_id = data.get("room_id")
    target_uid = data.get("user_id")
    with db() as con:
        row = con.execute("SELECT host_id FROM rooms WHERE id=?", (room_id,)).fetchone()
    if not row or row["host_id"] != info["user_id"]:
        return  # solo el host
    listener = _room_listeners.get(room_id, {}).pop(target_uid, None)
    if listener:
        _room_speakers.setdefault(room_id, {})[target_uid] = {
            "id": target_uid, "name": listener["name"], "role": "speaker",
            "muted": False, "is_speaking": False,
        }
        await sio.emit("role-changed", {"user_id": target_uid, "role": "speaker"}, room=room_id)


@sio.on("reaction")
async def on_reaction(sid, data):
    info = _sid_user.get(sid)
    if not info:
        return
    room_id = data.get("room_id")
    await sio.emit("reaction", {"user_id": info["user_id"], "emoji": data.get("emoji")}, room=room_id)


# ============================================================
# Servir frontend estatico
# ============================================================
if FRONTEND_DIR.exists():
    api.mount(
        "/static",
        StaticFiles(directory=str(FRONTEND_DIR)),
        name="frontend_static",
    )

    @api.get("/")
    def index():
        return FileResponse(str(FRONTEND_DIR / "index.html"))

    @api.get("/css/{path:path}")
    def css_proxy(path: str):
        f = FRONTEND_DIR / "css" / path
        if f.exists():
            return FileResponse(str(f))
        raise HTTPException(404)

    @api.get("/js/{path:path}")
    def js_proxy(path: str):
        f = FRONTEND_DIR / "js" / path
        if f.exists():
            return FileResponse(str(f))
        raise HTTPException(404)


# ============================================================
# COMBINAR FastAPI + Socket.IO en una sola ASGI app
# ============================================================
init_db()
app = socketio.ASGIApp(sio, other_asgi_app=api, socketio_path="/socket.io")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=PORT, log_level="info")
