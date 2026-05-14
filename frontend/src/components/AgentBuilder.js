import { useEffect, useState } from "react";
import { api, formatError } from "../api";

const VOICES = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"];

export default function AgentBuilder() {
  const [builtin, setBuiltin] = useState([]);
  const [custom, setCustom] = useState([]);
  const [availTools, setAvailTools] = useState([]);
  const [editing, setEditing] = useState(null);
  const [err, setErr] = useState("");
  const [ok, setOk] = useState("");

  const empty = () => ({
    id: "", name: "", emoji: "🤖", color: "#5fb4ff", voice: "alloy",
    tagline: "", system: "", tools: [],
  });

  const refresh = async () => {
    try {
      const [a, t] = await Promise.all([
        api.get("/agent-builder"),
        api.get("/agent-builder/available-tools"),
      ]);
      setBuiltin(a.data.builtin || []);
      setCustom(a.data.custom || []);
      setAvailTools(t.data.tools || []);
    } catch (e) { setErr(formatError(e)); }
  };
  useEffect(() => { refresh(); }, []);

  const save = async () => {
    setErr(""); setOk("");
    try {
      if (editing.is_new) {
        await api.post("/agent-builder", editing);
        setOk("Agente creado.");
      } else {
        await api.put(`/agent-builder/${editing.id}`, editing);
        setOk("Agente actualizado.");
      }
      setEditing(null);
      refresh();
    } catch (e) { setErr(formatError(e)); }
  };

  const remove = async (id) => {
    if (!window.confirm(`Borrar agente ${id}?`)) return;
    await api.delete(`/agent-builder/${id}`);
    refresh();
  };

  const toggleTool = (tid) => {
    setEditing((p) => ({
      ...p,
      tools: p.tools.includes(tid) ? p.tools.filter((x) => x !== tid) : [...p.tools, tid],
    }));
  };

  return (
    <div className="ab-wrap" data-testid="agent-builder">
      <div className="ab-head">
        <h3>Arquitecto Maestro — gestion de agentes</h3>
        <button className="bc-new-btn" onClick={() => setEditing({ ...empty(), is_new: true })}
                data-testid="ab-new-btn">+ Nuevo agente</button>
      </div>

      {err && <div className="alert">{err}</div>}
      {ok && <div className="alert ok">{ok}</div>}

      <h4>Built-in ({builtin.length})</h4>
      <div className="ab-grid">
        {builtin.map((a) => (
          <div key={a.id} className="ab-card" style={{ borderColor: a.color }}>
            <div className="ab-emoji" style={{ background: a.color }}>{a.emoji}</div>
            <div className="ab-info">
              <strong>{a.name}</strong>
              <div className="ab-tag">{a.tagline}</div>
              <div className="ab-meta">🎙 {a.voice} · {a.tools?.length || 0} tools</div>
            </div>
          </div>
        ))}
      </div>

      <h4 style={{ marginTop: "2rem" }}>Custom ({custom.length})</h4>
      <div className="ab-grid">
        {custom.length === 0 && <div className="bc-empty">Sin agentes custom todavia.</div>}
        {custom.map((a) => (
          <div key={a.id} className="ab-card" style={{ borderColor: a.color }}>
            <div className="ab-emoji" style={{ background: a.color }}>{a.emoji}</div>
            <div className="ab-info">
              <strong>{a.name}</strong>
              <div className="ab-tag">{a.tagline}</div>
              <div className="ab-meta">🎙 {a.voice} · {a.tools?.length || 0} tools</div>
              <div className="ab-actions">
                <button onClick={() => setEditing({ ...a, is_new: false })}>Editar</button>
                <button onClick={() => remove(a.id)} className="danger">Borrar</button>
              </div>
            </div>
          </div>
        ))}
      </div>

      {editing && (
        <div className="bc-modal-overlay" onClick={() => setEditing(null)}>
          <div className="bc-modal" onClick={(e) => e.stopPropagation()} data-testid="ab-editor">
            <h3>{editing.is_new ? "Nuevo agente" : `Editar ${editing.name}`}</h3>
            <div className="ab-form">
              <label>ID (sin espacios, minusculas)
                <input value={editing.id} onChange={(e) => setEditing({ ...editing, id: e.target.value })}
                       disabled={!editing.is_new} placeholder="contador_chile" data-testid="ab-id" />
              </label>
              <label>Nombre visible
                <input value={editing.name} onChange={(e) => setEditing({ ...editing, name: e.target.value })}
                       placeholder="Contador Chile" data-testid="ab-name" />
              </label>
              <div className="ab-row">
                <label>Emoji
                  <input value={editing.emoji} onChange={(e) => setEditing({ ...editing, emoji: e.target.value })}
                         placeholder="📊" />
                </label>
                <label>Color
                  <input type="color" value={editing.color}
                         onChange={(e) => setEditing({ ...editing, color: e.target.value })} />
                </label>
                <label>Voz
                  <select value={editing.voice}
                          onChange={(e) => setEditing({ ...editing, voice: e.target.value })}>
                    {VOICES.map((v) => <option key={v} value={v}>{v}</option>)}
                  </select>
                </label>
              </div>
              <label>Tagline (max 120 chars)
                <input value={editing.tagline} maxLength={120}
                       onChange={(e) => setEditing({ ...editing, tagline: e.target.value })}
                       placeholder="Experto en taxes y contabilidad chilena" />
              </label>
              <label>System prompt (instrucciones para el agente)
                <textarea value={editing.system} rows={7} maxLength={2000}
                       onChange={(e) => setEditing({ ...editing, system: e.target.value })}
                       placeholder="Eres Contador especializado en Chile. Conoces SII, IVA, F22, F29..." />
              </label>
              <div>
                <strong>Tools (cada una cuesta oros):</strong>
                <div className="ab-tools">
                  {availTools.map((t) => (
                    <label key={t.id} className="ab-tool-chk">
                      <input type="checkbox" checked={editing.tools.includes(t.id)}
                             onChange={() => toggleTool(t.id)} />
                      {t.id} <span>({t.cost_oros}o)</span>
                    </label>
                  ))}
                </div>
              </div>
              <div className="ab-actions">
                <button onClick={save} className="bc-new-btn" data-testid="ab-save">Guardar</button>
                <button onClick={() => setEditing(null)}>Cancelar</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
