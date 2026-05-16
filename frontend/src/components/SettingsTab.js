/* SettingsTab - configuración del usuario (GitHub + notificaciones + Telegram).
   Compartido entre ClientDashboard y AdminDashboard. */
import { useEffect, useState } from "react";
import { api, formatError } from "../api";

export default function SettingsTab() {
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
        <button className="login-btn" type="submit" data-testid="settings-save" style={{ marginTop: "1rem" }}>
          Guardar configuración
        </button>
      </form>

      <TelegramLinkCard />
    </div>
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
