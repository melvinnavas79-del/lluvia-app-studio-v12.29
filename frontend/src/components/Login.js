import { useEffect, useState } from "react";
import { useAuth } from "../AuthContext";
import { useBranding } from "../BrandingContext";
import { api, formatError } from "../api";

export default function Login({ mode = "login", onBack }) {
  const { login, register } = useAuth();
  const { branding } = useBranding();
  const [isRegister, setIsRegister] = useState(mode === "register");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);
  const [trialOros, setTrialOros] = useState(15);

  useEffect(() => {
    // Leer oros de trial desde site_content (configurable por SuperAdmin)
    api.get("/site/content").then((r) => {
      if (typeof r.data?.trial_oros === "number") {
        setTrialOros(r.data.trial_oros);
      }
    }).catch(() => {});
  }, []);

  const onSubmit = async (e) => {
    e.preventDefault();
    setErr("");
    setLoading(true);
    try {
      if (isRegister) {
        const data = await register(email.trim(), password, name.trim() || null);
        if (data?.trial_oros) {
          alert(`¡Bienvenido! Te regalamos ${data.trial_oros} oros de trial para que pruebes la plataforma.`);
        }
      } else {
        await login(email.trim(), password);
      }
    } catch (e2) {
      setErr(formatError(e2));
    } finally {
      setLoading(false);
    }
  };

  const productName = branding?.product_name || "Lluvia App Studio";
  const tagline = branding?.tagline || "";

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={onSubmit} data-testid="login-form">
        <div className="brand-mark" style={{ alignItems: "center" }}>
          {branding?.logo_data_url ? (
            <img src={branding.logo_data_url} alt="logo" style={{ height: 26, width: "auto", objectFit: "contain" }} />
          ) : (
            <span className="brand-dot" />
          )}
          <span data-testid="brand-product-name">{productName.toUpperCase()}</span>
        </div>

        {isRegister && (
          <span className="trial-badge" data-testid="trial-badge">
            🎁 {trialOros} oros de regalo
          </span>
        )}

        <h2>{isRegister ? "Crea tu cuenta" : "Bienvenido de vuelta"}</h2>
        <p className="login-sub">
          {isRegister
            ? `Te regalamos ${trialOros} oros de trial. Sin tarjeta, sin compromiso.`
            : (tagline || "Ingresa con tu email y contraseña.")}
        </p>

        {isRegister && (
          <>
            <label>Tu nombre (opcional)</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Tu nombre"
              data-testid="register-name"
              autoComplete="name"
            />
          </>
        )}

        <label>Email</label>
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="tu@email.com"
          required
          data-testid="login-email"
          autoComplete="email"
        />

        <label>Contraseña</label>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder={isRegister ? "Mínimo 6 caracteres" : "••••••••"}
          required
          minLength={isRegister ? 6 : 1}
          data-testid="login-password"
          autoComplete={isRegister ? "new-password" : "current-password"}
        />

        {err && <div className="login-err" data-testid="login-error">{err}</div>}

        <button
          type="submit"
          className="login-btn"
          disabled={loading}
          data-testid="login-submit"
        >
          {loading
            ? (isRegister ? "Creando cuenta..." : "Entrando...")
            : (isRegister ? "Crear cuenta gratis" : "Entrar")}
        </button>

        <button
          type="button"
          className="login-btn login-toggle"
          onClick={() => { setIsRegister(!isRegister); setErr(""); }}
          data-testid="login-toggle-mode"
        >
          {isRegister
            ? "¿Ya tienes cuenta? Inicia sesión"
            : `¿Eres nuevo? Crear cuenta (${trialOros} oros)`}
        </button>

        {branding?.support_email && (
          <p style={{ marginTop: "1.25rem", fontSize: "0.78rem", color: "var(--text-muted)", textAlign: "center" }}>
            Soporte: {branding.support_email}
          </p>
        )}

        {onBack && (
          <button
            type="button"
            onClick={onBack}
            data-testid="login-back-public"
            style={{
              marginTop: "0.4rem", background: "transparent", border: "none",
              color: "var(--text-muted)", fontSize: "0.82rem", cursor: "pointer", width: "100%",
              padding: "0.5rem",
            }}
          >
            ← Volver al inicio
          </button>
        )}
      </form>
    </div>
  );
}
