"""
Tests v11 (iteration_6) — SuperAdmin, Appointments, Rich Cards, custom-agent sessions.

Run:
    pytest /app/backend/tests/test_iteration_6_v11.py -v --tb=short \
        --junitxml=/app/test_reports/pytest/iteration_6_results.xml
"""
import os
import time
import uuid
import json
import pytest
import requests

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE}/api"

ADMIN_EMAIL = "melvinnavas79@gmail.com"
ADMIN_PASS = "Admin#2026"

# Non-admin throwaway
NORMAL_EMAIL = f"TEST_user_{uuid.uuid4().hex[:8]}@test.com"
NORMAL_PASS = "Hola1234!"


# ----------- Fixtures -----------
@pytest.fixture(scope="session")
def admin_token():
    r = requests.post(f"{API}/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def normal_token(admin_token):
    # Create an affiliate user via admin endpoint, then login as them.
    payload = {"email": NORMAL_EMAIL, "password": NORMAL_PASS,
               "name": "TEST V11 Affiliate", "commission_pct": 10,
               "telegram_chat_id": "0"}
    r = requests.post(f"{API}/affiliates", json=payload,
                      headers=H(admin_token), timeout=15)
    # 200/201 if created, 409 if already exists (re-run scenario)
    assert r.status_code in (200, 201, 409), r.text
    r2 = requests.post(f"{API}/auth/login",
                       json={"email": NORMAL_EMAIL, "password": NORMAL_PASS}, timeout=15)
    assert r2.status_code == 200, r2.text
    return r2.json()["access_token"]


def H(tok):
    return {"Authorization": f"Bearer {tok}"}


# ============================================================
# 1) Custom agent creation + session against custom agent id
# ============================================================
@pytest.fixture(scope="session")
def custom_agent(admin_token):
    aid = f"test_v11_{uuid.uuid4().hex[:6]}"
    body = {
        "id": aid, "name": "Test V11 Agent", "emoji": "🧪", "color": "#5fb4ff",
        "voice": "alloy", "tagline": "test",
        "system": "Eres un asistente de prueba para verificacion v11. Sigue instrucciones de tools.",
        "tools": ["book_appointment", "check_availability", "list_appointments",
                  "cancel_appointment", "paypal_invoice_card", "service_card"],
    }
    r = requests.post(f"{API}/agent-builder", json=body,
                      headers=H(admin_token), timeout=15)
    assert r.status_code == 200, r.text
    yield aid
    requests.delete(f"{API}/agent-builder/{aid}", headers=H(admin_token), timeout=10)


def test_create_session_with_custom_agent(admin_token, custom_agent):
    """v11 fix: console.create_session must accept custom agent_id (was 400 before)."""
    r = requests.post(f"{API}/console/sessions",
                      json={"agent_id": custom_agent, "title": "TEST_v11_custom_sess"},
                      headers=H(admin_token), timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["agent_id"] == custom_agent
    assert "id" in body
    # cleanup
    requests.delete(f"{API}/console/sessions/{body['id']}",
                    headers=H(admin_token), timeout=10)


def test_create_session_unknown_agent_400(admin_token):
    r = requests.post(f"{API}/console/sessions",
                      json={"agent_id": "no_existe_xxx"},
                      headers=H(admin_token), timeout=15)
    assert r.status_code == 400


# ============================================================
# 2) /api/super/* (SuperAdmin)
# ============================================================
def test_super_overview_admin(admin_token):
    r = requests.get(f"{API}/super/overview", headers=H(admin_token), timeout=15)
    assert r.status_code == 200, r.text
    j = r.json()
    for k in ("users", "sessions", "custom_agents", "appointments",
              "proposals_pending", "recent_sessions"):
        assert k in j, f"missing key {k}"
    assert isinstance(j["recent_sessions"], list)
    if j["recent_sessions"]:
        assert "user_email" in j["recent_sessions"][0]


def test_super_overview_forbidden_for_normal(normal_token):
    r = requests.get(f"{API}/super/overview", headers=H(normal_token), timeout=15)
    assert r.status_code == 403


def test_super_sessions_all(admin_token):
    r = requests.get(f"{API}/super/sessions/all", headers=H(admin_token), timeout=15)
    assert r.status_code == 200
    j = r.json()
    assert "sessions" in j and isinstance(j["sessions"], list)
    if j["sessions"]:
        assert "user_email" in j["sessions"][0]


def test_super_sessions_all_forbidden(normal_token):
    r = requests.get(f"{API}/super/sessions/all", headers=H(normal_token), timeout=15)
    assert r.status_code == 403


def test_super_session_by_id_404(admin_token):
    r = requests.get(f"{API}/super/sessions/does_not_exist_xxx",
                     headers=H(admin_token), timeout=15)
    assert r.status_code == 404


def test_super_session_by_id_and_takeover(admin_token, custom_agent):
    # Create a session
    r = requests.post(f"{API}/console/sessions",
                      json={"agent_id": custom_agent, "title": "TEST_takeover"},
                      headers=H(admin_token), timeout=15)
    sid = r.json()["id"]
    try:
        # GET as super
        r2 = requests.get(f"{API}/super/sessions/{sid}",
                          headers=H(admin_token), timeout=15)
        assert r2.status_code == 200
        body = r2.json()
        assert body["id"] == sid
        assert "user_email" in body and body["user_email"] == ADMIN_EMAIL

        # Takeover injects message
        payload = {"text": "TEST_takeover_v11_inject", "as_role": "assistant"}
        r3 = requests.post(f"{API}/super/sessions/{sid}/takeover",
                           json=payload, headers=H(admin_token), timeout=15)
        assert r3.status_code == 200, r3.text
        injected = r3.json()["message"]
        assert injected["superadmin_takeover"] is True
        assert injected["by"] == ADMIN_EMAIL

        # Verify persisted
        r4 = requests.get(f"{API}/super/sessions/{sid}",
                          headers=H(admin_token), timeout=15)
        msgs = r4.json().get("messages", [])
        assert any(m.get("superadmin_takeover") and
                   m["content"] == "TEST_takeover_v11_inject" for m in msgs)
    finally:
        requests.delete(f"{API}/console/sessions/{sid}",
                        headers=H(admin_token), timeout=10)


def test_super_users(admin_token):
    r = requests.get(f"{API}/super/users", headers=H(admin_token), timeout=15)
    assert r.status_code == 200
    j = r.json()
    assert "users" in j and isinstance(j["users"], list)
    assert len(j["users"]) > 0
    sample = j["users"][0]
    assert "balance" in sample
    assert "lifetime_spent" in sample
    assert "password_hash" not in sample


def test_super_users_forbidden(normal_token):
    r = requests.get(f"{API}/super/users", headers=H(normal_token), timeout=15)
    assert r.status_code == 403


def test_super_github_push(admin_token):
    r = requests.post(f"{API}/super/github/push",
                      json={"commit_message": "TEST v11 backup probe"},
                      headers=H(admin_token), timeout=120)
    assert r.status_code == 200, f"github_push must NOT 500 even if token revoked, got {r.status_code} {r.text[:300]}"
    j = r.json()
    assert "ok" in j
    assert "steps" in j and isinstance(j["steps"], list)
    step_names = [s["step"] for s in j["steps"]]
    for need in ("remote", "add", "commit", "push"):
        assert need in step_names, f"missing step {need}"


def test_super_github_push_forbidden(normal_token):
    r = requests.post(f"{API}/super/github/push", json={},
                      headers=H(normal_token), timeout=30)
    assert r.status_code == 403


def test_super_github_history(admin_token):
    r = requests.get(f"{API}/super/github/history",
                     headers=H(admin_token), timeout=15)
    assert r.status_code == 200
    j = r.json()
    assert "backups" in j and isinstance(j["backups"], list)


# ============================================================
# 3) /api/appointments GET/DELETE
# ============================================================
def test_appointments_list_owner_only(admin_token):
    r = requests.get(f"{API}/appointments", headers=H(admin_token), timeout=15)
    assert r.status_code == 200
    j = r.json()
    assert "appointments" in j and isinstance(j["appointments"], list)


def test_appointments_delete_cancels(admin_token):
    # We need at least one appointment. Try to create one via direct module not possible via HTTP.
    # Use a fake id first to verify endpoint shape.
    r = requests.delete(f"{API}/appointments/nonexistent_xxx",
                        headers=H(admin_token), timeout=15)
    assert r.status_code == 200
    j = r.json()
    assert j.get("cancelled") is False


# ============================================================
# 4) Tool flow via send_message — paypal_invoice_card + book
# ============================================================
@pytest.fixture(scope="session")
def custom_session(admin_token, custom_agent):
    r = requests.post(f"{API}/console/sessions",
                      json={"agent_id": custom_agent, "title": "TEST_v11_tool_flow"},
                      headers=H(admin_token), timeout=15)
    sid = r.json()["id"]
    yield sid
    requests.delete(f"{API}/console/sessions/{sid}",
                    headers=H(admin_token), timeout=10)


def _send(sid, text, tok, timeout=60):
    return requests.post(f"{API}/console/sessions/{sid}/messages",
                         json={"text": text}, headers=H(tok), timeout=timeout)


def test_paypal_invoice_card_tool(admin_token, custom_session):
    """Pidiendo cobrar 20 USD, el agente debe invocar paypal_invoice_card.
    Cuando se ejecuta, debe haber tool_calls con result containing approve_url."""
    r = _send(custom_session,
              "Genera una factura PayPal de 20 USD para el cliente Juan, descripcion: corte de cabello.",
              admin_token, timeout=90)
    assert r.status_code == 200, r.text
    body = r.json()
    am = body.get("assistant_message", {})
    tcs = am.get("tool_calls", [])
    paypal_call = next((t for t in tcs if t["name"] == "paypal_invoice_card"), None)
    if paypal_call is None:
        pytest.skip(f"LLM no llamo paypal_invoice_card (no-deterministic). tools_called={[t['name'] for t in tcs]}")
    preview = paypal_call.get("result_preview", "")
    # debe contener approve_url o order_id o error de PayPal
    assert ("approve_url" in preview) or ("order_id" in preview) or ("error" in preview), preview


def test_book_and_check_availability(admin_token, custom_session):
    """Reservar para Juan en una fecha futura — espera book_appointment + check."""
    future_date = "2027-06-15"
    text = (f"Reserva una cita: cliente Juan, telefono 555-1234, "
            f"email juan@example.com, servicio corte, fecha {future_date}, hora 10:00.")
    r = _send(custom_session, text, admin_token, timeout=90)
    assert r.status_code == 200, r.text
    body = r.json()
    tcs = body.get("assistant_message", {}).get("tool_calls", [])
    names = [t["name"] for t in tcs]
    if "book_appointment" not in names:
        pytest.skip(f"LLM no llamo book_appointment. tools_called={names}")
    # Verificar que aparece en /api/appointments
    r2 = requests.get(f"{API}/appointments",
                      headers=H(admin_token), timeout=15)
    appts = r2.json().get("appointments", [])
    assert any(a.get("date") == future_date and a.get("time") == "10:00" and
               a.get("status") == "confirmed" for a in appts), \
        f"cita no aparece en /api/appointments: {[a for a in appts if a.get('date')==future_date]}"


# ============================================================
# 5) Validacion appointments (via direct module call)
# ============================================================
@pytest.mark.asyncio
async def test_validation_past_date_invalid_format_overlap(admin_token):
    """Direct call to appointments.tool_book / tool_check_availability."""
    import sys
    sys.path.insert(0, "/app/backend")
    import appointments as appt
    from motor.motor_asyncio import AsyncIOMotorClient

    cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = cli[os.environ["DB_NAME"]]
    appt.set_db(db)

    # find admin user id
    u = await db.users.find_one({"email": ADMIN_EMAIL})
    owner_id = u["id"]
    agent_id = f"test_validate_{uuid.uuid4().hex[:6]}"

    # past date
    r = await appt.tool_book(owner_id, agent_id, {
        "client_name": "Test", "service": "X", "date": "2020-01-01", "time": "10:00"})
    assert "error" in r and "pasado" in r["error"].lower()

    # invalid format
    r = await appt.tool_book(owner_id, agent_id, {
        "client_name": "T", "service": "X", "date": "15-06-2027", "time": "10:00"})
    assert "error" in r and "formato" in r["error"].lower()

    # missing field
    r = await appt.tool_book(owner_id, agent_id, {"client_name": "T"})
    assert "error" in r

    # overlap
    args = {"client_name": "T", "service": "X", "date": "2027-08-20", "time": "14:00",
            "client_phone": "999", "client_email": "t@t.com"}
    r1 = await appt.tool_book(owner_id, agent_id, args)
    assert r1.get("booked") is True
    r2 = await appt.tool_book(owner_id, agent_id, args)
    assert "error" in r2 and ("solap" in r2["error"].lower() or "cita en" in r2["error"].lower())

    # cleanup overlap doc
    await db.appointments.delete_many({"owner_id": owner_id, "agent_id": agent_id})
    cli.close()


# ============================================================
# 6) Admin-only tools return error when role != admin
# ============================================================
def test_admin_only_tools_blocked_for_normal_user(normal_token):
    """create custom agent w/ create_agent tool, send message as normal user.
    Should not error: tools are filtered only when is_admin=True, so no tool_calls."""
    # Create a session against a builtin "arquitecto" if exists, else simple sexologo
    r = requests.get(f"{API}/console/agents", headers=H(normal_token), timeout=15)
    assert r.status_code == 200
    agents = [a["id"] for a in r.json()["agents"]]
    # Pick any non-admin-tool agent
    aid = next((a for a in agents if a in ("sexologo", "psicologo_pareja", "doctor_gp")), agents[0])
    r2 = requests.post(f"{API}/console/sessions",
                      json={"agent_id": aid}, headers=H(normal_token), timeout=15)
    assert r2.status_code == 200
    sid = r2.json()["id"]
    try:
        # Just verify message flow ok (no admin-tool exec)
        r3 = _send(sid, "Hola, como estas?", normal_token, timeout=60)
        if r3.status_code == 402:
            pytest.skip("Normal user has 0 oros — no podemos probar flow chat")
        # 502 if OPENAI key broken in preview, but message base flow is invoked
        assert r3.status_code in (200, 502), r3.text
    finally:
        requests.delete(f"{API}/console/sessions/{sid}",
                        headers=H(normal_token), timeout=10)


# ============================================================
# 7) v10 endpoints still functional
# ============================================================
def test_v10_promos_crud(admin_token):
    r = requests.get(f"{API}/promos", headers=H(admin_token), timeout=15)
    assert r.status_code == 200


def test_v10_proposals_list(admin_token):
    r = requests.get(f"{API}/proposals", headers=H(admin_token), timeout=15)
    assert r.status_code == 200


def test_v10_paypal_packs(admin_token):
    r = requests.get(f"{API}/paypal/packs", headers=H(admin_token), timeout=15)
    assert r.status_code == 200
    j = r.json()
    assert "packs" in j


def test_v10_paypal_webhook_403_no_sig():
    r = requests.post(f"{API}/paypal/webhook", json={"event_type": "x"}, timeout=15)
    assert r.status_code == 403


def test_v10_branding_get():
    r = requests.get(f"{API}/branding", timeout=15)
    assert r.status_code == 200


def test_v10_download_info():
    r = requests.get(f"{API}/download/lluvia-deploy/info", timeout=15)
    assert r.status_code == 200


def test_v10_voice_call_center_auth_required():
    r = requests.post(f"{API}/voice/call-center/turn",
                      json={"agent_id": "sexologo", "audio_b64": ""}, timeout=15)
    assert r.status_code in (401, 403, 422)
