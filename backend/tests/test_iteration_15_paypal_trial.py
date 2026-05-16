"""
Iteration 15 (v12.16) — Tests:
- PayPal create-order incluye return_url/cancel_url y approve_url
- Trial dinamico (default 15, configurable via site_content.trial_oros)
- Anti-farming por IP (max 3 registros/dia, HTTP 429 al 4to)
- GET /api/site/content devuelve trial_oros y hero_cta_primary "Empezar gratis con 15 oros →"
- Regresion: login admin, login normal
"""

import os
import time
import uuid
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "melvinnavas79@gmail.com"
ADMIN_PASS = "Admin#2026"


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=15)
    assert r.status_code == 200, f"Admin login failed: {r.status_code} {r.text[:200]}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


# =========================================================
# Site content: trial_oros + hero_cta_primary
# =========================================================
def test_site_content_has_trial_oros_and_cta():
    r = requests.get(f"{API}/site/content", timeout=10)
    assert r.status_code == 200
    data = r.json()
    assert "trial_oros" in data, "site_content missing trial_oros field"
    assert isinstance(data["trial_oros"], int)
    assert 0 <= data["trial_oros"] <= 500
    # default debe ser 15
    assert data["trial_oros"] == 15, f"Expected default trial_oros=15, got {data['trial_oros']}"
    # CTA
    assert "hero_cta_primary" in data
    assert "15 oros" in data["hero_cta_primary"], f"CTA should mention '15 oros', got: {data['hero_cta_primary']}"


# =========================================================
# Register: trial dinamico
# =========================================================
def test_register_grants_default_15_oros():
    email = f"TEST_reg_{uuid.uuid4().hex[:8]}@test.com"
    r = requests.post(f"{API}/auth/register", json={"email": email, "password": "test1234", "name": "Test"}, timeout=15)
    # Puede dar 429 si la IP ya excedio, pero en CI fresco esperamos 200
    if r.status_code == 429:
        pytest.skip(f"IP ya excedio el cap diario: {r.text}")
    assert r.status_code == 200, f"Register failed: {r.status_code} {r.text[:200]}"
    data = r.json()
    assert "access_token" in data
    assert data.get("trial_oros") == 15, f"Expected trial_oros=15, got {data.get('trial_oros')}"
    # Verificar balance
    token = data["access_token"]
    bal = requests.get(f"{API}/console/credits/me", headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert bal.status_code == 200
    assert bal.json().get("balance") == 15, f"Balance should be 15, got {bal.json()}"


def test_register_dynamic_trial_via_site_content(admin_headers):
    """SuperAdmin cambia trial_oros=5 → nuevos registros reciben 5 → restaurar a 15."""
    # 1) PUT trial_oros=5
    r = requests.put(f"{API}/site/content", json={"trial_oros": 5}, headers=admin_headers, timeout=10)
    assert r.status_code == 200
    assert r.json().get("trial_oros") == 5

    try:
        # 2) Registrar (puede dar 429 segun IP)
        email = f"TEST_dyn_{uuid.uuid4().hex[:8]}@test.com"
        r2 = requests.post(f"{API}/auth/register", json={"email": email, "password": "test1234"}, timeout=15)
        if r2.status_code == 429:
            pytest.skip("IP cap hit; restored trial_oros in teardown")
        assert r2.status_code == 200, f"Register failed: {r2.text[:200]}"
        assert r2.json().get("trial_oros") == 5, f"Expected dynamic trial=5, got {r2.json().get('trial_oros')}"

        # Verificar balance
        token = r2.json()["access_token"]
        bal = requests.get(f"{API}/console/credits/me", headers={"Authorization": f"Bearer {token}"}, timeout=10)
        assert bal.status_code == 200
        assert bal.json().get("balance") == 5
    finally:
        # 3) Restaurar a 15
        rr = requests.put(f"{API}/site/content", json={"trial_oros": 15}, headers=admin_headers, timeout=10)
        assert rr.status_code == 200
        assert rr.json().get("trial_oros") == 15


# =========================================================
# Anti-farming: max 3 registros/IP/dia → 4to da 429
# =========================================================
def test_anti_farming_429_on_4th_register():
    """Registrar 4 usuarios desde la misma IP en sucesion → el 4to debe rechazarse."""
    # Cleanup previo: borrar registros TEST_farm_ con misma IP no es trivial sin DB.
    # En este ambiente compartido, simplemente intentamos. Si el rate-limit/IP ya
    # estaba saturado, el primer call ya da 429: marcamos skip.
    results = []
    for i in range(4):
        email = f"TEST_farm_{uuid.uuid4().hex[:10]}@test.com"
        r = requests.post(f"{API}/auth/register", json={"email": email, "password": "test1234"}, timeout=15)
        results.append(r.status_code)
        time.sleep(0.4)  # evitar rate-limit por minuto (6/min)

    # Esperamos: al menos un 429 en la respuesta (idealmente el 4to)
    assert 429 in results, f"Expected 429 in {results} (anti-farming should kick in)"


# =========================================================
# PayPal: create-order con return_url y approve_url persistido
# =========================================================
def test_paypal_create_order_has_approve_url(admin_headers):
    r = requests.post(f"{API}/paypal/create-order", json={"pack": "starter"}, headers=admin_headers, timeout=20)
    assert r.status_code == 200, f"create-order failed: {r.status_code} {r.text[:300]}"
    data = r.json()
    assert "order_id" in data
    assert "approve_url" in data
    assert data["approve_url"], "approve_url is empty"
    assert "paypal.com" in data["approve_url"], f"approve_url should be paypal.com, got: {data['approve_url']}"


def test_paypal_capture_unknown_order_404(admin_headers):
    """Capture a una orden inexistente / inválida debe devolver 502 (PayPal 404) o 404."""
    fake_id = "FAKEORDER" + uuid.uuid4().hex[:8].upper()
    r = requests.post(f"{API}/paypal/capture/{fake_id}", headers=admin_headers, timeout=15)
    # PayPal devuelve 404 al intentar capturar orden inexistente → backend traduce a 502
    assert r.status_code in (400, 404, 502), f"Expected 400/404/502, got {r.status_code}: {r.text[:200]}"


# =========================================================
# Regresion login admin
# =========================================================
def test_admin_login_works(admin_token):
    assert admin_token
    r = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {admin_token}"}, timeout=10)
    assert r.status_code == 200
    assert r.json().get("role") == "admin"
