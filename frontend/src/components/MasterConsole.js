/**
 * MasterConsole.js — Operations Console
 *
 * Tab oculta accesible via #/masterops desde AdminDashboard.
 * SOLO visible para SuperAdmin que conoce el MASTER_KEY.
 * NO reemplaza ningún componente existente.
 *
 * Convive con: DevOpsConsole, BossConsole, SuperAdminPanel, AgentBuilder, etc.
 * Reutiliza: api, formatError desde ../api — useAuth desde ../AuthContext
 * Consume: /api/master/* endpoints (master_console.py — MASTER_KEY required)
 *
 * Sub-secciones:
 *   monitor     — Live snapshot: queue, costos IA, errores, worker heartbeat
 *   python      — Sandbox Python con MASTER_KEY
 *   shell       — Shell runner con blocklist de seguridad
 *   queue       — Job queue: ver, reintentar, limpiar DLQ
 *   diagnostics — Diagnóstico por tenant_id
 *   audit       — Audit trail de acciones de la consola
 *   status      — Estado REAL/PARCIAL/STUB de todos los módulos
 */

import { useEffect, useState, useRef, useCallback } from "react";
import { api, formatError } from "../api";
import { useAuth } from "../AuthContext";

// ──────────────────────────────────────────────────────────────
// MASTER_KEY header helper
// ──────────────────────────────────────────────────────────────
function masterHeaders(key) {
  return { "X-Master-Key": key };
}

// ──────────────────────────────────────────────────────────────
// Root
// ──────────────────────────────────────────────────────────────
export default function MasterConsole() {
  const { user } = useAuth();
  const [masterKey, setMasterKey]   = useState(() => sessionStorage.getItem("mc_key") || "");
  const [keyInput, setKeyInput]     = useState("");
  const [keyError, setKeyError]     = useState("");
  const [keyOk, setKeyOk]           = useState(false);
  const [sub, setSub]               = useState("monitor");

  // Verify key on load if already stored
  useEffect(() => {
    if (masterKey) { verifyKey(masterKey); }
  }, []); // eslint-disable-line

  async function verifyKey(k) {
    try {
      await api.get("/master/ping", { headers: masterHeaders(k) });
      setKeyOk(true);
      setKeyError("");
      sessionStorage.setItem("mc_key", k);
    } catch {
      setKeyOk(false);
      setKeyError("MASTER_KEY inválida o servidor no disponible");
      sessionStorage.removeItem("mc_key");
    }
  }

  function handleKeySubmit(e) {
    e.preventDefault();
    if (!keyInput.trim()) return;
    setMasterKey(keyInput.trim());
    verifyKey(keyInput.trim());
  }

  function handleLockout() {
    setMasterKey(""); setKeyInput(""); setKeyOk(false);
    sessionStorage.removeItem("mc_key");
  }

  if (!keyOk) {
    return (
      <div style={{ maxWidth: 440, margin: "3rem auto", padding: "2rem", border: "1px solid #e5e7eb", borderRadius: 12 }}>
        <h2 style={{ marginBottom: "0.5rem", fontSize: "1.25rem", fontWeight: 700 }}>
          🔐 Master Console
        </h2>
        <p style={{ color: "#6b7280", marginBottom: "1.5rem", fontSize: "0.875rem" }}>
          Acceso restringido — requiere MASTER_KEY del servidor.
          Solo para SuperAdmin / operaciones internas.
        </p>
        <form onSubmit={handleKeySubmit} style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
          <input
            type="password"
            placeholder="MASTER_KEY"
            value={keyInput}
            onChange={e => setKeyInput(e.target.value)}
            style={{ padding: "0.6rem 1rem", borderRadius: 8, border: "1px solid #d1d5db", fontSize: "0.95rem" }}
            autoFocus
          />
          {keyError && <div className="alert" style={{ margin: 0 }}>{keyError}</div>}
          <button type="submit" className="btn-primary">Acceder</button>
        </form>
      </div>
    );
  }

  return (
    <div style={{ padding: "0 0 2rem" }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: "1.5rem" }}>
        <div>
          <h2 className="section-title" style={{ marginBottom: "0.4rem" }}>
            🔐 Master Console
          </h2>
          <p className="hero-sub" style={{ margin: 0 }}>
            Centro de operaciones internas. Python sandbox, shell controlado, live monitoring, audit trail.
            Toda ejecución requiere MASTER_KEY explícita. Cada acción queda en audit.
          </p>
        </div>
        <button
          onClick={handleLockout}
          style={{ fontSize: "0.75rem", padding: "0.35rem 0.75rem", borderRadius: 6, border: "1px solid #e5e7eb", cursor: "pointer", color: "#6b7280" }}
        >
          🔒 Cerrar sesión
        </button>
      </div>

      <div className="tabs" style={{ marginBottom: "1.5rem" }}>
        {[
          ["monitor",     "Live Monitor"],
          ["queue",       "Jobs / Queue"],
          ["python",      "Python Runner"],
          ["shell",       "Shell Runner"],
          ["diagnostics", "Diagnóstico Tenant"],
          ["audit",       "Audit Trail"],
          ["status",      "Estado Módulos"],
        ].map(([k, l]) => (
          <button
            key={k}
            className={`tab ${sub === k ? "active" : ""}`}
            onClick={() => setSub(k)}
          >
            {l}
          </button>
        ))}
      </div>

      {sub === "monitor"     && <MonitorTab     mk={masterKey} />}
      {sub === "queue"       && <QueueTab       mk={masterKey} />}
      {sub === "python"      && <PythonTab      mk={masterKey} />}
      {sub === "shell"       && <ShellTab       mk={masterKey} />}
      {sub === "diagnostics" && <DiagnosticsTab mk={masterKey} />}
      {sub === "audit"       && <AuditTab       mk={masterKey} />}
      {sub === "status"      && <StatusTab      mk={masterKey} />}
    </div>
  );
}

