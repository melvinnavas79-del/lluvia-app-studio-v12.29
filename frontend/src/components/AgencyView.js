import { useEffect, useState } from "react";
import { api, formatError } from "../api";

export default function AgencyView() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    api.get("/agency/clients")
      .then((r) => setData(r.data))
      .catch((e) => setErr(formatError(e)));
  }, []);

  if (err) return <div className="alert">{err}</div>;
  if (!data) return <div className="bc-empty">Cargando...</div>;

  return (
    <div className="agency-view" data-testid="agency-view">
      <div className="ag-stats">
        <div className="ag-stat">
          <div className="ag-stat-label">Clientes activos</div>
          <div className="ag-stat-num">{data.active_count}</div>
        </div>
        <div className="ag-stat">
          <div className="ag-stat-label">MRR estimado</div>
          <div className="ag-stat-num">${data.mrr_usd?.toLocaleString() || 0}<small>USD/mes</small></div>
        </div>
        <div className="ag-stat">
          <div className="ag-stat-label">Total desplegados</div>
          <div className="ag-stat-num">{data.clients?.length || 0}</div>
        </div>
      </div>

      <h3>Clientes desplegados</h3>
      {(!data.clients || data.clients.length === 0) ? (
        <div className="bc-empty">
          Aun no has desplegado clientes. <br/>
          Usa el agente <strong>DevOps</strong> o <strong>App Builder</strong> y pidele:<br/>
          <em>"instala una radio para Pedro Martinez"</em>
        </div>
      ) : (
        <table className="ag-table">
          <thead>
            <tr><th>Cliente</th><th>URL</th><th>Estado</th><th>Plan</th><th>Desde</th></tr>
          </thead>
          <tbody>
            {data.clients.map((c) => (
              <tr key={c.slug || c.id}>
                <td><strong>{c.display || c.slug}</strong></td>
                <td><a href={c.url} target="_blank" rel="noreferrer">{c.url}</a></td>
                <td><span className={`ag-status ${c.active ? "ok" : "down"}`}>
                  {c.active ? "● Activo" : "● Inactivo"}
                </span></td>
                <td>${c.monthly_usd || 199}/mes</td>
                <td>{c.created_at?.slice(0, 10)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
