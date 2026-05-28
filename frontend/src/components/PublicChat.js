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
  Mic, Github, Smartphone, Check, Zap, Building2, Users,
} from "lucide-react";

const PRICING_PLANS = [
  {
    id: "starter",
    name: "Starter",
    price: "Gratis",
    period: "",
    desc: "Para probar y explorar la plataforma.",
    oros: 15,
    highlight: false,
    tag: null,
    features: [
      "15 oros de prueba",
      "1 agente activo",
      "Chat web + Telegram",
      "Reservas y pagos básicos",
      "Push a tu GitHub",
      "Soporte por comunidad",
    ],
    cta: "Empezar gratis",
    ctaVariant: "secondary",
  },
  {
    id: "pro",
    name: "Pro",
    price: "$29",
    period: "/mes",
    desc: "Para freelancers y agencias pequeñas.",
    oros: 500,
    highlight: true,
    tag: "Más popular",
    features: [
      "500 oros/mes incluidos",
      "Agentes ilimitados",
      "Todas las 91 tools de E1",
      "WhatsApp + Instagram + Telegram",
      "App Builder Pro (Audio Room, TikTok clone)",
      "Dominio personalizado",
      "Soporte prioritario",
    ],
    cta: "Empezar con Pro →",
    ctaVariant: "primary",
  },
  {
    id: "agency",
    name: "Agency",
    price: "$99",
    period: "/mes",
    desc: "Para agencias con múltiples clientes.",
    oros: 2000,
    highlight: false,
    tag: "White-Label",
    features: [
      "2000 oros/mes incluidos",
      "White-label completo (tu marca)",
      "Panel de afiliados + comisiones",
      "Sub-cuentas por cliente",
      "E2–E11 specialist agents",
      "Deploy VPS por cliente",
      "SLA + soporte dedicado",
    ],
    cta: "Contactar ventas",
    ctaVariant: "outline",
  },
];

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

        <a
          href="/api/demo/audio-room-static/"
          target="_blank"
          rel="noreferrer"
          className="landing-live-demo"
          data-testid="hero-live-demo-btn"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: "0.55rem",
            marginTop: "1.1rem",
            padding: "0.65rem 1.15rem",
            background: "linear-gradient(135deg, #2563EB22, #7C3AED22)",
            border: "1px solid rgba(37,99,235,0.35)",
            borderRadius: "999px",
            color: "var(--text-primary)",
            fontSize: "0.92rem",
            fontWeight: 600,
            textDecoration: "none",
            transition: "transform 0.18s ease, box-shadow 0.18s ease",
          }}
          onMouseEnter={(e) => { e.currentTarget.style.transform = "translateY(-2px)"; e.currentTarget.style.boxShadow = "0 8px 24px rgba(37,99,235,0.25)"; }}
          onMouseLeave={(e) => { e.currentTarget.style.transform = "translateY(0)"; e.currentTarget.style.boxShadow = "none"; }}
        >
          <span style={{ width: 8, height: 8, borderRadius: "50%", background: "#EF4444", display: "inline-block", boxShadow: "0 0 0 4px rgba(239,68,68,0.15)" }} />
          🎙 Probá una Audio Room en vivo — armada por App Builder Pro en 30 seg
          <span style={{ opacity: 0.6 }}>→</span>
        </a>

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

      {/* ── Pricing ──────────────────────────────────────────────────── */}
      <section className="landing-pricing" id="pricing" data-testid="pricing-section">
        <div className="pricing-header">
          <span className="pricing-eyebrow">Planes y precios</span>
          <h2>Empieza gratis. Escala cuando estés listo.</h2>
          <p className="pricing-sub">
            Sin contratos. Sin sorpresas. Cancela cuando quieras.
          </p>
        </div>
        <div className="pricing-grid">
          {PRICING_PLANS.map((plan) => (
            <div
              key={plan.id}
              className={`pricing-card${plan.highlight ? " pricing-card--highlight" : ""}`}
              data-testid={`pricing-${plan.id}`}
            >
              {plan.tag && (
                <div className="pricing-tag">{plan.tag}</div>
              )}
              <div className="pricing-plan-icon">
                {plan.id === "starter" && <Zap size={22} />}
                {plan.id === "pro" && <Users size={22} />}
                {plan.id === "agency" && <Building2 size={22} />}
              </div>
              <div className="pricing-name">{plan.name}</div>
              <div className="pricing-price">
                <span className="pricing-amount">{plan.price}</span>
                {plan.period && <span className="pricing-period">{plan.period}</span>}
              </div>
              <p className="pricing-desc">{plan.desc}</p>
              {plan.oros > 0 && (
                <div className="pricing-oros">
                  {plan.oros === 15 ? "15 oros de prueba" : `${plan.oros.toLocaleString()} oros/mes`}
                </div>
              )}
              <ul className="pricing-features">
                {plan.features.map((f, i) => (
                  <li key={i}>
                    <Check size={15} strokeWidth={2.5} className="pricing-check" />
                    {f}
                  </li>
                ))}
              </ul>
              <button
                className={plan.ctaVariant === "primary" ? "cta-primary" : plan.ctaVariant === "outline" ? "cta-outline" : "cta-secondary"}
                onClick={plan.id === "agency" ? () => window.location.href = "mailto:lluviaappstudio@gmail.com?subject=Agency Plan" : plan.id === "starter" ? onRegisterClick : onRegisterClick}
                style={{ width: "100%", marginTop: "auto" }}
                data-testid={`pricing-cta-${plan.id}`}
              >
                {plan.cta}
              </button>
            </div>
          ))}
        </div>
        <p className="pricing-note">
          ¿Necesitás más oros? Recargás desde el panel en cualquier momento. Oros no vencen.
        </p>
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