// ──────────────────────────────────────────────────────────────
// Live Monitor
// ──────────────────────────────────────────────────────────────
function MonitorTab({ mk }) {
  const [data, setData]       = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr]         = useState("");

  const load = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      const { data: d } = await api.get("/master/monitor", { headers: masterHeaders(mk) });
      setData(d);
    } catch (e) { setErr(formatError(e)); }
    finally { setLoading(false); }
  }, [mk]);

  useEffect(() => { load(); }, [load]);

  if (loading && !data) return <Spinner />;
  if (err) return <Alert msg={err} />;
  if (!data) return null;

  const queueEntries = Object.entries(data.queue?.by_status || {});
  const totalAICost  = (data.ai_costs_today || []).reduce((s, r) => s + r.total_usd, 0);

  return (
    <div>
      <div style={{ display: "flex", gap: "0.75rem", marginBottom: "1.5rem", flexWrap: "wrap", alignItems: "center" }}>
        <span style={{ fontSize: "0.75rem", color: "#6b7280" }}>Actualizado: {new Date(data.ts).toLocaleTimeString()}</span>
        <button className="btn-secondary" onClick={load} disabled={loading} style={{ fontSize: "0.8rem", padding: "0.3rem 0.8rem" }}>
          {loading ? "…" : "↻ Refrescar"}
        </button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: "1rem", marginBottom: "1.5rem" }}>
        <StatCard label="DLQ hoy"         value={data.queue?.dlq_today ?? 0}  color="#ef4444" />
        <StatCard label="SLA breaches"    value={data.sla_breaches_open ?? 0} color="#f59e0b" />
        <StatCard label="Costo IA hoy"    value={`$${totalAICost.toFixed(4)}`} color="#6366f1" />
        <StatCard label="Worker HB"       value={data.worker_last_heartbeat ? new Date(data.worker_last_heartbeat).toLocaleTimeString() : "N/A"} color="#22c55e" />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem", marginBottom: "1.5rem" }}>
        <Card title="Queue por status">
          {queueEntries.length === 0 ? <Muted>Cola vacía</Muted> : (
            <table style={{ width: "100%", fontSize: "0.85rem" }}>
              <tbody>
                {queueEntries.map(([status, count]) => (
                  <tr key={status}>
                    <td style={{ paddingBottom: 4 }}><StatusBadge status={status} /></td>
                    <td style={{ textAlign: "right", fontWeight: 600 }}>{count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>

        <Card title="Costos IA hoy">
          {(data.ai_costs_today || []).length === 0 ? <Muted>Sin costos registrados</Muted> : (
            <table style={{ width: "100%", fontSize: "0.82rem" }}>
              <thead><tr style={{ color: "#6b7280" }}><th>Modelo</th><th>Calls</th><th>USD</th></tr></thead>
              <tbody>
                {(data.ai_costs_today || []).map((r, i) => (
                  <tr key={i}>
                    <td style={{ paddingBottom: 4 }}>{r.model}</td>
                    <td style={{ textAlign: "right" }}>{r.calls}</td>
                    <td style={{ textAlign: "right", fontWeight: 600 }}>${r.total_usd}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>

      <Card title="Últimos errores (10)">
        {(data.recent_errors || []).length === 0 ? <Muted>Sin errores recientes</Muted> : (
          <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
            {data.recent_errors.map((e, i) => (
              <div key={i} style={{ background: "#fef2f2", borderRadius: 6, padding: "0.5rem 0.75rem", fontSize: "0.82rem" }}>
                <span style={{ fontWeight: 600, color: "#dc2626" }}>{e.module}.{e.event}</span>
                <span style={{ color: "#6b7280", marginLeft: "0.5rem" }}>{e.tenant}</span>
                <div style={{ color: "#374151", marginTop: "0.25rem" }}>{e.error || "—"}</div>
                <div style={{ color: "#9ca3af", fontSize: "0.75rem" }}>{e.ts}</div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────
// Queue Tab
// ──────────────────────────────────────────────────────────────
function QueueTab({ mk }) {
  const [status, setStatus]   = useState("queued");
  const [jobs, setJobs]       = useState([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr]         = useState("");
  const [msg, setMsg]         = useState("");

  const load = useCallback(async () => {
    setLoading(true); setErr(""); setMsg("");
    try {
      const { data } = await api.get(`/master/queue/snapshot?status=${status}&limit=30`, { headers: masterHeaders(mk) });
      setJobs(data.jobs || []);
    } catch (e) { setErr(formatError(e)); }
    finally { setLoading(false); }
  }, [mk, status]);

  useEffect(() => { load(); }, [load]);

  async function retryJob(jobId) {
    try {
      await api.post(`/master/queue/retry/${jobId}`, {}, { headers: masterHeaders(mk) });
      setMsg(`Job ${jobId} reencolar OK`);
      load();
    } catch (e) { setErr(formatError(e)); }
  }

  async function flushDlq() {
    if (!window.confirm("¿Eliminar jobs del DLQ con >7 días? Esta acción es irreversible.")) return;
    try {
      const { data } = await api.delete("/master/queue/dlq/flush", { headers: masterHeaders(mk) });
      setMsg(`DLQ flush OK — eliminados: ${data.deleted}`);
      load();
    } catch (e) { setErr(formatError(e)); }
  }

  return (
    <div>
      <div style={{ display: "flex", gap: "0.75rem", marginBottom: "1rem", flexWrap: "wrap", alignItems: "center" }}>
        {["queued","running","retrying","dead_letter","completed","failed"].map(s => (
          <button
            key={s}
            className={`tab ${status === s ? "active" : ""}`}
            onClick={() => setStatus(s)}
            style={{ fontSize: "0.8rem", padding: "0.35rem 0.75rem" }}
          >
            {s}
          </button>
        ))}
        <button className="btn-secondary" onClick={load} disabled={loading} style={{ fontSize: "0.8rem", padding: "0.35rem 0.8rem" }}>
          {loading ? "…" : "↻"}
        </button>
        {status === "dead_letter" && (
          <button
            onClick={flushDlq}
            style={{ fontSize: "0.8rem", padding: "0.35rem 0.8rem", background: "#fee2e2", border: "1px solid #fca5a5", borderRadius: 6, cursor: "pointer", color: "#dc2626" }}
          >
            🗑 Flush DLQ &gt;7d
          </button>
        )}
      </div>
      {err && <Alert msg={err} />}
      {msg && <Success msg={msg} />}
      {jobs.length === 0 && !loading ? <Muted>Sin jobs con status "{status}"</Muted> : (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
          {jobs.map((j, i) => (
            <div key={i} style={{ background: "#f9fafb", borderRadius: 8, padding: "0.75rem 1rem", border: "1px solid #e5e7eb", fontSize: "0.82rem" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.25rem" }}>
                <span style={{ fontWeight: 600 }}>{j.job_type}</span>
                <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
                  <StatusBadge status={j.status} />
                  {(j.status === "dead_letter" || j.status === "failed") && (
                    <button
                      onClick={() => retryJob(j.job_id)}
                      style={{ fontSize: "0.75rem", padding: "0.2rem 0.6rem", borderRadius: 4, border: "1px solid #6366f1", background: "#eef2ff", cursor: "pointer", color: "#4f46e5" }}
                    >
                      ↻ Retry
                    </button>
                  )}
                </div>
              </div>
              <div style={{ color: "#6b7280" }}>tenant: {j.tenant_id} · intentos: {j.attempts ?? 0} · prioridad: {j.priority}</div>
              <div style={{ color: "#9ca3af" }}>run_at: {j.run_at} · job_id: {j.job_id}</div>
              {j.error && <div style={{ color: "#dc2626", marginTop: "0.25rem" }}>Error: {j.error}</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ──────────────────────────────────────────────────────────────
// Python Runner
// ──────────────────────────────────────────────────────────────
function PythonTab({ mk }) {
  const [code, setCode]       = useState("# Sandbox Python — builtins peligrosos deshabilitados\n# No hay acceso a os, sys, open, __import__\n\nresult = sum(range(10))\nprint(f'Suma 0-9 = {result}')");
  const [timeout, setTimeout] = useState(10);
  const [res, setRes]         = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr]         = useState("");

  async function run(e) {
    e.preventDefault();
    if (!window.confirm("¿Ejecutar este código Python en el servidor?")) return;
    setLoading(true); setErr(""); setRes(null);
    try {
      const { data } = await api.post("/master/python/run", { code, timeout_sec: timeout }, { headers: masterHeaders(mk) });
      setRes(data);
    } catch (ex) { setErr(formatError(ex)); }
    finally { setLoading(false); }
  }

  return (
    <div>
      <div style={{ background: "#fef3c7", border: "1px solid #fde68a", borderRadius: 8, padding: "0.75rem 1rem", marginBottom: "1rem", fontSize: "0.82rem", color: "#92400e" }}>
        ⚠️ <strong>Sandbox restringido.</strong> Sin acceso a os, sys, open, socket, subprocess.
        Toda ejecución queda en audit trail. Se requiere confirmación explícita.
      </div>
      <form onSubmit={run}>
        <textarea
          value={code}
          onChange={e => setCode(e.target.value)}
          rows={12}
          style={{ width: "100%", fontFamily: "monospace", fontSize: "0.85rem", padding: "0.75rem", border: "1px solid #d1d5db", borderRadius: 8, resize: "vertical", boxSizing: "border-box" }}
        />
        <div style={{ display: "flex", gap: "0.75rem", marginTop: "0.5rem", alignItems: "center" }}>
          <label style={{ fontSize: "0.82rem", color: "#6b7280" }}>
            Timeout:
            <input
              type="number" min={1} max={60} value={timeout}
              onChange={e => setTimeout(Number(e.target.value))}
              style={{ width: 60, marginLeft: "0.4rem", padding: "0.3rem 0.5rem", borderRadius: 4, border: "1px solid #d1d5db" }}
            />s
          </label>
          <button type="submit" className="btn-primary" disabled={loading} style={{ minWidth: 100 }}>
            {loading ? "Ejecutando…" : "▶ Ejecutar"}
          </button>
        </div>
      </form>

      {err && <Alert msg={err} />}
      {res && (
        <div style={{ marginTop: "1rem" }}>
          <div style={{ display: "flex", gap: "0.75rem", marginBottom: "0.5rem" }}>
            <span style={{ fontSize: "0.82rem", fontWeight: 600, color: res.ok ? "#16a34a" : "#dc2626" }}>
              {res.ok ? "✅ OK" : "❌ Error"} — {res.elapsed_ms}ms
            </span>
          </div>
          {res.stdout && <pre style={preStyle}>{res.stdout}</pre>}
          {res.stderr && <pre style={{ ...preStyle, background: "#fef2f2", color: "#dc2626" }}>{res.stderr}</pre>}
          {res.error  && <pre style={{ ...preStyle, background: "#fef2f2", color: "#dc2626" }}>{res.error}</pre>}
          {res.result && <pre style={preStyle}>→ result = {res.result}</pre>}
        </div>
      )}
    </div>
  );
}

// ──────────────────────────────────────────────────────────────
// Shell Runner
// ──────────────────────────────────────────────────────────────
function ShellTab({ mk }) {
  const [cmd, setCmd]         = useState("");
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr]         = useState("");
  const bottomRef             = useRef(null);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [history]);

  async function run(e) {
    e.preventDefault();
    if (!cmd.trim()) return;
    if (!window.confirm(`¿Ejecutar en el servidor?\n\n$ ${cmd}`)) return;
    setLoading(true); setErr("");
    try {
      const { data } = await api.post("/master/shell/run", { command: cmd }, { headers: masterHeaders(mk) });
      setHistory(h => [...h, { cmd, ...data, ts: new Date().toLocaleTimeString() }]);
      setCmd("");
    } catch (ex) { setErr(formatError(ex)); }
    finally { setLoading(false); }
  }

  return (
    <div>
      <div style={{ background: "#fef3c7", border: "1px solid #fde68a", borderRadius: 8, padding: "0.75rem 1rem", marginBottom: "1rem", fontSize: "0.82rem", color: "#92400e" }}>
        ⚠️ <strong>Shell real.</strong> Blocklist activa (rm -rf /, mkfs, shutdown, etc.).
        Timeout 30s. Cada comando queda en audit trail. Se requiere confirmación.
      </div>
      {history.length > 0 && (
        <div style={{ background: "#111827", borderRadius: 8, padding: "1rem", marginBottom: "1rem", maxHeight: 400, overflowY: "auto", fontFamily: "monospace", fontSize: "0.82rem" }}>
          {history.map((h, i) => (
            <div key={i} style={{ marginBottom: "0.75rem" }}>
              <div style={{ color: "#34d399" }}>$ {h.cmd} <span style={{ color: "#6b7280", fontSize: "0.75rem" }}>({h.ts})</span></div>
              {h.stdout && <div style={{ color: "#f3f4f6", whiteSpace: "pre-wrap" }}>{h.stdout}</div>}
              {h.stderr && <div style={{ color: "#fca5a5", whiteSpace: "pre-wrap" }}>{h.stderr}</div>}
              {h.error  && <div style={{ color: "#fca5a5" }}>Error: {h.error}</div>}
              <div style={{ color: h.ok ? "#34d399" : "#f87171", fontSize: "0.75rem" }}>
                exit_code={h.exit_code} · {h.elapsed_ms}ms
              </div>
            </div>
          ))}
          <div ref={bottomRef} />
        </div>
      )}
      {err && <Alert msg={err} />}
      <form onSubmit={run} style={{ display: "flex", gap: "0.5rem" }}>
        <input
          value={cmd}
          onChange={e => setCmd(e.target.value)}
          placeholder="$ comando shell..."
          style={{ flex: 1, padding: "0.6rem 1rem", fontFamily: "monospace", borderRadius: 8, border: "1px solid #d1d5db", fontSize: "0.9rem" }}
          disabled={loading}
        />
        <button type="submit" className="btn-primary" disabled={loading || !cmd.trim()}>
          {loading ? "…" : "▶"}
        </button>
      </form>
      <button onClick={() => setHistory([])} style={{ fontSize: "0.75rem", color: "#9ca3af", background: "none", border: "none", cursor: "pointer", marginTop: "0.4rem" }}>
        Limpiar historial
      </button>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────
// Tenant Diagnostics
// ──────────────────────────────────────────────────────────────
function DiagnosticsTab({ mk }) {
  const [tenantId, setTenantId] = useState("");
  const [data, setData]         = useState(null);
  const [loading, setLoading]   = useState(false);
  const [err, setErr]           = useState("");

  async function load(e) {
    e.preventDefault();
    if (!tenantId.trim()) return;
    setLoading(true); setErr(""); setData(null);
    try {
      const { data: d } = await api.get(`/master/tenant/${tenantId.trim()}/diagnostics`, { headers: masterHeaders(mk) });
      setData(d);
    } catch (ex) { setErr(formatError(ex)); }
    finally { setLoading(false); }
  }

  return (
    <div>
      <form onSubmit={load} style={{ display: "flex", gap: "0.5rem", marginBottom: "1.5rem" }}>
        <input
          value={tenantId}
          onChange={e => setTenantId(e.target.value)}
          placeholder="tenant_id..."
          style={{ flex: 1, padding: "0.6rem 1rem", borderRadius: 8, border: "1px solid #d1d5db" }}
        />
        <button type="submit" className="btn-primary" disabled={loading}>{loading ? "…" : "Diagnosticar"}</button>
      </form>
      {err && <Alert msg={err} />}
      {data && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
          <Card title="Jobs">
            {Object.entries(data.jobs?.by_status || {}).map(([s, c]) => (
              <div key={s} style={{ display: "flex", justifyContent: "space-between", fontSize: "0.85rem", padding: "0.2rem 0" }}>
                <StatusBadge status={s} /> <strong>{c}</strong>
              </div>
            ))}
          </Card>
          <Card title="Tickets">
            <div style={{ fontSize: "0.85rem" }}>Abiertos: <strong>{data.tickets?.open}</strong></div>
            <div style={{ fontSize: "0.85rem", color: data.tickets?.sla_breached > 0 ? "#ef4444" : undefined }}>SLA breach: <strong>{data.tickets?.sla_breached}</strong></div>
          </Card>
          <Card title="Costos IA 7d">
            {(data.ai_costs_7d || []).length === 0 ? <Muted>Sin registros</Muted> : (
              data.ai_costs_7d.map((r, i) => (
                <div key={i} style={{ fontSize: "0.82rem", display: "flex", justifyContent: "space-between" }}>
                  <span>{r.model}</span> <strong>${r.usd} ({r.calls} calls)</strong>
                </div>
              ))
            )}
          </Card>
          <Card title="Errores 24h">
            {(data.errors_24h || []).length === 0 ? <Muted>Sin errores</Muted> : (
              data.errors_24h.slice(0, 8).map((e, i) => (
                <div key={i} style={{ fontSize: "0.8rem", borderBottom: "1px solid #f3f4f6", paddingBottom: "0.3rem", marginBottom: "0.3rem" }}>
                  <span style={{ fontWeight: 600, color: "#dc2626" }}>{e.module}</span>
                  <div style={{ color: "#6b7280" }}>{e.error || "—"}</div>
                </div>
              ))
            )}
          </Card>
        </div>
      )}
    </div>
  );
}

// ──────────────────────────────────────────────────────────────
// Audit Trail
// ──────────────────────────────────────────────────────────────
function AuditTab({ mk }) {
  const [entries, setEntries]   = useState([]);
  const [filter, setFilter]     = useState("");
  const [loading, setLoading]   = useState(false);
  const [err, setErr]           = useState("");

  const load = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      const url = `/master/audit?limit=50${filter ? `&action=${filter}` : ""}`;
      const { data } = await api.get(url, { headers: masterHeaders(mk) });
      setEntries(data.entries || []);
    } catch (e) { setErr(formatError(e)); }
    finally { setLoading(false); }
  }, [mk, filter]);

  useEffect(() => { load(); }, [load]);

  return (
    <div>
      <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem", alignItems: "center" }}>
        <select value={filter} onChange={e => setFilter(e.target.value)} style={{ padding: "0.4rem 0.75rem", borderRadius: 6, border: "1px solid #d1d5db", fontSize: "0.85rem" }}>
          <option value="">Todas las acciones</option>
          {["ping","python_run","shell_run","deploy_trigger","docker","ssl","system_metrics","file_read","ai_engineer","live_monitor","queue_retry","dlq_flush","tenant_diagnostics"].map(a => (
            <option key={a} value={a}>{a}</option>
          ))}
        </select>
        <button className="btn-secondary" onClick={load} disabled={loading} style={{ fontSize: "0.8rem", padding: "0.35rem 0.8rem" }}>
          {loading ? "…" : "↻"}
        </button>
      </div>
      {err && <Alert msg={err} />}
      {entries.length === 0 && !loading ? <Muted>Sin entradas de audit</Muted> : (
        <table style={{ width: "100%", fontSize: "0.82rem", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ borderBottom: "2px solid #e5e7eb", textAlign: "left" }}>
              <th style={{ padding: "0.4rem 0.5rem" }}>Acción</th>
              <th style={{ padding: "0.4rem 0.5rem" }}>IP</th>
              <th style={{ padding: "0.4rem 0.5rem" }}>ms</th>
              <th style={{ padding: "0.4rem 0.5rem" }}>Resultado</th>
              <th style={{ padding: "0.4rem 0.5rem" }}>Timestamp</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e, i) => (
              <tr key={i} style={{ borderBottom: "1px solid #f3f4f6" }}>
                <td style={{ padding: "0.4rem 0.5rem", fontWeight: 600 }}>{e.action}</td>
                <td style={{ padding: "0.4rem 0.5rem", color: "#6b7280" }}>{e.ip}</td>
                <td style={{ padding: "0.4rem 0.5rem" }}>{e.duration_ms}</td>
                <td style={{ padding: "0.4rem 0.5rem" }}>
                  <span style={{ color: e.result_ok ? "#16a34a" : "#dc2626" }}>{e.result_ok ? "OK" : "FAIL"}</span>
                </td>
                <td style={{ padding: "0.4rem 0.5rem", color: "#9ca3af" }}>{e.ts?.replace("T", " ").slice(0, 19)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ──────────────────────────────────────────────────────────────
// Status — estado módulos
// ──────────────────────────────────────────────────────────────
function StatusTab({ mk }) {
  const [data, setData]       = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr]         = useState("");

  useEffect(() => {
    setLoading(true);
    api.get("/master/status", { headers: masterHeaders(mk) })
      .then(({ data: d }) => setData(d))
      .catch(e => setErr(formatError(e)))
      .finally(() => setLoading(false));
  }, [mk]);

  if (loading) return <Spinner />;
  if (err) return <Alert msg={err} />;
  if (!data) return null;

  const statusColor = { REAL: "#16a34a", PARCIAL: "#f59e0b", STUB: "#6b7280", MOCK: "#9ca3af" };

  return (
    <div>
      {(data.missing_env_vars || []).length > 0 && (
        <div style={{ background: "#fef3c7", border: "1px solid #fde68a", borderRadius: 8, padding: "0.75rem 1rem", marginBottom: "1rem", fontSize: "0.82rem" }}>
          ⚠️ Variables de entorno faltantes: <strong>{data.missing_env_vars.join(", ")}</strong>
        </div>
      )}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: "0.5rem" }}>
        {Object.entries(data.modules || {}).map(([mod, status]) => {
          const level = ["REAL","PARCIAL","STUB","MOCK"].find(l => status.startsWith(l)) || "?";
          return (
            <div key={mod} style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", background: "#f9fafb", borderRadius: 8, padding: "0.6rem 0.75rem", border: "1px solid #e5e7eb", fontSize: "0.82rem" }}>
              <span style={{ fontWeight: 600 }}>{mod}</span>
              <div style={{ textAlign: "right" }}>
                <span style={{ background: statusColor[level] || "#6b7280", color: "white", borderRadius: 4, padding: "0.15rem 0.4rem", fontSize: "0.72rem", fontWeight: 700 }}>{level}</span>
                {status.length > level.length && <div style={{ color: "#6b7280", fontSize: "0.72rem", marginTop: "0.2rem" }}>{status.slice(level.length + 3)}</div>}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────
// Shared helpers
// ──────────────────────────────────────────────────────────────
const preStyle = {
  background: "#111827", color: "#f3f4f6", borderRadius: 8,
  padding: "0.75rem 1rem", fontFamily: "monospace",
  fontSize: "0.82rem", whiteSpace: "pre-wrap", overflowX: "auto",
  maxHeight: 300, overflowY: "auto", margin: 0,
};

function Card({ title, children }) {
  return (
    <div style={{ border: "1px solid #e5e7eb", borderRadius: 10, padding: "1rem" }}>
      {title && <div style={{ fontWeight: 700, marginBottom: "0.75rem", fontSize: "0.9rem" }}>{title}</div>}
      {children}
    </div>
  );
}

function StatCard({ label, value, color }) {
  return (
    <div style={{ border: "1px solid #e5e7eb", borderRadius: 10, padding: "1rem", textAlign: "center" }}>
      <div style={{ fontSize: "1.5rem", fontWeight: 700, color: color || "#1f2937" }}>{value}</div>
      <div style={{ fontSize: "0.78rem", color: "#6b7280", marginTop: "0.25rem" }}>{label}</div>
    </div>
  );
}

function StatusBadge({ status }) {
  const colors = {
    queued: "#6366f1", running: "#f59e0b", retrying: "#f97316",
    dead_letter: "#ef4444", completed: "#22c55e", failed: "#dc2626",
    published: "#22c55e", processing: "#f59e0b", failed_post: "#ef4444",
  };
  return (
    <span style={{
      background: colors[status] || "#e5e7eb", color: colors[status] ? "white" : "#374151",
      borderRadius: 4, padding: "0.15rem 0.4rem", fontSize: "0.72rem", fontWeight: 600,
    }}>
      {status}
    </span>
  );
}

function Alert({ msg }) {
  return <div className="alert" style={{ marginBottom: "1rem" }}>{msg}</div>;
}

function Success({ msg }) {
  return <div className="success" style={{ marginBottom: "1rem" }}>{msg}</div>;
}

function Muted({ children }) {
  return <div style={{ color: "#9ca3af", fontSize: "0.85rem", padding: "0.5rem 0" }}>{children}</div>;
}

function Spinner() {
  return <div style={{ color: "#6b7280", padding: "2rem", textAlign: "center" }}>Cargando…</div>;
}
