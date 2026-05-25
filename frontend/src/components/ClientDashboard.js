/* ClientDashboard - Panel del usuario final
   Boss Console + Recarga oros + Push to GitHub + Settings */
import { useEffect, useState } from "react";
import { useAuth } from "../AuthContext";
import { useBranding } from "../BrandingContext";
import { ThemeToggle } from "../ThemeContext";
import { api, formatError } from "../api";
import BossConsole from "./BossConsole";
import SettingsTab from "./SettingsTab";
import Studio from "./Studio";
import AgentBuilder from "./AgentBuilder";

export default function ClientDashboard() {
  const { user, logout } = useAuth();
  const { branding } = useBranding();
  // Tab sincronizado con location.hash (#/settings, #/github, etc) para que
  // los enlaces internos (ej "Configurá tu GitHub") puedan saltar entre tabs.
  const hashToTab = (h) => {
    const key = (h || "").replace(/^#\/?/, "").trim();
    return ["chat", "recharge", "github", "settings", "studio", "myapps"].includes(key) ? key : "chat";
  };
  // Si volvemos desde PayPal con ?paypal=success o ?paypal=cancel, forzamos
  // el tab "recharge" para que el RechargeTab procese el callback.
  const initialTab = () => {
    const sp = new URLSearchParams(window.location.search);
    if (sp.get("paypal") === "success" || sp.get("paypal") === "cancel") {
      return "recharge";
    }
    return hashToTab(window.location.hash);
  };
  const [tab, setTab] = useState(initialTab);
  const [balance, setBalance] = useState(null);

  useEffect(() => {
    const onHash = () => setTab(hashToTab(window.location.hash));
    const onGoSettings = () => { window.location.hash = "#/settings"; setTab("settings"); };
    window.addEventListener("hashchange", onHash);
    window.addEventListener("lluvia:goto-settings", onGoSettings);
    return () => {
      window.removeEventListener("hashchange", onHash);
      window.removeEventListener("lluvia:goto-settings", onGoSettings);
    };
  }, []);

  const goTab = (k) => { setTab(k); window.location.hash = `#/${k}`; };

  useEffect(() => {
    api.get("/console/credits/me").then((r) => setBalance(r.data.balance)).catch(() => {});
    const t = setInterval(() => {
      api.get("/console/credits/me").then((r) => setBalance(r.data.balance)).catch(() => {});
    }, 15000);
    return () => clearInterval(t);
  }, []);

  const brandName = branding?.product_name || "Lluvia App Studio";

  return (
    <div className="client-dash" data-testid="client-dashboard">
      <header className="cd-header">
        <div className="cd-brand">
          <div className="cd-logo">{brandName.slice(0, 1)}</div>
          <div>
            <div className="cd-name">{brandName}</div>
            <div className="cd-user">{user?.name || user?.email}</div>
          </div>
        </div>
        <div className="cd-actions">
          {balance !== null && (
            <span className="cd-balance" data-testid="cd-balance">
              <strong>{balance}</strong> oros
            </span>
          )}
          <ThemeToggle />
          <button className="cd-logout" onClick={logout} data-testid="cd-logout">Salir</button>
        </div>
      </header>

      <div className="cd-tabs" data-testid="cd-tabs">
        {[
          ["chat", "Mis Agentes"],
          ["myapps", "Mis Apps"],
          ["studio", "🛠 Studio"],
          ["recharge", "Recargar Oros"],
          ["github", "Push a GitHub"],
          ["settings", "Mi Cuenta"],
        ].map(([k, l]) => (
          <button
            key={k}
            className={`cd-tab ${tab === k ? "active" : ""}`}
            onClick={() => goTab(k)}
            data-testid={`cd-tab-${k}`}
          >
            {l}
          </button>
        ))}
      </div>

      <main className="cd-main">
        {tab === "chat" && <BossConsole />}
        {tab === "myapps" && <AgentBuilder />}
        {tab === "studio" && <Studio />}
        {tab === "recharge" && <RechargeTab onTopup={() => api.get("/credits/me").then((r) => setBalance(r.data.balance))} />}
        {tab === "github" && <GitHubTab />}
        {tab === "settings" && <SettingsTab />}
      </main>
    </div>
  );
}

function RechargeTab({ onTopup }) {
  const [packs, setPacks] = useState({});
  const [activePromo, setActivePromo] = useState(null);
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const [success, setSuccess] = useState(null);

  useEffect(() => {
    api.get("/paypal/packs").then((r) => {
      setPacks(r.data.packs || {});
      setActivePromo(r.data.active_promo);
    }).catch((e) => setErr(formatError(e)));

    // Capturar el callback de PayPal: cuando PayPal redirige con ?paypal=success&token=ORDER_ID,
    // llamamos a /paypal/capture/{order_id} para acreditar los oros.
    const params = new URLSearchParams(window.location.search);
    const paypalStatus = params.get("paypal");
    const orderId = params.get("token");
    if (paypalStatus === "success" && orderId) {
      setBusy("capturing");
      api.post(`/paypal/capture/${orderId}`).then((r) => {
        setSuccess({
          oros: r.data.credited_oros,
          balance: r.data.balance,
          already: r.data.already_processed,
        });
        if (onTopup) onTopup();
      }).catch((e) => setErr(`Error capturando pago: ${formatError(e)}`))
        .finally(() => {
          setBusy("");
          // Limpiar la URL para que un refresh no reintente capturar
          const cleanUrl = window.location.pathname + window.location.hash;
          window.history.replaceState({}, "", cleanUrl);
        });
    } else if (paypalStatus === "cancel") {
      setErr("Cancelaste el pago. Si querés intentar de nuevo, elegí un pack abajo.");
      const cleanUrl = window.location.pathname + window.location.hash;
      window.history.replaceState({}, "", cleanUrl);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const buy = async (key) => {
    setBusy(key);
    setErr("");
    try {
      const { data } = await api.post("/paypal/create-order", { pack: key });
      if (data.approve_url) {
        window.location.href = data.approve_url;
      }
    } catch (e) {
      setErr(formatError(e));
      setBusy("");
    }
  };

  return (
    <div className="recharge-tab" data-testid="recharge-tab">
      <h2>Recarga tu cuenta</h2>
      <p className="hero-sub">
        Los oros se descuentan por cada mensaje, voz o acción que pides a los agentes.
        Sin caducidad, sin suscripción. Pagas solo cuando los necesitas.
      </p>
      {activePromo && (
        <div className="promo-banner" data-testid="active-promo">
          🎉 {activePromo.label} — descuento aplicado automáticamente
        </div>
      )}
      {busy === "capturing" && (
        <div className="alert" style={{ background: "#FEF3C7", borderColor: "#FCD34D", color: "#92400E" }}
             data-testid="paypal-capturing">
          ⏳ Confirmando tu pago con PayPal... no cierres la ventana.
        </div>
      )}
      {success && (
        <div className="alert" style={{ background: "#D1FAE5", borderColor: "#34D399", color: "#065F46" }}
             data-testid="paypal-success">
          ✅ {success.already
            ? "Este pago ya estaba procesado."
            : `¡Pago confirmado! Acreditamos ${success.oros} oros a tu cuenta.`}
          <strong> Saldo actual: {success.balance} oros.</strong>
        </div>
      )}
      {err && <div className="alert">{err}</div>}
      <div className="packs-grid">
        {Object.entries(packs).map(([key, p]) => (
          <div key={key} className={`pack-card ${p.popular ? "popular" : ""}`} data-testid={`pack-${key}`}>
            {p.popular && <div className="pack-tag">Más elegido</div>}
            <h3>{p.label}</h3>
            <div className="pack-price">${p.price_usd}<small>USD</small></div>
            <div className="pack-oros"><strong>{p.oros}</strong> oros</div>
            {p.original_oros && p.original_oros !== p.oros && (
              <div className="pack-saving">+{p.oros - p.original_oros} oros bonus</div>
            )}
            <button
              className="pack-buy"
              onClick={() => buy(key)}
              disabled={busy === key}
              data-testid={`buy-${key}`}
            >
              {busy === key ? "Conectando con PayPal..." : "Comprar con PayPal"}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

function GitHubTab() {
  const [settings, setSettings] = useState(null);
  const [apps, setApps] = useState([]);
  const [commitMsg, setCommitMsg] = useState("");
  const [history, setHistory] = useState([]);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [err, setErr] = useState("");

  const load = async () => {
    try {
      const [s, a, h] = await Promise.all([
        api.get("/me/settings"),
        api.get("/me/apps"),
        api.get("/me/github/history"),
      ]);
      setSettings(s.data);
      setApps(a.data.apps || []);
      setHistory(h.data.history || []);
    } catch (e) { setErr(formatError(e)); }
  };
  useEffect(() => { load(); }, []);

  const push = async () => {
    setBusy(true); setErr(""); setResult(null);
    try {
      const { data } = await api.post("/me/github/push", {
        commit_message: commitMsg || null,
      });
      setResult(data);
      await load();
    } catch (e) {
      setErr(formatError(e));
    } finally { setBusy(false); }
  };

  if (!settings) return <div className="empty">Cargando...</div>;
  const configured = settings.has_github_token && settings.github_repo;

  return (
    <div className="github-tab" data-testid="github-tab">
      <h2>Push a GitHub</h2>
      <p className="hero-sub">
        Empuja tu codigo generado a TU repositorio de GitHub con 1 click.
        Tu codigo, tu repo, tu propiedad.
      </p>

      {!configured && (
        <div className="warn-card" data-testid="github-not-configured">
          ⚠️ Falta configurar tu GitHub. Ve a <strong>Mi Cuenta → GitHub</strong> y pega:
          <ul>
            <li>Tu <strong>GITHUB_TOKEN</strong> (Personal Access Token, scope `repo`)</li>
            <li>El <strong>repositorio destino</strong> formato: <code>tu-usuario/nombre-del-repo</code></li>
          </ul>
          <a href="https://github.com/settings/tokens/new?scopes=repo&description=Lluvia+App+Studio"
             target="_blank" rel="noreferrer" className="login-btn">
            Crear mi GitHub Token
          </a>
        </div>
      )}

      {configured && (
        <>
          <div className="form-card">
            <strong>Repo destino:</strong> <code>{settings.github_repo}</code> · branch <code>{settings.github_branch || "main"}</code>
          </div>
          <div className="form-row" style={{ marginTop: "1rem" }}>
            <div className="field" style={{ flex: 1 }}>
              <label>Mensaje del commit (opcional)</label>
              <input
                value={commitMsg}
                onChange={(e) => setCommitMsg(e.target.value)}
                placeholder="backup automatico"
                data-testid="github-commit-msg"
              />
            </div>
          </div>
          <button
            className="login-btn"
            onClick={push}
            disabled={busy}
            data-testid="github-push-btn"
            style={{ marginTop: "1rem" }}
          >
            {busy ? "Empujando..." : "🚀 Push a mi GitHub ahora"}
          </button>
        </>
      )}

      {err && <div className="alert" style={{ marginTop: "1rem" }}>{err}</div>}
      {result && result.export_locked && (
        <div className="form-card" data-testid="export-locked-modal" style={{
          marginTop: "1rem", padding: "1.4rem 1.3rem",
          background: "linear-gradient(135deg, rgba(245,158,11,0.10), rgba(124,58,237,0.08))",
          border: "1px solid #F59E0B", borderRadius: 14,
        }}>
          <h3 style={{ margin: 0, fontSize: "1.15rem" }}>🔒 Exportación bloqueada</h3>
          <p style={{ margin: "0.6rem 0 0.9rem", lineHeight: 1.55, fontSize: "0.95rem" }}>
            {result.message}
          </p>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "0.5rem",
                        padding: "0.75rem", borderRadius: 10, background: "rgba(15,23,42,0.04)",
                        border: "1px solid rgba(15,23,42,0.08)", marginBottom: "0.9rem" }}>
            <div style={{ textAlign: "center" }}>
              <div style={{ fontSize: "0.7rem", color: "var(--text-muted)", textTransform: "uppercase" }}>Saldo</div>
              <div style={{ fontSize: "1.4rem", fontWeight: 800 }}>{result.balance ?? 0}</div>
            </div>
            <div style={{ textAlign: "center", borderLeft: "1px solid rgba(15,23,42,0.1)", borderRight: "1px solid rgba(15,23,42,0.1)" }}>
              <div style={{ fontSize: "0.7rem", color: "var(--text-muted)", textTransform: "uppercase" }}>Necesitas</div>
              <div style={{ fontSize: "1.4rem", fontWeight: 800, color: "#D97706" }}>{result.required ?? 50}</div>
            </div>
            <div style={{ textAlign: "center" }}>
              <div style={{ fontSize: "0.7rem", color: "var(--text-muted)", textTransform: "uppercase" }}>Te faltan</div>
              <div style={{ fontSize: "1.4rem", fontWeight: 800, color: "#7C3AED" }}>{result.missing ?? "?"}</div>
            </div>
          </div>
          <button onClick={() => { window.location.hash = "#/recharge"; }}
                  data-testid="export-locked-recharge-btn"
                  className="login-btn"
                  style={{ background: "linear-gradient(135deg,#F59E0B,#D97706)", border: 0, color: "#fff" }}>
            Recargar oros y desbloquear →
          </button>
        </div>
      )}
      {result && !result.export_locked && (
        <div className={`form-card ${result.ok ? "success-card" : "fail-card"}`} style={{ marginTop: "1rem" }}>
          <strong>{result.ok ? "✅ Push exitoso" : "❌ Push fallo"}</strong>
          <div style={{ fontSize: "0.85em" }}>Repo: <code>{result.repo}</code></div>
          {!result.ok && (
            <details style={{ marginTop: "0.5rem" }}>
              <summary>Ver error</summary>
              <pre style={{ fontSize: "0.75em" }}>{JSON.stringify(result.steps, null, 2)}</pre>
            </details>
          )}
        </div>
      )}

      <h3 style={{ marginTop: "2rem" }}>Apps generadas en tu workspace</h3>
      {apps.length === 0 ? (
        <div className="empty">Sin apps todavia. Crea una pidiéndole al agente "App Builder" en el chat.</div>
      ) : (
        <table className="ag-table">
          <thead><tr><th>Nombre</th><th>Tamaño</th><th>Modificado</th></tr></thead>
          <tbody>
            {apps.map((a) => (
              <tr key={a.name}>
                <td>{a.name}</td>
                <td>{Math.round((a.size_bytes || 0) / 1024)} KB</td>
                <td>{(a.modified || "").slice(0, 16).replace("T", " ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h3 style={{ marginTop: "2rem" }}>Historial de pushes</h3>
      {history.length === 0 ? (
        <div className="empty">Aun no haces pushes.</div>
      ) : (
        <table className="ag-table">
          <thead><tr><th>Fecha</th><th>Repo</th><th>Branch</th><th>Mensaje</th><th>OK</th></tr></thead>
          <tbody>
            {history.map((b) => (
              <tr key={b.id}>
                <td>{(b.ts || "").slice(0, 16).replace("T", " ")}</td>
                <td><code>{b.repo}</code></td>
                <td>{b.branch}</td>
                <td style={{ fontSize: "0.85em" }}>{(b.commit_message || "").slice(0, 40)}</td>
                <td>{b.success ? "✅" : "❌"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
