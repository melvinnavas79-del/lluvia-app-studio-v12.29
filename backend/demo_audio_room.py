"""
Demo público de la Audio Room — sirve el frontend del template + canned API
en /api/demo/audio-room/* para que cualquier visitante de la landing pueda
navegar las 4 pantallas reales antes de pagar.

NO usa WebRTC ni Socket.IO. Datos canned para mostrar el producto en accion.
"""

import os
import time
import re
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse

router = APIRouter(prefix="/demo/audio-room", tags=["demo_audio_room"])

TEMPLATE_DIR = Path(__file__).parent / "app_templates" / "audio_room" / "frontend"
SERVE_DIR = Path(__file__).parent / "uploads" / "demo-audio-room"
DEMO_APP_NAME = "Lluvia Audio Live"
DEMO_BRAND_COLOR = "#2563EB"


# ============================================================
# Setup: copiar template a una carpeta servible (con placeholders ya reemplazados)
# ============================================================
def _prepare_serve_dir():
    """Materializa los archivos del template con placeholders reemplazados +
    inyecta APP_CONFIG en index.html. Se ejecuta una vez al import."""
    if SERVE_DIR.exists():
        shutil.rmtree(SERVE_DIR)
    SERVE_DIR.mkdir(parents=True, exist_ok=True)

    for root, dirs, files in os.walk(TEMPLATE_DIR):
        rel = Path(root).relative_to(TEMPLATE_DIR)
        (SERVE_DIR / rel).mkdir(parents=True, exist_ok=True)
        for fname in files:
            src = Path(root) / fname
            dst = SERVE_DIR / rel / fname
            try:
                text = src.read_text(encoding="utf-8")
                text = text.replace("{{APP_NAME}}", DEMO_APP_NAME).replace("{{BRAND_COLOR}}", DEMO_BRAND_COLOR)
                if fname == "index.html":
                    # Reescribir paths de css/js para apuntar a /api/demo/audio-room-static/
                    # (StaticFiles mount que respeta content-types)
                    text = text.replace('href="css/', 'href="/api/demo/audio-room-static/css/')
                    text = text.replace('src="js/', 'src="/api/demo/audio-room-static/js/')
                    # Inyectar APP_CONFIG antes de api.js
                    config_script = (
                        '<script>window.APP_CONFIG={'
                        'API_URL:"/api/demo/audio-room",'
                        'DEMO_MODE:true,'
                        f'BRAND:"{DEMO_APP_NAME}"'
                        '};</script>'
                    )
                    text = text.replace('<script src="/api/demo/audio-room-static/js/api.js">',
                                        config_script + '<script src="/api/demo/audio-room-static/js/api.js">')
                    banner = (
                        '<div style="position:fixed;top:0;left:0;right:0;z-index:9999;'
                        'background:linear-gradient(135deg,#2563EB,#7C3AED);color:#fff;'
                        'padding:8px 16px;text-align:center;font:600 13px/1.4 system-ui;'
                        'box-shadow:0 2px 8px rgba(0,0,0,0.2)">'
                        'DEMO PUBLICO · Esta app la ensambla App Builder Pro en 30 segundos · '
                        '<a href="/" style="color:#fff;text-decoration:underline">Volver a Lluvia App Studio</a>'
                        '</div>'
                        '<style>body{padding-top:42px}</style>'
                    )
                    text = text.replace("<body>", "<body>" + banner)
                dst.write_text(text, encoding="utf-8")
            except UnicodeDecodeError:
                shutil.copy2(src, dst)


_prepare_serve_dir()


