"""
Iteration 22 — Hotfix v12.24: GitHub push via REST API (httpx) instead of
subprocess.run('git'). The production container does NOT ship the `git`
binary. This suite validates:

  * ZERO references to subprocess / 'git' binary in user_workspace.py
  * do_push handles 3 init scenarios:
      (a) repo with existing commits (ref 200)
      (b) brand-new branch on existing repo (ref 404)
      (c) totally empty repo (ref 409) -> bootstrap via /contents/README.md
  * Correct skip patterns (.git, __pycache__, node_modules, .pyc, large files)
  * Invalid PAT formats rejected before touching GitHub
  * Bad credentials surface as ok=False / auth_failed=True (no Errno 2 crash)
  * iteration_20 regression: export_locked evaluated BEFORE push REST path

All GitHub HTTP calls are mocked with httpx.MockTransport / AsyncMock so we
don't burn the admin's PAT rate limit.
"""
import os
import re
import sys
import asyncio
import tempfile
import importlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx

# Ensure /app/backend is on sys.path
BACKEND_DIR = Path("/app/backend")
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import user_workspace  # noqa: E402


# =============================================================
# Static / source-level checks (Fix #1 of the incident)
# =============================================================
class TestSourceLevelHotfix:
    """v12.24 hotfix: ensure NO subprocess + NO 'git' binary references."""

    SRC = (BACKEND_DIR / "user_workspace.py").read_text()

    def test_no_subprocess_import(self):
        # Must not import subprocess at all
        assert not re.search(r"^\s*import\s+subprocess", self.SRC, re.MULTILINE), \
            "user_workspace.py must NOT import subprocess (prod container has no git)"
        assert not re.search(r"^\s*from\s+subprocess\s+import", self.SRC, re.MULTILINE)

    def test_no_subprocess_calls(self):
        assert "subprocess." not in self.SRC, "No subprocess.* calls allowed"
        assert "subprocess.run" not in self.SRC

    def test_no_git_binary_string(self):
        # Look for ['git', ...] or "git " executable invocations.
        # We allow occurrences inside literals like 'github', 'git_', '/git/' (REST endpoints).
        # The dangerous pattern is the bare token 'git' (or "git") as a list element / argv.
        bad_patterns = [
            r"\[\s*['\"]git['\"]\s*,",      # ["git", ...]
            r"['\"]git\s+(push|add|commit|init|clone|remote|config|fetch|pull)['\"]",
        ]
        for pat in bad_patterns:
            m = re.search(pat, self.SRC)
            assert m is None, f"Forbidden git-binary pattern found: {pat} -> {m}"


# =============================================================
# _validate_github_token format checks
# =============================================================
class TestTokenFormatValidation:
    """Pre-flight format check before hitting GitHub."""

    @pytest.mark.asyncio
    async def test_invalid_format_rejected_before_network(self):
        # 'invalid-format' must be rejected by the format check, no httpx call
        with patch("user_workspace.httpx.AsyncClient") as mock_cli:
            res = await user_workspace._validate_github_token("invalid-format-token-xxxxxx")
            assert res["ok"] is False
            assert "formato" in res["error"].lower() or "format" in res["error"].lower()
            # No HTTP call should have been issued
            mock_cli.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_token_rejected(self):
        res = await user_workspace._validate_github_token("")
        assert res["ok"] is False
        assert "vac" in res["error"].lower() or "invalid" in res["error"].lower()

    @pytest.mark.asyncio
    async def test_too_short_token_rejected(self):
        res = await user_workspace._validate_github_token("ghp_x")
        assert res["ok"] is False

    @pytest.mark.asyncio
    async def test_fine_grained_format_passes_check(self):
        """github_pat_xxx should pass the format check (but may 401 on real API)."""
        async def handler(request):
            # GitHub returns 401 for our fake token
            return httpx.Response(401, json={"message": "Bad credentials"})

        transport = httpx.MockTransport(handler)

        # Patch AsyncClient to use the mock transport
        real_async_client = httpx.AsyncClient

        def fake_ctor(*args, **kwargs):
            kwargs["transport"] = transport
            return real_async_client(*args, **kwargs)

        with patch("user_workspace.httpx.AsyncClient", side_effect=fake_ctor):
            res = await user_workspace._validate_github_token(
                "github_pat_11ABCDE_fake_token_value_for_testing_only_xxxxxxx"
            )
            # Format passes, but 401 should surface as Bad credentials
            assert res["ok"] is False
            assert "bad credentials" in res["error"].lower() or "401" in res["error"]

    @pytest.mark.asyncio
    async def test_classic_format_with_bad_credentials(self):
        async def handler(request):
            return httpx.Response(401, json={"message": "Bad credentials"})

        transport = httpx.MockTransport(handler)
        real = httpx.AsyncClient
        with patch("user_workspace.httpx.AsyncClient",
                   side_effect=lambda *a, **kw: real(*a, transport=transport, **{k: v for k, v in kw.items() if k != "transport"})):
            res = await user_workspace._validate_github_token("ghp_BAD" + "x" * 30)
            assert res["ok"] is False
            assert "bad credentials" in res["error"].lower()


