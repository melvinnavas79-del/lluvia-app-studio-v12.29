/* SettingsTab - configuración del usuario (GitHub + notificaciones + VPS + Telegram).
   Compartido entre ClientDashboard y AdminDashboard. */
import { useEffect, useState } from "react";
import { api, formatError } from "../api";
import VpsServersTab from "./VpsServersTab";

export default function SettingsTab() {
  const [activeSection, setActiveSection] = useState("github"); // github | vps | account
  const [form, setForm] = useState({
    github_token: "",
    github_repo: "",
    github_branch: "main",
    project_name: "",
    notify_email: "",
  });
  const [hasToken, setHasToken] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  useEffect(() => {
    api.get("/me/settings").then((r) => {
      setForm((f) => ({ ...f, ...r.data, github_token: "" }));
      setHasToken(!!r.data.has_github_token);
    }).catch(() => {});
  }, []);

  const save = async (e) => {
    e.preventDefault();
    setErr(""); setMsg("");
    try {
      const payload = { ...form };
      if (!payload.github_token) delete payload.github_token; // no resetear si vacio
      await api.put("/me/settings", payload);
      setMsg("Guardado correctamente.");
      setTimeout(() => setMsg(""), 3000);
      const r = await api.get("/me/settings");
      setHasToken(!!r.data.has_github_token);
      setForm((f) => ({ ...f, github_token: "" }));
    } catch (e2) { setErr(formatError(e2)); }
  };

  return (
    <div data-testid="settings-tab">
      <h2>Mi Cuenta</h2>

      {/* Sub-tabs */}
      <div style={{
        display: "flex", gap: "0.4rem", marginBottom: "1rem",
        borderBottom: "1px solid rgba(0,0,0,0.08)", paddingBottom: "0.5rem",
      }}>
        {[
          ["github", "🔧 GitHub"],
          ["vps", "🖥 Mis Servidores"],
          ["account", "⚙ Cuenta"],
        ].map(([k, l]) => (
          <button key={k} onClick={() => setActiveSection(k)}
            data-testid={`settings-section-${k}`}
            style={{
              padding: "0.45rem 0.9rem",
              background: activeSection === k ? "#5B8DEF" : "transparent",
              color: activeSection === k ? "#fff" : "var(--text-primary)",
              border: activeSection === k ? "none" : "1px solid rgba(0,0,0,0.12)",
              borderRadius: 8, cursor: "pointer", fontWeight: 600, fontSize: "0.85rem",
            }}>
            {l}
          </button>
        ))}
      </div>

      {activeSection === "vps" && <VpsServersTab />}

      {activeSection === "github" && (
      <form className="form-card" onSubmit={save}>
        <h3>GitHub</h3>
        <p style={{ color: "var(--text-secondary)", fontSize: "0.88rem", margin: "0 0 1rem" }}>
          Configurá tu token personal y tu repositorio destino para poder hacer <strong>Push</strong> de
          tu workspace a GitHub desde el chat o el botón superior.
        </p>
        <div className="field">
          <label>
            GITHUB_TOKEN
            {hasToken && <span style={{ color: "#059669", fontSize: "0.8em", marginLeft: "0.5rem" }}>
              ✓ Configurado (dejá vacío para mantenerlo)
            </span>}
          </label>
          <input
            type="password"
            value={form.github_token}
            onChange={(e) => setForm({ ...form, github_token: e.target.value })}
            placeholder={hasToken ? "(oculto, dejá vacío para no cambiar)" : "ghp_..."}
            data-testid="settings-github-token"
          />
          <small>
            Generalo en{" "}
            <a href="https://github.com/settings/tokens/new?scopes=repo" target="_blank" rel="noreferrer">
              github.com/settings/tokens
            </a> con scope <code>repo</code>
          </small>
        </div>
        <div className="field">
          <label>Repositorio destino (owner/repo)</label>
          <input
            value={form.github_repo || ""}
            onChange={(e) => setForm({ ...form, github_repo: e.target.value })}
            placeholder="tu-usuario/mi-app-lluvia"
            data-testid="settings-github-repo"
          />
        </div>
        <div className="form-row">
          <div className="field">
            <label>Branch</label>
            <input
              value={form.github_branch || "main"}
              onChange={(e) => setForm({ ...form, github_branch: e.target.value })}
              data-testid="settings-github-branch"
            />
          </div>
          <div className="field">
            <label>Nombre del proyecto</label>
            <input
              value={form.project_name || ""}
              onChange={(e) => setForm({ ...form, project_name: e.target.value })}
              placeholder="Mi App"
              data-testid="settings-project-name"
            />
          </div>
        </div>
        <CreateRepoCard hasToken={hasToken} onCreated={(repoName) => {
          setForm((f) => ({ ...f, github_repo: repoName }));
          setMsg(`✓ Repo creado y seleccionado como destino: ${repoName}`);
          setTimeout(() => setMsg(""), 6000);
        }} />
        <h3 style={{ marginTop: "1.5rem" }}>Notificaciones</h3>
        <div className="field">
          <label>Email de notificación</label>
          <input
            type="email"
            value={form.notify_email || ""}
            onChange={(e) => setForm({ ...form, notify_email: e.target.value })}
            placeholder="tu@email.com"
            data-testid="settings-notify-email"
          />
        </div>
        {err && <div className="alert">{err}</div>}
        {msg && <div className="success">{msg}</div>}
        <div style={{ display: "flex", gap: "0.65rem", marginTop: "1rem", flexWrap: "wrap" }}>
          <button className="login-btn" type="submit" data-testid="settings-save"
                  style={{ width: "auto", padding: "0.75rem 1.25rem" }}>
            Guardar configuración
          </button>
          <ValidateGitHubButton hasToken={hasToken} />
        </div>
      </form>
      )}

      {activeSection === "account" && <TelegramLinkCard />}
    </div>
  );
}

