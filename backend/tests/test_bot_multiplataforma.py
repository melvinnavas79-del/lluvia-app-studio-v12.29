"""
Backend tests for Bot Multiplataforma.
Covers: health, status, /command flows, webhooks (WhatsApp/Telegram/Instagram),
security, app generation, GitHub guard, and AI memory.
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://ai-bot-cost-calc.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ---------------- Basic ----------------
class TestBasicEndpoints:
    def test_root(self, client):
        r = client.get(f"{API}/", timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["service"] == "Bot Multiplataforma"
        assert d["status"] == "running"
        assert "telegram" in d["platforms"]

    def test_status(self, client):
        r = client.get(f"{API}/status", timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["ok"] is True
        creds = d["credentials"]
        assert "llm_ready" in creds
        assert creds["model"] == "gpt-4o-mini" or "gpt" in creds["model"]
        assert "memory" in d
        assert "total_users" in d["memory"]


# ---------------- /command commands ----------------
class TestCommands:
    def test_help_command(self, client):
        r = client.post(f"{API}/command", json={"message": "/help", "user": "t1"}, timeout=20)
        assert r.status_code == 200
        resp = r.json()["response"]
        assert "crear app" in resp.lower() or "comandos" in resp.lower()

    def test_status_command(self, client):
        r = client.post(f"{API}/command", json={"message": "/status", "user": "t1"}, timeout=20)
        assert r.status_code == 200
        resp = r.json()["response"]
        assert "Estado" in resp or "estado" in resp.lower()
        assert "IA" in resp or "ia" in resp.lower()

    def test_create_app(self, client):
        r = client.post(f"{API}/command", json={"message": "crear app Mi Tienda", "user": "t1"}, timeout=30)
        assert r.status_code == 200
        resp = r.json()["response"]
        assert "creada" in resp.lower()
        assert "Mi Tienda" in resp or "mi-tienda" in resp.lower()

        # verify file persisted via /status -> generated_apps
        s = client.get(f"{API}/status", timeout=15).json()
        apps = s.get("generated_apps", [])
        assert any("mi-tienda" in a.lower() for a in apps), f"App file not found: {apps}"

    def test_github_not_configured(self, client):
        r = client.post(f"{API}/command", json={"message": "crear repo test", "user": "t1"}, timeout=20)
        assert r.status_code == 200
        resp = r.json()["response"].lower()
        assert "github" in resp and ("no" in resp and "configura" in resp)

    def test_server_command_echo(self, client):
        r = client.post(f"{API}/command", json={"message": "ejecuta echo hello", "user": "t1"}, timeout=30)
        assert r.status_code == 200
        resp = r.json()["response"]
        assert "hello" in resp

    def test_security_blocks_dangerous(self, client):
        r = client.post(f"{API}/command", json={"message": "ejecuta rm -rf /", "user": "t1"}, timeout=20)
        assert r.status_code == 200
        resp = r.json()["response"].lower()
        assert "rechazado" in resp or "bloqueado" in resp or "seguridad" in resp

    def test_command_missing_message(self, client):
        r = client.post(f"{API}/command", json={"user": "t1"}, timeout=15)
        assert r.status_code == 400


# ---------------- AI / Memory ----------------
class TestAI:
    def test_ai_business_reply(self, client):
        r = client.post(
            f"{API}/command",
            json={"message": "Hola, quiero vender online", "user": "cliente1"},
            timeout=90,
        )
        assert r.status_code == 200
        resp = r.json()["response"]
        # substantial AI response (not error and not template)
        assert len(resp) > 40, f"AI response too short: {resp}"
        low = resp.lower()
        assert "error generando" not in low
        assert "no esta configurado" not in low

    def test_memory_context_followup(self, client):
        user = "ctx_user_42"
        r1 = client.post(
            f"{API}/command",
            json={"message": "Mi tienda se llama Aurora y vende velas aromaticas.", "user": user},
            timeout=90,
        )
        assert r1.status_code == 200
        time.sleep(1)
        r2 = client.post(
            f"{API}/command",
            json={"message": "Como se llama mi tienda?", "user": user},
            timeout=90,
        )
        assert r2.status_code == 200
        resp2 = r2.json()["response"].lower()
        assert "aurora" in resp2, f"Context not preserved. Response: {resp2}"


# ---------------- Webhooks ----------------
class TestWhatsAppWebhook:
    def test_verify_ok(self, client):
        r = client.get(
            f"{API}/webhook/whatsapp",
            params={"hub.verify_token": "12345", "hub.challenge": "ABC123"},
            timeout=10,
        )
        assert r.status_code == 200
        assert r.text == "ABC123"

    def test_verify_wrong_token(self, client):
        r = client.get(
            f"{API}/webhook/whatsapp",
            params={"hub.verify_token": "wrong", "hub.challenge": "X"},
            timeout=10,
        )
        assert r.status_code == 403

    def test_post_valid_payload(self, client):
        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": "5491100000000",
                            "text": {"body": "/help"},
                        }]
                    }
                }]
            }]
        }
        r = client.post(f"{API}/webhook/whatsapp", json=payload, timeout=30)
        assert r.status_code == 200
        assert r.json() == {"ok": True}


class TestTelegramWebhook:
    def test_invalid_token_403(self, client):
        r = client.post(
            f"{API}/webhook/telegram/INVALIDTOKEN12345",
            json={"message": {"text": "hi", "chat": {"id": 1}}},
            timeout=10,
        )
        assert r.status_code == 403


class TestInstagramWebhook:
    def test_post_valid_payload(self, client):
        payload = {
            "entry": [{
                "messaging": [{
                    "sender": {"id": "u_demo_42"},
                    "message": {"text": "/help"},
                }]
            }]
        }
        r = client.post(f"{API}/webhook/instagram", json=payload, timeout=30)
        assert r.status_code == 200
        assert r.json() == {"ok": True}
