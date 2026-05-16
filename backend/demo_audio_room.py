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

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel

router = APIRouter(prefix="/demo/audio-room", tags=["demo_audio_room"])

TEMPLATE_DIR = Path(__file__).parent / "app_templates" / "audio_room" / "frontend"
SERVE_DIR = Path(__file__).parent / "uploads" / "demo-audio-room"
DEMO_APP_NAME = "Lluvia Audio Live"
DEMO_BRAND_COLOR = "#2563EB"


def _build_demo_cta() -> str:
    """CTA flotante + modal inyectado al final del body del demo.
    Solo aparece en modo demo (DEMO_MODE). El template original NO incluye esto."""
    return r"""
<style>
  .lluvia-demo-cta {
    position: fixed; right: 18px; bottom: 88px; z-index: 9998;
    display: flex; align-items: center; gap: 0.6rem;
    padding: 0.7rem 1.05rem;
    background: linear-gradient(135deg, #2563EB, #7C3AED);
    color: #fff; border-radius: 999px;
    box-shadow: 0 12px 28px rgba(37,99,235,0.45), 0 0 0 4px rgba(255,255,255,0.06);
    font: 600 0.86rem/1.2 system-ui, sans-serif;
    border: 0; cursor: pointer;
    animation: lluviaCtaPulse 2.4s ease-in-out infinite;
  }
  .lluvia-demo-cta:hover { transform: translateY(-2px); box-shadow: 0 16px 36px rgba(37,99,235,0.55); }
  .lluvia-demo-cta .dot { width:8px;height:8px;border-radius:50%;background:#FCA5A5;box-shadow:0 0 0 4px rgba(252,165,165,0.25); animation: lluviaCtaBlink 1.4s infinite; }
  @keyframes lluviaCtaPulse { 0%,100%{ transform: translateY(0)} 50%{transform: translateY(-3px)} }
  @keyframes lluviaCtaBlink { 50%{opacity:0.4} }
  .lluvia-demo-overlay {
    position: fixed; inset: 0; z-index: 10000; background: rgba(2,6,23,0.78);
    display: none; align-items: center; justify-content: center; padding: 1rem;
    backdrop-filter: blur(6px);
  }
  .lluvia-demo-overlay.show { display: flex; }
  .lluvia-demo-modal {
    background: #0F172A; color: #F1F5F9; border-radius: 18px;
    width: 100%; max-width: 420px; padding: 1.6rem 1.4rem;
    box-shadow: 0 32px 64px rgba(0,0,0,0.6); border: 1px solid rgba(255,255,255,0.08);
  }
  .lluvia-demo-modal h3 { margin:0 0 0.3rem 0; font-size: 1.25rem; }
  .lluvia-demo-modal .sub { color:#94A3B8; font-size:0.86rem; margin-bottom:1rem; }
  .lluvia-demo-modal label { display:block; font-size:0.78rem; color:#CBD5E1; margin: 0.8rem 0 0.3rem; letter-spacing:0.04em; text-transform:uppercase; }
  .lluvia-demo-modal input { width:100%; padding:0.7rem 0.85rem; border-radius:10px; background:#1E293B; color:#F8FAFC; border:1px solid #334155; font-size:0.95rem; box-sizing:border-box; }
  .lluvia-demo-modal input:focus { outline:none; border-color:#3B82F6; box-shadow: 0 0 0 3px rgba(59,130,246,0.25); }
  .lluvia-demo-modal .row { display:grid; grid-template-columns: 1fr 110px; gap: 0.5rem; }
  .lluvia-demo-modal .color-swatch { width:38px;height:38px;border-radius:10px;border:2px solid #334155; cursor:pointer; }
  .lluvia-demo-modal .btn-primary { margin-top: 1rem; width:100%; padding:0.8rem; border-radius:12px;
    background: linear-gradient(135deg,#2563EB,#7C3AED); color:#fff; font-weight:700; border:0; cursor:pointer; font-size:0.95rem; }
  .lluvia-demo-modal .btn-primary:hover { filter: brightness(1.08); }
  .lluvia-demo-modal .btn-primary:disabled { opacity:0.55; cursor:wait; }
  .lluvia-demo-modal .cancel { width:100%; margin-top:0.5rem; padding:0.55rem; background:transparent; color:#94A3B8; border:0; cursor:pointer; font-size:0.85rem; }
  .lluvia-demo-modal .err { color:#FCA5A5; font-size:0.82rem; margin-top:0.6rem; min-height:1.2em; }
  .lluvia-demo-modal .price-line { color:#A7F3D0; font-size:0.82rem; margin-top:0.55rem; font-weight:600; }
</style>
<button id="lluvia-demo-cta" class="lluvia-demo-cta" data-testid="demo-cta-floating" onclick="lluviaOpenConvert()">
  <span class="dot"></span>
  <span>¿Te gusta? Ármala con TU marca → 40 oros</span>
</button>
<div id="lluvia-demo-overlay" class="lluvia-demo-overlay" onclick="if(event.target.id==='lluvia-demo-overlay')lluviaCloseConvert()">
  <div class="lluvia-demo-modal">
    <h3>🚀 Tu propia Audio Room en 30 segundos</h3>
    <div class="sub">Te creamos cuenta con 15 oros gratis. Después App Builder Pro la ensambla a tu marca.</div>
    <label>Nombre de tu app</label>
    <input id="lc-app-name" placeholder="ej: Talklatina" maxlength="60" data-testid="demo-cta-app-name"/>
    <label>Color principal</label>
    <div class="row">
      <input id="lc-color-hex" placeholder="#5B8DEF" maxlength="7" value="#5B8DEF" data-testid="demo-cta-color"/>
      <input id="lc-color-pick" type="color" class="color-swatch" value="#5B8DEF" oninput="document.getElementById('lc-color-hex').value=this.value"/>
    </div>
    <label>Tu email</label>
    <input id="lc-email" type="email" placeholder="tucorreo@gmail.com" maxlength="120" data-testid="demo-cta-email"/>
    <label>Contraseña (mín 6 chars)</label>
    <input id="lc-pwd" type="password" placeholder="••••••" maxlength="60" data-testid="demo-cta-password"/>
    <div class="price-line">✓ 15 oros gratis al crear cuenta · La app cuesta 40 oros · Sin tarjeta</div>
    <div class="err" id="lc-err"></div>
    <button id="lc-submit" class="btn-primary" onclick="lluviaSubmitConvert()" data-testid="demo-cta-submit">
      Crear mi cuenta y armar mi app →
    </button>
    <button class="cancel" onclick="lluviaCloseConvert()">Seguir explorando el demo</button>
  </div>
</div>
<script>
  window.lluviaOpenConvert = function() {
    document.getElementById('lluvia-demo-overlay').classList.add('show');
    setTimeout(function(){ document.getElementById('lc-app-name').focus(); }, 100);
  };
  window.lluviaCloseConvert = function() {
    document.getElementById('lluvia-demo-overlay').classList.remove('show');
    document.getElementById('lc-err').textContent = '';
  };
  window.lluviaSubmitConvert = async function() {
    const e = function(id){ return document.getElementById(id); };
    const errBox = e('lc-err');
    const btn = e('lc-submit');
    errBox.textContent = '';
    const app_name = e('lc-app-name').value.trim();
    let brand_color = e('lc-color-hex').value.trim();
    const email = e('lc-email').value.trim();
    const password = e('lc-pwd').value;
    if (!app_name) { errBox.textContent = 'Falta el nombre de la app'; return; }
    if (!/^#[0-9A-Fa-f]{6}$/.test(brand_color)) brand_color = '#5B8DEF';
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) { errBox.textContent = 'Email inválido'; return; }
    if (password.length < 6) { errBox.textContent = 'Contraseña: mínimo 6 caracteres'; return; }
    btn.disabled = true; btn.textContent = 'Creando tu cuenta...';
    try {
      const r = await fetch('/api/demo/audio-room/api/convert', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email, password: password, app_name: app_name, brand_color: brand_color }),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail || 'Error');
      localStorage.setItem('bot_admin_token', j.access_token);
      localStorage.setItem('lluvia_demo_seed', JSON.stringify(j.seed));
      btn.textContent = '✓ Cuenta lista, llevándote al chat...';
      setTimeout(function(){ window.location.href = '/#/chat'; }, 700);
    } catch (err) {
      errBox.textContent = err.message || 'No pude crear tu cuenta';
      btn.disabled = false;
      btn.textContent = 'Crear mi cuenta y armar mi app →';
    }
  };
</script>
"""


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
                    text = text.replace('href="css/', 'href="/api/demo/audio-room-static/css/')
                    text = text.replace('src="js/', 'src="/api/demo/audio-room-static/js/')
                    config_script = (
                        '<script>window.APP_CONFIG={'
                        'API_URL:"/api/demo/audio-room",'
                        'DEMO_MODE:true,'
                        f'BRAND:"{DEMO_APP_NAME}"'
                        '};</script>'
                    )
                    text = text.replace('<script src="/api/demo/audio-room-static/js/api.js">',
                                        config_script + '<script src="/api/demo/audio-room-static/js/api.js">')
                    # Inyectar CTA flotante de conversion + modal
                    cta_html = _build_demo_cta()
                    text = text.replace("</body>", cta_html + "</body>")
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


