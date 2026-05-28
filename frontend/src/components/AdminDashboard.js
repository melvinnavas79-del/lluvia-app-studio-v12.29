import { useEffect, useState } from "react";
import { api, fmtMoney, fmtDate, formatError } from "../api";
import { useAuth } from "../AuthContext";
import { useBranding } from "../BrandingContext";
import { PLATFORMS } from "./AffiliateDashboard";
import BrandingTab from "./BrandingTab";
import BossConsole from "./BossConsole";
import AgentBuilder from "./AgentBuilder";
import AgencyView from "./AgencyView";
import ProposalsTab from "./ProposalsTab";
import PromosTab from "./PromosTab";
import CallCenter from "./CallCenter";
import SuperAdminPanel from "./SuperAdminPanel";
import SettingsTab from "./SettingsTab";
import DevOpsConsole from "./DevOpsConsole";
import MasterConsole from "./MasterConsole";

export default function AdminDashboard() {
  const { user, logout } = useAuth();
  const { branding } = useBranding();
  const ALLOWED_TABS = ["super","overview","console","callcenter","agency","builder","proposals","promos","affiliates","sales","branding","settings","devops","masterops"];
  const MVP_TABS = ["builder","branding","overview","settings"];
  const hashToTab = (h) => {
    const key = (h || "").replace(/^#\/?/, "").trim();
    return ALLOWED_TABS.includes(key) ? key : "console";
  };
  const [tab, setTab] = useState(() => hashToTab(window.location.hash));
  const [network, setNetwork] = useState(null);
  const [affiliates, setAffiliates] = useState([]);
  const [sales, setSales] = useState([]);
  const [agents, setAgents] = useState([]);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");

  useEffect(() => {
    const onHash = () => setTab(hashToTab(window.location.hash));
    const onGoSettings = () => { window.location.hash = "#/settings"; setTab("settings"); };
    window.addEventListener("hashchange", onHash);
    window.addEventListener("lluvia:goto-settings", onGoSettings);
    return () => {
      window.removeEventListener("hashchange", onHash);
      window.removeEventListener("lluvia:goto-settings", onGoSettings);
    };
  }, []);
  const goTab = (k) => { setTab(k); window.location.hash = `#/${k}`; };

  const refresh = async () => {
    setErr("");
    try {
      const [n, a, s, ag] = await Promise.all([
        api.get("/stats/network"),
        api.get("/affiliates"),
        api.get("/sales"),
        api.get("/console/agents"),
      ]);
      setNetwork(n.data);
      setAffiliates(a.data);
      setSales(s.data);
      setAgents(ag.data.agents || []);
    } catch (e) {
      setErr(formatError(e));
    }
  };
  useEffect(() => { refresh(); }, []);

  const flash = (text) => {
    setMsg(text);
    setTimeout(() => setMsg(""), 3000);
  };

  return (
    <div className="container">
      <div className="brand">
        <div className="brand-mark">
          <span className="brand-dot" />
          <span>ADMIN // {user?.email}</span>
        </div>
        <button className="logout-btn" onClick={logout} data-testid="logout-btn">
          Cerrar sesion
        </button>
      </div>

      <header className="hero">
        <span className="hero-tag">PANEL DE CONTROL — ADMIN</span>
        <h1>{branding?.product_name ? `${branding.product_name}.` : "Lluvia App Studio."}</h1>
        <p className="hero-sub">
          Consola maestra, agentes E1-E11, DevOps AI, usuarios, ventas y configuración completa.
        </p>
      </header>

      {err && <div className="alert" data-testid="admin-error">{err}</div>}
      {msg && <div className="success" data-testid="admin-success">{msg}</div>}

      <div className="tabs" data-testid="admin-tabs" style={{ flexWrap: "wrap", gap: "4px" }}>
        {[
          ["console",   "💬 Chat / Agentes"],
          ["overview",  "📊 Overview"],
          ["super",     "👥 Usuarios"],
          ["builder",   "🤖 Constructor"],
          ["agency",    "🏢 Agencia"],
          ["callcenter","📞 Call Center"],
          ["devops",    "⚙️ DevOps AI"],
          ["masterops", "🖥️ Master Console"],
          ["affiliates","🔗 Afiliados"],
          ["sales",     "💰 Ventas"],
          ["proposals", "📋 Propuestas"],
          ["promos",    "🎁 Promos"],
          ["branding",  "🎨 Branding"],
          ["settings",  "⚙️ Mi Cuenta"],
        ].map(([k, label]) => (
          <button
            key={k}
            className={`tab ${tab === k ? "active" : ""}`}
            onClick={() => goTab(k)}
            data-testid={`tab-${k}`}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "super" && <SuperAdminPanel />}
      {tab === "overview" && <Overview network={network} />}
      {tab === "console" && <BossConsole />}
      {tab === "callcenter" && <CallCenter agents={agents} />}
      {tab === "agency" && <AgencyView />}
      {tab === "builder" && <AgentBuilder />}
      {tab === "proposals" && <ProposalsTab />}
      {tab === "promos" && <PromosTab />}
      {tab === "affiliates" && (
        <AffiliatesTab
          affiliates={affiliates}
          onChange={refresh}
          flash={flash}
          setErr={setErr}
        />
      )}
      {tab === "sales" && (
        <SalesTab
          sales={sales}
          affiliates={affiliates}
          onChange={refresh}
          flash={flash}
          setErr={setErr}
        />
      )}
      {tab === "branding" && <BrandingTab />}
      {tab === "settings" && <SettingsTab />}
      {tab === "devops" && <DevOpsConsole />}
      {tab === "masterops" && <MasterConsole />}
    </div>
  );
}

// ============================================================
// OVERVIEW
// ============================================================
function Overview({ network }) {
  if (!network) return <div className="empty">Cargando...</div>;
  const o = network.overall;
  return (
    <>
      <h2 className="section-title">01 — Total de la red</h2>
      <div className="kpi-grid" data-testid="overview-kpis">
        <Kpi label="Afiliados" value={network.affiliates_count} />
        <Kpi label="Ventas" value={o.total_sales} />
        <Kpi label="Facturado" value={fmtMoney(o.total_amount)} />
        <Kpi label="Comisiones generadas" value={fmtMoney(o.total_commission)} accent />
        <Kpi label="Pendientes de pago" value={fmtMoney(o.pending_commission)} warn />
        <Kpi label="Pagadas" value={fmtMoney(o.paid_commission)} ok />
      </div>

      <h2 className="section-title">02 — Ranking de afiliados</h2>
      <div className="table-wrap" data-testid="ranking-table">
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Afiliado</th>
              <th>Codigo</th>
              <th style={{ textAlign: "right" }}>Ventas</th>
              <th style={{ textAlign: "right" }}>Facturado</th>
              <th style={{ textAlign: "right" }}>Comision</th>
              <th style={{ textAlign: "right" }}>Pendiente</th>
            </tr>
          </thead>
          <tbody>
            {network.breakdown.length === 0 && (
              <tr><td colSpan={7} className="empty">Aun no hay afiliados con ventas.</td></tr>
            )}
            {network.breakdown.map((a, i) => (
              <tr key={a.affiliate_id}>
                <td>{i + 1}</td>
                <td>{a.name}</td>
                <td><span className="chip">{a.affiliate_code}</span></td>
                <td style={{ textAlign: "right" }}>{a.total_sales}</td>
                <td style={{ textAlign: "right" }}>{fmtMoney(a.total_amount)}</td>
                <td style={{ textAlign: "right", color: "#f5d76e" }}>{fmtMoney(a.total_commission)}</td>
                <td style={{ textAlign: "right", color: "#ec9b3b" }}>{fmtMoney(a.pending_commission)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

// ============================================================
// AFILIADOS
// ============================================================
function AffiliatesTab({ affiliates, onChange, flash, setErr }) {
  const [form, setForm] = useState({ name: "", email: "", password: "", commission_pct: 20 });
  const [creating, setCreating] = useState(false);

  const create = async (e) => {
    e.preventDefault();
    setCreating(true);
    setErr("");
    try {
      const { data } = await api.post("/affiliates", {
        ...form,
        commission_pct: Number(form.commission_pct),
      });
      flash(`Afiliado creado: ${data.affiliate_code}`);
      setForm({ name: "", email: "", password: "", commission_pct: 20 });
      onChange();
    } catch (e) {
      setErr(formatError(e));
    } finally {
      setCreating(false);
    }
  };

  const toggle = async (a) => {
    try {
      await api.patch(`/affiliates/${a.id}`, { active: !a.active });
      onChange();
    } catch (e) {
      setErr(formatError(e));
    }
  };

  return (
    <>
      <h2 className="section-title">+ Crear afiliado</h2>
      <form className="form-card" onSubmit={create} data-testid="aff-create-form">
        <div className="form-row">
          <Input label="Nombre" value={form.name} onChange={(v) => setForm({ ...form, name: v })} testid="aff-name" required />
          <Input label="Email" type="email" value={form.email} onChange={(v) => setForm({ ...form, email: v })} testid="aff-email" required />
        </div>
        <div className="form-row">
          <Input label="Password" type="password" value={form.password} onChange={(v) => setForm({ ...form, password: v })} testid="aff-password" required minLength={6} />
          <Input label="Comision %" type="number" value={form.commission_pct} onChange={(v) => setForm({ ...form, commission_pct: v })} testid="aff-pct" required min={0} max={100} step="0.1" />
        </div>
        <button className="login-btn" disabled={creating} data-testid="aff-create-submit">
          {creating ? "Creando..." : "Crear afiliado"}
        </button>
      </form>

      <h2 className="section-title">Afiliados activos ({affiliates.length})</h2>
      <div className="table-wrap" data-testid="affiliates-table">
        <table>
          <thead>
            <tr>
              <th>Nombre</th>
              <th>Email</th>
              <th>Codigo</th>
              <th style={{ textAlign: "right" }}>Comision %</th>
              <th>Alta</th>
              <th>Estado</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {affiliates.length === 0 && (
              <tr><td colSpan={7} className="empty">Aun no hay afiliados. Crea el primero arriba.</td></tr>
            )}
            {affiliates.map((a) => (
              <tr key={a.id}>
                <td>{a.name}</td>
                <td>{a.email}</td>
                <td><span className="chip">{a.affiliate_code}</span></td>
                <td style={{ textAlign: "right" }}>{a.commission_pct}%</td>
                <td>{fmtDate(a.created_at)}</td>
                <td>{a.active ? <span className="badge ok">ACTIVO</span> : <span className="badge no">INACTIVO</span>}</td>
                <td>
                  <button
                    className="copy-btn"
                    onClick={() => toggle(a)}
                    data-testid={`toggle-${a.affiliate_code}`}
                  >
                    {a.active ? "DESACTIVAR" : "ACTIVAR"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

// ============================================================
// VENTAS
// ============================================================
function SalesTab({ sales, affiliates, onChange, flash, setErr }) {
  const [form, setForm] = useState({
    affiliate_code: "",
    amount: "",
    product: "",
    customer: "",
    platform: "manual",
    notes: "",
  });
  const [creating, setCreating] = useState(false);

  const create = async (e) => {
    e.preventDefault();
    setCreating(true);
    setErr("");
    try {
      await api.post("/sales", {
        ...form,
        amount: Number(form.amount),
      });
      flash("Venta registrada");
      setForm({ affiliate_code: "", amount: "", product: "", customer: "", platform: "manual", notes: "" });
      onChange();
    } catch (e) {
      setErr(formatError(e));
    } finally {
      setCreating(false);
    }
  };

  const togglePay = async (s) => {
    try {
      await api.patch(`/sales/${s.id}/pay`, { paid: !s.paid });
      onChange();
    } catch (e) {
      setErr(formatError(e));
    }
  };

  return (
    <>
      <h2 className="section-title">+ Registrar venta</h2>
      <form className="form-card" onSubmit={create} data-testid="sale-create-form">
        <div className="form-row">
          <div className="field">
            <label>Codigo afiliado</label>
            <select
              value={form.affiliate_code}
              onChange={(e) => setForm({ ...form, affiliate_code: e.target.value })}
              required
              data-testid="sale-affiliate"
            >
              <option value="">— Selecciona —</option>
              {affiliates.filter(a => a.active).map((a) => (
                <option key={a.id} value={a.affiliate_code}>
                  {a.affiliate_code} · {a.name} ({a.commission_pct}%)
                </option>
              ))}
            </select>
          </div>
          <Input label="Monto" type="number" value={form.amount} onChange={(v) => setForm({ ...form, amount: v })} testid="sale-amount" required min={0} step="0.01" />
        </div>
        <div className="form-row">
          <Input label="Producto" value={form.product} onChange={(v) => setForm({ ...form, product: v })} testid="sale-product" required />
          <Input label="Cliente (opcional)" value={form.customer} onChange={(v) => setForm({ ...form, customer: v })} testid="sale-customer" />
        </div>
        <div className="form-row">
          <div className="field">
            <label>Canal</label>
            <select
              value={form.platform}
              onChange={(e) => setForm({ ...form, platform: e.target.value })}
              data-testid="sale-platform"
            >
              {PLATFORMS.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </div>
          <Input label="Notas" value={form.notes} onChange={(v) => setForm({ ...form, notes: v })} testid="sale-notes" />
        </div>
        <button className="login-btn" disabled={creating} data-testid="sale-create-submit">
          {creating ? "Registrando..." : "Registrar venta"}
        </button>
      </form>

      <h2 className="section-title">Ventas registradas ({sales.length})</h2>
      <div className="table-wrap" data-testid="sales-table">
        <table>
          <thead>
            <tr>
              <th>Fecha</th>
              <th>Afiliado</th>
              <th>Producto</th>
              <th>Cliente</th>
              <th>Canal</th>
              <th style={{ textAlign: "right" }}>Monto</th>
              <th style={{ textAlign: "right" }}>Comision</th>
              <th>Estado</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {sales.length === 0 && (
              <tr><td colSpan={9} className="empty">Aun no hay ventas registradas.</td></tr>
            )}
            {sales.map((s) => (
              <tr key={s.id}>
                <td>{fmtDate(s.created_at)}</td>
                <td>{s.affiliate_name || s.affiliate_code}</td>
                <td>{s.product}</td>
                <td>{s.customer || "—"}</td>
                <td><span className="chip">{s.platform}</span></td>
                <td style={{ textAlign: "right" }}>{fmtMoney(s.amount)}</td>
                <td style={{ textAlign: "right", color: "#f5d76e" }}>{fmtMoney(s.commission)}</td>
                <td>
                  {s.paid
                    ? <span className="badge ok">PAGADA</span>
                    : <span className="badge warn">PENDIENTE</span>}
                </td>
                <td>
                  <button
                    className="copy-btn"
                    onClick={() => togglePay(s)}
                    data-testid={`pay-${s.id}`}
                  >
                    {s.paid ? "MARCAR PENDIENTE" : "MARCAR PAGADA"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

// ============================================================
// HELPERS
// ============================================================
function Kpi({ label, value, accent, ok, warn }) {
  let color = "#ebedf2";
  if (accent) color = "#f5d76e";
  if (ok) color = "#5fdbc4";
  if (warn) color = "#ec9b3b";
  return (
    <div className="kpi">
      <div className="kpi-label">{label}</div>
      <div className="kpi-value" style={{ color }}>{value}</div>
    </div>
  );
}

function Input({ label, value, onChange, type = "text", testid, ...rest }) {
  return (
    <div className="field">
      <label>{label}</label>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        data-testid={testid}
        {...rest}
      />
    </div>
  );
}
