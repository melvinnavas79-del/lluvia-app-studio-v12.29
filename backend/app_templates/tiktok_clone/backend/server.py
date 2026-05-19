"""
{{APP_NAME}} - Backend FastAPI + Socket.IO para Feed Vertical de Videos en vivo
(estilo TikTok / Bigo Live / Kuaishou).

Arquitectura:
- FastAPI sirve la API REST + el frontend estatico desde el MISMO puerto.
- python-socketio (ASGI mode) para comentarios en tiempo real y notificaciones.
- SQLite local (cero config). En produccion podes migrar a Postgres o Mongo.

Endpoints publicos:
  POST  /api/users/anonymous          -> crea usuario rapido + JWT
  GET   /api/users/{user_id}          -> perfil con stats
  POST  /api/users/{user_id}/follow   -> seguir/dejar de seguir
  GET   /api/users/top                -> ranking creadores
  GET   /api/videos/feed              -> feed personalizado (paginado)
  GET   /api/videos/trending          -> ranking videos top
  POST  /api/videos                   -> publicar un video (url remota)
  GET   /api/videos/{id}              -> detalle video
  POST  /api/videos/{id}/like         -> like / unlike
  GET   /api/videos/{id}/comments     -> listar comentarios
  POST  /api/videos/{id}/comment      -> comentar
  POST  /api/videos/{id}/gift         -> mandar regalo virtual (cobra credits)
  POST  /api/users/{id}/topup         -> agregar credits (stub para Stripe/PayPal)
  GET   /api/health                   -> health check

Eventos Socket.IO (sala = video_id):
  join-video {video_id}
  leave-video {video_id}
  new-comment {video_id, text}        -> server emite a la sala
  new-gift {video_id, gift, value}    -> server emite a la sala
  Server emits: viewer-count, comment, gift, like-burst
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

GIFTS = {
    "rose":     {"name": "Rosa",        "emoji": "🌹", "credits": 5},
    "heart":    {"name": "Corazon",     "emoji": "💖", "credits": 10},
    "fire":     {"name": "Fuego",       "emoji": "🔥", "credits": 20},
    "rocket":   {"name": "Cohete",      "emoji": "🚀", "credits": 50},
    "diamond":  {"name": "Diamante",    "emoji": "💎", "credits": 200},
    "crown":    {"name": "Corona",      "emoji": "👑", "credits": 500},
}

# ============================================================
# DB
# ============================================================
def init_db():
    con = sqlite3.connect(DB_PATH)
    con.executescript("""
    CREATE TABLE IF NOT EXISTS users (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      handle TEXT UNIQUE,
      bio TEXT,
      avatar_color TEXT,
      followers INTEGER DEFAULT 0,
      following INTEGER DEFAULT 0,
      videos_count INTEGER DEFAULT 0,
      total_likes INTEGER DEFAULT 0,
      credits INTEGER DEFAULT 100,
      created_at INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS videos (
      id TEXT PRIMARY KEY,
      author_id TEXT NOT NULL,
      caption TEXT,
      video_url TEXT NOT NULL,
      thumb_url TEXT,
      duration_sec INTEGER DEFAULT 0,
      tags TEXT,
      likes INTEGER DEFAULT 0,
      views INTEGER DEFAULT 0,
      comments_count INTEGER DEFAULT 0,
      gifts_total_credits INTEGER DEFAULT 0,
      is_live INTEGER DEFAULT 0,
      created_at INTEGER NOT NULL,
      FOREIGN KEY (author_id) REFERENCES users(id)
    );
    CREATE INDEX IF NOT EXISTS idx_videos_created ON videos(created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_videos_likes ON videos(likes DESC);
    CREATE TABLE IF NOT EXISTS follows (
      follower_id TEXT NOT NULL,
      followee_id TEXT NOT NULL,
      created_at INTEGER NOT NULL,
      PRIMARY KEY (follower_id, followee_id)
    );
    CREATE TABLE IF NOT EXISTS likes (
      user_id TEXT NOT NULL,
      video_id TEXT NOT NULL,
      created_at INTEGER NOT NULL,
      PRIMARY KEY (user_id, video_id)
    );
    CREATE TABLE IF NOT EXISTS comments (
      id TEXT PRIMARY KEY,
      video_id TEXT NOT NULL,
      author_id TEXT NOT NULL,
      text TEXT NOT NULL,
      created_at INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_comments_video ON comments(video_id, created_at DESC);
    CREATE TABLE IF NOT EXISTS gifts_log (
      id TEXT PRIMARY KEY,
      from_user_id TEXT NOT NULL,
      to_user_id TEXT NOT NULL,
      video_id TEXT,
      gift_key TEXT NOT NULL,
      credits INTEGER NOT NULL,
      created_at INTEGER NOT NULL
    );
    """)
    # Seed demo data si esta vacio
    cur = con.execute("SELECT COUNT(*) FROM users").fetchone()
    if cur[0] == 0:
        _seed_demo(con)
    con.commit()
    con.close()


def _seed_demo(con):
    """Carga 3 creadores y 6 videos de muestra para que el feed no este vacio."""
    now = int(time.time())
    creators = [
        ("luna", "Luna Star", "@luna.star", "Bailarina pro · Live cada noche 9pm", "#FF0050", 12500, 230, 18),
        ("dj_neo", "DJ Neo", "@djneo", "House & Techno · Sesiones en vivo", "#5B8DEF", 8900, 145, 9),
        ("chef_mia", "Chef Mia", "@chefmia", "Cocina rapida en 60 segundos", "#10B981", 6700, 88, 14),
    ]
    for uid, name, handle, bio, color, followers, likes, videos in creators:
        con.execute(
            "INSERT INTO users (id, name, handle, bio, avatar_color, followers, total_likes, videos_count, credits, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (uid, name, handle, bio, color, followers, likes, videos, 500, now)
        )
    sample_videos = [
        ("luna", "Coreografia nueva 🔥 esperaba este beat", "music,dance,viral",
         "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerJoyrides.mp4",
         "https://images.unsplash.com/photo-1518609878373-06d740f60d8b?w=400", 18, 2340, 45000),
        ("dj_neo", "Drop a la 0:30 sube el volumen 🎧", "music,electronic,live",
         "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerFun.mp4",
         "https://images.unsplash.com/photo-1493225457124-a3eb161ffa5f?w=400", 60, 1820, 28000),
        ("chef_mia", "Pasta 4 quesos en 90 segundos 🍝", "food,cooking,easy",
         "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerEscapes.mp4",
         "https://images.unsplash.com/photo-1565299624946-b28f40a0ae38?w=400", 90, 1240, 19500),
        ("luna", "GRWM para mi live de esta noche 💃", "lifestyle,getready,fashion",
         "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerMeltdowns.mp4",
         "https://images.unsplash.com/photo-1469334031218-e382a71b716b?w=400", 22, 1980, 38000),
        ("dj_neo", "Vibing con mi nuevo controller 🎛️", "music,gear,setup",
         "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerBlazes.mp4",
         "https://images.unsplash.com/photo-1571266028243-d220c6a16f96?w=400", 15, 1450, 22000),
        ("chef_mia", "El truco que cambio mi sopa de tomate 🍅", "food,trick,viral",
         "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerJoyrides.mp4",
         "https://images.unsplash.com/photo-1547592180-85f173990554?w=400", 33, 980, 12500),
    ]
    for author, caption, tags, vurl, thumb, dur, views, likes in sample_videos:
        vid = str(uuid.uuid4())[:12]
        con.execute(
            "INSERT INTO videos (id, author_id, caption, video_url, thumb_url, duration_sec, tags, likes, views, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (vid, author, caption, vurl, thumb, dur, tags, likes, views, now - int(time.time()) % 86400)
        )


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
# Auth helpers
# ============================================================
def make_jwt(user_id: str) -> str:
    return jwt.encode(
        {"uid": user_id, "iat": int(time.time()), "exp": int(time.time()) + 60 * 60 * 24 * 30},
        JWT_SECRET, algorithm="HS256",
    )


def auth_user(authorization: Optional[str] = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Bearer token requerido")
    try:
        payload = jwt.decode(authorization.split(" ", 1)[1], JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError as e:
        raise HTTPException(401, f"Token invalido: {e}")
    with db() as con:
        u = con.execute("SELECT * FROM users WHERE id=?", (payload["uid"],)).fetchone()
        if not u:
            raise HTTPException(401, "Usuario no encontrado")
        return dict(u)


def maybe_user(authorization: Optional[str] = Header(None)) -> Optional[dict]:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    try:
        return auth_user(authorization)
    except Exception:
        return None


# ============================================================
# Pydantic models
# ============================================================
class AnonIn(BaseModel):
    name: Optional[str] = None
    handle: Optional[str] = None


class VideoIn(BaseModel):
    caption: str = Field(..., max_length=400)
    video_url: str = Field(..., max_length=600)
    thumb_url: Optional[str] = Field(None, max_length=600)
    duration_sec: int = Field(0, ge=0, le=600)
    tags: Optional[str] = Field("", max_length=200)


class CommentIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=300)


class GiftIn(BaseModel):
    gift_key: str


class TopupIn(BaseModel):
    amount: int = Field(..., ge=1, le=100000)


# ============================================================
# FastAPI
# ============================================================
api = FastAPI(title=f"{APP_NAME} API", version="1.0.0")

api.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)


@api.get("/api/health")
def health():
    return {"ok": True, "app": APP_NAME, "ts": int(time.time())}


# -------------------- Users --------------------
@api.post("/api/users/anonymous")
def create_anon(data: AnonIn):
    uid = str(uuid.uuid4())[:12]
    name = (data.name or f"user_{uid[:6]}").strip()[:60]
    handle = (data.handle or f"@{uid[:8]}").strip()[:30]
    if not handle.startswith("@"):
        handle = "@" + handle
    palette = ["#FF0050", "#5B8DEF", "#10B981", "#F59E0B", "#A855F7", "#EC4899"]
    color = palette[hash(uid) % len(palette)]
    with db() as con:
        try:
            con.execute(
                "INSERT INTO users (id, name, handle, avatar_color, credits, created_at)"
                " VALUES (?,?,?,?,?,?)",
                (uid, name, handle, color, 100, int(time.time()))
            )
        except sqlite3.IntegrityError:
            # handle ya existe, generar uno random
            handle = f"@{uid[:8]}_{secrets.token_hex(2)}"
            con.execute(
                "INSERT INTO users (id, name, handle, avatar_color, credits, created_at)"
                " VALUES (?,?,?,?,?,?)",
                (uid, name, handle, color, 100, int(time.time()))
            )
    return {"token": make_jwt(uid), "user_id": uid, "name": name, "handle": handle, "credits": 100}


@api.get("/api/users/top")
def top_creators(limit: int = 20):
    with db() as con:
        rows = con.execute(
            "SELECT id, name, handle, bio, avatar_color, followers, total_likes, videos_count"
            " FROM users ORDER BY followers DESC LIMIT ?", (limit,)
        ).fetchall()
    return {"creators": [dict(r) for r in rows]}


@api.get("/api/users/{user_id}")
def get_user(user_id: str, viewer: Optional[dict] = Depends(maybe_user)):
    with db() as con:
        u = con.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if not u:
            raise HTTPException(404, "Usuario no encontrado")
        following = False
        if viewer:
            following = bool(con.execute(
                "SELECT 1 FROM follows WHERE follower_id=? AND followee_id=?",
                (viewer["id"], user_id),
            ).fetchone())
        vids = con.execute(
            "SELECT id, caption, thumb_url, likes, views, duration_sec, created_at"
            " FROM videos WHERE author_id=? ORDER BY created_at DESC LIMIT 30",
            (user_id,),
        ).fetchall()
    out = dict(u)
    out["is_following"] = following
    out["videos"] = [dict(v) for v in vids]
    return out


@api.post("/api/users/{user_id}/follow")
def follow_user(user_id: str, viewer: dict = Depends(auth_user)):
    if user_id == viewer["id"]:
        raise HTTPException(400, "No podes seguirte a vos mismo")
    with db() as con:
        existing = con.execute(
            "SELECT 1 FROM follows WHERE follower_id=? AND followee_id=?",
            (viewer["id"], user_id),
        ).fetchone()
        if existing:
            con.execute("DELETE FROM follows WHERE follower_id=? AND followee_id=?", (viewer["id"], user_id))
            con.execute("UPDATE users SET followers = MAX(0, followers - 1) WHERE id=?", (user_id,))
            con.execute("UPDATE users SET following = MAX(0, following - 1) WHERE id=?", (viewer["id"],))
            return {"following": False}
        con.execute(
            "INSERT INTO follows (follower_id, followee_id, created_at) VALUES (?,?,?)",
            (viewer["id"], user_id, int(time.time())),
        )
        con.execute("UPDATE users SET followers = followers + 1 WHERE id=?", (user_id,))
        con.execute("UPDATE users SET following = following + 1 WHERE id=?", (viewer["id"],))
    return {"following": True}


@api.post("/api/users/{user_id}/topup")
def topup(user_id: str, data: TopupIn, viewer: dict = Depends(auth_user)):
    """Stub para integracion con Stripe/PayPal. Cobrar primero, llamar aca despues."""
    if viewer["id"] != user_id:
        raise HTTPException(403, "Solo podes recargar tu propia cuenta")
    with db() as con:
        con.execute("UPDATE users SET credits = credits + ? WHERE id=?", (data.amount, user_id))
        row = con.execute("SELECT credits FROM users WHERE id=?", (user_id,)).fetchone()
    return {"credits": row["credits"]}


# -------------------- Videos --------------------
@api.get("/api/videos/feed")
def feed(limit: int = 12, offset: int = 0, viewer: Optional[dict] = Depends(maybe_user)):
    with db() as con:
        rows = con.execute("""
            SELECT v.*, u.name AS author_name, u.handle AS author_handle, u.avatar_color AS author_color
            FROM videos v JOIN users u ON v.author_id = u.id
            ORDER BY v.created_at DESC LIMIT ? OFFSET ?
        """, (limit, offset)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["liked"] = False
            if viewer:
                liked = con.execute(
                    "SELECT 1 FROM likes WHERE user_id=? AND video_id=?",
                    (viewer["id"], r["id"]),
                ).fetchone()
                d["liked"] = bool(liked)
            out.append(d)
    return {"videos": out, "next_offset": offset + limit if len(out) == limit else None}


@api.get("/api/videos/trending")
def trending(limit: int = 20):
    with db() as con:
        rows = con.execute("""
            SELECT v.*, u.name AS author_name, u.handle AS author_handle, u.avatar_color AS author_color
            FROM videos v JOIN users u ON v.author_id = u.id
            ORDER BY (v.likes + v.gifts_total_credits / 5) DESC LIMIT ?
        """, (limit,)).fetchall()
    return {"videos": [dict(r) for r in rows]}


@api.post("/api/videos")
def create_video(data: VideoIn, viewer: dict = Depends(auth_user)):
    vid = str(uuid.uuid4())[:12]
    with db() as con:
        con.execute("""
            INSERT INTO videos (id, author_id, caption, video_url, thumb_url, duration_sec, tags, created_at)
            VALUES (?,?,?,?,?,?,?,?)
        """, (vid, viewer["id"], data.caption.strip(), data.video_url.strip(),
              (data.thumb_url or "").strip(), data.duration_sec, data.tags or "", int(time.time())))
        con.execute("UPDATE users SET videos_count = videos_count + 1 WHERE id=?", (viewer["id"],))
    return {"id": vid, "ok": True}


@api.get("/api/videos/{video_id}")
def video_detail(video_id: str, viewer: Optional[dict] = Depends(maybe_user)):
    with db() as con:
        v = con.execute("""
            SELECT v.*, u.name AS author_name, u.handle AS author_handle,
                   u.avatar_color AS author_color, u.followers AS author_followers
            FROM videos v JOIN users u ON v.author_id = u.id WHERE v.id=?
        """, (video_id,)).fetchone()
        if not v:
            raise HTTPException(404, "Video no encontrado")
        con.execute("UPDATE videos SET views = views + 1 WHERE id=?", (video_id,))
        liked = False
        if viewer:
            liked = bool(con.execute(
                "SELECT 1 FROM likes WHERE user_id=? AND video_id=?",
                (viewer["id"], video_id),
            ).fetchone())
    out = dict(v)
    out["liked"] = liked
    return out


@api.post("/api/videos/{video_id}/like")
def toggle_like(video_id: str, viewer: dict = Depends(auth_user)):
    with db() as con:
        v = con.execute("SELECT author_id FROM videos WHERE id=?", (video_id,)).fetchone()
        if not v:
            raise HTTPException(404, "Video no encontrado")
        existing = con.execute(
            "SELECT 1 FROM likes WHERE user_id=? AND video_id=?",
            (viewer["id"], video_id),
        ).fetchone()
        if existing:
            con.execute("DELETE FROM likes WHERE user_id=? AND video_id=?", (viewer["id"], video_id))
            con.execute("UPDATE videos SET likes = MAX(0, likes - 1) WHERE id=?", (video_id,))
            con.execute("UPDATE users SET total_likes = MAX(0, total_likes - 1) WHERE id=?", (v["author_id"],))
            new = con.execute("SELECT likes FROM videos WHERE id=?", (video_id,)).fetchone()["likes"]
            return {"liked": False, "likes": new}
        con.execute(
            "INSERT INTO likes (user_id, video_id, created_at) VALUES (?,?,?)",
            (viewer["id"], video_id, int(time.time())),
        )
        con.execute("UPDATE videos SET likes = likes + 1 WHERE id=?", (video_id,))
        con.execute("UPDATE users SET total_likes = total_likes + 1 WHERE id=?", (v["author_id"],))
        new = con.execute("SELECT likes FROM videos WHERE id=?", (video_id,)).fetchone()["likes"]
    return {"liked": True, "likes": new}


@api.get("/api/videos/{video_id}/comments")
def video_comments(video_id: str, limit: int = 50):
    with db() as con:
        rows = con.execute("""
            SELECT c.id, c.text, c.created_at,
                   u.id AS author_id, u.name AS author_name,
                   u.handle AS author_handle, u.avatar_color AS author_color
            FROM comments c JOIN users u ON c.author_id = u.id
            WHERE c.video_id=? ORDER BY c.created_at DESC LIMIT ?
        """, (video_id, limit)).fetchall()
    return {"comments": [dict(r) for r in rows]}


@api.post("/api/videos/{video_id}/comment")
async def add_comment(video_id: str, data: CommentIn, viewer: dict = Depends(auth_user)):
    cid = str(uuid.uuid4())[:12]
    text = data.text.strip()
    if not text:
        raise HTTPException(400, "Comentario vacio")
    with db() as con:
        v = con.execute("SELECT id FROM videos WHERE id=?", (video_id,)).fetchone()
        if not v:
            raise HTTPException(404, "Video no encontrado")
        con.execute("""
            INSERT INTO comments (id, video_id, author_id, text, created_at)
            VALUES (?,?,?,?,?)
        """, (cid, video_id, viewer["id"], text, int(time.time())))
        con.execute("UPDATE videos SET comments_count = comments_count + 1 WHERE id=?", (video_id,))
    payload = {
        "id": cid, "text": text, "created_at": int(time.time()),
        "author_id": viewer["id"], "author_name": viewer["name"],
        "author_handle": viewer["handle"], "author_color": viewer["avatar_color"],
    }
    # Broadcast via socket.io
    await sio.emit("comment", payload, room=video_id)
    return payload


@api.get("/api/gifts")
def list_gifts():
    return {"gifts": [{"key": k, **v} for k, v in GIFTS.items()]}


@api.post("/api/videos/{video_id}/gift")
async def send_gift(video_id: str, data: GiftIn, viewer: dict = Depends(auth_user)):
    gift = GIFTS.get(data.gift_key)
    if not gift:
        raise HTTPException(400, "Regalo invalido")
    cost = gift["credits"]
    with db() as con:
        u = con.execute("SELECT credits FROM users WHERE id=?", (viewer["id"],)).fetchone()
        if not u or u["credits"] < cost:
            raise HTTPException(402, f"Necesitas {cost} credits. Tenes {u['credits'] if u else 0}.")
        v = con.execute("SELECT author_id FROM videos WHERE id=?", (video_id,)).fetchone()
        if not v:
            raise HTTPException(404, "Video no encontrado")
        con.execute("UPDATE users SET credits = credits - ? WHERE id=?", (cost, viewer["id"]))
        # 70% del valor en credits va al creador
        creator_share = int(cost * 0.7)
        con.execute("UPDATE users SET credits = credits + ? WHERE id=?", (creator_share, v["author_id"]))
        con.execute("UPDATE videos SET gifts_total_credits = gifts_total_credits + ? WHERE id=?", (cost, video_id))
        con.execute("""
            INSERT INTO gifts_log (id, from_user_id, to_user_id, video_id, gift_key, credits, created_at)
            VALUES (?,?,?,?,?,?,?)
        """, (str(uuid.uuid4())[:12], viewer["id"], v["author_id"], video_id,
              data.gift_key, cost, int(time.time())))
    payload = {
        "gift": gift, "from_user_id": viewer["id"], "from_name": viewer["name"],
        "value": cost,
    }
    await sio.emit("gift", payload, room=video_id)
    return {"ok": True, "remaining_credits": u["credits"] - cost, **payload}


# ============================================================
# Socket.IO
# ============================================================
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*", logger=False, engineio_logger=False)
_video_viewers: dict[str, set] = {}  # video_id -> set(sid)


@sio.event
async def connect(sid, environ, auth):
    pass


@sio.event
async def disconnect(sid):
    for vid, sids in list(_video_viewers.items()):
        if sid in sids:
            sids.discard(sid)
            await sio.emit("viewer-count", {"count": len(sids)}, room=vid)
            if not sids:
                _video_viewers.pop(vid, None)


@sio.on("join-video")
async def join_video(sid, data):
    vid = (data or {}).get("video_id")
    if not vid:
        return
    await sio.enter_room(sid, vid)
    _video_viewers.setdefault(vid, set()).add(sid)
    await sio.emit("viewer-count", {"count": len(_video_viewers[vid])}, room=vid)


@sio.on("leave-video")
async def leave_video(sid, data):
    vid = (data or {}).get("video_id")
    if not vid:
        return
    await sio.leave_room(sid, vid)
    sids = _video_viewers.get(vid, set())
    sids.discard(sid)
    await sio.emit("viewer-count", {"count": len(sids)}, room=vid)


@sio.on("like-burst")
async def like_burst(sid, data):
    """Cliente envia rafaga de likes (anim). Server broadcastea a la sala."""
    vid = (data or {}).get("video_id")
    if not vid:
        return
    await sio.emit("like-burst", {"x": data.get("x"), "y": data.get("y")}, room=vid, skip_sid=sid)


# ============================================================
# Servir frontend estatico
# ============================================================
if FRONTEND_DIR.exists():
    api.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="frontend_static")

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
# Combinar FastAPI + Socket.IO en una sola ASGI app
# ============================================================
init_db()
app = socketio.ASGIApp(sio, other_asgi_app=api, socketio_path="/socket.io")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=PORT, log_level="info")
