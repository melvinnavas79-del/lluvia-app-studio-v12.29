"""
============================================================
GMAIL OAUTH2 INTEGRATION · Lluvia App Studio
============================================================
Flujo OAuth2 estandar Google para que el "Agente Soporte Maestro"
pueda leer y responder correos del cliente 24/7.

Endpoints:
  GET  /api/integrations/gmail/oauth/start     -> redirige a Google consent
  GET  /api/integrations/gmail/oauth/callback  <- Google redirige aqui (REDIRECT URI)
  GET  /api/integrations/gmail/status          -> ver si el admin vincul ya su Gmail
  POST /api/integrations/gmail/disconnect      -> borra tokens

REQUIERE en /app/backend/.env:
  GOOGLE_CLIENT_ID=...
  GOOGLE_CLIENT_SECRET=...
  GMAIL_OAUTH_REDIRECT_URI=https://<dominio>/api/integrations/gmail/oauth/callback
"""

import os
import logging
import secrets
import urllib.parse
from datetime import datetime, timezone, timedelta
from typing import Optional

import requests
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, HTMLResponse

from auth import get_current_user

logger = logging.getLogger("gmail_integration")
router = APIRouter(prefix="/integrations/gmail", tags=["gmail"])

_db_ref: dict = {"db": None}


def set_db(db) -> None:
    _db_ref["db"] = db


SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/userinfo.email",
]

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


def _client_id() -> str:
    return os.environ.get("GOOGLE_CLIENT_ID", "")


def _client_secret() -> str:
    return os.environ.get("GOOGLE_CLIENT_SECRET", "")


def _redirect_uri(request: Request) -> str:
    """Permite override por env. Si no hay env, autodetecta desde el request."""
    env_uri = os.environ.get("GMAIL_OAUTH_REDIRECT_URI", "").strip()
    if env_uri:
        return env_uri
    base = str(request.base_url).rstrip("/")
    return f"{base}/api/integrations/gmail/oauth/callback"


