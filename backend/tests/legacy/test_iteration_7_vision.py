"""
Iteration 7 — Vision / Image upload + chat ChatGPT-like UI feature tests.

Covers:
  * POST /api/console/sessions/{id}/upload-image (accept image/* y rechazo de tipos/tamaño)
  * GET  /api/uploads/chat_images/{fname} (StaticFiles mount)
  * POST /api/console/sessions/{id}/messages con image_urls -> vision GPT-4o, cobro 3 oros/img
  * 404 si la sesion no es del usuario
  * Regresion voz: /api/voice/transcribe y /api/voice/tts no rompieron

Credenciales: admin melvinnavas79@gmail.com / Admin#2026
"""
import io
import os
import time
import uuid

import pytest
import requests
from PIL import Image

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://ai-bot-cost-calc.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "melvinnavas79@gmail.com"
ADMIN_PASSWORD = "Admin#2026"


# --------------------------- Fixtures ---------------------------
@pytest.fixture(scope="session")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="session")
def session_id(admin_headers):
    # Crear sesion sobre un agente del catalogo (peluqueria) — admin tiene oros.
    # Probamos agentes habituales del catalogo.
    sid = None
    last = None
    # Listar agentes y tomar el primero disponible
    ra = requests.get(f"{BASE_URL}/api/console/agents", headers=admin_headers, timeout=30)
    assert ra.status_code == 200, f"no se pueden listar agentes: {ra.status_code}"
    payload = ra.json()
    arr = payload.get("agents") if isinstance(payload, dict) else payload
    assert arr, f"sin agentes: {payload}"
    for a in arr:
        ag_id = a.get("id")
        if not ag_id:
            continue
        r = requests.post(f"{BASE_URL}/api/console/sessions",
                          headers=admin_headers, json={"agent_id": ag_id}, timeout=30)
        last = (ag_id, r.status_code, r.text[:200])
        if r.status_code == 200:
            sid = r.json().get("id") or r.json().get("session_id")
            break
    assert sid, f"no se pudo crear sesion: {last}"
    return sid


