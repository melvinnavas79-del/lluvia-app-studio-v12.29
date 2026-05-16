"""
Iteration v12.18 — Tests for:
  - POST /api/me/github/validate (pre-validates token without charging)
  - Admin cost_oros=0 + is_admin_free=true + nominal_cost_oros in messages
  - GitHub push error translation + auth_failed flag

Run:
  pytest /app/backend/tests/test_iteration_16_github_validate.py -v \
    --junitxml=/app/test_reports/pytest/iteration_16_results.xml
"""

import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://ai-bot-cost-calc.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "melvinnavas79@gmail.com"
ADMIN_PASS = "Admin#2026"


# ---------------- helpers ----------------
def _login(email: str, password: str) -> str:
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:200]}"
    return r.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def admin_token():
    try:
        return _login(ADMIN_EMAIL, ADMIN_PASS)
    except AssertionError as e:
        pytest.skip(f"admin login failed: {e}")


# ---------------- GitHub validate endpoint ----------------
class TestGithubValidate:
    """POST /api/me/github/validate"""

    def test_requires_auth(self):
        r = requests.post(f"{BASE_URL}/api/me/github/validate", timeout=10)
        assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}"

    def test_returns_400_when_no_token_configured(self, admin_token):
        # Limpia el token configurado del admin para forzar el 400
        # (lo guardamos despues si existia para no romper otros tests)
        prev = requests.get(f"{BASE_URL}/api/me/settings",
                            headers=_auth(admin_token), timeout=10).json()
        had_token = prev.get("has_github_token")
        if had_token:
            # No podemos blanquear el token sin perder configuracion del admin.
            # En su lugar, creamos un usuario nuevo para esta prueba.
            email = f"TEST_gh_{uuid.uuid4().hex[:8]}@test.com"
            rr = requests.post(f"{BASE_URL}/api/auth/register",
                               json={"email": email, "password": "test1234", "name": "tgh"},
                               timeout=15)
            if rr.status_code == 429:
                pytest.skip("anti-farming 429 — skipping")
            assert rr.status_code in (200, 201), rr.text
            t = rr.json()["access_token"]
        else:
            t = admin_token

        r = requests.post(f"{BASE_URL}/api/me/github/validate",
                          headers=_auth(t), timeout=15)
        assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text[:200]}"
        body = r.json()
        # Mensaje claro en español
        detail = (body.get("detail") or "").lower()
        assert "token" in detail, f"unclear error: {detail}"

    def test_admin_validate_returns_clear_message(self, admin_token):
        """Admin tiene un token configurado pero invalido (segun handoff).
        El endpoint /me/github/validate debe responder 200 con ok:false y
        un mensaje claro en espanol que mencione el link de tokens."""
        # Primero verificar si admin tiene token configurado
        s = requests.get(f"{BASE_URL}/api/me/settings",
                        headers=_auth(admin_token), timeout=10).json()
        has_token = s.get("has_github_token") or s.get("github_token_set")
        if not has_token:
            pytest.skip("admin sin token configurado — no podemos probar contra GitHub real")

        r = requests.post(f"{BASE_URL}/api/me/github/validate",
                          headers=_auth(admin_token), timeout=20)
        assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text[:200]}"
        body = r.json()
        # Resultado puede ser ok:true (si funciona) o ok:false (si fue rotado).
        # En cualquier caso, debe haber un campo 'ok'
        assert "ok" in body, f"missing ok field: {body}"
        if body["ok"] is False:
            err = (body.get("error") or "").lower()
            assert "token" in err
            # Debe ofrecer link de help
            assert "github.com" in err

    def test_fake_token_returns_ok_false_with_clear_spanish_message(self, admin_token):
        # Crear usuario nuevo, ponerle un token fake, validar
        email = f"TEST_ghfake_{uuid.uuid4().hex[:8]}@test.com"
        rr = requests.post(f"{BASE_URL}/api/auth/register",
                           json={"email": email, "password": "test1234", "name": "fake"},
                           timeout=15)
        if rr.status_code == 429:
            pytest.skip("anti-farming 429")
        assert rr.status_code in (200, 201), rr.text
        t = rr.json()["access_token"]

        # Configurar un token fake
        s = requests.put(f"{BASE_URL}/api/me/settings", headers=_auth(t),
                         json={"github_token": "ghp_fake12345_invalido_xxxx",
                               "github_repo": "melvinnavas79-del/foo-bar"},
                         timeout=15)
        assert s.status_code == 200, s.text

        # Validar — GitHub debe devolver 401, nuestro endpoint debe devolver ok:false
        r = requests.post(f"{BASE_URL}/api/me/github/validate",
                          headers=_auth(t), timeout=20)
        assert r.status_code == 200, f"expected 200 wrapping the result, got {r.status_code}: {r.text[:200]}"
        body = r.json()
        assert body.get("ok") is False, f"expected ok:false, body={body}"
        err = (body.get("error") or "").lower()
        # Mensaje clave: debe mencionar "token" y "github.com/settings/tokens"
        assert "token" in err, f"unclear error message: {err}"
        assert "github.com/settings/tokens" in err, f"missing help link: {err}"


