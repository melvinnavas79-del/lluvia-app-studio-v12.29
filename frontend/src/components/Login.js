import { useState } from "react";
import { useAuth } from "../AuthContext";
import { useBranding } from "../BrandingContext";
import { formatError } from "../api";

export default function Login({ mode = "login", onBack }) {
  const { login, register } = useAuth();
  const { branding } = useBranding();
  const [isRegister, setIsRegister] = useState(mode === "register");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);

  const onSubmit = async (e) => {
    e.preventDefault();
    setErr("");
    setLoading(true);
    try {
      if (isRegister) {
        const data = await register(email.trim(), password, name.trim() || null);
        if (data?.trial_oros) {
          // bienvenida con oros de trial
          alert(`Bienvenido! Te regalamos ${data.trial_oros} oros de trial para que pruebes la plataforma.`);
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

  const productName = branding?.product_name || "Bot Multiplataforma";
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
        <h2>{isRegister ? "Crear cuenta gratis" : "Acceso al Panel"}</h2>
        <p className="login-sub">
          {isRegister
            ? "Te regalamos 50 oros de trial para que pruebes la plataforma sin compromiso."
            : (tagline || "Ingresa con tu email y password.")}
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

        <label>Password</label>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder={isRegister ? "Minimo 6 caracteres" : "••••••••"}
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
          className="login-toggle"
          onClick={() => { setIsRegister(!isRegister); setErr(""); }}
          data-testid="login-toggle-mode"
          style={{
            marginTop: "1rem", background: "transparent", border: "none",
            color: "#5fb4ff", fontSize: "0.85rem", cursor: "pointer", width: "100%",
            textDecoration: "underline",
          }}
        >
          {isRegister
            ? "Ya tengo cuenta → Entrar"
            : "Soy nuevo → Crear cuenta gratis (50 oros)"}
        </button>

        {branding?.support_email && (
          <p style={{ marginTop: "1.25rem", fontSize: "0.75rem", color: "#6c7280", textAlign: "center" }}>
            Soporte: {branding.support_email}
          </p>
        )}

        {onBack && (
          <button
            type="button"
            onClick={onBack}
            data-testid="login-back-public"
            style={{
              marginTop: "0.5rem", background: "transparent", border: "none",
              color: "#9ca3af", fontSize: "0.8rem", cursor: "pointer", width: "100%",
            }}
          >
            ← Volver al inicio
          </button>
        )}
      </form>
    </div>
  );
}
