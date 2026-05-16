import { useEffect, useState } from "react";
import { api, formatError } from "../api";

export default function SuperAdminPanel() {
  const [tab, setTab] = useState("overview");
  return (
    <div className="super-admin" data-testid="super-admin-panel">
      <div className="sa-header">
        <h2 className="section-title" style={{ marginBottom: 0 }}>
          👑 Consola del Dueño · SuperAdmin
        </h2>
        <p className="hero-sub" style={{ marginTop: "0.25rem" }}>
          Control total · Bypass de oros · Backup directo a GitHub
        </p>
      </div>

      <div className="tabs sa-tabs" style={{ marginTop: "1rem" }}>
        {[
          ["overview", "📊 Overview"],
          ["sessions", "💬 Sesiones de todos"],
          ["users", "👥 Usuarios"],
          ["backup", "📦 Push & Backup"],
          ["integrations", "🔗 Integraciones"],
          ["content", "📝 Contenido del Sitio"],
          ["pricing", "💰 Precios de Templates"],
        ].map(([k, label]) => (
          <button
            key={k}
            className={`tab ${tab === k ? "active" : ""}`}
            onClick={() => setTab(k)}
            data-testid={`sa-tab-${k}`}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "overview" && <OverviewPanel />}
      {tab === "sessions" && <SessionsPanel />}
      {tab === "users" && <UsersPanel />}
      {tab === "backup" && <BackupPanel />}
      {tab === "integrations" && <IntegrationsPanel />}
      {tab === "content" && <SiteContentPanel />}
      {tab === "pricing" && <PricingPanel />}
    </div>
  );
}

function SiteContentPanel() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  const [ok, setOk] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => api.get("/site/content").then((r) => setData(r.data)).catch((e) => setErr(formatError(e)));
  useEffect(() => { load(); }, []);

  const update = (path, value) => {
    setData((prev) => {
      const next = JSON.parse(JSON.stringify(prev || {}));
      const parts = path.split(".");
      let cur = next;
      for (let i = 0; i < parts.length - 1; i++) {
        const p = parts[i];
        if (cur[p] == null) cur[p] = isNaN(parseInt(parts[i + 1])) ? {} : [];
        cur = cur[p];
      }
      cur[parts[parts.length - 1]] = value;
      return next;
    });
  };

  const save = async () => {
    setBusy(true); setErr(""); setOk("");
    try {
      const payload = {
        hero_tag: data.hero_tag,
        hero_title: data.hero_title,
        hero_title_accent: data.hero_title_accent,
        hero_sub: data.hero_sub,
        hero_cta_primary: data.hero_cta_primary,
        hero_cta_secondary: data.hero_cta_secondary,
        pillars: data.pillars,
        streaming: data.streaming,
        social: data.social,
      };
      const { data: saved } = await api.put("/site/content", payload);
      setData(saved);
      setOk("✓ Cambios guardados. Recarga la landing para verlos en vivo.");
    } catch (e) {
      setErr(formatError(e));
    } finally { setBusy(false); }
  };

  if (err) return <div className="alert">{err}</div>;
  if (!data) return <div className="empty">Cargando contenido...</div>;

  const inp = { padding: "0.7rem", background: "var(--surface)", border: "1px solid var(--border-strong)",
                borderRadius: "var(--r-md)", color: "var(--text-primary)", fontFamily: "var(--font-body)",
                fontSize: "0.92rem", width: "100%" };

  return (
    <div data-testid="site-content-panel" style={{ marginTop: "1.5rem" }}>
      <div className="form-card">
        <h3 style={{ fontFamily: "var(--font-display)", margin: "0 0 1rem" }}>Hero principal</h3>
        <label style={{ display: "block", fontSize: "0.78rem", color: "var(--text-muted)", marginBottom: "0.3rem" }}>Tag superior</label>
        <input style={inp} value={data.hero_tag || ""} onChange={(e) => update("hero_tag", e.target.value)} data-testid="content-hero-tag"/>
        <label style={{ display: "block", fontSize: "0.78rem", color: "var(--text-muted)", marginTop: "0.75rem", marginBottom: "0.3rem" }}>Título</label>
        <input style={inp} value={data.hero_title || ""} onChange={(e) => update("hero_title", e.target.value)} data-testid="content-hero-title"/>
        <label style={{ display: "block", fontSize: "0.78rem", color: "var(--text-muted)", marginTop: "0.75rem", marginBottom: "0.3rem" }}>Título (parte italic resaltada)</label>
        <input style={inp} value={data.hero_title_accent || ""} onChange={(e) => update("hero_title_accent", e.target.value)} data-testid="content-hero-accent"/>
        <label style={{ display: "block", fontSize: "0.78rem", color: "var(--text-muted)", marginTop: "0.75rem", marginBottom: "0.3rem" }}>Subtítulo</label>
        <textarea style={{ ...inp, minHeight: 90 }} value={data.hero_sub || ""} onChange={(e) => update("hero_sub", e.target.value)} data-testid="content-hero-sub"/>
        <div className="form-row" style={{ marginTop: "0.75rem" }}>
          <div>
            <label style={{ display: "block", fontSize: "0.78rem", color: "var(--text-muted)", marginBottom: "0.3rem" }}>Botón CTA primario</label>
            <input style={inp} value={data.hero_cta_primary || ""} onChange={(e) => update("hero_cta_primary", e.target.value)} data-testid="content-cta-primary"/>
          </div>
          <div>
            <label style={{ display: "block", fontSize: "0.78rem", color: "var(--text-muted)", marginBottom: "0.3rem" }}>Botón CTA secundario</label>
            <input style={inp} value={data.hero_cta_secondary || ""} onChange={(e) => update("hero_cta_secondary", e.target.value)} data-testid="content-cta-secondary"/>
          </div>
        </div>
      </div>

      <div className="form-card">
        <h3 style={{ fontFamily: "var(--font-display)", margin: "0 0 1rem" }}>Tres pilares</h3>
        {(data.pillars || []).map((p, i) => (
          <div key={i} style={{ marginBottom: "1.25rem", paddingBottom: "1rem", borderBottom: "1px solid var(--border)" }}>
            <div style={{ display: "flex", gap: "0.5rem", marginBottom: "0.5rem" }}>
              <input style={{ ...inp, flex: 1 }} placeholder="Tag (ej 01 · Multimedia)"
                     value={p.tag || ""} onChange={(e) => update(`pillars.${i}.tag`, e.target.value)}
                     data-testid={`content-pillar-${i}-tag`}/>
              <input style={{ ...inp, width: 100 }} placeholder="Color hex" value={p.accent || ""}
                     onChange={(e) => update(`pillars.${i}.accent`, e.target.value)}
                     data-testid={`content-pillar-${i}-accent`}/>
              <input style={{ ...inp, width: 120 }} placeholder="Icono lucide" value={p.icon || ""}
                     onChange={(e) => update(`pillars.${i}.icon`, e.target.value)}
                     data-testid={`content-pillar-${i}-icon`}/>
            </div>
            <input style={inp} placeholder="Título" value={p.title || ""}
                   onChange={(e) => update(`pillars.${i}.title`, e.target.value)}
                   data-testid={`content-pillar-${i}-title`}/>
            <textarea style={{ ...inp, minHeight: 60, marginTop: "0.5rem" }} placeholder="Descripción"
                      value={p.description || ""}
                      onChange={(e) => update(`pillars.${i}.description`, e.target.value)}
                      data-testid={`content-pillar-${i}-desc`}/>
            <textarea style={{ ...inp, minHeight: 60, marginTop: "0.5rem" }}
                      placeholder="Bullets (una por línea)"
                      value={(p.bullets || []).join("\n")}
                      onChange={(e) => update(`pillars.${i}.bullets`, e.target.value.split("\n"))}
                      data-testid={`content-pillar-${i}-bullets`}/>
          </div>
        ))}
      </div>

      <div className="form-card">
        <h3 style={{ fontFamily: "var(--font-display)", margin: "0 0 1rem" }}>Redes sociales (footer)</h3>
        {["tiktok", "instagram", "facebook", "youtube", "twitter", "linkedin"].map((k) => (
          <div key={k} style={{ marginBottom: "0.5rem" }}>
            <label style={{ display: "block", fontSize: "0.78rem", color: "var(--text-muted)", textTransform: "capitalize", marginBottom: "0.2rem" }}>{k}</label>
            <input style={inp} placeholder={`URL completa de ${k}`}
                   value={data.social?.[k] || ""}
                   onChange={(e) => update(`social.${k}`, e.target.value)}
                   data-testid={`content-social-${k}`}/>
          </div>
        ))}
      </div>

      <div className="form-card">
        <h3 style={{ fontFamily: "var(--font-display)", margin: "0 0 1rem" }}>Streaming (radio / video live)</h3>
        <label style={{ display: "block", fontSize: "0.78rem", color: "var(--text-muted)", marginBottom: "0.3rem" }}>URL del stream de radio (HLS/Icecast)</label>
        <input style={inp} value={data.streaming?.radio_stream_url || ""}
               onChange={(e) => update("streaming.radio_stream_url", e.target.value)}
               data-testid="content-radio-url"/>
        <label style={{ display: "block", fontSize: "0.78rem", color: "var(--text-muted)", marginTop: "0.75rem", marginBottom: "0.3rem" }}>URL "now playing" (metadata)</label>
        <input style={inp} value={data.streaming?.radio_now_playing_url || ""}
               onChange={(e) => update("streaming.radio_now_playing_url", e.target.value)}
               data-testid="content-radio-meta-url"/>
        <label style={{ display: "block", fontSize: "0.78rem", color: "var(--text-muted)", marginTop: "0.75rem", marginBottom: "0.3rem" }}>URL del video live (YouTube/Twitch/HLS)</label>
        <input style={inp} value={data.streaming?.video_live_url || ""}
               onChange={(e) => update("streaming.video_live_url", e.target.value)}
               data-testid="content-video-url"/>
        <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginTop: "0.75rem", cursor: "pointer" }}>
          <input type="checkbox" checked={!!data.streaming?.enabled}
                 onChange={(e) => update("streaming.enabled", e.target.checked)}
                 data-testid="content-streaming-enabled"/>
          <span>Activar streaming en la landing</span>
        </label>
      </div>

      <button className="login-btn" onClick={save} disabled={busy}
              data-testid="content-save-btn"
              style={{ width: "auto", padding: "0.8rem 1.75rem", marginTop: 0 }}>
        {busy ? "Guardando..." : "💾 Guardar todos los cambios"}
      </button>
      {ok && <div className="success" style={{ marginTop: "0.75rem" }} data-testid="content-save-ok">{ok}</div>}
      {err && <div className="alert" style={{ marginTop: "0.75rem" }} data-testid="content-save-err">{err}</div>}
    </div>
  );
}

