import { useState } from "react";
import { useAuth } from "../AuthContext";
import { formatError } from "../api";

export default function Login() {
  const { login } = useAuth();
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

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={onSubmit} data-testid="login-form">
        <div className="brand-mark">
          <span className="brand-dot" />
          <span>BOT // MULTIPLATAFORMA</span>
        </div>
        <h2>Acceso al Panel</h2>
        <p className="login-sub">
          Solo personal autorizado. Cada afiliado ve unicamente sus propias ventas.
        </p>

        <label>Email</label>
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="admin@admin.com"
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
      </form>
    </div>
  );
}
