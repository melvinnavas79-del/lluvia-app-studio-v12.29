"""
Iteration 21 — Gmail Maestro Auto-Send (OPCION C).

Backend tests (mocked):
- AUTOSEND_CONFIDENCE_THRESHOLD = 0.9 y AUTOSEND_CATEGORIES = {'lead-caliente','soporte'}
- _send_gmail_draft(token, draft_id) hace POST a /drafts/send y devuelve message_id o None
- _process_inbox_for_user con monkeypatch de requests.get/post + _classify_and_draft:
   * Caso A: conf 0.95 + lead-caliente -> auto_sent=True
   * Caso B: conf 0.80 + lead-caliente -> auto_sent=False (draft creado pero NO enviado)
   * Caso C: conf 0.99 + comercial    -> auto_sent=False (categoria no califica)
- System prompt de _classify_and_draft contiene reglas de auto-senders
- GET /api/integrations/gmail/maestro/metrics expone auto_sent/autosend_threshold/autosend_categories
"""

import asyncio
import inspect
import os
import uuid

import pytest
import requests

import gmail_maestro
from gmail_maestro import (
    AUTOSEND_CATEGORIES,
    AUTOSEND_CONFIDENCE_THRESHOLD,
    _classify_and_draft,
    _process_inbox_for_user,
    _send_gmail_draft,
    set_db,
)


BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://ai-bot-cost-calc.preview.emergentagent.com",
).rstrip("/")
ADMIN_EMAIL = "melvinnavas79@gmail.com"
ADMIN_PASSWORD = "Admin#2026"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _login(email: str, password: str) -> str:
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password},
        timeout=15,
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:200]}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_token() -> str:
    return _login(ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture(scope="module")
def admin_h(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


def _get_db():
    from motor.motor_asyncio import AsyncIOMotorClient
    cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
    return cli, cli[os.environ["DB_NAME"]]


class _FakeResp:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text

    def json(self):
        return self._json


# ============================================================
# 1. Constantes
# ============================================================
class TestConstants:
    def test_autosend_threshold_is_09(self):
        assert AUTOSEND_CONFIDENCE_THRESHOLD == 0.9

    def test_autosend_categories(self):
        assert AUTOSEND_CATEGORIES == {"lead-caliente", "soporte"}


# ============================================================
# 2. _send_gmail_draft
# ============================================================
class TestSendDraft:
    def test_send_draft_success(self, monkeypatch):
        captured = {}

        def fake_post(url, headers=None, json=None, timeout=None):
            captured["url"] = url
            captured["json"] = json
            return _FakeResp(200, {"id": "msg-abc-123"})

        monkeypatch.setattr(gmail_maestro.requests, "post", fake_post)
        result = asyncio.run(_send_gmail_draft("fake_token", "draft-1"))
        assert result == "msg-abc-123"
        assert captured["url"].endswith("/drafts/send")
        assert captured["json"] == {"id": "draft-1"}

    def test_send_draft_failure_returns_none(self, monkeypatch):
        def fake_post(url, headers=None, json=None, timeout=None):
            return _FakeResp(403, {"error": "no perms"}, text="forbidden")

        monkeypatch.setattr(gmail_maestro.requests, "post", fake_post)
        result = asyncio.run(_send_gmail_draft("fake_token", "draft-2"))
        assert result is None

    def test_send_draft_exception_returns_none(self, monkeypatch):
        def fake_post(url, headers=None, json=None, timeout=None):
            raise RuntimeError("network down")

        monkeypatch.setattr(gmail_maestro.requests, "post", fake_post)
        result = asyncio.run(_send_gmail_draft("fake_token", "draft-3"))
        assert result is None


# ============================================================
# 3. _process_inbox_for_user (mocked end-to-end)
# ============================================================
def _install_process_inbox_mocks(monkeypatch, classify_result, message_id="m-1"):
    """Patches requests.get/post + _classify_and_draft + _get_valid_access_token.
    Returns a `calls` dict to inspect what happened."""
    calls = {
        "list_get": 0,
        "msg_get": 0,
        "draft_create_post": 0,
        "draft_send_post": 0,
    }

    async def fake_token(user_id):
        return "fake_access_token"

    async def fake_classify(subject, from_addr, body):
        return classify_result

    def fake_get(url, headers=None, params=None, timeout=None):
        if url.endswith("/messages"):
            calls["list_get"] += 1
            return _FakeResp(200, {"messages": [{"id": message_id}]})
        if f"/messages/{message_id}" in url:
            calls["msg_get"] += 1
            return _FakeResp(200, {
                "id": message_id,
                "threadId": "thr-1",
                "snippet": "hola quiero comprar",
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": "Consulta"},
                        {"name": "From", "value": "cliente@example.com"},
                        {"name": "Message-ID", "value": "<orig@x>"},
                    ],
                    "body": {"data": ""},
                },
            })
        return _FakeResp(404, {})

    def fake_post(url, headers=None, json=None, timeout=None, data=None):
        if url.endswith("/drafts"):
            calls["draft_create_post"] += 1
            return _FakeResp(200, {"id": "draft-X"})
        if url.endswith("/drafts/send"):
            calls["draft_send_post"] += 1
            return _FakeResp(200, {"id": "sent-msg-Y"})
        return _FakeResp(404, {})

    monkeypatch.setattr(gmail_maestro, "_get_valid_access_token", fake_token)
    monkeypatch.setattr(gmail_maestro, "_classify_and_draft", fake_classify)
    monkeypatch.setattr(gmail_maestro.requests, "get", fake_get)
    monkeypatch.setattr(gmail_maestro.requests, "post", fake_post)
    return calls


