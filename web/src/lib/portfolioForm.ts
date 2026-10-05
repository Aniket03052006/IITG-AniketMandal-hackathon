/** The portfolio editor's form state and its conversion to the API payload. Pure, so it is unit-tested without a browser. */
import type { HoldingInput, PortfolioInput } from "../api/types";

export interface Row {
  ticker: string;
  weight: string;
  quantity: string;
  price: string;
  cost: string;
  name: string;
  assetClass: "" | "EQUITY" | "BOND" | "CASH" | "OTHER";
  sector: string;
  region: string;
  currency: string;
  beta: string;
  duration: string;
}

export interface Form {
  name: string;
  currency: string;
  mode: "WEIGHT" | "QUANTITY";
  totalValue: string;
  remainderAsCash: boolean;
  notes: string;
  rows: Row[];
}

export const CURRENCIES = ["USD", "INR", "EUR", "GBP", "JPY"] as const;

export const emptyRow = (): Row => ({ ticker: "", weight: "", quantity: "", price: "", cost: "", name: "", assetClass: "", sector: "", region: "", currency: "", beta: "", duration: "" });

export const emptyForm = (): Form => ({ name: "My portfolio", currency: "USD", mode: "WEIGHT", totalValue: "", remainderAsCash: false, notes: "", rows: [emptyRow()] });

/** "1,250.5" -> 1250.5; empty or unreadable -> null (the server then says what is missing). */
export function num(s: string): number | null {
  const t = s.replace(/[,\s]/g, "");
  if (t === "") return null;
  const v = Number(t);
  return Number.isFinite(v) ? v : null;
}

const str = (s: string): string | null => (s.trim() === "" ? null : s.trim());

export function toInput(f: Form): PortfolioInput {
  const holdings: HoldingInput[] = f.rows
    .filter((r) => r.ticker.trim() !== "" || r.weight !== "" || r.quantity !== "")
    .map((r) => ({
      ticker: r.ticker.trim() || "?",
      name: str(r.name),
      weight_pct: f.mode === "WEIGHT" ? num(r.weight) : null,
      quantity: f.mode === "QUANTITY" ? num(r.quantity) : null,
      price: f.mode === "QUANTITY" ? num(r.price) : null,
      cost_basis: num(r.cost),
      asset_class: r.assetClass === "" ? null : r.assetClass,
      sector: str(r.sector),
      region: str(r.region),
      currency: str(r.currency)?.toUpperCase() ?? null,
      beta: num(r.beta),
      duration: num(r.duration),
    }));
  return {
    name: f.name,
    base_currency: f.currency,
    mode: f.mode,
    total_value: f.mode === "WEIGHT" ? num(f.totalValue) : null,
    remainder_as_cash: f.mode === "WEIGHT" && f.remainderAsCash,
    notes: f.notes,
    holdings,
  };
}

const s = (v: number | null | undefined): string => (v == null ? "" : String(v));

export function fromInput(p: PortfolioInput): Form {
  return {
    name: p.name,
    currency: p.base_currency ?? "USD",
    mode: p.mode === "QUANTITY" ? "QUANTITY" : "WEIGHT",
    totalValue: s(p.total_value),
    remainderAsCash: !!p.remainder_as_cash,
    notes: p.notes ?? "",
    rows: p.holdings.length
      ? p.holdings.map((h) => ({
          ticker: h.ticker,
          weight: s(h.weight_pct),
          quantity: s(h.quantity),
          price: s(h.price),
          cost: s(h.cost_basis),
          name: h.name ?? "",
          assetClass: (h.asset_class ?? "") as Row["assetClass"],
          sector: h.sector ?? "",
          region: h.region ?? "",
          currency: h.currency ?? "",
          beta: s(h.beta),
          duration: s(h.duration),
        }))
      : [emptyRow()],
  };
}

/** True when there is anything to check (an empty form is not an error yet, just unfinished). */
export const hasContent = (f: Form): boolean => f.rows.some((r) => r.ticker.trim() !== "");

export const QUICK_EXAMPLE = "AAPL 20%\nJPM 15%\nMSFT 15%\nTLT 25%\nCash 25%";
export const QUICK_EXAMPLE_QTY = "AAPL 100 @ 190\nJPM 50 @ 210\nTLT 80 @ 92\nCash 20000";
