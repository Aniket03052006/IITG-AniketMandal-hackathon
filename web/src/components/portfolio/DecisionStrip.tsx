import clsx from "clsx";
import { useSignalRelevance } from "../../api/hooks";
import type { StressResult } from "../../api/types";
import { money, pct } from "../../lib/format";
import { KindBadge } from "../ProvenanceKind";

const BAND_WORD: Record<string, string> = { NONE: "None", LOW: "Low", MEDIUM: "Medium", HIGH: "High", UNDETERMINED: "Not determined" };

/**
 * Three different questions, three different answers, never blended into one score:
 *   how serious is the event (an assessment, uncalibrated),
 *   how much of MY portfolio does it reach (my holdings),
 *   what would the scenario do to it (a modeled change under illustrative shocks).
 */
export function DecisionStrip({ r, signalId, severity, portfolioName }: { r: StressResult; signalId: string; severity: number | null; portfolioName?: string }) {
  const { data: rel } = useSignalRelevance(signalId);
  const sum = r.summary;
  return (
    <section className="grid gap-px overflow-hidden rounded-md border border-rule bg-rule md:grid-cols-3" aria-label="Event severity, portfolio relevance and modeled impact">
      <div className="bg-paper p-4">
        <p className="eyebrow">Event severity</p>
        <p className="num mt-1 text-xl font-semibold">{severity != null ? `${severity}/10` : "–"}</p>
        <p className="mt-1 text-xs text-muted">How serious the event reads. A transparent triage score, not calibrated to outcomes.</p>
        <div className="mt-2"><KindBadge kind="model" label="Assessment" /></div>
      </div>
      <div className="bg-paper p-4">
        <p className="eyebrow">Portfolio relevance</p>
        <p className="mt-1 text-xl font-semibold">{rel ? BAND_WORD[rel.band] ?? rel.band : "…"}</p>
        <p className="mt-1 text-xs text-muted">
          {rel ? (rel.share != null ? `${pct(rel.share, 1)} of ${portfolioName ?? rel.portfolio_name ?? "the portfolio"} is reached by what the event is about.` : "Nothing identified, so it cannot be stated.") : ""}
        </p>
        <div className="mt-2"><KindBadge kind="historical" label="Your holdings" /></div>
      </div>
      <div className="bg-paper p-4">
        <p className="eyebrow">Modeled portfolio impact</p>
        <p className={clsx("num mt-1 text-xl font-semibold", sum && sum.pnl < 0 ? "text-neg" : sum && sum.pnl > 0 ? "text-pos" : "")}>
          {sum ? `${pct(sum.pnl_pct, 2, true)}` : "–"}
        </p>
        <p className="mt-1 text-xs text-muted">{sum ? `${money(sum.pnl, { signed: true })} under illustrative scenario shocks. Not a forecast of actual loss.` : ""}</p>
        <div className="mt-2"><KindBadge kind="scenario" label="Scenario assumption" /></div>
      </div>
    </section>
  );
}
