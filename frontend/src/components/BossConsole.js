import { useEffect, useState, useRef, memo } from "react";
import { api, formatError } from "../api";
import AgentAvatar from "./AgentAvatar";
import PreviewIframe from "./PreviewIframe";
import PreviewPanel from "./PreviewPanel";

export default function BossConsole() {
  const [agents, setAgents] = useState([]);
  const [sessions, setSessions] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [activeSession, setActiveSession] = useState(null);
  const [balance, setBalance] = useState(null);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [recording, setRecording] = useState(false);
  const [err, setErr] = useState("");
  const [showPicker, setShowPicker] = useState(false);
  const [showShop, setShowShop] = useState(false);
  const [packs, setPacks] = useState({});
  const [packsConfigured, setPacksConfigured] = useState(false);
  const [attachments, setAttachments] = useState([]); // [{url, name, preview, uploading}]
  const [dragOver, setDragOver] = useState(false);
  const [cameraOpen, setCameraOpen] = useState(false);
  const [cameraErr, setCameraErr] = useState("");
  const [showAttachMenu, setShowAttachMenu] = useState(false);
  const [appPickerForPush, setAppPickerForPush] = useState(null); // null | [{name,size_bytes,modified}]
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewSlug, setPreviewSlug] = useState(null); // app slug for preview
  const [userApps, setUserApps] = useState([]); // list of user's apps
  const scrollRef = useRef(null);
  const mediaRef = useRef(null);
  const chunksRef = useRef([]);
  const fileInputRef = useRef(null);
  const textareaRef = useRef(null);
  const cameraVideoRef = useRef(null);
  const cameraStreamRef = useRef(null);
  const nativeCameraInputRef = useRef(null);  // <input capture> fallback iOS/Android
  const backendBase = (process.env.REACT_APP_BACKEND_URL || "").replace(/\/$/, "");

  // Auto-resize del textarea estilo ChatGPT
  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 200) + "px";
  }, [input]);

  const refreshAll = async () => {
    try {
      const [a, s, c, p] = await Promise.all([
        api.get("/console/agents"),
        api.get("/console/sessions"),
        api.get("/console/credits/me"),
        api.get("/paypal/packs"),
      ]);
      setAgents(a.data.agents);
      setSessions(s.data.sessions);
      setBalance(c.data.balance);
      setPacks(p.data.packs || {});
      setPacksConfigured(p.data.configured);
    } catch (e) {
      setErr(formatError(e));
    }
    // Load user apps for preview
    try {
      const { data } = await api.get("/me/apps");
      setUserApps(data.apps || []);
    } catch (_) {}
  };

  // Auto-detect app slug from conversation messages (for preview auto-open)
  const detectPreviewSlug = (messages) => {
    if (!messages || !messages.length) return null;
    // Look for tool calls that created/modified an app
    for (let i = messages.length - 1; i >= 0; i--) {
      const msg = messages[i];
      if (!msg.tool_calls) continue;
      for (const tc of msg.tool_calls) {
        if (tc.name === "generate_audio_room_app" || tc.name === "generate_tiktok_app") {
          try {
            const r = JSON.parse(tc.result_preview || "{}");
            if (r.app_name || r.slug) return r.app_name || r.slug;
          } catch (_) {}
        }
      }
    }
    // Fallback: check if there's only 1 user app
    if (userApps.length === 1) return userApps[0].name;
    return null;
  };

  useEffect(() => { refreshAll(); }, []);

  // Si el visitante vino del demo publico, hay un seed en localStorage con
  // {app_name, brand_color}. Auto-creamos una sesion con app_builder_pro
  // y mandamos el mensaje para que ensamble la app inmediatamente.
  useEffect(() => {
    if (!agents.length) return;
    let seed = null;
    try { seed = JSON.parse(localStorage.getItem("lluvia_demo_seed") || "null"); } catch (_) {}
    if (!seed || !seed.app_name) return;
    localStorage.removeItem("lluvia_demo_seed"); // consumir una sola vez
    (async () => {
      try {
        const r = await api.post("/console/sessions", { agent_id: "app_builder_pro" });
        await refreshAll();
        setActiveId(r.data.id);
        // dar tiempo a que activeSession se cargue
        setTimeout(() => {
          const text = `Llamala "${seed.app_name}" y usá color ${seed.brand_color || "#5B8DEF"}. Generala ya.`;
          window.dispatchEvent(new CustomEvent("lluvia:compose-message", { detail: { text, send: true } }));
        }, 800);
      } catch (e) { setErr(formatError(e)); }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agents.length]);

  useEffect(() => {
    if (!activeId) { setActiveSession(null); return; }
    api.get(`/console/sessions/${activeId}`)
      .then((r) => setActiveSession(r.data))
      .catch((e) => setErr(formatError(e)));
  }, [activeId]);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [activeSession?.messages?.length, sending]);

  const createSession = async (agentId) => {
    setShowPicker(false);
    try {
      const r = await api.post("/console/sessions", { agent_id: agentId });
      await refreshAll();
      setActiveId(r.data.id);
    } catch (e) { setErr(formatError(e)); }
  };

  const send = async (overrideText) => {
    const text = (overrideText ?? input).trim();
    const readyImages = attachments.filter((a) => a.url && !a.uploading);
    if ((!text && readyImages.length === 0) || !activeId || sending) return;
    setInput("");
    setSending(true);
    setErr("");
    const imageUrls = readyImages.map((a) => a.url);
    setAttachments([]);
    setActiveSession((p) => p ? {
      ...p,
      messages: [...(p.messages || []), {
        id: "tmp" + Date.now(),
        role: "user",
        content: text,
        image_urls: imageUrls,
        ts: new Date().toISOString(),
      }],
    } : p);
    try {
      const r = await api.post(`/console/sessions/${activeId}/messages`, {
        text: text || "(imagen)",
        image_urls: imageUrls.length ? imageUrls : undefined,
      });
      setBalance(r.data.balance);
      const fresh = await api.get(`/console/sessions/${activeId}`);
      setActiveSession(fresh.data);
      const s = await api.get("/console/sessions");
      setSessions(s.data.sessions);
    } catch (e) {
      setErr(formatError(e));
    } finally { setSending(false); }
  };

  // Listener global para que las rich cards puedan pre-rellenar y enviar
  // mensajes (ej: CTA "Generar video real con Sora 2" desde VideoScriptCard).
  useEffect(() => {
    const onCompose = (e) => {
      const { text, send: shouldSend } = e.detail || {};
      if (!text) return;
      if (shouldSend) {
        send(text);  // enviar directamente
      } else {
        setInput((prev) => (prev ? prev + " " + text : text));
        textareaRef.current?.focus();
      }
    };
    window.addEventListener("lluvia:compose-message", onCompose);
    return () => window.removeEventListener("lluvia:compose-message", onCompose);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId, attachments]);

  // ---- IMAGENES: subir archivo y adjuntar al proximo mensaje
  const uploadImage = async (file) => {
    if (!file || !activeId) return;
    if (!file.type.startsWith("image/")) {
      setErr("Solo se permiten imagenes (JPG, PNG, GIF, WebP)");
      return;
    }
    if (file.size > 8 * 1024 * 1024) {
      setErr("Imagen demasiado grande (max 8MB)");
      return;
    }
    const previewUrl = URL.createObjectURL(file);
    const tmpId = "att" + Date.now() + Math.random();
    setAttachments((prev) => [...prev, { id: tmpId, preview: previewUrl, name: file.name, uploading: true }]);
    const fd = new FormData();
    fd.append("file", file);
    try {
      const r = await api.post(`/console/sessions/${activeId}/upload-image`, fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setAttachments((prev) => prev.map((a) =>
        a.id === tmpId ? { ...a, url: r.data.url, uploading: false } : a
      ));
    } catch (e) {
      setAttachments((prev) => prev.filter((a) => a.id !== tmpId));
      setErr(formatError(e));
    }
  };

  const onFilePick = (e) => {
    const files = Array.from(e.target.files || []);
    files.slice(0, 4).forEach(uploadImage);
    if (e.target) e.target.value = "";
  };

  const removeAttachment = (id) => {
    setAttachments((prev) => prev.filter((a) => a.id !== id));
  };

  const onDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    const files = Array.from(e.dataTransfer.files || []).filter((f) => f.type.startsWith("image/"));
    files.slice(0, 4).forEach(uploadImage);
  };

  const onPaste = (e) => {
    const items = Array.from(e.clipboardData?.items || []);
    const imgs = items.filter((i) => i.type.startsWith("image/")).map((i) => i.getAsFile()).filter(Boolean);
    if (imgs.length) {
      e.preventDefault();
      imgs.slice(0, 4).forEach(uploadImage);
    }
  };

  // ---- CAMARA: abrir modal con getUserMedia y capturar foto a canvas
  // En entornos donde getUserMedia esta bloqueado (iframe Preview iOS,
  // WebView, contexto inseguro), automaticamente caemos al <input capture>
  // nativo que iOS Safari SI permite incluso dentro del Preview.
  const triggerNativeCamera = () => {
    closeCamera();
    if (nativeCameraInputRef.current) {
      nativeCameraInputRef.current.value = "";
      nativeCameraInputRef.current.click();
    }
  };

  const openCamera = async () => {
    setCameraErr("");
    // Si no hay API de mediaDevices (Safari iframe / contexto inseguro),
    // saltamos directo a la camara nativa nativa del SO.
    if (!navigator.mediaDevices?.getUserMedia || !window.isSecureContext) {
      triggerNativeCamera();
      return;
    }
    setCameraOpen(true);
    // Esperar al siguiente tick para que el <video> exista
    await new Promise((r) => setTimeout(r, 60));
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 }, height: { ideal: 1280 } },
        audio: false,
      });
      cameraStreamRef.current = stream;
      if (cameraVideoRef.current) {
        cameraVideoRef.current.srcObject = stream;
        try { await cameraVideoRef.current.play(); } catch (_) {}
      }
    } catch (e) {
      const name = e?.name || "";
      const isBlocked = name === "NotAllowedError" || /not allowed/i.test(e?.message || "");
      if (isBlocked) {
        // Preview de Emergent / iframe en iOS bloquea getUserMedia.
        // Caemos al input capture nativo (que SI funciona).
        triggerNativeCamera();
        return;
      }
      const msg = name === "NotFoundError"
        ? "No detecté ninguna cámara. Probá adjuntar desde la galería."
        : `No pude abrir la cámara: ${e?.message || e}. Tocá '📱 Usar cámara del teléfono' para usar la cámara nativa.`;
      setCameraErr(msg);
    }
  };

  const closeCamera = () => {
    const stream = cameraStreamRef.current;
    if (stream) stream.getTracks().forEach((t) => t.stop());
    cameraStreamRef.current = null;
    if (cameraVideoRef.current) cameraVideoRef.current.srcObject = null;
    setCameraOpen(false);
  };

  const flipCamera = async () => {
    // Alterna entre front/rear apagando y volviendo a abrir con facingMode contrario.
    const current = cameraStreamRef.current?.getVideoTracks?.()[0]?.getSettings?.()?.facingMode;
    const newFacing = current === "user" ? "environment" : "user";
    // Cortar tracks viejos antes de pedir otros (algunos WebViews lo requieren).
    const oldStream = cameraStreamRef.current;
    if (oldStream) oldStream.getTracks().forEach((t) => t.stop());
    cameraStreamRef.current = null;
    if (cameraVideoRef.current) cameraVideoRef.current.srcObject = null;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: newFacing }, width: { ideal: 1280 }, height: { ideal: 1280 } },
        audio: false,
      });
      cameraStreamRef.current = stream;
      if (cameraVideoRef.current) {
        cameraVideoRef.current.srcObject = stream;
        try { await cameraVideoRef.current.play(); } catch (_) {}
      }
    } catch (e) {
      // En iOS Preview iframe el flip suele fallar con NotAllowed; caemos al nativo.
      triggerNativeCamera();
    }
  };

  const capturePhoto = async () => {
    const video = cameraVideoRef.current;
    if (!video || !video.videoWidth) {
      setCameraErr("La cámara aún no tiene video. Esperá un segundo y reintentá.");
      return;
    }
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise((res) => canvas.toBlob(res, "image/jpeg", 0.92));
    if (!blob) {
      setCameraErr("No pude capturar la foto. Reintentá.");
      return;
    }
    const file = new File([blob], `camara_${Date.now()}.jpg`, { type: "image/jpeg" });
    closeCamera();
    uploadImage(file);
  };

  // Cerrar el menu de adjuntos al clickear fuera
  useEffect(() => {
    if (!showAttachMenu) return;
    const onClick = (e) => {
      if (!e.target.closest(".bc-attach-menu") && !e.target.closest(".bc-attach-btn")) {
        setShowAttachMenu(false);
      }
    };
    document.addEventListener("click", onClick);
    return () => document.removeEventListener("click", onClick);
  }, [showAttachMenu]);

  // Limpiar el stream al desmontar (evita el clasico "pantalla negra" en reintentos)
  useEffect(() => {
    return () => {
      const s = cameraStreamRef.current;
      if (s) s.getTracks().forEach((t) => t.stop());
    };
  }, []);

  const delSession = async (id) => {
    if (!window.confirm("Borrar este hilo?")) return;
    await api.delete(`/console/sessions/${id}`);
    if (activeId === id) setActiveId(null);
    refreshAll();
  };

  // ---- VOZ: grabar y transcribir
  const toggleRecord = async () => {
    if (recording) {
      mediaRef.current?.stop();
      setRecording(false);
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream);
      chunksRef.current = [];
      mr.ondataavailable = (e) => chunksRef.current.push(e.data);
      mr.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        const fd = new FormData();
        fd.append("audio", blob, "voice.webm");
        try {
          const r = await api.post("/voice/transcribe", fd, {
            headers: { "Content-Type": "multipart/form-data" },
          });
          setBalance(r.data.balance);
          if (r.data.text) send(r.data.text);
        } catch (e) { setErr(formatError(e)); }
      };
      mr.start();
      mediaRef.current = mr;
      setRecording(true);
    } catch (e) {
      setErr("Permiso de microfono denegado");
    }
  };

  const playTts = async (text, voice) => {
    try {
      const resp = await api.post("/voice/tts", { text, voice: voice || "alloy" },
        { responseType: "blob" });
      const balance = resp.headers["x-balance-after"];
      if (balance) setBalance(parseInt(balance, 10));
      const url = URL.createObjectURL(resp.data);
      new Audio(url).play();
    } catch (e) { setErr(formatError(e)); }
  };

  // ---- PAYPAL
  const buyPack = async (packId) => {
    try {
      const r = await api.post("/paypal/create-order", { pack: packId });
      const w = window.open(r.data.approve_url, "_blank", "width=500,height=700");
      // Polling: cuando el usuario apruebe y vuelva, capturamos
      const orderId = r.data.order_id;
      const poll = setInterval(async () => {
        if (w && w.closed) {
          clearInterval(poll);
          try {
            const cap = await api.post(`/paypal/capture/${orderId}`);
            if (cap.data.balance) setBalance(cap.data.balance);
            setShowShop(false);
            alert(`✅ Acreditados ${cap.data.credited_oros || 0} oros. Saldo: ${cap.data.balance}`);
          } catch (e) {
            alert("La orden quedo pendiente. Intentaras de nuevo desde 'Mis ordenes'.");
          }
        }
      }, 1500);
    } catch (e) { setErr(formatError(e)); }
  };

  const getAgent = (id) => agents.find((a) => a.id === id);
  const currentAgent = activeSession ? getAgent(activeSession.agent_id) : null;

  // Pushea UNA app a su repo dedicado — reutiliza /me/github/push-app existente
  const _pushAppDedicated = async (appSlug) => {
    const msg = prompt(
      "Mensaje del commit (opcional):",
      `deploy: ${appSlug} ${new Date().toLocaleString()}`
    );
    if (msg === null) return;
    try {
      const { data } = await api.post("/me/github/push-app", {
        app_slug: appSlug,
        create_new: true,
        commit_message: msg,
      });
      if (data.ok) {
        const repoUrl = data.repo_url || `https://github.com/${data.repo}`;
        const repoLine = data.created_new_repo
          ? `\n✨ Repo nuevo creado: ${data.repo}`
          : `\nRepo: ${data.repo}`;
        alert(`✅ Push exitoso!${repoLine}\n\nVer en GitHub: ${repoUrl}`);
      } else if (data.export_locked) {
        if (window.confirm(`🔒 ${data.message}\n\n¿Querés recargar oros ahora?`))
          window.location.hash = "#/recharge";
      } else {
        const lastStep = (data.steps || []).slice(-1)[0];
        const detail =
          data.error ||
          data.message ||
          (lastStep && (lastStep.out || lastStep.err || JSON.stringify(lastStep))) ||
          "Error desconocido, contactá soporte.";
        alert(`⚠ Push falló:\n\n${detail}`);
      }
    } catch (e) {
      const detail = e?.response?.data?.detail || formatError(e);
      if (detail?.toLowerCase().includes("token") || detail?.toLowerCase().includes("configura")) {
        if (window.confirm("Falta tu token de GitHub. ¿Ir a 'Mi Cuenta' ahora para configurarlo?"))
          window.dispatchEvent(new CustomEvent("lluvia:goto-settings"));
      } else {
        alert(`✕ ${detail}`);
      }
    }
  };

  // Botón "Push a GitHub" del header: lista apps primero, luego pushea per-app
  const pushNow = async () => {
    try {
      const { data } = await api.get("/me/apps");
      const apps = data.apps || [];
      if (apps.length === 0) {
        alert("No tenés apps generadas. Creá una primero con App Builder Pro.");
        return;
      }
      if (apps.length === 1) {
        await _pushAppDedicated(apps[0].name);
      } else {
        setAppPickerForPush(apps);
      }
    } catch (e) {
      setErr(formatError(e));
    }
  };

  return (
    <div className={`boss-console${previewOpen ? " boss-console--split" : ""}`} data-testid="boss-console">
      <aside className="bc-sidebar">
        <div className="bc-side-head">
          <button className="bc-new-btn" onClick={() => setShowPicker(true)} data-testid="bc-new-thread-btn">
            + Nuevo hilo
          </button>
        </div>
        <div className="bc-thread-list">
          {sessions.length === 0 && <div className="bc-empty">Sin hilos aun</div>}
          {sessions.map((s) => {
            const ag = getAgent(s.agent_id);
            return (
              <div key={s.id} className={`bc-thread ${activeId === s.id ? "active" : ""}`}
                   onClick={() => setActiveId(s.id)} data-testid={`bc-thread-${s.id}`}>
                {ag ? (
                  <AgentAvatar agent={ag} size={40} rounded="rounded" />
                ) : (
                  <div style={{ width: 40, height: 40, borderRadius: 12, background: "var(--surface-warm)" }} />
                )}
                <div className="bc-thread-meta">
                  <div className="bc-thread-title">{s.title}</div>
                  <div className="bc-thread-preview">{s.last_message_preview || "Sin mensajes"}</div>
                </div>
                <button className="bc-thread-del"
                        onClick={(e) => { e.stopPropagation(); delSession(s.id); }}>×</button>
              </div>
            );
          })}
        </div>
      </aside>

      <main className="bc-main">
        <header className="bc-header">
          <div className="bc-header-left">
            {currentAgent ? (
              <>
                <AgentAvatar agent={currentAgent} size={44} rounded="rounded" />
                <div>
                  <div className="bc-header-name">{currentAgent.name}</div>
                  <div className="bc-header-tag">{currentAgent.tagline}</div>
                </div>
              </>
            ) : <div className="bc-header-tag">Elige un agente para empezar</div>}
          </div>
          <div className="bc-header-right">
            {/* Preview toggle */}
            <button
              className={`bc-shop-btn${previewOpen ? " bc-shop-btn--active" : ""}`}
              onClick={() => {
                if (!previewOpen) {
                  const slug = previewSlug || detectPreviewSlug(activeSession?.messages) || (userApps[0]?.name);
                  setPreviewSlug(slug || null);
                }
                setPreviewOpen(o => !o);
              }}
              title={previewOpen ? "Cerrar preview" : "Ver preview en vivo"}
              style={{ display: "inline-flex", alignItems: "center", gap: "0.35rem" }}
              data-testid="bc-preview-toggle"
            >
              <span style={{ fontSize: "0.9rem" }}>👁</span>
              Preview
            </button>
            <button className="bc-shop-btn" onClick={pushNow} data-testid="bc-push-github"
                    title="Push de tu workspace a GitHub"
                    style={{ display: "inline-flex", alignItems: "center", gap: "0.35rem" }}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                <path d="M12 .297a12 12 0 0 0-3.79 23.39c.6.11.82-.26.82-.58v-2.02c-3.34.72-4.04-1.61-4.04-1.61-.55-1.4-1.35-1.78-1.35-1.78-1.1-.75.08-.74.08-.74 1.22.09 1.86 1.25 1.86 1.25 1.09 1.86 2.85 1.32 3.54 1.01.11-.79.42-1.32.77-1.62-2.66-.3-5.47-1.33-5.47-5.93 0-1.31.47-2.38 1.24-3.22-.13-.31-.54-1.53.12-3.18 0 0 1.01-.32 3.3 1.23a11.5 11.5 0 0 1 6 0c2.29-1.55 3.3-1.23 3.3-1.23.66 1.65.25 2.87.12 3.18.78.84 1.24 1.91 1.24 3.22 0 4.61-2.81 5.62-5.48 5.92.43.37.81 1.1.81 2.22v3.29c0 .32.22.7.83.58A12 12 0 0 0 12 .297z"/>
              </svg>
              Push
            </button>
            <button className="bc-shop-btn" onClick={() => setShowShop(true)} data-testid="bc-shop-btn">
              + Recargar
            </button>
            <div className="bc-credits" data-testid="bc-credits">
              <span className="bc-credits-icon">⚜</span>
              <span className="bc-credits-num">{balance ?? "—"}</span>
              <span className="bc-credits-label">oros</span>
            </div>
          </div>
        </header>

        {err && <div className="alert" data-testid="bc-error">{err}</div>}

        <div
          className={`bc-chat ${dragOver ? "bc-drag-over" : ""}`}
          ref={scrollRef}
          onDragOver={(e) => { if (activeSession) { e.preventDefault(); setDragOver(true); } }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
        >
          {dragOver && activeSession && (
            <div className="bc-drop-hint" data-testid="bc-drop-hint">
              <span>📷 Soltá la imagen para enviarla</span>
            </div>
          )}
          {!activeSession && (
            <div className="bc-welcome">
              <h2>Elige tu agente</h2>
              <p>{agents.length} agentes con herramientas reales · voz · cobros · agendamiento</p>
              <div className="bc-agent-grid">
                {agents.map((a) => (
                  <button key={a.id} className="bc-agent-card"
                          onClick={() => createSession(a.id)} data-testid={`bc-agent-card-${a.id}`}>
                    <AgentAvatar agent={a} size={48} rounded="rounded" />
                    <div className="bc-agent-name">{a.name}</div>
                    <div className="bc-agent-tag">{a.tagline}</div>
                    <div className="bc-agent-foot">
                      <span className="bc-voice-tag">🎙 {a.voice || "alloy"}</span>
                      {a.tools?.length > 0 && <span>{a.tools.length} tools</span>}
                      {a.is_custom && <span className="bc-custom-tag">custom</span>}
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}

          {activeSession?.messages?.map((m) => (
            <Message key={m.id} msg={m} agent={currentAgent} onPlay={playTts} backendBase={backendBase} />
          ))}

          {sending && (
            <div className="bc-msg bc-msg-assistant">
              {currentAgent && <AgentAvatar agent={currentAgent} size={36} rounded="circle" />}
              <div className="bc-msg-body">
                <div className="bc-typing-dots"><span/><span/><span/></div>
              </div>
            </div>
          )}
        </div>

        {activeSession && (
          <div className="bc-composer-wrap">
            {attachments.length > 0 && (
              <div className="bc-attachments-row" data-testid="bc-attachments-row">
                {attachments.map((a) => (
                  <div key={a.id} className="bc-attachment-chip" data-testid="bc-attachment-chip">
                    <img src={a.preview} alt={a.name} />
                    {a.uploading && <div className="bc-attachment-uploading">…</div>}
                    <button
                      className="bc-attachment-remove"
                      onClick={() => removeAttachment(a.id)}
                      data-testid="bc-attachment-remove"
                      title="Quitar"
                    >×</button>
                  </div>
                ))}
              </div>
            )}
            <div className="bc-composer">
              <input
                ref={fileInputRef}
                type="file"
                accept="image/png,image/jpeg,image/jpg,image/webp,image/gif"
                multiple
                style={{ display: "none" }}
                onChange={onFilePick}
                data-testid="bc-file-input"
              />
              <input
                ref={nativeCameraInputRef}
                type="file"
                accept="image/*"
                capture="environment"
                style={{ display: "none" }}
                onChange={onFilePick}
                data-testid="bc-native-camera-input"
              />
              <button
                className="bc-attach-btn"
                onClick={() => setShowAttachMenu((v) => !v)}
                data-testid="bc-attach-btn"
                title="Adjuntar"
                disabled={sending}
              >
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none"
                     stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 5v14M5 12h14"/>
                </svg>
              </button>
              {showAttachMenu && (
                <div className="bc-attach-menu" data-testid="bc-attach-menu" onClick={(e) => e.stopPropagation()}>
                  <button
                    className="bc-attach-menu-item"
                    onClick={() => { setShowAttachMenu(false); fileInputRef.current?.click(); }}
                    data-testid="bc-attach-gallery"
                  >
                    <span className="bc-attach-menu-icon">🖼</span>
                    <span>Subir desde galería</span>
                  </button>
                  <button
                    className="bc-attach-menu-item"
                    onClick={() => { setShowAttachMenu(false); openCamera(); }}
                    data-testid="bc-attach-camera"
                  >
                    <span className="bc-attach-menu-icon">📷</span>
                    <span>Tomar foto</span>
                  </button>
                  <button
                    className="bc-attach-menu-item"
                    onClick={() => { setShowAttachMenu(false); pushNow(); }}
                    data-testid="bc-attach-github"
                  >
                    <span className="bc-attach-menu-icon">⬆</span>
                    <span>Push a GitHub</span>
                  </button>
                </div>
              )}
              <textarea
                ref={textareaRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onPaste={onPaste}
                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }}}
                placeholder={`Escribile a ${currentAgent?.name}...`}
                rows={1}
                data-testid="bc-input"
                disabled={sending} />
              <button
                className={`bc-mic-btn ${recording ? "rec" : ""}`}
                onClick={toggleRecord}
                data-testid="bc-mic-btn"
                title={recording ? "Detener grabación" : "Hablar al agente"}>
                {recording ? (
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>
                ) : (
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
                    <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
                    <line x1="12" y1="19" x2="12" y2="23"/>
                    <line x1="8" y1="23" x2="16" y2="23"/>
                  </svg>
                )}
              </button>
              <button
                className="bc-send-btn"
                onClick={() => send()}
                disabled={(!input.trim() && attachments.filter(a => a.url).length === 0) || sending || attachments.some(a => a.uploading)}
                data-testid="bc-send-btn">
                {sending ? (
                  <span className="bc-send-spinner"/>
                ) : (
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M12 19V5M5 12l7-7 7 7"/>
                  </svg>
                )}
              </button>
            </div>
            <div className="bc-composer-hint">
              GPT-4o vision · 3 oros por imagen · arrastrá o pegá fotos
            </div>
          </div>
        )}
      </main>

      {/* Modal: agent picker */}
      {showPicker && (
        <div className="bc-modal-overlay" onClick={() => setShowPicker(false)}>
          <div className="bc-modal" onClick={(e) => e.stopPropagation()}>
            <h3>Elige un agente</h3>
            <div className="bc-agent-grid">
              {agents.map((a) => (
                <button key={a.id} className="bc-agent-card"
                        onClick={() => createSession(a.id)}>
                  <AgentAvatar agent={a} size={44} rounded="rounded" />
                  <div className="bc-agent-name">{a.name}</div>
                  <div className="bc-agent-tag">{a.tagline}</div>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Modal: PayPal shop */}
      {showShop && (
        <div className="bc-modal-overlay" onClick={() => setShowShop(false)}>
          <div className="bc-modal" onClick={(e) => e.stopPropagation()} data-testid="bc-shop-modal">
            <h3>Recargar oros</h3>
            {!packsConfigured ? (
              <div className="alert">
                PayPal no configurado todavia.<br/>
                Pega tus credenciales en <code>backend/.env</code>:<br/>
                <code>PAYPAL_CLIENT_ID=...</code><br/>
                <code>PAYPAL_SECRET=...</code><br/>
                Y reinicia el backend.
              </div>
            ) : (
              <div className="bc-pack-grid">
                {Object.entries(packs).map(([k, p]) => (
                  <button key={k} className="bc-pack-card" onClick={() => buyPack(k)}
                          data-testid={`bc-pack-${k}`}>
                    <div className="bc-pack-oros">{p.oros.toLocaleString()} ⚜</div>
                    <div className="bc-pack-price">${p.price_usd} USD</div>
                    <div className="bc-pack-label">{p.label}</div>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Modal: Cámara nativa (getUserMedia) */}
      {cameraOpen && (
        <div className="bc-modal-overlay bc-camera-overlay" onClick={closeCamera}>
          <div className="bc-camera-modal" onClick={(e) => e.stopPropagation()} data-testid="bc-camera-modal">
            <div className="bc-camera-stage">
              <video
                ref={cameraVideoRef}
                className="bc-camera-video"
                autoPlay
                playsInline
                muted
                data-testid="bc-camera-video"
              />
              {cameraErr && (
                <div className="bc-camera-err" data-testid="bc-camera-err">
                  <div>{cameraErr}</div>
                  <button
                    className="bc-camera-fallback-btn"
                    onClick={triggerNativeCamera}
                    data-testid="bc-camera-native-btn"
                  >
                    📱 Usar cámara del teléfono
                  </button>
                </div>
              )}
            </div>
            <div className="bc-camera-controls">
              <button className="bc-camera-secondary" onClick={closeCamera} data-testid="bc-camera-cancel">
                Cancelar
              </button>
              <button
                className="bc-camera-shutter"
                onClick={capturePhoto}
                disabled={!!cameraErr}
                data-testid="bc-camera-shutter"
                aria-label="Capturar foto"
              >
                <span className="bc-camera-shutter-inner"/>
              </button>
              <button className="bc-camera-secondary" onClick={flipCamera} data-testid="bc-camera-flip" title="Voltear cámara">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M3 12a9 9 0 0 1 14.85-6.85L20 7M21 12a9 9 0 0 1-14.85 6.85L4 17"/>
                  <path d="M4 4v3h3M20 20v-3h-3"/>
                </svg>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* App picker: aparece cuando hay >1 apps y el usuario hace "Push a GitHub" */}
      {appPickerForPush && (
        <div
          style={{
            position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)",
            zIndex: 200, display: "flex", alignItems: "center", justifyContent: "center",
          }}
          onClick={() => setAppPickerForPush(null)}
        >
          <div
            style={{
              background: "var(--surface-card, #1a1a2e)", borderRadius: 14,
              padding: "1.4rem", minWidth: 320, maxWidth: 460,
              boxShadow: "0 12px 48px rgba(0,0,0,0.5)",
            }}
            onClick={e => e.stopPropagation()}
          >
            <div style={{ fontWeight: 700, fontSize: "1rem", marginBottom: "0.35rem" }}>
              ¿Qué app pushear a GitHub?
            </div>
            <div style={{ fontSize: "0.8rem", color: "var(--text-muted)", marginBottom: "1rem", lineHeight: 1.45 }}>
              Cada app va a su propio repo — nunca se mezclan entre sí.
            </div>
            {appPickerForPush.map(app => (
              <button
                key={app.name}
                data-testid={`push-picker-${app.name}`}
                onClick={() => { setAppPickerForPush(null); _pushAppDedicated(app.name); }}
                style={{
                  display: "block", width: "100%", textAlign: "left",
                  padding: "0.65rem 0.9rem", marginBottom: "0.45rem",
                  background: "rgba(255,255,255,0.05)",
                  border: "1px solid rgba(255,255,255,0.1)",
                  borderRadius: 9, cursor: "pointer",
                  color: "var(--text-primary)", fontWeight: 600, fontSize: "0.9rem",
                }}
              >
                📦 {app.name}
                {app.size_bytes > 0 && (
                  <span style={{ fontSize: "0.72rem", fontWeight: 400, color: "var(--text-muted)", marginLeft: "0.5rem" }}>
                    {Math.round(app.size_bytes / 1024)} KB
                  </span>
                )}
              </button>
            ))}
            <button
              onClick={() => setAppPickerForPush(null)}
              style={{
                marginTop: "0.3rem", width: "100%", padding: "0.5rem",
                background: "transparent", border: "none",
                color: "var(--text-muted)", cursor: "pointer", fontSize: "0.82rem",
              }}
            >
              Cancelar
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function Message({ msg, agent, onPlay, backendBase }) {
  const isUser = msg.role === "user";
  const imageUrls = msg.image_urls || [];
  const absUrl = (u) => {
    if (!u) return u;
    if (u.startsWith("http") || u.startsWith("blob:") || u.startsWith("data:")) return u;
    return (backendBase || "") + u;
  };
  // Extraer rich cards desde tool_calls
  const RICH_CARD_TOOLS = [
    "paypal_invoice_card", "service_card", "push_to_my_github",
    "generate_haircut_preview", "video_script_card", "generate_promo_video",
    "generate_audio_room_app",
  ];
  const cards = (msg.tool_calls || []).map((tc) => {
    if (!RICH_CARD_TOOLS.includes(tc.name)) return null;
    try {
      const r = JSON.parse(tc.result_preview || "{}");
      if (r.card_type) return r;
    } catch (_) {}
    return null;
  }).filter(Boolean);

  return (
    <div className={`bc-msg ${isUser ? "bc-msg-user" : "bc-msg-assistant"}`} data-testid={`bc-msg-${msg.role}`}>
      {isUser ? (
        <div className="bc-msg-avatar" data-testid="msg-user-avatar">TU</div>
      ) : (
        agent
          ? <AgentAvatar agent={agent} size={36} rounded="circle" />
          : <div className="bc-msg-avatar">AI</div>
      )}
      <div className="bc-msg-body">
        {msg.tool_calls?.length > 0 && (
          <div className="bc-tool-trace">
            {msg.tool_calls.map((tc, i) => (
              <div key={i} className="bc-tool-call">
                <span className="bc-tool-name">⚙ {tc.name}</span>
                <span className="bc-tool-args">{JSON.stringify(tc.args).slice(0, 80)}</span>
              </div>
            ))}
          </div>
        )}
        {imageUrls.length > 0 && (
          <div className={`bc-msg-images ${imageUrls.length > 1 ? "multi" : ""}`} data-testid="bc-msg-images">
            {imageUrls.map((u, i) => (
              <a key={i} href={absUrl(u)} target="_blank" rel="noreferrer" className="bc-msg-image-link">
                <img src={absUrl(u)} alt={`adjunto ${i+1}`} className="bc-msg-image" loading="lazy" />
              </a>
            ))}
          </div>
        )}
        {msg.content && <div className="bc-msg-text">{msg.content}</div>}
        {cards.map((c, i) => {
          if (c.card_type === "payment") return <PaymentCard key={i} card={c} agent={agent} />;
          if (c.card_type === "github_push") return <GitHubPushCard key={i} card={c} />;
          if (c.card_type === "before_after") return <BeforeAfterCard key={i} card={c} agent={agent} backendBase={backendBase} />;
          if (c.card_type === "video_script") return <VideoScriptCard key={i} card={c} agent={agent} />;
          if (c.card_type === "video_job") return <VideoJobCard key={i} card={c} agent={agent} backendBase={backendBase} />;
          if (c.card_type === "app_built") return <AppBuiltCard key={i} card={c} />;
          return <ServiceCard key={i} card={c} agent={agent} />;
        })}
        {msg.superadmin_takeover && (
          <div className="bc-takeover-badge">👑 SuperAdmin · {msg.by}</div>
        )}
        <div className="bc-msg-foot">
          {msg.is_admin_free && msg.nominal_cost_oros > 0 && (
            <span className="bc-msg-cost" style={{ color: "#059669" }} title="Sos admin: no se cobra">
              👑 Gratis (admin · sería {msg.nominal_cost_oros} oros)
            </span>
          )}
          {!msg.is_admin_free && msg.cost_oros !== undefined && msg.cost_oros > 0 && (
            <span className="bc-msg-cost">-{msg.cost_oros} oros</span>
          )}
          {!isUser && msg.content && (
            <button className="bc-play-btn" onClick={() => onPlay(msg.content, agent?.voice)}
                    title="Escuchar">🔊</button>
          )}
        </div>
      </div>
    </div>
  );
}

function PaymentCard({ card, agent }) {
  const accent = agent?.color || "#5fb4ff";
  return (
    <div className="rich-card payment-card" data-testid="payment-card" style={{ borderColor: accent }}>
      <div className="rc-head" style={{ background: `linear-gradient(135deg, ${accent}22, transparent)` }}>
        <div className="rc-brand">
          <div className="rc-logo" style={{ background: accent }}>{(card.brand || "L").slice(0, 1)}</div>
          <div>
            <div className="rc-brand-name">{card.brand || "Lluvia App Studio"}</div>
            <div className="rc-brand-sub">Pago seguro · PayPal</div>
          </div>
        </div>
        <div className="rc-amount">${card.amount_usd}<small>USD</small></div>
      </div>
      <div className="rc-body">
        <div className="rc-desc">{card.description}</div>
        {card.client_name && <div className="rc-client">A nombre de: <strong>{card.client_name}</strong></div>}
        <div className="rc-order-id">Orden: {(card.order_id || "").slice(0, 12)}...</div>
      </div>
      <a href={card.approve_url} target="_blank" rel="noreferrer"
         className="rc-cta" style={{ background: accent }}
         data-testid="payment-card-cta">
        Pagar con PayPal →
      </a>
    </div>
  );
}

function ServiceCard({ card, agent }) {
  const accent = agent?.color || "#5fb4ff";
  return (
    <div className="rich-card service-card" data-testid="service-card" style={{ borderColor: accent }}>
      {card.image_url && (
        <img src={card.image_url} alt={card.title} className="rc-image" />
      )}
      <div className="rc-body">
        <div className="rc-title">{card.title}</div>
        {card.description && <div className="rc-desc">{card.description}</div>}
        {card.price_usd && (
          <div className="rc-price" style={{ color: accent }}>
            ${card.price_usd}<small> USD</small>
          </div>
        )}
        <button className="rc-cta-soft" style={{ borderColor: accent, color: accent }}>
          {card.cta_label || "Ver más"}
        </button>
      </div>
    </div>
  );
}

function GitHubPushCard({ card }) {
  const isOk = card.ok === true;
  const needsSetup = card.needs_setup === true;
  const exportLocked = card.export_locked === true;
  const stateColor = isOk ? "#059669" : (needsSetup || exportLocked) ? "#D97706" : "#DC2626";
  const stateLabel = isOk ? "Push exitoso" : exportLocked ? "🔒 Exportación bloqueada" : needsSetup ? "Setup pendiente" : "Push fallido";
  const stateIcon = isOk ? "✓" : exportLocked ? "🔒" : needsSetup ? "!" : "✕";
  // Si export_locked, mostramos card premium especial
  if (exportLocked) {
    return (
      <div className="rich-card github-push-card" data-testid="github-push-card-locked"
           style={{
             borderColor: "#D97706",
             background: "linear-gradient(135deg, rgba(245,158,11,0.08), rgba(124,58,237,0.06))",
             overflow: "hidden",
           }}>
        <div className="rc-head" style={{ background: "linear-gradient(135deg, rgba(245,158,11,0.18), rgba(124,58,237,0.10))" }}>
          <div className="rc-brand">
            <div className="rc-logo" style={{ background: "linear-gradient(135deg,#F59E0B,#D97706)", fontSize: "1.05rem" }}>🔒</div>
            <div>
              <div className="rc-brand-name">Tu app está lista — falta desbloquear la exportación</div>
              <div className="rc-brand-sub">Vista previa premium · Lluvia App Studio</div>
            </div>
          </div>
        </div>
        <div className="rc-body">
          <div style={{ fontSize: "0.92rem", lineHeight: 1.55, color: "var(--text-secondary)" }}>
            {card.message}
          </div>
          <div style={{
            display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "0.5rem",
            marginTop: "0.85rem", padding: "0.75rem", borderRadius: 12,
            background: "rgba(15,23,42,0.04)", border: "1px solid rgba(15,23,42,0.08)",
          }}>
            <div style={{ textAlign: "center" }}>
              <div style={{ fontSize: "0.7rem", color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.08em" }}>Saldo</div>
              <div style={{ fontSize: "1.35rem", fontWeight: 800, color: "var(--text-primary)" }}>{card.balance ?? 0}</div>
              <div style={{ fontSize: "0.7rem", color: "var(--text-muted)" }}>oros</div>
            </div>
            <div style={{ textAlign: "center", borderLeft: "1px solid rgba(15,23,42,0.1)", borderRight: "1px solid rgba(15,23,42,0.1)" }}>
              <div style={{ fontSize: "0.7rem", color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.08em" }}>Necesitas</div>
              <div style={{ fontSize: "1.35rem", fontWeight: 800, color: "#D97706" }}>{card.required ?? 50}</div>
              <div style={{ fontSize: "0.7rem", color: "var(--text-muted)" }}>oros</div>
            </div>
            <div style={{ textAlign: "center" }}>
              <div style={{ fontSize: "0.7rem", color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.08em" }}>Te faltan</div>
              <div style={{ fontSize: "1.35rem", fontWeight: 800, color: "#7C3AED" }}>{card.missing ?? "?"}</div>
              <div style={{ fontSize: "0.7rem", color: "var(--text-muted)" }}>oros</div>
            </div>
          </div>
          {card.refunded_oros > 0 && (
            <div style={{ marginTop: "0.6rem", color: "#059669", fontWeight: 600, fontSize: "0.85rem" }}>
              💸 Te devolvimos {card.refunded_oros} oros del intento de push.
            </div>
          )}
        </div>
        <a href={card.recharge_url || "#/recharge"} className="rc-cta"
           style={{ background: "linear-gradient(135deg,#F59E0B,#D97706)", display: "block", textAlign: "center" }}
           data-testid="github-push-card-recharge">
          Recargar oros y desbloquear exportación →
        </a>
      </div>
    );
  }
  return (
    <div className="rich-card github-push-card" data-testid="github-push-card"
         style={{ borderColor: stateColor }}>
      <div className="rc-head" style={{ background: `${stateColor}14` }}>
        <div className="rc-brand">
          <div className="rc-logo" style={{ background: stateColor, fontSize: "1rem" }}>{stateIcon}</div>
          <div>
            <div className="rc-brand-name">{stateLabel}</div>
            <div className="rc-brand-sub">Push a GitHub · Lluvia Workspace</div>
          </div>
        </div>
        <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"
             style={{ color: "var(--text-primary)" }}>
          <path d="M12 .297a12 12 0 0 0-3.79 23.39c.6.11.82-.26.82-.58v-2.02c-3.34.72-4.04-1.61-4.04-1.61-.55-1.4-1.35-1.78-1.35-1.78-1.1-.75.08-.74.08-.74 1.22.09 1.86 1.25 1.86 1.25 1.09 1.86 2.85 1.32 3.54 1.01.11-.79.42-1.32.77-1.62-2.66-.3-5.47-1.33-5.47-5.93 0-1.31.47-2.38 1.24-3.22-.13-.31-.54-1.53.12-3.18 0 0 1.01-.32 3.3 1.23a11.5 11.5 0 0 1 6 0c2.29-1.55 3.3-1.23 3.3-1.23.66 1.65.25 2.87.12 3.18.78.84 1.24 1.91 1.24 3.22 0 4.61-2.81 5.62-5.48 5.92.43.37.81 1.1.81 2.22v3.29c0 .32.22.7.83.58A12 12 0 0 0 12 .297z"/>
        </svg>
      </div>
      <div className="rc-body">
        {card.repo && (
          <div className="rc-desc">
            <span style={{ color: "var(--text-muted)", fontSize: "0.78rem" }}>Repositorio:</span>{" "}
            <strong>{card.repo}</strong>
            {card.branch && <span style={{ color: "var(--text-muted)" }}> · rama <code>{card.branch}</code></span>}
          </div>
        )}
        {card.commit_message && (
          <div style={{ fontSize: "0.85rem", color: "var(--text-secondary)", marginTop: "0.35rem" }}>
            Commit: <em>{card.commit_message}</em>
          </div>
        )}
        {card.message && !isOk && (
          <div className="rc-desc" style={{ color: stateColor, marginTop: "0.5rem" }}>
            {card.message}
          </div>
        )}
        {card.error && (
          <div className="rc-desc" style={{ color: stateColor, marginTop: "0.5rem", whiteSpace: "pre-wrap", fontSize: "0.85rem", lineHeight: 1.55 }}>
            {card.error}
          </div>
        )}
        {card.refunded_oros > 0 && (
          <div style={{ marginTop: "0.6rem", color: "#059669", fontWeight: 600, fontSize: "0.88rem" }}>
            💸 Te reembolsamos {card.refunded_oros} oros automáticamente.
          </div>
        )}
      </div>
      {isOk && card.repo_url && (
        <a href={card.repo_url} target="_blank" rel="noreferrer"
           className="rc-cta" style={{ background: stateColor }}
           data-testid="github-push-card-cta">
          Ver en GitHub →
        </a>
      )}
      {needsSetup && (
        <a href="#/settings" className="rc-cta" style={{ background: stateColor }}
           data-testid="github-push-card-setup">
          Configurar GitHub ahora →
        </a>
      )}
      {card.help_url && !isOk && !needsSetup && (
        <a href={card.help_url} target="_blank" rel="noreferrer"
           className="rc-cta" style={{ background: stateColor }}
           data-testid="github-push-card-help">
          Crear token nuevo en GitHub →
        </a>
      )}
    </div>
  );
}

function BeforeAfterCard({ card, agent, backendBase }) {
  const accent = agent?.color || "#ec4899";
  const abs = (u) => {
    if (!u) return u;
    if (u.startsWith("http") || u.startsWith("blob:") || u.startsWith("data:")) return u;
    return (backendBase || "") + u;
  };
  const ok = card.ok === true;
  return (
    <div className="rich-card before-after-card" data-testid="before-after-card"
         style={{ borderColor: accent }}>
      <div className="rc-head" style={{ background: `linear-gradient(135deg, ${accent}22, transparent)` }}>
        <div className="rc-brand">
          <div className="rc-logo" style={{ background: accent }}>💇</div>
          <div>
            <div className="rc-brand-name">{card.look_name || "Look propuesto"}</div>
            <div className="rc-brand-sub">Estilista Visual · Vista previa IA</div>
          </div>
        </div>
      </div>
      {!ok && (
        <div className="rc-body">
          <div className="rc-desc" style={{ color: "#DC2626" }}>
            {card.error || "No pude generar la vista previa. Pedile al cliente una foto clara."}
          </div>
          {card.refunded_oros > 0 && (
            <div style={{ marginTop: "0.5rem", color: "#059669", fontSize: "0.85rem", fontWeight: 600 }}>
              💸 Te reembolsamos {card.refunded_oros} oros automáticamente.
            </div>
          )}
        </div>
      )}
      {ok && (
        <div className="ba-grid">
          <div className="ba-slot">
            <div className="ba-label">Antes</div>
            <a href={abs(card.before_url)} target="_blank" rel="noreferrer">
              <img src={abs(card.before_url)} alt="Antes" className="ba-img" loading="lazy" />
            </a>
          </div>
          <div className="ba-arrow" aria-hidden="true">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M5 12h14M13 5l7 7-7 7"/>
            </svg>
          </div>
          <div className="ba-slot">
            <div className="ba-label" style={{ color: accent }}>Después · IA</div>
            <a href={abs(card.after_url)} target="_blank" rel="noreferrer">
              <img src={abs(card.after_url)} alt="Después" className="ba-img"
                   style={{ borderColor: accent }} loading="lazy" />
            </a>
          </div>
        </div>
      )}
      {ok && card.look_description && (
        <div className="rc-body" style={{ paddingTop: "0.6rem" }}>
          <div className="rc-desc" style={{ fontSize: "0.82rem", color: "var(--text-muted)", fontStyle: "italic" }}>
            {card.look_description}
          </div>
        </div>
      )}
    </div>
  );
}

function VideoScriptCard({ card, agent }) {
  const accent = agent?.color || "#f59e0b";
  const platformLabel = {
    tiktok: "TikTok", reels: "Instagram Reels", shorts: "YouTube Shorts", todos: "9:16 universal",
  }[card.platform] || card.platform;
  const copyAll = () => {
    const text = [
      `📹 ${card.title}`,
      `Plataforma: ${platformLabel} · ${card.duration_sec}s`,
      ``,
      `HOOK (0-3s): ${card.hook}`,
      ``,
      `ESCENAS:`,
      ...(card.scenes || []).map((s) => `  ${s.t} · ${s.visual}\n      → "${s.voiceover}"`),
      ``,
      `CTA: ${card.cta}`,
      `Música: ${card.music_suggestion || "—"}`,
      ``,
      `📝 CAPTION:`,
      card.caption,
      ``,
      `# ${(card.hashtags || []).join(" ")}`,
    ].join("\n");
    navigator.clipboard?.writeText(text);
  };
  const requestRealVideo = () => {
    // Dispara un evento global que el contenedor (BossConsole) escucha y
    // arma un mensaje pre-rellenado en el composer para pedirle a Sora 2
    // el video real de este guion.
    const dur = card.duration_sec <= 6 ? 4 : (card.duration_sec <= 10 ? 8 : 12);
    const isHorizontal = card.platform === "shorts" || card.platform === "youtube";
    const aspectWord = isHorizontal ? "horizontal" : "vertical";
    const prompt = [
      `Hace el video REAL con Sora 2 de este guion:`,
      `"${card.title}". Hook: ${card.hook}.`,
      `Duracion ${dur} segundos, ${aspectWord}, calidad standard. Confirmo el costo.`,
    ].join(" ");
    window.dispatchEvent(new CustomEvent("lluvia:compose-message", { detail: { text: prompt, send: true } }));
  };
  return (
    <div className="rich-card video-script-card" data-testid="video-script-card"
         style={{ borderColor: accent }}>
      <div className="rc-head" style={{ background: `linear-gradient(135deg, ${accent}22, transparent)` }}>
        <div className="rc-brand">
          <div className="rc-logo" style={{ background: accent }}>🎬</div>
          <div>
            <div className="rc-brand-name">{card.title}</div>
            <div className="rc-brand-sub">{platformLabel} · {card.duration_sec}s</div>
          </div>
        </div>
        <button className="vs-copy-btn" onClick={copyAll}
                data-testid="video-script-copy" title="Copiar todo">
          📋
        </button>
      </div>
      <div className="vs-body">
        <div className="vs-section">
          <div className="vs-section-title">HOOK <span>(0-3s)</span></div>
          <div className="vs-hook" style={{ borderLeftColor: accent }}>{card.hook}</div>
        </div>
        <div className="vs-section">
          <div className="vs-section-title">ESCENAS</div>
          <ol className="vs-scenes">
            {(card.scenes || []).map((s, i) => (
              <li key={i} className="vs-scene">
                <span className="vs-scene-t" style={{ color: accent }}>{s.t}</span>
                <div className="vs-scene-visual"><strong>📷</strong> {s.visual}</div>
                <div className="vs-scene-vo">🎙 "{s.voiceover}"</div>
              </li>
            ))}
          </ol>
        </div>
        <div className="vs-section">
          <div className="vs-section-title">CTA</div>
          <div className="vs-cta" style={{ color: accent }}>{card.cta}</div>
        </div>
        {card.music_suggestion && (
          <div className="vs-section">
            <div className="vs-section-title">MÚSICA</div>
            <div className="vs-music">🎵 {card.music_suggestion}</div>
          </div>
        )}
        <div className="vs-section">
          <div className="vs-section-title">CAPTION</div>
          <div className="vs-caption">{card.caption}</div>
        </div>
        {card.hashtags?.length > 0 && (
          <div className="vs-section">
            <div className="vs-section-title">HASHTAGS</div>
            <div className="vs-hashtags">
              {card.hashtags.map((h, i) => (
                <span key={i} className="vs-hashtag" style={{ color: accent, borderColor: accent + "55" }}>
                  {h.startsWith("#") ? h : `#${h}`}
                </span>
              ))}
            </div>
          </div>
        )}
        <button
          className="vs-cta-real-video"
          onClick={requestRealVideo}
          style={{ background: accent }}
          data-testid="vs-request-real-video"
        >
          🎥 Generar este video REAL con Sora 2
          <span className="vs-cta-price">30–55 oros</span>
        </button>
      </div>
    </div>
  );
}



const AppBuiltCard = memo(function AppBuiltCard({ card }) {
  const ok = card.ok === true;
  const stateColor = ok ? "#059669" : "#DC2626";
  const accent = card.brand_color || "#5B8DEF";

  const [pushState, setPushState] = useState("idle"); // idle | pushing | done | err
  const [pushResult, setPushResult] = useState(null);
  const [pushError, setPushError] = useState("");
  const [repoName, setRepoName] = useState(card.repo_suggestion || card.app_slug || "");
  const [showRepoForm, setShowRepoForm] = useState(false);
  // Auto-expandido si la app se generó con éxito; preserva estado entre re-renders
  const [showPreview, setShowPreview] = useState(ok);

  const doPushAndDeploy = async () => {
    if (!repoName || repoName.length < 2) {
      setPushError("Elegí un nombre de repo (mínimo 2 caracteres).");
      return;
    }
    setPushState("pushing");
    setPushError("");
    try {
      const { data } = await api.post("/me/github/push-app", {
        app_slug: card.app_slug,
        repo_name: repoName,
        create_new: true,
        commit_message: `deploy: ${card.app_name || card.app_slug}`,
        set_as_default: false,
      });
      if (data.ok) {
        setPushResult(data);
        setPushState("done");
      } else {
        setPushError(data.error || data.message || "Push falló sin detalle");
        setPushState("err");
      }
    } catch (e) {
      const detail = e?.response?.data?.detail || e?.message || "Error desconocido";
      if (detail.toLowerCase().includes("token") || detail.toLowerCase().includes("configura")) {
        if (window.confirm("Falta tu token de GitHub. ¿Ir a configurarlo?")) {
          window.dispatchEvent(new CustomEvent("lluvia:goto-settings"));
        }
      }
      setPushError(detail);
      setPushState("err");
    }
  };

  return (
    <div className="rich-card app-built-card" data-testid="app-built-card"
         style={{ borderColor: stateColor, overflow: "hidden" }}>
      <div className="rc-head" style={{ background: `linear-gradient(135deg, ${accent}1F, ${accent}05)` }}>
        <div className="rc-brand">
          <div className="rc-logo" style={{ background: accent, fontSize: "1.1rem" }}>🚀</div>
          <div>
            <div className="rc-brand-name">{ok ? "App ensamblada" : "Falló el ensamble"}</div>
            <div className="rc-brand-sub">{card.template_name || "App Builder Pro"}</div>
          </div>
        </div>
        <div style={{ fontSize: "0.72rem", color: "var(--text-muted)", fontWeight: 600 }}>
          {card.stack}
        </div>
      </div>
      <div className="rc-body">
        {ok ? (
          <>
            <div style={{ fontSize: "1.05rem", fontWeight: 700, color: "var(--text-primary)" }}>
              {card.app_name}
            </div>
            <div style={{ fontSize: "0.82rem", color: "var(--text-muted)", marginTop: "0.2rem" }}>
              Workspace: <code>{card.app_slug}</code> · {card.files_written} archivos · {Math.round((card.bytes_written || 0) / 1024)} KB
            </div>
            <div style={{
              marginTop: "0.9rem", display: "grid",
              gridTemplateColumns: "repeat(2, 1fr)", gap: "0.45rem",
            }}>
              {(card.screens || []).map((s, i) => (
                <div key={i} style={{
                  background: `${accent}10`, border: `1px solid ${accent}33`,
                  borderRadius: 10, padding: "0.5rem 0.7rem", fontSize: "0.82rem",
                  fontWeight: 600, color: "var(--text-primary)",
                }}>
                  📱 {s}
                </div>
              ))}
            </div>
            {card.next_step && (
              <div style={{
                marginTop: "0.8rem", padding: "0.65rem 0.8rem",
                background: "var(--surface-muted, rgba(0,0,0,0.04))",
                borderRadius: 10, fontSize: "0.85rem", lineHeight: 1.5,
                color: "var(--text-secondary)",
              }}>
                💡 {card.next_step}
              </div>
            )}

            {/* Push & Deploy section: SIEMPRE crea un repo nuevo para evitar
                que las apps generadas se sobrescriban entre sí */}
            <div style={{
              marginTop: "0.9rem", padding: "0.85rem",
              background: `${accent}0D`, border: `1.5px dashed ${accent}66`,
              borderRadius: 12,
            }}>
              {pushState === "done" && pushResult ? (
                <div data-testid="app-built-pushed">
                  <div style={{ fontWeight: 700, color: "#059669", marginBottom: "0.4rem" }}>
                    ✅ Subido a tu propio repo
                  </div>
                  <div style={{ fontSize: "0.85rem", marginBottom: "0.6rem" }}>
                    <code style={{ background: "rgba(0,0,0,0.05)", padding: "2px 6px", borderRadius: 4 }}>
                      {pushResult.repo}
                    </code>
                  </div>
                  <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                    <a href={pushResult.repo_url} target="_blank" rel="noreferrer"
                       style={{
                         background: "#0d1117", color: "#fff", padding: "0.55rem 0.9rem",
                         borderRadius: 8, fontWeight: 700, fontSize: "0.85rem", textDecoration: "none",
                         display: "inline-flex", alignItems: "center", gap: "0.4rem",
                       }}
                       data-testid="app-built-repo-link">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M12 .297a12 12 0 0 0-3.79 23.39c.6.11.82-.26.82-.58v-2.02c-3.34.72-4.04-1.61-4.04-1.61-.55-1.4-1.35-1.78-1.35-1.78-1.1-.75.08-.74.08-.74 1.22.09 1.86 1.25 1.86 1.25 1.09 1.86 2.85 1.32 3.54 1.01.11-.79.42-1.32.77-1.62-2.66-.3-5.47-1.33-5.47-5.93 0-1.31.47-2.38 1.24-3.22-.13-.31-.54-1.53.12-3.18 0 0 1.01-.32 3.3 1.23a11.5 11.5 0 0 1 6 0c2.29-1.55 3.3-1.23 3.3-1.23.66 1.65.25 2.87.12 3.18.78.84 1.24 1.91 1.24 3.22 0 4.61-2.81 5.62-5.48 5.92.43.37.81 1.1.81 2.22v3.29c0 .32.22.7.83.58A12 12 0 0 0 12 .297z"/></svg>
                      Ver en GitHub
                    </a>
                    <a href={pushResult.render_deploy_url || `https://render.com/deploy?repo=${encodeURIComponent(pushResult.repo_url)}`}
                       target="_blank" rel="noreferrer"
                       style={{
                         background: "#46E3B7", color: "#000", padding: "0.55rem 0.9rem",
                         borderRadius: 8, fontWeight: 700, fontSize: "0.85rem", textDecoration: "none",
                       }}
                       data-testid="app-built-deploy-render">
                      ⚡ Deploy a Render (1-click)
                    </a>
                  </div>
                </div>
              ) : (
                <>
                  <div style={{ fontWeight: 700, fontSize: "0.92rem", marginBottom: "0.3rem", color: "var(--text-primary)" }}>
                    🚀 Publicar esta app en su propio repo
                  </div>
                  <div style={{ fontSize: "0.8rem", color: "var(--text-muted)", marginBottom: "0.55rem", lineHeight: 1.45 }}>
                    Cada app va a un repositorio dedicado: así no se mezclan ni se sobrescriben tus apps anteriores.
                  </div>
                  {showRepoForm && (
                    <input
                      type="text" value={repoName}
                      onChange={(e) => setRepoName(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, "-"))}
                      placeholder="nombre-del-repo"
                      data-testid="app-built-repo-name"
                      style={{
                        width: "100%", padding: "0.55rem 0.75rem", borderRadius: 8,
                        border: "1px solid rgba(0,0,0,0.15)", marginBottom: "0.55rem",
                        fontSize: "0.9rem", fontFamily: "monospace",
                      }}
                    />
                  )}
                  <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap" }}>
                    {!showRepoForm ? (
                      <button onClick={() => setShowRepoForm(true)}
                              data-testid="app-built-push-cta"
                              style={{
                                background: accent, color: "#fff", padding: "0.6rem 1rem",
                                borderRadius: 8, fontWeight: 700, fontSize: "0.88rem",
                                border: "none", cursor: "pointer",
                              }}>
                        ⬆ Push & Deploy
                      </button>
                    ) : (
                      <button onClick={doPushAndDeploy} disabled={pushState === "pushing"}
                              data-testid="app-built-push-confirm"
                              style={{
                                background: accent, color: "#fff", padding: "0.55rem 1rem",
                                borderRadius: 8, fontWeight: 700, fontSize: "0.88rem",
                                border: "none", cursor: pushState === "pushing" ? "not-allowed" : "pointer",
                                opacity: pushState === "pushing" ? 0.6 : 1,
                              }}>
                        {pushState === "pushing" ? "⏳ Creando repo y pusheando..." : `✓ Crear repo "${repoName}" y push`}
                      </button>
                    )}
                  </div>
                  {pushError && (
                    <div style={{
                      marginTop: "0.55rem", padding: "0.55rem 0.7rem",
                      background: "#FEE2E2", color: "#991B1B",
                      borderRadius: 8, fontSize: "0.8rem", lineHeight: 1.4,
                    }} data-testid="app-built-push-err">
                      ⚠ {pushError}
                    </div>
                  )}
                </>
              )}
            </div>

            {/* Live Preview embebido — reutiliza PreviewIframe.js + workspace_preview.py */}
            <div style={{ marginTop: "0.65rem" }}>
              <button
                onClick={() => setShowPreview(p => !p)}
                data-testid="app-built-preview-toggle"
                style={{
                  background: showPreview ? `${accent}22` : "rgba(0,0,0,0.04)",
                  border: `1px solid ${showPreview ? accent : "rgba(0,0,0,0.1)"}`,
                  borderRadius: 8, padding: "0.45rem 0.85rem",
                  fontSize: "0.84rem", fontWeight: 700, cursor: "pointer",
                  color: showPreview ? accent : "var(--text-secondary)",
                  width: "100%", textAlign: "left",
                  display: "flex", alignItems: "center", gap: "0.4rem",
                }}>
                <span>{showPreview ? "▼" : "▶"}</span>
                <span>Vista Previa en vivo</span>
                {showPreview && (
                  <span style={{ marginLeft: "auto", fontSize: "0.72rem", fontWeight: 400, opacity: 0.7 }}>
                    app real · hot reload · desktop/móvil
                  </span>
                )}
              </button>
              {showPreview && (
                <div style={{
                  marginTop: "0.4rem",
                  border: `1px solid ${accent}33`,
                  borderRadius: 10, overflow: "hidden", height: 440,
                }}>
                  <PreviewIframe appSlug={card.app_slug} autoStart={true} />
                </div>
              )}
            </div>
          </>
        ) : (
          <>
            <div style={{ color: stateColor, fontSize: "0.92rem", lineHeight: 1.55, whiteSpace: "pre-wrap" }}>
              {card.error || "Error desconocido"}
            </div>
            {card.refunded_oros > 0 && (
              <div style={{ marginTop: "0.6rem", color: "#059669", fontWeight: 600, fontSize: "0.88rem" }}>
                💸 Te reembolsamos {card.refunded_oros} oros automáticamente.
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
});

function VideoJobCard({ card, agent, backendBase }) {
  const [job, setJob] = useState({
    status: card.status || "queued",
    video_url: null,
    error: null,
    duration: card.duration,
  });
  const accent = agent?.color || "#f59e0b";
  const startedRef = useRef(Date.now());
  const [elapsed, setElapsed] = useState(0);

  // Polling cada 6s mientras esta queued/generating
  useEffect(() => {
    if (job.status === "ready" || job.status === "error") return;
    const tick = async () => {
      try {
        const r = await api.get(`/console/video-jobs/${card.job_id}`);
        setJob(r.data);
      } catch (_) {}
    };
    tick();
    const i = setInterval(tick, 6000);
    return () => clearInterval(i);
  }, [card.job_id, job.status]);

  // Cronometro mientras se genera
  useEffect(() => {
    if (job.status === "ready" || job.status === "error") return;
    const i = setInterval(() => setElapsed(Math.floor((Date.now() - startedRef.current) / 1000)), 1000);
    return () => clearInterval(i);
  }, [job.status]);

  const absUrl = (u) => {
    if (!u) return u;
    if (u.startsWith("http")) return u;
    return (backendBase || "") + u;
  };

  const isReady = job.status === "ready" && job.video_url;
  const isError = job.status === "error";
  const isWorking = !isReady && !isError;

  const eta = card.estimated_wait_sec || (card.duration === 4 ? 180 : (card.duration === 8 ? 300 : 480));
  const progress = isWorking ? Math.min(95, Math.round((elapsed / eta) * 100)) : (isReady ? 100 : 0);

  return (
    <div className="rich-card video-job-card" data-testid="video-job-card" style={{ borderColor: accent }}>
      <div className="rc-head" style={{ background: `linear-gradient(135deg, ${accent}22, transparent)` }}>
        <div className="rc-brand">
          <div className="rc-logo" style={{ background: accent }}>🎥</div>
          <div>
            <div className="rc-brand-name">Sora 2 · Video {card.duration}s</div>
            <div className="rc-brand-sub">
              {card.model || "sora-2"} · {card.size || ""} · {card.aspect}
            </div>
          </div>
        </div>
      </div>
      <div className="vj-body">
        {card.prompt && (
          <div className="vj-prompt">
            <span className="vj-label">PROMPT</span>
            <div>{card.prompt}</div>
          </div>
        )}

        {isWorking && (
          <div className="vj-progress-wrap" data-testid="vj-progress">
            <div className="vj-status">
              <span className="vj-spinner" style={{ borderTopColor: accent }} />
              <span>
                {job.status === "queued" ? "En cola..." : "Generando con Sora 2..."}
                <strong style={{ marginLeft: 8 }}>{elapsed}s</strong>
                <span style={{ color: "var(--text-muted)" }}> / ~{eta}s</span>
              </span>
            </div>
            <div className="vj-progress">
              <div className="vj-progress-fill"
                   style={{ width: `${progress}%`, background: accent }} />
            </div>
            <div className="vj-hint">
              Podés cerrar el chat, el video sigue generándose. Te notificamos al volver.
              <br/><span style={{ color: "#059669" }}>✓ Si Sora 2 falla, los oros se devuelven automáticamente.</span>
            </div>
          </div>
        )}

        {isReady && (
          <div className="vj-video-wrap" data-testid="vj-video-wrap">
            <video
              controls
              playsInline
              className="vj-video"
              data-testid="vj-video"
              src={absUrl(job.video_url)}
              style={{ aspectRatio: card.aspect === "horizontal" ? "16/9" : (card.aspect === "square" ? "1/1" : "9/16") }}
            />
            <div className="vj-actions">
              <a
                href={absUrl(job.video_url)}
                download={`lluvia-sora2-${card.job_id}.mp4`}
                className="vj-download"
                style={{ background: accent }}
                data-testid="vj-download"
              >
                ⬇ Descargar MP4
              </a>
            </div>
          </div>
        )}

        {isError && (
          <div className="vj-error" data-testid="vj-error">
            ✕ {job.error || "La generación falló. Reintentá con otro prompt."}
            {job.refunded && (
              <div style={{ marginTop: "0.5rem", color: "#059669", fontWeight: 600 }}>
                💸 Te reembolsamos los oros automáticamente. Saldo restaurado.
              </div>
            )}
            {!job.refunded && (
              <div style={{ marginTop: "0.5rem", fontSize: "0.78rem", opacity: 0.85 }}>
                Si el cobro no se devolvió, avisanos para revisarlo manualmente.
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── Live Preview Panel (split view) ──────────────────────────── */}
      {previewOpen && (
        <div className="bc-preview-pane" data-testid="bc-preview-pane">
          {previewSlug ? (
            <PreviewPanel
              appSlug={previewSlug}
              autoStart={true}
              onClose={() => setPreviewOpen(false)}
            />
          ) : (
            <div className="preview-panel">
              <div className="preview-header">
                <span style={{ color: "var(--text-muted)", fontSize: "0.9rem" }}>Preview</span>
                <button className="preview-btn" onClick={() => setPreviewOpen(false)}>✕</button>
              </div>
              <div className="preview-empty">
                <span style={{ fontSize: "2rem", opacity: 0.3, marginBottom: "1rem" }}>👁</span>
                <p style={{ color: "var(--text-secondary)", fontSize: "0.9rem" }}>
                  Sin app seleccionada
                </p>
                {userApps.length > 0 && (
                  <div style={{ marginTop: "1rem", display: "flex", flexDirection: "column", gap: "0.5rem" }}>
                    <p style={{ fontSize: "0.82rem", color: "var(--text-muted)" }}>Tus apps:</p>
                    {userApps.slice(0, 5).map(app => (
                      <button key={app.name} className="cta-secondary"
                              onClick={() => setPreviewSlug(app.name)}
                              style={{ fontSize: "0.85rem" }}>
                        ▶ {app.name}
                      </button>
                    ))}
                  </div>
                )}
                {userApps.length === 0 && (
                  <p style={{ fontSize: "0.82rem", color: "var(--text-muted)", marginTop: "0.5rem" }}>
                    Pídele a E1 que genere una app primero
                  </p>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
