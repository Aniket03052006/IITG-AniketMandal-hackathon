import { pct } from "./format";

/**
 * Plain-language names, units and sections for every input the impact model can read (the ids are the model's own feature ids,
 * registered in `modeling/leakage.FEATURE_REGISTRY`). Nothing here invents an input: a feature that is not in the signal's audit is not shown.
 */
export type Fmt = "pct" | "pct0" | "ratio" | "num1" | "num2" | "flag" | "days" | "hours" | "int" | "dow" | "hour";

export interface FeatureInfo {
  label: string;
  fmt: Fmt;
}

export type InputSection = "report" | "text" | "calendar" | "market";

export const SECTION_TITLE: Record<InputSection, { title: string; note: string }> = {
  report: { title: "The report", note: "Who, when and how the story reached us. All known at the moment it appeared." },
  text: {
    title: "What the text models read",
    note: "Sentiment and event-type probabilities, as seen by the impact stage (it reads the TF-IDF event model, which it was fitted on).",
  },
  calendar: {
    title: "Calendar context",
    note: "Scheduled or already-published facts: earnings dates projected from the issuer's own earlier filings, 8-Ks accepted before the report, FOMC dates.",
  },
  market: { title: "Market state", note: "Prices and volatility up to the previous close. Nothing from the reaction session itself." },
};

const F: Record<string, FeatureInfo> = {
  f_sigma_60: { label: "Company's usual daily move (60-session volatility)", fmt: "pct" },
  f_beta_market: { label: "Sensitivity to the market (beta)", fmt: "num2" },
  f_beta_sector: { label: "Sensitivity to its sector", fmt: "num2" },
  f_ret_1d: { label: "Company return, last session", fmt: "pct" },
  f_ret_5d: { label: "Company return, last 5 sessions", fmt: "pct" },
  f_ret_20d: { label: "Company return, last 20 sessions", fmt: "pct" },
  f_mkt_ret_5d: { label: "S&P 500 return, last 5 sessions", fmt: "pct" },
  f_sector_ret_5d: { label: "Sector return, last 5 sessions", fmt: "pct" },
  f_volume_ratio: { label: "Trading volume vs its 20-session norm", fmt: "ratio" },
  f_resid_vol_5d_ratio: { label: "Recent vs usual volatility (5 sessions)", fmt: "ratio" },
  f_resid_vol_20d_ratio: { label: "Recent vs usual volatility (20 sessions)", fmt: "ratio" },
  f_vix_level: { label: "VIX the session before", fmt: "num1" },
  f_vix_chg_5d: { label: "VIX change over 5 sessions", fmt: "pct" },
  m_sigma_60: { label: "S&P 500's usual daily move (60-session volatility)", fmt: "pct" },
  m_ret_1d: { label: "S&P 500 return, last session", fmt: "pct" },
  m_ret_5d: { label: "S&P 500 return, last 5 sessions", fmt: "pct" },
  m_ret_20d: { label: "S&P 500 return, last 20 sessions", fmt: "pct" },
  m_dev_vol_5d_ratio: { label: "Recent vs usual market volatility (5 sessions)", fmt: "ratio" },
  m_dev_vol_20d_ratio: { label: "Recent vs usual market volatility (20 sessions)", fmt: "ratio" },
  m_vix_level: { label: "VIX the session before", fmt: "num1" },
  m_vix_chg_5d: { label: "VIX change over 5 sessions", fmt: "pct" },
  m_vix_rel_60: { label: "VIX relative to its 60-session level", fmt: "ratio" },
  m_rate_level: { label: "10-year yield level (%)", fmt: "num2" },
  m_rate_chg_5d: { label: "10-year yield change over 5 sessions", fmt: "num2" },
  link_confidence: { label: "Confidence the story is about this company", fmt: "pct0" },
  novelty: { label: "Novelty of the report (1 = nothing similar in 72 h)", fmt: "num2" },
  dow: { label: "Day of the week of the report", fmt: "dow" },
  local_hour: { label: "Hour of the report (US Eastern)", fmt: "hour" },
  is_news: { label: "Source is a news outlet (not a social post)", fmt: "flag" },
  t_pre_open: { label: "Published before the market open", fmt: "flag" },
  t_in_session: { label: "Published during the trading session", fmt: "flag" },
  t_date_only: { label: "Source gave a date but no time", fmt: "flag" },
  t_first_seen: { label: "Time is a crawl (first-seen) time", fmt: "flag" },
  earn_days_to_expected: { label: "Days to the expected earnings release (negative: just passed)", fmt: "num1" },
  earn_window: { label: "Inside the earnings window (within 1.5 days)", fmt: "flag" },
  earn_days_since_last: { label: "Days since the last earnings filing", fmt: "days" },
  f8k_hours_since_last: { label: "Hours since the issuer's last 8-K", fmt: "hours" },
  f8k_count_24h: { label: "8-K filings in the previous 24 hours", fmt: "int" },
  f8k_earnings_24h: { label: "Earnings 8-K in the previous 24 hours", fmt: "flag" },
  f8k_deal_24h: { label: "Deal 8-K in the previous 24 hours", fmt: "flag" },
  f8k_distress_24h: { label: "Distress 8-K in the previous 24 hours", fmt: "flag" },
  f8k_financing_24h: { label: "Financing 8-K in the previous 24 hours", fmt: "flag" },
  f8k_leadership_24h: { label: "Leadership 8-K in the previous 24 hours", fmt: "flag" },
  fomc_s0: { label: "Scheduled FOMC decision on the reaction session", fmt: "flag" },
  fomc_s1: { label: "Scheduled FOMC decision on the session after", fmt: "flag" },
  ev_p_none: { label: "Chance the text is not a market event", fmt: "pct0" },
  sent_pos: { label: "Sentiment: positive probability", fmt: "pct0" },
  sent_neg: { label: "Sentiment: negative probability", fmt: "pct0" },
  sent_abs: { label: "Sentiment strength (|positive − negative|)", fmt: "num2" },
};

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export function featureInfo(name: string, categoryLabel?: (id: string) => string): FeatureInfo {
  const hit = F[name];
  if (hit) return hit;
  if (name.startsWith("ev_p_")) {
    const id = name.slice(5).toUpperCase();
    return { label: `Event-type probability: ${categoryLabel ? categoryLabel(id) : id.toLowerCase().replace(/_/g, " ")}`, fmt: "pct0" };
  }
  if (name.startsWith("item_")) return { label: `Filing item ${name.slice(5).replace("_", ".")}`, fmt: "flag" };
  return { label: name.replace(/_/g, " "), fmt: "num2" };
}

