"""
Backend test suite for Lluvia App Studio v10 (iteration 5).
Covers:
- Auth login + rate limit (8/min)
- Promos CRUD + day-of-week/month logic
- Proposals CRUD + approval workflow (promo_create end-to-end)
- PayPal packs (promo discount, webhook signature 403)
- Telegram unified /agente /miagente /saldo + agent persistence
- Call-center /turn validations (auth, oversize, OPENAI 502 controlled)
- Branding extended fields GET/PUT
- /api/download/lluvia-deploy/info version v10
- Existing v9 endpoints non-broken (console/agency/agent-builder)
"""
import os
import io
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://ai-bot-cost-calc.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "melvinnavas79@gmail.com"
ADMIN_PASSWORD = "Admin#2026"


# ---------------- fixtures ----------------
@pytest.fixture(scope="module")
def admin_token():
    # Retry on 429 (rate limit) — wait up to 75s
    deadline = time.time() + 80
    last = None
    while time.time() < deadline:
        r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=15)
        last = r
        if r.status_code == 200:
            return r.json()["access_token"]
        if r.status_code == 429:
            time.sleep(8)
            continue
        break
    pytest.fail(f"login failed: {last.status_code} {last.text}")


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


# ---------------- AUTH + RATE LIMIT (moved to bottom of file) ----------------


# ---------------- PROMOS ----------------
class TestPromos:
    rule_id = f"TEST-promo-{uuid.uuid4().hex[:6]}"

    def test_list_promos_requires_auth(self):
        r = requests.get(f"{API}/promos", timeout=10)
        assert r.status_code == 401

    def test_create_list_delete_promo(self, admin_headers):
        # CREATE permanent (no days filters) so it always applies
        payload = {
            "rule_id": self.rule_id,
            "description": "TEST permanent 10% off",
            "discount_pct": 10,
            "active": True,
        }
        r = requests.post(f"{API}/promos", json=payload, headers=admin_headers, timeout=10)
        assert r.status_code == 200, r.text
        assert r.json()["rule_id"] == self.rule_id

        # LIST
        r = requests.get(f"{API}/promos", headers=admin_headers, timeout=10)
        assert r.status_code == 200
        ids = [p["rule_id"] for p in r.json()["promos"]]
        assert self.rule_id in ids

        # Verify packs reflect the promo discount (permanent always applies)
        r = requests.get(f"{API}/paypal/packs", timeout=10)
        assert r.status_code == 200
        body = r.json()
        starter = body["packs"]["starter"]
        assert starter["discount_pct"] >= 10
        assert starter["promo_label"] is not None
        assert float(starter["price_usd"]) <= float(starter["price_usd_original"])

        # DELETE
        r = requests.delete(f"{API}/promos/{self.rule_id}", headers=admin_headers, timeout=10)
        assert r.status_code == 200
        assert r.json()["deleted"] == 1

        # Verify removed
        r = requests.get(f"{API}/promos", headers=admin_headers, timeout=10)
        ids = [p["rule_id"] for p in r.json()["promos"]]
        assert self.rule_id not in ids


