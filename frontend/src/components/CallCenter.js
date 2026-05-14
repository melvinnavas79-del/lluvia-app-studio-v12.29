import { useEffect, useRef, useState } from "react";
import { formatError, API, getToken } from "../api";

/**
 * CallCenter — modo voz continuo, loop mic -> Whisper -> agente -> TTS.
 *
 * Como funciona:
 *  - Usa MediaRecorder con timeslices manuales: graba 4 segundos, corta
 *    automaticamente, envia el blob al backend /api/voice/call-center/turn,
 *    reproduce el mp3 de respuesta, y al terminar vuelve a grabar.
 *  - Detiene cuando el usuario aprieta "Colgar".
 *  - Muestra transcripcion turno por turno y saldo de oros restante.
 */
export default function CallCenter({ agents, defaultAgentId }) {
  const [agentId, setAgentId] = useState(defaultAgentId || "");
  const [active, setActive] = useState(false);
  const [status, setStatus] = useState("idle"); // idle|recording|sending|playing
  const [turns, setTurns] = useState([]);
  const [balance, setBalance] = useState(null);
  const [err, setErr] = useState("");
  const [sessionId, setSessionId] = useState("");

  const mediaRef = useRef(null);
  const streamRef = useRef(null);
  const audioRef = useRef(null);
  const stopFlag = useRef(false);

  useEffect(() => {
    if (!agentId && agents && agents.length) {
      // Prioriza vendedor / arquitecto para conversacion abierta
      const pref = agents.find((a) => a.id === "vendedor")
        || agents.find((a) => a.id === "arquitecto") || agents[0];
      setAgentId(pref.id);
    }
  }, [agents, agentId]);

  const stop = () => {
    stopFlag.current = true;
    setActive(false);
    setStatus("idle");
    try { mediaRef.current?.stop(); } catch (_) {}
    try { streamRef.current?.getTracks().forEach((t) => t.stop()); } catch (_) {}
    streamRef.current = null;
    mediaRef.current = null;
    try { audioRef.current?.pause(); } catch (_) {}
  };

  useEffect(() => () => stop(), []);

  const recordOneTurn = async (stream) => new Promise((resolve, reject) => {
    try {
      const mr = new MediaRecorder(stream, { mimeType: "audio/webm" });
      mediaRef.current = mr;
      const chunks = [];
      mr.ondataavailable = (e) => { if (e.data.size > 0) chunks.push(e.data); };
      mr.onstop = () => resolve(new Blob(chunks, { type: "audio/webm" }));
      mr.onerror = (e) => reject(e.error || new Error("MediaRecorder error"));
      mr.start();
      setStatus("recording");
      // Grabar 4.5 segundos por turno
      setTimeout(() => { try { mr.state === "recording" && mr.stop(); } catch (_) {} }, 4500);
    } catch (e) { reject(e); }
  });

  const playAudio = (b64) => new Promise((resolve) => {
    if (!b64) return resolve();
    const audio = new Audio(`data:audio/mpeg;base64,${b64}`);
    audioRef.current = audio;
    audio.onended = () => resolve();
    audio.onerror = () => resolve();
    audio.play().catch(() => resolve());
  });

  const sendTurn = async (blob) => {
    setStatus("sending");
    const fd = new FormData();
    fd.append("audio", blob, "turn.webm");
    fd.append("agent_id", agentId);
    if (sessionId) fd.append("session_id", sessionId);
    const token = getToken();
    const r = await fetch(`${API}/voice/call-center/turn`, {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: fd,
    });
    if (!r.ok) {
      const text = await r.text();
      throw new Error(text || `HTTP ${r.status}`);
    }
    return await r.json();
  };

  const startCall = async () => {
    setErr("");
    setTurns([]);
    setSessionId("");
    stopFlag.current = false;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      setActive(true);
      // Loop hasta que el usuario cuelgue
      while (!stopFlag.current) {
        const blob = await recordOneTurn(stream);
        if (stopFlag.current) break;
        if (!blob || blob.size < 800) {
          // silencio muy corto, repetir
          continue;
        }
        try {
          const data = await sendTurn(blob);
          if (data.session_id) setSessionId(data.session_id);
          setBalance(data.balance);
          setTurns((t) => [...t, {
            user: data.user_text,
            assistant: data.assistant_text,
            cost: data.cost_oros,
          }]);
          if (data.audio_base64) {
            setStatus("playing");
            await playAudio(data.audio_base64);
          }
        } catch (e) {
          setErr(formatError(e));
          // si saldo insuficiente, cortar
          if ((e?.message || "").includes("402") || (e?.message || "").toLowerCase().includes("saldo")) {
            break;
          }
        }
      }
    } catch (e) {
      setErr(formatError(e));
    } finally {
      stop();
    }
  };

  return (
    <div className="call-center" data-testid="call-center">
      <div className="cc-header">
        <h2 className="section-title" style={{ marginBottom: 0 }}>Call Center — modo voz continuo</h2>
        {balance !== null && (
          <span className="oro-badge" data-testid="cc-balance">{balance} oros</span>
        )}
      </div>
      <p className="hero-sub" style={{ marginBottom: "1.5rem" }}>
        Conversacion fluida tipo telefono: hablas, el agente te responde por voz, y vuelve a escuchar.
        Cada turno consume oros (audio in + chat + audio out).
      </p>

      <div className="form-row" style={{ alignItems: "flex-end" }}>
        <div className="field">
          <label>Agente</label>
          <select
            value={agentId}
            onChange={(e) => setAgentId(e.target.value)}
            disabled={active}
            data-testid="cc-agent-select"
            style={{ minWidth: 280 }}
          >
            {(agents || []).map((a) => (
              <option key={a.id} value={a.id}>{a.emoji} {a.name} — {a.tagline}</option>
            ))}
          </select>
        </div>
        <div className="field">
          {!active ? (
            <button
              className="login-btn"
              onClick={startCall}
              disabled={!agentId}
              data-testid="cc-start"
            >
              📞 Llamar
            </button>
          ) : (
            <button
              className="copy-btn"
              onClick={stop}
              data-testid="cc-stop"
              style={{ background: "#ff4d6d", color: "#fff" }}
            >
              ■ Colgar
            </button>
          )}
        </div>
        <div className="field" style={{ flex: 1 }}>
          <label>Estado</label>
          <div className="cc-status" data-testid="cc-status">
            {status === "idle" && "Listo"}
            {status === "recording" && <span style={{ color: "#ff4d6d" }}>● Grabando...</span>}
            {status === "sending" && "Enviando al agente..."}
            {status === "playing" && <span style={{ color: "#5fb4ff" }}>♪ Reproduciendo respuesta</span>}
          </div>
        </div>
      </div>

      {err && <div className="alert" style={{ marginTop: "1rem" }} data-testid="cc-error">{err}</div>}

      <div className="cc-transcript" data-testid="cc-transcript" style={{ marginTop: "1.5rem" }}>
        {turns.length === 0 && !active && (
          <div className="empty">Aprieta "Llamar" y empieza a hablar. Cada turno son ~4.5 segundos de grabacion.</div>
        )}
        {turns.map((t, i) => (
          <div key={i} className="cc-turn">
            <div className="cc-bubble user">
              <span className="cc-role">Tu:</span> {t.user || <em>(silencio)</em>}
            </div>
            <div className="cc-bubble assistant">
              <span className="cc-role">Agente:</span> {t.assistant}
              <span className="cc-cost">-{t.cost} oros</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
