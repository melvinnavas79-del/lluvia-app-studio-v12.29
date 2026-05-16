"""
Iteration 20 — Panel admin de precios + Push Lock (candado de exportación).

Backend tests:
- GET/PUT /api/admin/pricing (admin only / 403 user normal)
- Validación de claves desconocidas (ignoradas) y valores negativos/strings
- PUSH LOCK: balance < threshold devuelve export_locked=True
- PUSH LOCK con threshold modificado en runtime
- console.py audio_room: cost dinámico desde pricing
"""

import os
import asyncio
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://ai-bot-cost-calc.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "melvinnavas79@gmail.com"
ADMIN_PASSWORD = "Admin#2026"
USER_EMAIL = "juan@test.com"
USER_PASSWORD = "test1234"


# ---------- helpers ----------
def _login(email: str, password: str) -> str:
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": email, "password": password},
                      timeout=15)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text[:200]}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_token() -> str:
    return _login(ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture(scope="module")
def user_token() -> str:
    return _login(USER_EMAIL, USER_PASSWORD)


@pytest.fixture(scope="module")
def admin_h(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="module")
def user_h(user_token):
    return {"Authorization": f"Bearer {user_token}"}


@pytest.fixture(scope="module")
def user_id(user_token) -> str:
    r = requests.get(f"{BASE_URL}/api/auth/me",
                     headers={"Authorization": f"Bearer {user_token}"}, timeout=10)
    assert r.status_code == 200
    return r.json()["id"]


def _set_user_balance(uid: str, balance: int) -> None:
    """Set user balance directly via mongo (motor async)."""
    async def _do():
        from motor.motor_asyncio import AsyncIOMotorClient
        cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = cli[os.environ["DB_NAME"]]
        await db.credits.update_one({"user_id": uid},
                                    {"$set": {"user_id": uid, "balance": balance}},
                                    upsert=True)
        cli.close()
    asyncio.get_event_loop().run_until_complete(_do()) if False else asyncio.run(_do())


def _ensure_user_settings(uid: str) -> None:
    """Guarantee github_token + github_repo exist for the user (so PUSH-LOCK
    branch is not short-circuited by needs_setup)."""
    async def _do():
        from motor.motor_asyncio import AsyncIOMotorClient
        cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = cli[os.environ["DB_NAME"]]
        await db.user_settings.update_one(
            {"user_id": uid},
            {"$set": {
                "user_id": uid,
                "github_token": "ghp_FAKE_FOR_TEST_ONLY_DO_NOT_USE",
                "github_repo": "fake/repo-test",
                "github_branch": "main",
            }},
            upsert=True,
        )
        cli.close()
    asyncio.run(_do())


# ============================================================
# 1. Admin pricing — GET
# ============================================================
class TestAdminPricingGet:
    def test_admin_get_pricing(self, admin_h):
        r = requests.get(f"{BASE_URL}/api/admin/pricing", headers=admin_h, timeout=10)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "tool_prices" in data
        assert "min_balance_for_export" in data
        assert "templates" in data
        # audio_room está en defaults
        assert "generate_audio_room_app" in data["tool_prices"]
        # 5 templates (1 audio_room + 4 coming_soon)
        assert len(data["templates"]) == 5
        coming_soon = [t for t in data["templates"] if t.get("coming_soon")]
        assert len(coming_soon) == 4
        # types
        assert isinstance(data["tool_prices"]["generate_audio_room_app"], int)
        assert isinstance(data["min_balance_for_export"], int)

    def test_user_get_pricing_403(self, user_h):
        r = requests.get(f"{BASE_URL}/api/admin/pricing", headers=user_h, timeout=10)
        assert r.status_code == 403, f"expected 403, got {r.status_code} {r.text[:200]}"

    def test_no_auth_get_pricing(self):
        r = requests.get(f"{BASE_URL}/api/admin/pricing", timeout=10)
        assert r.status_code in (401, 403)


# ============================================================
# 2. Admin pricing — PUT
# ============================================================
class TestAdminPricingPut:
    def test_put_updates_and_persists(self, admin_h):
        # Snapshot original
        orig = requests.get(f"{BASE_URL}/api/admin/pricing", headers=admin_h).json()
        orig_audio = orig["tool_prices"]["generate_audio_room_app"]
        orig_thr = orig["min_balance_for_export"]

        try:
            r = requests.put(f"{BASE_URL}/api/admin/pricing", headers=admin_h,
                             json={"tool_prices": {"generate_audio_room_app": 25},
                                   "min_balance_for_export": 80}, timeout=10)
            assert r.status_code == 200, r.text
            data = r.json()
            assert data["tool_prices"]["generate_audio_room_app"] == 25
            assert data["min_balance_for_export"] == 80
            assert data.get("updated_by") == ADMIN_EMAIL
            assert data.get("updated_at")  # ISO no nulo

            # Persistencia
            r2 = requests.get(f"{BASE_URL}/api/admin/pricing", headers=admin_h).json()
            assert r2["tool_prices"]["generate_audio_room_app"] == 25
            assert r2["min_balance_for_export"] == 80
        finally:
            # Restaurar
            requests.put(f"{BASE_URL}/api/admin/pricing", headers=admin_h,
                         json={"tool_prices": {"generate_audio_room_app": orig_audio},
                               "min_balance_for_export": orig_thr}, timeout=10)

    def test_put_unknown_tool_id_ignored(self, admin_h):
        before = requests.get(f"{BASE_URL}/api/admin/pricing", headers=admin_h).json()
        r = requests.put(f"{BASE_URL}/api/admin/pricing", headers=admin_h,
                         json={"tool_prices": {"fake_tool_xyz": 99}}, timeout=10)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "fake_tool_xyz" not in data["tool_prices"]
        # set conocidos no cambiaron
        assert data["tool_prices"]["generate_audio_room_app"] == \
               before["tool_prices"]["generate_audio_room_app"]

    def test_put_negative_saturates_to_zero(self, admin_h):
        orig = requests.get(f"{BASE_URL}/api/admin/pricing", headers=admin_h).json()
        orig_v = orig["tool_prices"]["generate_audio_room_app"]
        try:
            r = requests.put(f"{BASE_URL}/api/admin/pricing", headers=admin_h,
                             json={"tool_prices": {"generate_audio_room_app": -10}},
                             timeout=10)
            assert r.status_code == 200
            assert r.json()["tool_prices"]["generate_audio_room_app"] == 0
        finally:
            requests.put(f"{BASE_URL}/api/admin/pricing", headers=admin_h,
                         json={"tool_prices": {"generate_audio_room_app": orig_v}},
                         timeout=10)

    def test_put_string_value_ignored(self, admin_h):
        before = requests.get(f"{BASE_URL}/api/admin/pricing", headers=admin_h).json()
        before_v = before["tool_prices"]["generate_audio_room_app"]
        r = requests.put(f"{BASE_URL}/api/admin/pricing", headers=admin_h,
                         json={"tool_prices": {"generate_audio_room_app": "abc"}},
                         timeout=10)
        # No debe romper. El valor previo se mantiene.
        assert r.status_code == 200
        assert r.json()["tool_prices"]["generate_audio_room_app"] == before_v

    def test_put_user_403(self, user_h):
        r = requests.put(f"{BASE_URL}/api/admin/pricing", headers=user_h,
                         json={"min_balance_for_export": 10}, timeout=10)
        assert r.status_code == 403


# ============================================================
# 3. Push Lock
# ============================================================
class TestPushLock:
    def test_user_low_balance_locked(self, user_h, admin_h, user_id):
        # set threshold a 50 + balance del user a 10
        requests.put(f"{BASE_URL}/api/admin/pricing", headers=admin_h,
                     json={"min_balance_for_export": 50}, timeout=10)
        _set_user_balance(user_id, 10)
        _ensure_user_settings(user_id)

        r = requests.post(f"{BASE_URL}/api/me/github/push", headers=user_h,
                          json={"commit_message": "test"}, timeout=15)
        # do_push devuelve dict con ok:false; el endpoint pasa el dict tal cual
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("ok") is False
        assert data.get("export_locked") is True
        assert data.get("balance") == 10
        assert data.get("required") == 50
        assert data.get("missing") == 40
        assert data.get("recharge_url") == "/#/recharge"
        assert "Has creado tu app con éxito" in data.get("message", "")
        assert "adquiere un paquete de oros" in data.get("message", "")

    def test_threshold_modified_unlocks(self, user_h, admin_h, user_id):
        # bajar threshold a 5 -> user con 10 ya puede pasar la lock
        try:
            requests.put(f"{BASE_URL}/api/admin/pricing", headers=admin_h,
                         json={"min_balance_for_export": 5}, timeout=10)
            _set_user_balance(user_id, 10)
            _ensure_user_settings(user_id)
            r = requests.post(f"{BASE_URL}/api/me/github/push", headers=user_h,
                              json={"commit_message": "test"}, timeout=20)
            assert r.status_code == 200, r.text
            data = r.json()
            # Ya no está locked. Puede fallar por token inválido (esperado),
            # pero NO debe tener export_locked.
            assert data.get("export_locked") is not True, \
                f"Should NOT be export_locked anymore: {data}"
        finally:
            # Restaurar
            requests.put(f"{BASE_URL}/api/admin/pricing", headers=admin_h,
                         json={"min_balance_for_export": 50}, timeout=10)

    def test_admin_bypasses_push_lock(self, admin_h, admin_token):
        """Admin nunca debe ser bloqueado por push lock — independiente de saldo."""
        # admin no necesita settings completos -- nos fijamos solo que NO
        # devuelva export_locked:True
        r = requests.post(f"{BASE_URL}/api/me/github/push", headers=admin_h,
                          json={"commit_message": "admin test"}, timeout=20)
        assert r.status_code == 200
        data = r.json()
        assert data.get("export_locked") is not True


# ============================================================
# 4. Console.py — cost dinámico (verificación funcional vía pricing module)
# ============================================================
class TestDynamicCost:
    def test_get_tool_price_reflects_admin_change(self, admin_h):
        """Verifica que cambiar el precio via panel se refleja en pricing.get_tool_price
        — que es lo que console.py:667-707 lee para setear cost en _exec_tool."""
        orig = requests.get(f"{BASE_URL}/api/admin/pricing", headers=admin_h).json()
        orig_v = orig["tool_prices"]["generate_audio_room_app"]
        try:
            requests.put(f"{BASE_URL}/api/admin/pricing", headers=admin_h,
                         json={"tool_prices": {"generate_audio_room_app": 25}},
                         timeout=10)
            # Verificar via GET que el efecto está en DB (que es lo mismo que
            # console.py lee con pricing_mod.get_tool_price)
            after = requests.get(f"{BASE_URL}/api/admin/pricing", headers=admin_h).json()
            assert after["tool_prices"]["generate_audio_room_app"] == 25

            # Lectura directa al módulo pricing para confirmar la lógica
            async def _check():
                import sys
                sys.path.insert(0, "/app/backend")
                from motor.motor_asyncio import AsyncIOMotorClient
                cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
                db = cli[os.environ["DB_NAME"]]
                import pricing as pm
                pm.set_db(db)
                price = await pm.get_tool_price("generate_audio_room_app")
                cli.close()
                return price
            price = asyncio.run(_check())
            assert price == 25, f"pricing.get_tool_price returned {price}, expected 25"
        finally:
            requests.put(f"{BASE_URL}/api/admin/pricing", headers=admin_h,
                         json={"tool_prices": {"generate_audio_room_app": orig_v}},
                         timeout=10)