class TestProcessInboxAutoSend:
    def _run(self, monkeypatch, classify_result, mid_suffix=""):
        """Setup DB, run _process_inbox_for_user once, return inserted doc + calls."""
        # Unique user/message ids per test so we don't collide with previous runs
        user_id = f"test-user-{uuid.uuid4().hex[:8]}"
        message_id = f"msg-{uuid.uuid4().hex[:8]}{mid_suffix}"
        calls = _install_process_inbox_mocks(monkeypatch, classify_result, message_id=message_id)

        async def _do():
            cli, db = _get_db()
            set_db(db)
            try:
                result = await _process_inbox_for_user(user_id, max_msgs=5)
                doc = await db.gmail_processed.find_one(
                    {"user_id": user_id, "message_id": message_id}, {"_id": 0}
                )
                # cleanup
                await db.gmail_processed.delete_many({"user_id": user_id})
                return result, doc
            finally:
                cli.close()

        result, doc = asyncio.run(_do())
        return result, doc, calls

    def test_caseA_high_confidence_lead_caliente_autosends(self, monkeypatch):
        classify = {
            "category": "lead-caliente",
            "confidence": 0.95,
            "reply_draft": "Hola, gracias por escribirnos. Te enviamos info.",
            "reasoning": "prospect wants pricing",
        }
        result, doc, calls = self._run(monkeypatch, classify, "-A")
        assert result["ok"] is True
        assert doc is not None, "doc not inserted"
        assert calls["draft_create_post"] == 1, "draft was NOT created"
        assert calls["draft_send_post"] == 1, "draft was NOT auto-sent"
        assert doc["auto_sent"] is True
        assert doc["sent_message_id"] == "sent-msg-Y"
        assert doc["category"] == "lead-caliente"
        assert doc["confidence"] == 0.95
        assert doc["draft_id"] == "draft-X"

    def test_caseB_low_confidence_no_autosend(self, monkeypatch):
        classify = {
            "category": "lead-caliente",
            "confidence": 0.8,  # debajo del threshold 0.9
            "reply_draft": "Borrador tibio.",
            "reasoning": "not sure",
        }
        result, doc, calls = self._run(monkeypatch, classify, "-B")
        assert result["ok"] is True
        assert doc is not None
        assert calls["draft_create_post"] == 1, "draft should still be created"
        assert calls["draft_send_post"] == 0, "should NOT auto-send below threshold"
        assert doc["auto_sent"] is False
        assert doc["sent_message_id"] is None
        assert doc["draft_id"] == "draft-X"

    def test_caseC_high_confidence_comercial_no_autosend(self, monkeypatch):
        classify = {
            "category": "comercial",
            "confidence": 0.99,  # alto pero categoria no califica
            "reply_draft": "Gracias por el contacto comercial.",
            "reasoning": "vendor offer",
        }
        result, doc, calls = self._run(monkeypatch, classify, "-C")
        assert result["ok"] is True
        assert doc is not None
        assert calls["draft_create_post"] == 1
        assert calls["draft_send_post"] == 0, "comercial no debe auto-enviarse"
        assert doc["auto_sent"] is False
        assert doc["sent_message_id"] is None
        assert doc["category"] == "comercial"

    def test_caseD_high_confidence_soporte_autosends(self, monkeypatch):
        """Refuerzo: soporte tambien califica para auto-envio."""
        classify = {
            "category": "soporte",
            "confidence": 0.92,
            "reply_draft": "Te ayudamos con tu duda tecnica.",
            "reasoning": "real support",
        }
        result, doc, calls = self._run(monkeypatch, classify, "-D")
        assert doc is not None
        assert calls["draft_send_post"] == 1
        assert doc["auto_sent"] is True
        assert doc["sent_message_id"] == "sent-msg-Y"

    def test_caseE_spam_no_draft_no_send(self, monkeypatch):
        """Spam: no se crea draft ni se envia."""
        classify = {
            "category": "spam",
            "confidence": 0.99,
            "reply_draft": "",  # vacio segun nuevas reglas
            "reasoning": "facebook notification",
        }
        result, doc, calls = self._run(monkeypatch, classify, "-E")
        assert doc is not None
        assert calls["draft_create_post"] == 0
        assert calls["draft_send_post"] == 0
        assert doc["auto_sent"] is False
        assert doc["draft_id"] is None


