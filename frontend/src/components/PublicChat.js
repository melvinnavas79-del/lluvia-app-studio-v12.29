/* PublicChat - Landing premium con foco comercial real:
   Plataforma multi-cara (TikTok/Kwai/Likee, radios live) + Agentes IA
   personalizados para negocios tradicionales (peluquerías, WhatsApp, etc).
   Contenido editable via /api/site/content (Site Content 2.0). */
import { useEffect, useState } from "react";
import axios from "axios";
import { useBranding } from "../BrandingContext";
import { ThemeToggle } from "../ThemeContext";
import AgentAvatar from "./AgentAvatar";
import * as LucideIcons from "lucide-react";
import {
  Video, Bot, Radio, Sparkles, Calendar, CreditCard,
  Mic, Github, Smartphone,
} from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

// Mapea string -> componente lucide para los pillars editables
function pillarIcon(name) {
  const C = LucideIcons[name];
  if (C) return <C size={28} strokeWidth={1.6} />;
  return <Sparkles size={28} strokeWidth={1.6} />;
}

export default function PublicChat({ onLoginClick, onRegisterClick }) {
  const { branding } = useBranding();
  const [agents, setAgents] = useState([]);
  const [site, setSite] = useState(null);

  useEffect(() => {
    axios
      .get(`${API}/public/agents`)
      .then((r) => setAgents(r.data.agents || []))
      .catch(() => {});
    axios
      .get(`${API}/site/content`)
      .then((r) => setSite(r.data))
      .catch(() => {});
  }, []);

  const brandName = branding?.product_name || branding?.company_name || "Lluvia App Studio";
  const heroBots = agents.slice(0, 5);
  const pillars = site?.pillars || [];
  const social = site?.social || {};
  const socialLinks = [
    ["tiktok", "TikTok", "https://tiktok.com"],
    ["instagram", "Instagram", "https://instagram.com"],
    ["facebook", "Facebook", "https://facebook.com"],
    ["youtube", "YouTube", "https://youtube.com"],
    ["twitter", "Twitter / X", "https://x.com"],
    ["linkedin", "LinkedIn", "https://linkedin.com"],
  ].filter(([k]) => social[k]);

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
          <span className="hero-tag">{site?.hero_tag || "★ Apps multimedia + Agentes IA · Lanza en minutos"}</span>
          <h1>
            {site?.hero_title || "Crea Aplicaciones Profesionales y"}{" "}
            <span>{site?.hero_title_accent || "Agentes de IA que trabajan por ti 24/7"}</span>
          </h1>
          <p className="landing-sub">
            {site?.hero_sub ||
              "Lanza plataformas completas con interfaces avanzadas al estilo de TikTok, Kwai o sistemas de radio en vivo, mientras configuras agentes de IA especializados para automatizar peluquerías, tiendas o soporte por WhatsApp. Todo programado, desplegado y gestionado por IA sin tocar una sola línea de código."}
          </p>
        <div className="landing-cta">
          <button
            className="cta-primary"
            onClick={onRegisterClick}
            data-testid="hero-register-btn"
          >
            {site?.hero_cta_primary || `Empezar gratis con ${site?.trial_oros ?? 15} oros →`}
          </button>
          <button
            className="cta-secondary"
            onClick={onLoginClick}
            data-testid="hero-login-btn"
          >
            {site?.hero_cta_secondary || "Ya tengo cuenta"}
          </button>
        </div>
        <p className="landing-mini">
          <span>✓ Sin tarjeta de crédito</span>
          <span>✓ {site?.trial_oros ?? 15} oros gratis al registrarte</span>
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
          {(pillars.length > 0 ? pillars : [
            { icon: "Video", tag: "01 · Multimedia", title: "Apps complejas y multimedia",
              description: "Desarrolla aplicaciones profesionales con feeds de video corto, salas de streaming en vivo y perfiles dinámicos inspirados en plataformas como TikTok o Likee.",
              bullets: ["Feeds verticales tipo TikTok / Kwai", "Streaming en vivo + chats de sala", "Perfiles, follows y monetización"],
              accent: "#EC4899" },
            { icon: "Bot", tag: "02 · Negocios", title: "Agentes personalizados para negocios",
              description: "Clona empleados virtuales inteligentes entrenados para cualquier nicho: agendar citas en peluquerías, cerrar ventas, dar soporte y automatizar tu WhatsApp.",
              bullets: ["Citas reales en base de datos", "Cobros con PayPal en automático", "WhatsApp · Telegram · DM Web"],
              accent: "#10B981" },
            { icon: "Radio", tag: "03 · Audio Live", title: "Sistemas de radio y audio live",
              description: "Monta emisoras digitales y plataformas de streaming de audio completas, monitoreadas y administradas por IA en tiempo real.",
              bullets: ["Emisora 24/7 con DJ-IA", "Programación, anuncios y jingles", "Estadísticas en vivo y moderación"],
              accent: "#F59E0B" },
          ]).map((p, idx) => (
            <article key={idx} className={`pillar-card pillar-${idx + 1}`}
                     data-testid={`pillar-${idx}`}
                     style={p.accent ? { "--pillar-accent": p.accent } : {}}>
              <div className="pillar-icon">{pillarIcon(p.icon)}</div>
              <span className="pillar-tag">{p.tag}</span>
              <h3>{p.title}</h3>
              <p>{p.description}</p>
              <ul className="pillar-bullets">
                {(p.bullets || []).map((b, j) => <li key={j}>{b}</li>)}
              </ul>
            </article>
          ))}
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
        <p>{site?.trial_oros ?? 15} oros gratis te alcanzan para una prueba inicial. Cuando los consumas, recargas lo que necesites.</p>
        <button
          className="cta-primary"
          onClick={onRegisterClick}
          data-testid="footer-register-btn"
        >
          Crear mi cuenta gratis →
        </button>
      </section>

      <footer className="pc-footer">
        {socialLinks.length > 0 && (
          <div style={{ marginBottom: "0.75rem", display: "flex", gap: "1rem", justifyContent: "center", flexWrap: "wrap" }}>
            {socialLinks.map(([k, label]) => (
              <a key={k} href={social[k]} target="_blank" rel="noreferrer"
                 style={{ color: "var(--text-secondary)", textDecoration: "none", fontWeight: 500 }}
                 data-testid={`social-${k}`}>
                {label}
              </a>
            ))}
          </div>
        )}
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
