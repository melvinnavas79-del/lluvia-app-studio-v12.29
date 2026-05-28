"""
Iteration 3 backend tests: /api/branding (GET public / PUT admin / POST reset),
sale defense vs deactivated affiliate, persistence after restart and existing endpoints regression.
"""
import os
import base64
import time
import subprocess
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://ai-bot-cost-calc.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "melvinnavas79@gmail.com"
ADMIN_PASS = "Admin#2026"
JUAN_EMAIL = "juan@test.com"
JUAN_PASS = "juan123"


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_h(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="module")
def juan_token():
    r = requests.post(f"{API}/auth/login", json={"email": JUAN_EMAIL, "password": JUAN_PASS}, timeout=15)
    if r.status_code != 200:
        pytest.skip("juan@test.com not seeded")
    return r.json()["access_token"]


# ============= BRANDING =============
class TestBrandingPublicRead:
    def test_get_branding_public_no_auth(self):
        r = requests.get(f"{API}/branding", timeout=10)
        assert r.status_code == 200
        d = r.json()
        for k in ["product_name", "tagline", "primary_color", "accent_color",
                  "background_color", "text_color", "logo_data_url",
                  "company_name", "support_email"]:
            assert k in d, f"missing field {k}"


class TestBrandingPutAuth:
    def test_put_no_token_returns_401(self):
        r = requests.put(f"{API}/branding", json={"product_name": "X"}, timeout=10)
        assert r.status_code == 401

    def test_put_affiliate_returns_403(self, juan_token):
        h = {"Authorization": f"Bearer {juan_token}"}
        r = requests.put(f"{API}/branding", json={"product_name": "X"}, headers=h, timeout=10)
        assert r.status_code == 403

    def test_reset_no_token_returns_401(self):
        r = requests.post(f"{API}/branding/reset", timeout=10)
        assert r.status_code == 401

    def test_reset_affiliate_returns_403(self, juan_token):
        h = {"Authorization": f"Bearer {juan_token}"}
        r = requests.post(f"{API}/branding/reset", headers=h, timeout=10)
        assert r.status_code == 403