# =============================================================
# do_push — scenario tests (mocked GitHub)
# =============================================================
@pytest.fixture
def fake_workspace(tmp_path, monkeypatch):
    """Create a fake user workspace with realistic file mix incl. skip cases."""
    user_id = "test-user-iter22"
    base = tmp_path / "user_apps" / user_id
    base.mkdir(parents=True)
    (base / "index.html").write_text("<html>hello</html>")
    (base / "app.py").write_text("print('hi')\n")
    # Skipped dirs
    (base / ".git").mkdir()
    (base / ".git" / "HEAD").write_text("ref: refs/heads/main")
    (base / "node_modules").mkdir()
    (base / "node_modules" / "junk.js").write_text("x" * 100)
    (base / "__pycache__").mkdir()
    (base / "__pycache__" / "x.cpython.pyc").write_text("bytecode")
    # Skipped extensions at top level
    (base / "debug.log").write_text("log content")
    (base / "data.pyc").write_text("bytecode")
    # Large file (>1.5MB) -> skip_large
    (base / "huge.bin").write_bytes(b"\x00" * 1_600_000)
    # Nested valid file
    (base / "sub").mkdir()
    (base / "sub" / "page.js").write_text("console.log(1)")

    monkeypatch.setenv("LLUVIA_HOME", str(tmp_path))
    return user_id, base


@pytest.fixture
def fake_db():
    """Mock async Mongo db that returns valid settings + admin balance."""
    db = MagicMock()

    async def find_one_user_settings(*a, **kw):
        return {
            "user_id": "test-user-iter22",
            "github_token": "ghp_" + "a" * 36,
            "github_repo": "melvinnavas79-del/lluvia-empty-test",
            "github_branch": "main",
        }

    db.user_settings.find_one = AsyncMock(side_effect=find_one_user_settings)
    db.credits.find_one = AsyncMock(return_value={"balance": 9999})
    db.user_github_pushes.insert_one = AsyncMock(return_value=None)
    return db


