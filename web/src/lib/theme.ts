/** Light is the default; dark is a toggle. The choice is per-browser convenience only (never needed for correctness). */
export type Theme = "light" | "dark";

const KEY = "eventshock-theme";

export function parseTheme(v: string | null | undefined): Theme | null {
  return v === "light" || v === "dark" ? v : null;
}

/** ?theme= (for reproducible captures) beats the stored choice; the default is always light, whatever the OS prefers. */
export function resolveTheme(search: string, stored: string | null): Theme {
  return parseTheme(new URLSearchParams(search).get("theme")) ?? parseTheme(stored) ?? "light";
}

function readStored(): string | null {
  try {
    return window.localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  root.dataset.theme = theme;
  root.style.colorScheme = theme;
  document.querySelector('meta[name="color-scheme"]')?.setAttribute("content", theme);
}

export function initialTheme(): Theme {
  return resolveTheme(window.location.search, readStored());
}

export function storeTheme(theme: Theme): void {
  try {
    window.localStorage.setItem(KEY, theme);
  } catch {
    /* private window / blocked storage: the toggle still works for this page view */
  }
}
