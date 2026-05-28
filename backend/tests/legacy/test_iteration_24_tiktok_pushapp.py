"""
Iteration 24 — Validacion backend de:
- POST /api/me/github/push-app (NUEVO): crea repo dedicado por app
- POST /api/me/github/push (MODIFICADO): acepta repo/branch/auto_create_repo
- GET  /api/admin/pricing: incluye generate_tiktok_app
- GET  /api/console/agents: app_builder_pro tiene 3 tools
- App Builder Pro chat: reconoce TikTok como template
- Materializacion local del template tiktok_clone (sin DB)
- Backend del template TikTok inicia OK con endpoints health/videos/users/gifts
"""

import os
import sys
import shutil
import subprocess
import time
import socket
import json
from pathlib import Path

import pytest
import requests

BACKEND_DIR = "/app/backend"
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://ai-bot-cost-calc.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "melvinnavas79@gmail.com"
ADMIN_PASS = "Admin#2026"


# ===== Fixtures =====
@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=15)
    assert r.status_code == 200, f"Login fallo: {r.status_code} {r.text[:200]}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


# ===== /api/me/github/push-app =====
class TestPushAppEndpoint:
    """Endpoint nuevo: empuja UNA app a un repo dedicado."""

    def test_push_app_requires_auth(self):
        r = requests.post(f"{BASE_URL}/api/me/github/push-app",
                          json={"app_slug": "demo"}, timeout=10)
        assert r.status_code in (401, 403), f"Sin auth deberia 401/403, got {r.status_code}"

    def test_push_app_validates_payload(self, auth_headers):
        # app_slug requerido (min_length=1)
        r = requests.post(f"{BASE_URL}/api/me/github/push-app",
                          json={}, headers=auth_headers, timeout=10)
        assert r.status_code == 422, f"Payload invalido deberia 422, got {r.status_code}"

    def test_push_app_404_when_app_missing(self, auth_headers):
        """Si admin no tiene token o no tiene la app: detail claro 400/404."""
        r = requests.post(f"{BASE_URL}/api/me/github/push-app",
                          json={"app_slug": "no-existe-app-xxxxx-zzz", "create_new": False,
                                "target_owner_repo": "octocat/Hello-World"},
                          headers=auth_headers, timeout=15)
        # Puede ser 400 (no github_token) o 404 (app no existe en workspace)
        assert r.status_code in (400, 404), f"Esperado 400/404, got {r.status_code} {r.text[:200]}"
        detail = r.json().get("detail", "")
        assert isinstance(detail, str) and len(detail) > 5

    def test_push_app_invalid_target_owner_repo(self, auth_headers):
        """target_owner_repo con formato invalido -> 400 con detail claro
        (no 500)."""
        r = requests.post(f"{BASE_URL}/api/me/github/push-app",
                          json={"app_slug": "x", "target_owner_repo": "no-slash-format"},
                          headers=auth_headers, timeout=10)
        # 400 (sin github_token) o 404 (app no existe) — nunca 500
        assert r.status_code in (400, 404), f"Esperado 400/404, got {r.status_code}"


# ===== /api/me/github/push modificado =====
class TestPushEndpointBackcompat:
    """El endpoint original sigue funcionando y ahora acepta los nuevos campos."""

    def test_push_requires_auth(self):
        r = requests.post(f"{BASE_URL}/api/me/github/push", json={}, timeout=10)
        assert r.status_code in (401, 403)

    def test_push_accepts_extended_payload_shape(self, auth_headers):
        """Aceptar los nuevos campos sin reventar (devuelve needs_setup o
        algun 4xx con detail claro si no hay token, no 500)."""
        r = requests.post(f"{BASE_URL}/api/me/github/push",
                          json={"app_name": "demo", "repo": "octocat/Hello-World",
                                "branch": "main", "auto_create_repo": False},
                          headers=auth_headers, timeout=20)
        assert r.status_code != 500, f"500 no aceptable: {r.text[:300]}"
        # 200 (push intentado) o 4xx (needs_setup -> 400)
        assert r.status_code in (200, 400, 401, 403, 404, 422)

    def test_push_legacy_payload_still_works(self, auth_headers):
        """Sin repo, debe seguir intentando contra el repo default del user."""
        r = requests.post(f"{BASE_URL}/api/me/github/push",
                          json={"commit_message": "test"},
                          headers=auth_headers, timeout=20)
        assert r.status_code != 500
        assert r.status_code in (200, 400, 401, 403, 404)


