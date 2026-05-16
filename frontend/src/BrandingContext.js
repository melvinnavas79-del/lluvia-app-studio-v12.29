import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api } from "./api";

const BrandingCtx = createContext(null);

const FALLBACK = {
  product_name: "Lluvia App Studio",
  tagline: "Agentes inteligentes que trabajan por vos 24/7.",
  primary_color: "#0F172A",
  accent_color: "#2563EB",
  background_color: "#FDFBF7",
  text_color: "#111827",
  logo_data_url: "",
  company_name: "",
  support_email: "",
};

function applyTheme(b) {
  const root = document.documentElement;
  // Solo aplicamos primary/accent (el canvas — bg/text/surfaces — lo controla ThemeContext)
  root.style.setProperty("--brand-primary", b.primary_color || FALLBACK.primary_color);
  root.style.setProperty("--brand-accent", b.accent_color || FALLBACK.accent_color);
  if (b.product_name) document.title = b.product_name;
}

export function BrandingProvider({ children }) {
  const [branding, setBranding] = useState(FALLBACK);

  const refresh = useCallback(async () => {
    try {
      const { data } = await api.get("/branding");
      setBranding(data);
      applyTheme(data);
    } catch {
      applyTheme(FALLBACK);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return (
    <BrandingCtx.Provider value={{ branding, refresh, setBranding: (b) => { setBranding(b); applyTheme(b); } }}>
      {children}
    </BrandingCtx.Provider>
  );
}

export const useBranding = () => useContext(BrandingCtx);
