/**
 * DevOpsConsole.js - AI Operating Center
 *
 * Tab hidden accesible via #/devops desde AdminDashboard.
 * Convive con toda la infraestructura existente sin reemplazarla.
 *
 * Reutiliza:
 *   - api, formatError desde ../api (cliente HTTP existente)
 *   - useAuth desde ../AuthContext (auth existente)
 *   - Endpoints /api/devops/* del nuevo módulo devops_ai.py
 *
 * NO reemplaza ni copia:
 *   - ProposalsTab.js (ese maneja propuestas de agentes, este maneja DevOps)
 *   - BossConsole.js, AgentBuilder.js, SuperAdminPanel.js
 *   - Ningún componente existente
 */

import { useEffect, useState, useRef, useCallback } from "react";
import { api, formatError } from "../api";
import { useAuth } from "../AuthContext";

const RISK_COLOR = { low: "#22c55e", medium: "#f59e0b", high: "#ef4444" };
const STATUS_COLOR = {
  pending:  "#6366f1",
  applying: "#f59e0b",
  applied:  "#22c55e",
  failed:   "#ef4444",
  rejected: "#6b7280",
};

// ============================================================
// Root
// ============================================================
export default function DevOpsConsole() {
  const { user } = useAuth();
  const [sub, setSub] = useState("chat");

  return (
    <div style={{ padding: "0 0 2rem" }}>
      <div style={{ marginBottom: "1.5rem" }}>
        <h2 className="section-title" style={{ marginBottom: "0.4rem" }}>
          AI Operating Center
        </h2>
        <p className="hero-sub" style={{ margin: 0 }}>
          Propone cambios en lenguaje natural → revisa el diff → aprueba → rollback automático disponible.
          No modifica producción sin checkpoint previo.
        </p>
      </div>

      <div className="tabs" style={{ marginBottom: "1.5rem" }}>
        {[
          ["chat",        "Chat AI"],
          ["proposals",   "Propuestas DevOps"],
          ["checkpoints", "Checkpoints"],
          ["status",      "Estado del sistema"],
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

      {sub === "chat"        && <ChatTab />}
      {sub === "proposals"   && <ProposalsTab />}
      {sub === "checkpoints" && <CheckpointsTab />}
      {sub === "status"      && <StatusTab />}
    </div>
  );
}

// ============================================================
// ChatTab — NL → análisis → propuesta → aprobación
// ============================================================
function ChatTab() {
  const [input, setInput]       = useState("");
  const [loading, setLoading]   = useState(false);
  const [proposal, setProposal] = useState(null);
  const [err, setErr]           = useState("");
  const [msg, setMsg]           = useState("");
  const [busy, setBusy]         = useState("");
  const textRef = useRef(null);

  const analyze = async () => {
    if (!input.trim()) return;
    setLoading(true); setErr(""); setProposal(null); setMsg("");
    try {
      const { data } = await api.post("/devops/analyze", { request: input });
      setProposal(data);
    } catch (e) {
      setErr(formatError(e));
    } finally {
      setLoading(false);
    }
  };

  const act = async (action) => {
    if (!proposal) return;
    setBusy(action); setErr(""); setMsg("");
    try {
      if (action === "approve") {
        const { data } = await api.post(`/devops/proposals/${proposal.id}/approve`);
        setMsg(data.ok
          ? `Cambios aplicados. Checkpoint: ${data.checkpoint_id}`
          : `Aprobado pero con errores: ${JSON.stringify(data.error)}`);
        setProposal((p) => ({ ...p, status: data.ok ? "applied" : "failed" }));
      } else {
        await api.post(`/devops/proposals/${proposal.id}/reject`, { reason: "" });
        setMsg("Propuesta rechazada.");
        setProposal((p) => ({ ...p, status: "rejected" }));
      }
    } catch (e) {
      setErr(formatError(e));
    } finally {
      setBusy("");
    }
  };

  const handleKey = (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) analyze();
  };

  return (
    <div>
      {/* Input */}
      <div className="form-card" style={{ marginBottom: "1rem" }}>
        <label style={{ display: "block", marginBottom: "0.5rem", fontWeight: 600 }}>
          Describe el cambio que quieres hacer:
        </label>
        <textarea
          ref={textRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKey}
          rows={3}
          style={{
            width: "100%", boxSizing: "border-box", resize: "vertical",
            padding: "0.6rem 0.8rem", borderRadius: 8,
            border: "1px solid var(--border, #e2e8f0)",
            background: "var(--bg-card, #fff)", color: "var(--text, #1e293b)",
            fontFamily: "inherit", fontSize: "0.95rem",
          }}
          placeholder={'Ej: "mejora el onboarding" · "agrega validación al builder" · "optimiza el login" — Ctrl+Enter para enviar'}
          disabled={loading}
        />
        <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.5rem", alignItems: "center" }}>
          <button className="login-btn" onClick={analyze} disabled={loading || !input.trim()}>
            {loading ? "Analizando con IA..." : "Analizar y generar propuesta"}
          </button>
          {proposal && (
            <span style={{ fontSize: "0.82rem", color: "var(--text-muted, #64748b)" }}>
              Propuesta generada — revisa abajo
            </span>
          )}
        </div>
      </div>

      {err && <div className="alert" style={{ marginBottom: "1rem" }}>{err}</div>}
      {msg && <div className="success" style={{ marginBottom: "1rem" }}>{msg}</div>}

      {/* Propuesta generada */}
      {proposal && <ProposalDetail proposal={proposal} onAct={act} busy={busy} />}
    </div>
  );
}

// ============================================================
// ProposalsTab — lista de propuestas DevOps pasadas
// ============================================================
function ProposalsTab() {
  const [items, setItems]     = useState([]);
  const [selected, setSelected] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr]         = useState("");
  const [msg, setMsg]         = useState("");
  const [busy, setBusy]       = useState("");

  const load = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      const { data } = await api.get("/devops/proposals");
      setItems(data.proposals || []);
    } catch (e) {
      setErr(formatError(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const loadDetail = async (pid) => {
    try {
      const { data } = await api.get(`/devops/proposals/${pid}`);
      setSelected(data);
    } catch (e) {
      setErr(formatError(e));
    }
  };

  const act = async (pid, action) => {
    setBusy(pid + action); setErr(""); setMsg("");
    try {
      if (action === "approve") {
        const { data } = await api.post(`/devops/proposals/${pid}/approve`);
        setMsg(data.ok ? `Aplicado. Checkpoint: ${data.checkpoint_id}` : `Falló: ${data.error}`);
      } else {
        await api.post(`/devops/proposals/${pid}/reject`, { reason: "" });
        setMsg("Rechazado.");
      }
      await load();
      setSelected(null);
    } catch (e) {
      setErr(formatError(e));
    } finally {
      setBusy("");
    }
  };

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
        <h3 style={{ margin: 0 }}>Propuestas DevOps</h3>
        <button className="tab" onClick={load}>Actualizar</button>
      </div>

      {err && <div className="alert">{err}</div>}
      {msg && <div className="success">{msg}</div>}

      {loading ? (
        <div className="empty">Cargando...</div>
      ) : items.length === 0 ? (
        <div className="empty">Sin propuestas DevOps todavía. Usa el tab Chat AI para generar una.</div>
      ) : (
        <div>
          {/* Lista resumida */}
          {!selected && (
            <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
              {items.map((p) => (
                <div
                  key={p.id}
                  className="proposal-card"
                  style={{ cursor: "pointer" }}
                  onClick={() => loadDetail(p.id)}
                >
                  <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "center" }}>
                    <span className="chip" style={{ background: STATUS_COLOR[p.status] || "#6b7280", color: "#fff" }}>
                      {p.status}
                    </span>
                    <span className="chip" style={{ background: RISK_COLOR[p.risk] || "#6b7280", color: "#fff" }}>
                      riesgo: {p.risk}
                    </span>
                    <span style={{ fontWeight: 600 }}>{p.request?.slice(0, 80)}</span>
                    <span style={{ marginLeft: "auto", fontSize: "0.8rem", color: "var(--text-muted, #64748b)" }}>
                      {p.created_at?.slice(0, 16).replace("T", " ")}
                    </span>
                  </div>
                  {p.analysis && (
                    <p style={{ margin: "0.4rem 0 0", fontSize: "0.85rem", color: "var(--text-muted, #64748b)" }}>
                      {p.analysis}
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Detalle */}
          {selected && (
            <div>
              <button className="tab" onClick={() => setSelected(null)} style={{ marginBottom: "1rem" }}>
                &larr; Volver a la lista
              </button>
              <ProposalDetail
                proposal={selected}
                onAct={(action) => act(selected.id, action)}
                busy={busy}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ============================================================
// ProposalDetail — shared entre ChatTab y ProposalsTab
// ============================================================
function ProposalDetail({ proposal: p, onAct, busy }) {
  const [expandedFile, setExpandedFile] = useState(null);
  const isPending = p.status === "pending";

  return (
    <div className="form-card">
      {/* Header */}
      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginBottom: "0.8rem" }}>
        <span className="chip" style={{ background: STATUS_COLOR[p.status] || "#6b7280", color: "#fff" }}>
          {p.status}
        </span>
        <span className="chip" style={{ background: RISK_COLOR[p.risk] || "#6b7280", color: "#fff" }}>
          riesgo {p.risk}
        </span>
        {p.requires_build && (
          <span className="chip" style={{ background: "#6366f1", color: "#fff" }}>requiere build frontend</span>
        )}
        {(p.requires_restart || []).map((s) => (
          <span key={s} className="chip" style={{ background: "#374151", color: "#fff" }}>restart {s}</span>
        ))}
      </div>

      <p style={{ fontWeight: 600, margin: "0 0 0.4rem" }}>{p.request}</p>
      {p.analysis && (
        <p style={{ fontSize: "0.88rem", color: "var(--text-muted, #64748b)", margin: "0 0 0.8rem" }}>
          {p.analysis}
        </p>
      )}

      {/* Riesgo y rollback */}
      {p.risk_detail && (
        <div style={{
          padding: "0.5rem 0.75rem", borderRadius: 6, marginBottom: "0.8rem",
          background: `${RISK_COLOR[p.risk]}18`,
          border: `1px solid ${RISK_COLOR[p.risk]}40`,
          fontSize: "0.85rem",
        }}>
          <strong>Riesgo:</strong> {p.risk_detail}
        </div>
      )}
      {p.rollback_plan && (
        <div style={{
          padding: "0.5rem 0.75rem", borderRadius: 6, marginBottom: "1rem",
          background: "rgba(99,102,241,0.06)", border: "1px solid rgba(99,102,241,0.2)",
          fontSize: "0.85rem",
        }}>
          <strong>Rollback:</strong> {p.rollback_plan}
        </div>
      )}

      {/* Archivos afectados + diffs */}
      {(p.changes || []).length > 0 && (
        <div style={{ marginBottom: "1rem" }}>
          <strong style={{ display: "block", marginBottom: "0.5rem" }}>
            Archivos afectados ({p.changes.length}):
          </strong>
          {p.changes.map((ch, i) => (
            <div key={i} style={{ marginBottom: "0.5rem" }}>
              <button
                className="tab"
                style={{ width: "100%", textAlign: "left", fontFamily: "monospace", fontSize: "0.82rem" }}
                onClick={() => setExpandedFile(expandedFile === i ? null : i)}
              >
                {expandedFile === i ? "▼" : "▶"} {ch.action === "create" ? "[NUEVO]" : "[MODIF]"} {ch.file}
              </button>
              {expandedFile === i && ch.diff && (
                <DiffViewer diff={ch.diff} />
              )}
              {expandedFile === i && !ch.diff && ch.new_content && (
                <pre style={{
                  background: "var(--bg-code, #0f172a)", color: "#e2e8f0",
                  padding: "0.75rem", borderRadius: "0 0 6px 6px",
                  fontSize: "0.76rem", overflow: "auto", maxHeight: 300,
                  margin: 0,
                }}>
                  {ch.new_content.slice(0, 3000)}
                </pre>
              )}
              {expandedFile === i && ch.rationale && (
                <p style={{
                  fontSize: "0.82rem", color: "var(--text-muted, #64748b)",
                  margin: "0.3rem 0 0", padding: "0 0.25rem",
                }}>
                  Motivo: {ch.rationale}
                </p>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Log de ejecución si ya fue procesada */}
      {p.apply_log && p.apply_log.length > 0 && (
        <details style={{ marginBottom: "1rem" }}>
          <summary style={{ cursor: "pointer", fontWeight: 600, fontSize: "0.88rem" }}>
            Log de ejecución ({p.apply_log.length} pasos)
          </summary>
          <div style={{ marginTop: "0.5rem" }}>
            {p.apply_log.map((l, i) => (
              <div key={i} style={{
                display: "flex", gap: "0.5rem", padding: "0.25rem 0",
                fontSize: "0.82rem", borderBottom: "1px solid var(--border, #e2e8f0)",
              }}>
                <span>{l.ok ? "✅" : "❌"}</span>
                <span style={{ fontFamily: "monospace" }}>{l.step}</span>
                {l.error && <span style={{ color: "#ef4444" }}>{l.error}</span>}
              </div>
            ))}
          </div>
        </details>
      )}

      {/* Checkpoint ID si existe */}
      {p.checkpoint_id && (
        <p style={{ fontSize: "0.82rem", color: "var(--text-muted, #64748b)", marginBottom: "0.8rem" }}>
          Checkpoint: <code>{p.checkpoint_id}</code>
        </p>
      )}

      {/* Acciones */}
      {isPending && (
        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
          <button
            className="login-btn"
            onClick={() => onAct("approve")}
            disabled={!!busy}
            style={{ background: "#22c55e", borderColor: "#22c55e" }}
          >
            {busy === "approve" ? "Aplicando..." : "APROBAR y ejecutar"}
          </button>
          <button
            className="tab"
            onClick={() => onAct("reject")}
            disabled={!!busy}
            style={{ color: "#ef4444", borderColor: "#ef4444" }}
          >
            {busy === "reject" ? "Rechazando..." : "Rechazar"}
          </button>
          <span style={{ fontSize: "0.8rem", color: "var(--text-muted, #64748b)", alignSelf: "center" }}>
            Se crea checkpoint automático antes de aplicar cualquier cambio
          </span>
        </div>
      )}
    </div>
  );
}

// ============================================================
// DiffViewer — renderiza unified diff con colores
// ============================================================
function DiffViewer({ diff }) {
  const lines = diff.split("\n");
  return (
    <pre style={{
      background: "var(--bg-code, #0f172a)",
      padding: "0.75rem", borderRadius: "0 0 6px 6px",
      fontSize: "0.74rem", overflow: "auto", maxHeight: 350,
      margin: 0, lineHeight: 1.5,
    }}>
      {lines.map((line, i) => {
        let color = "#94a3b8";
        if (line.startsWith("+") && !line.startsWith("+++")) color = "#4ade80";
        else if (line.startsWith("-") && !line.startsWith("---")) color = "#f87171";
        else if (line.startsWith("@@")) color = "#60a5fa";
        return (
          <span key={i} style={{ display: "block", color }}>
            {line || " "}
          </span>
        );
      })}
    </pre>
  );
}

// ============================================================
// CheckpointsTab — historial de snapshots + rollback
// ============================================================
function CheckpointsTab() {
  const [items, setItems]   = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr]       = useState("");
  const [msg, setMsg]       = useState("");
  const [busy, setBusy]     = useState("");
  const [confirmRollback, setConfirmRollback] = useState(null);

  const load = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      const { data } = await api.get("/devops/checkpoints");
      setItems(data.checkpoints || []);
    } catch (e) {
      setErr(formatError(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const rollback = async (cid) => {
    setBusy(cid); setErr(""); setMsg("");
    try {
      const { data } = await api.post(`/devops/checkpoints/${cid}/rollback`);
      if (data.ok) {
        setMsg(`Rollback completado. Restaurados: ${data.restored?.join(", ") || "archivos del checkpoint"}`);
      } else {
        setErr(`Rollback con errores: ${(data.errors || []).join("; ")}`);
      }
      setConfirmRollback(null);
      await load();
    } catch (e) {
      setErr(formatError(e));
    } finally {
      setBusy("");
    }
  };

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
        <h3 style={{ margin: 0 }}>Checkpoints de rollback</h3>
        <button className="tab" onClick={load}>Actualizar</button>
      </div>

      <div style={{
        padding: "0.6rem 0.9rem", borderRadius: 8, marginBottom: "1rem",
        background: "rgba(99,102,241,0.06)", border: "1px solid rgba(99,102,241,0.2)",
        fontSize: "0.85rem",
      }}>
        Cada vez que apruebas una propuesta, el sistema crea automáticamente un checkpoint
        antes de aplicar cualquier cambio. Puedes restaurar cualquier punto anterior desde aquí.
      </div>

      {err && <div className="alert">{err}</div>}
      {msg && <div className="success">{msg}</div>}

      {loading ? (
        <div className="empty">Cargando...</div>
      ) : items.length === 0 ? (
        <div className="empty">Sin checkpoints todavía. Se crean automáticamente al aprobar propuestas.</div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
          {items.map((c) => (
            <div key={c.id} className="proposal-card">
              <div style={{ display: "flex", gap: "0.75rem", alignItems: "flex-start", flexWrap: "wrap" }}>
                <div style={{ flex: 1 }}>
                  <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
                    <code style={{ fontSize: "0.78rem", color: "#6366f1" }}>{c.id}</code>
                    {c.rolled_back_at && (
                      <span className="chip" style={{ background: "#6b7280", color: "#fff", fontSize: "0.72rem" }}>
                        usado para rollback
                      </span>
                    )}
                  </div>
                  <p style={{ margin: "0.3rem 0 0.2rem", fontWeight: 500 }}>{c.description}</p>
                  <p style={{ margin: 0, fontSize: "0.82rem", color: "var(--text-muted, #64748b)" }}>
                    {c.created_at?.slice(0, 16).replace("T", " ")}
                    {c.files_backed_up?.length > 0 && ` · ${c.files_backed_up.length} archivos en backup`}
                  </p>
                </div>

                <div style={{ display: "flex", flexDirection: "column", gap: "0.4rem", alignItems: "flex-end" }}>
                  {confirmRollback === c.id ? (
                    <div style={{ display: "flex", gap: "0.4rem" }}>
                      <button
                        className="login-btn"
                        onClick={() => rollback(c.id)}
                        disabled={!!busy}
                        style={{ background: "#ef4444", borderColor: "#ef4444", padding: "0.3rem 0.7rem" }}
                      >
                        {busy === c.id ? "Restaurando..." : "Confirmar rollback"}
                      </button>
                      <button
                        className="tab"
                        onClick={() => setConfirmRollback(null)}
                        style={{ padding: "0.3rem 0.7rem" }}
                      >
                        Cancelar
                      </button>
                    </div>
                  ) : (
                    <button
                      className="tab"
                      onClick={() => setConfirmRollback(c.id)}
                      disabled={!!busy}
                      style={{ color: "#ef4444", borderColor: "#ef4444", padding: "0.3rem 0.7rem" }}
                    >
                      DESHACER a este punto
                    </button>
                  )}
                </div>
              </div>

              {/* Archivos del backup */}
              {c.files_backed_up?.length > 0 && (
                <details style={{ marginTop: "0.5rem" }}>
                  <summary style={{ cursor: "pointer", fontSize: "0.82rem", color: "var(--text-muted, #64748b)" }}>
                    Ver archivos en el backup
                  </summary>
                  <div style={{ marginTop: "0.3rem", display: "flex", gap: "0.3rem", flexWrap: "wrap" }}>
                    {c.files_backed_up.map((f) => (
                      <code key={f} style={{
                        fontSize: "0.74rem", padding: "0.1rem 0.4rem",
                        background: "var(--bg-code, #0f172a)", color: "#94a3b8",
                        borderRadius: 4,
                      }}>
                        {f}
                      </code>
                    ))}
                  </div>
                </details>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ============================================================
// StatusTab — estado del sistema (git, docker, disco)
// ============================================================
function StatusTab() {
  const [data, setData]     = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr]       = useState("");

  const load = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      const { data: r } = await api.get("/devops/status");
      setData(r.status);
    } catch (e) {
      setErr(formatError(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
        <h3 style={{ margin: 0 }}>Estado del sistema</h3>
        <button className="tab" onClick={load} disabled={loading}>
          {loading ? "Cargando..." : "Actualizar"}
        </button>
      </div>

      {err && <div className="alert">{err}</div>}

      {data && (
        <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
          <StatusBlock title="Git status" content={data.git_status} />
          <StatusBlock title="Git log (últimos 10)" content={data.git_log} />
          <StatusBlock title="Contenedores Docker" content={data.containers} />
          <StatusBlock title="Disco (/opt)" content={data.disk} />
        </div>
      )}

      {!data && !loading && !err && (
        <div className="empty">Sin datos. Haz click en Actualizar.</div>
      )}
    </div>
  );
}

function StatusBlock({ title, content }) {
  return (
    <div className="form-card" style={{ padding: "0.75rem 1rem" }}>
      <strong style={{ display: "block", marginBottom: "0.4rem", fontSize: "0.88rem" }}>{title}</strong>
      <pre style={{
        background: "var(--bg-code, #0f172a)", color: "#e2e8f0",
        padding: "0.6rem 0.75rem", borderRadius: 6,
        fontSize: "0.78rem", margin: 0, overflow: "auto",
        maxHeight: 200, whiteSpace: "pre-wrap", wordBreak: "break-word",
      }}>
        {content || "(vacío)"}
      </pre>
    </div>
  );
}