function IntegrationsPanel() {
  const [status, setStatus] = useState(null);
  const [err, setErr] = useState("");
  const [magic, setMagic] = useState(null);
  const [busy, setBusy] = useState(false);

  const refresh = () => {
    api.get("/integrations/gmail/status")
      .then((r) => setStatus(r.data))
      .catch((e) => setErr(formatError(e)));
  };
  useEffect(() => { refresh(); }, []);

  const vincular = async () => {
    setBusy(true); setErr("");
    try {
      const { data } = await api.get("/integrations/gmail/oauth/magic-link");
      setMagic(data);
      // Abrir en nueva pestaña — funciona en desktop. En móvil dejamos la URL visible.
      window.open(data.url, "_blank", "noopener");
    } catch (e) {
      setErr(formatError(e));
    } finally { setBusy(false); }
  };

  const desvincular = async () => {
    if (!window.confirm("¿Desvincular Gmail Maestro?")) return;
    await api.post("/integrations/gmail/disconnect");
    setMagic(null);
    refresh();
  };

  if (err) return <div className="alert" data-testid="integrations-error">{err}</div>;
  if (!status) return <div className="empty">Cargando...</div>;

  return (
    <div data-testid="integrations-panel">
      <div className="form-card" style={{ marginTop: "1.5rem" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginBottom: "1rem" }}>
          <div style={{ width: 48, height: 48, borderRadius: 12,
                        background: "#FEE2E2", display: "flex",
                        alignItems: "center", justifyContent: "center", fontSize: "1.4rem" }}>
            📧
          </div>
          <div>
            <h3 style={{ margin: 0, fontFamily: "var(--font-display)", fontSize: "1.2rem" }}>
              Gmail Maestro
            </h3>
            <div style={{ color: "var(--text-muted)", fontSize: "0.88rem" }}>
              Agente 24/7 que lee y responde correos del cliente.
            </div>
          </div>
          <span className={`badge ${status.linked ? "ok" : "no"}`} style={{ marginLeft: "auto" }}>
            {status.linked ? "Vinculado" : "No vinculado"}
          </span>
        </div>

        {status.linked && status.account && (
          <div style={{ background: "var(--surface-soft)", padding: "0.85rem 1rem",
                        borderRadius: 8, marginBottom: "1rem", fontSize: "0.9rem",
                        display: "flex", flexDirection: "column", gap: "0.6rem" }}>
            <div>
              Cuenta de Google: <strong data-testid="gmail-linked-email">{status.account.google_email}</strong><br/>
              <span style={{ color: "var(--text-muted)", fontSize: "0.83rem" }}>
                Vinculada: {new Date(status.account.linked_at).toLocaleString()}
              </span>
            </div>
            <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "center" }}>
              <span style={{ fontSize: "0.78rem", color: "var(--text-muted)", flex: 1, minWidth: 200 }}>
                ⚠ Asegurate que esta sea la cuenta a la que <strong>te llegan los correos de tus clientes</strong>
                (no tu Gmail personal). Si necesitás cambiarla, desvinculá y vinculá la correcta.
              </span>
              <button
                className="copy-btn"
                onClick={desvincular}
                data-testid="gmail-unlink-btn-inline"
                style={{ background: "#DC2626", color: "#fff", borderColor: "#DC2626",
                         padding: "0.5rem 0.9rem", fontSize: "0.82rem", fontWeight: 600 }}
              >
                Desvincular y cambiar cuenta
              </button>
            </div>
          </div>
        )}

        {status.linked && <GmailMaestroSection />}

        <div style={{ marginBottom: "1rem", fontSize: "0.85rem", color: "var(--text-secondary)" }}>
          <div>Client ID: {status.client_id_configured ? "✓ configurado" : "✕ falta"}</div>
          <div>Client Secret: {status.client_secret_configured ? "✓ configurado" : "✕ falta"}</div>
        </div>

        {!status.linked ? (
          <button
            className="login-btn"
            onClick={vincular}
            disabled={busy || !status.client_id_configured || !status.client_secret_configured}
            data-testid="gmail-link-btn"
            style={{ width: "auto", padding: "0.75rem 1.5rem", marginTop: 0 }}
          >
            {busy ? "Generando enlace..." : "🔗 Vincular Gmail Maestro"}
          </button>
        ) : (
          <button
            className="login-btn"
            onClick={desvincular}
            data-testid="gmail-unlink-btn"
            style={{ width: "auto", padding: "0.75rem 1.5rem", marginTop: 0,
                     background: "#DC2626", borderColor: "#DC2626" }}
          >
            Desvincular
          </button>
        )}

        {magic && (
          <div style={{ marginTop: "1.5rem", padding: "1rem", borderRadius: 8,
                        background: "var(--surface-warm)", border: "1px solid var(--border)" }}>
            <strong style={{ display: "block", marginBottom: "0.4rem" }}>
              ¿Estás en el móvil o no se abrió la pestaña?
            </strong>
            <p style={{ fontSize: "0.85rem", color: "var(--text-secondary)", margin: "0 0 0.5rem" }}>
              Copiá y pegá este enlace en el navegador (válido 60 min):
            </p>
            <code style={{ display: "block", wordBreak: "break-all", padding: "0.6rem",
                           background: "var(--surface)", border: "1px solid var(--border)",
                           borderRadius: 6, fontSize: "0.78rem" }}
                  data-testid="gmail-magic-link-url">
              {magic.url}
            </code>
            <button
              className="copy-btn" style={{ marginTop: "0.6rem" }}
              onClick={() => { navigator.clipboard.writeText(magic.url); }}
              data-testid="gmail-magic-link-copy"
            >
              Copiar enlace
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function OverviewPanel() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    api.get("/super/overview").then((r) => setData(r.data)).catch((e) => setErr(formatError(e)));
  }, []);
  if (err) return <div className="alert">{err}</div>;
  if (!data) return <div className="empty">Cargando...</div>;
  return (
    <div style={{ marginTop: "1rem" }}>
      <div className="ag-stats">
        <Stat label="Usuarios" value={data.users} />
        <Stat label="Sesiones totales" value={data.sessions} />
        <Stat label="Agentes custom" value={data.custom_agents} />
        <Stat label="Citas reservadas" value={data.appointments} />
        <Stat label="Propuestas pendientes" value={data.proposals_pending} />
      </div>
      <h3>Últimas sesiones (todos los usuarios)</h3>
      <table className="ag-table" data-testid="sa-recent-sessions">
        <thead>
          <tr><th>Usuario</th><th>Agente</th><th>Título</th><th>Último mensaje</th><th>Actualizado</th></tr>
        </thead>
        <tbody>
          {data.recent_sessions.map((s) => (
            <tr key={s.id}>
              <td>{s.user_email}</td>
              <td>{s.agent_id}</td>
              <td>{s.title}</td>
              <td style={{ fontSize: "0.8em", color: "rgba(255,255,255,0.6)" }}>
                {(s.last_message_preview || "").slice(0, 60)}
              </td>
              <td>{(s.updated_at || "").slice(0, 16).replace("T", " ")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Stat({ label, value }) {
  return (
    <div className="ag-stat">
      <div className="ag-stat-label">{label}</div>
      <div className="ag-stat-num">{value}</div>
    </div>
  );
}

function SessionsPanel() {
  const [sessions, setSessions] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [activeSession, setActiveSession] = useState(null);
  const [takeoverText, setTakeoverText] = useState("");
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");

  const load = async () => {
    try {
      const { data } = await api.get("/super/sessions/all");
      setSessions(data.sessions || []);
    } catch (e) { setErr(formatError(e)); }
  };
  useEffect(() => { load(); }, []);

  const openSession = async (sid) => {
    setActiveId(sid);
    try {
      const { data } = await api.get(`/super/sessions/${sid}`);
      setActiveSession(data);
    } catch (e) { setErr(formatError(e)); }
  };

  const takeover = async () => {
    if (!takeoverText.trim() || !activeId) return;
    setErr(""); setMsg("");
    try {
      await api.post(`/super/sessions/${activeId}/takeover`, {
        text: takeoverText, as_role: "assistant",
      });
      setMsg("Mensaje inyectado como agente.");
      setTakeoverText("");
      setTimeout(() => setMsg(""), 3000);
      openSession(activeId);
    } catch (e) { setErr(formatError(e)); }
  };

  return (
    <div style={{ display: "grid", gridTemplateColumns: "320px 1fr", gap: "1rem", marginTop: "1rem" }}>
      <div style={{ maxHeight: 600, overflowY: "auto" }}>
        <h4 style={{ margin: "0 0 0.5rem" }}>Todas las sesiones ({sessions.length})</h4>
        {sessions.map((s) => (
          <div
            key={s.id}
            className={`bc-thread ${activeId === s.id ? "active" : ""}`}
            onClick={() => openSession(s.id)}
            style={{ cursor: "pointer", marginBottom: "0.5rem" }}
            data-testid={`sa-session-${s.id}`}
          >
            <div className="bc-thread-meta">
              <div className="bc-thread-title">{s.title || s.agent_id}</div>
              <div className="bc-thread-preview">
                {s.user_email} · {(s.last_message_preview || "").slice(0, 40)}
              </div>
            </div>
          </div>
        ))}
      </div>
      <div>
        {!activeSession ? (
          <div className="empty">Elige una sesión para verla y tomar control.</div>
        ) : (
          <>
            <div className="form-card" style={{ padding: "0.75rem 1rem" }}>
              <strong>{activeSession.title}</strong> · {activeSession.user_email} · agente: {activeSession.agent_id}
            </div>
            {err && <div className="alert">{err}</div>}
            {msg && <div className="success">{msg}</div>}
            <div className="cc-transcript" style={{ marginTop: "0.75rem", maxHeight: 420 }}>
              {(activeSession.messages || []).slice(-30).map((m, i) => (
                <div key={i} className={`cc-bubble ${m.role === "user" ? "user" : "assistant"}`}>
                  <span className="cc-role">{m.role}{m.superadmin_takeover ? " · 👑" : ""}:</span>
                  {m.content}
                </div>
              ))}
            </div>
            <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.75rem" }}>
              <input
                value={takeoverText}
                onChange={(e) => setTakeoverText(e.target.value)}
                placeholder="Escribir como agente (takeover)..."
                style={{ flex: 1 }}
                data-testid="sa-takeover-input"
              />
              <button className="login-btn" onClick={takeover} data-testid="sa-takeover-send">
                Inyectar
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function GmailMaestroSection() {
  const [metrics, setMetrics] = useState(null);
  const [recent, setRecent] = useState([]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  const refresh = () => {
    api.get("/integrations/gmail/maestro/metrics").then((r) => setMetrics(r.data)).catch(() => {});
    api.get("/integrations/gmail/maestro/recent").then((r) => setRecent(r.data.items || [])).catch(() => {});
  };
  useEffect(() => { refresh(); }, []);

  const process = async () => {
    setBusy(true); setMsg("");
    try {
      const { data } = await api.post("/integrations/gmail/maestro/process-inbox");
      setMsg(`✓ Procesados ${data.newly_processed ?? 0} correos nuevos (de ${data.total_unread ?? 0} no leídos)`);
      refresh();
    } catch (e) {
      setMsg(`✕ ${formatError(e)}`);
    } finally { setBusy(false); }
  };

  return (
    <div style={{ marginTop: "1.5rem", borderTop: "1px solid var(--border)", paddingTop: "1.25rem" }}>
      <h3 style={{ fontFamily: "var(--font-display)", margin: "0 0 1rem", fontSize: "1.05rem" }}>
        🤖 Agente Maestro Gmail
      </h3>
      <p style={{ color: "var(--text-secondary)", fontSize: "0.9rem", margin: "0 0 1rem" }}>
        Clasifica correos entrantes y genera borradores de respuesta en tu Gmail.
        Los drafts aparecen en gmail.com → Borradores listos para revisar y enviar.
      </p>
      <button className="login-btn" onClick={process} disabled={busy}
              data-testid="gmail-maestro-process"
              style={{ width: "auto", padding: "0.65rem 1.25rem", marginTop: 0 }}>
        {busy ? "Procesando..." : "▶ Procesar inbox ahora"}
      </button>
      {msg && (
        <div style={{ marginTop: "0.75rem", fontSize: "0.9rem",
                      color: msg.startsWith("✓") ? "var(--success)" : "var(--danger)" }}>
          {msg}
        </div>
      )}

      {metrics && (
        <div className="kpi-grid" style={{ marginTop: "1.25rem" }}>
          <div className="kpi"><div className="kpi-label">Procesados</div><div className="kpi-value">{metrics.total_processed}</div></div>
          <div className="kpi"><div className="kpi-label">Con borrador</div><div className="kpi-value">{metrics.with_drafts}</div></div>
          <div className="kpi"><div className="kpi-label">Min. ahorrados</div><div className="kpi-value">{metrics.estimated_minutes_saved}</div></div>
        </div>
      )}

      {recent.length > 0 && (
        <table className="ag-table" style={{ marginTop: "1.25rem" }}>
          <thead><tr><th>De</th><th>Asunto</th><th>Categoría</th><th>Draft</th></tr></thead>
          <tbody>
            {recent.slice(0, 10).map((r) => (
              <tr key={r.id} data-testid={`gmail-msg-${r.id}`}>
                <td>{(r.from || "").slice(0, 30)}</td>
                <td style={{ maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {r.subject}
                </td>
                <td><span className={`badge ${r.category === "lead-caliente" ? "ok" : r.category === "spam" ? "no" : "warn"}`}>
                  {r.category}
                </span></td>
                <td>{r.draft_id ? <span style={{ color: "var(--success)" }}>✓</span> : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function UsersPanel() {
  const [users, setUsers] = useState([]);
  const [err, setErr] = useState("");
  useEffect(() => {
    api.get("/super/users").then((r) => setUsers(r.data.users || [])).catch((e) => setErr(formatError(e)));
  }, []);
  if (err) return <div className="alert">{err}</div>;
  return (
    <table className="ag-table" data-testid="sa-users-table" style={{ marginTop: "1rem" }}>
      <thead>
        <tr><th>Email</th><th>Nombre</th><th>Rol</th><th>Balance</th><th>Gastado</th><th>Activo</th></tr>
      </thead>
      <tbody>
        {users.map((u) => (
          <tr key={u.id}>
            <td>{u.email}</td>
            <td>{u.name || "—"}</td>
            <td><span className={`chip status-${u.role === "admin" ? "applied" : "pending"}`}>{u.role}</span></td>
            <td style={{ color: "#ffc85a" }}>{u.balance} ⚜</td>
            <td>{u.lifetime_spent}</td>
            <td>{u.active === false ? "❌" : "✅"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function BackupPanel() {
  const [commitMessage, setCommitMessage] = useState("");
  const [branch, setBranch] = useState("main");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [history, setHistory] = useState([]);
  const [err, setErr] = useState("");

  const loadHistory = async () => {
    try {
      const { data } = await api.get("/super/github/history");
      setHistory(data.backups || []);
    } catch (_) {}
  };
  useEffect(() => { loadHistory(); }, []);

  const doPush = async () => {
    setBusy(true);
    setErr(""); setResult(null);
    try {
      const { data } = await api.post("/super/github/push", {
        commit_message: commitMessage || null,
        branch,
      });
      setResult(data);
      await loadHistory();
    } catch (e) {
      setErr(formatError(e));
    } finally { setBusy(false); }
  };

  return (
    <div style={{ marginTop: "1rem" }}>
      <div className="form-card" data-testid="sa-backup-form">
        <h3 style={{ marginTop: 0 }}>📦 Push & Backup a GitHub</h3>
        <p className="hero-sub">
          Empuja TODO el código `/app` a tu repo privado. Solo vos (SuperAdmin) ves esto;
          los clientes nunca acceden a tu código base.
        </p>
        <div className="form-row">
          <div className="field" style={{ flex: 2 }}>
            <label>Commit message</label>
            <input
              value={commitMessage}
              onChange={(e) => setCommitMessage(e.target.value)}
              placeholder="backup automático (default)"
              data-testid="sa-commit-msg"
            />
          </div>
          <div className="field">
            <label>Branch</label>
            <input
              value={branch}
              onChange={(e) => setBranch(e.target.value)}
              data-testid="sa-branch"
            />
          </div>
        </div>
        <button
          className="login-btn"
          onClick={doPush}
          disabled={busy}
          data-testid="sa-push-btn"
          style={{ marginTop: "0.75rem" }}
        >
          {busy ? "Empujando..." : "🚀 Push & Backup ahora"}
        </button>
      </div>

      {err && <div className="alert" style={{ marginTop: "1rem" }}>{err}</div>}
      {result && (
        <div className={`form-card ${result.ok ? "success-card" : "fail-card"}`} style={{ marginTop: "1rem" }}>
          <strong>{result.ok ? "✅ Push exitoso" : "❌ Push falló"}</strong>
          <div style={{ fontSize: "0.85em", marginTop: "0.5rem" }}>
            Repo: <code>{result.repo}</code> · Branch: <code>{result.branch}</code>
          </div>
          <details style={{ marginTop: "0.5rem" }}>
            <summary>Ver detalle por paso</summary>
            <pre style={{ fontSize: "0.75em", maxHeight: 300, overflow: "auto" }}>
              {JSON.stringify(result.steps, null, 2)}
            </pre>
          </details>
        </div>
      )}

      <h4 style={{ marginTop: "1.5rem" }}>Historial de backups</h4>
      {history.length === 0 ? (
        <div className="empty">Sin backups todavía.</div>
      ) : (
        <table className="ag-table">
          <thead><tr><th>Fecha</th><th>Por</th><th>Branch</th><th>Msg</th><th>OK</th></tr></thead>
          <tbody>
            {history.map((b) => (
              <tr key={b.id}>
                <td>{(b.ts || "").slice(0, 16).replace("T", " ")}</td>
                <td>{b.by}</td>
                <td>{b.branch}</td>
                <td style={{ fontSize: "0.85em" }}>{(b.commit_message || "").slice(0, 50)}</td>
                <td>{b.success ? "✅" : "❌"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}


// =====================================================================
// PRICING PANEL — control admin de precios de templates + threshold de export
// =====================================================================
function PricingPanel() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  const [ok, setOk] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () =>
    api.get("/admin/pricing")
      .then((r) => setData(r.data))
      .catch((e) => setErr(formatError(e)));
  useEffect(() => { load(); }, []);

  const updatePrice = (toolId, value) => {
    setData((prev) => ({
      ...prev,
      tool_prices: { ...prev.tool_prices, [toolId]: value },
    }));
  };

  const save = async () => {
    setBusy(true); setErr(""); setOk("");
    try {
      const r = await api.put("/admin/pricing", {
        tool_prices: data.tool_prices,
        min_balance_for_export: Number(data.min_balance_for_export),
      });
      setData(r.data);
      setOk("✓ Precios actualizados. Los cambios se aplican en el próximo ensamble.");
      setTimeout(() => setOk(""), 4000);
    } catch (e) {
      setErr(formatError(e));
    } finally {
      setBusy(false);
    }
  };

  if (!data) return <div style={{ padding: "1.5rem" }}>Cargando precios…</div>;

  const knownIds = Object.keys(data.tool_prices || {});

  return (
    <div className="sa-section" data-testid="pricing-panel" style={{ padding: "1rem" }}>
      <h3 style={{ marginTop: 0 }}>💰 Control de precios y candado de exportación</h3>
      <p style={{ color: "var(--text-muted)", fontSize: "0.9rem", lineHeight: 1.5 }}>
        Acá decidís cuánto cobrar por cada template que ensambla App Builder Pro y
        cuál es el saldo mínimo que un usuario debe tener para exportar el código a su GitHub.
        Los curiosos pueden ver la preview dentro de Lluvia, pero solo descargan el código si tienen oros.
      </p>

      {err && <div className="msg-error" style={{ marginTop: 12 }}>{err}</div>}
      {ok && <div className="msg-success" style={{ marginTop: 12 }}>{ok}</div>}

      <div style={{ marginTop: "1.4rem", padding: "1rem 1.1rem", background: "var(--surface-elevated, #0F172A0A)", borderRadius: 12, border: "1px solid var(--border, rgba(0,0,0,0.08))" }}>
        <h4 style={{ marginTop: 0, fontSize: "1rem" }}>🔒 Candado de exportación</h4>
        <p style={{ fontSize: "0.85rem", color: "var(--text-muted)", marginBottom: "0.6rem" }}>
          Saldo mínimo (oros) para desbloquear el push a GitHub. Si está por debajo, el usuario ve un modal premium en lugar de descargar.
        </p>
        <input
          type="number" min="0" max="10000"
          value={data.min_balance_for_export ?? 50}
          onChange={(e) => setData((p) => ({ ...p, min_balance_for_export: e.target.value }))}
          data-testid="pricing-min-balance"
          style={{ width: 120, padding: "0.55rem 0.7rem", fontSize: "1rem", borderRadius: 8, border: "1px solid var(--border, #ddd)", background: "var(--surface, #fff)", color: "var(--text-primary, #000)" }}
        />
        <span style={{ marginLeft: 10, color: "var(--text-muted)", fontSize: "0.88rem" }}>oros</span>
      </div>

      <div style={{ marginTop: "1.4rem" }}>
        <h4 style={{ fontSize: "1rem", marginBottom: "0.6rem" }}>📦 Precio por template</h4>
        <div style={{ display: "flex", flexDirection: "column", gap: "0.6rem" }}>
          {(data.templates || []).map((tpl) => {
            const isKnown = knownIds.includes(tpl.tool_id);
            const isComing = tpl.coming_soon;
            return (
              <div
                key={tpl.tool_id}
                data-testid={`pricing-row-${tpl.tool_id}`}
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr 140px",
                  gap: "0.8rem",
                  padding: "0.85rem 1rem",
                  background: isComing ? "rgba(148,163,184,0.08)" : "var(--surface-elevated, #0F172A05)",
                  borderRadius: 12,
                  border: "1px solid var(--border, rgba(0,0,0,0.08))",
                  alignItems: "center",
                  opacity: isComing ? 0.7 : 1,
                }}
              >
                <div>
                  <div style={{ fontWeight: 700, fontSize: "0.96rem" }}>
                    {tpl.name}
                    {isComing && <span style={{ marginLeft: 8, fontSize: "0.7rem", padding: "2px 7px", borderRadius: 4, background: "#94a3b8", color: "#fff", fontWeight: 600 }}>SOON</span>}
                  </div>
                  <div style={{ fontSize: "0.78rem", color: "var(--text-muted)", marginTop: 4 }}>
                    {tpl.stack} · {tpl.screens.join(" · ")}
                  </div>
                </div>
                <div>
                  <input
                    type="number" min="0" max="10000"
                    disabled={!isKnown || isComing}
                    value={data.tool_prices[tpl.tool_id] ?? tpl.default_price}
                    onChange={(e) => updatePrice(tpl.tool_id, e.target.value)}
                    data-testid={`pricing-input-${tpl.tool_id}`}
                    style={{
                      width: "100%", padding: "0.55rem 0.7rem", fontSize: "1rem",
                      borderRadius: 8, border: "1px solid var(--border, #ddd)",
                      background: "var(--surface, #fff)", color: "var(--text-primary, #000)",
                      textAlign: "right",
                    }}
                  />
                  <div style={{ fontSize: "0.7rem", color: "var(--text-muted)", textAlign: "right", marginTop: 2 }}>
                    oros · default {tpl.default_price}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div style={{ marginTop: "1.4rem", display: "flex", gap: "0.6rem", alignItems: "center" }}>
        <button
          onClick={save} disabled={busy}
          className="btn-primary"
          data-testid="pricing-save-btn"
          style={{
            padding: "0.7rem 1.3rem", borderRadius: 10, fontWeight: 700,
            background: "linear-gradient(135deg, #2563EB, #7C3AED)", color: "#fff", border: 0, cursor: busy ? "wait" : "pointer",
            opacity: busy ? 0.6 : 1,
          }}
        >
          {busy ? "Guardando..." : "Guardar precios"}
        </button>
        {data.updated_at && (
          <span style={{ fontSize: "0.78rem", color: "var(--text-muted)" }}>
            Última edición: {new Date(data.updated_at).toLocaleString()} · {data.updated_by}
          </span>
        )}
      </div>
    </div>
  );
}

