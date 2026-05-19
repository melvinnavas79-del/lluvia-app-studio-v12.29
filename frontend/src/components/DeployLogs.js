import { useEffect, useRef, useState } from "react";

/**
 * DeployLogs — streaming en vivo de journalctl via WebSocket.
 * Props: vpsId, service (nombre del systemd unit), autoConnect (bool).
 */
const ANSI_RE = /\x1b\[[0-9;]*m/g;
const LEVEL_RE = {
  ERROR: /\b(ERROR|FATAL|CRITICAL|Traceback)\b/i,
  WARN: /\b(WARN|WARNING)\b/i,
  INFO: /\b(INFO|NOTICE)\b/i,
  DEBUG: /\b(DEBUG)\b/i,
};

export default function DeployLogs({ vpsId, service, autoConnect = true }) {
  const [lines, setLines] = useState([]);
  const [status, setStatus] = useState("idle"); // idle | connecting | live | closed | error
  const [filter, setFilter] = useState("ALL");
  const [autoScroll, setAutoScroll] = useState(true);
  const [serviceInput, setServiceInput] = useState(service || "");
  const wsRef = useRef(null);
  const logsContainerRef = useRef(null);
  const linesRef = useRef([]);

  const connect = (svc) => {
    if (!vpsId || !svc) return;
    if (wsRef.current) {
      try { wsRef.current.close(); } catch (_) {}
    }
    setLines([]);
    linesRef.current = [];
    setStatus("connecting");

    const token = localStorage.getItem("token");
    const backend = process.env.REACT_APP_BACKEND_URL || "";
    const wsProto = backend.startsWith("https") ? "wss" : "ws";
    const host = backend.replace(/^https?:\/\//, "");
    const wsUrl = `${wsProto}://${host}/api/me/vps/${vpsId}/logs/${svc}?token=${encodeURIComponent(token)}`;

    const ws = new WebSocket(wsUrl);
    ws.onopen = () => setStatus("live");
    ws.onmessage = (ev) => {
      const chunks = ev.data.split("\n");
      const incoming = chunks
        .filter(l => l.trim())
        .map(l => l.replace(ANSI_RE, ""));
      linesRef.current = [...linesRef.current, ...incoming].slice(-5000);
      setLines(linesRef.current);
    };
    ws.onerror = () => setStatus("error");
    ws.onclose = () => setStatus("closed");
    wsRef.current = ws;
  };

  const disconnect = () => {
    if (wsRef.current) {
      try { wsRef.current.close(); } catch (_) {}
    }
    setStatus("closed");
  };

  useEffect(() => {
    if (autoConnect && vpsId && service) connect(service);
    return () => disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vpsId, service, autoConnect]);

  useEffect(() => {
    if (autoScroll && logsContainerRef.current) {
      logsContainerRef.current.scrollTop = logsContainerRef.current.scrollHeight;
    }
  }, [lines, autoScroll]);

  const colorForLine = (line) => {
    if (LEVEL_RE.ERROR.test(line)) return "#FCA5A5";
    if (LEVEL_RE.WARN.test(line)) return "#FCD34D";
    if (LEVEL_RE.INFO.test(line)) return "#93C5FD";
    if (LEVEL_RE.DEBUG.test(line)) return "#9CA3AF";
    return "#D4D4D4";
  };

  const visible = filter === "ALL"
    ? lines
    : lines.filter(l => LEVEL_RE[filter]?.test(l));

  const statusBadge = {
    idle: { c: "#9CA3AF", t: "idle" },
    connecting: { c: "#FBBF24", t: "conectando…" },
    live: { c: "#10B981", t: "● en vivo" },
    closed: { c: "#9CA3AF", t: "cerrado" },
    error: { c: "#EF4444", t: "error" },
  }[status];

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", background: "#0F0F12" }}
         data-testid="deploy-logs">
      <div style={{
        padding: "0.4rem 0.8rem", background: "#1A1A1F",
        borderBottom: "1px solid rgba(255,255,255,0.08)",
        display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap",
      }}>
        <input
          value={serviceInput}
          onChange={(e) => setServiceInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && connect(serviceInput)}
          placeholder="lluvia-mi-app"
          data-testid="deploy-logs-service"
          style={{
            flex: 1, minWidth: 160, padding: "0.3rem 0.6rem", borderRadius: 4,
            background: "#0F0F12", color: "#E4E4E7", border: "1px solid rgba(255,255,255,0.15)",
            fontFamily: "monospace", fontSize: "0.82rem",
          }}
        />
        {status === "live" ? (
          <button onClick={disconnect} data-testid="deploy-logs-disconnect"
            style={{
              padding: "0.3rem 0.7rem", background: "#7F1D1D", color: "#fff",
              border: "none", borderRadius: 4, fontSize: "0.78rem", cursor: "pointer",
            }}>
            ⏹ Detener
          </button>
        ) : (
          <button onClick={() => connect(serviceInput)} disabled={!serviceInput}
            data-testid="deploy-logs-connect"
            style={{
              padding: "0.3rem 0.7rem", background: "#5B8DEF", color: "#fff",
              border: "none", borderRadius: 4, fontSize: "0.78rem", cursor: "pointer",
              opacity: serviceInput ? 1 : 0.5,
            }}>
            ▶ Stream en vivo
          </button>
        )}
        <select value={filter} onChange={(e) => setFilter(e.target.value)}
          data-testid="deploy-logs-filter"
          style={{
            padding: "0.3rem 0.5rem", borderRadius: 4, background: "#0F0F12",
            color: "#E4E4E7", border: "1px solid rgba(255,255,255,0.15)", fontSize: "0.78rem",
          }}>
          <option value="ALL">Todos</option>
          <option value="ERROR">Errores</option>
          <option value="WARN">Warnings</option>
          <option value="INFO">Info</option>
          <option value="DEBUG">Debug</option>
        </select>
        <label style={{
          color: "#E4E4E7", fontSize: "0.78rem", display: "flex",
          alignItems: "center", gap: 4, cursor: "pointer",
        }}>
          <input type="checkbox" checked={autoScroll}
            onChange={(e) => setAutoScroll(e.target.checked)} />
          Auto-scroll
        </label>
        <span style={{ color: statusBadge.c, fontSize: "0.78rem", fontWeight: 600 }}>
          {statusBadge.t}
        </span>
      </div>
      <div ref={logsContainerRef} style={{
        flex: 1, minHeight: 0, overflowY: "auto", padding: "0.6rem 0.8rem",
        fontFamily: "Menlo, Monaco, monospace", fontSize: "0.78rem",
        lineHeight: 1.5, color: "#D4D4D4",
      }}>
        {visible.length === 0 ? (
          <div style={{ color: "#6B7280", fontStyle: "italic" }}>
            {status === "live" ? "Esperando logs…" :
             status === "idle" ? "Ingresá el nombre del service y dale ▶ Stream en vivo." :
             status === "error" ? "Error de conexión. Verificá que el service exista." :
             "Sin conexión activa."}
          </div>
        ) : visible.map((l, i) => (
          <div key={i} style={{ color: colorForLine(l), whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
            {l}
          </div>
        ))}
      </div>
      <div style={{
        padding: "0.3rem 0.8rem", background: "#1A1A1F",
        borderTop: "1px solid rgba(255,255,255,0.08)",
        fontSize: "0.72rem", color: "#9CA3AF", display: "flex", justifyContent: "space-between",
      }}>
        <span>{lines.length} líneas en buffer</span>
        <button onClick={() => { linesRef.current = []; setLines([]); }}
          style={{ background: "transparent", border: "none", color: "#9CA3AF", cursor: "pointer", fontSize: "0.72rem" }}>
          🗑 Limpiar
        </button>
      </div>
    </div>
  );
}