# ---------------- PROPOSALS ----------------
class TestProposals:
    def test_list_proposals_admin_only(self, admin_headers):
        r = requests.get(f"{API}/proposals", headers=admin_headers, timeout=10)
        assert r.status_code == 200
        assert "proposals" in r.json()

    def test_create_invalid_type_rejected(self, admin_headers):
        r = requests.post(f"{API}/proposals", headers=admin_headers, timeout=10, json={
            "type": "bogus_type", "title": "x", "rationale": "y", "payload": {},
        })
        assert r.status_code == 400

    def test_proposal_approve_promo_end_to_end(self, admin_headers):
        rule_id = f"TEST-prop-{uuid.uuid4().hex[:6]}"
        # Create proposal
        r = requests.post(f"{API}/proposals", headers=admin_headers, timeout=10, json={
            "type": "promo_create",
            "title": "TEST proposal promo",
            "rationale": "auto-test",
            "payload": {
                "rule_id": rule_id,
                "description": "TEST proposal 5% off",
                "discount_pct": 5,
                "days_of_week": [],
                "days_of_month": [],
            },
        })
        assert r.status_code == 200, r.text
        prop = r.json()
        assert prop["status"] == "pending"
        pid = prop["id"]

        # Approve
        r = requests.post(f"{API}/proposals/{pid}/approve", headers=admin_headers, timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["status"] == "applied"

        # Verify promo exists
        r = requests.get(f"{API}/promos", headers=admin_headers, timeout=10)
        ids = [p["rule_id"] for p in r.json()["promos"]]
        assert rule_id in ids

        # Cleanup
        requests.delete(f"{API}/promos/{rule_id}", headers=admin_headers, timeout=10)

    def test_proposal_reject(self, admin_headers):
        r = requests.post(f"{API}/proposals", headers=admin_headers, timeout=10, json={
            "type": "branding_update",
            "title": "TEST reject",
            "rationale": "to-reject",
            "payload": {"tagline": "x"},
        })
        pid = r.json()["id"]
        r = requests.post(f"{API}/proposals/{pid}/reject", headers=admin_headers, timeout=10)
        assert r.status_code == 200
        assert r.json()["ok"] is True
        # Approve after reject must fail
        r = requests.post(f"{API}/proposals/{pid}/approve", headers=admin_headers, timeout=10)
        assert r.status_code == 400


# ---------------- PAYPAL ----------------
class TestPaypal:
    def test_packs_public(self):
        r = requests.get(f"{API}/paypal/packs", timeout=10)
        assert r.status_code == 200
        body = r.json()
        assert set(body["packs"].keys()) == {"starter", "growth", "scale"}
        for k, p in body["packs"].items():
            assert "discount_pct" in p
            assert "promo_label" in p
            assert "price_usd_original" in p

    def test_webhook_missing_signature_403(self):
        r = requests.post(f"{API}/paypal/webhook",
                          json={"event_type": "PAYMENT.CAPTURE.COMPLETED", "resource": {}},
                          timeout=10)
        # Without PAYPAL_WEBHOOK_ID env or paypal headers, must reject
        assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text[:200]}"


# ---------------- TELEGRAM UNIFIED via /api/command ----------------
class TestTelegramUnified:
    user_key = f"TEST_tg_{uuid.uuid4().hex[:6]}"

    def test_agente_menu(self):
        r = requests.post(f"{API}/command", json={"message": "/agente", "user": self.user_key}, timeout=15)
        assert r.status_code == 200
        text = r.json()["response"]
        # Must list builtin agents (>= 7)
        assert "Agentes disponibles" in text or "/agente_" in text
        agent_links = text.count("/agente_") + text.count("/agente\\_")
        assert agent_links >= 7, f"expected >=7 agents in menu, got {agent_links}: {text[:400]}"

    def test_select_devops_and_miagente(self):
        r = requests.post(f"{API}/command", json={"message": "/agente_devops", "user": self.user_key}, timeout=15)
        assert r.status_code == 200
        assert "devops" in r.json()["response"].lower() or "DevOps" in r.json()["response"]

        r = requests.post(f"{API}/command", json={"message": "/miagente", "user": self.user_key}, timeout=15)
        assert r.status_code == 200
        assert "devops" in r.json()["response"].lower() or "DevOps" in r.json()["response"]

    def test_saldo(self):
        r = requests.post(f"{API}/command", json={"message": "/saldo", "user": self.user_key}, timeout=15)
        assert r.status_code == 200
        body = r.json()["response"]
        assert "oros" in body.lower() or "saldo" in body.lower()

    def test_normal_message_does_not_break(self):
        # Without valid OPENAI_API_KEY we expect either error string or insufficient balance, NOT a 500
        r = requests.post(f"{API}/command", json={"message": "hola", "user": self.user_key}, timeout=30)
        assert r.status_code == 200, r.text
        assert isinstance(r.json().get("response"), str)


# ---------------- CALL CENTER ----------------
class TestCallCenter:
    def test_requires_auth(self):
        r = requests.post(f"{API}/voice/call-center/turn",
                          files={"audio": ("a.webm", b"x", "audio/webm")},
                          data={"agent_id": "devops"}, timeout=10)
        assert r.status_code == 401

    def test_oversize_rejected(self, admin_headers):
        big = b"\x00" * (8 * 1024 * 1024 + 10)
        r = requests.post(f"{API}/voice/call-center/turn",
                          headers=admin_headers,
                          files={"audio": ("big.webm", io.BytesIO(big), "audio/webm")},
                          data={"agent_id": "devops"}, timeout=30)
        # 413 expected (server validates size after charge? check code: charge happens after size check)
        assert r.status_code in (413, 402), f"expected 413, got {r.status_code}: {r.text[:200]}"

    def test_unknown_agent_400(self, admin_headers):
        r = requests.post(f"{API}/voice/call-center/turn",
                          headers=admin_headers,
                          files={"audio": ("a.webm", b"abc", "audio/webm")},
                          data={"agent_id": "no_such_agent_xyz"}, timeout=15)
        assert r.status_code == 400

    def test_openai_failure_is_502_not_500(self, admin_headers):
        # With small but non-empty audio, OpenAI key is invalid in preview -> should 502 (not 500)
        # If admin has 0 balance we may get 402 first; this is also acceptable (no 500).
        r = requests.post(f"{API}/voice/call-center/turn",
                          headers=admin_headers,
                          files={"audio": ("a.webm", b"\x1aE\xdf\xa3" + b"\x00" * 200, "audio/webm")},
                          data={"agent_id": "devops"}, timeout=60)
        assert r.status_code != 500, f"got 500: {r.text[:400]}"
        # Acceptable: 200 (key works) / 502 (openai fail) / 402 (no oros) / 503 (key missing)
        assert r.status_code in (200, 402, 502, 503), f"unexpected: {r.status_code} {r.text[:300]}"


