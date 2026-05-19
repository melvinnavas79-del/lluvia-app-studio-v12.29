import { useEffect, useState } from "react";
import { Group as PanelGroup, Panel, Separator as PanelResizeHandle } from "react-resizable-panels";
import { api, formatError } from "../api";
import FileTree from "./FileTree";
import CodeEditor from "./CodeEditor";

/**
 * Studio — IDE web tipo Emergent dentro de Lluvia App Studio.
 * Layout: 3 paneles redimensionables.
 *   [FileTree] | [Chat/Sessions] | [Preview / Editor / Terminal / Logs]
 *
 * NOTA: el chat queda como link al BossConsole por ahora. La sincronizacion
 * bidireccional (chat ↔ studio) la armará Claude en el VPS (Fase 7 del plan).
 */
export default function Studio() {
  const [apps, setApps] = useState([]);
  const [selectedApp, setSelectedApp] = useState(null);
  const [tree, setTree] = useState(null);
  const [selectedFile, setSelectedFile] = useState(null);
  const [rightTab, setRightTab] = useState("editor"); // editor | preview | logs
  const [vpsList, setVpsList] = useState([]);
  const [selectedVps, setSelectedVps] = useState(null);
  const [logService, setLogService] = useState("");
  const [logs, setLogs] = useState("");
  const [logsLoading, setLogsLoading] = useState(false);
  const [deploys, setDeploys] = useState([]);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get("/me/apps").then(({ data }) => {
      setApps(data.apps || []);
      if (data.apps?.length) setSelectedApp(data.apps[0].name);
    }).catch(e => setError(formatError(e)));
    api.get("/me/vps").then(({ data }) => {
      setVpsList(data.vps || []);
      if (data.vps?.length) setSelectedVps(data.vps[0].id);
    });
  }, []);

  useEffect(() => {
    if (!selectedApp) return;
    api.get(`/me/apps/${selectedApp}/files`)
      .then(({ data }) => setTree(data.tree))
      .catch(e => setError(formatError(e)));
  }, [selectedApp]);

  useEffect(() => {
    if (!selectedVps) return;
    api.get(`/me/vps/${selectedVps}/deployments`)
      .then(({ data }) => setDeploys(data.deployments || []));
  }, [selectedVps]);

  const refreshTree = () => {
    if (!selectedApp) return;
    api.get(`/me/apps/${selectedApp}/files`).then(({ data }) => setTree(data.tree));
  };

  const fetchLogs = async () => {
    if (!selectedVps || !logService) return;
    setLogsLoading(true);
    try {
      const { data } = await api.get(`/me/vps/${selectedVps}/tail-logs`,
        { params: { service: logService, lines: 200 } });
      setLogs((data.stdout || "") + (data.stderr ? "\n--- STDERR ---\n" + data.stderr : ""));
    } catch (e) { setLogs(formatError(e)); }
    finally { setLogsLoading(false); }
  };

  return (
    <div style={{ height: "100vh", display: "flex", flexDirection: "column", background: "var(--bg, #fff)" }}
         data-testid="studio-page">
      {/* Top bar */}
      <div style={{
        display: "flex", alignItems: "center", gap: "1rem",
        padding: "0.6rem 1rem", borderBottom: "1px solid rgba(0,0,0,0.08)",
        background: "var(--surface, #fafafa)", fontSize: "0.9rem",
      }}>
        <div style={{ fontWeight: 800, fontSize: "1.05rem" }}>🛠 Lluvia Studio</div>
        <div style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
          <span style={{ color: "var(--text-muted)" }}>App:</span>
          <select value={selectedApp || ""} onChange={(e) => setSelectedApp(e.target.value)}
                  data-testid="studio-app-select"
                  style={{ padding: "0.3rem 0.6rem", borderRadius: 6 }}>
            {apps.length === 0 && <option value="">— Sin apps —</option>}
            {apps.map(a => <option key={a.name} value={a.name}>{a.name}</option>)}
          </select>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
          <span style={{ color: "var(--text-muted)" }}>VPS:</span>
          <select value={selectedVps || ""} onChange={(e) => setSelectedVps(e.target.value)}
                  data-testid="studio-vps-select"
                  style={{ padding: "0.3rem 0.6rem", borderRadius: 6 }}>
            {vpsList.length === 0 && <option value="">— Sin VPS —</option>}
            {vpsList.map(v => <option key={v.id} value={v.id}>{v.name} ({v.host})</option>)}
          </select>
        </div>
        <button
          onClick={() => window.location.hash = "#/dashboard"}
          style={{
            marginLeft: "auto", padding: "0.4rem 0.8rem", background: "transparent",
            border: "1px solid rgba(0,0,0,0.15)", borderRadius: 6, cursor: "pointer",
            fontSize: "0.82rem",
          }}>
          ← Volver al Dashboard
        </button>
      </div>

      {error && (
        <div style={{ padding: "0.5rem 1rem", background: "#FEE2E2", color: "#991B1B", fontSize: "0.85rem" }}>
          {error}
        </div>
      )}

      <div style={{ flex: 1, minHeight: 0 }}>
        <PanelGroup direction="horizontal">
          {/* LEFT: file tree */}
          <Panel defaultSize={20} minSize={12}>
            <div style={{
              height: "100%", overflowY: "auto", background: "var(--surface, #fafafa)",
              borderRight: "1px solid rgba(0,0,0,0.08)",
            }} data-testid="studio-filetree-panel">
              <div style={{ padding: "0.5rem 0.8rem", fontSize: "0.78rem", fontWeight: 700,
                            color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                Archivos {selectedApp && `· ${selectedApp}`}
              </div>
              {tree ? (
                <FileTree tree={tree} onSelectFile={(p) => { setSelectedFile(p); setRightTab("editor"); }}
                          selectedPath={selectedFile} />
              ) : (
                <div style={{ padding: "1rem", color: "var(--text-muted)", fontSize: "0.85rem" }}>
                  {apps.length === 0 ? "Generá una app primero (usando App Builder Pro)" : "Cargando…"}
                </div>
              )}
              <div style={{ padding: "0.6rem 0.8rem", borderTop: "1px solid rgba(0,0,0,0.08)", marginTop: "1rem" }}>
                <button onClick={refreshTree}
                  style={{
                    width: "100%", padding: "0.4rem", background: "transparent",
                    border: "1px solid rgba(0,0,0,0.15)", borderRadius: 6, cursor: "pointer",
                    fontSize: "0.78rem", color: "var(--text-muted)",
                  }}>
                  🔄 Refrescar
                </button>
              </div>
            </div>
          </Panel>
          <PanelResizeHandle style={{ width: 4, background: "rgba(0,0,0,0.05)" }} />

          {/* CENTER: chat preview */}
          <Panel defaultSize={35} minSize={20}>
            <div style={{
              height: "100%", padding: "1rem", overflowY: "auto",
              background: "var(--bg, #fff)",
            }}>
              <div style={{ fontWeight: 700, marginBottom: "0.8rem" }}>💬 Chat con Lluvia Studio</div>
              <div style={{
                padding: "1rem", background: "var(--surface, #fafafa)", borderRadius: 12,
                fontSize: "0.88rem", lineHeight: 1.55, color: "var(--text-secondary)",
              }}>
                <p>Para chatear con el agente de Lluvia Studio (file edits + deploy a VPS):</p>
                <ol style={{ paddingLeft: "1.2rem", marginTop: "0.5rem" }}>
                  <li>Abrí el <a href="#/dashboard"
                                 style={{ color: "#5B8DEF", fontWeight: 700 }}>Dashboard</a></li>
                  <li>Click en "+ Nuevo hilo"</li>
                  <li>Seleccioná el agente <b>"Lluvia Studio"</b> 🛠</li>
                  <li>Pedile: "Listá los archivos de mi-tiktok" o "Deployá mi-tiktok a mi VPS Contabo"</li>
                </ol>
                <p style={{ marginTop: "0.8rem", color: "var(--text-muted)", fontSize: "0.82rem" }}>
                  💡 La integración del chat dentro de este Studio se va a sincronizar en
                  la próxima fase. Por ahora podés usar el Dashboard en paralelo.
                </p>
              </div>

              <div style={{ marginTop: "1.5rem", fontWeight: 700, marginBottom: "0.5rem" }}>
                🚀 Deploys recientes en este VPS
              </div>
              {deploys.length === 0 ? (
                <div style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>Ninguno todavía.</div>
              ) : (
                <div style={{ display: "grid", gap: "0.5rem" }}>
                  {deploys.slice(0, 5).map(d => (
                    <div key={d.id} style={{
                      padding: "0.6rem 0.8rem", background: "var(--surface, #fafafa)",
                      borderRadius: 8, fontSize: "0.85rem",
                      borderLeft: `3px solid ${d.status === "running" ? "#10B981" :
                                  d.status === "failed" ? "#EF4444" : "#9CA3AF"}`,
                    }} data-testid={`studio-deploy-${d.id}`}>
                      <div style={{ display: "flex", justifyContent: "space-between" }}>
                        <span style={{ fontWeight: 700 }}>{d.app_slug}</span>
                        <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
                          {d.status}
                        </span>
                      </div>
                      <div style={{ fontSize: "0.78rem", color: "var(--text-muted)", marginTop: "0.2rem" }}>
                        {d.service_name} · :{d.port}
                        {d.domain && ` · ${d.domain}${d.https_enabled ? " 🔒" : ""}`}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </Panel>
          <PanelResizeHandle style={{ width: 4, background: "rgba(0,0,0,0.05)" }} />

          {/* RIGHT: tabs (Editor / Preview / Logs) */}
          <Panel defaultSize={45} minSize={25}>
            <div style={{ height: "100%", display: "flex", flexDirection: "column",
                          background: "var(--surface, #fafafa)" }}>
              {/* Tabs */}
              <div style={{ display: "flex", borderBottom: "1px solid rgba(0,0,0,0.08)" }}>
                {[
                  { id: "editor", label: "✏ Editor" },
                  { id: "preview", label: "👁 Preview" },
                  { id: "logs", label: "📋 Logs" },
                ].map(t => (
                  <button key={t.id}
                    onClick={() => setRightTab(t.id)}
                    data-testid={`studio-tab-${t.id}`}
                    style={{
                      padding: "0.6rem 1rem", background: "transparent", border: "none",
                      cursor: "pointer", fontSize: "0.85rem",
                      borderBottom: rightTab === t.id ? "2px solid #5B8DEF" : "2px solid transparent",
                      color: rightTab === t.id ? "#5B8DEF" : "var(--text-muted)",
                      fontWeight: rightTab === t.id ? 700 : 500,
                    }}>
                    {t.label}
                  </button>
                ))}
              </div>

              <div style={{ flex: 1, minHeight: 0, overflow: "hidden" }}>
                {rightTab === "editor" && selectedFile && selectedApp && (
                  <CodeEditor appSlug={selectedApp} path={selectedFile} onEditCreated={() => {}} />
                )}
                {rightTab === "editor" && !selectedFile && (
                  <div style={{ padding: "2rem", textAlign: "center", color: "var(--text-muted)" }}>
                    Seleccioná un archivo del tree de la izquierda
                  </div>
                )}

                {rightTab === "preview" && (
                  <div style={{ padding: "2rem", textAlign: "center", color: "var(--text-muted)" }}>
                    <p>Preview iframe llega en la Fase 5.</p>
                    <p style={{ fontSize: "0.85rem", marginTop: "0.8rem" }}>
                      Por ahora, deployá tu app a tu VPS y abrí la URL en otra pestaña.
                    </p>
                  </div>
                )}

                {rightTab === "logs" && (
                  <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
                    <div style={{ padding: "0.6rem", display: "flex", gap: "0.5rem",
                                  borderBottom: "1px solid rgba(0,0,0,0.08)" }}>
                      <input value={logService} onChange={(e) => setLogService(e.target.value)}
                        placeholder="lluvia-mi-tiktok" data-testid="studio-logs-service"
                        style={{ flex: 1, padding: "0.4rem 0.6rem", borderRadius: 6,
                                 border: "1px solid rgba(0,0,0,0.15)", fontFamily: "monospace" }} />
                      <button onClick={fetchLogs} disabled={logsLoading || !selectedVps || !logService}
                        data-testid="studio-logs-fetch"
                        style={{
                          padding: "0.4rem 0.9rem", background: "#5B8DEF", color: "#fff",
                          border: "none", borderRadius: 6, fontWeight: 700, cursor: "pointer",
                        }}>
                        {logsLoading ? "…" : "Cargar"}
                      </button>
                    </div>
                    <pre style={{
                      flex: 1, margin: 0, padding: "0.8rem", background: "#1E1E1E", color: "#D4D4D4",
                      fontSize: "0.78rem", overflowY: "auto", fontFamily: "monospace",
                      whiteSpace: "pre-wrap", wordBreak: "break-word",
                    }}>
                      {logs || "(sin logs todavía — ingresá el nombre del service y click Cargar)"}
                    </pre>
                  </div>
                )}
              </div>
            </div>
          </Panel>
        </PanelGroup>
      </div>
    </div>
  );
}