def _make_mock_transport(scenario: str, capture: dict):
    """Build an httpx MockTransport that responds based on scenario.

    scenario: 'existing' | 'new_branch' | 'empty_repo' | 'bad_token'
    capture: dict to record requests for assertions.
    """
    capture.setdefault("requests", [])

    def handler(request: httpx.Request) -> httpx.Response:
        capture["requests"].append((request.method, str(request.url)))
        url = str(request.url)

        # /user (token validation)
        if url.endswith("/user"):
            if scenario == "bad_token":
                return httpx.Response(401, json={"message": "Bad credentials"})
            return httpx.Response(
                200,
                headers={"X-OAuth-Scopes": "repo, user"},
                json={"login": "melvinnavas79-del"},
            )
        # /repos/{repo} (validation)
        if re.search(r"/repos/[^/]+/[^/]+$", url):
            return httpx.Response(
                200,
                json={"permissions": {"push": True, "admin": True}},
            )
        # /git/refs/heads/{branch}
        if "/git/refs/heads/" in url and request.method == "GET":
            if scenario == "existing":
                return httpx.Response(
                    200, json={"object": {"sha": "a" * 40, "type": "commit"}}
                )
            if scenario == "new_branch":
                return httpx.Response(404, json={"message": "Not Found"})
            if scenario == "empty_repo":
                return httpx.Response(
                    409, json={"message": "Git Repository is empty."}
                )

        # /git/commits/{sha}  (only hit in existing scenario)
        if re.search(r"/git/commits/[a-f0-9]{40}$", url) and request.method == "GET":
            return httpx.Response(200, json={"tree": {"sha": "b" * 40}})

        # PUT /contents/README.md  (empty-repo bootstrap)
        if "/contents/README.md" in url and request.method == "PUT":
            return httpx.Response(
                201,
                json={
                    "commit": {"sha": "c" * 40, "tree": {"sha": "d" * 40}},
                },
            )

        # POST /git/blobs
        if url.endswith("/git/blobs") and request.method == "POST":
            return httpx.Response(201, json={"sha": "e" * 40})

        # POST /git/trees
        if url.endswith("/git/trees") and request.method == "POST":
            return httpx.Response(201, json={"sha": "f" * 40})

        # POST /git/commits
        if url.endswith("/git/commits") and request.method == "POST":
            return httpx.Response(201, json={"sha": "1" * 40})

        # PATCH /git/refs/heads/{branch}
        if "/git/refs/heads/" in url and request.method == "PATCH":
            return httpx.Response(200, json={"object": {"sha": "1" * 40}})

        # POST /git/refs (create new branch)
        if url.endswith("/git/refs") and request.method == "POST":
            return httpx.Response(201, json={"object": {"sha": "1" * 40}})

        return httpx.Response(500, json={"message": f"unmocked {request.method} {url}"})

    return httpx.MockTransport(handler)


def _patch_async_client(transport):
    """Helper to patch user_workspace.httpx.AsyncClient with our transport."""
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs.pop("transport", None)
        return real(*args, transport=transport, **kwargs)

    return patch("user_workspace.httpx.AsyncClient", side_effect=factory)


class TestDoPushScenarios:
    """Three init scenarios required by the hotfix."""

    @pytest.mark.asyncio
    async def test_existing_repo_with_commits(self, fake_workspace, fake_db):
        user_id, _ = fake_workspace
        user_workspace.set_db(fake_db)
        cap = {}
        transport = _make_mock_transport("existing", cap)

        with _patch_async_client(transport):
            res = await user_workspace.do_push(
                user={"id": user_id, "email": "admin@x.com",
                      "role": "admin", "name": "Admin"},
                commit_message="test commit existing",
            )
        assert res.get("ok") is True, f"expected ok=True, got: {res}"
        assert res.get("repo") == "melvinnavas79-del/lluvia-empty-test"
        # Confirm steps include ref_existing, blobs, tree, commit, push
        step_names = [s["step"] for s in res["steps"]]
        assert "ref_existing" in step_names
        assert "blobs" in step_names
        assert "tree" in step_names
        assert "commit" in step_names
        assert "push" in step_names

    @pytest.mark.asyncio
    async def test_new_branch_404(self, fake_workspace, fake_db):
        user_id, _ = fake_workspace
        user_workspace.set_db(fake_db)
        cap = {}
        transport = _make_mock_transport("new_branch", cap)

        with _patch_async_client(transport):
            res = await user_workspace.do_push(
                user={"id": user_id, "email": "admin@x.com",
                      "role": "admin", "name": "Admin"},
                commit_message="test commit new branch",
            )
        assert res.get("ok") is True, f"expected ok=True, got: {res}"
        step_names = [s["step"] for s in res["steps"]]
        assert "ref_new" in step_names
        assert "push" in step_names

    @pytest.mark.asyncio
    async def test_empty_repo_409_bootstrap(self, fake_workspace, fake_db):
        """CRITICAL: empty repo (HTTP 409) -> bootstrap via /contents/README.md.

        This path uses base64.b64encode at line 466. If `base64` is not
        imported at module level, this will raise NameError.
        """
        user_id, _ = fake_workspace
        user_workspace.set_db(fake_db)
        cap = {}
        transport = _make_mock_transport("empty_repo", cap)

        with _patch_async_client(transport):
            res = await user_workspace.do_push(
                user={"id": user_id, "email": "admin@x.com",
                      "role": "admin", "name": "Admin"},
                commit_message="test commit empty repo",
            )
        assert res.get("ok") is True, (
            f"empty repo bootstrap must succeed, got: {res}"
        )
        step_names = [s["step"] for s in res["steps"]]
        assert "bootstrap" in step_names, (
            f"steps must include 'bootstrap' for empty repo; got {step_names}"
        )
        assert "push" in step_names

        # Confirm a PUT to /contents/README.md was issued
        put_contents = [
            (m, u) for (m, u) in cap["requests"]
            if m == "PUT" and "/contents/README.md" in u
        ]
        assert len(put_contents) == 1, (
            f"expected exactly 1 PUT /contents/README.md, got {put_contents}"
        )


