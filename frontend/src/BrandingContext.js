import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api } from "./api";

const BrandingCtx = createContext(null);

const FALLBACK = {
  product_name: "Bot Multiplataforma",
  tagline: "Un bot que entiende, ejecuta y vende.",
  primary_color: "#f5d76e",
  accent_color: "#5fdbc4",
  background_color: "#08090d",
  text_color: "#e7e9ee",
  logo_data_url: "",
  company_name: "",
  support_email: "",
};

function applyTheme(b) {
  const root = document.documentElement;
  root.style.setProperty("--brand-primary", b.primary_color || FALLBACK.primary_color);
  root.style.setProperty("--brand-accent", b.accent_color || FALLBACK.accent_color);
  root.style.setProperty("--brand-bg", b.background_color || FALLBACK.background_color);
  root.style.setProperty("--brand-text", b.text_color || FALLBACK.text_color);
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
