/**
 * PreviewPanel — Preview en vivo estilo Lovable/Bolt.
 *
 * Features:
 *   - iframe con URL pública temporal (token auth, sin JWT)
 *   - SSE para status/reload/log events desde el servidor
 *   - Barra de estado: starting → ready → building → error
 *   - Panel de logs colapsable (últimas N líneas del proceso)
 *   - Botón de share URL temporal
 *   - Botón de abrir en nueva pestaña
 *   - Auto-refetch al detectar "ready" después de "building"
 *   - Mobile-friendly collapse
 */

import { useEffect, useRef, useState, useCallback } from "react";
import { api, formatError } from "../api";
import {
  ExternalLink, Copy, RefreshCw, ChevronDown, ChevronUp,
  Loader2, CheckCircle2, XCircle, AlertTriangle, Monitor,
  Smartphone, X,
} from "lucide-react";

const STATUS_CONFIG = {
  idle:      { label: "Sin preview",  color: "#6B7280", Icon: Monitor },
  starting:  { label: "Iniciando...", color: "#D97706", Icon: Loader2,  spin: true },
  ready:     { label: "En vivo",      color: "#059669", Icon: CheckCircle2 },
  building:  { label: "Compilando...",color: "#D97706", Icon: Loader2,  spin: true },
  crashed:   { label: "Error",        color: "#DC2626", Icon: XCircle },
  error:     { label: "Error",        color: "#DC2626", Icon: XCircle },
  stopped:   { label: "Detenido",     color: "#6B7280", Icon: Monitor },
};

