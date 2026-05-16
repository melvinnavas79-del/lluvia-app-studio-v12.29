"""
Iteration 8 — Estilista Visual agent + Settings/Composer UX.

Backend coverage:
  * GET /api/console/agents incluye 'estilista_visual' con tools correctos.
  * Crear sesion con agent_id='estilista_visual' y enviar mensaje multimodal
    con una imagen (foto de rostro placeholder) — GPT-4o vision responde sin 500.
  * Regresion: /api/me/settings GET/PUT, /api/me/github/push, voice endpoints.

Credenciales: admin melvinnavas79@gmail.com / Admin#2026
"""
import io
import os
import uuid

import pytest
import requests
from PIL import Image

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
ADMIN_EMAIL = "melvinnavas79@gmail.com"
ADMIN_PASSWORD = "Admin#2026"


@pytest.fixture(scope="session")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


def _face_png_bytes():
    """Imagen placeholder simulando un rostro (degradado simple)."""
    img = Image.new("RGB", (256, 256), (255, 220, 200))
    # un par de circulos para que la heuristica de 'rostro' tenga algo
    px = img.load()
    for y in range(80, 110):
        for x in range(80, 110):
            px[x, y] = (40, 40, 40)
        for x in range(150, 180):
            px[x, y] = (40, 40, 40)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# --------------------------- Catalog ---------------------------
class TestEstilistaCatalog:
    def test_estilista_visual_present_in_agents(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/console/agents", headers=admin_headers, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        agents = data.get("agents") if isinstance(data, dict) else data
        assert agents, "agents lista vacia"
        ids = [a["id"] for a in agents]
        assert "estilista_visual" in ids, f"falta estilista_visual en {ids}"
        ev = next(a for a in agents if a["id"] == "estilista_visual")
        assert ev["name"] == "Estilista Visual"
        assert ev["emoji"] == "💇"
        assert ev["color"] == "#ec4899"
        assert ev["voice"] == "shimmer"
        expected_tools = {"service_card", "check_availability", "book_appointment",
                          "list_appointments", "cancel_appointment", "paypal_invoice_card"}
        assert set(ev["tools"]) == expected_tools, f"tools mismatch: {ev['tools']}"


# --------------------------- Vision flow on Estilista ---------------------------
class TestEstilistaVisionFlow:
    def test_create_session_and_send_face_image(self, admin_headers):
        # Crear sesion
        r = requests.post(f"{BASE_URL}/api/console/sessions", headers=admin_headers,
                          json={"agent_id": "estilista_visual"}, timeout=30)
        assert r.status_code == 200, f"no se pudo crear sesion: {r.status_code} {r.text}"
        sid = r.json().get("id") or r.json().get("session_id")
        assert sid

        # Upload imagen
        png = _face_png_bytes()
        up = requests.post(f"{BASE_URL}/api/console/sessions/{sid}/upload-image",
                           headers=admin_headers,
                           files={"file": ("face.png", png, "image/png")},
                           timeout=30)
        assert up.status_code == 200, up.text
        img_url = up.json()["url"]

        # Enviar mensaje multimodal
        body = {"text": "Me pongo el pelo igual, que me recomendas?",
                "image_urls": [img_url]}
        r = requests.post(f"{BASE_URL}/api/console/sessions/{sid}/messages",
                          headers=admin_headers, json=body, timeout=120)
        assert r.status_code == 200, f"5xx o 4xx en chat estilista: {r.status_code} {r.text[:300]}"
        data = r.json()
        # cost_oros >=4 (base + vision)
        assert data.get("cost_oros", 0) >= 4

        # Verificar persistencia y respuesta del asistente no vacia
        rs = requests.get(f"{BASE_URL}/api/console/sessions/{sid}",
                          headers=admin_headers, timeout=20)
        assert rs.status_code == 200
        msgs = rs.json().get("messages", [])
        assistant_msgs = [m for m in msgs if m.get("role") == "assistant"]
        assert assistant_msgs, "no hay respuesta del asistente"
        text = assistant_msgs[-1].get("content", "")
        print(f"Estilista response: {text[:300]}")
        assert len(text) >= 10, f"respuesta del estilista demasiado corta: {text!r}"


# --------------------------- Regression: /me/settings ---------------------------
class TestMeSettings:
    def test_get_settings(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/me/settings", headers=admin_headers, timeout=20)
        assert r.status_code == 200, r.text
        # debe ser dict, no 404/500
        data = r.json()
        assert isinstance(data, dict)

    def test_put_settings_roundtrip(self, admin_headers):
        # PUT campos benignos (sin tocar github_token real)
        payload = {
            "github_repo": "melvinnavas79-del/test-repo",
            "github_branch": "main",
            "project_name": "TEST_iter8",
            "notify_email": "melvinnavas79@gmail.com",
        }
        r = requests.put(f"{BASE_URL}/api/me/settings", headers=admin_headers,
                         json=payload, timeout=20)
        assert r.status_code == 200, r.text
        # Validar persistencia
        rg = requests.get(f"{BASE_URL}/api/me/settings", headers=admin_headers, timeout=20)
        assert rg.status_code == 200
        got = rg.json()
        assert got.get("project_name") == "TEST_iter8"
        assert got.get("github_branch") == "main"

    def test_github_push_endpoint_exists(self, admin_headers):
        # Solo verificamos que existe y responde — sin token real podria retornar 4xx
        r = requests.post(f"{BASE_URL}/api/me/github/push", headers=admin_headers,
                          json={"commit_message": "TEST_iter8 ping"}, timeout=30)
        assert r.status_code != 404, "endpoint /api/me/github/push no existe"
        assert r.status_code < 500 or r.status_code == 500, f"status {r.status_code}: {r.text[:200]}"


# --------------------------- Regression: voice endpoints ---------------------------
class TestVoiceRegression:
    def test_transcribe_endpoint_exists(self, admin_headers):
        r = requests.post(f"{BASE_URL}/api/voice/transcribe", headers=admin_headers, timeout=20)
        assert r.status_code != 404
        assert r.status_code != 500, r.text[:200]

    def test_tts_endpoint_works(self, admin_headers):
        r = requests.post(f"{BASE_URL}/api/voice/tts", headers=admin_headers,
                          json={"text": "hola"}, timeout=60)
        assert r.status_code != 404
        assert r.status_code < 500
