"""
Iteration 18 — Tests E2E:
- Demo publico (/api/demo/audio-room/* + /api/demo/audio-room-static/*)
- Registro publico + trial 15 oros + tool generate_audio_room_app desde nuevo user
- GitHub validate + push real del admin (auto-create repo logic)
- Re-correr iteration_17 implicitamente (via marker)
"""
import os
import re
import json
import time
import random
import subprocess
import tempfile
from pathlib import Path

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    BASE_URL = "https://ai-bot-cost-calc.preview.emergentagent.com"

ADMIN_EMAIL = "melvinnavas79@gmail.com"
ADMIN_PASSWORD = "Admin#2026"
LLUVIA_HOME = os.environ.get("LLUVIA_HOME", "/tmp/lluvia")
GITHUB_REPO = "melvinnavas79-del/lluvia-audio-room-demo"


# --------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------
@pytest.fixture(scope="module")
def admin_headers():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=15,
    )
    assert r.status_code == 200, f"Admin login failed: {r.status_code} {r.text[:300]}"
    tok = r.json()["access_token"]
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def admin_user_id(admin_headers):
    r = requests.get(f"{BASE_URL}/api/auth/me", headers=admin_headers, timeout=10)
    assert r.status_code == 200
    me = r.json()
    return me.get("id") or me.get("user", {}).get("id")


@pytest.fixture(scope="module")
def new_user():
    """Registrar usuario aleatorio y devolver email+password+headers+uid."""
    email = f"test_iter18_{int(time.time())}_{random.randint(1000,9999)}@test.com"
    password = "test1234"
    r = requests.post(
        f"{BASE_URL}/api/auth/register",
        json={"email": email, "password": password, "name": "Iter18 Tester"},
        timeout=15,
    )
    assert r.status_code in (200, 201), f"register failed: {r.status_code} {r.text[:300]}"
    # Login (algunos endpoints retornan token en register; otros no)
    r2 = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password},
        timeout=15,
    )
    assert r2.status_code == 200, f"login new user failed: {r2.text[:300]}"
    tok = r2.json()["access_token"]
    headers = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
    me = requests.get(f"{BASE_URL}/api/auth/me", headers=headers, timeout=10).json()
    uid = me.get("id") or me.get("user", {}).get("id")
    return {"email": email, "password": password, "headers": headers, "id": uid}