export default function PreviewPanel({ appSlug, autoStart = false, onClose }) {
  const [status, setStatus]         = useState("idle");
  const [proxyUrl, setProxyUrl]     = useState("");
  const [shareUrl, setShareUrl]     = useState("");
  const [eventsUrl, setEventsUrl]   = useState("");
  const [logs, setLogs]             = useState([]);
  const [logsOpen, setLogsOpen]     = useState(false);
  const [mobile, setMobile]         = useState(false);
  const [copied, setCopied]         = useState(false);
  const [error, setError]           = useState("");
  const [reloadKey, setReloadKey]   = useState(0);
  const [iframeReady, setIframeReady] = useState(false);

  const iframeRef    = useRef(null);
  const evtSourceRef = useRef(null);
  const logsEndRef   = useRef(null);
  const started      = useRef(false);

  // ── SSE connection ─────────────────────────────────────────────────────────
  const connectSSE = useCallback((url) => {
    if (evtSourceRef.current) {
      evtSourceRef.current.close();
    }
    const es = new EventSource(url);
    evtSourceRef.current = es;

    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.type === "status") {
          setStatus(data.status);
        }
        if (data.type === "reload") {
          setStatus("building");
          // Small delay so the file write settles, then reload iframe
          setTimeout(() => {
            setReloadKey(k => k + 1);
            setStatus("ready");
            setIframeReady(false);
          }, 400);
          const fileList = data.files?.slice(0, 3).join(", ");
          if (fileList) addLog(`↺ Changed: ${fileList}`);
        }
        if (data.type === "log") {
          addLog(data.line);
        }
      } catch (_) {}
    };

    es.onerror = () => {
      // SSE reconnects automatically after error
    };

    return es;
  }, []);

  const addLog = (line) => {
    setLogs(prev => {
      const next = [...prev, line];
      return next.length > 200 ? next.slice(-200) : next;
    });
  };

  // Auto-scroll logs
  useEffect(() => {
    if (logsOpen && logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [logs, logsOpen]);

  // ── Start preview ──────────────────────────────────────────────────────────
  const startPreview = useCallback(async () => {
    if (!appSlug) return;
    setStatus("starting");
    setError("");
    setLogs([]);
    addLog("► Iniciando preview...");

    try {
      const { data } = await api.post(`/me/apps/${appSlug}/preview`);
      setProxyUrl(data.proxy_url);
      setShareUrl(data.share_url || "");
      setEventsUrl(data.events_url || "");
      setStatus(data.status || "ready");
      addLog(`✓ Preview listo en puerto ${data.port}`);
      if (data.share_url) addLog(`🔗 Share URL: ${data.share_url}`);
      if (data.events_url) connectSSE(data.events_url);
    } catch (e) {
      setStatus("error");
      const msg = formatError(e);
      setError(msg);
      addLog(`✗ Error: ${msg}`);
    }
  }, [appSlug, connectSSE]);

  // ── Auto-start ─────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!autoStart || !appSlug || started.current) return;
    started.current = true;
    startPreview();
  }, [autoStart, appSlug, startPreview]);

  // ── Cleanup SSE on unmount ─────────────────────────────────────────────────
  useEffect(() => {
    return () => {
      if (evtSourceRef.current) evtSourceRef.current.close();
    };
  }, []);

  // ── Status badge ───────────────────────────────────────────────────────────
  const cfg = STATUS_CONFIG[status] || STATUS_CONFIG.idle;
  const StatusIcon = cfg.Icon;

  // ── Copy share URL ─────────────────────────────────────────────────────────
  const copyShare = () => {
    const url = shareUrl
      ? `${window.location.origin}${shareUrl}`
      : `${window.location.origin}${proxyUrl}`;
    navigator.clipboard.writeText(url).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  // ── Open in new tab ────────────────────────────────────────────────────────
  const openExternal = () => {
    const url = shareUrl || proxyUrl;
    if (url) window.open(`${window.location.origin}${url}`, "_blank");
  };

  const canInteract = status === "ready" || status === "building";

  return (
    <div className="preview-panel" data-testid="preview-panel">
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div className="preview-header">
        <div className="preview-status-row">
          <div className="preview-status-badge" style={{ color: cfg.color }}>
            <StatusIcon
              size={13}
              strokeWidth={2.5}
              style={cfg.spin ? { animation: "spin 1s linear infinite" } : {}}
            />
            <span>{cfg.label}</span>
          </div>
          {appSlug && (
            <span className="preview-app-name">{appSlug}</span>
          )}
        </div>

        <div className="preview-actions">
          {/* Mobile/Desktop toggle */}
          <button
            className="preview-btn"
            onClick={() => setMobile(m => !m)}
            title={mobile ? "Vista escritorio" : "Vista móvil"}
          >
            {mobile ? <Monitor size={14} /> : <Smartphone size={14} />}
          </button>

          {/* Reload */}
          {canInteract && (
            <button
              className="preview-btn"
              onClick={() => { setReloadKey(k => k + 1); setIframeReady(false); }}
              title="Recargar"
            >
              <RefreshCw size={14} />
            </button>
          )}

          {/* Copy share URL */}
          {shareUrl && (
            <button
              className={`preview-btn${copied ? " preview-btn--success" : ""}`}
              onClick={copyShare}
              title="Copiar URL compartible"
            >
              <Copy size={14} />
              <span>{copied ? "¡Copiado!" : "Share"}</span>
            </button>
          )}

          {/* Open in new tab */}
          {canInteract && (
            <button className="preview-btn" onClick={openExternal} title="Abrir en nueva pestaña">
              <ExternalLink size={14} />
            </button>
          )}

          {/* Logs toggle */}
          <button
            className={`preview-btn${logsOpen ? " preview-btn--active" : ""}`}
            onClick={() => setLogsOpen(o => !o)}
            title="Logs del proceso"
          >
            {logsOpen ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
            <span>Logs</span>
          </button>

          {/* Close */}
          {onClose && (
            <button className="preview-btn preview-btn--danger" onClick={onClose} title="Cerrar preview">
              <X size={14} />
            </button>
          )}
        </div>
      </div>

      {/* ── Iframe area ────────────────────────────────────────────────────── */}
      <div className="preview-iframe-wrap" style={{ flex: 1 }}>
        {status === "idle" && (
          <div className="preview-empty">
            <Monitor size={40} strokeWidth={1} style={{ opacity: 0.2, marginBottom: "1rem" }} />
            <p>Preview no iniciado</p>
            <button className="cta-primary" onClick={startPreview} style={{ marginTop: "1rem" }}>
              ▶ Iniciar preview
            </button>
          </div>
        )}

        {status === "starting" && (
          <div className="preview-empty">
            <Loader2 size={32} strokeWidth={1.5} style={{ opacity: 0.4, animation: "spin 1s linear infinite", marginBottom: "1rem" }} />
            <p style={{ color: "var(--text-secondary)", fontSize: "0.9rem" }}>
              Arrancando tu app...
            </p>
            <p style={{ color: "var(--text-muted)", fontSize: "0.8rem", marginTop: "0.5rem" }}>
              Primera vez puede tardar ~30s (instalando dependencias)
            </p>
          </div>
        )}

        {(status === "crashed" || status === "error") && (
          <div className="preview-empty preview-empty--error">
            <XCircle size={36} strokeWidth={1.5} style={{ color: "#DC2626", opacity: 0.6, marginBottom: "1rem" }} />
            <p style={{ fontWeight: 600 }}>Preview falló</p>
            {error && <p style={{ color: "var(--text-muted)", fontSize: "0.85rem", marginTop: "0.5rem", maxWidth: 400 }}>{error}</p>}
            <button className="cta-primary" onClick={startPreview} style={{ marginTop: "1rem" }}>
              Reintentar
            </button>
            <button
              className="cta-secondary"
              onClick={() => setLogsOpen(true)}
              style={{ marginTop: "0.5rem" }}
            >
              Ver logs
            </button>
          </div>
        )}

        {canInteract && proxyUrl && (
          <div
            className="preview-iframe-container"
            style={{
              width: mobile ? "390px" : "100%",
              maxWidth: "100%",
              margin: mobile ? "0 auto" : undefined,
              height: "100%",
              position: "relative",
            }}
          >
            {!iframeReady && (
              <div className="preview-iframe-loading">
                <Loader2 size={20} strokeWidth={1.5} style={{ animation: "spin 1s linear infinite" }} />
              </div>
            )}
            <iframe
              ref={iframeRef}
              key={reloadKey}
              src={proxyUrl}
              title={`Preview: ${appSlug}`}
              className="preview-iframe"
              style={{ opacity: iframeReady ? 1 : 0.3, transition: "opacity 0.3s" }}
              onLoad={() => setIframeReady(true)}
              sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-modals"
            />
          </div>
        )}
      </div>

      {/* ── Logs panel ─────────────────────────────────────────────────────── */}
      {logsOpen && (
        <div className="preview-logs">
          <div className="preview-logs-header">
            <span>Logs del proceso</span>
            <button className="preview-btn" onClick={() => setLogs([])}>Limpiar</button>
          </div>
          <div className="preview-logs-body">
            {logs.length === 0 && (
              <span style={{ color: "var(--text-muted)", fontStyle: "italic" }}>Sin logs aún...</span>
            )}
            {logs.map((line, i) => (
              <div key={i} className={`preview-log-line${line.startsWith("✗") ? " preview-log-error" : line.startsWith("✓") ? " preview-log-ok" : ""}`}>
                {line}
              </div>
            ))}
            <div ref={logsEndRef} />
          </div>
        </div>
      )}
    </div>
  );
}
