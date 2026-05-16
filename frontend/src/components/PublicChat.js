/* PublicChat - Marketing Landing con CTA registrarse */
import { useEffect, useState } from "react";
import axios from "axios";
import { useBranding } from "../BrandingContext";

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

  const brandColor = branding?.primary_color || "#5fb4ff";
  const brandName = branding?.product_name || branding?.company_name || "Lluvia App Studio";
  const tagline = branding?.tagline || "Agentes inteligentes que atienden tu negocio 24/7";

  return (
    <div className="landing" data-testid="public-chat-page">
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
        <div style={{ display: "flex", gap: "0.5rem" }}>
          <button
            className="pc-admin-link"
            onClick={onLoginClick}
            data-testid="public-login-btn"
          >
            Entrar
          </button>
          <button
            className="login-btn"
            onClick={onRegisterClick}
            data-testid="public-register-btn"
            style={{ background: brandColor, padding: "0.5rem 1.25rem" }}
          >
            Crear cuenta gratis
          </button>
        </div>
      </header>

      <section className="landing-hero">
        <h1>
          Tu agencia digital con <span style={{ color: brandColor }}>agentes que trabajan solos 24/7</span>
        </h1>
        <p className="landing-sub">
          Crea bots inteligentes para atender, reservar, cobrar y vender en automatico.
          Sin instalar nada, sin codigo. Pagas solo lo que consumes (modelo de oros).
        </p>
        <div className="landing-cta">
          <button
            className="cta-primary"
            onClick={onRegisterClick}
            style={{ background: brandColor }}
            data-testid="hero-register-btn"
          >
            Empezar gratis con 50 oros 🎁
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
          ✓ Sin tarjeta de credito · ✓ 50 oros gratis al registrarte · ✓ Tu codigo, tu GitHub
        </p>
      </section>

      <section className="landing-features">
        <h2>Que puedes hacer</h2>
        <div className="feature-grid">
          <div className="feature-card">
            <div className="feature-icon">🤖</div>
            <h3>Crea tus propios agentes</h3>
            <p>Dile al "Arquitecto" que necesitas un bot para tu negocio. En segundos lo crea con su personalidad, voz y herramientas.</p>
          </div>
          <div className="feature-card">
            <div className="feature-icon">📅</div>
            <h3>Reservas reales</h3>
            <p>Tus agentes reservan citas en una base de datos real, validan horarios y evitan duplicados.</p>
          </div>
          <div className="feature-card">
            <div className="feature-icon">💳</div>
            <h3>Cobros con PayPal</h3>
            <p>Genera ordenes de pago profesionales que tus clientes pagan con 1 click. Sin comisiones extras.</p>
          </div>
          <div className="feature-card">
            <div className="feature-icon">🗣️</div>
            <h3>Voz natural</h3>
            <p>Whisper + TTS de OpenAI. Cada agente tiene su propia voz. Modo Call Center continuo disponible.</p>
          </div>
          <div className="feature-card">
            <div className="feature-icon">📦</div>
            <h3>Push a tu GitHub</h3>
            <p>Empuja todo el codigo generado a TU repositorio con 1 click. Tu trabajo, tu propiedad.</p>
          </div>
          <div className="feature-card">
            <div className="feature-icon">📱</div>
            <h3>Telegram + Web</h3>
            <p>Tus agentes responden tambien por Telegram. Tus clientes los acceden desde cualquier canal.</p>
          </div>
        </div>
      </section>

      <section className="landing-agents">
        <h2>Agentes disponibles para inspirarte</h2>
        <div className="landing-agents-grid">
          {agents.map((a) => (
            <div key={a.id} className="landing-agent-card" data-testid={`landing-agent-${a.id}`}>
              <div className="landing-agent-emoji" style={{ background: a.color }}>{a.emoji}</div>
              <div>
                <div className="landing-agent-name">{a.name}</div>
                <div className="landing-agent-tag">{a.tagline}</div>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="landing-cta-final">
        <h2>Listo para empezar?</h2>
        <p>50 oros gratis te alcanzan para ~50 mensajes de prueba. Cuando los acabes, recarga lo que necesites.</p>
        <button
          className="cta-primary"
          onClick={onRegisterClick}
          style={{ background: brandColor }}
          data-testid="footer-register-btn"
        >
          Crear mi cuenta gratis →
        </button>
      </section>

      <footer className="pc-footer">
        Powered by {brandName} · {new Date().getFullYear()}
      </footer>
    </div>
  );
}
