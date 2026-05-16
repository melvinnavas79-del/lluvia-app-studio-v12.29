/* PublicChat - Landing 24/7 para visitantes anonimos */
import { useEffect, useRef, useState } from "react";
import axios from "axios";
import { useBranding } from "../BrandingContext";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export default function PublicChat({ onAdminClick }) {
  const { branding } = useBranding();
  const [agents, setAgents] = useState([]);
  const [selected, setSelected] = useState(null);
  const [messages, setMessages] = useState([]);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [sessionId, setSessionId] = useState("");
  const [visitorName, setVisitorName] = useState(
    () => localStorage.getItem("lluvia_visitor_name") || ""
  );
  const [nameAsked, setNameAsked] = useState(!!visitorName);
  const [err, setErr] = useState("");
  const scrollRef = useRef(null);

  useEffect(() => {
    axios
      .get(`${API}/public/agents`)
      .then((r) => setAgents(r.data.agents || []))
      .catch((e) => setErr(e.response?.data?.detail || "Error cargando agentes"));
  }, []);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const saveName = () => {
    if (visitorName.trim().length >= 2) {
      localStorage.setItem("lluvia_visitor_name", visitorName.trim());
      setNameAsked(true);
    }
  };

  const send = async () => {
    if (!text.trim() || !selected) return;
    const userMsg = { role: "user", content: text.trim(), id: Date.now() };
    setMessages((m) => [...m, userMsg]);
    setText("");
    setSending(true);
    setErr("");
    try {
      const { data } = await axios.post(`${API}/public/chat`, {
        agent_id: selected.id,
        text: userMsg.content,
        session_id: sessionId || undefined,
        visitor_name: visitorName || undefined,
      });
      if (data.session_id && !sessionId) setSessionId(data.session_id);
      setMessages((m) => [...m, {
        role: "assistant",
        content: data.response,
        agent: data.agent,
        id: Date.now() + 1,
      }]);
    } catch (e) {
      setErr(e.response?.data?.detail || "Error enviando mensaje. Intenta de nuevo.");
    } finally {
      setSending(false);
    }
  };

  const pickAgent = (a) => {
    setSelected(a);
    setMessages([{
      role: "assistant",
      content: `Hola${visitorName ? ` ${visitorName}` : ""}, soy ${a.name}. ${a.tagline || "¿En que te ayudo?"}`,
      agent: a,
      id: Date.now(),
    }]);
    setSessionId("");
  };

  const brandColor = branding?.primary_color || "#5fb4ff";
  const brandName = branding?.product_name || branding?.company_name || "Lluvia App Studio";
  const tagline = branding?.tagline || "Agentes inteligentes a tu servicio 24/7";

  return (
    <div className="public-chat" data-testid="public-chat-page">
      <header className="pc-header">
        <div className="pc-brand">
          <div className="pc-logo" style={{ background: brandColor }}>
            {brandName.slice(0, 1)}
          </div>
          <div>
            <div className="pc-name">{brandName}</div>
            <div className="pc-tag">{tagline}</div>
          </div>
        </div>
        <button
          className="pc-admin-link"
          onClick={onAdminClick}
          data-testid="public-admin-login-btn"
        >
          Soy admin → Login
        </button>
      </header>

      {!nameAsked && (
        <div className="pc-name-card" data-testid="pc-name-card">
          <h3>Bienvenido 👋</h3>
          <p>¿Como te llamas? (asi el agente te trata mejor)</p>
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <input
              type="text"
              value={visitorName}
              onChange={(e) => setVisitorName(e.target.value)}
              placeholder="Tu nombre"
              maxLength={60}
              onKeyDown={(e) => e.key === "Enter" && saveName()}
              data-testid="pc-name-input"
            />
            <button
              onClick={saveName}
              style={{ background: brandColor }}
              data-testid="pc-name-submit"
            >
              Empezar
            </button>
          </div>
          <button
            className="pc-skip"
            onClick={() => setNameAsked(true)}
            data-testid="pc-name-skip"
          >
            Prefiero no decirlo
          </button>
        </div>
      )}

      {nameAsked && (
        <div className="pc-body">
          <aside className="pc-agents" data-testid="pc-agents-list">
            <h4>Elige un agente</h4>
            {agents.length === 0 && !err && <div className="empty">Cargando...</div>}
            {err && <div className="alert">{err}</div>}
            {agents.map((a) => (
              <button
                key={a.id}
                className={`pc-agent ${selected?.id === a.id ? "active" : ""}`}
                onClick={() => pickAgent(a)}
                data-testid={`pc-agent-${a.id}`}
                style={selected?.id === a.id ? { borderColor: a.color || brandColor } : {}}
              >
                <span className="pc-agent-emoji" style={{ background: a.color }}>
                  {a.emoji}
                </span>
                <span className="pc-agent-info">
                  <span className="pc-agent-name">{a.name}</span>
                  <span className="pc-agent-tagline">{a.tagline}</span>
                </span>
              </button>
            ))}
          </aside>

          <main className="pc-chat">
            {!selected ? (
              <div className="pc-empty-state">
                <h2>Hola {visitorName || "👋"}</h2>
                <p>Elige uno de los agentes para empezar a conversar</p>
              </div>
            ) : (
              <>
                <div className="pc-chat-head" style={{ borderColor: selected.color }}>
                  <div className="pc-chat-avatar" style={{ background: selected.color }}>
                    {selected.emoji}
                  </div>
                  <div>
                    <div className="pc-chat-name">{selected.name}</div>
                    <div className="pc-chat-status">● en linea</div>
                  </div>
                </div>

                <div className="pc-messages" ref={scrollRef} data-testid="pc-messages">
                  {messages.map((m) => (
                    <div key={m.id} className={`pc-msg pc-msg-${m.role}`}>
                      <div
                        className="pc-bubble"
                        style={m.role === "assistant" ? { borderColor: selected.color + "44" } : {}}
                      >
                        {m.content}
                      </div>
                    </div>
                  ))}
                  {sending && (
                    <div className="pc-msg pc-msg-assistant">
                      <div className="pc-bubble pc-typing">
                        <span></span><span></span><span></span>
                      </div>
                    </div>
                  )}
                </div>

                {err && <div className="alert">{err}</div>}

                <div className="pc-input">
                  <input
                    type="text"
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && !sending && send()}
                    placeholder="Escribe tu mensaje..."
                    maxLength={1000}
                    disabled={sending}
                    data-testid="pc-msg-input"
                  />
                  <button
                    onClick={send}
                    disabled={!text.trim() || sending}
                    style={{ background: selected.color }}
                    data-testid="pc-msg-send"
                  >
                    {sending ? "..." : "Enviar"}
                  </button>
                </div>
              </>
            )}
          </main>
        </div>
      )}

      <footer className="pc-footer">
        Powered by {brandName} · {new Date().getFullYear()}
      </footer>
    </div>
  );
}