# =============================================================
# Skip patterns
# =============================================================
class TestSkipPatterns:
    @pytest.mark.asyncio
    async def test_skipped_dirs_and_extensions(self, fake_workspace, fake_db):
        user_id, base = fake_workspace
        user_workspace.set_db(fake_db)
        cap = {}
        transport = _make_mock_transport("existing", cap)

        with _patch_async_client(transport):
            res = await user_workspace.do_push(
                user={"id": user_id, "email": "admin@x.com",
                      "role": "admin", "name": "Admin"},
                commit_message="check skips",
            )
        assert res.get("ok") is True

        # collect step should report N files (only valid ones)
        collect = [s for s in res["steps"] if s["step"] == "collect"][0]
        # Expected valid files: index.html, app.py, sub/page.js -> 3
        assert "3 archivos" in collect["out"] or "3 files" in collect["out"].lower(), \
            f"expected 3 files collected, got: {collect}"

        # Large file must have produced a skip_large step
        skip_large = [s for s in res["steps"] if s["step"] == "skip_large"]
        assert len(skip_large) == 1
        assert "huge.bin" in skip_large[0]["out"]


# =============================================================
# Bad credentials => no Errno 2 crash
# =============================================================
class TestBadCredentialsGraceful:
    @pytest.mark.asyncio
    async def test_bad_token_returns_auth_failed(self, fake_workspace, fake_db):
        user_id, _ = fake_workspace
        user_workspace.set_db(fake_db)
        cap = {}
        transport = _make_mock_transport("bad_token", cap)

        with _patch_async_client(transport):
            res = await user_workspace.do_push(
                user={"id": user_id, "email": "admin@x.com",
                      "role": "admin", "name": "Admin"},
                commit_message="bad token",
            )
        assert res.get("ok") is False
        assert res.get("auth_failed") is True
        # Error message must mention Bad credentials or 401, NOT Errno 2 / git
        err = (res.get("error") or "").lower()
        assert "bad credentials" in err or "401" in err
        assert "errno 2" not in err
        assert "no such file" not in err


# =============================================================
# Regression: export_locked evaluated BEFORE push REST path
# =============================================================
class TestExportLockRegression:
    @pytest.mark.asyncio
    async def test_non_admin_below_threshold_blocks_push(self, fake_workspace, monkeypatch):
        user_id, _ = fake_workspace
        db = MagicMock()
        db.user_settings.find_one = AsyncMock(return_value={
            "github_token": "ghp_" + "a" * 36,
            "github_repo": "foo/bar",
            "github_branch": "main",
        })
        db.credits.find_one = AsyncMock(return_value={"balance": 5})
        db.user_github_pushes.insert_one = AsyncMock(return_value=None)
        user_workspace.set_db(db)

        # Patch pricing.get_min_balance_for_export to a high threshold
        import pricing as pricing_mod
        monkeypatch.setattr(
            pricing_mod, "get_min_balance_for_export",
            AsyncMock(return_value=100),
        )

        # Even if we'd hit GitHub, the lock should short-circuit BEFORE
        cap = {}
        transport = _make_mock_transport("existing", cap)
        with _patch_async_client(transport):
            res = await user_workspace.do_push(
                user={"id": user_id, "email": "user@x.com",
                      "role": "user", "name": "Normie"},
                commit_message="locked test",
            )
        assert res.get("ok") is False
        assert res.get("export_locked") is True
        assert res.get("balance") == 5
        assert res.get("required") == 100
        # Confirm we did NOT call GitHub at all
        assert len(cap.get("requests", [])) == 0, (
            "export_locked must short-circuit BEFORE any GitHub call"
        )
