import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api } from "./api";
import { useTheme } from "./ThemeContext";

const BrandingCtx = createContext(null);

const FALLBACK = {
  product_name: "Lluvia App Studio",
  tagline: "Agentes inteligentes que trabajan por ti 24/7.",
  primary_color: "#0F172A",
  accent_color: "#2563EB",
  background_color: "#FDFBF7",
  text_color: "#111827",
  default_theme: "light",
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
  const themeCtx = useTheme();

  const refresh = useCallback(async () => {
    try {
      const { data } = await api.get("/branding");
      setBranding(data);
      applyTheme(data);
      if (data.default_theme && themeCtx?.applyDefault) {
        themeCtx.applyDefault(data.default_theme);
      }
    } catch {
      applyTheme(FALLBACK);
    }
  }, [themeCtx]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return (
    <BrandingCtx.Provider value={{
      branding,
      refresh,
      setBranding: (b) => {
        setBranding(b);
        applyTheme(b);
        if (b?.default_theme && themeCtx?.applyDefault) themeCtx.applyDefault(b.default_theme);
      },
    }}>
      {children}
    </BrandingCtx.Provider>
  );
}

export const useBranding = () => useContext(BrandingCtx);
