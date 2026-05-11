import { useEffect, useState, useRef } from "react";
import { api, formatError } from "../api";
import { useAuth } from "../AuthContext";

export default function BossConsole() {
  const { user } = useAuth();
  const [agents, setAgents] = useState([]);
  const [sessions, setSessions] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [activeSession, setActiveSession] = useState(null);
  const [balance, setBalance] = useState(null);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [err, setErr] = useState("");
  const [showAgentPicker, setShowAgentPicker] = useState(false);
  const scrollRef = useRef(null);

  const refreshAll = async () => {
    try {
      const [a, s, c] = await Promise.all([
        api.get("/console/agents"),
        api.get("/console/sessions"),
        api.get("/console/credits/me"),
      ]);
      setAgents(a.data.agents);
      setSessions(s.data.sessions);
      setBalance(c.data.balance);
    } catch (e) {
      setErr(formatError(e));
    }
  };

  useEffect(() => { refreshAll(); }, []);

  useEffect(() => {
    if (!activeId) return;
    api.get(`/console/sessions/${activeId}`)
      .then((r) => setActiveSession(r.data))
      .catch((e) => setErr(formatError(e)));
  }, [activeId]);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [activeSession?.messages?.length, sending]);

  const createSession = async (agentId) => {
    setShowAgentPicker(false);
    setErr("");
    try {
      const r = await api.post("/console/sessions", { agent_id: agentId });
      await refreshAll();
      setActiveId(r.data.id);
    } catch (e) {
      setErr(formatError(e));
    }
  };

  const send = async () => {
    if (!input.trim() || !activeId || sending) return;
    const text = input.trim();
    setInput("");
    setSending(true);
    setErr("");
    // optimista
    setActiveSession((prev) => prev ? {
      ...prev,
      messages: [...(prev.messages || []), { id: "tmp", role: "user", content: text, ts: new Date().toISOString() }],
    } : prev);
    try {
      const r = await api.post(`/console/sessions/${activeId}/messages`, { text });
      setBalance(r.data.balance);
      // refrescar sesion completa
      const fresh = await api.get(`/console/sessions/${activeId}`);
      setActiveSession(fresh.data);
      // refrescar lista (updated_at)
      const s = await api.get("/console/sessions");
      setSessions(s.data.sessions);
    } catch (e) {
      setErr(formatError(e));
    } finally {
      setSending(false);
    }
  };

  const deleteSession = async (id) => {
    if (!window.confirm("Borrar este hilo?")) return;
    await api.delete(`/console/sessions/${id}`);
    if (activeId === id) {
      setActiveId(null);
      setActiveSession(null);
    }
    refreshAll();
  };

  const getAgent = (id) => agents.find((a) => a.id === id);
  const currentAgent = activeSession ? getAgent(activeSession.agent_id) : null;

  return (
    <div className="boss-console" data-testid="boss-console">
      {/* Sidebar threads */}
      <aside className="bc-sidebar" data-testid="bc-sidebar">
        <div className="bc-side-head">
          <button
            className="bc-new-btn"
            onClick={() => setShowAgentPicker(true)}
            data-testid="bc-new-thread-btn"
          >
            + Nuevo hilo
          </button>
        </div>
        <div className="bc-thread-list" data-testid="bc-thread-list">
          {sessions.length === 0 && (
            <div className="bc-empty">Sin hilos aun. Crea uno arriba.</div>
          )}
          {sessions.map((s) => {
            const ag = getAgent(s.agent_id);
            return (
              <div
                key={s.id}
                className={`bc-thread ${activeId === s.id ? "active" : ""}`}
                onClick={() => setActiveId(s.id)}
                data-testid={`bc-thread-${s.id}`}
              >
                <div className="bc-thread-emoji" style={{ background: ag?.color || "#333" }}>
                  {ag?.emoji || "💬"}
                </div>
                <div className="bc-thread-meta">
                  <div className="bc-thread-title">{s.title}</div>
                  <div className="bc-thread-preview">{s.last_message_preview || "Sin mensajes"}</div>
                </div>
                <button
                  className="bc-thread-del"
                  onClick={(e) => { e.stopPropagation(); deleteSession(s.id); }}
                  data-testid={`bc-del-${s.id}`}
                >×</button>
              </div>
            );
          })}
        </div>
      </aside>

      {/* Main panel */}
      <main className="bc-main">
        <header className="bc-header">
          <div className="bc-header-left">
            {currentAgent ? (
              <>
                <span className="bc-header-emoji" style={{ background: currentAgent.color }}>
                  {currentAgent.emoji}
                </span>
                <div>
                  <div className="bc-header-name">{currentAgent.name}</div>
                  <div className="bc-header-tag">{currentAgent.tagline}</div>
                </div>
              </>
            ) : (
              <div className="bc-header-tag">Selecciona o crea un hilo para comenzar</div>
            )}
          </div>
          <div className="bc-credits" data-testid="bc-credits">
            <span className="bc-credits-icon">⚜</span>
            <span className="bc-credits-num">{balance ?? "—"}</span>
            <span className="bc-credits-label">oros</span>
          </div>
        </header>

        {err && <div className="alert" data-testid="bc-error">{err}</div>}

        <div className="bc-chat" ref={scrollRef} data-testid="bc-chat-area">
          {!activeSession && (
            <div className="bc-welcome" data-testid="bc-welcome">
              <h2>Boss Console</h2>
              <p>Multi-agente · tools reales · oros descuentan por tarea</p>
              <div className="bc-agent-grid">
                {agents.map((a) => (
                  <button
                    key={a.id}
                    className="bc-agent-card"
                    style={{ borderColor: a.color }}
                    onClick={() => createSession(a.id)}
                    data-testid={`bc-agent-card-${a.id}`}
                  >
                    <div className="bc-agent-emoji" style={{ background: a.color }}>{a.emoji}</div>
                    <div className="bc-agent-name">{a.name}</div>
                    <div className="bc-agent-tag">{a.tagline}</div>
                    {a.tools.length > 0 && (
                      <div className="bc-agent-tools">{a.tools.length} tools</div>
                    )}
                  </button>
                ))}
              </div>
            </div>
          )}

          {activeSession?.messages?.map((m) => (
            <Message key={m.id} msg={m} agent={currentAgent} />
          ))}

          {sending && (
            <div className="bc-msg bc-msg-assistant" data-testid="bc-typing">
              <div className="bc-msg-avatar" style={{ background: currentAgent?.color }}>
                {currentAgent?.emoji}
              </div>
              <div className="bc-msg-body">
                <div className="bc-typing-dots"><span></span><span></span><span></span></div>
              </div>
            </div>
          )}
        </div>

        {activeSession && (
          <div className="bc-composer" data-testid="bc-composer">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
              placeholder={`Escribele a ${currentAgent?.name}... (Enter para enviar)`}
              rows={2}
              data-testid="bc-input"
              disabled={sending}
            />
            <button
              className="bc-send-btn"
              onClick={send}
              disabled={!input.trim() || sending}
              data-testid="bc-send-btn"
            >
              {sending ? "..." : "Enviar"}
            </button>
          </div>
        )}
      </main>

      {/* Modal: picker de agente */}
      {showAgentPicker && (
        <div className="bc-modal-overlay" onClick={() => setShowAgentPicker(false)}>
          <div className="bc-modal" onClick={(e) => e.stopPropagation()} data-testid="bc-agent-picker">
            <h3>Elige un agente</h3>
            <div className="bc-agent-grid">
              {agents.map((a) => (
                <button
                  key={a.id}
                  className="bc-agent-card"
                  style={{ borderColor: a.color }}
                  onClick={() => createSession(a.id)}
                  data-testid={`bc-picker-${a.id}`}
                >
                  <div className="bc-agent-emoji" style={{ background: a.color }}>{a.emoji}</div>
                  <div className="bc-agent-name">{a.name}</div>
                  <div className="bc-agent-tag">{a.tagline}</div>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Message({ msg, agent }) {
  const isUser = msg.role === "user";
  return (
    <div className={`bc-msg ${isUser ? "bc-msg-user" : "bc-msg-assistant"}`} data-testid={`bc-msg-${msg.role}`}>
      <div className="bc-msg-avatar" style={{ background: isUser ? "#222" : agent?.color }}>
        {isUser ? "👤" : agent?.emoji || "🤖"}
      </div>
      <div className="bc-msg-body">
        {msg.tool_calls?.length > 0 && (
          <div className="bc-tool-trace">
            {msg.tool_calls.map((tc, i) => (
              <div key={i} className="bc-tool-call">
                <span className="bc-tool-name">⚙ {tc.name}</span>
                <span className="bc-tool-args">{JSON.stringify(tc.args).slice(0, 80)}</span>
              </div>
            ))}
          </div>
        )}
        <div className="bc-msg-text">{msg.content}</div>
        {msg.cost_oros !== undefined && msg.cost_oros > 0 && (
          <div className="bc-msg-cost">-{msg.cost_oros} oros</div>
        )}
      </div>
    </div>
  );
}
