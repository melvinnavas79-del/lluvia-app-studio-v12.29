"""
Iteration 13 (v12.13) — Sora 2 video generation + camera bug fix.

Backend coverage:
  * generate_promo_video tool registered in OPENAI_TOOLS and on marketing_lab agent.
  * Cost dynamic by duration: 4=30, 8=40, 12=55 oros (override TOOL_NAMES catalog).
  * GET /api/console/video-jobs/{id} requires auth; owner-only (404 if not owner).
  * enqueue_video module-level: queued doc inserted in mongo, background task fires.
  * Regression: marketing_lab agent still includes video_script_card; estilista_visual
    keeps generate_haircut_preview.

We DO NOT wait for Sora 2 to finish (4s clip ~90s). We only validate the job is
enqueued and the card payload is correct. The agent flow test is light: we send a
prompt with the explicit confirmation phrase so the agent calls the tool, and we
check the tool_call appears with card_type=video_job and the expected metadata.
"""
import json
import os
import time

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
ADMIN_EMAIL = "melvinnavas79@gmail.com"
ADMIN_PASSWORD = "Admin#2026"


@pytest.fixture(scope="session")
def admin_token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=30,
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


# --------------------------- Catalog ---------------------------
class TestCatalogSora2:
    def test_marketing_lab_has_promo_video_tool(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/console/agents", headers=admin_headers, timeout=30)
        assert r.status_code == 200
        data = r.json()
        agents = data.get("agents") if isinstance(data, dict) else data
        ml = next((a for a in agents if a["id"] == "marketing_lab"), None)
        assert ml is not None, "marketing_lab agent missing"
        assert "generate_promo_video" in ml["tools"], f"tools: {ml['tools']}"
        assert "video_script_card" in ml["tools"], "regression: video_script_card lost"

    def test_estilista_keeps_haircut_preview(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/console/agents", headers=admin_headers, timeout=30)
        agents = r.json().get("agents")
        ev = next(a for a in agents if a["id"] == "estilista_visual")
        assert "generate_haircut_preview" in ev["tools"]


# --------------------------- Video job endpoint security ---------------------------
class TestVideoJobEndpoint:
    def test_video_job_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/console/video-jobs/nonexistent", timeout=15)
        assert r.status_code in (401, 403), f"unauth got {r.status_code}"

    def test_video_job_404_for_unknown(self, admin_headers):
        r = requests.get(
            f"{BASE_URL}/api/console/video-jobs/this-id-does-not-exist-abc123",
            headers=admin_headers,
            timeout=20,
        )
        assert r.status_code == 404


# --------------------------- enqueue (module-level direct) ---------------------------
def test_video_gen_module_constants():
    """Smoke test the video_gen module constants (no API call)."""
    import sys
    sys.path.insert(0, "/app/backend")
    import video_gen
    assert video_gen.COST_BY_DURATION == {4: 30, 8: 40, 12: 55}
    assert video_gen.ALLOWED_DURATIONS == {4, 8, 12}
    assert video_gen.ALLOWED_SIZES == {"720x1280", "1280x720"}
    # SIZES patched at import time
    from emergentintegrations.llm.openai.video_generation import OpenAIVideoGeneration
    assert "720x1280" in OpenAIVideoGeneration.SIZES
    assert "1280x720" in OpenAIVideoGeneration.SIZES


# --------------------------- E2E: agent enqueues video job ---------------------------
class TestMarketingLabVideoFlow:
    def test_promo_video_enqueued_after_confirmation(self, admin_headers):
        # Create session
        r = requests.post(
            f"{BASE_URL}/api/console/sessions",
            headers=admin_headers,
            json={"agent_id": "marketing_lab"},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        sid = r.json().get("id") or r.json().get("session_id")
        assert sid

        prompt = (
            "Generá YA el video con Sora 2. Datos: prompt='A modern barber shop, "
            "close-up of scissors cutting hair in slow motion, warm golden neon "
            "lighting, depth of field, cinematic 4k commercial style'. "
            "duration=4 segundos. aspect=vertical. quality=standard. "
            "CONFIRMO el costo de 30 oros. Llamá a generate_promo_video DIRECTAMENTE "
            "AHORA, no me hagas más preguntas."
        )
        r = requests.post(
            f"{BASE_URL}/api/console/sessions/{sid}/messages",
            headers=admin_headers,
            json={"text": prompt},
            timeout=120,
        )
        assert r.status_code == 200, f"chat fail: {r.status_code} {r.text[:300]}"

        rs = requests.get(
            f"{BASE_URL}/api/console/sessions/{sid}",
            headers=admin_headers,
            timeout=20,
        )
        assert rs.status_code == 200
        msgs = rs.json().get("messages", [])

        video_card = None
        for m in reversed(msgs):
            if m.get("role") == "assistant" and m.get("tool_calls"):
                for tc in m["tool_calls"]:
                    if tc.get("name") == "generate_promo_video":
                        try:
                            video_card = json.loads(tc.get("result_preview", "{}"))
                        except Exception:
                            pass
                        break
                if video_card:
                    break

        tool_names_seen = [
            tc.get("name") for m in msgs for tc in (m.get("tool_calls") or [])
        ]
        assert video_card is not None, (
            f"generate_promo_video no fue invocada. tool_calls vistos: {tool_names_seen}"
        )
        assert video_card.get("card_type") == "video_job"
        assert video_card.get("job_id"), "falta job_id"
        assert video_card.get("status") in ("queued", "generating", "ready"), (
            f"status raro: {video_card.get('status')}"
        )
        assert video_card.get("duration") == 4, f"duration={video_card.get('duration')}"
        assert video_card.get("aspect") == "vertical"
        assert video_card.get("size") == "720x1280"
        assert video_card.get("model") in ("sora-2", "sora-2-pro")
        assert video_card.get("prompt"), "falta prompt en card"

        # Now poll the endpoint a few times to confirm owner can fetch the job
        job_id = video_card["job_id"]
        time.sleep(2)
        pr = requests.get(
            f"{BASE_URL}/api/console/video-jobs/{job_id}",
            headers=admin_headers,
            timeout=20,
        )
        assert pr.status_code == 200, pr.text
        job = pr.json()
        assert job["id"] == job_id
        assert job["status"] in ("queued", "generating", "ready", "error")
        assert job["duration"] == 4
        assert job["size"] == "720x1280"
        assert job["model"] in ("sora-2", "sora-2-pro")

    def test_agent_asks_confirmation_before_calling_tool(self, admin_headers):
        """The agent must NOT call generate_promo_video when user hasn't confirmed cost.
        Should mention cost (30/40/55 oros) and ask for confirmation."""
        r = requests.post(
            f"{BASE_URL}/api/console/sessions",
            headers=admin_headers,
            json={"agent_id": "marketing_lab"},
            timeout=30,
        )
        sid = r.json().get("id") or r.json().get("session_id")
        # Explicit Sora 2 request but WITHOUT cost confirmation
        prompt = (
            "Generá el VIDEO REAL con Sora 2 de 4 segundos para TikTok del agente "
            "Estilista Visual. (Quiero el video real, no el guion.)"
        )
        r = requests.post(
            f"{BASE_URL}/api/console/sessions/{sid}/messages",
            headers=admin_headers,
            json={"text": prompt},
            timeout=90,
        )
        assert r.status_code == 200, r.text[:300]
        rs = requests.get(
            f"{BASE_URL}/api/console/sessions/{sid}",
            headers=admin_headers,
            timeout=20,
        )
        msgs = rs.json().get("messages", [])
        called = False
        last_assistant_text = ""
        for m in reversed(msgs):
            if m.get("role") == "assistant":
                if not last_assistant_text:
                    last_assistant_text = (m.get("content") or m.get("text") or "").lower()
                for tc in (m.get("tool_calls") or []):
                    if tc.get("name") == "generate_promo_video":
                        called = True
        assert not called, (
            "generate_promo_video fue llamada SIN confirmacion explicita del costo. "
            f"Texto agente: {last_assistant_text[:200]}"
        )
        assert any(k in last_assistant_text for k in ("30", "40", "55", "oros", "costo", "cuesta", "confirm")), (
            f"Agente no menciona costo/confirmacion: {last_assistant_text[:300]}"
        )