function ValidateGitHubButton({ hasToken }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const test = async () => {
    setBusy(true);
    setResult(null);
    try {
      const r = await api.post("/me/github/validate");
      setResult(r.data);
    } catch (e) {
      setResult({ ok: false, error: formatError(e) });
    } finally { setBusy(false); }
  };
  if (!hasToken) return null;
  return (
    <>
      <button type="button" className="copy-btn" onClick={test} disabled={busy}
              data-testid="github-validate-btn"
              style={{ padding: "0.75rem 1.25rem" }}>
        {busy ? "Validando..." : "Probar mi token de GitHub"}
      </button>
      {result && (
        <div style={{ flex: "1 1 100%", marginTop: "0.5rem" }}
             className={result.ok ? "success" : "alert"} data-testid="github-validate-result">
          {result.ok ? (
            <>
              ✅ Token válido. Usuario GitHub: <strong>{result.login}</strong>
              {result.repo_access === "writable" && <> · ✅ Tenés permisos de escritura en el repo</>}
              {result.repo_access === "not_found" && <> · ⚠ El repo no existe todavía; GitHub lo creará en el primer push si tu token tiene scope <code>repo</code></>}
              {result.repo_access === "read_only" && <> · ❌ Solo lectura sobre el repo (necesitás scope <code>repo</code> completo)</>}
              {!result.has_repo_scope && (
                <div style={{ marginTop: "0.4rem", color: "#92400E" }}>
                  ⚠ Tu token no tiene scope <code>repo</code>. Regeneralo con ese permiso o el push va a fallar.
                </div>
              )}
            </>
          ) : (
            <span style={{ whiteSpace: "pre-wrap" }}>❌ {result.error}</span>
          )}
        </div>
      )}
    </>
  );
}

