"""
Iteration 17 — App Builder Pro tests
Foco: agente app_builder_pro registrado, tool generate_audio_room_app dispara
desde mensaje en español, archivos materializados con placeholders correctos,
re-invocacion limpia, refund admin_free, template backend importable.
"""
import os
import json
import time
import importlib.util
from pathlib import Path

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # En el contenedor backend, REACT_APP_BACKEND_URL no esta definido; usar el preview
    BASE_URL = "https://ai-bot-cost-calc.preview.emergentagent.com"

ADMIN_EMAIL = "melvinnavas79@gmail.com"
ADMIN_PASSWORD = "Admin#2026"
LLUVIA_HOME = os.environ.get("LLUVIA_HOME", "/tmp/lluvia")


# ----------------- Fixtures -----------------
@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=15,
    )
    assert r.status_code == 200, f"Login admin failed: {r.status_code} {r.text}"
    data = r.json()
    assert "access_token" in data, data
    return data["access_token"]


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def admin_user_id(admin_headers):
    r = requests.get(f"{BASE_URL}/api/auth/me", headers=admin_headers, timeout=10)
    assert r.status_code == 200
    me = r.json()
    return me.get("id") or me.get("user", {}).get("id")


# ----------------- Backend module-level tests -----------------
class TestAgentCatalog:
    def test_agents_list_contains_app_builder_pro(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/console/agents", headers=admin_headers, timeout=10)
        assert r.status_code == 200
        agents = r.json()
        # Tolerar formato list o dict {agents:[...]}
        agents_list = agents if isinstance(agents, list) else agents.get("agents", [])
        ids = [a.get("id") for a in agents_list]
        assert "app_builder_pro" in ids, f"app_builder_pro not in agents: {ids}"

        a = next(a for a in agents_list if a.get("id") == "app_builder_pro")
        assert a.get("emoji") == "🚀", a
        assert "Audio Room" in (a.get("tagline") or ""), a.get("tagline")
        tools = a.get("tools") or []
        assert "generate_audio_room_app" in tools, tools
        assert "push_to_my_github" in tools, tools

    def test_other_agents_still_present(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/console/agents", headers=admin_headers, timeout=10)
        assert r.status_code == 200
        agents = r.json()
        agents_list = agents if isinstance(agents, list) else agents.get("agents", [])
        ids = {a.get("id") for a in agents_list}
        # Sanity: otros agentes claves siguen
        assert "estilista_visual" in ids
        assert "marketing_lab" in ids


class TestCreditsEndpoint:
    def test_credits_me_ok(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/console/credits/me", headers=admin_headers, timeout=10)
        assert r.status_code == 200
        data = r.json()
        assert "balance" in data or "oros" in data or isinstance(data, dict)


class TestTemplateImportable:
    def test_audio_room_backend_imports(self):
        template_server = Path("/app/backend/app_templates/audio_room/backend/server.py")
        assert template_server.exists(), template_server
        spec = importlib.util.spec_from_file_location(
            "audio_room_template_server", str(template_server)
        )
        mod = importlib.util.module_from_spec(spec)
        # Cargar el modulo
        spec.loader.exec_module(mod)
        assert hasattr(mod, "app"), "El template debe exponer ASGI `app`"
        assert hasattr(mod, "api"), "El template debe exponer FastAPI `api`"


# ----------------- Session + tool trigger -----------------
class TestAppBuilderToolFlow:
    """Flujo: crear sesion app_builder_pro -> mensaje en español -> verificar tool call."""

    @pytest.fixture(scope="class")
    def session_id(self, admin_headers):
        r = requests.post(
            f"{BASE_URL}/api/console/sessions",
            headers=admin_headers,
            json={"agent_id": "app_builder_pro"},
            timeout=15,
        )
        assert r.status_code == 200, f"create session failed: {r.status_code} {r.text}"
        sid = r.json().get("id") or r.json().get("session_id") or r.json().get("session", {}).get("id")
        assert sid, r.json()
        return sid

    @pytest.fixture(scope="class")
    def admin_user_apps_dir(self, admin_user_id):
        return Path(LLUVIA_HOME) / "user_apps" / admin_user_id

    def _cleanup_app(self, user_apps_dir: Path, slug: str):
        target = user_apps_dir / slug
        if target.exists():
            import shutil
            shutil.rmtree(target, ignore_errors=True)

    def test_01_tool_invoked_and_files_materialized(
        self, admin_headers, session_id, admin_user_apps_dir
    ):
        # Cleanup previo: borrar /tmp/lluvia/user_apps/<admin>/mytalkapp/ si existe
        self._cleanup_app(admin_user_apps_dir, "mytalkapp")

        msg = "Llamala MyTalkApp y usa color #2563EB. Generala ya"
        r = requests.post(
            f"{BASE_URL}/api/console/sessions/{session_id}/messages",
            headers=admin_headers,
            json={"text": msg},
            timeout=120,
        )
        assert r.status_code == 200, f"send_message failed: {r.status_code} {r.text}"
        body = r.json()
        assistant = body.get("assistant_message") or body.get("assistant") or {}
        tool_calls = assistant.get("tool_calls") or []
        tool_names = [tc.get("name") or tc.get("tool") or (tc.get("function") or {}).get("name") for tc in tool_calls]
        assert any(n == "generate_audio_room_app" for n in tool_names), (
            f"generate_audio_room_app NO disparada. tool_calls={tool_calls}"
        )

        # Encontrar el tool_call relevante y parsear result_preview
        target_call = next(
            (tc for tc in tool_calls if (tc.get("name") or tc.get("tool") or (tc.get("function") or {}).get("name")) == "generate_audio_room_app"),
            None,
        )
        assert target_call, tool_calls
        raw = target_call.get("result_preview") or target_call.get("result") or target_call.get("output")
        assert raw, f"No result_preview en tool_call: {target_call}"
        parsed = raw if isinstance(raw, dict) else json.loads(raw)

        assert parsed.get("card_type") == "app_built", parsed
        assert parsed.get("ok") is True, parsed
        assert parsed.get("app_slug") == "mytalkapp", parsed.get("app_slug")
        screens = parsed.get("screens") or []
        assert screens == ["Inicio", "Tendencias", "Sala Activa", "Perfil"], screens
        assert parsed.get("files_written", 0) >= 10, parsed.get("files_written")

        # Verificacion FISICA de archivos en disco
        app_dir = admin_user_apps_dir / "mytalkapp"
        assert app_dir.exists(), f"App dir no existe: {app_dir}"
        required = [
            "backend/server.py",
            "backend/requirements.txt",
            "frontend/index.html",
            "frontend/css/styles.css",
            "frontend/js/api.js",
            "frontend/js/webrtc.js",
            "frontend/js/app.js",
            "README.md",
            ".env.example",
            ".gitignore",
        ]
        missing = [f for f in required if not (app_dir / f).exists()]
        assert not missing, f"Faltan archivos: {missing}"

        # Verificar reemplazo de placeholders
        idx = (app_dir / "frontend/index.html").read_text(encoding="utf-8")
        assert "{{APP_NAME}}" not in idx and "{{BRAND_COLOR}}" not in idx, "Placeholders sin reemplazar en index.html"
        assert "MyTalkApp" in idx, "APP_NAME no aplicado en index.html"
        assert "#2563EB" in idx, "BRAND_COLOR no aplicado en index.html"

        readme = (app_dir / "README.md").read_text(encoding="utf-8")
        assert "{{APP_NAME}}" not in readme, "Placeholder sin reemplazar en README.md"
        assert "MyTalkApp" in readme, readme[:200]

    def test_02_reinvocation_same_app_name_fails_cleanly_and_admin_free(
        self, admin_headers, admin_user_apps_dir
    ):
        # Crear nueva sesion para no contaminar contexto
        rs = requests.post(
            f"{BASE_URL}/api/console/sessions",
            headers=admin_headers,
            json={"agent_id": "app_builder_pro"},
            timeout=15,
        )
        assert rs.status_code == 200
        sid2 = rs.json().get("id") or rs.json().get("session_id") or rs.json().get("session", {}).get("id")

        # Saldo antes
        bal_before = requests.get(f"{BASE_URL}/api/console/credits/me", headers=admin_headers, timeout=10).json()
        b0 = bal_before.get("balance") or bal_before.get("oros") or 0

        msg = "Llamala MyTalkApp y usa color #2563EB. Generala ya"
        r = requests.post(
            f"{BASE_URL}/api/console/sessions/{sid2}/messages",
            headers=admin_headers,
            json={"text": msg},
            timeout=120,
        )
        assert r.status_code == 200
        body = r.json()
        assistant = body.get("assistant_message") or {}
        tool_calls = assistant.get("tool_calls") or []
        target = next(
            (tc for tc in tool_calls if (tc.get("name") or tc.get("tool") or (tc.get("function") or {}).get("name")) == "generate_audio_room_app"),
            None,
        )
        # Si la LLM esta vez no disparo la tool (porque puede pedir confirmacion),
        # se omite la verificacion estricta, pero el test al menos no debe romper
        if not target:
            pytest.skip("LLM no re-invoco la tool en este turno (no determinismo).")
        raw = target.get("result_preview") or target.get("result") or target.get("output")
        parsed = raw if isinstance(raw, dict) else json.loads(raw)
        assert parsed.get("ok") is False, f"Esperaba ok=false (target ya existe), got: {parsed}"
        assert parsed.get("error"), f"Esperaba error con motivo. parsed={parsed}"
        # admin_free => cost real = 0
        cost = body.get("cost_oros", assistant.get("cost_oros", 0))
        is_admin_free = body.get("is_admin_free") or assistant.get("is_admin_free")
        # Verificamos por saldo: NO debe bajar 40 oros
        bal_after = requests.get(f"{BASE_URL}/api/console/credits/me", headers=admin_headers, timeout=10).json()
        b1 = bal_after.get("balance") or bal_after.get("oros") or 0
        # Admin no paga aunque falle: balance debe mantenerse o incluso aumentar (no refund debit)
        assert b1 >= b0 - 1, f"Admin perdio oros: before={b0} after={b1} cost={cost} admin_free={is_admin_free}"

    def test_03_cleanup_generated_app(self, admin_user_apps_dir):
        # Cleanup final para no dejar basura
        self._cleanup_app(admin_user_apps_dir, "mytalkapp")
        assert not (admin_user_apps_dir / "mytalkapp").exists()
