import { useEffect, useRef, useState } from "react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";

/**
 * VpsTerminal — terminal interactiva via WebSocket SSH (PTY).
 * Props: vpsId, vpsName (opcional, para el banner).
 */
export default function VpsTerminal({ vpsId, vpsName }) {
  const containerRef = useRef(null);
  const termRef = useRef(null);
  const wsRef = useRef(null);
  const [status, setStatus] = useState("connecting"); // connecting | connected | disconnected | error

  useEffect(() => {
    if (!vpsId || !containerRef.current) return;
    const token = localStorage.getItem("token");
    if (!token) {
      setStatus("error");
      return;
    }

    const term = new Terminal({
      cursorBlink: true,
      fontSize: 13,
      fontFamily: 'Menlo, Monaco, "Courier New", monospace',
      theme: {
        background: "#0F0F12",
        foreground: "#E4E4E7",
        cursor: "#5B8DEF",
        selectionBackground: "rgba(91,141,239,0.3)",
      },
      scrollback: 5000,
      allowProposedApi: true,
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(containerRef.current);
    setTimeout(() => fit.fit(), 100);
    termRef.current = term;

    // Construir URL WS desde REACT_APP_BACKEND_URL
    const backend = process.env.REACT_APP_BACKEND_URL || "";
    const wsProto = backend.startsWith("https") ? "wss" : "ws";
    const host = backend.replace(/^https?:\/\//, "");
    const wsUrl = `${wsProto}://${host}/api/me/vps/${vpsId}/terminal?token=${encodeURIComponent(token)}`;

    const ws = new WebSocket(wsUrl);
    ws.onopen = () => {
      setStatus("connected");
      // Mandar tamaño inicial
      ws.send(`\x1bRESIZE:${term.cols},${term.rows}`);
    };
    ws.onmessage = (ev) => term.write(ev.data);
    ws.onclose = () => setStatus("disconnected");
    ws.onerror = () => setStatus("error");
    wsRef.current = ws;

    term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) ws.send(data);
    });

    // Resize handler
    const onResize = () => {
      try {
        fit.fit();
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(`\x1bRESIZE:${term.cols},${term.rows}`);
        }
      } catch (_) {}
    };
    window.addEventListener("resize", onResize);

    return () => {
      window.removeEventListener("resize", onResize);
      try { ws.close(); } catch (_) {}
      try { term.dispose(); } catch (_) {}
    };
  }, [vpsId]);

  const reconnect = () => {
    // El useEffect se vuelve a montar al cambiar la key. Lo hacemos via forceUpdate.
    if (wsRef.current) {
      try { wsRef.current.close(); } catch (_) {}
    }
    setStatus("connecting");
    // Forzar reconexion manual:
    window.location.reload();
  };

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", background: "#0F0F12" }}
         data-testid="vps-terminal">
      <div style={{
        padding: "0.4rem 0.8rem", background: "#1A1A1F", color: "#E4E4E7",
        fontSize: "0.78rem", fontFamily: "monospace",
        display: "flex", justifyContent: "space-between", alignItems: "center",
        borderBottom: "1px solid rgba(255,255,255,0.08)",
      }}>
        <span>
          🖥 {vpsName || vpsId}
          <span style={{
            marginLeft: "0.6rem",
            color: status === "connected" ? "#10B981" :
                   status === "error" ? "#EF4444" :
                   status === "disconnected" ? "#9CA3AF" : "#FBBF24",
          }}>● {status}</span>
        </span>
        {status !== "connected" && (
          <button onClick={reconnect} data-testid="vps-terminal-reconnect"
            style={{
              padding: "0.2rem 0.6rem", background: "#5B8DEF", color: "#fff",
              border: "none", borderRadius: 4, fontSize: "0.75rem", cursor: "pointer",
            }}>
            Reconectar
          </button>
        )}
      </div>
      <div ref={containerRef} style={{ flex: 1, minHeight: 0, padding: "0.3rem" }} />
    </div>
  );
}
