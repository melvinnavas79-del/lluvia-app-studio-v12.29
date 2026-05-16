import { useEffect, useState, useRef } from "react";
import { api, formatError } from "../api";
import AgentAvatar from "./AgentAvatar";

export default function BossConsole() {
  const [agents, setAgents] = useState([]);
  const [sessions, setSessions] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [activeSession, setActiveSession] = useState(null);
  const [balance, setBalance] = useState(null);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [recording, setRecording] = useState(false);
  const [err, setErr] = useState("");
  const [showPicker, setShowPicker] = useState(false);
  const [showShop, setShowShop] = useState(false);
  const [packs, setPacks] = useState({});
  const [packsConfigured, setPacksConfigured] = useState(false);
  const scrollRef = useRef(null);
  const mediaRef = useRef(null);
  const chunksRef = useRef([]);

  const refreshAll = async () => {
    try {
      const [a, s, c, p] = await Promise.all([
        api.get("/console/agents"),
        api.get("/console/sessions"),
        api.get("/console/credits/me"),
        api.get("/paypal/packs"),
      ]);
      setAgents(a.data.agents);
      setSessions(s.data.sessions);
      setBalance(c.data.balance);
      setPacks(p.data.packs || {});
      setPacksConfigured(p.data.configured);
    } catch (e) {
      setErr(formatError(e));
    }
  };

  useEffect(() => { refreshAll(); }, []);

  useEffect(() => {
    if (!activeId) { setActiveSession(null); return; }
    api.get(`/console/sessions/${activeId}`)
      .then((r) => setActiveSession(r.data))
      .catch((e) => setErr(formatError(e)));
  }, [activeId]);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [activeSession?.messages?.length, sending]);

  const createSession = async (agentId) => {
    setShowPicker(false);
    try {
      const r = await api.post("/console/sessions", { agent_id: agentId });
      await refreshAll();
      setActiveId(r.data.id);
    } catch (e) { setErr(formatError(e)); }
  };

  const send = async (overrideText) => {
    const text = (overrideText ?? input).trim();
    if (!text || !activeId || sending) return;
    setInput("");
    setSending(true);
    setErr("");
    setActiveSession((p) => p ? {
      ...p,
      messages: [...(p.messages || []), { id: "tmp" + Date.now(), role: "user", content: text, ts: new Date().toISOString() }],
    } : p);
    try {
      const r = await api.post(`/console/sessions/${activeId}/messages`, { text });
      setBalance(r.data.balance);
      const fresh = await api.get(`/console/sessions/${activeId}`);
      setActiveSession(fresh.data);
      const s = await api.get("/console/sessions");
      setSessions(s.data.sessions);
    } catch (e) {
      setErr(formatError(e));
    } finally { setSending(false); }
  };

  const delSession = async (id) => {
    if (!window.confirm("Borrar este hilo?")) return;
    await api.delete(`/console/sessions/${id}`);
    if (activeId === id) setActiveId(null);
    refreshAll();
  };

  // ---- VOZ: grabar y transcribir
  const toggleRecord = async () => {
    if (recording) {
      mediaRef.current?.stop();
      setRecording(false);
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream);
      chunksRef.current = [];
      mr.ondataavailable = (e) => chunksRef.current.push(e.data);
      mr.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        const fd = new FormData();
        fd.append("audio", blob, "voice.webm");
        try {
          const r = await api.post("/voice/transcribe", fd, {
            headers: { "Content-Type": "multipart/form-data" },
          });
          setBalance(r.data.balance);
          if (r.data.text) send(r.data.text);
        } catch (e) { setErr(formatError(e)); }
      };
      mr.start();
      mediaRef.current = mr;
      setRecording(true);
    } catch (e) {
      setErr("Permiso de microfono denegado");
    }
  };

  const playTts = async (text, voice) => {
    try {
      const resp = await api.post("/voice/tts", { text, voice: voice || "alloy" },
        { responseType: "blob" });
      const balance = resp.headers["x-balance-after"];
      if (balance) setBalance(parseInt(balance, 10));
      const url = URL.createObjectURL(resp.data);
      new Audio(url).play();
    } catch (e) { setErr(formatError(e)); }
  };

  // ---- PAYPAL
  const buyPack = async (packId) => {
    try {
      const r = await api.post("/paypal/create-order", { pack: packId });
      const w = window.open(r.data.approve_url, "_blank", "width=500,height=700");
      // Polling: cuando el usuario apruebe y vuelva, capturamos
      const orderId = r.data.order_id;
      const poll = setInterval(async () => {
        if (w && w.closed) {
          clearInterval(poll);
          try {
            const cap = await api.post(`/paypal/capture/${orderId}`);
            if (cap.data.balance) setBalance(cap.data.balance);
            setShowShop(false);
            alert(`✅ Acreditados ${cap.data.credited_oros || 0} oros. Saldo: ${cap.data.balance}`);
          } catch (e) {
            alert("La orden quedo pendiente. Intentaras de nuevo desde 'Mis ordenes'.");
          }
        }
      }, 1500);
    } catch (e) { setErr(formatError(e)); }
  };

  const getAgent = (id) => agents.find((a) => a.id === id);
  const currentAgent = activeSession ? getAgent(activeSession.agent_id) : null;

  const pushNow = async () => {
    const msg = prompt("Mensaje del commit (opcional):", `Push desde Lluvia ${new Date().toLocaleString()}`);
    if (msg === null) return; // canceló
    try {
      const { data } = await api.post("/me/github/push", { commit_message: msg });
      if (data.ok) {
        alert(`✅ Push exitoso!\n\nRepo: ${data.repo}\nRama: ${data.branch}\n\nVer en GitHub: ${data.repo_url || `https://github.com/${data.repo}`}`);
      } else {
        alert(`⚠ Push falló:\n\n${(data.steps || []).slice(-1)[0]?.out || "ver consola"}`);
      }
    } catch (e) {
      const detail = e?.response?.data?.detail || formatError(e);
      if (detail && detail.toLowerCase().includes("configura")) {
        if (window.confirm("Aún no configuraste tu GitHub. ¿Ir a Settings ahora?")) {
          window.location.hash = "#/settings";
          window.location.reload();
        }
      } else {
        alert(`✕ ${detail}`);
      }
    }
  };

  return (
    <div className="boss-console" data-testid="boss-console">
      <aside className="bc-sidebar">
        <div className="bc-side-head">
          <button className="bc-new-btn" onClick={() => setShowPicker(true)} data-testid="bc-new-thread-btn">
            + Nuevo hilo
          </button>
        </div>
        <div className="bc-thread-list">
          {sessions.length === 0 && <div className="bc-empty">Sin hilos aun</div>}
          {sessions.map((s) => {
            const ag = getAgent(s.agent_id);
            return (
              <div key={s.id} className={`bc-thread ${activeId === s.id ? "active" : ""}`}
                   onClick={() => setActiveId(s.id)} data-testid={`bc-thread-${s.id}`}>
                {ag ? (
                  <AgentAvatar agent={ag} size={40} rounded="rounded" />
                ) : (
                  <div style={{ width: 40, height: 40, borderRadius: 12, background: "var(--surface-warm)" }} />
                )}
                <div className="bc-thread-meta">
                  <div className="bc-thread-title">{s.title}</div>
                  <div className="bc-thread-preview">{s.last_message_preview || "Sin mensajes"}</div>
                </div>
                <button className="bc-thread-del"
                        onClick={(e) => { e.stopPropagation(); delSession(s.id); }}>×</button>
              </div>
            );
          })}
        </div>
      </aside>

      <main className="bc-main">
        <header className="bc-header">
          <div className="bc-header-left">
            {currentAgent ? (
              <>
                <AgentAvatar agent={currentAgent} size={44} rounded="rounded" />
                <div>
                  <div className="bc-header-name">{currentAgent.name}</div>
                  <div className="bc-header-tag">{currentAgent.tagline}</div>
                </div>
              </>
            ) : <div className="bc-header-tag">Elige un agente para empezar</div>}
          </div>
          <div className="bc-header-right">
            <button className="bc-shop-btn" onClick={pushNow} data-testid="bc-push-github"
                    title="Push de tu workspace a GitHub"
                    style={{ display: "inline-flex", alignItems: "center", gap: "0.35rem" }}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                <path d="M12 .297a12 12 0 0 0-3.79 23.39c.6.11.82-.26.82-.58v-2.02c-3.34.72-4.04-1.61-4.04-1.61-.55-1.4-1.35-1.78-1.35-1.78-1.1-.75.08-.74.08-.74 1.22.09 1.86 1.25 1.86 1.25 1.09 1.86 2.85 1.32 3.54 1.01.11-.79.42-1.32.77-1.62-2.66-.3-5.47-1.33-5.47-5.93 0-1.31.47-2.38 1.24-3.22-.13-.31-.54-1.53.12-3.18 0 0 1.01-.32 3.3 1.23a11.5 11.5 0 0 1 6 0c2.29-1.55 3.3-1.23 3.3-1.23.66 1.65.25 2.87.12 3.18.78.84 1.24 1.91 1.24 3.22 0 4.61-2.81 5.62-5.48 5.92.43.37.81 1.1.81 2.22v3.29c0 .32.22.7.83.58A12 12 0 0 0 12 .297z"/>
              </svg>
              Push
            </button>
            <button className="bc-shop-btn" onClick={() => setShowShop(true)} data-testid="bc-shop-btn">
              + Recargar
            </button>
            <div className="bc-credits" data-testid="bc-credits">
              <span className="bc-credits-icon">⚜</span>
              <span className="bc-credits-num">{balance ?? "—"}</span>
              <span className="bc-credits-label">oros</span>
            </div>
          </div>
        </header>

        {err && <div className="alert" data-testid="bc-error">{err}</div>}

        <div className="bc-chat" ref={scrollRef}>
          {!activeSession && (
            <div className="bc-welcome">
              <h2>Elige tu agente</h2>
              <p>{agents.length} agentes con herramientas reales · voz · cobros · agendamiento</p>
              <div className="bc-agent-grid">
                {agents.map((a) => (
                  <button key={a.id} className="bc-agent-card"
                          onClick={() => createSession(a.id)} data-testid={`bc-agent-card-${a.id}`}>
                    <AgentAvatar agent={a} size={48} rounded="rounded" />
                    <div className="bc-agent-name">{a.name}</div>
                    <div className="bc-agent-tag">{a.tagline}</div>
                    <div className="bc-agent-foot">
                      <span className="bc-voice-tag">🎙 {a.voice || "alloy"}</span>
                      {a.tools?.length > 0 && <span>{a.tools.length} tools</span>}
                      {a.is_custom && <span className="bc-custom-tag">custom</span>}
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}

          {activeSession?.messages?.map((m) => (
            <Message key={m.id} msg={m} agent={currentAgent} onPlay={playTts} />
          ))}

          {sending && (
            <div className="bc-msg bc-msg-assistant">
              {currentAgent && <AgentAvatar agent={currentAgent} size={36} rounded="circle" />}
              <div className="bc-msg-body">
                <div className="bc-typing-dots"><span/><span/><span/></div>
              </div>
            </div>
          )}
        </div>

        {activeSession && (
          <div className="bc-composer">
            <button
              className={`bc-mic-btn ${recording ? "rec" : ""}`}
              onClick={toggleRecord}
              data-testid="bc-mic-btn"
              title="Hablar al agente">
              {recording ? "⏹" : "🎙"}
            </button>
            <textarea value={input} onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }}}
              placeholder={`Escribele a ${currentAgent?.name}...`}
              rows={2} data-testid="bc-input" disabled={sending} />
            <button className="bc-send-btn" onClick={() => send()} disabled={!input.trim() || sending}
                    data-testid="bc-send-btn">
              {sending ? "..." : "Enviar"}
            </button>
          </div>
        )}
      </main>

      {/* Modal: agent picker */}
      {showPicker && (
        <div className="bc-modal-overlay" onClick={() => setShowPicker(false)}>
          <div className="bc-modal" onClick={(e) => e.stopPropagation()}>
            <h3>Elige un agente</h3>
            <div className="bc-agent-grid">
              {agents.map((a) => (
                <button key={a.id} className="bc-agent-card"
                        onClick={() => createSession(a.id)}>
                  <AgentAvatar agent={a} size={44} rounded="rounded" />
                  <div className="bc-agent-name">{a.name}</div>
                  <div className="bc-agent-tag">{a.tagline}</div>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Modal: PayPal shop */}
      {showShop && (
        <div className="bc-modal-overlay" onClick={() => setShowShop(false)}>
          <div className="bc-modal" onClick={(e) => e.stopPropagation()} data-testid="bc-shop-modal">
            <h3>Recargar oros</h3>
            {!packsConfigured ? (
              <div className="alert">
                PayPal no configurado todavia.<br/>
                Pega tus credenciales en <code>backend/.env</code>:<br/>
                <code>PAYPAL_CLIENT_ID=...</code><br/>
                <code>PAYPAL_SECRET=...</code><br/>
                Y reinicia el backend.
              </div>
            ) : (
              <div className="bc-pack-grid">
                {Object.entries(packs).map(([k, p]) => (
                  <button key={k} className="bc-pack-card" onClick={() => buyPack(k)}
                          data-testid={`bc-pack-${k}`}>
                    <div className="bc-pack-oros">{p.oros.toLocaleString()} ⚜</div>
                    <div className="bc-pack-price">${p.price_usd} USD</div>
                    <div className="bc-pack-label">{p.label}</div>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function Message({ msg, agent, onPlay }) {
  const isUser = msg.role === "user";
  // Extraer rich cards desde tool_calls (paypal_invoice_card / service_card / push_to_my_github)
  const cards = (msg.tool_calls || []).map((tc) => {
    if (!["paypal_invoice_card", "service_card", "push_to_my_github"].includes(tc.name)) return null;
    try {
      const r = JSON.parse(tc.result_preview || "{}");
      if (r.card_type) return r;
    } catch (_) {}
    return null;
  }).filter(Boolean);

  return (
    <div className={`bc-msg ${isUser ? "bc-msg-user" : "bc-msg-assistant"}`} data-testid={`bc-msg-${msg.role}`}>
      {isUser ? (
        <div className="bc-msg-avatar" data-testid="msg-user-avatar">TU</div>
      ) : (
        agent
          ? <AgentAvatar agent={agent} size={36} rounded="circle" />
          : <div className="bc-msg-avatar">AI</div>
      )}
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
        {msg.content && <div className="bc-msg-text">{msg.content}</div>}
        {cards.map((c, i) => {
          if (c.card_type === "payment") return <PaymentCard key={i} card={c} agent={agent} />;
          if (c.card_type === "github_push") return <GitHubPushCard key={i} card={c} />;
          return <ServiceCard key={i} card={c} agent={agent} />;
        })}
        {msg.superadmin_takeover && (
          <div className="bc-takeover-badge">👑 SuperAdmin · {msg.by}</div>
        )}
        <div className="bc-msg-foot">
          {msg.cost_oros !== undefined && msg.cost_oros > 0 && (
            <span className="bc-msg-cost">-{msg.cost_oros} oros</span>
          )}
          {!isUser && msg.content && (
            <button className="bc-play-btn" onClick={() => onPlay(msg.content, agent?.voice)}
                    title="Escuchar">🔊</button>
          )}
        </div>
      </div>
    </div>
  );
}

function PaymentCard({ card, agent }) {
  const accent = agent?.color || "#5fb4ff";
  return (
    <div className="rich-card payment-card" data-testid="payment-card" style={{ borderColor: accent }}>
      <div className="rc-head" style={{ background: `linear-gradient(135deg, ${accent}22, transparent)` }}>
        <div className="rc-brand">
          <div className="rc-logo" style={{ background: accent }}>{(card.brand || "L").slice(0, 1)}</div>
          <div>
            <div className="rc-brand-name">{card.brand || "Lluvia App Studio"}</div>
            <div className="rc-brand-sub">Pago seguro · PayPal</div>
          </div>
        </div>
        <div className="rc-amount">${card.amount_usd}<small>USD</small></div>
      </div>
      <div className="rc-body">
        <div className="rc-desc">{card.description}</div>
        {card.client_name && <div className="rc-client">A nombre de: <strong>{card.client_name}</strong></div>}
        <div className="rc-order-id">Orden: {(card.order_id || "").slice(0, 12)}...</div>
      </div>
      <a href={card.approve_url} target="_blank" rel="noreferrer"
         className="rc-cta" style={{ background: accent }}
         data-testid="payment-card-cta">
        Pagar con PayPal →
      </a>
    </div>
  );
}

function ServiceCard({ card, agent }) {
  const accent = agent?.color || "#5fb4ff";
  return (
    <div className="rich-card service-card" data-testid="service-card" style={{ borderColor: accent }}>
      {card.image_url && (
        <img src={card.image_url} alt={card.title} className="rc-image" />
      )}
      <div className="rc-body">
        <div className="rc-title">{card.title}</div>
        {card.description && <div className="rc-desc">{card.description}</div>}
        {card.price_usd && (
          <div className="rc-price" style={{ color: accent }}>
            ${card.price_usd}<small> USD</small>
          </div>
        )}
        <button className="rc-cta-soft" style={{ borderColor: accent, color: accent }}>
          {card.cta_label || "Ver más"}
        </button>
      </div>
    </div>
  );
}

function GitHubPushCard({ card }) {
  const isOk = card.ok === true;
  const needsSetup = card.needs_setup === true;
  const stateColor = isOk ? "#059669" : needsSetup ? "#D97706" : "#DC2626";
  const stateLabel = isOk ? "Push exitoso" : needsSetup ? "Setup pendiente" : "Push fallido";
  const stateIcon = isOk ? "✓" : needsSetup ? "!" : "✕";
  return (
    <div className="rich-card github-push-card" data-testid="github-push-card"
         style={{ borderColor: stateColor }}>
      <div className="rc-head" style={{ background: `${stateColor}14` }}>
        <div className="rc-brand">
          <div className="rc-logo" style={{ background: stateColor, fontSize: "1rem" }}>{stateIcon}</div>
          <div>
            <div className="rc-brand-name">{stateLabel}</div>
            <div className="rc-brand-sub">Push a GitHub · Lluvia Workspace</div>
          </div>
        </div>
        <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"
             style={{ color: "var(--text-primary)" }}>
          <path d="M12 .297a12 12 0 0 0-3.79 23.39c.6.11.82-.26.82-.58v-2.02c-3.34.72-4.04-1.61-4.04-1.61-.55-1.4-1.35-1.78-1.35-1.78-1.1-.75.08-.74.08-.74 1.22.09 1.86 1.25 1.86 1.25 1.09 1.86 2.85 1.32 3.54 1.01.11-.79.42-1.32.77-1.62-2.66-.3-5.47-1.33-5.47-5.93 0-1.31.47-2.38 1.24-3.22-.13-.31-.54-1.53.12-3.18 0 0 1.01-.32 3.3 1.23a11.5 11.5 0 0 1 6 0c2.29-1.55 3.3-1.23 3.3-1.23.66 1.65.25 2.87.12 3.18.78.84 1.24 1.91 1.24 3.22 0 4.61-2.81 5.62-5.48 5.92.43.37.81 1.1.81 2.22v3.29c0 .32.22.7.83.58A12 12 0 0 0 12 .297z"/>
        </svg>
      </div>
      <div className="rc-body">
        {card.repo && (
          <div className="rc-desc">
            <span style={{ color: "var(--text-muted)", fontSize: "0.78rem" }}>Repositorio:</span>{" "}
            <strong>{card.repo}</strong>
            {card.branch && <span style={{ color: "var(--text-muted)" }}> · rama <code>{card.branch}</code></span>}
          </div>
        )}
        {card.commit_message && (
          <div style={{ fontSize: "0.85rem", color: "var(--text-secondary)", marginTop: "0.35rem" }}>
            Commit: <em>{card.commit_message}</em>
          </div>
        )}
        {card.message && !isOk && (
          <div className="rc-desc" style={{ color: stateColor, marginTop: "0.5rem" }}>
            {card.message}
          </div>
        )}
        {card.error && (
          <div className="rc-desc" style={{ color: stateColor, marginTop: "0.5rem", fontFamily: "var(--font-mono)", fontSize: "0.78rem" }}>
            {card.error}
          </div>
        )}
      </div>
      {isOk && card.repo_url && (
        <a href={card.repo_url} target="_blank" rel="noreferrer"
           className="rc-cta" style={{ background: stateColor }}
           data-testid="github-push-card-cta">
          Ver en GitHub →
        </a>
      )}
      {needsSetup && (
        <div className="rc-cta" style={{ background: stateColor, cursor: "default", fontSize: "0.85rem" }}>
          Configura tu token en Mi Cuenta → Settings
        </div>
      )}
    </div>
  );
}
