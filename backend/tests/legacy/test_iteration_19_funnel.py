"""
Iteration 19 — Funnel demo->CTA->register->/#/chat->app_builder_pro
Tests:
- voseos removed in audio_room template server.py
- demo health no regression
- CTA injected en /api/demo/audio-room-static/
- POST /api/demo/audio-room/api/convert flow
- credits/me + agents include app_builder_pro post-convert
"""
import os
import re
import time
import random
from pathlib import Path

import pytest
import requests

def _load_base_url():
    val = os.environ.get("REACT_APP_BACKEND_URL", "").strip()
    if not val:
        # Read from frontend/.env
        env_path = Path("/app/frontend/.env")
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("REACT_APP_BACKEND_URL="):
                    val = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    return val.rstrip("/")


BASE_URL = _load_base_url()
TEMPLATE_SERVER = Path("/app/backend/app_templates/audio_room/backend/server.py")


# 1. Voseos translation
class TestVoseosTranslated:
    def test_server_py_no_vos_text(self):
        text = TEMPLATE_SERVER.read_text(encoding="utf-8")
        # Negative checks: vos forms must NOT exist
        assert "No podes seguirte a vos mismo" not in text, "vos form still present line ~206"
        assert "Tenes " not in text, "'Tenes' present (should be 'Tienes')"
        # Positive checks: neutral spanish
        assert "No puedes seguirte a ti mismo" in text, "neutral spanish missing line 206"
        assert "Tienes" in text, "'Tienes' missing line 323"


# 2. Demo audio room API health (no regression)
class TestDemoHealth:
    def test_health(self):
        r = requests.get(f"{BASE_URL}/api/demo/audio-room/api/health", timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("ok") is True
        assert d.get("mode") == "demo"
        assert d.get("rooms") == 6
        assert d.get("users") == 5


# 3. CTA HTML injection
class TestDemoCTAInjected:
    def test_cta_in_static_html(self):
        r = requests.get(f"{BASE_URL}/api/demo/audio-room-static/", timeout=10)
        assert r.status_code == 200
        html = r.text
        assert 'id="lluvia-demo-cta"' in html, "missing CTA button id"
        assert 'data-testid="demo-cta-floating"' in html, "missing testid demo-cta-floating"
        assert 'data-testid="demo-cta-submit"' in html, "missing testid demo-cta-submit"
        assert 'data-testid="demo-cta-email"' in html
        assert 'data-testid="demo-cta-password"' in html
        assert 'data-testid="demo-cta-app-name"' in html
        assert 'data-testid="demo-cta-color"' in html
        assert "window.lluviaSubmitConvert" in html, "missing JS hook"
        assert "/api/demo/audio-room/api/convert" in html, "missing endpoint reference"
        assert "bot_admin_token" in html, "missing localStorage token key"
        assert "lluvia_demo_seed" in html, "missing localStorage seed key"
        assert "/#/chat" in html, "missing redirect to /#/chat"


# 4. Convert endpoint
class TestConvertEndpoint:
    """The convert endpoint reuses affiliates.register which has IP rate-limit.
       We accept either 200 (success with token+seed) OR 429 (rate-limited valid protection)."""

    def test_convert_validation_400_short_password(self):
        r = requests.post(
            f"{BASE_URL}/api/demo/audio-room/api/convert",
            json={"email": "foo@bar.com", "password": "123", "app_name": "X", "brand_color": "#EC4899"},
            timeout=15,
        )
        assert r.status_code in (400, 422), f"expected 4xx for short pwd, got {r.status_code}: {r.text[:200]}"

    def test_convert_validation_400_bad_email(self):
        r = requests.post(
            f"{BASE_URL}/api/demo/audio-room/api/convert",
            json={"email": "notanemail", "password": "test1234", "app_name": "X", "brand_color": "#EC4899"},
            timeout=15,
        )
        assert r.status_code in (400, 422), f"expected 4xx for bad email, got {r.status_code}"

    def test_convert_happy_path_or_ratelimit(self):
        email = f"funnel_iter19_{int(time.time())}_{random.randint(1000,9999)}@test.com"
        payload = {
            "email": email,
            "password": "test1234",
            "app_name": "TestFunnel",
            "brand_color": "#EC4899",
        }
        r = requests.post(f"{BASE_URL}/api/demo/audio-room/api/convert", json=payload, timeout=20)
        if r.status_code == 429:
            # Rate-limit valid protection — accept and verify message clarity
            txt = r.text.lower()
            assert "demasiad" in txt or "rate" in txt or "limit" in txt or "esper" in txt, (
                f"429 but message unclear: {r.text[:300]}"
            )
            pytest.skip(f"Rate-limited 429 (expected anti-abuse). Body: {r.text[:200]}")
        assert r.status_code == 200, f"convert failed: {r.status_code} {r.text[:300]}"
        d = r.json()
        assert d.get("ok") is True
        assert "access_token" in d and isinstance(d["access_token"], str) and len(d["access_token"]) > 10
        assert "user" in d
        seed = d.get("seed", {})
        assert seed.get("app_name") == "TestFunnel"
        assert seed.get("brand_color") == "#EC4899"
        assert d.get("next_url") == "/"

        # Verify token works — credits + agents
        headers = {"Authorization": f"Bearer {d['access_token']}"}
        rc = requests.get(f"{BASE_URL}/api/console/credits/me", headers=headers, timeout=10)
        assert rc.status_code == 200, rc.text[:200]
        bal = rc.json().get("balance", 0)
        assert bal >= 15, f"trial credit not granted, balance={bal}"

        ra = requests.get(f"{BASE_URL}/api/console/agents", headers=headers, timeout=10)
        assert ra.status_code == 200
        agents = ra.json()
        if isinstance(agents, dict):
            agents = agents.get("agents") or agents.get("items") or []
        agent_ids = [a.get("id") or a.get("agent_id") or a.get("slug") for a in agents]
        assert "app_builder_pro" in agent_ids, f"app_builder_pro missing from agents: {agent_ids}"
