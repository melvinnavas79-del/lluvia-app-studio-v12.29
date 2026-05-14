import { useEffect, useState } from "react";
import { api, formatError } from "../api";

export default function ProposalsTab() {
  const [items, setItems] = useState([]);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState("");

  const load = async () => {
    setErr("");
    try {
      const { data } = await api.get("/proposals");
      setItems(data.proposals || []);
    } catch (e) {
      setErr(formatError(e));
    }
  };

  useEffect(() => { load(); }, []);

  const act = async (pid, action) => {
    setBusy(pid);
    setErr(""); setMsg("");
    try {
      const { data } = await api.post(`/proposals/${pid}/${action}`);
      setMsg(action === "approve"
        ? (data.ok ? `Propuesta aplicada (${data.result?.applied || "ok"})`
                   : `Aprobada pero fallo al aplicar: ${data.result?.error || "?"}`)
        : "Propuesta rechazada.");
      setTimeout(() => setMsg(""), 4000);
      await load();
    } catch (e) {
      setErr(formatError(e));
    } finally {
      setBusy("");
    }
  };

  return (
    <div data-testid="proposals-tab">
      <h2 className="section-title">Propuestas de los agentes</h2>
      <p className="hero-sub" style={{ marginBottom: "1.5rem" }}>
        Los agentes proponen cambios (branding, promos, nuevos agentes, pricing).
        Nada se aplica hasta que tu, como admin, apruebes manualmente.
      </p>

      {err && <div className="alert" data-testid="proposals-error">{err}</div>}
      {msg && <div className="success" data-testid="proposals-success">{msg}</div>}

      {items.length === 0 ? (
        <div className="empty">Sin propuestas pendientes. Cuando un agente sugiera un cambio aparecera aqui.</div>
      ) : (
        <div className="proposals-list">
          {items.map((p) => (
            <div key={p.id} className="proposal-card" data-testid={`proposal-${p.id}`}>
              <div className="proposal-head">
                <span className={`chip proposal-type type-${p.type}`}>{p.type}</span>
                <span className={`chip status-${p.status}`}>{p.status}</span>
                <span className="proposal-date">{p.created_at?.slice(0, 16).replace("T", " ")}</span>
              </div>
              <h3 className="proposal-title">{p.title}</h3>
              <p className="proposal-rationale">{p.rationale}</p>
              <details className="proposal-payload">
                <summary>Ver payload</summary>
                <pre>{JSON.stringify(p.payload, null, 2)}</pre>
              </details>
              {p.proposed_by_agent && (
                <div className="proposal-author">Propuesto por agente: <strong>{p.proposed_by_agent}</strong></div>
              )}
              {p.status === "pending" && (
                <div className="proposal-actions">
                  <button
                    className="login-btn"
                    disabled={busy === p.id}
                    onClick={() => act(p.id, "approve")}
                    data-testid={`proposal-approve-${p.id}`}
                  >
                    {busy === p.id ? "..." : "Aprobar y aplicar"}
                  </button>
                  <button
                    className="copy-btn"
                    disabled={busy === p.id}
                    onClick={() => act(p.id, "reject")}
                    data-testid={`proposal-reject-${p.id}`}
                  >
                    Rechazar
                  </button>
                </div>
              )}
              {p.apply_result && p.apply_result.error && (
                <div className="alert" style={{ marginTop: "0.5rem" }}>
                  Error al aplicar: {p.apply_result.error}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
