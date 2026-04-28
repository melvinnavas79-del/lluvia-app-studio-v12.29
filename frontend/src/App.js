import { useEffect, useRef, useState } from "react";
import "@/App.css";
import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const PLATFORMS = [
  { key: "telegram",  label: "Telegram",  hint: "Bot conversacional via @BotFather", icon: "TG" },
  { key: "whatsapp",  label: "WhatsApp",  hint: "Meta Cloud API webhook",            icon: "WA" },
  { key: "instagram", label: "Instagram", hint: "Mensajes directos via Meta",        icon: "IG" },
  { key: "github",    label: "GitHub",    hint: "Crear repos / listar / commits",    icon: "GH" },
  { key: "llm_ready", label: "Motor IA",  hint: "OpenAI GPT (conexion directa)",     icon: "AI" },
];

const SUGGESTIONS = [
  "/help",
  "/status",
  "Hola, soy un cliente",
  "crear app Mi Tienda",
  "crear repo mi-bot",
  "listar repos",
];

function App() {
  const [status, setStatus] = useState(null);
  const [messages, setMessages] = useState([
    { role: "bot", content: "Bot multiplataforma listo. Escribe /help para ver los comandos." },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState("");
  const consoleRef = useRef(null);

  useEffect(() => {
    fetchStatus();
    const t = setInterval(fetchStatus, 15000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    if (consoleRef.current) {
      consoleRef.current.scrollTop = consoleRef.current.scrollHeight;
    }
  }, [messages]);

  const fetchStatus = async () => {
    try {
      const r = await axios.get(`${API}/status`);
      setStatus(r.data);
    } catch (e) {
      console.error("status error", e);
    }
  };

  const sendMessage = async (text) => {
    const msg = (text || input).trim();
    if (!msg || loading) return;
    setMessages((m) => [...m, { role: "user", content: msg }]);
    setInput("");
    setLoading(true);
    try {
      const r = await axios.post(`${API}/command`, { message: msg, user: "dashboard" });
      setMessages((m) => [...m, { role: "bot", content: r.data.response }]);
      fetchStatus();
    } catch (e) {
      setMessages((m) => [...m, { role: "bot", content: "Error: " + (e.message || "fallo de red") }]);
    } finally {
      setLoading(false);
    }
  };

  const copy = (text, key) => {
    navigator.clipboard.writeText(text);
    setCopied(key);
    setTimeout(() => setCopied(""), 1500);
  };

  const credentials = status?.credentials || {};
  const isReady = (k) => Boolean(credentials[k]);

  const webhooks = [
    { label: "Telegram",  url: `${API}/webhook/telegram/{TELEGRAM_TOKEN}` },
    { label: "WhatsApp",  url: `${API}/webhook/whatsapp` },
    { label: "Instagram", url: `${API}/webhook/instagram` },
    { label: "Comando",   url: `${API}/command (POST)` },
  ];

  return (
    <div className="App">
      <div className="container">
        {/* BRAND */}
        <div className="brand" data-testid="brand">
          <div className="brand-mark">
            <span className="brand-dot" />
            <span>BOT // MULTIPLATAFORMA</span>
          </div>
          <div className="brand-meta">
            v1.0.0 · puerto 8001 (mapeado /api)
          </div>
        </div>

        {/* HERO */}
        <header className="hero">
          <span className="hero-tag" data-testid="hero-tag">SISTEMA ACTIVO</span>
          <h1>
            Un bot que entiende, <br />
            <span className="accent">ejecuta y vende.</span>
          </h1>
          <p className="hero-sub">
            FastAPI + OpenAI GPT conectado a Telegram, WhatsApp e Instagram.
            Crea apps, gestiona tu GitHub, ejecuta comandos en el servidor
            y responde a tus clientes con memoria conversacional.
          </p>
        </header>

        {/* PLATFORMS */}
        <h2 className="section-title">01 — Estado de plataformas</h2>
        <div className="grid" data-testid="platforms-grid">
          {PLATFORMS.map((p) => (
            <div className="card" key={p.key} data-testid={`card-${p.key}`}>
              <div className="card-head">
                <div className="card-icon">{p.icon}</div>
                <span className={`badge ${isReady(p.key) ? "ok" : "no"}`}>
                  {isReady(p.key) ? "ACTIVO" : "PENDIENTE"}
                </span>
              </div>
              <h3>{p.label}</h3>
              <p>{p.hint}</p>
            </div>
          ))}
        </div>

        {/* CONSOLA */}
        <h2 className="section-title">02 — Consola en vivo</h2>
        <div className="console" data-testid="console">
          <div className="console-header">
            <span className="console-dot r" />
            <span className="console-dot y" />
            <span className="console-dot g" />
            <span style={{ marginLeft: "0.5rem" }}>bot@multiplataforma:~$</span>
          </div>
          <div className="console-body" ref={consoleRef}>
            {messages.map((m, i) => (
              <div key={i}>
                {m.role === "user" ? (
                  <div className="msg-user">
                    <span className="msg-prefix">$</span>{m.content}
                  </div>
                ) : (
                  <div className="msg-bot">
                    <span className="msg-prefix">&gt;</span>{m.content}
                  </div>
                )}
              </div>
            ))}
            {loading && <div className="msg-bot"><span className="msg-prefix">&gt;</span>procesando...</div>}
          </div>
          <div className="console-input">
            <input
              data-testid="console-input"
              type="text"
              placeholder="Escribe un comando o pregunta..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && sendMessage()}
            />
            <button data-testid="console-send" onClick={() => sendMessage()} disabled={loading}>
              ENVIAR
            </button>
          </div>
        </div>
        <div className="suggestions">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              data-testid={`suggestion-${s.replace(/\W+/g, "-")}`}
              onClick={() => sendMessage(s)}
              disabled={loading}
            >
              {s}
            </button>
          ))}
        </div>

        {/* WEBHOOKS */}
        <h2 className="section-title">03 — URLs de webhook</h2>
        <div className="webhook-list" data-testid="webhooks">
          {webhooks.map((w) => (
            <div key={w.label} className="webhook-row">
              <div className="label">{w.label}</div>
              <div className="url">{w.url}</div>
              <button
                data-testid={`copy-${w.label.toLowerCase()}`}
                className={`copy-btn ${copied === w.label ? "copied" : ""}`}
                onClick={() => copy(w.url, w.label)}
              >
                {copied === w.label ? "COPIADO" : "COPIAR"}
              </button>
            </div>
          ))}
        </div>

        {/* SETUP */}
        <h2 className="section-title">04 — Configurar tus API Keys</h2>
        <div className="steps">
          <div className="step">
            <div className="step-num">PASO 01</div>
            <h4>Edita el archivo .env</h4>
            <p>
              Abre <code>backend/.env</code> y completa los tokens de las plataformas
              que quieras activar, incluida tu <code>OPENAI_API_KEY</code>.
            </p>
          </div>
          <div className="step">
            <div className="step-num">PASO 02</div>
            <h4>Reinicia el backend</h4>
            <p>
              Ejecuta <code>sudo supervisorctl restart backend</code> para que tomen efecto.
            </p>
          </div>
          <div className="step">
            <div className="step-num">PASO 03</div>
            <h4>Apunta los webhooks</h4>
            <p>
              Copia las URLs de la sección 03 y pégalas en Telegram, Meta WhatsApp Business
              y Meta Instagram para empezar a recibir mensajes.
            </p>
          </div>
        </div>

        <footer data-testid="footer">
          <span>memoria: {status?.memory?.total_users ?? 0} usuarios · {status?.memory?.total_messages ?? 0} mensajes</span>
          <span>apps generadas: {status?.generated_apps?.length ?? 0}</span>
        </footer>
      </div>
    </div>
  );
}

export default App;
