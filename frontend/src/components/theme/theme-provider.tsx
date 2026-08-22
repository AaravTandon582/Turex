"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type ThemePreference = "light" | "dark" | "system";

/**
 * What a first visit gets, before anyone has chosen.
 *
 * Dark, and deliberately *not* "system". A reader spends hours here on dense text and PDF
 * pages, and this is the scheme the product is designed around — deferring to the operating
 * system would give most people light, which is not the default this app wants.
 *
 * It decides nothing after the first visit. The toggle still offers light, dark and system,
 * and a stored choice always wins; this only picks the starting point.
 */
const DEFAULT_PREFERENCE: ThemePreference = "dark";
export type ResolvedTheme = "light" | "dark";

export const THEME_STORAGE_KEY = "turex-theme";

interface ThemeContextValue {
  preference: ThemePreference;
  resolved: ResolvedTheme;
  setPreference: (preference: ThemePreference) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

/** What the operating system asks for. Only consulted when the reader has chosen "system". */
function systemTheme(): ResolvedTheme {
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function resolve(preference: ThemePreference): ResolvedTheme {
  return preference === "system" ? systemTheme() : preference;
}

function applyTheme(resolved: ResolvedTheme): void {
  document.documentElement.classList.toggle("dark", resolved === "dark");
  document.documentElement.style.colorScheme = resolved;
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  // Starts as "system" on both server and client so the first render matches the markup
  // the inline script produced; the effect below reconciles with what is actually stored.
  const [preference, setPreferenceState] = useState<ThemePreference>(DEFAULT_PREFERENCE);
  const [resolved, setResolved] = useState<ResolvedTheme>("dark");

  useEffect(() => {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY) as ThemePreference | null;
    const initial: ThemePreference =
      stored === "light" || stored === "dark" || stored === "system"
        ? stored
        : DEFAULT_PREFERENCE;
    setPreferenceState(initial);
    setResolved(resolve(initial));
  }, []);

  useEffect(() => {
    applyTheme(resolved);
  }, [resolved]);

  // Track OS changes only while the user is deferring to the system.
  useEffect(() => {
    if (preference !== "system") return;
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => setResolved(systemTheme());
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, [preference]);

  const setPreference = useCallback((next: ThemePreference) => {
    setPreferenceState(next);
    setResolved(next === "system" ? systemTheme() : next);
    window.localStorage.setItem(THEME_STORAGE_KEY, next);
  }, []);

  const value = useMemo(
    () => ({ preference, resolved, setPreference }),
    [preference, resolved, setPreference],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const context = useContext(ThemeContext);
  if (!context) throw new Error("useTheme must be used inside a ThemeProvider");
  return context;
}

/**
 * Applies the stored theme before first paint.
 *
 * Rendered as a blocking inline script in <head>. Without it the page paints light, then
 * snaps to dark once React hydrates — a visible flash on every navigation to the app.
 */
export const themeInitScript = `
(function () {
  try {
    var stored = localStorage.getItem(${JSON.stringify(THEME_STORAGE_KEY)});
    // No stored choice means dark — the app's default, not the system's. Only someone who has
    // explicitly asked to follow the system gets asked about it.
    var dark = stored === 'dark' || !stored ||
      (stored === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches);
    document.documentElement.classList.toggle('dark', dark);
    document.documentElement.style.colorScheme = dark ? 'dark' : 'light';
  } catch (e) {}
})();
`.trim();
