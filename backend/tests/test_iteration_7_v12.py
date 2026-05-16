"""
Iteration 7 — UI/UX redesign v12.1 backend validation.
Focus: only backend pieces that changed for the redesign:
  - GET /api/branding has new field default_theme
  - PUT /api/branding accepts default_theme and persists it
  - GET /api/public/agents returns list (used by landing strip)
  - POST /api/auth/register returns trial_oros=50 and creates user with 50 oros
  - Logged in client lifecycle: credits/me, console/sessions (create + message),
    me/settings GET+PUT (has_github_token), me/apps, me/github/history
  - PayPal create-order returns approve_url (LIVE keys configured)
"""
import os, uuid, time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://ai-bot-cost-calc.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "melvinnavas79@gmail.com"
ADMIN_PASSWORD = "Admin#2026"


# ---------- shared fixtures ----------
@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def client_token():
    email = f"test_v12_{uuid.uuid4().hex[:10]}@test.com"
    r = requests.post(f"{API}/auth/register", json={
        "email": email, "password": "test1234", "name": "Test V12"
    }, timeout=30)
    assert r.status_code == 200, f"register failed: {r.status_code} {r.text}"
    data = r.json()
    return {"token": data["access_token"], "email": email, "register_resp": data}


def h(token): return {"Authorization": f"Bearer {token}"}


# ---------- registration trial ----------
def test_register_grants_50_trial_oros(client_token):
    data = client_token["register_resp"]
    assert "access_token" in data
    assert data.get("trial_oros") == 50, f"trial_oros expected 50, got: {data.get('trial_oros')}"

def test_credits_after_register_is_50(client_token):
    r = requests.get(f"{API}/console/credits/me", headers=h(client_token["token"]), timeout=20)
    assert r.status_code == 200
    assert r.json()["balance"] == 50, f"balance expected 50, got {r.json()}"


# ---------- public agents ----------
def test_public_agents_endpoint_returns_array():
    r = requests.get(f"{API}/public/agents", timeout=20)
    assert r.status_code == 200
    payload = r.json()
    agents = payload.get("agents") if isinstance(payload, dict) else payload
    assert isinstance(agents, list) and len(agents) > 0
    sample = agents[0]
    assert "id" in sample and "name" in sample
    # tagline used by landing
    assert "tagline" in sample


# ---------- branding default_theme (NEW field) ----------
def test_branding_get_includes_default_theme():
    r = requests.get(f"{API}/branding", timeout=20)
    assert r.status_code == 200
    body = r.json()
    assert "default_theme" in body, f"default_theme missing in branding response keys={list(body.keys())}"
    assert body["default_theme"] in ("light", "dark")


def test_branding_put_persists_default_theme(admin_token):
    # save original to restore at end
    orig = requests.get(f"{API}/branding", timeout=20).json()
    original_theme = orig.get("default_theme", "light")
    target = "dark" if original_theme != "dark" else "light"

    payload = {**orig, "default_theme": target}
    payload.pop("logo_data_url", None) if not orig.get("logo_data_url") else None

    r = requests.put(f"{API}/branding", json=payload, headers=h(admin_token), timeout=30)
    assert r.status_code == 200, f"PUT branding: {r.status_code} {r.text}"
    assert r.json().get("default_theme") == target

    # verify persistence
    r2 = requests.get(f"{API}/branding", timeout=20)
    assert r2.json()["default_theme"] == target

    # restore
    restore = {**r2.json(), "default_theme": original_theme}
    requests.put(f"{API}/branding", json=restore, headers=h(admin_token), timeout=30)


def test_branding_put_rejects_invalid_default_theme(admin_token):
    orig = requests.get(f"{API}/branding", timeout=20).json()
    payload = {**orig, "default_theme": "neon"}
    r = requests.put(f"{API}/branding", json=payload, headers=h(admin_token), timeout=30)
    # either rejected (422/400) OR silently coerced — accept both but flag
    assert r.status_code in (200, 400, 422)
    if r.status_code == 200:
        assert r.json().get("default_theme") in ("light", "dark"), "invalid default_theme leaked"


# ---------- console / chat flow ----------
def test_console_agents_listed(client_token):
    r = requests.get(f"{API}/console/agents", headers=h(client_token["token"]), timeout=20)
    assert r.status_code == 200
    agents = r.json().get("agents", [])
    assert len(agents) >= 5, f"expected at least 5 agents, got {len(agents)}"


def test_create_session_and_send_message_charges_credit(client_token):
    token = client_token["token"]
    agents = requests.get(f"{API}/console/agents", headers=h(token), timeout=20).json()["agents"]
    assert agents
    aid = agents[0]["id"]
    r = requests.post(f"{API}/console/sessions", json={"agent_id": aid}, headers=h(token), timeout=20)
    assert r.status_code == 200, r.text
    sid = r.json()["id"]

    bal_before = requests.get(f"{API}/console/credits/me", headers=h(token), timeout=20).json()["balance"]

    r = requests.post(f"{API}/console/sessions/{sid}/messages",
                       json={"text": "hola, responde con una sola palabra"},
                       headers=h(token), timeout=60)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "balance" in body
    assert body["balance"] <= bal_before, f"balance not charged: before={bal_before} after={body['balance']}"


# ---------- user settings ----------
def test_settings_get_and_put_with_github_token(client_token):
    token = client_token["token"]
    # get initial
    r = requests.get(f"{API}/me/settings", headers=h(token), timeout=20)
    assert r.status_code == 200
    initial = r.json()
    assert "has_github_token" in initial

    # set a token
    r = requests.put(f"{API}/me/settings",
                     json={"github_token": "ghp_dummy_test_v12_xxx", "github_repo": "user/repo",
                           "github_branch": "main", "project_name": "TEST_v12"},
                     headers=h(token), timeout=20)
    assert r.status_code == 200, r.text

    r = requests.get(f"{API}/me/settings", headers=h(token), timeout=20)
    body = r.json()
    assert body["has_github_token"] is True
    assert body.get("github_repo") == "user/repo"
    assert body.get("github_branch") == "main"


def test_me_apps_and_github_history(client_token):
    token = client_token["token"]
    r = requests.get(f"{API}/me/apps", headers=h(token), timeout=20)
    assert r.status_code == 200
    assert "apps" in r.json()

    r = requests.get(f"{API}/me/github/history", headers=h(token), timeout=20)
    assert r.status_code == 200
    assert "history" in r.json()


# ---------- PayPal create-order ----------
def test_paypal_create_order_returns_approve_url(client_token):
    token = client_token["token"]
    # find a valid pack
    packs = requests.get(f"{API}/paypal/packs", headers=h(token), timeout=20).json()
    pack_keys = list((packs.get("packs") or {}).keys())
    if not pack_keys:
        pytest.skip("no paypal packs configured")
    r = requests.post(f"{API}/paypal/create-order", json={"pack": pack_keys[0]},
                      headers=h(token), timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("approve_url", "").startswith("http"), f"no approve_url: {body}"
    assert "order_id" in body