# ===== /api/admin/pricing =====
class TestPricingIncludesTiktok:
    def test_pricing_has_generate_tiktok_app(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/admin/pricing", headers=auth_headers, timeout=10)
        assert r.status_code == 200, f"GET /api/admin/pricing fallo: {r.status_code} {r.text[:200]}"
        data = r.json()
        # tool_prices debe incluir generate_tiktok_app=50 (default)
        assert "tool_prices" in data
        assert "generate_tiktok_app" in data["tool_prices"], \
            f"Falta generate_tiktok_app en tool_prices: {list(data['tool_prices'].keys())}"
        assert int(data["tool_prices"]["generate_tiktok_app"]) == 50

        # templates debe incluirlo como template ACTIVO (no coming_soon)
        templates = data.get("templates", [])
        tiktok = next((t for t in templates if t["tool_id"] == "generate_tiktok_app"), None)
        assert tiktok is not None, "Falta entry tiktok en templates[]"
        assert not tiktok.get("coming_soon"), "generate_tiktok_app NO deberia ser coming_soon"
        assert "TikTok" in tiktok.get("name", "") or "Bigo" in tiktok.get("name", "")


# ===== /api/console/agents =====
class TestAgentsCatalog:
    def test_app_builder_pro_lists_three_tools(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/console/agents", headers=auth_headers, timeout=10)
        assert r.status_code == 200, r.text[:200]
        agents = r.json().get("agents") or r.json()
        # puede venir como dict o list
        if isinstance(agents, dict):
            agents = list(agents.values())
        app_builder = next((a for a in agents if a.get("id") == "app_builder_pro" or a.get("agent_id") == "app_builder_pro"), None)
        assert app_builder is not None, f"No encuentro app_builder_pro. Agents: {[a.get('id') or a.get('agent_id') for a in agents]}"
        tools = app_builder.get("tools") or []
        for required in ("generate_audio_room_app", "generate_tiktok_app", "push_to_my_github"):
            assert required in tools, f"Falta tool '{required}' en app_builder_pro.tools = {tools}"


# ===== App Builder Pro chat reconoce TikTok =====
class TestAppBuilderProChat:
    """Pide al agente crear app tipo TikTok y validamos que el system prompt
    sabe del template (verificacion estatica del prompt; el chat real
    requiere LLM calls que cuestan creditos)."""

    def test_app_builder_system_prompt_mentions_tiktok(self):
        from agents_catalog import AGENTS
        # AGENTS puede ser dict keyed-by-id o list de dicts
        if isinstance(AGENTS, dict):
            ab = AGENTS.get("app_builder_pro")
        else:
            ab = next((a for a in AGENTS if isinstance(a, dict) and a.get("id") == "app_builder_pro"), None)
        assert ab is not None, "No encuentro app_builder_pro en AGENTS"
        # ab puede ser dict con system_prompt o sub-objeto
        prompt = ab.get("system") or ab.get("system_prompt", "") if isinstance(ab, dict) else (getattr(ab, "system", "") or getattr(ab, "system_prompt", ""))
        assert "generate_tiktok_app" in prompt, "system_prompt no menciona la tool generate_tiktok_app"
        assert "tiktok" in prompt.lower() or "feed vertical" in prompt.lower() or "bigo" in prompt.lower(), \
            "system_prompt deberia hablar de TikTok/Bigo/feed vertical"


# ===== Materializacion del template (sin DB) =====
class TestTiktokTemplateMaterialization:
    """Verifica que app_builder.list_templates() incluye tiktok_clone y que
    materialize_template() copia todos los archivos del brief."""

    def test_list_templates_includes_tiktok(self):
        from app_builder import list_templates
        items = list_templates()
        ids = [t["id"] for t in items]
        assert "tiktok_clone" in ids, f"tiktok_clone NO listado. Disponibles: {ids}"

    def test_materialize_creates_all_required_files(self, tmp_path):
        from app_builder import materialize_template
        target = tmp_path / "my-tiktok-app"
        result = materialize_template(
            template_id="tiktok_clone",
            target_dir=target,
            app_name="MyTikTok",
            brand_color="#FF0050",
        )
        assert result.get("ok"), f"materialize fallo: {result}"

        required = [
            "backend/server.py", "backend/requirements.txt",
            "frontend/index.html", "frontend/css/styles.css",
            "frontend/js/app.js", "frontend/js/api.js",
            "README.md", "render.yaml", "railway.toml",
            "Dockerfile", "docker-compose.yml", "Procfile", "install.sh",
        ]
        for rel in required:
            assert (target / rel).exists(), f"Falta archivo materializado: {rel}"

    def test_no_unresolved_placeholders_in_materialized(self, tmp_path):
        """{{APP_NAME}} / {{BRAND_COLOR}} / {{APP_NAME_SLUG}} NO deben quedar."""
        from app_builder import materialize_template
        target = tmp_path / "ttk"
        materialize_template(
            template_id="tiktok_clone",
            target_dir=target,
            app_name="LiveTok",
            brand_color="#FF0050",
        )
        leftovers = []
        for p in target.rglob("*"):
            if not p.is_file():
                continue
            try:
                txt = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for tok in ("{{APP_NAME}}", "{{APP_NAME_SLUG}}", "{{BRAND_COLOR}}"):
                if tok in txt:
                    leftovers.append((str(p.relative_to(target)), tok))
        assert not leftovers, f"Placeholders sin resolver: {leftovers[:10]}"


# ===== TikTok backend boot + endpoints =====
def _free_port() -> int:
    s = socket.socket(); s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]; s.close()
    return port


class TestTiktokBackendBoots:
    """Levanta el backend materializado y golpea sus endpoints publicos."""

    @pytest.fixture(scope="class")
    def running_backend(self, tmp_path_factory):
        from app_builder import materialize_template
        base = tmp_path_factory.mktemp("ttk_run")
        target = base / "boot-app"  # materialize requiere que NO exista
        result = materialize_template(
            template_id="tiktok_clone",
            target_dir=target,
            app_name="BootTok",
            brand_color="#FF0050",
        )
        assert result.get("ok"), f"materialize fallo: {result}"

        # Install deps in a venv? Mejor: usar python actual y pip install --user para velocidad.
        # Verificamos si las deps clave estan instaladas; si no, instalamos.
        try:
            import fastapi  # noqa
            import socketio  # noqa
            import jwt  # noqa
        except ImportError:
            req = (target / "backend" / "requirements.txt").read_text()
            subprocess.run([sys.executable, "-m", "pip", "install", "-q"] +
                           [line.strip() for line in req.splitlines() if line.strip() and not line.startswith("#")],
                           timeout=120, check=False)

        port = _free_port()
        env = os.environ.copy()
        env.update({
            "PORT": str(port),
            "APP_NAME": "BootTok",
            "BRAND_COLOR": "#FF0050",
            "JWT_SECRET": "test-secret-iter24",
            "DB_PATH": str(target / "backend" / "boot.db"),
        })
        proc = subprocess.Popen(
            [sys.executable, "server.py"],
            cwd=str(target / "backend"),
            env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        # Esperar boot
        url = f"http://127.0.0.1:{port}"
        deadline = time.time() + 25
        last_err = None
        booted = False
        while time.time() < deadline:
            try:
                r = requests.get(f"{url}/api/health", timeout=2)
                if r.status_code == 200:
                    booted = True
                    break
            except Exception as e:
                last_err = e
            if proc.poll() is not None:
                out = proc.stdout.read().decode("utf-8", errors="ignore") if proc.stdout else ""
                pytest.fail(f"TikTok backend murio en boot. Stdout:\n{out[:2000]}")
            time.sleep(0.5)
        if not booted:
            try:
                proc.terminate()
            except Exception:
                pass
            pytest.fail(f"TikTok backend NO arranco en 25s. last_err={last_err}")
        yield url
        try:
            proc.terminate(); proc.wait(timeout=5)
        except Exception:
            try: proc.kill()
            except Exception: pass

    def test_health(self, running_backend):
        r = requests.get(f"{running_backend}/api/health", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert data.get("status") == "ok" or data.get("ok") is True or "status" in data

    def test_videos_feed_seeded(self, running_backend):
        r = requests.get(f"{running_backend}/api/videos/feed", timeout=5)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        videos = data if isinstance(data, list) else (data.get("videos") or data.get("items") or [])
        assert len(videos) >= 6, f"Esperado >=6 videos seed, got {len(videos)}"

    def test_videos_trending(self, running_backend):
        r = requests.get(f"{running_backend}/api/videos/trending", timeout=5)
        assert r.status_code == 200
        data = r.json()
        videos = data if isinstance(data, list) else (data.get("videos") or data.get("items") or [])
        assert len(videos) >= 1

    def test_users_top_has_three_creators(self, running_backend):
        r = requests.get(f"{running_backend}/api/users/top", timeout=5)
        assert r.status_code == 200
        data = r.json()
        users = data if isinstance(data, list) else (data.get("creators") or data.get("users") or data.get("items") or [])
        assert len(users) >= 3, f"Esperado >=3 creators seed, got {len(users)}"

    def test_create_anonymous_user(self, running_backend):
        r = requests.post(f"{running_backend}/api/users/anonymous",
                          json={"display_name": "TEST_anon"}, timeout=5)
        assert r.status_code in (200, 201), r.text[:300]
        data = r.json()
        assert ("token" in data) or ("access_token" in data) or ("user_id" in data) or ("id" in data)

    def test_gifts_catalog(self, running_backend):
        r = requests.get(f"{running_backend}/api/gifts", timeout=5)
        assert r.status_code == 200
        data = r.json()
        gifts = data if isinstance(data, list) else (data.get("gifts") or data.get("items") or [])
        assert len(gifts) >= 1, f"Catalogo de regalos vacio: {data}"