# ---------------- BRANDING ----------------
class TestBranding:
    def test_get_branding_has_extended_fields(self):
        r = requests.get(f"{API}/branding", timeout=10)
        assert r.status_code == 200
        b = r.json()
        for k in ("product_name", "tagline", "primary_color", "accent_color",
                  "background_color", "text_color", "logo_data_url",
                  "company_name", "support_email"):
            assert k in b, f"branding missing {k}: {list(b.keys())}"

    def test_put_branding_admin(self, admin_headers):
        new_tag = f"TEST tag {uuid.uuid4().hex[:6]}"
        r = requests.put(f"{API}/branding",
                         headers=admin_headers,
                         json={"tagline": new_tag, "primary_color": "#112233"},
                         timeout=10)
        assert r.status_code == 200, r.text
        assert r.json()["tagline"] == new_tag
        assert r.json()["primary_color"] == "#112233"

    def test_put_branding_invalid_color(self, admin_headers):
        r = requests.put(f"{API}/branding",
                         headers=admin_headers, json={"primary_color": "blue"}, timeout=10)
        assert r.status_code == 422


# ---------------- DEPLOY INFO ----------------
class TestDeployInfo:
    def test_version_v10(self):
        r = requests.get(f"{API}/download/lluvia-deploy/info", timeout=10)
        # File may not exist in preview -> skip
        if r.status_code == 404:
            pytest.skip("paquete no disponible en preview")
        assert r.status_code == 200
        assert r.json().get("version") == "v10-unified-promos-proposals-callcenter"


# ---------------- v9 NON-BROKEN ----------------
class TestV9NotBroken:
    def test_console_agents(self, admin_headers):
        r = requests.get(f"{API}/console/agents", headers=admin_headers, timeout=10)
        assert r.status_code == 200
        body = r.json()
        # 8 builtin agents per v10
        agents = body.get("agents") or body
        assert isinstance(agents, list)
        assert len(agents) >= 7, f"expected >=7 agents, got {len(agents)}"

    def test_sessions_crud(self, admin_headers):
        # CREATE
        r = requests.post(f"{API}/console/sessions",
                         headers=admin_headers, json={"agent_id": "devops", "title": "TEST sess"}, timeout=10)
        assert r.status_code in (200, 201), r.text
        sid = r.json()["id"]
        # LIST
        r = requests.get(f"{API}/console/sessions", headers=admin_headers, timeout=10)
        assert r.status_code == 200
        # DELETE
        r = requests.delete(f"{API}/console/sessions/{sid}", headers=admin_headers, timeout=10)
        assert r.status_code in (200, 204)

    def test_agency_clients(self, admin_headers):
        r = requests.get(f"{API}/agency/clients", headers=admin_headers, timeout=10)
        assert r.status_code == 200

    def test_agent_builder_list(self, admin_headers):
        r = requests.get(f"{API}/agent-builder", headers=admin_headers, timeout=10)
        assert r.status_code == 200


# ---------------- AUTH + RATE LIMIT (runs last to not deplete login quota) ----------------
class TestZAuthAndRateLimit:
    def test_login_admin_ok(self, admin_token):
        # Fixture already validated; just check it's a non-empty string
        assert isinstance(admin_token, str) and len(admin_token) > 20

    def test_login_rate_limit_429(self):
        # 8/min limit — using unique invalid password to avoid succeeding
        statuses = []
        for _ in range(12):
            r = requests.post(f"{API}/auth/login",
                              json={"email": "ratelimit-bogus@test.com", "password": "wrong"},
                              timeout=10)
            statuses.append(r.status_code)
            if r.status_code == 429:
                break
        assert 429 in statuses, f"Expected 429 within 12 attempts, got {statuses}"
        non_429 = [s for s in statuses if s != 429]
        assert all(s in (401, 400) for s in non_429), f"unexpected statuses: {statuses}"
