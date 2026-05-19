import { useEffect, useState } from "react";
import { api, formatError } from "../api";

/**
 * VpsServersTab — conexion SSH a VPS del usuario (Contabo, Hetzner, etc).
 * Va dentro de SettingsTab como una sub-pestaña.
 */
export default function VpsServersTab() {
  const [vpsList, setVpsList] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({
    name: "",
    host: "",
    port: 22,
    username: "root",
    ssh_key: "",
    password: "",
    auth_mode: "ssh_key", // "ssh_key" | "password"
  });
  const [testing, setTesting] = useState(null);
  const [testResult, setTestResult] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/me/vps");
      setVpsList(data.vps || []);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const handleSave = async (e) => {
    e.preventDefault();
    try {
      const payload = {
        name: form.name,
        host: form.host,
        port: Number(form.port),
        username: form.username,
      };
      if (form.auth_mode === "ssh_key") payload.ssh_key = form.ssh_key;
      else payload.password = form.password;
      await api.post("/me/vps", payload);
      setShowForm(false);
      setForm({ name: "", host: "", port: 22, username: "root", ssh_key: "", password: "", auth_mode: "ssh_key" });
      load();
    } catch (e) {
      alert(formatError(e));
    }
  };

  const handleTest = async (vps_id) => {
    setTesting(vps_id);
    setTestResult(null);
    try {
      const { data } = await api.post(`/me/vps/${vps_id}/test`);
      setTestResult({ vps_id, ...data });
      load();
    } catch (e) {
      setTestResult({ vps_id, ok: false, error: formatError(e) });
    } finally {
      setTesting(null);
    }
  };

  const handleDelete = async (vps_id, name) => {
    if (!window.confirm(`¿Borrar el VPS "${name}"? Los deploys siguen vivos en el servidor.`)) return;
    try {
      await api.delete(`/me/vps/${vps_id}`);
      load();
    } catch (e) { alert(formatError(e)); }
  };

  return (
    <div className="settings-section" data-testid="vps-servers-tab">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
        <div>
          <h3 style={{ margin: 0 }}>Mis Servidores VPS</h3>
          <div style={{ fontSize: "0.85rem", color: "var(--text-muted)", marginTop: "0.2rem" }}>
            Conectá tu Contabo / Hetzner / DigitalOcean para que el agente IA pueda deployar tus apps en 1 click.
          </div>
        </div>
        <button
          className="btn-primary"
          onClick={() => setShowForm(!showForm)}
          data-testid="vps-add-btn"
          style={{
            padding: "0.55rem 1rem", background: "#5B8DEF", color: "#fff",
            border: "none", borderRadius: 8, fontWeight: 700, cursor: "pointer",
          }}
        >
          {showForm ? "Cancelar" : "+ Agregar VPS"}
        </button>
      </div>

      {showForm && (
        <form onSubmit={handleSave} style={{
          background: "var(--surface, #f7f7f9)", padding: "1rem", borderRadius: 12,
          marginBottom: "1rem", display: "grid", gap: "0.75rem",
        }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem" }}>
            <label>
              <div className="field-label">Alias</div>
              <input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="Mi Contabo Principal" data-testid="vps-form-name" className="field-input" />
            </label>
            <label>
              <div className="field-label">Host / IP</div>
              <input required value={form.host} onChange={(e) => setForm({ ...form, host: e.target.value })}
                placeholder="207.180.235.220" data-testid="vps-form-host" className="field-input" />
            </label>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 2fr", gap: "0.75rem" }}>
            <label>
              <div className="field-label">Puerto SSH</div>
              <input type="number" value={form.port} onChange={(e) => setForm({ ...form, port: e.target.value })}
                data-testid="vps-form-port" className="field-input" />
            </label>
            <label>
              <div className="field-label">Usuario SSH</div>
              <input required value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })}
                placeholder="root" data-testid="vps-form-user" className="field-input" />
            </label>
          </div>

          <div style={{ display: "flex", gap: "0.5rem" }}>
            <label style={{ display: "flex", alignItems: "center", gap: "0.4rem", cursor: "pointer" }}>
              <input type="radio" checked={form.auth_mode === "ssh_key"}
                onChange={() => setForm({ ...form, auth_mode: "ssh_key" })} />
              <span>Clave SSH privada (recomendado)</span>
            </label>
            <label style={{ display: "flex", alignItems: "center", gap: "0.4rem", cursor: "pointer" }}>
              <input type="radio" checked={form.auth_mode === "password"}
                onChange={() => setForm({ ...form, auth_mode: "password" })} />
              <span>Password</span>
            </label>
          </div>

          {form.auth_mode === "ssh_key" ? (
            <label>
              <div className="field-label">SSH Private Key (PEM)</div>
              <textarea required value={form.ssh_key} onChange={(e) => setForm({ ...form, ssh_key: e.target.value })}
                placeholder="-----BEGIN OPENSSH PRIVATE KEY-----&#10;...&#10;-----END OPENSSH PRIVATE KEY-----"
                rows={6} data-testid="vps-form-key" className="field-input"
                style={{ fontFamily: "monospace", fontSize: "0.8rem" }} />
              <div style={{ fontSize: "0.78rem", color: "var(--text-muted)", marginTop: "0.3rem" }}>
                Pegá el contenido de tu archivo <code>~/.ssh/id_rsa</code> o <code>id_ed25519</code>.
                Se guarda cifrado con AES-GCM.
              </div>
            </label>
          ) : (
            <label>
              <div className="field-label">Password SSH</div>
              <input type="password" required value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                placeholder="••••••••" data-testid="vps-form-password" className="field-input" />
            </label>
          )}

          <div style={{ display: "flex", gap: "0.6rem", justifyContent: "flex-end" }}>
            <button type="submit" data-testid="vps-form-submit"
              style={{
                background: "#5B8DEF", color: "#fff", padding: "0.55rem 1.2rem",
                border: "none", borderRadius: 8, fontWeight: 700, cursor: "pointer",
              }}>
              Guardar y probar conexión
            </button>
          </div>
        </form>
      )}

      {loading ? <div>Cargando…</div> : vpsList.length === 0 ? (
        <div style={{
          padding: "1.5rem", textAlign: "center", color: "var(--text-muted)",
          background: "var(--surface, #f7f7f9)", borderRadius: 12,
        }}>
          No tenés VPS conectados. Agregá uno con el botón de arriba.
        </div>
      ) : (
        <div style={{ display: "grid", gap: "0.75rem" }}>
          {vpsList.map((v) => (
            <div key={v.id} style={{
              padding: "1rem", background: "var(--surface, #f7f7f9)", borderRadius: 12,
              border: `1px solid ${v.status === "connected" ? "#10B981" : v.status === "error" ? "#EF4444" : "rgba(0,0,0,0.1)"}`,
            }} data-testid={`vps-card-${v.id}`}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start", marginBottom: "0.5rem" }}>
                <div>
                  <div style={{ fontWeight: 700, fontSize: "1.05rem" }}>
                    🖥 {v.name}{" "}
                    <span style={{
                      fontSize: "0.7rem", padding: "2px 8px", borderRadius: 999, marginLeft: "0.5rem",
                      background: v.status === "connected" ? "#D1FAE5" :
                                  v.status === "error" ? "#FEE2E2" : "#F3F4F6",
                      color: v.status === "connected" ? "#065F46" :
                             v.status === "error" ? "#991B1B" : "#374151",
                    }}>
                      {v.status === "connected" ? "● CONECTADO" :
                       v.status === "error" ? "● ERROR" : "● PENDIENTE"}
                    </span>
                  </div>
                  <div style={{ fontSize: "0.85rem", color: "var(--text-muted)", marginTop: "0.2rem" }}>
                    <code>{v.username}@{v.host}:{v.port}</code> · {v.auth_method}
                  </div>
                  {v.os_distro && v.os_distro !== "unknown" && (
                    <div style={{ fontSize: "0.78rem", color: "var(--text-muted)", marginTop: "0.2rem" }}>
                      OS: {v.os_distro}
                    </div>
                  )}
                </div>
                <div style={{ display: "flex", gap: "0.4rem" }}>
                  <button
                    onClick={() => handleTest(v.id)}
                    disabled={testing === v.id}
                    data-testid={`vps-test-${v.id}`}
                    style={{
                      padding: "0.4rem 0.8rem", background: "#5B8DEF", color: "#fff",
                      border: "none", borderRadius: 6, fontWeight: 600, fontSize: "0.85rem",
                      cursor: testing === v.id ? "wait" : "pointer",
                    }}>
                    {testing === v.id ? "Probando…" : "Probar"}
                  </button>
                  <button
                    onClick={() => handleDelete(v.id, v.name)}
                    data-testid={`vps-delete-${v.id}`}
                    style={{
                      padding: "0.4rem 0.8rem", background: "#FEE2E2", color: "#991B1B",
                      border: "none", borderRadius: 6, fontWeight: 600, fontSize: "0.85rem",
                      cursor: "pointer",
                    }}>
                    Borrar
                  </button>
                </div>
              </div>

              {testResult && testResult.vps_id === v.id && (
                <div style={{
                  marginTop: "0.6rem", padding: "0.6rem", borderRadius: 8,
                  background: testResult.ok ? "#ECFDF5" : "#FEF2F2",
                  fontSize: "0.82rem", lineHeight: 1.5,
                }} data-testid={`vps-test-result-${v.id}`}>
                  {testResult.ok ? (
                    <>
                      <div style={{ color: "#065F46", fontWeight: 700 }}>✅ Conexión OK</div>
                      <div style={{ color: "#065F46", marginTop: "0.3rem" }}>
                        {testResult.detected?.uname}<br />
                        Python: {testResult.detected?.python}<br />
                        nginx: {testResult.detected?.has_nginx ? "✓" : "✗"} · git: {testResult.detected?.has_git ? "✓" : "✗"}
                      </div>
                    </>
                  ) : (
                    <div style={{ color: "#991B1B" }}>
                      ⚠ Error: <pre style={{ whiteSpace: "pre-wrap", margin: 0, fontSize: "0.78rem" }}>{testResult.stderr || testResult.error}</pre>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      <div style={{
        marginTop: "1rem", padding: "0.8rem 1rem", background: "#EFF6FF",
        borderRadius: 10, fontSize: "0.82rem", color: "#1E40AF", lineHeight: 1.5,
      }}>
        💡 <b>¿Primera vez?</b> Generá una clave SSH en tu compu con{" "}
        <code>ssh-keygen -t ed25519</code>. Copiá el contenido de <code>~/.ssh/id_ed25519.pub</code>{" "}
        a tu VPS con <code>ssh-copy-id user@ip</code>, y pegá el contenido de la clave privada{" "}
        (<code>~/.ssh/id_ed25519</code>) arriba.
      </div>
    </div>
  );
}
