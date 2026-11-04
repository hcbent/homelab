import { EuiProvider, useEuiTheme } from "@elastic/eui";
import { ReactNode, createContext, useContext, useEffect, useMemo, useState } from "react";

const KEY = "ecm.theme";
export type Mode = "light" | "dark";

const media = () => (typeof matchMedia === "function" ? matchMedia("(prefers-color-scheme: dark)") : null);

function storedMode(): Mode | null {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : null;
  } catch { return null; }
}

interface ThemeApi { mode: Mode; toggle: () => void }
const ThemeContext = createContext<ThemeApi>({ mode: "light", toggle: () => {} });
export const useThemeMode = () => useContext(ThemeContext);

/** Copies EUI theme tokens into CSS variables so the plain stylesheet follows the installed theme. */
function ThemeVars() {
  const { euiTheme } = useEuiTheme();
  useEffect(() => {
    const c = euiTheme.colors;
    const s = document.documentElement.style;
    s.setProperty("--ecm-canvas", c.backgroundBasePlain);
    s.setProperty("--ecm-surface", c.backgroundBasePlain);
    s.setProperty("--ecm-surface-alt", c.backgroundBaseSubdued);
    s.setProperty("--ecm-border", c.borderBasePlain);
    s.setProperty("--ecm-text", c.textParagraph);
    s.setProperty("--ecm-heading", c.textHeading);
    s.setProperty("--ecm-muted", c.textSubdued);
    s.setProperty("--ecm-accent", c.primary);
    s.setProperty("--ecm-accent-text", c.textPrimary);
    s.setProperty("--ecm-accent-tint", c.backgroundLightPrimary);
    s.setProperty("--ecm-frame-fill", c.backgroundBaseFormsPrepend);
    s.setProperty("--ecm-frame-edge", c.borderBaseProminent);
    s.setProperty("--ecm-hover", c.backgroundBaseInteractiveHover);
    s.setProperty("--ecm-row-changed", c.backgroundLightPrimary);
  }, [euiTheme]);
  return null;
}

/** Follows the system colour scheme until the operator picks a theme; the pick is persisted. */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [override, setOverride] = useState<Mode | null>(storedMode);
  const [system, setSystem] = useState<Mode>(() => (media()?.matches ? "dark" : "light"));

  useEffect(() => {
    const m = media();
    if (!m) return;
    const on = () => setSystem(m.matches ? "dark" : "light");
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, []);

  const mode = override ?? system;
  const api = useMemo<ThemeApi>(() => ({
    mode,
    toggle: () => {
      const next: Mode = mode === "dark" ? "light" : "dark";
      setOverride(next);
      try { localStorage.setItem(KEY, next); } catch { /* private mode */ }
    },
  }), [mode]);

  useEffect(() => { document.documentElement.dataset.theme = mode; }, [mode]);

  return (
    <EuiProvider colorMode={mode}>
      <ThemeVars />
      <ThemeContext.Provider value={api}>{children}</ThemeContext.Provider>
    </EuiProvider>
  );
}
