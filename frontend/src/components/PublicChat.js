/* PublicChat - Landing premium con foco comercial real:
   Plataforma multi-cara (TikTok/Kwai/Likee, radios live) + Agentes IA
   personalizados para negocios tradicionales (peluquerías, WhatsApp, etc). */
import { useEffect, useState } from "react";
import axios from "axios";
import { useBranding } from "../BrandingContext";
import { ThemeToggle } from "../ThemeContext";
import AgentAvatar from "./AgentAvatar";
import {
  Video, Bot, Radio, Sparkles, Calendar, CreditCard,
  Mic, Github, Smartphone,
} from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export default function PublicChat({ onLoginClick, onRegisterClick }) {
  const { branding } = useBranding();
  const [agents, setAgents] = useState([]);

  useEffect(() => {
    axios
      .get(`${API}/public/agents`)
      .then((r) => setAgents(r.data.agents || []))
      .catch(() => {});
  }, []);

  const brandName = branding?.product_name || branding?.company_name || "Lluvia App Studio";
  const heroBots = agents.slice(0, 5);

  return (
    <div className="landing" data-testid="public-chat-page">
      <header className="pc-header">
        <div className="pc-brand">
          <div className="pc-logo">{brandName.slice(0, 1)}</div>
          <div>
            <div className="pc-name">{brandName}</div>
            <div className="pc-tag">Apps profesionales + Agentes IA · 24/7</div>
          </div>
        </div>
        <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
          <ThemeToggle />
          <button
            className="pc-admin-link"
            onClick={onLoginClick}
            data-testid="public-login-btn"
          >
            Iniciar sesión
          </button>
          <button
            className="cta-primary"
            onClick={onRegisterClick}
            data-testid="public-register-btn"
            style={{ padding: "0.6rem 1.25rem", fontSize: "0.9rem" }}
          >
            Crear cuenta
          </button>
        </div>
      </header>

      <section className="landing-hero">
          <span className="hero-tag">★ Apps multimedia + Agentes IA · Lanza en minutos</span>
          <h1>
            Crea Aplicaciones Profesionales y <span>Agentes de IA que trabajan por ti 24/7</span>
          </h1>
          <p className="landing-sub">
            Lanza plataformas completas con interfaces avanzadas al estilo de TikTok, Kwai o
            sistemas de radio en vivo, mientras configuras agentes de IA especializados para
            automatizar peluquerías, tiendas o soporte por WhatsApp. Todo programado,
            desplegado y gestionado por IA sin tocar una sola línea de código.
          </p>
        <div className="landing-cta">
          <button
            className="cta-primary"
            onClick={onRegisterClick}
            data-testid="hero-register-btn"
          >
            Empezar gratis con 50 oros →
          </button>
          <button
            className="cta-secondary"
            onClick={onLoginClick}
            data-testid="hero-login-btn"
          >
            Ya tengo cuenta
          </button>
        </div>
        <p className="landing-mini">
          <span>✓ Sin tarjeta de crédito</span>
          <span>✓ 50 oros gratis al registrarte</span>
          <span>✓ Tu código, tu GitHub</span>
        </p>

        {heroBots.length > 0 && (
          <div className="landing-bots-strip" aria-hidden="true">
            {heroBots.map((a) => (
              <AgentAvatar key={a.id} agent={a} size={48} rounded="circle" />
            ))}
          </div>
        )}
      </section>

      {/* ── 3 grandes propuestas de valor ─────────────────────────── */}
      <section className="landing-pillars">
        <h2>Tres motores en una sola plataforma</h2>
        <p className="landing-pillars-sub">
          Construimos los tres tipos de productos digitales más rentables del mercado actual.
          Tú eliges cuál lanzar — la IA lo construye y lo opera.
        </p>
        <div className="pillars-grid">
          <article className="pillar-card pillar-1" data-testid="pillar-apps-multimedia">
            <div className="pillar-icon">
              <Video size={28} strokeWidth={1.6} />
            </div>
            <span className="pillar-tag">01 · Multimedia</span>
            <h3>Apps complejas y multimedia</h3>
            <p>
              Desarrolla aplicaciones profesionales con feeds de video corto, salas de
              streaming en vivo y perfiles dinámicos inspirados en plataformas como
              TikTok o Likee.
            </p>
            <ul className="pillar-bullets">
              <li>Feeds verticales tipo TikTok / Kwai</li>
              <li>Streaming en vivo + chats de sala</li>
              <li>Perfiles, follows y monetización</li>
            </ul>
          </article>

          <article className="pillar-card pillar-2" data-testid="pillar-agentes-negocios">
            <div className="pillar-icon">
              <Bot size={28} strokeWidth={1.6} />
            </div>
            <span className="pillar-tag">02 · Negocios</span>
            <h3>Agentes personalizados para negocios</h3>
            <p>
              Clona empleados virtuales inteligentes entrenados para cualquier nicho:
              agendar citas en peluquerías, cerrar ventas, dar soporte y automatizar
              tu WhatsApp.
            </p>
            <ul className="pillar-bullets">
              <li>Citas reales en base de datos</li>
              <li>Cobros con PayPal en automático</li>
              <li>WhatsApp · Telegram · DM Web</li>
            </ul>
          </article>

          <article className="pillar-card pillar-3" data-testid="pillar-radio-live">
            <div className="pillar-icon">
              <Radio size={28} strokeWidth={1.6} />
            </div>
            <span className="pillar-tag">03 · Audio Live</span>
            <h3>Sistemas de radio y audio live</h3>
            <p>
              Monta emisoras digitales y plataformas de streaming de audio completas,
              monitoreadas y administradas por IA en tiempo real.
            </p>
            <ul className="pillar-bullets">
              <li>Emisora 24/7 con DJ-IA</li>
              <li>Programación, anuncios y jingles</li>
              <li>Estadísticas en vivo y moderación</li>
            </ul>
          </article>
        </div>
      </section>

      {/* ── Capacidades técnicas (más sutil ahora, no héroe) ──────── */}
      <section className="landing-features">
        <h2>Capacidades que vienen incluidas</h2>
        <div className="feature-grid">
          <div className="feature-card">
            <div className="feature-icon"><Sparkles size={20} /></div>
            <h3>Arquitecto de agentes</h3>
            <p>Pídele a la IA un agente para tu rubro y lo crea con personalidad, voz y tools.</p>
          </div>
          <div className="feature-card">
            <div className="feature-icon"><Calendar size={20} /></div>
            <h3>Reservas reales</h3>
            <p>Citas en DB real, validación de horarios y bloqueo de duplicados.</p>
          </div>
          <div className="feature-card">
            <div className="feature-icon"><CreditCard size={20} /></div>
            <h3>Cobros con PayPal</h3>
            <p>Órdenes profesionales que tus clientes pagan con 1 click. Sin comisiones extra.</p>
          </div>
          <div className="feature-card">
            <div className="feature-icon"><Mic size={20} /></div>
            <h3>Voz natural</h3>
            <p>Whisper + TTS. Cada agente con su propia voz. Modo Call Center continuo.</p>
          </div>
          <div className="feature-card">
            <div className="feature-icon"><Github size={20} /></div>
            <h3>Push a tu GitHub</h3>
            <p>Empuja todo el código generado a TU repositorio. Tu trabajo, tu propiedad.</p>
          </div>
          <div className="feature-card">
            <div className="feature-icon"><Smartphone size={20} /></div>
            <h3>Multi-canal</h3>
            <p>Telegram, WhatsApp (próx.), Web y DMs. Mismo agente, todos los canales.</p>
          </div>
        </div>
      </section>

      <section className="landing-agents">
        <h2>Agentes listos para inspirarte</h2>
        <div className="landing-agents-grid">
          {agents.map((a) => (
            <div key={a.id} className="landing-agent-card" data-testid={`landing-agent-${a.id}`}>
              <AgentAvatar agent={a} size={44} rounded="rounded" />
              <div>
                <div className="landing-agent-name">{a.name}</div>
                <div className="landing-agent-tag">{a.tagline}</div>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="landing-cta-final">
        <h2>¿Listo para construir tu próxima plataforma?</h2>
        <p>50 oros gratis te alcanzan para ~50 mensajes de prueba. Cuando los consumas, recargas lo que necesites.</p>
        <button
          className="cta-primary"
          onClick={onRegisterClick}
          data-testid="footer-register-btn"
        >
          Crear mi cuenta gratis →
        </button>
      </section>

      <footer className="pc-footer">
        <div style={{ marginBottom: "0.5rem" }}>
          <a href="/api/legal/terms" target="_blank" rel="noreferrer" style={{ color: "var(--text-muted)", marginRight: "1rem" }}
             data-testid="footer-terms-link">Términos</a>
          <a href="/api/legal/privacy" target="_blank" rel="noreferrer" style={{ color: "var(--text-muted)", marginRight: "1rem" }}
             data-testid="footer-privacy-link">Privacidad</a>
          <a href="/api/legal/cookies" target="_blank" rel="noreferrer" style={{ color: "var(--text-muted)" }}
             data-testid="footer-cookies-link">Cookies</a>
        </div>
        Powered by {brandName} · {new Date().getFullYear()}
      </footer>
    </div>
  );
}
