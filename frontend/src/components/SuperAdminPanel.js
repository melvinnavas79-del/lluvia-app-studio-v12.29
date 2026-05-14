import { useEffect, useState } from "react";
import { api, formatError } from "../api";

export default function SuperAdminPanel() {
  const [tab, setTab] = useState("overview");
  return (
    <div className="super-admin" data-testid="super-admin-panel">
      <div className="sa-header">
        <h2 className="section-title" style={{ marginBottom: 0 }}>
          👑 Consola del Dueño · SuperAdmin
        </h2>
        <p className="hero-sub" style={{ marginTop: "0.25rem" }}>
          Control total · Bypass de oros · Backup directo a GitHub
        </p>
      </div>

      <div className="tabs sa-tabs" style={{ marginTop: "1rem" }}>
        {[
          ["overview", "📊 Overview"],
          ["sessions", "💬 Sesiones de todos"],
          ["users", "👥 Usuarios"],
          ["backup", "📦 Push & Backup"],
        ].map(([k, label]) => (
          <button
            key={k}
            className={`tab ${tab === k ? "active" : ""}`}
            onClick={() => setTab(k)}
            data-testid={`sa-tab-${k}`}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "overview" && <OverviewPanel />}
      {tab === "sessions" && <SessionsPanel />}
      {tab === "users" && <UsersPanel />}
      {tab === "backup" && <BackupPanel />}
    </div>
  );
}

function OverviewPanel() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    api.get("/super/overview").then((r) => setData(r.data)).catch((e) => setErr(formatError(e)));
  }, []);
  if (err) return <div className="alert">{err}</div>;
  if (!data) return <div className="empty">Cargando...</div>;
  return (
    <div style={{ marginTop: "1rem" }}>
      <div className="ag-stats">
        <Stat label="Usuarios" value={data.users} />
        <Stat label="Sesiones totales" value={data.sessions} />
        <Stat label="Agentes custom" value={data.custom_agents} />
        <Stat label="Citas reservadas" value={data.appointments} />
        <Stat label="Propuestas pendientes" value={data.proposals_pending} />
      </div>
      <h3>Últimas sesiones (todos los usuarios)</h3>
      <table className="ag-table" data-testid="sa-recent-sessions">
        <thead>
          <tr><th>Usuario</th><th>Agente</th><th>Título</th><th>Último mensaje</th><th>Actualizado</th></tr>
        </thead>
        <tbody>
          {data.recent_sessions.map((s) => (
            <tr key={s.id}>
              <td>{s.user_email}</td>
              <td>{s.agent_id}</td>
              <td>{s.title}</td>
              <td style={{ fontSize: "0.8em", color: "rgba(255,255,255,0.6)" }}>
                {(s.last_message_preview || "").slice(0, 60)}
              </td>
              <td>{(s.updated_at || "").slice(0, 16).replace("T", " ")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Stat({ label, value }) {
  return (
    <div className="ag-stat">
      <div className="ag-stat-label">{label}</div>
      <div className="ag-stat-num">{value}</div>
    </div>
  );
}

function SessionsPanel() {
  const [sessions, setSessions] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [activeSession, setActiveSession] = useState(null);
  const [takeoverText, setTakeoverText] = useState("");
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");

  const load = async () => {
    try {
      const { data } = await api.get("/super/sessions/all");
      setSessions(data.sessions || []);
    } catch (e) { setErr(formatError(e)); }
  };
  useEffect(() => { load(); }, []);

  const openSession = async (sid) => {
    setActiveId(sid);
    try {
      const { data } = await api.get(`/super/sessions/${sid}`);
      setActiveSession(data);
    } catch (e) { setErr(formatError(e)); }
  };

  const takeover = async () => {
    if (!takeoverText.trim() || !activeId) return;
    setErr(""); setMsg("");
    try {
      await api.post(`/super/sessions/${activeId}/takeover`, {
        text: takeoverText, as_role: "assistant",
      });
      setMsg("Mensaje inyectado como agente.");
      setTakeoverText("");
      setTimeout(() => setMsg(""), 3000);
      openSession(activeId);
    } catch (e) { setErr(formatError(e)); }
  };

  return (
    <div style={{ display: "grid", gridTemplateColumns: "320px 1fr", gap: "1rem", marginTop: "1rem" }}>
      <div style={{ maxHeight: 600, overflowY: "auto" }}>
        <h4 style={{ margin: "0 0 0.5rem" }}>Todas las sesiones ({sessions.length})</h4>
        {sessions.map((s) => (
          <div
            key={s.id}
            className={`bc-thread ${activeId === s.id ? "active" : ""}`}
            onClick={() => openSession(s.id)}
            style={{ cursor: "pointer", marginBottom: "0.5rem" }}
            data-testid={`sa-session-${s.id}`}
          >
            <div className="bc-thread-meta">
              <div className="bc-thread-title">{s.title || s.agent_id}</div>
              <div className="bc-thread-preview">
                {s.user_email} · {(s.last_message_preview || "").slice(0, 40)}
              </div>
            </div>
          </div>
        ))}
      </div>
      <div>
        {!activeSession ? (
          <div className="empty">Elige una sesión para verla y tomar control.</div>
        ) : (
          <>
            <div className="form-card" style={{ padding: "0.75rem 1rem" }}>
              <strong>{activeSession.title}</strong> · {activeSession.user_email} · agente: {activeSession.agent_id}
            </div>
            {err && <div className="alert">{err}</div>}
            {msg && <div className="success">{msg}</div>}
            <div className="cc-transcript" style={{ marginTop: "0.75rem", maxHeight: 420 }}>
              {(activeSession.messages || []).slice(-30).map((m, i) => (
                <div key={i} className={`cc-bubble ${m.role === "user" ? "user" : "assistant"}`}>
                  <span className="cc-role">{m.role}{m.superadmin_takeover ? " · 👑" : ""}:</span>
                  {m.content}
                </div>
              ))}
            </div>
            <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.75rem" }}>
              <input
                value={takeoverText}
                onChange={(e) => setTakeoverText(e.target.value)}
                placeholder="Escribir como agente (takeover)..."
                style={{ flex: 1 }}
                data-testid="sa-takeover-input"
              />
              <button className="login-btn" onClick={takeover} data-testid="sa-takeover-send">
                Inyectar
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function UsersPanel() {
  const [users, setUsers] = useState([]);
  const [err, setErr] = useState("");
  useEffect(() => {
    api.get("/super/users").then((r) => setUsers(r.data.users || [])).catch((e) => setErr(formatError(e)));
  }, []);
  if (err) return <div className="alert">{err}</div>;
  return (
    <table className="ag-table" data-testid="sa-users-table" style={{ marginTop: "1rem" }}>
      <thead>
        <tr><th>Email</th><th>Nombre</th><th>Rol</th><th>Balance</th><th>Gastado</th><th>Activo</th></tr>
      </thead>
      <tbody>
        {users.map((u) => (
          <tr key={u.id}>
            <td>{u.email}</td>
            <td>{u.name || "—"}</td>
            <td><span className={`chip status-${u.role === "admin" ? "applied" : "pending"}`}>{u.role}</span></td>
            <td style={{ color: "#ffc85a" }}>{u.balance} ⚜</td>
            <td>{u.lifetime_spent}</td>
            <td>{u.active === false ? "❌" : "✅"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function BackupPanel() {
  const [commitMessage, setCommitMessage] = useState("");
  const [branch, setBranch] = useState("main");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [history, setHistory] = useState([]);
  const [err, setErr] = useState("");

  const loadHistory = async () => {
    try {
      const { data } = await api.get("/super/github/history");
      setHistory(data.backups || []);
    } catch (_) {}
  };
  useEffect(() => { loadHistory(); }, []);

  const doPush = async () => {
    setBusy(true);
    setErr(""); setResult(null);
    try {
      const { data } = await api.post("/super/github/push", {
        commit_message: commitMessage || null,
        branch,
      });
      setResult(data);
      await loadHistory();
    } catch (e) {
      setErr(formatError(e));
    } finally { setBusy(false); }
  };

  return (
    <div style={{ marginTop: "1rem" }}>
      <div className="form-card" data-testid="sa-backup-form">
        <h3 style={{ marginTop: 0 }}>📦 Push & Backup a GitHub</h3>
        <p className="hero-sub">
          Empuja TODO el código `/app` a tu repo privado. Solo vos (SuperAdmin) ves esto;
          los clientes nunca acceden a tu código base.
        </p>
        <div className="form-row">
          <div className="field" style={{ flex: 2 }}>
            <label>Commit message</label>
            <input
              value={commitMessage}
              onChange={(e) => setCommitMessage(e.target.value)}
              placeholder="backup automático (default)"
              data-testid="sa-commit-msg"
            />
          </div>
          <div className="field">
            <label>Branch</label>
            <input
              value={branch}
              onChange={(e) => setBranch(e.target.value)}
              data-testid="sa-branch"
            />
          </div>
        </div>
        <button
          className="login-btn"
          onClick={doPush}
          disabled={busy}
          data-testid="sa-push-btn"
          style={{ marginTop: "0.75rem" }}
        >
          {busy ? "Empujando..." : "🚀 Push & Backup ahora"}
        </button>
      </div>

      {err && <div className="alert" style={{ marginTop: "1rem" }}>{err}</div>}
      {result && (
        <div className={`form-card ${result.ok ? "success-card" : "fail-card"}`} style={{ marginTop: "1rem" }}>
          <strong>{result.ok ? "✅ Push exitoso" : "❌ Push falló"}</strong>
          <div style={{ fontSize: "0.85em", marginTop: "0.5rem" }}>
            Repo: <code>{result.repo}</code> · Branch: <code>{result.branch}</code>
          </div>
          <details style={{ marginTop: "0.5rem" }}>
            <summary>Ver detalle por paso</summary>
            <pre style={{ fontSize: "0.75em", maxHeight: 300, overflow: "auto" }}>
              {JSON.stringify(result.steps, null, 2)}
            </pre>
          </details>
        </div>
      )}

      <h4 style={{ marginTop: "1.5rem" }}>Historial de backups</h4>
      {history.length === 0 ? (
        <div className="empty">Sin backups todavía.</div>
      ) : (
        <table className="ag-table">
          <thead><tr><th>Fecha</th><th>Por</th><th>Branch</th><th>Msg</th><th>OK</th></tr></thead>
          <tbody>
            {history.map((b) => (
              <tr key={b.id}>
                <td>{(b.ts || "").slice(0, 16).replace("T", " ")}</td>
                <td>{b.by}</td>
                <td>{b.branch}</td>
                <td style={{ fontSize: "0.85em" }}>{(b.commit_message || "").slice(0, 50)}</td>
                <td>{b.success ? "✅" : "❌"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
