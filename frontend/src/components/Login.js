import { useState } from "react";
import { useAuth } from "../AuthContext";
import { useBranding } from "../BrandingContext";
import { formatError } from "../api";

export default function Login({ onBack }) {
  const { login } = useAuth();
  const { branding } = useBranding();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);

  const onSubmit = async (e) => {
    e.preventDefault();
    setErr("");
    setLoading(true);
    try {
      await login(email.trim(), password);
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
        <h2>Acceso al Panel</h2>
        <p className="login-sub">
          {tagline || "Solo personal autorizado. Cada afiliado ve unicamente sus propias ventas."}
        </p>

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
          placeholder="••••••••"
          required
          data-testid="login-password"
          autoComplete="current-password"
        />

        {err && <div className="login-err" data-testid="login-error">{err}</div>}

        <button
          type="submit"
          className="login-btn"
          disabled={loading}
          data-testid="login-submit"
        >
          {loading ? "Entrando..." : "Entrar"}
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
              marginTop: "0.75rem", background: "transparent", border: "none",
              color: "#9ca3af", fontSize: "0.8rem", cursor: "pointer", width: "100%",
            }}
          >
            ← Volver al chat publico
          </button>
        )}
      </form>
    </div>
  );
}
