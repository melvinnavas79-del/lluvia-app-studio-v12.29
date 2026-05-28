"""
Iteration 23 — v12.26 fixes críticos.

Cubre:
- Tool generate_audio_room_app con distintos deploy_target (render/railway/vps/heroku/fly/docker/local + inválido).
- Materialización de los 6 archivos de deploy multi-provider con placeholders sustituidos.
- Endpoint /api/integrations/gmail/oauth/magic-link detecta el dominio del request.
- Endpoint /api/me/github/create-repo (validaciones, sin push real).
"""
import os
import sys
import json
import asyncio
import shutil
import re
from pathlib import Path

import pytest
import requests

sys.path.insert(0, "/app/backend")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://ai-bot-cost-calc.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "melvinnavas79@gmail.com"
ADMIN_PASSWORD = "Admin#2026"
ADMIN_USER_ID = "9d026605-d08f-49ba-a9dc-f4ad0e45d271"


# ============================================================
# Fixtures
# ============================================================
@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=15,
    )
    assert r.status_code == 200, f"Admin login failed: {r.status_code} {r.text}"
    token = r.json()["access_token"]
    assert token
    return token


@pytest.fixture
def cleanup_workspace():
    """Limpia los slugs de test después de cada test."""
    created = []
    yield created
    for slug in created:
        p = Path(f"/app/user_apps/{ADMIN_USER_ID}/{slug}")
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)


# ============================================================
# Helper para ejecutar la tool directamente
# ============================================================
async def _run_exec_tool(args: dict, slug_override: str | None = None):
    """Llama console._exec_tool('generate_audio_room_app', args) y devuelve (dict, cost)."""
    if slug_override:
        args = {**args, "app_slug": slug_override}
    import console
    res_str, cost = await console._exec_tool(
        "generate_audio_room_app", args, ADMIN_USER_ID, is_admin=True
    )
    return json.loads(res_str), cost


# ============================================================
# TestAudioRoomDeployTargets
# ============================================================
class TestAudioRoomDeployTargets:
    """Tool generate_audio_room_app con diferentes deploy_target."""

    def test_deploy_render(self, cleanup_workspace):
        slug = "testbeta-render"
        cleanup_workspace.append(slug)
        data, cost = asyncio.run(
            _run_exec_tool(
                {"app_name": "TestBeta", "brand_color": "#FF0000", "deploy_target": "render"},
                slug_override=slug,
            )
        )
        assert data["ok"] is True, f"Tool falló: {data.get('error')}"
        assert data["deploy_target"] == "render"
        assert data["files_written"] >= 16, f"files_written={data['files_written']}, esperado >=16"
        next_step = data["next_step"]
        assert "render.yaml" in next_step or "onrender.com" in next_step
        assert data["card_type"] == "app_built"

    def test_deploy_vps(self, cleanup_workspace):
        slug = "testbeta-vps"
        cleanup_workspace.append(slug)
        data, _ = asyncio.run(
            _run_exec_tool(
                {"app_name": "TestBeta", "brand_color": "#00FF00", "deploy_target": "vps"},
                slug_override=slug,
            )
        )
        assert data["ok"] is True
        assert data["deploy_target"] == "vps"
        next_step = data["next_step"]
        assert "install.sh" in next_step
        # systemd se infiere desde install.sh + el "systemd" mencionado en el README
        # El brief exige que mencione systemd o instalación VPS; aceptamos install.sh + systemd vinculado.
        # En el helper actual el next_step menciona "install.sh" e "instala Python + systemd + ...".
        assert "systemd" in next_step.lower()

    def test_deploy_railway(self, cleanup_workspace):
        slug = "testbeta-railway"
        cleanup_workspace.append(slug)
        data, _ = asyncio.run(
            _run_exec_tool(
                {"app_name": "TestBeta", "brand_color": "#0000FF", "deploy_target": "railway"},
                slug_override=slug,
            )
        )
        assert data["ok"] is True
        assert data["deploy_target"] == "railway"
        next_step = data["next_step"]
        assert "railway.toml" in next_step or "Railway" in next_step

    def test_deploy_invalid_falls_back_to_render(self, cleanup_workspace):
        slug = "testbeta-invalid"
        cleanup_workspace.append(slug)
        data, _ = asyncio.run(
            _run_exec_tool(
                {"app_name": "TestBeta", "brand_color": "#FFFFFF", "deploy_target": "amazonia"},
                slug_override=slug,
            )
        )
        assert data["ok"] is True
        assert data["deploy_target"] == "render", "deploy_target inválido debería caer a render"

    def test_deploy_empty_falls_back_to_render(self, cleanup_workspace):
        slug = "testbeta-empty"
        cleanup_workspace.append(slug)
        data, _ = asyncio.run(
            _run_exec_tool(
                {"app_name": "TestBeta", "brand_color": "#5B8DEF", "deploy_target": ""},
                slug_override=slug,
            )
        )
        assert data["ok"] is True
        assert data["deploy_target"] == "render"