# ============================================================
# StaticFiles SE NECESITA registrar en la app principal (server.py)
# porque APIRouter no soporta mount() directo. Exportamos SERVE_DIR
# para que server.py haga app.mount("/api/demo/audio-room", StaticFiles(...))
# ============================================================
# Igual ofrecemos un fallback para index.html via FileResponse en este router
# (algunas configuraciones de ingress prefieren routes a mounts).
@router.get("/")
async def demo_index_fallback():
    """Redirige al StaticFiles mount que sirve el index con content-types correctos."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/api/demo/audio-room-static/", status_code=302)


# ============================================================
# Canned API - datos fake para que el frontend renderice
# ============================================================
DEMO_ROOMS = [
    {
        "id": "demo-room-001", "host_id": "demo-host-1", "host_name": "Sofia DJ",
        "title": "Late night beats - latin urban edition",
        "description": "Mezclas de reggaeton y trap latino para tu finde",
        "category": "Musica", "language": "es", "monetization": "free", "price_credits": 0,
        "is_live": 1, "listeners_count": 248, "speakers_count": 3,
        "created_at": int(time.time()) - 1800,
    },
    {
        "id": "demo-room-002", "host_id": "demo-host-2", "host_name": "Carlos Tech",
        "title": "Como armar un SaaS sin equipo en 2026",
        "description": "Reflexiones de un founder solo despues de 200k MRR",
        "category": "Tecnologia", "language": "es", "monetization": "premium", "price_credits": 50,
        "is_live": 1, "listeners_count": 89, "speakers_count": 2,
        "created_at": int(time.time()) - 600,
    },
    {
        "id": "demo-room-003", "host_id": "demo-host-3", "host_name": "Lucia Mindful",
        "title": "Meditacion guiada antes de dormir",
        "description": "20 minutos de respiracion + sonidos binaurales",
        "category": "Bienestar", "language": "es", "monetization": "free", "price_credits": 0,
        "is_live": 1, "listeners_count": 412, "speakers_count": 1,
        "created_at": int(time.time()) - 300,
    },
    {
        "id": "demo-room-004", "host_id": "demo-host-4", "host_name": "Diego Sportscaster",
        "title": "Analisis post-partido: clasico sudamericano",
        "description": "Hablamos de las jugadas clave con dos panelistas",
        "category": "Deportes", "language": "es", "monetization": "free", "price_credits": 0,
        "is_live": 1, "listeners_count": 156, "speakers_count": 4,
        "created_at": int(time.time()) - 7200,
    },
    {
        "id": "demo-room-005", "host_id": "demo-host-5", "host_name": "Maria Founder",
        "title": "Q&A: como conseguir tus primeros 100 clientes",
        "description": "Pregunta lo que quieras sobre tu negocio",
        "category": "Negocios", "language": "es", "monetization": "premium", "price_credits": 100,
        "is_live": 1, "listeners_count": 67, "speakers_count": 1,
        "created_at": int(time.time()) - 120,
    },
    {
        "id": "demo-room-006", "host_id": "demo-host-1", "host_name": "Sofia DJ",
        "title": "English practice - casual chat for B1/B2 learners",
        "description": "Practice your English with native speakers",
        "category": "English", "language": "en", "monetization": "free", "price_credits": 0,
        "is_live": 1, "listeners_count": 33, "speakers_count": 2,
        "created_at": int(time.time()) - 900,
    },
]

DEMO_USERS = {
    "demo-host-1": {"id": "demo-host-1", "name": "Sofia DJ", "handle": "sofiadj",
                    "bio": "DJ residente, musica latina urbana. Hago sets en vivo cada finde.",
                    "color": "#EC4899", "followers": 12400, "rooms_hosted": 87, "total_listeners": 45000},
    "demo-host-2": {"id": "demo-host-2", "name": "Carlos Tech", "handle": "carlostech",
                    "bio": "Founder solo. SaaS B2B. 200k MRR. Hablo de productos y growth.",
                    "color": "#2563EB", "followers": 8900, "rooms_hosted": 54, "total_listeners": 28000},
    "demo-host-3": {"id": "demo-host-3", "name": "Lucia Mindful", "handle": "luciamind",
                    "bio": "Coach de meditacion. Salas para descansar mejor.",
                    "color": "#10B981", "followers": 15700, "rooms_hosted": 124, "total_listeners": 62000},
    "demo-host-4": {"id": "demo-host-4", "name": "Diego Sportscaster", "handle": "diegosports",
                    "bio": "Periodista deportivo. Analisis en vivo de futbol sudamericano.",
                    "color": "#F59E0B", "followers": 6300, "rooms_hosted": 41, "total_listeners": 19500},
    "demo-host-5": {"id": "demo-host-5", "name": "Maria Founder", "handle": "mariafounder",
                    "bio": "Mentora de startups. Q&A semanal para founders early-stage.",
                    "color": "#8B5CF6", "followers": 4200, "rooms_hosted": 22, "total_listeners": 8800},
}


@router.post("/api/users/anonymous")
async def demo_anonymous(data: dict):
    name = (data.get("name") or "Invitado").strip()[:40]
    uid = "guest-" + re.sub(r"[^a-z0-9]", "", name.lower())[:10] + str(int(time.time()))[-4:]
    user = {
        "id": uid, "name": name, "handle": name.lower().replace(" ", ""),
        "bio": "Visitante del demo de Lluvia Audio Live",
        "color": "#5B8DEF", "followers": 0, "rooms_hosted": 0, "total_listeners": 0,
        "credits": 100, "created_at": int(time.time()),
    }
    return {"token": "demo-token-" + uid, "user": user}


@router.get("/api/users/top")
async def demo_top(limit: int = 10):
    sorted_users = sorted(DEMO_USERS.values(), key=lambda u: -u["followers"])[:max(1, min(10, limit))]
    return {"users": sorted_users}


@router.get("/api/users/{user_id}")
async def demo_user(user_id: str):
    if user_id in DEMO_USERS:
        return DEMO_USERS[user_id]
    if user_id.startswith("guest-"):
        return {
            "id": user_id, "name": "Invitado", "handle": "invitado",
            "bio": "Visitante del demo", "color": "#5B8DEF",
            "followers": 0, "rooms_hosted": 0, "total_listeners": 0,
        }
    raise HTTPException(404, "Usuario no encontrado")


@router.post("/api/users/{user_id}/follow")
async def demo_follow(user_id: str):
    return {"ok": True, "demo_note": "En modo demo el follow no persiste."}


@router.get("/api/rooms")
async def demo_rooms(category: str | None = None, host_id: str | None = None,
                     sort: str | None = None, limit: int = 20):
    rooms = list(DEMO_ROOMS)
    if category and category.lower() != "todas":
        rooms = [r for r in rooms if r["category"].lower() == category.lower()]
    if host_id:
        rooms = [r for r in rooms if r["host_id"] == host_id]
    if sort == "listeners":
        rooms.sort(key=lambda r: -r["listeners_count"])
    else:
        rooms.sort(key=lambda r: -r["created_at"])
    return {"rooms": rooms[:max(1, min(50, limit))]}


@router.get("/api/rooms/{room_id}")
async def demo_room_detail(room_id: str):
    room = next((r for r in DEMO_ROOMS if r["id"] == room_id), None)
    if not room:
        raise HTTPException(404, "Sala no encontrada")
    d = dict(room)
    d["has_access"] = True
    d["speakers"] = [
        {"id": room["host_id"], "name": room["host_name"], "role": "host",
         "muted": False, "is_speaking": True},
    ]
    if room["speakers_count"] > 1:
        d["speakers"].append({
            "id": "speaker-2", "name": "Andrea co-host", "role": "speaker",
            "muted": False, "is_speaking": False,
        })
    d["listeners"] = [
        {"id": f"l-{i}", "name": n}
        for i, n in enumerate(["Pedro", "Ana", "Luis", "Sara", "Tomas", "Vale"][:6])
    ]
    return d


@router.delete("/api/rooms/{room_id}")
async def demo_close_room(room_id: str):
    return {"ok": True}


@router.post("/api/rooms")
async def demo_create_room(data: dict):
    return {
        "id": "demo-created-" + str(int(time.time())),
        "ok": True,
        "demo_note": "En modo demo no creas salas reales. Deploy esta misma app a Railway para tener tu propio Clubhouse.",
    }


@router.post("/api/rooms/{room_id}/purchase")
async def demo_purchase(room_id: str):
    return {"ok": True, "remaining_credits": 50}


@router.get("/api/health")
async def demo_health():
    return {"ok": True, "mode": "demo", "rooms": len(DEMO_ROOMS), "users": len(DEMO_USERS)}
