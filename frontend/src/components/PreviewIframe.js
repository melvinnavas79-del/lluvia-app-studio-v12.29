import { useEffect, useState, useRef } from "react";
import { api, formatError } from "../api";

/**
 * PreviewIframe — preview local de la app del workspace + screenshots Playwright.
 * Props: appSlug, autoStart (bool, default false).
 */
export default function PreviewIframe({ appSlug, autoStart = false }) {
  const [previewState, setPreviewState] = useState("idle"); // idle | starting | running | error | stopped
  const [previewUrl, setPreviewUrl] = useState("");
  const [error, setError] = useState("");
  const [mobile, setMobile] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [shooting, setShooting] = useState(false);
  const [lastShot, setLastShot] = useState(null);
  const heartbeatRef = useRef(null);
  const didAutoStart = useRef(false);

  // Heartbeat: cada 60s pingeamos /preview/status para que no expire por TTL
  useEffect(() => {
    if (previewState !== "running" || !appSlug) return;
    heartbeatRef.current = setInterval(() => {
      api.get(`/me/apps/${appSlug}/preview/status`).catch(() => {});
    }, 60000);
    return () => clearInterval(heartbeatRef.current);
  }, [previewState, appSlug]);

  // Auto-start al montar si el padre lo solicita (solo una vez)
  useEffect(() => {
    if (!autoStart || !appSlug || didAutoStart.current) return;
    didAutoStart.current = true;
    // Pequeño delay para que el DOM esté listo
    const t = setTimeout(() => startPreview(), 400);
    return () => clearTimeout(t);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Al desmontar el componente, NO matamos el preview (puede seguir corriendo)
  // si el usuario quiere apagarlo, hay un botón.

  const startPreview = async () => {
    if (!appSlug) return;
    setPreviewState("starting");
    setError("");
    try {
      const { data } = await api.post(`/me/apps/${appSlug}/preview`);
      setPreviewUrl(data.url);
      setPreviewState("running");
    } catch (e) {
      setError(formatError(e));
      setPreviewState("error");
    }
  };

  const stopPreview = async () => {
    if (!appSlug) return;
    try {
      await api.post(`/me/apps/${appSlug}/preview/stop`);
    } catch (_) {}
    setPreviewState("stopped");
    setPreviewUrl("");
  };

  const reload = () => setReloadKey(k => k + 1);

  const takeScreenshot = async () => {
    if (!appSlug || !previewUrl) return;
    setShooting(true);
    setLastShot(null);
    try {
      // Para Playwright necesitamos URL absoluta. El proxy interno no funciona desde
      // headless chromium del servidor (no tiene cookie/auth). Usamos URL relativa al backend.
      const absUrl = (process.env.REACT_APP_BACKEND_URL || "") + previewUrl;
      const { data } = await api.post(`/me/apps/${appSlug}/screenshot`, {
        url: absUrl.startsWith("http") ? absUrl : `http://localhost:8001${previewUrl}`,
        viewport_width: mobile ? 375 : 1280,
        viewport_height: mobile ? 812 : 800,
        full_page: false,
        wait_ms: 1800,
      });
      setLastShot({
        id: data.screenshot_id,
        url: (process.env.REACT_APP_BACKEND_URL || "") + data.image_url,
        taken_at: new Date().toLocaleTimeString(),
        size: data.size_bytes,
      });
    } catch (e) {
      setError(formatError(e));
    } finally {
      setShooting(false);
    }
  };

  if (!appSlug) {
    return (
      <div style={{ padding: "2rem", textAlign: "center", color: "var(--text-muted)" }}>
        Seleccioná una app primero.
      </div>
    );
  }

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column" }}
         data-testid="preview-iframe">
      <div style={{
        padding: "0.4rem 0.7rem", background: "var(--surface, #fafafa)",
        borderBottom: "1px solid rgba(0,0,0,0.08)",
        display: "flex", gap: "0.4rem", alignItems: "center", flexWrap: "wrap",
      }}>
        {previewState === "running" ? (
          <>
            <span style={{ color: "#10B981", fontSize: "0.78rem", fontWeight: 700 }}>
              ● Live
            </span>
            <button onClick={reload} data-testid="preview-reload"
              style={{ ...btnStyle, background: "#5B8DEF", color: "#fff" }}>
              🔄 Reload
            </button>
            <button onClick={() => setMobile(!mobile)} data-testid="preview-mobile-toggle"
              style={{ ...btnStyle, background: mobile ? "#5B8DEF" : "rgba(0,0,0,0.06)",
                       color: mobile ? "#fff" : "var(--text-primary)" }}>
              {mobile ? "📱 Móvil" : "💻 Desktop"}
            </button>
            <button onClick={takeScreenshot} disabled={shooting} data-testid="preview-screenshot"
              style={{ ...btnStyle, background: "#A855F7", color: "#fff", opacity: shooting ? 0.6 : 1 }}>
              {shooting ? "📸 …" : "📸 Screenshot"}
            </button>
            <button onClick={stopPreview} data-testid="preview-stop"
              style={{ ...btnStyle, background: "#FEE2E2", color: "#991B1B" }}>
              ⏹ Stop
            </button>
          </>
        ) : (
          <button onClick={startPreview} disabled={previewState === "starting"}
            data-testid="preview-start"
            style={{ ...btnStyle, background: "#10B981", color: "#fff",
                     opacity: previewState === "starting" ? 0.6 : 1 }}>
            {previewState === "starting" ? "⏳ Arrancando preview…" : "▶ Iniciar preview"}
          </button>
        )}
        {previewUrl && previewState === "running" && (
          <span style={{ marginLeft: "auto", fontSize: "0.72rem", color: "var(--text-muted)" }}>
            {previewUrl}
          </span>
        )}
      </div>

      {error && (
        <div style={{ padding: "0.5rem 0.8rem", background: "#FEE2E2", color: "#991B1B", fontSize: "0.82rem" }}>
          ⚠ {error}
        </div>
      )}

      <div style={{ flex: 1, minHeight: 0, display: "flex", background: "#1E1E1E", padding: "0.5rem", overflow: "auto" }}>
        {previewState === "running" && previewUrl ? (
          <iframe
            key={reloadKey}
            src={previewUrl}
            data-testid="preview-iframe-frame"
            title="Preview"
            style={{
              width: mobile ? 375 : "100%",
              height: mobile ? 812 : "100%",
              maxWidth: "100%",
              margin: "0 auto",
              border: "none",
              borderRadius: 8,
              background: "#fff",
              boxShadow: mobile ? "0 4px 20px rgba(0,0,0,0.5)" : "none",
            }}
            sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
          />
        ) : (
          <div style={{
            margin: "auto", textAlign: "center", color: "#9CA3AF",
            padding: "2rem", maxWidth: 480,
          }}>
            <div style={{ fontSize: "2.5rem", marginBottom: "0.5rem" }}>🎬</div>
            <div style={{ fontWeight: 700, color: "#E4E4E7", marginBottom: "0.4rem" }}>
              {previewState === "idle" && "Preview no iniciado"}
              {previewState === "starting" && "Arrancando uvicorn…"}
              {previewState === "stopped" && "Preview detenido"}
              {previewState === "error" && "Error al iniciar"}
            </div>
            <div style={{ fontSize: "0.85rem", lineHeight: 1.5 }}>
              {previewState === "starting" ?
                "Esto puede tardar 5-30s la primera vez (crea venv + instala deps)." :
                "Click en \"▶ Iniciar preview\" para arrancar tu app en un puerto temporal y verla acá mismo."}
            </div>
          </div>
        )}
      </div>

      {lastShot && (
        <div style={{
          padding: "0.5rem 0.8rem", background: "var(--surface, #fafafa)",
          borderTop: "1px solid rgba(0,0,0,0.08)",
          display: "flex", gap: "0.6rem", alignItems: "center", fontSize: "0.78rem",
        }}>
          <span style={{ color: "#10B981", fontWeight: 700 }}>📸 {lastShot.taken_at}</span>
          <a href={lastShot.url} target="_blank" rel="noreferrer"
             data-testid={`preview-screenshot-link-${lastShot.id}`}
             style={{ color: "#5B8DEF", fontWeight: 600 }}>
            Abrir ({Math.round(lastShot.size / 1024)}KB)
          </a>
          <img src={lastShot.url} alt="screenshot" style={{
            height: 40, borderRadius: 4, border: "1px solid rgba(0,0,0,0.08)",
          }} />
        </div>
      )}
    </div>
  );
}

const btnStyle = {
  padding: "0.35rem 0.7rem",
  border: "none",
  borderRadius: 4,
  fontSize: "0.78rem",
  fontWeight: 600,
  cursor: "pointer",
};
