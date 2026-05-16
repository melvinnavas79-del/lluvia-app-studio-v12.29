"""
Iteration 14 (v12.14) — Backend coverage for user-reported fixes:
  1. Marketing Lab: 'crea un video' (vague) → agent asks A/B (guion vs video real).
  2. Marketing Lab: explicit confirmation 'B + duración + aspect + confirmo' →
     generate_promo_video tool MUST be invoked EN EL MISMO TURNO.
  3. Regression: video_script_card / generate_haircut_preview / agent catalog.
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
def H(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


def _new_session(H, agent_id="marketing_lab"):
    r = requests.post(
        f"{BASE_URL}/api/console/sessions",
        headers=H,
        json={"agent_id": agent_id},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    return r.json().get("id") or r.json().get("session_id")


def _send(H, sid, text, timeout=120):
    r = requests.post(
        f"{BASE_URL}/api/console/sessions/{sid}/messages",
        headers=H,
        json={"text": text},
        timeout=timeout,
    )
    assert r.status_code == 200, f"chat fail: {r.status_code} {r.text[:300]}"
    return r.json()


def _msgs(H, sid):
    r = requests.get(f"{BASE_URL}/api/console/sessions/{sid}", headers=H, timeout=20)
    assert r.status_code == 200
    return r.json().get("messages", [])


def _last_assistant_text(msgs):
    for m in reversed(msgs):
        if m.get("role") == "assistant":
            return (m.get("content") or m.get("text") or "").lower()
    return ""


def _tool_calls(msgs, name):
    out = []
    for m in msgs:
        for tc in (m.get("tool_calls") or []):
            if tc.get("name") == name:
                out.append(tc)
    return out


# ------------------------- Marketing Lab A/B decision -------------------------
class TestMarketingLabABDecision:
    def test_vague_request_asks_ab(self, H):
        """'Crea un video sobre X' (vago) → agente debe preguntar A vs B."""
        sid = _new_session(H)
        _send(H, sid, "Crea un video sobre Estilista Visual")
        msgs = _msgs(H, sid)
        text = _last_assistant_text(msgs)
        # Should NOT have invoked generate_promo_video on vague prompt
        assert not _tool_calls(msgs, "generate_promo_video"), (
            f"generate_promo_video llamada con prompt vago. Texto: {text[:200]}"
        )
        # Should mention both options A (guion) and B (video real / sora)
        has_a = any(k in text for k in ("a)", "opción a", "opcion a", "guion", "guión"))
        has_b = any(k in text for k in ("b)", "opción b", "opcion b", "sora", "video real"))
        assert has_a and has_b, f"Agente no ofrece A/B. Texto: {text[:400]}"


# ------------------------- Marketing Lab same-turn invocation -------------------------
class TestMarketingLabSameTurnInvocation:
    def test_explicit_confirmation_invokes_tool_same_turn(self, H):
        """Confirmación explícita B+duration+aspect+'confirmo' → tool call mismo turno."""
        sid = _new_session(H)
        prompt = (
            "Opción B: VIDEO REAL con Sora 2. "
            "prompt='A modern barber shop, close-up of scissors cutting hair in slow motion, "
            "warm golden neon lighting, cinematic 4k commercial style'. "
            "duration=4 segundos. aspect=vertical. quality=standard. "
            "CONFIRMO el costo de 30 oros. Genera ya."
        )
        _send(H, sid, prompt, timeout=120)
        msgs = _msgs(H, sid)
        calls = _tool_calls(msgs, "generate_promo_video")
        assert calls, (
            f"generate_promo_video NO fue invocada en el mismo turno. "
            f"Texto: {_last_assistant_text(msgs)[:300]}"
        )
        card = None
        try:
            card = json.loads(calls[-1].get("result_preview", "{}"))
        except Exception:
            pass
        assert card and card.get("card_type") == "video_job"
        assert card.get("job_id"), "falta job_id"
        assert card.get("status") in ("queued", "generating", "ready"), card.get("status")
        assert card.get("duration") == 4
        assert card.get("size") == "720x1280"

        # Poll endpoint
        time.sleep(2)
        pr = requests.get(
            f"{BASE_URL}/api/console/video-jobs/{card['job_id']}",
            headers=H,
            timeout=20,
        )
        assert pr.status_code == 200, pr.text
        job = pr.json()
        assert job["status"] in ("queued", "generating", "ready", "error")
        assert job["duration"] == 4


# ------------------------- Regression: catalog -------------------------
class TestRegressionCatalog:
    def test_marketing_lab_tools(self, H):
        r = requests.get(f"{BASE_URL}/api/console/agents", headers=H, timeout=20)
        assert r.status_code == 200
        agents = r.json().get("agents")
        ml = next(a for a in agents if a["id"] == "marketing_lab")
        assert "generate_promo_video" in ml["tools"]
        assert "video_script_card" in ml["tools"]

    def test_estilista_keeps_haircut(self, H):
        r = requests.get(f"{BASE_URL}/api/console/agents", headers=H, timeout=20)
        agents = r.json().get("agents")
        ev = next(a for a in agents if a["id"] == "estilista_visual")
        assert "generate_haircut_preview" in ev["tools"]

    def test_video_job_endpoint_security(self):
        r = requests.get(f"{BASE_URL}/api/console/video-jobs/x", timeout=15)
        assert r.status_code in (401, 403)

    def test_video_gen_constants(self):
        import sys
        sys.path.insert(0, "/app/backend")
        import video_gen
        assert video_gen.COST_BY_DURATION == {4: 30, 8: 40, 12: 55}
        assert video_gen.ALLOWED_SIZES == {"720x1280", "1280x720"}
