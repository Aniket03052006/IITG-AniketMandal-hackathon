/**
 * The active portfolio is OPTIONAL and per-browser: nothing selected (null) = the synthetic default portfolio.
 * It is a convenience only (never needed for correctness), so every storage access is guarded and the app works without it.
 * `?portfolio=` beats the stored choice (so a link or a capture is reproducible); `?portfolio=default` forces the default.
 */
import { useSyncExternalStore } from "react";

export const DEFAULT_PORTFOLIO = "default";
const KEY = "eventshock-portfolio";
const EVENT = "eventshock-portfolio-change";

export function parsePortfolioId(v: string | null | undefined): string | null {
  return v && /^pf_[a-z0-9]{6,32}$/.test(v) ? v : null;
}

/** null = the default. A query value of "default" (or anything unrecognised) is the default and ignores storage. */
export function resolveActivePortfolio(search: string, stored: string | null): string | null {
  const q = new URLSearchParams(search).get("portfolio");
  if (q !== null) return parsePortfolioId(q);
  return parsePortfolioId(stored);
}

function readStored(): string | null {
  try {
    return window.localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

let current: string | null | undefined;

function ensure(): string | null {
  if (current === undefined) current = resolveActivePortfolio(window.location.search, readStored());
  return current;
}

export function getActivePortfolio(): string | null {
  return ensure();
}

/** Choose a personal portfolio, or pass null to go back to the default. */
export function setActivePortfolio(id: string | null): void {
  current = parsePortfolioId(id);
  try {
    if (current) window.localStorage.setItem(KEY, current);
    else window.localStorage.removeItem(KEY);
  } catch {
    /* blocked storage: the choice still holds for this page view */
  }
  window.dispatchEvent(new Event(EVENT));
}

function subscribe(cb: () => void): () => void {
  window.addEventListener(EVENT, cb);
  return () => window.removeEventListener(EVENT, cb);
}

/** The portfolio id requests should carry (null = the default). Re-renders on a switch. */
export function useActivePortfolio(): string | null {
  return useSyncExternalStore(subscribe, ensure, () => null);
}

/** Test helper: forget the cached choice so the next read re-resolves from the URL and storage. */
export function resetActivePortfolioForTests(): void {
  current = undefined;
}

/** Query-string value for an API call: omitted for the default so default requests are byte-identical to before. */
export const pfParam = (id: string | null): string => (id ? `portfolio_id=${encodeURIComponent(id)}` : "");

const SYMBOL: Record<string, string> = { USD: "$", INR: "₹", EUR: "€", GBP: "£", JPY: "¥" };
export const currencySymbol = (code: string | undefined | null): string => (code ? (SYMBOL[code.toUpperCase()] ?? `${code.toUpperCase()} `) : "$");
