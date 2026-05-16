import { useEffect, useState } from "react";
import { api, formatError } from "../api";
import { useBranding } from "../BrandingContext";

const MAX_LOGO_KB = 600;

export default function BrandingTab() {
  const { branding, setBranding } = useBranding();
  const [form, setForm] = useState(branding);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");

  useEffect(() => {
    setForm(branding);
  }, [branding]);

  const change = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const onLogo = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > MAX_LOGO_KB * 1024) {
      setErr(`El logo debe pesar menos de ${MAX_LOGO_KB} KB`);
      return;
    }
    const reader = new FileReader();
    reader.onload = () => change("logo_data_url", reader.result);
    reader.readAsDataURL(file);
  };

  const save = async (e) => {
    e.preventDefault();
    setSaving(true);
    setErr("");
    setMsg("");
    try {
      const { data } = await api.put("/branding", form);
      setBranding(data);
      setMsg("Branding actualizado. Los cambios ya estan visibles.");
      setTimeout(() => setMsg(""), 3500);
    } catch (e2) {
      setErr(formatError(e2));
    } finally {
      setSaving(false);
    }
  };

  const reset = async () => {
    if (!window.confirm("Restablecer al branding por defecto?")) return;
    setSaving(true);
    try {
      const { data } = await api.post("/branding/reset");
      setBranding(data);
      setForm(data);
      setMsg("Branding restablecido.");
      setTimeout(() => setMsg(""), 3500);
    } catch (e2) {
      setErr(formatError(e2));
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <h2 className="section-title">Personaliza tu marca</h2>
      <p className="hero-sub" style={{ marginBottom: "2rem" }}>
        Cambia el logo, los colores y los nombres sin tocar codigo. Cada cliente que compre una copia
        del bot puede tener su propia identidad visual en menos de un minuto.
      </p>

      {err && <div className="alert" data-testid="branding-error">{err}</div>}
      {msg && <div className="success" data-testid="branding-success">{msg}</div>}

      <div className="branding-grid">
        {/* Form */}
        <form className="form-card" onSubmit={save} data-testid="branding-form">
          <div className="field">
            <label>Nombre del producto</label>
            <input
              value={form.product_name || ""}
              onChange={(e) => change("product_name", e.target.value)}
              data-testid="branding-product-name"
              maxLength={80}
            />
          </div>

          <div className="field" style={{ marginTop: "1rem" }}>
            <label>Tagline</label>
            <input
              value={form.tagline || ""}
              onChange={(e) => change("tagline", e.target.value)}
              data-testid="branding-tagline"
              maxLength={200}
            />
          </div>

          <div className="form-row" style={{ marginTop: "1rem" }}>
            <ColorField label="Color primario" value={form.primary_color} onChange={(v) => change("primary_color", v)} testid="color-primary" />
            <ColorField label="Color de acento" value={form.accent_color} onChange={(v) => change("accent_color", v)} testid="color-accent" />
          </div>

          <div className="form-row">
            <ColorField label="Fondo" value={form.background_color} onChange={(v) => change("background_color", v)} testid="color-bg" />
            <ColorField label="Texto" value={form.text_color} onChange={(v) => change("text_color", v)} testid="color-text" />
          </div>

          <div className="field" style={{ marginTop: "1rem" }}>
            <label>Tema por defecto al abrir la app</label>
            <div style={{ display: "flex", gap: "0.5rem" }}>
              {["light", "dark"].map((t) => {
                const active = (form.default_theme || "light") === t;
                return (
                  <button
                    key={t}
                    type="button"
                    onClick={() => change("default_theme", t)}
                    data-testid={`theme-default-${t}`}
                    style={{
                      flex: 1, padding: "0.7rem 1rem",
                      background: active ? "var(--brand-primary)" : "var(--surface)",
                      color: active ? "#fff" : "var(--text-primary)",
                      border: `1px solid ${active ? "var(--brand-primary)" : "var(--border-strong)"}`,
                      borderRadius: "var(--r-md)",
                      cursor: "pointer", fontWeight: 600,
                      textTransform: "capitalize",
                      transition: "all .15s",
                    }}
                  >
                    {t === "light" ? "☀ Claro Premium" : "🌙 Oscuro Premium"}
                  </button>
                );
              })}
            </div>
            <small style={{ color: "var(--text-muted)", marginTop: "0.4rem", display: "block" }}>
              Define qué tema verán los visitantes la primera vez. Si lo cambian manualmente, se respeta su elección.
            </small>
          </div>

          <div className="form-row">
            <div className="field">
              <label>Empresa (opcional)</label>
              <input
                value={form.company_name || ""}
                onChange={(e) => change("company_name", e.target.value)}
                data-testid="branding-company"
                maxLength={120}
              />
            </div>
            <div className="field">
              <label>Email de soporte (opcional)</label>
              <input
                type="email"
                value={form.support_email || ""}
                onChange={(e) => change("support_email", e.target.value)}
                data-testid="branding-support"
                maxLength={120}
              />
            </div>
          </div>

          <div className="field" style={{ marginTop: "1rem" }}>
            <label>Logo (PNG/SVG/JPG · max {MAX_LOGO_KB} KB)</label>
            <input
              type="file"
              accept="image/*"
              onChange={onLogo}
              data-testid="branding-logo-file"
            />
            {form.logo_data_url && (
              <button
                type="button"
                className="copy-btn"
                style={{ marginTop: "0.5rem", alignSelf: "flex-start" }}
                onClick={() => change("logo_data_url", "")}
                data-testid="branding-logo-clear"
              >
                QUITAR LOGO
              </button>
            )}
          </div>

          <div style={{ display: "flex", gap: "0.75rem", marginTop: "1.5rem", flexWrap: "wrap" }}>
            <button className="login-btn" disabled={saving} data-testid="branding-save" style={{ flex: 1, minWidth: 200 }}>
              {saving ? "Guardando..." : "Guardar cambios"}
            </button>
            <button type="button" className="copy-btn" onClick={reset} data-testid="branding-reset">
              Restablecer
            </button>
          </div>
        </form>

        {/* Preview */}
        <div className="form-card preview-card" data-testid="branding-preview">
          <div className="preview-label">Preview en vivo</div>
          <div
            className="preview-box"
            style={{
              background: form.background_color,
              color: form.text_color,
              borderColor: `${form.accent_color}33`,
            }}
          >
            {form.logo_data_url ? (
              <img src={form.logo_data_url} alt="logo" className="preview-logo" />
            ) : (
              <div className="preview-logo-placeholder" style={{ background: `${form.primary_color}22`, color: form.primary_color }}>
                {(form.product_name || "B").slice(0, 1).toUpperCase()}
              </div>
            )}
            <div className="preview-name" style={{ color: form.text_color }}>
              {form.product_name || "Producto"}
            </div>
            <div className="preview-tag" style={{ color: `${form.text_color}aa` }}>
              {form.tagline || "Tu tagline aqui"}
            </div>
            <div style={{ display: "flex", gap: "0.5rem", marginTop: "1rem", flexWrap: "wrap" }}>
              <span className="preview-chip" style={{ background: form.primary_color, color: form.background_color }}>
                Primario
              </span>
              <span className="preview-chip" style={{ background: form.accent_color, color: form.background_color }}>
                Acento
              </span>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

function ColorField({ label, value, onChange, testid }) {
  return (
    <div className="field">
      <label>{label}</label>
      <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
        <input
          type="color"
          value={value || "#000000"}
          onChange={(e) => onChange(e.target.value)}
          data-testid={`${testid}-picker`}
          style={{ width: 44, height: 44, padding: 0, border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8, background: "transparent", cursor: "pointer" }}
        />
        <input
          value={value || ""}
          onChange={(e) => onChange(e.target.value)}
          data-testid={`${testid}-text`}
          placeholder="#RRGGBB"
          style={{ fontFamily: "JetBrains Mono, monospace", flex: 1 }}
        />
      </div>
    </div>
  );
}