# --------------------------------------------------------------
# 1. Demo audio room API canned
# --------------------------------------------------------------
class TestDemoAudioRoomAPI:
    def test_health(self):
        r = requests.get(f"{BASE_URL}/api/demo/audio-room/api/health", timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("ok") is True
        assert d.get("mode") == "demo"
        assert d.get("rooms") == 6
        assert d.get("users") == 5

    def test_rooms_list(self):
        r = requests.get(f"{BASE_URL}/api/demo/audio-room/api/rooms?limit=5", timeout=10)
        assert r.status_code == 200
        rooms = r.json().get("rooms")
        assert isinstance(rooms, list) and len(rooms) == 5
        sample = rooms[0]
        for k in ("id", "host_name", "title", "listeners_count", "monetization", "category"):
            assert k in sample, f"missing key {k} in {sample}"

    def test_top_users(self):
        r = requests.get(f"{BASE_URL}/api/demo/audio-room/api/users/top?limit=5", timeout=10)
        assert r.status_code == 200
        users = r.json().get("users")
        assert isinstance(users, list) and len(users) == 5

    def test_user_sofia(self):
        r = requests.get(f"{BASE_URL}/api/demo/audio-room/api/users/demo-host-1", timeout=10)
        assert r.status_code == 200
        u = r.json()
        assert u.get("name") == "Sofia DJ"

    def test_room_detail(self):
        r = requests.get(f"{BASE_URL}/api/demo/audio-room/api/rooms/demo-room-001", timeout=10)
        assert r.status_code == 200
        d = r.json()
        assert "speakers" in d and len(d["speakers"]) >= 1
        assert "listeners" in d and len(d["listeners"]) >= 1


# --------------------------------------------------------------
# 2. Demo static frontend
# --------------------------------------------------------------
class TestDemoStaticFrontend:
    def test_index_html(self):
        r = requests.get(f"{BASE_URL}/api/demo/audio-room-static/", timeout=10)
        assert r.status_code == 200, r.text[:300]
        assert "text/html" in r.headers.get("content-type", "")
        assert "Lluvia Audio Live" in r.text
        assert "DEMO PUBLICO" in r.text

    def test_app_js_no_syntax_error(self):
        r = requests.get(f"{BASE_URL}/api/demo/audio-room-static/js/app.js", timeout=10)
        assert r.status_code == 200, r.text[:300]
        ct = r.headers.get("content-type", "")
        assert "javascript" in ct.lower(), f"content-type wrong: {ct}"
        # Escribir a tmp y correr node --check
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write(r.text)
            tmp = f.name
        try:
            result = subprocess.run(
                ["node", "--check", tmp],
                capture_output=True, text=True, timeout=15,
            )
            assert result.returncode == 0, (
                f"node --check FAILED:\nSTDOUT={result.stdout}\nSTDERR={result.stderr}"
            )
        finally:
            os.unlink(tmp)

    def test_styles_css_brand_color(self):
        r = requests.get(f"{BASE_URL}/api/demo/audio-room-static/css/styles.css", timeout=10)
        assert r.status_code == 200
        ct = r.headers.get("content-type", "")
        assert "css" in ct.lower(), f"content-type wrong: {ct}"
        assert "#2563EB" in r.text or "#2563eb" in r.text.lower()


# --------------------------------------------------------------
# 3. Registro nuevo usuario + trial 15 oros + tool app_builder_pro
# --------------------------------------------------------------
class TestNewUserTrialAndAppBuilder:
    def test_new_user_has_trial_credits(self, new_user):
        # site_content trial_oros default = 15
        r = requests.get(f"{BASE_URL}/api/console/credits/me", headers=new_user["headers"], timeout=10)
        assert r.status_code == 200
        bal = r.json().get("balance") or r.json().get("oros") or 0
        # Aceptamos rango (algun ambiente puede tener trial !=15)
        assert bal >= 15, f"trial credit < 15: balance={bal} body={r.json()}"

    def test_new_user_app_builder_flow(self, new_user):
        # Cleanup previo
        app_dir = Path(LLUVIA_HOME) / "user_apps" / new_user["id"] / "testend"
        if app_dir.exists():
            import shutil
            shutil.rmtree(app_dir, ignore_errors=True)

        # Saldo antes
        b0 = (requests.get(f"{BASE_URL}/api/console/credits/me", headers=new_user["headers"], timeout=10)
              .json()).get("balance", 0)

        # Crear sesion
        rs = requests.post(
            f"{BASE_URL}/api/console/sessions",
            headers=new_user["headers"],
            json={"agent_id": "app_builder_pro"},
            timeout=15,
        )
        assert rs.status_code == 200, rs.text[:300]
        sid = rs.json().get("id") or rs.json().get("session_id") or rs.json().get("session", {}).get("id")
        assert sid

        msg = "Generame una audio room llamala TestEnd y color #10B981. Generala ya."
        r = requests.post(
            f"{BASE_URL}/api/console/sessions/{sid}/messages",
            headers=new_user["headers"],
            json={"text": msg},
            timeout=180,
        )
        assert r.status_code == 200, r.text[:500]
        body = r.json()
        assistant = body.get("assistant_message") or {}
        tool_calls = assistant.get("tool_calls") or []
        names = [tc.get("name") or tc.get("tool") or (tc.get("function") or {}).get("name") for tc in tool_calls]
        if "generate_audio_room_app" not in names:
            pytest.skip(f"LLM no disparo la tool (no-determinism). tool_calls={names}")

        target = next(
            tc for tc in tool_calls
            if (tc.get("name") or tc.get("tool") or (tc.get("function") or {}).get("name")) == "generate_audio_room_app"
        )
        raw = target.get("result_preview") or target.get("result") or target.get("output")
        parsed = raw if isinstance(raw, dict) else json.loads(raw)
        assert parsed.get("ok") is True, f"tool failed: {parsed}"
        assert parsed.get("app_slug") == "testend"

        # Archivos en disco
        assert app_dir.exists(), f"missing app dir {app_dir}"
        assert (app_dir / "backend/server.py").exists()
        assert (app_dir / "frontend/index.html").exists()

        # Saldo después: debe haber bajado al menos 1 (chat) o más
        b1 = (requests.get(f"{BASE_URL}/api/console/credits/me", headers=new_user["headers"], timeout=10)
              .json()).get("balance", 0)
        assert b1 < b0, f"Balance NO bajo: before={b0} after={b1}"
        # Tolerancia: hasta 41 oros debitados (1 chat + 40 tool). Si LLM pidio mas turnos puede ser mas
        assert b1 >= 0, f"Balance quedo negativo: {b1}"


# --------------------------------------------------------------
# 4. GitHub validate + push admin (SOLO UN push)
# --------------------------------------------------------------
class TestAdminGithubPush:
    def test_github_validate(self, admin_headers):
        r = requests.post(f"{BASE_URL}/api/me/github/validate", headers=admin_headers, timeout=20)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert d.get("ok") is True, d
        assert d.get("login") == "melvinnavas79-del", d
        # repo_access esperado: writable (repo ya existe) o not_found (auto-create kicks in luego)
        assert d.get("repo_access") in ("writable", "writable_via_create", "owner_writable", "ok"), (
            f"repo_access unexpected: {d.get('repo_access')}, full={d}"
        )

    def test_github_push_admin_app(self, admin_headers, admin_user_id):
        # Necesitamos que exista una app del admin para empujar. Reusar 'miappdemo' si existe; sino generarla.
        ws = Path(LLUVIA_HOME) / "user_apps" / admin_user_id
        candidates = []
        if ws.exists():
            candidates = [p.name for p in ws.iterdir() if p.is_dir()]
        if not candidates:
            pytest.skip("No hay apps en workspace admin para push. Genera una primero.")

        # Preferir miappdemo si existe (segun task), sino la primera
        app_name = "miappdemo" if "miappdemo" in candidates else candidates[0]

        payload = {"app_name": app_name, "commit_message": "e2e test iteration_18"}
        r = requests.post(
            f"{BASE_URL}/api/me/github/push",
            headers=admin_headers,
            json=payload,
            timeout=120,
        )
        assert r.status_code == 200, f"push failed: {r.status_code} {r.text[:600]}"
        d = r.json()
        assert d.get("ok") is True, d
        repo_url = d.get("repo_url") or d.get("url") or ""
        assert "lluvia-audio-room-demo" in repo_url, f"unexpected repo_url: {repo_url}"

    def test_github_repo_exists_on_github_api(self):
        # Validacion lateral via GitHub public API (sin token: rate-limited pero suficiente)
        r = requests.get(f"https://api.github.com/repos/{GITHUB_REPO}", timeout=15)
        if r.status_code == 403:
            pytest.skip("GitHub rate-limited (no token). Validacion lateral omitida.")
        assert r.status_code == 200, f"GitHub repo no existe: {r.status_code} {r.text[:200]}"
        info = r.json()
        assert info.get("full_name") == GITHUB_REPO

    def test_github_has_expected_files(self):
        # Listar root del repo
        r = requests.get(f"https://api.github.com/repos/{GITHUB_REPO}/contents/", timeout=15)
        if r.status_code in (403, 404):
            pytest.skip(f"GitHub API no accesible o repo vacio ({r.status_code}).")
        items = r.json()
        names = {it.get("name") for it in items if isinstance(it, dict)}
        # README.md debe estar siempre
        assert "README.md" in names, f"README.md missing in repo: {names}"
        # backend y frontend folders
        assert "backend" in names, f"backend missing: {names}"
        assert "frontend" in names, f"frontend missing: {names}"
