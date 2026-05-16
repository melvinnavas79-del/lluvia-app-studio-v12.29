/* ClientDashboard - Panel del usuario final
   Boss Console + Recarga oros + Push to GitHub + Settings */
import { useEffect, useState } from "react";
import { useAuth } from "../AuthContext";
import { useBranding } from "../BrandingContext";
import { ThemeToggle } from "../ThemeContext";
import { api, formatError } from "../api";
import BossConsole from "./BossConsole";
import SettingsTab from "./SettingsTab";

export default function ClientDashboard() {
  const { user, logout } = useAuth();
  const { branding } = useBranding();
  // Tab sincronizado con location.hash (#/settings, #/github, etc) para que
  // los enlaces internos (ej "Configurá tu GitHub") puedan saltar entre tabs.
  const hashToTab = (h) => {
    const key = (h || "").replace(/^#\/?/, "").trim();
    return ["chat", "recharge", "github", "settings"].includes(key) ? key : "chat";
  };
  const [tab, setTab] = useState(() => hashToTab(window.location.hash));
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

  useEffect(() => {
    api.get("/paypal/packs").then((r) => {
      setPacks(r.data.packs || {});
      setActivePromo(r.data.active_promo);
    }).catch((e) => setErr(formatError(e)));
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
      {result && (
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