class TestBrandingPutAdmin:
    def test_put_admin_updates_and_merges(self, admin_h):
        payload = {"product_name": "Aurora Bot", "primary_color": "#ff6b9d"}
        r = requests.put(f"{API}/branding", json=payload, headers=admin_h, timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["product_name"] == "Aurora Bot"
        assert d["primary_color"] == "#ff6b9d"
        # merged with defaults
        assert d["accent_color"]  # still present
        assert "background_color" in d
        # Verify GET reflects persisted value
        r2 = requests.get(f"{API}/branding", timeout=10)
        assert r2.status_code == 200
        d2 = r2.json()
        assert d2["product_name"] == "Aurora Bot"
        assert d2["primary_color"] == "#ff6b9d"

    def test_put_large_logo_500kb_accepted(self, admin_h):
        # 500KB raw -> ~667KB base64. We use 360KB raw -> ~480KB b64 (under MAX 2MB)
        raw = b"A" * (360 * 1024)
        data_url = "data:image/png;base64," + base64.b64encode(raw).decode()
        r = requests.put(f"{API}/branding", json={"logo_data_url": data_url}, headers=admin_h, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json()["logo_data_url"].startswith("data:image/png;base64,")

    def test_reset_restores_defaults(self, admin_h):
        r = requests.post(f"{API}/branding/reset", headers=admin_h, timeout=10)
        assert r.status_code == 200
        d = r.json()
        assert d["product_name"] == "Lluvia App Studio"
        assert d["primary_color"] == "#5fb4ff"
        assert d["accent_color"] == "#5fdbc4"
        assert d["logo_data_url"] == ""


# ============= SALE DEFENSE: deactivated affiliate =============
class TestSaleDeactivatedAffiliate:
    def test_create_sale_for_deactivated_returns_400(self, admin_h, juan_token):
        # Find Juan's id
        r = requests.get(f"{API}/affiliates", headers=admin_h, timeout=10)
        assert r.status_code == 200
        juan = next((a for a in r.json() if a["email"] == JUAN_EMAIL), None)
        if not juan:
            pytest.skip("juan not present")
        original_active = juan["active"]
        code = juan["affiliate_code"]
        try:
            # deactivate
            r2 = requests.patch(f"{API}/affiliates/{juan['id']}", json={"active": False}, headers=admin_h, timeout=10)
            assert r2.status_code == 200
            assert r2.json()["active"] is False
            # try sale -> 400
            sale = {"affiliate_code": code, "amount": 100, "product": "TEST_DefenseProduct"}
            r3 = requests.post(f"{API}/sales", json=sale, headers=admin_h, timeout=10)
            assert r3.status_code == 400, r3.text
        finally:
            requests.patch(f"{API}/affiliates/{juan['id']}", json={"active": original_active}, headers=admin_h, timeout=10)


# ============= EXISTING REGRESSION =============
class TestRegression:
    def test_root(self):
        r = requests.get(f"{API}/", timeout=10)
        assert r.status_code == 200
        assert r.json()["service"] == "Bot Multiplataforma"

    def test_status(self):
        r = requests.get(f"{API}/status", timeout=10)
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_admin_login(self):
        r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=10)
        assert r.status_code == 200
        assert r.json()["user"]["role"] == "admin"

    def test_juan_login_and_stats(self, juan_token):
        h = {"Authorization": f"Bearer {juan_token}"}
        r = requests.get(f"{API}/auth/me", headers=h, timeout=10)
        assert r.status_code == 200
        assert r.json()["email"] == JUAN_EMAIL
        # stats/me
        rs = requests.get(f"{API}/stats/me", headers=h, timeout=10)
        assert rs.status_code == 200
        d = rs.json()
        assert "total_sales" in d
        assert d.get("affiliate_code")

    def test_juan_cannot_access_network_stats(self, juan_token):
        h = {"Authorization": f"Bearer {juan_token}"}
        r = requests.get(f"{API}/stats/network", headers=h, timeout=10)
        assert r.status_code == 403

    def test_admin_network_stats(self, admin_h):
        r = requests.get(f"{API}/stats/network", headers=admin_h, timeout=10)
        assert r.status_code == 200
        d = r.json()
        assert "overall" in d and "breakdown" in d


# ============= PERSISTENCE TEST (restart backend) =============
class TestPersistenceAfterRestart:
    def test_persistence_after_backend_restart(self, admin_h):
        # 1) Set a unique branding marker
        marker = f"PersistTest-{int(time.time())}"
        r = requests.put(f"{API}/branding", json={"product_name": marker}, headers=admin_h, timeout=10)
        assert r.status_code == 200
        # Snapshot affiliates count and juan
        a_before = requests.get(f"{API}/affiliates", headers=admin_h, timeout=10).json()
        s_before = requests.get(f"{API}/sales", headers=admin_h, timeout=10).json()
        juan_before = next((a for a in a_before if a["email"] == JUAN_EMAIL), None)

        # 2) Restart backend
        subprocess.run(["sudo", "supervisorctl", "restart", "backend"], check=False, timeout=30)
        # Wait for backend up
        for _ in range(20):
            time.sleep(1)
            try:
                rr = requests.get(f"{API}/", timeout=5)
                if rr.status_code == 200:
                    break
            except Exception:
                continue
        # extra grace
        time.sleep(2)

        # 3) Verify persistence
        rb = requests.get(f"{API}/branding", timeout=10)
        assert rb.status_code == 200
        assert rb.json()["product_name"] == marker, "branding not persisted after restart"

        # Re-login admin (token still valid 8h, but be safe)
        rl = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=10)
        assert rl.status_code == 200
        h = {"Authorization": f"Bearer {rl.json()['access_token']}"}

        a_after = requests.get(f"{API}/affiliates", headers=h, timeout=10).json()
        s_after = requests.get(f"{API}/sales", headers=h, timeout=10).json()
        assert len(a_after) == len(a_before), "affiliates lost after restart"
        assert len(s_after) == len(s_before), "sales lost after restart"
        if juan_before:
            juan_after = next((a for a in a_after if a["email"] == JUAN_EMAIL), None)
            assert juan_after is not None
            assert juan_after["affiliate_code"] == juan_before["affiliate_code"]

        # 4) Cleanup: reset branding to defaults
        requests.post(f"{API}/branding/reset", headers=h, timeout=10)
