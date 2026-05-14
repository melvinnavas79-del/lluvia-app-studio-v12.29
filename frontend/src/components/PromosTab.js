import { useEffect, useState } from "react";
import { api, formatError } from "../api";

const DOW_LABELS = ["Lun", "Mar", "Mie", "Jue", "Vie", "Sab", "Dom"];

export default function PromosTab() {
  const [items, setItems] = useState([]);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [form, setForm] = useState({
    rule_id: "",
    description: "",
    discount_pct: 20,
    days_of_week: [],
    days_of_month: [],
    active: true,
  });

  const load = async () => {
    setErr("");
    try {
      const { data } = await api.get("/promos");
      setItems(data.promos || []);
    } catch (e) {
      setErr(formatError(e));
    }
  };
  useEffect(() => { load(); }, []);

  const toggleDow = (d) => setForm((f) => ({
    ...f,
    days_of_week: f.days_of_week.includes(d)
      ? f.days_of_week.filter((x) => x !== d)
      : [...f.days_of_week, d],
  }));

  const create = async (e) => {
    e.preventDefault();
    setErr(""); setMsg("");
    try {
      const payload = {
        ...form,
        rule_id: form.rule_id.trim() || `promo_${Date.now()}`,
        discount_pct: Number(form.discount_pct),
        days_of_month: (form.days_of_month_text || "")
          .toString()
          .split(",")
          .map((x) => parseInt(x.trim(), 10))
          .filter((n) => !isNaN(n) && n >= 1 && n <= 31),
      };
      delete payload.days_of_month_text;
      await api.post("/promos", payload);
      setMsg("Promo creada/actualizada.");
      setTimeout(() => setMsg(""), 3000);
      setForm({
        rule_id: "", description: "", discount_pct: 20,
        days_of_week: [], days_of_month: [], active: true,
      });
      await load();
    } catch (e2) {
      setErr(formatError(e2));
    }
  };

  const remove = async (rule_id) => {
    if (!window.confirm(`Borrar promo "${rule_id}"?`)) return;
    try {
      await api.delete(`/promos/${rule_id}`);
      await load();
    } catch (e2) { setErr(formatError(e2)); }
  };

  return (
    <div data-testid="promos-tab">
      <h2 className="section-title">Promociones automaticas</h2>
      <p className="hero-sub" style={{ marginBottom: "1.5rem" }}>
        Reglas que aplican descuento a los packs de oros segun el dia.
        Si hay varias activas, se aplica la del mayor descuento.
      </p>

      {err && <div className="alert" data-testid="promos-error">{err}</div>}
      {msg && <div className="success" data-testid="promos-success">{msg}</div>}

      <form className="form-card" onSubmit={create} data-testid="promo-form" style={{ marginBottom: "2rem" }}>
        <div className="form-row">
          <div className="field">
            <label>ID de la regla</label>
            <input
              value={form.rule_id}
              onChange={(e) => setForm({ ...form, rule_id: e.target.value })}
              placeholder="fin_semana_20"
              data-testid="promo-rule-id"
              maxLength={40}
            />
          </div>
          <div className="field">
            <label>Descuento (%)</label>
            <input
              type="number" min={1} max={80}
              value={form.discount_pct}
              onChange={(e) => setForm({ ...form, discount_pct: e.target.value })}
              data-testid="promo-discount"
            />
          </div>
        </div>

        <div className="field">
          <label>Descripcion</label>
          <input
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            placeholder="20% off sabados y domingos"
            data-testid="promo-description"
            maxLength={200}
          />
        </div>

        <div className="field" style={{ marginTop: "1rem" }}>
          <label>Dias de la semana</label>
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            {DOW_LABELS.map((lbl, idx) => (
              <button
                type="button"
                key={lbl}
                onClick={() => toggleDow(idx)}
                data-testid={`promo-dow-${idx}`}
                className={`chip ${form.days_of_week.includes(idx) ? "chip-on" : ""}`}
                style={{ cursor: "pointer", background: form.days_of_week.includes(idx) ? "#5fb4ff33" : undefined }}
              >
                {lbl}
              </button>
            ))}
          </div>
        </div>

        <div className="field" style={{ marginTop: "1rem" }}>
          <label>Dias del mes (separados por coma, ej: 1,15,30)</label>
          <input
            value={form.days_of_month_text || ""}
            onChange={(e) => setForm({ ...form, days_of_month_text: e.target.value })}
            placeholder="15"
            data-testid="promo-dom"
          />
        </div>

        <button className="login-btn" type="submit" data-testid="promo-save" style={{ marginTop: "1rem" }}>
          Crear / Actualizar promo
        </button>
      </form>

      <h3>Promos activas ({items.length})</h3>
      {items.length === 0 ? (
        <div className="empty">Sin promos aun. Crea la primera arriba.</div>
      ) : (
        <table className="ag-table" data-testid="promos-list">
          <thead>
            <tr><th>ID</th><th>Descripcion</th><th>%</th><th>Dias</th><th>Activa</th><th></th></tr>
          </thead>
          <tbody>
            {items.map((p) => (
              <tr key={p.rule_id}>
                <td><strong>{p.rule_id}</strong></td>
                <td>{p.description}</td>
                <td>{p.discount_pct}%</td>
                <td style={{ fontSize: "0.85em" }}>
                  {p.days_of_week?.length ? `sem: ${p.days_of_week.map((d) => DOW_LABELS[d]).join(",")}` : ""}
                  {p.days_of_month?.length ? ` mes: ${p.days_of_month.join(",")}` : ""}
                  {!p.days_of_week?.length && !p.days_of_month?.length ? "permanente" : ""}
                </td>
                <td>{p.active ? "Si" : "No"}</td>
                <td>
                  <button className="copy-btn" onClick={() => remove(p.rule_id)} data-testid={`promo-delete-${p.rule_id}`}>
                    Borrar
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