# ============================================================
# Conversion endpoint: el visitante del demo se registra y vuelve a
# Lluvia App Studio con un seed para que App Builder Pro le arme
# inmediatamente su propia version de la Audio Room.
# ============================================================
class ConvertIn(BaseModel):
    email: str
    password: str
    app_name: str
    brand_color: str = "#5B8DEF"


@router.post("/api/convert")
async def demo_convert(data: ConvertIn, request: Request):
    """Registra al visitante reusando el flujo de /api/auth/register y
    devuelve el access_token + el seed que el frontend va a leer al loguearse.
    Asi el flujo es: demo -> click CTA -> modal -> POST /convert -> redirect a / -> 
    AuthContext detecta el token -> BossConsole detecta el seed -> abre chat con
    app_builder_pro y manda el mensaje automaticamente."""
    from affiliates import register as register_endpoint, RegisterIn
    if not data.email or "@" not in data.email or len(data.password) < 6:
        raise HTTPException(400, "Email invalido o password muy corto (min 6 chars)")
    app_name = (data.app_name or "Mi Audio Room").strip()[:60]
    brand_color = (data.brand_color or "#5B8DEF").strip()[:20]
    try:
        result = await register_endpoint(
            request=request,
            payload=RegisterIn(
                email=data.email.strip().lower()[:120],
                password=data.password,
                name=app_name,
            ),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Error registrando: {str(e)[:120]}")
    return {
        "ok": True,
        "access_token": result["access_token"],
        "user": result["user"],
        "seed": {"app_name": app_name, "brand_color": brand_color},
        "next_url": "/",
    }