function TelegramLinkCard() {
  const [code, setCode] = useState("");
  const [linked, setLinked] = useState([]);
  const [busy, setBusy] = useState(false);

  const refresh = () => {
    api.get("/me/telegram/status").then((r) => setLinked(r.data.linked_chats || [])).catch(() => {});
  };
  useEffect(() => { refresh(); }, []);

  const gen = async () => {
    setBusy(true);
    try {
      const { data } = await api.post("/me/telegram/code");
      setCode(data.code);
    } finally { setBusy(false); }
  };

  const unlink = async (chatId) => {
    if (!window.confirm("¿Desvincular este chat de Telegram?")) return;
    await api.delete(`/me/telegram/unlink/${chatId}`);
    refresh();
  };

  return (
    <div className="form-card" style={{ marginTop: "1.5rem" }} data-testid="telegram-link-card">
      <h3>Vincular Telegram</h3>
      <p style={{ color: "var(--text-secondary)", fontSize: "0.9rem", margin: "0 0 1rem" }}>
        Conectá tu chat de Telegram con esta cuenta para que el bot use tus oros y pueda
        ejecutar tools reales (push a GitHub, agendar citas, etc).
      </p>
      <button className="login-btn" type="button" onClick={gen} disabled={busy}
              data-testid="telegram-gen-code"
              style={{ width: "auto", padding: "0.65rem 1.25rem", marginTop: 0 }}>
        {busy ? "Generando..." : "Generar código de vinculación"}
      </button>
      {code && (
        <div style={{ marginTop: "1rem", padding: "1rem",
                      background: "var(--surface-warm)",
                      border: "1px solid var(--border)", borderRadius: 8 }}>
          <div style={{ fontSize: "0.85rem", color: "var(--text-muted)", marginBottom: "0.3rem" }}>
            Tu código (válido 15 min):
          </div>
          <code style={{ fontSize: "1.75rem", fontWeight: 700, letterSpacing: "0.1em",
                         color: "var(--brand-primary)", fontFamily: "var(--font-display)" }}
                data-testid="telegram-code-display">
            {code}
          </code>
          <p style={{ fontSize: "0.85rem", color: "var(--text-secondary)", margin: "0.6rem 0 0" }}>
            En Telegram, abrí tu bot y enviá: <code style={{ background: "var(--surface)" }}>/vincular {code}</code>
          </p>
        </div>
      )}
      {linked.length > 0 && (
        <div style={{ marginTop: "1rem" }}>
          <div style={{ fontSize: "0.85rem", color: "var(--text-muted)", marginBottom: "0.5rem" }}>
            Chats vinculados: {linked.length}
          </div>
          {linked.map((l) => (
            <div key={l.chat_id} style={{ display: "flex", justifyContent: "space-between",
                                          alignItems: "center", padding: "0.5rem 0",
                                          borderBottom: "1px solid var(--border)" }}>
              <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.85rem" }}>
                chat_id: {l.chat_id}
              </span>
              <button className="copy-btn" onClick={() => unlink(l.chat_id)}
                      data-testid={`telegram-unlink-${l.chat_id}`}>
                Desvincular
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}



// ====================================================================
// CREATE GITHUB REPO CARD — botón 1-click para crear un repo nuevo y
// dejarlo seleccionado como destino del próximo push, sin abrir GitHub.
// ====================================================================
function CreateRepoCard({ hasToken, onCreated }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [isPrivate, setIsPrivate] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [err, setErr] = useState("");

  const slug = name.toLowerCase().replace(/[^a-z0-9_.-]/g, "-").replace(/-+/g, "-").replace(/^-|-$/g, "").slice(0, 80);

  const create = async () => {
    if (!slug || slug.length < 2) { setErr("Poné un nombre de al menos 2 caracteres"); return; }
    setBusy(true); setErr(""); setResult(null);
    try {
      const r = await api.post("/me/github/create-repo", {
        name: slug, private: isPrivate, set_as_default: true,
      });
      setResult(r.data);
      onCreated && onCreated(r.data.repo);
    } catch (e) {
      setErr(formatError(e));
    } finally { setBusy(false); }
  };

  if (!hasToken) {
    return (
      <div style={{
        marginTop: "1rem", padding: "0.75rem 1rem", borderRadius: 10,
        background: "rgba(148,163,184,0.08)", border: "1px dashed rgba(148,163,184,0.4)",
        fontSize: "0.85rem", color: "var(--text-muted)",
      }} data-testid="create-repo-card-disabled">
        🔒 Guardá tu token de GitHub primero para poder crear repos desde acá.
      </div>
    );
  }

  return (
    <div style={{ marginTop: "1rem" }} data-testid="create-repo-card">
      {!open ? (
        <button
          type="button"
          onClick={() => setOpen(true)}
          data-testid="create-repo-toggle"
          style={{
            padding: "0.7rem 1.15rem", borderRadius: 10, fontWeight: 600, fontSize: "0.92rem",
            background: "linear-gradient(135deg,#0F172A,#1F2937)", color: "#fff",
            border: 0, cursor: "pointer", display: "inline-flex", alignItems: "center", gap: "0.5rem",
          }}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M12 .297a12 12 0 0 0-3.79 23.39c.6.11.82-.26.82-.58v-2.02c-3.34.72-4.04-1.61-4.04-1.61-.55-1.4-1.35-1.78-1.35-1.78-1.1-.75.08-.74.08-.74 1.22.09 1.86 1.25 1.86 1.25 1.09 1.86 2.85 1.32 3.54 1.01.11-.79.42-1.32.77-1.62-2.66-.3-5.47-1.33-5.47-5.93 0-1.31.47-2.38 1.24-3.22-.13-.31-.54-1.53.12-3.18 0 0 1.01-.32 3.3 1.23a11.5 11.5 0 0 1 6 0c2.29-1.55 3.3-1.23 3.3-1.23.66 1.65.25 2.87.12 3.18.78.84 1.24 1.91 1.24 3.22 0 4.61-2.81 5.62-5.48 5.92.43.37.81 1.1.81 2.22v3.29c0 .32.22.7.83.58A12 12 0 0 0 12 .297z"/></svg>
          Crear repo nuevo en GitHub
        </button>
      ) : (
        <div style={{
          padding: "1rem 1.1rem", borderRadius: 12,
          background: "var(--surface-elevated, rgba(15,23,42,0.04))",
          border: "1px solid var(--border, rgba(15,23,42,0.1))",
        }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.7rem" }}>
            <strong style={{ fontSize: "0.95rem" }}>📦 Crear repo nuevo en GitHub</strong>
            <button type="button" onClick={() => { setOpen(false); setResult(null); setErr(""); }}
                    data-testid="create-repo-close"
                    style={{ background: "transparent", border: 0, fontSize: "1.2rem", cursor: "pointer", color: "var(--text-muted)" }}>×</button>
          </div>
          <div className="field" style={{ marginBottom: "0.5rem" }}>
            <label style={{ fontSize: "0.8rem" }}>Nombre del repo</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="mi-app-audio-room"
              data-testid="create-repo-name"
              maxLength={80}
              autoFocus
            />
            {slug && slug !== name && (
              <small style={{ color: "var(--text-muted)", fontSize: "0.75rem" }}>
                Se guardará como: <code>{slug}</code>
              </small>
            )}
          </div>
          <label style={{ display: "flex", gap: "0.5rem", alignItems: "center", fontSize: "0.85rem", cursor: "pointer", margin: "0.6rem 0" }}>
            <input
              type="checkbox"
              checked={isPrivate}
              onChange={(e) => setIsPrivate(e.target.checked)}
              data-testid="create-repo-private"
            />
            🔒 Hacerlo privado (solo vos lo ves)
          </label>
          {err && <div className="alert" style={{ marginTop: "0.5rem", fontSize: "0.85rem" }}>{err}</div>}
          {result && result.ok && (
            <div className="success" data-testid="create-repo-result"
                 style={{ marginTop: "0.5rem", fontSize: "0.88rem" }}>
              {result.already_existed ? "ℹ️ El repo ya existía. " : "✅ "}
              Repo: <a href={result.html_url} target="_blank" rel="noreferrer">
                <strong>{result.repo}</strong>
              </a>
              <div style={{ fontSize: "0.8rem", marginTop: "0.3rem", color: "var(--text-muted)" }}>
                {result.message}
              </div>
            </div>
          )}
          <button
            type="button"
            onClick={create}
            disabled={busy || !slug}
            data-testid="create-repo-submit"
            style={{
              marginTop: "0.7rem", padding: "0.7rem 1.2rem", borderRadius: 10,
              background: "linear-gradient(135deg,#2563EB,#7C3AED)", color: "#fff",
              fontWeight: 700, border: 0, cursor: busy ? "wait" : "pointer",
              opacity: busy || !slug ? 0.6 : 1, width: "100%",
            }}
          >
            {busy ? "Creando en GitHub..." : "🚀 Crear y seleccionar como destino"}
          </button>
        </div>
      )}
    </div>
  );
}