# ============================================================
# 4. System prompt — auto-sender rules
# ============================================================
class TestSystemPrompt:
    def test_prompt_contains_autosender_rules(self):
        src = inspect.getsource(_classify_and_draft)
        # Reglas clave del nuevo prompt
        assert "facebookmail.com" in src
        assert "accounts.google.com" in src
        assert "no-reply" in src or "noreply" in src
        assert "category='spam'" in src or '"category": "spam"' in src or "spam" in src
        # Debe forzar reply_draft vacio para spam
        assert "reply_draft" in src
        assert "Lluvia App Studio" in src

    def test_classify_returns_spam_for_facebook_when_llm_says_so(self, monkeypatch):
        """Simulamos un LLM que respeta el prompt y devuelve spam.
        No probamos al LLM real, sino que la funcion deserializa correctamente
        la respuesta JSON con category='spam', confidence>=0.9, reply_draft=''."""

        class _FakeChoice:
            def __init__(self, content):
                self.message = type("M", (), {"content": content})()

        class _FakeResp:
            def __init__(self, content):
                self.choices = [_FakeChoice(content)]

        class _FakeCompletions:
            async def create(self, **kwargs):
                return _FakeResp(
                    '{"category":"spam","confidence":0.95,'
                    '"reply_draft":"","reasoning":"facebook auto-notification"}'
                )

        class _FakeClient:
            def __init__(self, *a, **kw):
                self.chat = type("C", (), {"completions": _FakeCompletions()})()

        # Forzar branch OPENAI_API_KEY
        monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
        # Patch AsyncOpenAI dentro del modulo openai (el import es lazy)
        import openai
        monkeypatch.setattr(openai, "AsyncOpenAI", _FakeClient)

        result = asyncio.run(_classify_and_draft(
            subject="(1) Tienes una nueva notificacion",
            from_addr="notification@priority.facebookmail.com",
            body="You have a new notification on Facebook.",
        ))
        assert result["category"] == "spam"
        assert result["confidence"] >= 0.9
        assert result["reply_draft"] == ""


# ============================================================
# 5. /metrics endpoint expone nuevos campos
# ============================================================
class TestMetricsEndpoint:
    def test_metrics_has_autosend_fields(self, admin_h):
        r = requests.get(
            f"{BASE_URL}/api/integrations/gmail/maestro/metrics",
            headers=admin_h, timeout=15,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        # Campos nuevos
        assert "auto_sent" in data
        assert isinstance(data["auto_sent"], int)
        assert "autosend_threshold" in data
        assert data["autosend_threshold"] == 0.9
        assert "autosend_categories" in data
        assert isinstance(data["autosend_categories"], list)
        assert set(data["autosend_categories"]) == {"lead-caliente", "soporte"}
        # Campos antiguos preservados
        assert "total_processed" in data
        assert "with_drafts" in data
        assert "by_category" in data
        assert "estimated_minutes_saved" in data

    def test_metrics_requires_admin(self):
        # sin token -> 401/403
        r = requests.get(
            f"{BASE_URL}/api/integrations/gmail/maestro/metrics", timeout=10
        )
        assert r.status_code in (401, 403)