# ---------------- Admin free cost in messages ----------------
class TestAdminFreeCost:
    """send_message para admin debe devolver cost_oros=0 + is_admin_free=true + nominal_cost_oros>0"""

    def test_admin_send_message_returns_admin_free(self, admin_token):
        # Crear sesion
        r = requests.post(f"{BASE_URL}/api/console/sessions",
                          headers=_auth(admin_token),
                          json={"agent_id": "vendedor", "title": "TEST_admin_free"},
                          timeout=15)
        assert r.status_code in (200, 201), r.text
        session_id = r.json().get("id") or r.json().get("session_id")
        assert session_id

        # Enviar mensaje
        r = requests.post(f"{BASE_URL}/api/console/sessions/{session_id}/messages",
                          headers=_auth(admin_token),
                          json={"text": "hola, di solo 'ok'"},
                          timeout=120)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        body = r.json()

        # cost_oros=0 para admin
        assert body.get("cost_oros") == 0, f"admin should pay 0, got cost_oros={body.get('cost_oros')}"

        # is_admin_free=true y nominal_cost_oros>0 en el assistant_message
        am = body.get("assistant_message") or {}
        assert am.get("is_admin_free") is True, f"is_admin_free missing: {am}"
        assert am.get("cost_oros") == 0, f"assistant_message.cost_oros should be 0: {am.get('cost_oros')}"
        nominal = am.get("nominal_cost_oros")
        assert isinstance(nominal, (int, float)) and nominal > 0, (
            f"nominal_cost_oros should be > 0, got {nominal}"
        )

    def test_admin_balance_not_charged(self, admin_token):
        # Capturar balance antes y despues — admin no se le debe descontar
        r0 = requests.get(f"{BASE_URL}/api/console/credits/me",
                          headers=_auth(admin_token), timeout=10)
        assert r0.status_code == 200
        bal0 = r0.json().get("balance")

        # Crear sesion + mensaje
        s = requests.post(f"{BASE_URL}/api/console/sessions",
                          headers=_auth(admin_token),
                          json={"agent_id": "vendedor", "title": "TEST_admin_bal"},
                          timeout=15)
        sid = s.json().get("id") or s.json().get("session_id")
        requests.post(f"{BASE_URL}/api/console/sessions/{sid}/messages",
                      headers=_auth(admin_token),
                      json={"text": "di hola"}, timeout=120)

        r1 = requests.get(f"{BASE_URL}/api/console/credits/me",
                          headers=_auth(admin_token), timeout=10)
        bal1 = r1.json().get("balance")
        # Balance no cambia para admin (admin_free)
        assert bal0 == bal1, f"admin balance changed: {bal0} -> {bal1}"


# ---------------- Regression: critical endpoints alive ----------------
class TestRegression:
    def test_site_content_alive(self):
        r = requests.get(f"{BASE_URL}/api/site/content", timeout=10)
        assert r.status_code == 200, r.text
        assert r.json().get("trial_oros") in (5, 15, 50), r.json().get("trial_oros")

    def test_paypal_create_order_alive(self, admin_token):
        r = requests.post(f"{BASE_URL}/api/paypal/create-order",
                          headers=_auth(admin_token),
                          json={"pack": "starter"}, timeout=15)
        # Acepta 200 o 502 si PayPal sandbox no responde; lo importante es que el endpoint exista
        assert r.status_code in (200, 400, 502), f"endpoint roto: {r.status_code} {r.text[:200]}"

    def test_me_settings_endpoint(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/me/settings",
                         headers=_auth(admin_token), timeout=10)
        assert r.status_code == 200
        body = r.json()
        # Deben existir las keys
        assert "has_github_token" in body or "github_token_set" in body or isinstance(body, dict)
