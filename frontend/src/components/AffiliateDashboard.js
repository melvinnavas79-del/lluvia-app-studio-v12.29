import { useEffect, useState } from "react";
import { api, fmtMoney, fmtDate, formatError } from "../api";
import { useAuth } from "../AuthContext";

const PLATFORMS = ["whatsapp", "telegram", "instagram", "web", "manual"];

export default function AffiliateDashboard() {
  const { user, logout } = useAuth();
  const [stats, setStats] = useState(null);
  const [sales, setSales] = useState([]);
  const [err, setErr] = useState("");

  const load = async () => {
    setErr("");
    try {
      const [s, sa] = await Promise.all([
        api.get("/stats/me"),
        api.get("/sales"),
      ]);
      setStats(s.data);
      setSales(sa.data);
    } catch (e) {
      setErr(formatError(e));
    }
  };

  useEffect(() => { load(); }, []);

  return (
    <div className="container">
      <div className="brand">
        <div className="brand-mark">
          <span className="brand-dot" />
          <span>AFILIADO // {user?.affiliate_code || "—"}</span>
        </div>
        <button className="logout-btn" onClick={logout} data-testid="logout-btn">
          Cerrar sesion
        </button>
      </div>

      <header className="hero">
        <span className="hero-tag">PANEL PERSONAL</span>
        <h1 data-testid="aff-hello">Hola {user?.name},</h1>
        <p className="hero-sub">
          Ves solo tus propias ventas y comisiones. Tu codigo de afiliado es{" "}
          <strong style={{ color: "#f5d76e" }}>{user?.affiliate_code}</strong>.
        </p>
      </header>

      {err && <div className="alert">{err}</div>}

      {/* KPIs */}
      <h2 className="section-title">01 — Mis numeros</h2>
      <div className="kpi-grid" data-testid="aff-kpis">
        <Kpi label="Ventas" value={stats?.total_sales ?? 0} />
        <Kpi label="Facturado" value={fmtMoney(stats?.total_amount)} />
        <Kpi label="Comision total" value={fmtMoney(stats?.total_commission)} accent />
        <Kpi label="Pendiente de cobro" value={fmtMoney(stats?.pending_commission)} warn />
        <Kpi label="Cobrado" value={fmtMoney(stats?.paid_commission)} ok />
        <Kpi label="Ultima venta" value={fmtDate(stats?.last_sale_at)} small />
      </div>

      <h2 className="section-title">02 — Historial de ventas</h2>
      <div className="table-wrap" data-testid="aff-sales-table">
        <table>
          <thead>
            <tr>
              <th>Fecha</th>
              <th>Producto</th>
              <th>Cliente</th>
              <th>Canal</th>
              <th style={{ textAlign: "right" }}>Monto</th>
              <th style={{ textAlign: "right" }}>Comision</th>
              <th>Estado</th>
            </tr>
          </thead>
          <tbody>
            {sales.length === 0 && (
              <tr><td colSpan={7} className="empty">Aun no tienes ventas registradas.</td></tr>
            )}
            {sales.map((s) => (
              <tr key={s.id}>
                <td>{fmtDate(s.created_at)}</td>
                <td>{s.product}</td>
                <td>{s.customer || "—"}</td>
                <td><span className="chip">{s.platform}</span></td>
                <td style={{ textAlign: "right" }}>{fmtMoney(s.amount)}</td>
                <td style={{ textAlign: "right", color: "#f5d76e" }}>{fmtMoney(s.commission)}</td>
                <td>
                  {s.paid
                    ? <span className="badge ok">COBRADO</span>
                    : <span className="badge warn">PENDIENTE</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Kpi({ label, value, accent, ok, warn, small }) {
  let color = "#ebedf2";
  if (accent) color = "#f5d76e";
  if (ok) color = "#5fdbc4";
  if (warn) color = "#ec9b3b";
  return (
    <div className="kpi">
      <div className="kpi-label">{label}</div>
      <div className="kpi-value" style={{ color, fontSize: small ? "1.05rem" : undefined }}>
        {value}
      </div>
    </div>
  );
}

export { PLATFORMS };