def _png_bytes(w=64, h=64, color=(255, 80, 80)):
    img = Image.new("RGB", (w, h), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# --------------------------- Upload image ---------------------------
class TestUploadImage:
    def test_upload_png_ok(self, admin_headers, session_id):
        png = _png_bytes()
        files = {"file": ("hello.png", png, "image/png")}
        r = requests.post(f"{BASE_URL}/api/console/sessions/{session_id}/upload-image",
                          headers=admin_headers, files=files, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["url"].startswith("/api/uploads/chat_images/")
        assert data["filename"].endswith(".png")
        assert data["content_type"] == "image/png"
        assert data["size"] == len(png)

        # Static serve
        url_abs = f"{BASE_URL}{data['url']}"
        r2 = requests.get(url_abs, timeout=20)
        assert r2.status_code == 200
        assert r2.headers.get("content-type", "").startswith("image/png")
        assert len(r2.content) == len(png)

    def test_upload_rejects_bad_mime(self, admin_headers, session_id):
        files = {"file": ("notes.txt", b"hello world" * 4, "text/plain")}
        r = requests.post(f"{BASE_URL}/api/console/sessions/{session_id}/upload-image",
                          headers=admin_headers, files=files, timeout=20)
        assert r.status_code == 400, r.text
        assert "no soportado" in r.text.lower() or "tipo" in r.text.lower()

    def test_upload_rejects_too_large(self, admin_headers, session_id):
        # generar PNG > 8MB con ruido (random) para que no comprima a nada
        big_bytes = os.urandom(8 * 1024 * 1024 + 1024)
        files = {"file": ("big.png", big_bytes, "image/png")}
        r = requests.post(f"{BASE_URL}/api/console/sessions/{session_id}/upload-image",
                          headers=admin_headers, files=files, timeout=60)
        assert r.status_code == 413, f"esperaba 413, obtuve {r.status_code} {r.text[:200]}"

    def test_upload_404_when_session_not_owned(self, admin_headers):
        fake_sid = f"TEST_fake_{uuid.uuid4().hex[:8]}"
        files = {"file": ("x.png", _png_bytes(), "image/png")}
        r = requests.post(f"{BASE_URL}/api/console/sessions/{fake_sid}/upload-image",
                          headers=admin_headers, files=files, timeout=20)
        assert r.status_code == 404, r.text

    def test_upload_requires_auth(self, session_id):
        files = {"file": ("x.png", _png_bytes(), "image/png")}
        r = requests.post(f"{BASE_URL}/api/console/sessions/{session_id}/upload-image",
                          files=files, timeout=20)
        assert r.status_code in (401, 403)


# --------------------------- Send message con vision ---------------------------
class TestSendMessageVision:
    def test_message_with_image_charges_vision_and_returns_image_urls(self, admin_headers, session_id):
        # 1. Saldo previo
        r0 = requests.get(f"{BASE_URL}/api/console/credits/me", headers=admin_headers, timeout=20)
        assert r0.status_code == 200
        balance_before = r0.json().get("balance", 0)

        # 2. Subir imagen
        png = _png_bytes(w=96, h=96, color=(20, 200, 80))
        up = requests.post(f"{BASE_URL}/api/console/sessions/{session_id}/upload-image",
                           headers=admin_headers,
                           files={"file": ("green.png", png, "image/png")},
                           timeout=30)
        assert up.status_code == 200
        img_url = up.json()["url"]

        # 3. Enviar mensaje multimodal
        body = {"text": "Que ves en esta imagen? Responde en 1 frase.", "image_urls": [img_url]}
        r = requests.post(f"{BASE_URL}/api/console/sessions/{session_id}/messages",
                          headers=admin_headers, json=body, timeout=90)
        assert r.status_code == 200, r.text
        data = r.json()
        # cost_oros debe incluir base(1) + vision(3*1) = 4 (sin tools)
        cost = data.get("cost_oros")
        assert cost is not None
        assert cost >= 4, f"esperaba cost>=4 (1 base + 3 vision), got {cost}"

        # 4. Verificar que el mensaje del user persiste con image_urls
        rs = requests.get(f"{BASE_URL}/api/console/sessions/{session_id}",
                          headers=admin_headers, timeout=20)
        assert rs.status_code == 200
        msgs = rs.json().get("messages", [])
        user_msgs_with_img = [m for m in msgs if m.get("role") == "user" and m.get("image_urls")]
        assert user_msgs_with_img, f"no encontre user msg con image_urls. msgs={[m.get('role') for m in msgs]}"
        assert img_url in user_msgs_with_img[-1]["image_urls"]

        # 5. Hay respuesta del asistente con contenido
        assistant_msgs = [m for m in msgs if m.get("role") == "assistant"]
        assert assistant_msgs, "no hay respuesta del asistente"
        last_assistant = assistant_msgs[-1]
        assert last_assistant.get("content"), "respuesta del asistente vacia"
        # Heuristica: la respuesta deberia mencionar verde / green / color porque la imagen es verde
        text_low = last_assistant["content"].lower()
        print(f"GPT-4o vision response: {last_assistant['content'][:200]}")
        # No forzamos string especifico para no ser flaky, pero verificamos longitud razonable
        assert len(text_low) >= 5

        # 6. Admin no descuenta saldo (admin_free), validamos solo cost_oros del response
        # (los tests de credits.charge para admins son intencionalmente $0)
        r1 = requests.get(f"{BASE_URL}/api/console/credits/me", headers=admin_headers, timeout=20)
        assert r1.status_code == 200
        # No assert sobre balance: admins son "admin_free" en credits.charge()

    def test_message_without_image_not_charge_vision(self, admin_headers, session_id):
        body = {"text": "Hola, solo decime 'ok' por favor."}
        r = requests.post(f"{BASE_URL}/api/console/sessions/{session_id}/messages",
                          headers=admin_headers, json=body, timeout=60)
        assert r.status_code == 200, r.text
        cost = r.json().get("cost_oros", 0)
        # Sin imagenes y sin tools, base = 1
        assert cost < 4, f"esperaba cost<4 (sin vision), got {cost}"


# --------------------------- Regresion voz ---------------------------
class TestVoiceRegression:
    def test_transcribe_endpoint_exists(self, admin_headers):
        # No mandamos audio real, pero el endpoint debe existir (no 404).
        # Esperamos 400/422 por payload faltante, NO 404 ni 500.
        r = requests.post(f"{BASE_URL}/api/voice/transcribe", headers=admin_headers, timeout=20)
        assert r.status_code != 404, "endpoint voice/transcribe no existe"
        assert r.status_code != 500, f"500 inesperado: {r.text[:200]}"
        # Aceptamos 400/415/422
        assert r.status_code in (400, 415, 422), f"status raro: {r.status_code} {r.text[:200]}"

    def test_tts_endpoint_works_or_exists(self, admin_headers):
        # POST /api/voice/tts con texto. Si lo procesa OK devuelve audio binario; si no, no 404/500.
        r = requests.post(f"{BASE_URL}/api/voice/tts", headers=admin_headers,
                          json={"text": "hola mundo"}, timeout=60)
        assert r.status_code != 404, "endpoint voice/tts no existe"
        # Aceptamos 200 (con audio) o 4xx funcional pero NO 500
        assert r.status_code < 500, f"5xx en tts: {r.status_code} {r.text[:200]}"
        if r.status_code == 200:
            ct = r.headers.get("content-type", "")
            assert "audio" in ct or "mpeg" in ct or "octet" in ct or "json" in ct, ct
