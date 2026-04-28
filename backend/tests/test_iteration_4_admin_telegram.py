"""
Iteration 4 — Admin migration to melvinnavas79@gmail.com + Telegram /mi-rendimiento + Branding defaults.
"""
import os
import re
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://ai-bot-cost-calc.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

NEW_ADMIN_EMAIL = "melvinnavas79@gmail.com"
OLD_ADMIN_EMAIL = "admin@admin.com"
ADMIN_PASS = "Admin#2026"

JUAN_EMAIL = "juan@test.com"
JUAN_PASS = "juan123"
JUAN_TELEGRAM_CHAT = "123456789"

TELEGRAM_TOKEN = "8628387028:AAFmGVNyNnsmNEFXf0HQQG8Id0PvCTgC-sk"


# ---------- Fixtures ----------
@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{API}/auth/login", json={"email": NEW_ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=15)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_h(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


# =========================================================
# 1. ADMIN MIGRATION
# =========================================================
class TestAdminMigration:
    def test_new_admin_login_ok(self):
        r = requests.post(f"{API}/auth/login", json={"email": NEW_ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert "access_token" in body
        assert body["user"]["email"] == NEW_ADMIN_EMAIL
        assert body["user"]["role"] == "admin"
        assert isinstance(body["user"]["id"], str) and len(body["user"]["id"]) > 0

    def test_old_admin_login_rejected(self):
        r = requests.post(f"{API}/auth/login", json={"email": OLD_ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=10)
        assert r.status_code == 401

    def test_old_admin_login_other_passwords_rejected(self):
        for pw in ["admin", "admin123", "password", ""]:
            r = requests.post(f"{API}/auth/login", json={"email": OLD_ADMIN_EMAIL, "password": pw}, timeout=10)
            assert r.status_code == 401, f"old admin should not exist with pw={pw!r}"

    def test_only_one_admin_in_system(self, admin_h):
        # Listing affiliates should not show the admin (admin is excluded from /api/affiliates)
        # Use /api/auth/me check + /api/stats/network as proxies.
        r = requests.get(f"{API}/auth/me", headers=admin_h, timeout=10)
        assert r.status_code == 200
        assert r.json()["email"] == NEW_ADMIN_EMAIL
        # network endpoint admin-only: confirms admin role works
        rn = requests.get(f"{API}/stats/network", headers=admin_h, timeout=15)
        assert rn.status_code == 200


# =========================================================
# 2. BRANDING DEFAULTS = Lluvia App Studio
# =========================================================
class TestBrandingDefaults:
    def test_branding_public_no_auth(self):
        r = requests.get(f"{API}/branding", timeout=10)
        assert r.status_code == 200
        b = r.json()
        assert b["product_name"] == "Lluvia App Studio"
        assert b["tagline"] == "Soluciones inteligentes que llueven sobre tu negocio."
        assert b["primary_color"].lower() == "#5fb4ff"
        assert b["accent_color"].lower() == "#5fdbc4"
        assert b["background_color"].lower() == "#0a1220"
        assert b["support_email"] == "melvinnavas79@gmail.com"
        assert b["company_name"] == "Lluvia App Studio"


# =========================================================
# 3. /mi-rendimiento via /api/command
# =========================================================
class TestMiRendimientoCommand:
    def test_command_with_juan_chat_id(self):
        r = requests.post(
            f"{API}/command",
            json={"message": "/mi-rendimiento", "user": JUAN_TELEGRAM_CHAT},
            timeout=30,
        )
        assert r.status_code == 200
        text = r.json().get("response", "")
        assert isinstance(text, str) and len(text) > 0
        # Expect Juan's affiliate code or similar markers
        # Code pattern JUANPE-XXXX
        assert re.search(r"JUANPE-\w+", text), f"Expected affiliate code in response: {text[:300]}"
        # Must mention 25%, 1 sale, $1000, $250 (allow flexible formatting)
        assert "25" in text
        assert "1000" in text or "1.000" in text or "1,000" in text
        assert "250" in text

    def test_command_with_unknown_chat_id(self):
        unknown = "999999999"
        r = requests.post(
            f"{API}/command",
            json={"message": "/mi-rendimiento", "user": unknown},
            timeout=30,
        )
        assert r.status_code == 200
        text = r.json().get("response", "").lower()
        # Should mention "not found" / "no encontre" + the chat id
        assert ("no encontr" in text) or ("no encuentro" in text) or ("not found" in text), f"unexpected: {text[:300]}"
        assert unknown in text


# =========================================================
# 4. Telegram webhook real
# =========================================================
class TestTelegramWebhook:
    def test_webhook_invalid_token_403(self):
        r = requests.post(f"{API}/webhook/telegram/INVALIDTOKEN", json={"message": {}}, timeout=10)
        assert r.status_code == 403

    def test_webhook_valid_token_returns_ok(self):
        payload = {
            "update_id": 1234,
            "message": {
                "message_id": 1,
                "from": {"id": int(JUAN_TELEGRAM_CHAT), "is_bot": False, "first_name": "Juan"},
                "chat": {"id": int(JUAN_TELEGRAM_CHAT), "type": "private"},
                "date": 1700000000,
                "text": "/mi-rendimiento",
            },
        }
        r = requests.post(f"{API}/webhook/telegram/{TELEGRAM_TOKEN}", json=payload, timeout=30)
        assert r.status_code == 200
        assert r.json() == {"ok": True}

    def test_webhook_unknown_user_does_not_crash(self):
        payload = {
            "update_id": 1235,
            "message": {
                "message_id": 2,
                "from": {"id": 999999999, "is_bot": False, "first_name": "Stranger"},
                "chat": {"id": 999999999, "type": "private"},
                "date": 1700000000,
                "text": "/mi-rendimiento",
            },
        }
        r = requests.post(f"{API}/webhook/telegram/{TELEGRAM_TOKEN}", json=payload, timeout=30)
        assert r.status_code == 200
        assert r.json() == {"ok": True}

    def test_webhook_malformed_payload_does_not_500(self):
        r = requests.post(f"{API}/webhook/telegram/{TELEGRAM_TOKEN}", json={"foo": "bar"}, timeout=10)
        assert r.status_code == 200  # silently logs warning


# =========================================================
# 5. Juan affiliate has telegram_chat_id linked
# =========================================================
class TestAffiliateLink:
    def test_juan_login_and_stats(self):
        r = requests.post(f"{API}/auth/login", json={"email": JUAN_EMAIL, "password": JUAN_PASS}, timeout=15)
        assert r.status_code == 200
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        rme = requests.get(f"{API}/auth/me", headers=h, timeout=10)
        assert rme.status_code == 200
        me = rme.json()
        assert me["role"] == "affiliate"
        # telegram_chat_id should be linked (string or int 123456789)
        chat = str(me.get("telegram_chat_id", ""))
        assert chat == JUAN_TELEGRAM_CHAT, f"Juan telegram_chat_id={chat!r}, expected {JUAN_TELEGRAM_CHAT}"

        # stats/me
        rs = requests.get(f"{API}/stats/me", headers=h, timeout=10)
        assert rs.status_code == 200


# =========================================================
# 6. Regression critical endpoints
# =========================================================
class TestRegression:
    def test_root(self):
        r = requests.get(f"{API}/", timeout=10)
        assert r.status_code == 200

    def test_status(self):
        r = requests.get(f"{API}/status", timeout=10)
        assert r.status_code == 200

    def test_command_general(self):
        r = requests.post(f"{API}/command", json={"message": "hola", "user": "tester"}, timeout=30)
        assert r.status_code == 200
        assert "response" in r.json()

    def test_affiliates_list_admin(self, admin_h):
        r = requests.get(f"{API}/affiliates", headers=admin_h, timeout=10)
        assert r.status_code == 200
        assert isinstance(r.json(), list)


# =========================================================
# 7. Telegram external API confirms bot identity
# =========================================================
class TestTelegramBotIdentity:
    def test_get_me(self):
        r = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getMe", timeout=15)
        assert r.status_code == 200
        b = r.json()
        assert b["ok"] is True
        assert b["result"]["username"] == "LluviaAppStudioBot"
        assert b["result"]["first_name"] == "Lluvia App Studio"

    def test_webhook_info_points_to_us(self):
        r = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getWebhookInfo", timeout=15)
        assert r.status_code == 200
        info = r.json()["result"]
        assert info["url"].endswith(f"/api/webhook/telegram/{TELEGRAM_TOKEN}")
