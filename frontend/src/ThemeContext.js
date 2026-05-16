/* ThemeContext — Toggle Light/Dark Premium persistente.
   Funciona en paralelo con BrandingContext (branding solo controla
   primary/accent; el theme controla canvas: bg/surface/text/border). */
import { createContext, useContext, useEffect, useState, useCallback } from "react";

const ThemeCtx = createContext(null);
const STORAGE_KEY = "lluvia-theme";

const LIGHT_VARS = {
  "--brand-bg": "#FDFBF7",
  "--brand-text": "#111827",
  "--surface": "#FFFFFF",
  "--surface-soft": "#F8F7F2",
  "--surface-warm": "#F4F1EA",
  "--text-primary": "#111827",
  "--text-secondary": "#4B5563",
  "--text-muted": "#6B7280",
  "--border": "#E7E5E0",
  "--border-strong": "#D6D3CB",
};

const DARK_VARS = {
  "--brand-bg": "#0B0F19",
  "--brand-text": "#F9FAFB",
  "--surface": "#111827",
  "--surface-soft": "#0F172A",
  "--surface-warm": "#1F2937",
  "--text-primary": "#F9FAFB",
  "--text-secondary": "#9CA3AF",
  "--text-muted": "#6B7280",
  "--border": "#1F2937",
  "--border-strong": "#374151",
};

function apply(mode) {
  const root = document.documentElement;
  const vars = mode === "dark" ? DARK_VARS : LIGHT_VARS;
  Object.entries(vars).forEach(([k, v]) => root.style.setProperty(k, v));
  root.setAttribute("data-theme", mode);
}

export function ThemeProvider({ children }) {
  const [mode, setMode] = useState(() => {
    try { return localStorage.getItem(STORAGE_KEY) || "light"; }
    catch { return "light"; }
  });
  const [userOverride, setUserOverride] = useState(() => {
    try { return localStorage.getItem(STORAGE_KEY) !== null; }
    catch { return false; }
  });

  useEffect(() => {
    apply(mode);
    if (userOverride) {
      try { localStorage.setItem(STORAGE_KEY, mode); } catch {}
    }
  }, [mode, userOverride]);

  const toggle = useCallback(() => {
    setMode((m) => (m === "dark" ? "light" : "dark"));
    setUserOverride(true);
  }, []);

  /* applyDefault: usado por BrandingContext para que admin elija tema por defecto.
     Solo aplica si el usuario aún no toggleó manualmente (sin entry en localStorage). */
  const applyDefault = useCallback((defaultMode) => {
    if (userOverride) return;
    if (defaultMode === "light" || defaultMode === "dark") {
      setMode(defaultMode);
    }
  }, [userOverride]);

  return (
    <ThemeCtx.Provider value={{ mode, toggle, setMode, applyDefault }}>
      {children}
    </ThemeCtx.Provider>
  );
}

export const useTheme = () => useContext(ThemeCtx);

export function ThemeToggle({ className = "", size = 36 }) {
  const { mode, toggle } = useTheme();
  const isDark = mode === "dark";
  return (
    <button
      type="button"
      onClick={toggle}
      className={`theme-toggle ${className}`}
      data-testid="theme-toggle"
      title={isDark ? "Cambiar a tema claro" : "Cambiar a tema oscuro"}
      aria-label="Cambiar tema"
      style={{ width: size, height: size }}
    >
      {isDark ? (
        /* sun icon */
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <circle cx="12" cy="12" r="4"/>
          <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/>
        </svg>
      ) : (
        /* moon icon */
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
        </svg>
      )}
    </button>
  );
}
