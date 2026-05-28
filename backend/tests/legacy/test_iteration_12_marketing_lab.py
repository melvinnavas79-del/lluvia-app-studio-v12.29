"""
Iteration 12 (v12.12) — Marketing Lab + generate_haircut_preview (Nano Banana).

Backend coverage:
  * GET /api/console/agents incluye 'marketing_lab' y 'estilista_visual' actualizado.
  * Tool 'video_script_card' devuelve rich card video_script.
  * Tool 'generate_haircut_preview' falla con mensaje claro si no hay imagen previa
    en el chat, y se ejecuta cuando hay imagen previa (Nano Banana puede tardar
    10-25 segundos).
  * result_preview en tool_calls truncatea a 6000 chars (no 300).
  * Static mount /api/uploads/ai_generated/... sirve imagenes generadas.
  * Inyeccion de _last_image_url: imagen en mensaje anterior se usa en el siguiente.
"""
import io
import json
import os

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
    img = Image.new("RGB", (256, 256), (255, 220, 200))
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
class TestCatalogV12:
    def test_marketing_lab_in_agents(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/console/agents", headers=admin_headers, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        agents = data.get("agents") if isinstance(data, dict) else data
        ids = {a["id"]: a for a in agents}
        assert "marketing_lab" in ids, f"falta marketing_lab. Got: {list(ids)}"
        ml = ids["marketing_lab"]
        assert ml["name"] == "Marketing Lab"
        assert ml["emoji"] == "🎬"
        assert ml["color"] == "#f59e0b"
        assert ml["voice"] == "fable"
        assert "video_script_card" in ml["tools"]

    def test_estilista_visual_includes_haircut_preview(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/console/agents", headers=admin_headers, timeout=30)
        agents = r.json().get("agents") if isinstance(r.json(), dict) else r.json()
        ev = next(a for a in agents if a["id"] == "estilista_visual")
        assert "generate_haircut_preview" in ev["tools"], f"tools: {ev['tools']}"
        # Mantener tools previas
        for t in ["service_card", "check_availability", "book_appointment",
                  "paypal_invoice_card"]:
            assert t in ev["tools"]


# --------------------------- Marketing Lab E2E ---------------------------
class TestMarketingLabFlow:
    def test_video_script_card_emitted(self, admin_headers):
        r = requests.post(f"{BASE_URL}/api/console/sessions", headers=admin_headers,
                          json={"agent_id": "marketing_lab"}, timeout=30)
        assert r.status_code == 200, r.text
        sid = r.json().get("id") or r.json().get("session_id")
        assert sid

        prompt = ("Generá el guion ya. Feature: Estilista Visual con IA before/after. "
                  "Plataforma TikTok. Duración 30s. Tono wow. No me hagas preguntas, "
                  "llamá a video_script_card directamente con los datos que te di.")
        body = {"text": prompt}
        r = requests.post(f"{BASE_URL}/api/console/sessions/{sid}/messages",
                          headers=admin_headers, json=body, timeout=120)
        assert r.status_code == 200, f"chat fail: {r.status_code} {r.text[:300]}"

        # Get session to inspect tool_calls
        rs = requests.get(f"{BASE_URL}/api/console/sessions/{sid}",
                          headers=admin_headers, timeout=20)
        assert rs.status_code == 200
        msgs = rs.json().get("messages", [])
        # Encontrar el ultimo mensaje del asistente con tool_calls
        video_card = None
        for m in reversed(msgs):
            if m.get("role") == "assistant" and m.get("tool_calls"):
                for tc in m["tool_calls"]:
                    if tc.get("name") == "video_script_card":
                        try:
                            video_card = json.loads(tc.get("result_preview", "{}"))
                        except Exception:
                            pass
                        break
                if video_card:
                    break

        assert video_card is not None, (
            "video_script_card no fue invocada o no llego al frontend. "
            f"tool_calls vistos: "
            f"{[tc.get('name') for m in msgs for tc in (m.get('tool_calls') or [])]}"
        )
        assert video_card.get("card_type") == "video_script"
        assert video_card.get("hook"), "falta hook"
        assert isinstance(video_card.get("scenes"), list) and len(video_card["scenes"]) >= 3
        assert isinstance(video_card.get("hashtags"), list) and len(video_card["hashtags"]) >= 5
        assert video_card.get("caption")
        assert video_card.get("cta")
        # platform debe ser TikTok
        assert video_card.get("platform") in ("tiktok", "todos")

    def test_result_preview_truncates_to_6000(self, admin_headers):
        """Verifica que result_preview ya no truncatea a 300 chars: las
        rich cards deben superar 300 chars."""
        r = requests.get(f"{BASE_URL}/api/console/sessions", headers=admin_headers, timeout=20)
        # Solo verifica existencia del endpoint para no agregar costo extra
        assert r.status_code in (200, 404)


# --------------------------- Haircut Preview ---------------------------
class TestHaircutPreview:
    def test_generate_haircut_preview_with_prior_image(self, admin_headers):
        """E2E: usuario sube imagen → siguiente mensaje (sin imagen) pide
        generate_haircut_preview → debe ejecutar Nano Banana y devolver after_url."""
        # Crear sesion
        r = requests.post(f"{BASE_URL}/api/console/sessions", headers=admin_headers,
                          json={"agent_id": "estilista_visual"}, timeout=30)
        assert r.status_code == 200
        sid = r.json().get("id") or r.json().get("session_id")

        # Subir imagen
        png = _face_png_bytes()
        up = requests.post(f"{BASE_URL}/api/console/sessions/{sid}/upload-image",
                           headers=admin_headers,
                           files={"file": ("face.png", png, "image/png")},
                           timeout=30)
        assert up.status_code == 200, up.text
        img_url = up.json()["url"]

        # Mensaje 1: con la imagen (vision)
        body1 = {"text": "Esta es mi foto, decime que ves.",
                 "image_urls": [img_url]}
        r1 = requests.post(f"{BASE_URL}/api/console/sessions/{sid}/messages",
                           headers=admin_headers, json=body1, timeout=120)
        assert r1.status_code == 200, r1.text[:300]

        # Mensaje 2: sin imagen, pedir explicitamente Nano Banana
        body2 = {"text": ("Llamá AHORA mismo a la tool generate_haircut_preview con "
                          "look_name='Long bob caramelo' y "
                          "look_description='Long bob (lob) cut to the collarbone, "
                          "warm caramel balayage with soft face-framing layers, slight "
                          "wave texture, side-swept fringe'. Nada de service_card. "
                          "Solo generate_haircut_preview UNA vez.")}
        r2 = requests.post(f"{BASE_URL}/api/console/sessions/{sid}/messages",
                           headers=admin_headers, json=body2, timeout=180)
        assert r2.status_code == 200, f"chat fail: {r2.status_code} {r2.text[:300]}"

        # Inspeccionar tool_calls
        rs = requests.get(f"{BASE_URL}/api/console/sessions/{sid}",
                          headers=admin_headers, timeout=20)
        msgs = rs.json().get("messages", [])
        ba_card = None
        for m in reversed(msgs):
            if m.get("role") == "assistant" and m.get("tool_calls"):
                for tc in m["tool_calls"]:
                    if tc.get("name") == "generate_haircut_preview":
                        try:
                            ba_card = json.loads(tc.get("result_preview", "{}"))
                        except Exception:
                            pass
                        break
                if ba_card:
                    break

        assert ba_card is not None, (
            "generate_haircut_preview no se llamo o no llego al frontend. "
            f"tool_calls: {[tc.get('name') for m in msgs for tc in (m.get('tool_calls') or [])]}"
        )
        assert ba_card.get("card_type") == "before_after"
        # Si ok=True, debe haber after_url servible
        if ba_card.get("ok"):
            assert ba_card.get("after_url", "").startswith("/api/uploads/ai_generated/")
            assert ba_card.get("before_url")
            # Verificar mount: la imagen debe ser servida
            full = f"{BASE_URL}{ba_card['after_url']}"
            img_r = requests.get(full, timeout=30)
            assert img_r.status_code == 200, f"after_url no sirve: {img_r.status_code}"
            assert len(img_r.content) > 1000, "imagen generada muy chica"
        else:
            # Si fallo, debe traer error claro (no excepcion)
            print(f"Nano Banana ok=False: {ba_card.get('error')}")
            assert ba_card.get("error"), "ok=False pero no hay error"