export function featureSection(name: string): InputSection {
  if (name.startsWith("ev_p_") || name.startsWith("sent_")) return "text";
  if (name.startsWith("earn_") || name.startsWith("f8k_") || name.startsWith("fomc_") || name.startsWith("item_")) return "calendar";
  if (name.startsWith("f_") || name.startsWith("m_")) return "market";
  return "report";
}

export function formatFeature(fmt: Fmt, v: number): string {
  switch (fmt) {
    case "pct":
      return pct(v, 2);
    case "pct0":
      return pct(v, 0);
    case "ratio":
      return `${v.toFixed(2)}×`;
    case "num1":
      return v.toFixed(1);
    case "num2":
      return v.toFixed(2);
    case "flag":
      return v >= 0.5 ? "yes" : "no";
    case "days":
      return `${v.toFixed(1)} days`;
    case "hours":
      return v >= 48 ? `${(v / 24).toFixed(1)} days` : `${v.toFixed(1)} h`;
    case "int":
      return String(Math.round(v));
    case "dow":
      return DAYS[Math.round(v)] ?? String(v);
    case "hour":
      return `${String(Math.round(v)).padStart(2, "0")}:00`;
  }
}

/** The availability classes the audit shows. Class c (known only afterwards) is never an input, so it has no entry. */
export const AVAILABILITY: Record<string, { label: string; says: string }> = {
  a: { label: "Known in advance", says: "Scheduled or derivable from filings accepted before the report." },
  b: { label: "Published before the report", says: "A filing the SEC accepted strictly before the report's own timestamp." },
  t: { label: "Event time", says: "From the report's own text and timestamp, or from prices up to the previous close." },
};
