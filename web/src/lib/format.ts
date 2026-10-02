const MINUS = "−";

/** Compact currency: $558.8M, $12.4K. Negative values use a true minus sign. */
export function money(value: number, opts: { signed?: boolean; currency?: string; digits?: number } = {}): string {
  const { signed = false, currency = "$", digits } = opts;
  const abs = Math.abs(value);
  let body: string;
  if (abs >= 1e9) body = `${(abs / 1e9).toFixed(digits ?? 2)}B`;
  else if (abs >= 1e6) body = `${(abs / 1e6).toFixed(digits ?? 1)}M`;
  else if (abs >= 1e3) body = `${(abs / 1e3).toFixed(digits ?? 1)}K`;
  else body = abs.toFixed(0);
  const sign = value < 0 ? MINUS : signed && value > 0 ? "+" : "";
  return `${sign}${currency}${body}`;
}

export function moneyFull(value: number, currency = "$"): string {
  const sign = value < 0 ? MINUS : "";
  return `${sign}${currency}${Math.abs(Math.round(value)).toLocaleString("en-US")}`;
}

export function pct(value: number, digits = 1, signed = false): string {
  const v = value * 100;
  const sign = v < 0 ? MINUS : signed && v > 0 ? "+" : "";
  return `${sign}${Math.abs(v).toFixed(digits)}%`;
}

export function signed(value: number, digits = 2): string {
  const sign = value < 0 ? MINUS : value > 0 ? "+" : "";
  return `${sign}${Math.abs(value).toFixed(digits)}`;
}

/** Units per risk factor, used to print shocks consistently. */
export function shockValue(factor: string, value: number): string {
  switch (factor) {
    case "EQUITY":
      return pct(value, 1, true);
    case "RATES_BPS":
    case "CREDIT_SPREAD_BPS":
      return `${value < 0 ? MINUS : value > 0 ? "+" : ""}${Math.abs(value).toFixed(0)} bp`;
    case "PD_MULTIPLIER":
      return `${value.toFixed(2)}×`;
    case "LGD_ADD":
      return `${value < 0 ? MINUS : "+"}${Math.abs(value * 100).toFixed(1)} pp`;
    default:
      return String(value);
  }
}

export const FACTOR_LABEL: Record<string, string> = {
  EQUITY: "Equity return",
  RATES_BPS: "Rates (parallel)",
  CREDIT_SPREAD_BPS: "Credit spread",
  PD_MULTIPLIER: "PD multiplier",
  LGD_ADD: "LGD add-on",
};

export const SCOPE_LABEL: Record<string, string> = {
  MARKET: "Market-wide",
  SECTOR: "Event sector",
  ISSUER: "Event issuer",
};

export const ASSET_CLASS_LABEL: Record<string, string> = {
  EQUITY: "Equities",
  BOND: "Bonds",
  LOAN: "Loans",
  DERIVATIVE: "Derivatives",
};

/** "3h ago" relative to the replay clock (not wall-clock) so the demo reads the same every time. */
export function ago(iso: string, asOfIso: string): string {
  const diffMin = Math.max(0, Math.round((Date.parse(asOfIso) - Date.parse(iso)) / 60000));
  if (diffMin < 1) return "now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const h = diffMin / 60;
  if (h < 48) return `${h < 10 ? h.toFixed(1).replace(/\.0$/, "") : Math.round(h)}h ago`;
  return `${Math.round(h / 24)}d ago`;
}

export function dateTime(iso: string): string {
  return new Date(iso).toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
    hour12: false,
  }) + " UTC";
}

export function titleCase(s: string): string {
  return s
    .toLowerCase()
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}
