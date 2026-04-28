"""
Iteration 2 - Backend regression for Auth JWT + Modo Afiliado MANUAL.

Cubre: /api/auth/login, /api/auth/me, /api/affiliates,
/api/sales, /api/stats/me, /api/stats/network, ademas de
verificar que los endpoints de iter 1 (root, status, command, webhooks)
sigan funcionando.
"""

import os
import re
import time
import uuid

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # fallback al .env del frontend
    env_path = "/app/frontend/.env"
    with open(env_path) as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().strip('"').rstrip("/")

API = f"{BASE_URL}/api"

ADMIN_EMAIL = "melvinnavas79@gmail.com"
ADMIN_PASSWORD = "Admin#2026"
JUAN_EMAIL = "juan@test.com"
JUAN_PASSWORD = "juan123"


# ============================================================
# Fixtures
# ============================================================
@pytest.fixture(scope="session")
def admin_token():
    r = requests.post(f"{API}/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                      timeout=15)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="session")
def juan_token():
    r = requests.post(f"{API}/auth/login",
                      json={"email": JUAN_EMAIL, "password": JUAN_PASSWORD},
                      timeout=15)
    if r.status_code != 200:
        pytest.skip(f"Afiliado juan no existe ({r.status_code}); requiere seed previo")
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def juan_headers(juan_token):
    return {"Authorization": f"Bearer {juan_token}"}


# ============================================================
# AUTH
# ============================================================
class TestAuth:
    def test_login_admin_success(self):
        r = requests.post(f"{API}/auth/login",
                          json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                          timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert "access_token" in data and isinstance(data["access_token"], str)
        assert data["user"]["role"] == "admin"
        assert data["user"]["email"] == ADMIN_EMAIL
        assert "password_hash" not in data["user"]

    def test_login_wrong_password(self):
        r = requests.post(f"{API}/auth/login",
                          json={"email": ADMIN_EMAIL, "password": "wrong"},
                          timeout=15)
        assert r.status_code == 401

    def test_me_with_token(self, admin_headers):
        r = requests.get(f"{API}/auth/me", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        u = r.json()
        assert u["role"] == "admin"
        assert "password_hash" not in u

    def test_me_without_token(self):
        r = requests.get(f"{API}/auth/me", timeout=15)
        assert r.status_code == 401


# ============================================================
# AFFILIATES
# ============================================================
class TestAffiliates:
    new_aff_id = None
    new_aff_email = None
    new_aff_code = None

    def test_create_affiliate_admin(self, admin_headers):
        unique = uuid.uuid4().hex[:6]
        email = f"test_aff_{unique}@test.com"
        payload = {
            "name": f"TestAff{unique}",
            "email": email,
            "password": "secret123",
            "commission_pct": 30.0,
        }
        r = requests.post(f"{API}/affiliates", json=payload,
                          headers=admin_headers, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["email"] == email
        assert data["role"] == "affiliate"
        assert data["commission_pct"] == 30.0
        assert "password_hash" not in data
        assert re.match(r"^[A-Z]{1,6}-[A-Z0-9]{4}$", data["affiliate_code"]), data["affiliate_code"]
        TestAffiliates.new_aff_id = data["id"]
        TestAffiliates.new_aff_email = email
        TestAffiliates.new_aff_code = data["affiliate_code"]

    def test_create_duplicate_email_409(self, admin_headers):
        assert TestAffiliates.new_aff_email is not None
        r = requests.post(f"{API}/affiliates", json={
            "name": "Dup",
            "email": TestAffiliates.new_aff_email,
            "password": "secret123",
            "commission_pct": 10.0,
        }, headers=admin_headers, timeout=15)
        assert r.status_code == 409

    def test_list_affiliates_admin(self, admin_headers):
        r = requests.get(f"{API}/affiliates", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        items = r.json()
        assert isinstance(items, list)
        ids = [a["id"] for a in items]
        assert TestAffiliates.new_aff_id in ids

    def test_list_affiliates_forbidden_for_affiliate(self, juan_headers):
        r = requests.get(f"{API}/affiliates", headers=juan_headers, timeout=15)
        assert r.status_code == 403

    def test_patch_deactivate(self, admin_headers):
        assert TestAffiliates.new_aff_id is not None
        r = requests.patch(
            f"{API}/affiliates/{TestAffiliates.new_aff_id}",
            json={"active": False},
            headers=admin_headers, timeout=15,
        )
        assert r.status_code == 200
        assert r.json()["active"] is False
        # Reactivar para no afectar tests siguientes
        requests.patch(f"{API}/affiliates/{TestAffiliates.new_aff_id}",
                       json={"active": True}, headers=admin_headers, timeout=15)


# ============================================================
# SALES
# ============================================================
class TestSales:
    sale_id = None

    def test_create_sale_admin_calculates_commission(self, admin_headers):
        assert TestAffiliates.new_aff_code is not None
        r = requests.post(f"{API}/sales", json={
            "affiliate_code": TestAffiliates.new_aff_code,
            "amount": 100.0,
            "product": "TEST_Producto",
            "platform": "manual",
        }, headers=admin_headers, timeout=15)
        assert r.status_code == 200, r.text
        sale = r.json()
        # commission = 100 * 30 / 100 = 30
        assert sale["commission"] == 30.0
        assert sale["amount"] == 100.0
        assert sale["paid"] is False
        assert sale["affiliate_code"] == TestAffiliates.new_aff_code
        TestSales.sale_id = sale["id"]

    def test_create_sale_invalid_code(self, admin_headers):
        r = requests.post(f"{API}/sales", json={
            "affiliate_code": "NOEXISTE-XXXX",
            "amount": 50,
            "product": "X",
        }, headers=admin_headers, timeout=15)
        assert r.status_code == 404

    def test_create_sale_forbidden_for_affiliate(self, juan_headers):
        r = requests.post(f"{API}/sales", json={
            "affiliate_code": TestAffiliates.new_aff_code or "AFL-XXXX",
            "amount": 10,
            "product": "X",
        }, headers=juan_headers, timeout=15)
        assert r.status_code == 403

    def test_list_sales_admin_sees_all(self, admin_headers):
        r = requests.get(f"{API}/sales", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        sales = r.json()
        assert isinstance(sales, list)
        assert any(s["id"] == TestSales.sale_id for s in sales)

    def test_list_sales_affiliate_only_own(self, juan_headers):
        r = requests.get(f"{API}/sales", headers=juan_headers, timeout=15)
        assert r.status_code == 200
        sales = r.json()
        # Juan no debe ver la venta del nuevo afiliado de prueba
        assert all(s["affiliate_code"] != TestAffiliates.new_aff_code for s in sales)

    def test_mark_paid(self, admin_headers):
        assert TestSales.sale_id is not None
        r = requests.patch(f"{API}/sales/{TestSales.sale_id}/pay",
                           json={"paid": True},
                           headers=admin_headers, timeout=15)
        assert r.status_code == 200
        sale = r.json()
        assert sale["paid"] is True
        assert sale["paid_at"] is not None


# ============================================================
# STATS
# ============================================================
class TestStats:
    def test_stats_me_admin(self, admin_headers):
        r = requests.get(f"{API}/stats/me", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert "total_amount" in data
        assert "total_commission" in data

    def test_stats_me_affiliate(self, juan_headers):
        r = requests.get(f"{API}/stats/me", headers=juan_headers, timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert "affiliate_code" in data
        assert "name" in data

    def test_stats_network_admin(self, admin_headers):
        r = requests.get(f"{API}/stats/network", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert "overall" in data
        assert "affiliates_count" in data
        assert "breakdown" in data
        # ordenado desc por total_amount
        amounts = [b["total_amount"] for b in data["breakdown"]]
        assert amounts == sorted(amounts, reverse=True)

    def test_stats_network_forbidden_for_affiliate(self, juan_headers):
        r = requests.get(f"{API}/stats/network", headers=juan_headers, timeout=15)
        assert r.status_code == 403


# ============================================================
# Iteration 1 regressions: endpoints viejos siguen vivos
# ============================================================
class TestExistingEndpoints:
    def test_root(self):
        r = requests.get(f"{API}/", timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert body.get("status") == "running"

    def test_status(self):
        r = requests.get(f"{API}/status", timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert body.get("ok") is True

    def test_command_real_openai(self):
        r = requests.post(f"{API}/command",
                          json={"message": "Hola, responde con OK", "user": "TEST_user"},
                          timeout=60)
        assert r.status_code == 200
        body = r.json()
        assert "response" in body
        assert isinstance(body["response"], str) and len(body["response"]) > 0

    def test_whatsapp_verify_403(self):
        r = requests.get(f"{API}/webhook/whatsapp",
                         params={"hub.verify_token": "wrong",
                                 "hub.challenge": "abc"}, timeout=15)
        assert r.status_code == 403

    def test_whatsapp_verify_ok(self):
        r = requests.get(f"{API}/webhook/whatsapp",
                         params={"hub.verify_token": "12345",
                                 "hub.challenge": "abc"}, timeout=15)
        assert r.status_code == 200
        assert r.text == "abc"

    def test_telegram_token_invalid(self):
        r = requests.post(f"{API}/webhook/telegram/wrongtoken",
                          json={}, timeout=15)
        assert r.status_code == 403