# ============================================================
# TestFilesMaterialized - validar archivos físicos + placeholders
# ============================================================
class TestFilesMaterialized:
    """Verifica archivos físicos en /app/user_apps/{user_id}/{slug}/."""

    def test_all_deploy_files_present_and_placeholders_replaced(self, cleanup_workspace):
        slug = "ai-bot-cost-calc"
        cleanup_workspace.append(slug)
        data, _ = asyncio.run(
            _run_exec_tool(
                {"app_name": "AI Bot Cost Calc", "brand_color": "#FF0000", "deploy_target": "render"},
                slug_override=slug,
            )
        )
        assert data["ok"] is True, f"Materialización falló: {data.get('error')}"

        root = Path(f"/app/user_apps/{ADMIN_USER_ID}/{slug}")
        assert root.exists()

        # Los 6 archivos de deploy
        required = ["render.yaml", "railway.toml", "Procfile", "Dockerfile", "docker-compose.yml", "install.sh"]
        for f in required:
            assert (root / f).exists(), f"Falta archivo {f}"

        # Validaciones específicas de cada archivo
        render_yaml = (root / "render.yaml").read_text()
        assert "name: ai-bot-cost-calc" in render_yaml, f"render.yaml no tiene name correcto:\n{render_yaml}"
        assert "rootDir: backend" in render_yaml, "render.yaml debe tener rootDir: backend"

        railway_toml = (root / "railway.toml").read_text()
        # Algún lugar debe contener el slug sustituido
        assert "ai-bot-cost-calc" in railway_toml, f"railway.toml no sustituyó slug:\n{railway_toml}"

        docker_compose = (root / "docker-compose.yml").read_text()
        assert "image: ai-bot-cost-calc:latest" in docker_compose, (
            f"docker-compose.yml no tiene image correcta:\n{docker_compose}"
        )

        install_sh = (root / "install.sh").read_text()
        assert "/opt/ai-bot-cost-calc" in install_sh, "install.sh debe referenciar /opt/ai-bot-cost-calc"
        assert "ai-bot-cost-calc.service" in install_sh, "install.sh debe definir ai-bot-cost-calc.service"

        # ZERO ocurrencias de placeholders en cualquier archivo de texto
        leftover = []
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix in {".db", ".png", ".jpg", ".ico", ".woff2", ".pyc"}:
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if "{{APP_NAME_SLUG}}" in content or "{{APP_NAME}}" in content or "{{BRAND_COLOR}}" in content:
                leftover.append(str(path.relative_to(root)))
        assert leftover == [], f"Placeholders sin sustituir en: {leftover}"


