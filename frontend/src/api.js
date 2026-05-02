import axios from "axios";

// Sanitizar BASE para evitar duplicacion de /api.
// Acepta cualquiera de estas formas en REACT_APP_BACKEND_URL:
//   https://dominio.com           -> https://dominio.com/api
//   https://dominio.com/          -> https://dominio.com/api
//   https://dominio.com/api       -> https://dominio.com/api
//   https://dominio.com/api/      -> https://dominio.com/api
//   http://1.2.3.4:8001           -> http://1.2.3.4:8001/api
//   http://1.2.3.4:8001/api       -> http://1.2.3.4:8001/api
const RAW = process.env.REACT_APP_BACKEND_URL || "";
const BASE = RAW.replace(/\/+$/, "").replace(/\/api$/, "");
export const API = `${BASE}/api`;

export const TOKEN_KEY = "bot_admin_token";

export const getToken = () => localStorage.getItem(TOKEN_KEY);
export const setToken = (t) => localStorage.setItem(TOKEN_KEY, t);
export const clearToken = () => localStorage.removeItem(TOKEN_KEY);

export const api = axios.create({ baseURL: API });

api.interceptors.request.use((cfg) => {
  const t = getToken();
  if (t) cfg.headers.Authorization = `Bearer ${t}`;
  return cfg;
});

export const formatError = (e) => {
  const detail = e?.response?.data?.detail;
  if (!detail) return e.message || "Error desconocido";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail))
    return detail.map((x) => (x?.msg ? x.msg : JSON.stringify(x))).join(" · ");
  if (typeof detail === "object" && detail.msg) return detail.msg;
  return String(detail);
};

export const fmtMoney = (n) =>
  new Intl.NumberFormat("es-AR", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 0,
  }).format(n || 0);

export const fmtDate = (iso) => {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("es-AR", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
};