# ============================================================
# START — redirige al admin al consent de Google
# ============================================================
@router.get("/oauth/start")
async def oauth_start(request: Request, user: dict = Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Solo admin puede vincular Gmail Maestro")
    if not _client_id() or not _client_secret():
        raise HTTPException(
            status_code=503,
            detail="Falta configurar GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET en backend/.env",
        )

    state = secrets.token_urlsafe(24)
    db = _db_ref["db"]
    await db.gmail_oauth_states.insert_one({
        "state": state,
        "user_id": user["id"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
    })

    params = {
        "client_id": _client_id(),
        "redirect_uri": _redirect_uri(request),
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",  # fuerza refresh_token
        "state": state,
    }
    url = f"{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"
    return RedirectResponse(url, status_code=302)


# ============================================================
# CALLBACK — Google redirige aca con ?code=... &state=...
# ESTA ES LA REDIRECT URI QUE EL CLIENTE TIENE QUE PEGAR EN
# GOOGLE CLOUD CONSOLE > Credenciales > URIs de redireccionamiento.
# ============================================================
@router.get("/oauth/callback")
async def oauth_callback(request: Request,
                         code: Optional[str] = None,
                         state: Optional[str] = None,
                         error: Optional[str] = None):
    if error:
        return _err_page(f"Google devolvio error: {error}")
    if not code or not state:
        return _err_page("Faltan parametros code/state")

    db = _db_ref["db"]
    st = await db.gmail_oauth_states.find_one({"state": state}, {"_id": 0})
    if not st:
        return _err_page("State invalido o expirado. Reintenta la vinculacion.")
    await db.gmail_oauth_states.delete_one({"state": state})

    # Intercambiar code por tokens
    try:
        r = requests.post(GOOGLE_TOKEN_URL, data={
            "code": code,
            "client_id": _client_id(),
            "client_secret": _client_secret(),
            "redirect_uri": _redirect_uri(request),
            "grant_type": "authorization_code",
        }, timeout=15)
        if r.status_code != 200:
            logger.error(f"Gmail token exchange fallo: {r.status_code} {r.text[:300]}")
            return _err_page(f"No se pudo intercambiar el code ({r.status_code}). Revisa que el Redirect URI en Google Console coincida exactamente.")
        tk = r.json()
    except Exception as e:
        logger.exception(f"Gmail token exchange exception: {e}")
        return _err_page(f"Error de red contra Google: {str(e)[:200]}")

    # Obtener email del admin de Google
    try:
        u = requests.get(GOOGLE_USERINFO_URL, headers={
            "Authorization": f"Bearer {tk.get('access_token','')}"
        }, timeout=10)
        google_email = u.json().get("email", "") if u.status_code == 200 else ""
    except Exception:
        google_email = ""

    # Guardar en la coleccion gmail_accounts (un solo registro por user_id)
    await db.gmail_accounts.update_one(
        {"user_id": st["user_id"]},
        {"$set": {
            "user_id": st["user_id"],
            "google_email": google_email,
            "access_token": tk.get("access_token"),
            "refresh_token": tk.get("refresh_token"),
            "token_type": tk.get("token_type", "Bearer"),
            "expires_in": tk.get("expires_in", 3600),
            "scope": tk.get("scope", ""),
            "linked_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )
    logger.info(f"Gmail vinculado para user {st['user_id']} -> {google_email}")
    return _ok_page(google_email)


@router.get("/status")
async def status(user: dict = Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="admin only")
    db = _db_ref["db"]
    acc = await db.gmail_accounts.find_one(
        {"user_id": user["id"]},
        {"_id": 0, "access_token": 0, "refresh_token": 0},
    )
    return {
        "linked": bool(acc),
        "client_id_configured": bool(_client_id()),
        "client_secret_configured": bool(_client_secret()),
        "redirect_uri_preview": "https://ai-bot-cost-calc.preview.emergentagent.com/api/integrations/gmail/oauth/callback",
        "redirect_uri_production": "https://lluvia-app-studio.lluvia-live.com/api/integrations/gmail/oauth/callback",
        "account": acc or None,
    }


@router.post("/disconnect")
async def disconnect(user: dict = Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="admin only")
    db = _db_ref["db"]
    res = await db.gmail_accounts.delete_one({"user_id": user["id"]})
    return {"ok": True, "deleted": res.deleted_count}


# ============================================================
# Paginas HTML auxiliares
# ============================================================
def _html(title: str, body_html: str) -> HTMLResponse:
    return HTMLResponse(f"""<!doctype html>
<html lang="es"><head>
<meta charset="utf-8"><title>{title}</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 540px; margin: 4rem auto;
         padding: 2rem; line-height: 1.6; text-align: center; background: #FDFBF7;
         color: #111827; }}
  .card {{ background: #fff; border: 1px solid #E7E5E0; border-radius: 16px;
          padding: 2rem; box-shadow: 0 2px 8px rgba(0,0,0,0.04); }}
  h1 {{ margin: 0.5rem 0; letter-spacing: -0.02em; }}
  a {{ color: #2563EB; }}
  .ok {{ color: #059669; font-size: 2rem; }}
  .err {{ color: #DC2626; font-size: 2rem; }}
</style></head><body>
<div class="card">{body_html}</div></body></html>""")


def _ok_page(email: str) -> HTMLResponse:
    return _html("Gmail vinculado", f"""
<div class="ok">✓</div>
<h1>Gmail vinculado correctamente</h1>
<p>El Agente Maestro de Gmail ya puede leer y responder correos en nombre de <strong>{email or 'tu cuenta'}</strong>.</p>
<p><a href="/">Volver al panel</a></p>""")


def _err_page(msg: str) -> HTMLResponse:
    return _html("Error vinculando Gmail", f"""
<div class="err">✕</div>
<h1>No se pudo vincular Gmail</h1>
<p>{msg}</p>
<p><a href="/">Volver al panel</a></p>""")