# ============================================================
# TestGmailMagicLink - detección de dominio
# ============================================================
class TestGmailMagicLink:
    def test_magic_link_with_lluvia_live_host(self, admin_token):
        """El ingress preview override x-forwarded-host, así que testeamos la
        lógica directamente via call al function con un fake Request."""
        import gmail_integration
        from unittest.mock import MagicMock

        # Mock Request con host = lluvia-live.com
        fake_req = MagicMock()
        fake_req.headers = {
            "authorization": f"Bearer {admin_token}",
            "host": "lluvia-app-studio.lluvia-live.com",
            "x-forwarded-host": "lluvia-app-studio.lluvia-live.com",
        }
        fake_req.base_url = "https://lluvia-app-studio.lluvia-live.com/"
        fake_user = {"id": ADMIN_USER_ID, "email": ADMIN_EMAIL, "role": "admin"}

        result = asyncio.run(gmail_integration.magic_link(fake_req, user=fake_user))
        assert result["url"].startswith(
            "https://lluvia-app-studio.lluvia-live.com/api/integrations/gmail/oauth/start?token="
        ), f"URL inesperada: {result['url']}"
        assert result["expires_in_minutes"] == 60

    def test_magic_link_with_emergent_preview_host(self, admin_token):
        r = requests.get(
            f"{BASE_URL}/api/integrations/gmail/oauth/magic-link",
            headers={
                "Authorization": f"Bearer {admin_token}",
                "x-forwarded-host": "ai-bot-cost-calc.preview.emergentagent.com",
            },
            timeout=15,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["url"].startswith(
            "https://ai-bot-cost-calc.preview.emergentagent.com/api/integrations/gmail/oauth/start?token="
        ), f"URL inesperada: {data['url']}"

    def test_magic_link_no_match_falls_back_to_env(self, admin_token):
        """Sin host conocido: cae al PUBLIC_BASE_URL o al request.base_url."""
        r = requests.get(
            f"{BASE_URL}/api/integrations/gmail/oauth/magic-link",
            headers={
                "Authorization": f"Bearer {admin_token}",
                # Cliente normal — el ingress sigue mandando el host real, pero validamos
                # que el link contenga /api/integrations/gmail/oauth/start con token.
            },
            timeout=15,
        )
        assert r.status_code == 200
        data = r.json()
        assert "/api/integrations/gmail/oauth/start?token=" in data["url"]
        assert data["expires_in_minutes"] == 60

    def test_magic_link_logic_unknown_host_uses_env_or_base_url(self, admin_token):
        """Unit test: host desconocido → cae a PUBLIC_BASE_URL o request.base_url."""
        import gmail_integration
        from unittest.mock import MagicMock

        fake_req = MagicMock()
        fake_req.headers = {
            "authorization": f"Bearer {admin_token}",
            "host": "completely-unknown-domain.example.com",
            "x-forwarded-host": "completely-unknown-domain.example.com",
        }
        fake_req.base_url = "http://completely-unknown-domain.example.com/"
        fake_user = {"id": ADMIN_USER_ID, "email": ADMIN_EMAIL, "role": "admin"}

        result = asyncio.run(gmail_integration.magic_link(fake_req, user=fake_user))
        # Debe usar PUBLIC_BASE_URL del .env (no la URL del host desconocido)
        public_base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
        if public_base:
            assert result["url"].startswith(public_base + "/api/integrations/gmail/oauth/start"), (
                f"URL no usó PUBLIC_BASE_URL: {result['url']}"
            )
        else:
            assert "/api/integrations/gmail/oauth/start?token=" in result["url"]


# ============================================================
# TestCreateRepoEndpoint - regresion v12.25
# ============================================================
class TestCreateRepoEndpoint:
    """Solo validaciones - sin push real a GitHub."""

    def test_create_repo_no_token_returns_400(self, admin_token):
        """Si el admin no tiene PAT configurado (o es inválido), debe responder claro."""
        r = requests.post(
            f"{BASE_URL}/api/me/github/create-repo",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"name": "TEST_should_not_create", "private": False, "set_as_default": False},
            timeout=20,
        )
        # Debe ser 400 (no token) o 401 (token inválido) — no 500
        assert r.status_code in (400, 401, 403), (
            f"Esperado 400/401/403, llegó {r.status_code}: {r.text}"
        )
        body = r.json()
        assert "detail" in body, f"No hay detail en respuesta: {body}"

    def test_create_repo_invalid_name_returns_400(self, admin_token):
        """Nombre vacío/inválido → 400 con mensaje útil (si el token existe)
        o 400/401 por token. En ambos casos NO debe ser 500."""
        r = requests.post(
            f"{BASE_URL}/api/me/github/create-repo",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"name": "!!", "private": False, "set_as_default": False},
            timeout=20,
        )
        assert r.status_code in (400, 401, 403), (
            f"Esperado 400/401/403, llegó {r.status_code}: {r.text}"
        )

    def test_create_repo_no_auth_returns_401(self):
        r = requests.post(
            f"{BASE_URL}/api/me/github/create-repo",
            json={"name": "TEST_repo", "private": False, "set_as_default": False},
            timeout=15,
        )
        assert r.status_code in (401, 403), f"Esperado 401/403, llegó {r.status_code}"
