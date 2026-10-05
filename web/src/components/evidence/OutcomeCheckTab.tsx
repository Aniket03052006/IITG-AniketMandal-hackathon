import { useOutcomeCheck } from "../../api/hooks";
import type { OutcomeCheck, OutcomeSplit } from "../../api/types";
import { pct, signed } from "../../lib/format";
import { StateNotice } from "../StateNotice";
import { ErrorState, Loading } from "../ui";

const NAME: Record<string, string> = {
  M1_overall_rank: "Rank correlation with the realised move",
  M2_within_regime_rank: "…within each volatility regime",
  M3_real_minus_placebo: "…minus the same on the window before the report",
  M4_increment_over_regime: "…beyond what the volatility regime already explains",
  placebo_rank: "Placebo window (before the report)",
};
const interval = (e: number | null, lo: number | null, hi: number | null) =>
  e == null ? "n/a" : `${signed(e, 3)}${lo != null && hi != null ? `  [${signed(lo, 3)}, ${signed(hi, 3)}]` : ""}`;
const rate = (x: number | null) => (x == null ? "n/a" : pct(x, 1));

function Metrics({ splits, caption }: { splits: OutcomeSplit[]; caption: string }) {
  if (!splits.length) return null;
  const names = splits[0]!.metrics.map((m) => m.name);
  return (
    <div className="scroll-x">
      <table className="dtable min-w-[42rem]">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            <th scope="col">Measure (95% interval)</th>
            {splits.map((s) => (
              <th key={s.split} scope="col" className="text-right">{s.split === "dev" ? "2018-2024" : s.split === "test" ? "2025 test" : "2026 live"} (n {s.n.toLocaleString("en-GB")})</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {names.map((n) => (
            <tr key={n}>
              <th scope="row" className="!font-normal">{NAME[n] ?? n}</th>
              {splits.map((s) => {
                const m = s.metrics.find((x) => x.name === n);
                return <td key={s.split} className="num whitespace-nowrap text-right text-sm">{m ? interval(m.estimate, m.lo, m.hi) : "n/a"}</td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Bands({ s }: { s: OutcomeSplit }) {
  return (
    <div className="scroll-x">
      <table className="dtable min-w-[32rem]">
        <caption className="sr-only">Share of moves of 2σ or more, by severity band, {s.split}</caption>
        <thead>
          <tr>
            <th scope="col">Severity band</th>
            <th scope="col" className="text-right">Reports</th>
            <th scope="col" className="text-right">Moved 2σ or more</th>
          </tr>
        </thead>
        <tbody>
          {s.bands.map((b) => (
            <tr key={b.band}>
              <th scope="row" className="!font-normal capitalize">{b.band === "abstained" ? "no market event read" : b.band}</th>
              <td className="num text-right text-sm">{b.n.toLocaleString("en-GB")}</td>
              <td className="num text-right text-sm">{rate(b.tail_rate)} <span className="text-xs text-muted">({rate(b.lo)} to {rate(b.hi)})</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function OutcomeCheckView({ o }: { o: OutcomeCheck }) {
  const test = o.splits.find((s) => s.split === "test");
  const a = o.audit;
  const r = o.retrieval;
  return (
    <div className="space-y-10">
      <section aria-label="Verdict">
        <div className="card p-5">
          <p className="eyebrow">Severity scale against realised market moves</p>
          <p className="mt-1 font-display text-xl font-semibold">{o.label === "HEURISTIC_UNCALIBRATED" ? "Heuristic: not calibrated to outcomes" : o.label === "OUTCOME_VALIDATED" ? "Outcome-validated" : o.label === "DIRECTIONALLY_INFORMATIVE" ? "Directionally informative" : "Not available"}</p>
          {o.label_reading && <p className="mt-2 max-w-[72ch] text-ink-2">{o.label_reading}</p>}
          <p className="mt-2 max-w-[72ch] text-xs text-muted">{o.note}</p>
        </div>
      </section>

      {o.splits.length > 0 && (
        <section aria-label="Severity against outcomes">
          <h3 className="text-lg font-semibold">Does the text-only severity score rank what the market did next?</h3>
          <p className="mb-4 mt-1 max-w-[72ch] text-sm text-muted">
            The score read the headline of each of {a?.news_episodes.toLocaleString("en-GB") ?? "~19,600"} past news episodes about large companies (no market data, no language model), and was compared with the realised move afterwards.
            A positive interval that excludes zero means it helped; the 2025 and 2026 columns were read once.
          </p>
          <Metrics splits={o.splits} caption="Rank correlation of severity with realised moves, by period" />
          {test && (
            <details className="disclosure mt-5">
              <summary>How often did the market move 2σ or more, by severity band (2025)?</summary>
              <p className="mb-3 mt-3 max-w-[70ch] text-sm text-muted">If the scale tracked outcomes, the rate would climb from the top row to the bottom. It does not climb steadily, and most headlines were read as not describing a market event.</p>
              <Bands s={test} />
            </details>
          )}
          {o.market_scope.length > 0 && (
            <details className="disclosure mt-3">
              <summary>Post-hoc: market-wide reports against the S&amp;P 500's move</summary>
              <p className="mb-3 mt-3 max-w-[70ch] text-sm text-muted">{o.market_scope_note} The sign changes between periods, which is what an uncalibrated scale looks like.</p>
              <Metrics splits={o.market_scope} caption="Rank correlation of severity with the S&P 500 move for market-wide reports" />
            </details>
          )}
        </section>
      )}

      {a && (
        <section aria-label="What the market does around ordinary news">
          <h3 className="text-lg font-semibold">What the market does around ordinary company news</h3>
          <p className="mb-4 mt-1 max-w-[72ch] text-sm text-muted">Compared with {a.quiet_days_sampled.toLocaleString("en-GB")} random ordinary days for the same companies and years.</p>
          <dl className="grid gap-x-8 gap-y-3 sm:grid-cols-2 lg:grid-cols-4">
            <div><dt className="text-xs text-muted">News episode vs ordinary day (0.5 = no difference)</dt><dd className="num text-lg">{a.auc?.toFixed(3)} <span className="text-xs text-muted">[{a.auc_lo?.toFixed(3)}, {a.auc_hi?.toFixed(3)}]</span></dd></div>
            <div><dt className="text-xs text-muted">Moved 2σ or more: news vs ordinary day</dt><dd className="num text-lg">{rate(a.share_move_news)} vs {rate(a.share_move_quiet)}</dd></div>
            <div><dt className="text-xs text-muted">Same, excluding earnings windows</dt><dd className="num text-lg">{a.auc_without_earnings?.toFixed(3)} <span className="text-xs text-muted">[{a.auc_without_earnings_lo?.toFixed(3)}, {a.auc_without_earnings_hi?.toFixed(3)}]</span></dd></div>
            <div><dt className="text-xs text-muted">With an earnings release in the window</dt><dd className="num text-lg">{a.auc_with_earnings?.toFixed(3)}</dd></div>
          </dl>
          <p className="mt-4 max-w-[72ch] text-sm text-ink-2">
            Ordinary headlines about these companies are barely distinguishable from an ordinary day; earnings are the exception. That is why a realised move cannot serve as the label for how serious a headline is, and why every interval here is clustered by reaction date (effective sample {a.effective_sample ? Math.round(a.effective_sample).toLocaleString("en-GB") : "n/a"} of {a.nominal_sample?.toLocaleString("en-GB")}).
          </p>
          <p className="mt-2 max-w-[72ch] text-xs text-muted">{a.sigma_reading}</p>
        </section>
      )}

      {r && (
        <section aria-label="Historical analogues, evaluated">
          <h3 className="text-lg font-semibold">Historical analogues: did retrieval earn a place in the score?</h3>
          <p className="mb-4 mt-1 max-w-[72ch] text-sm text-muted">{r.decision}.</p>
          {r.relevance.length > 0 && (
            <div className="scroll-x mb-5">
              <table className="dtable min-w-[40rem]">
                <caption className="sr-only">Retrieval relevance on unseen wording</caption>
                <thead><tr><th scope="col">Queries (unseen wording)</th><th scope="col" className="text-right">By chance</th><th scope="col" className="text-right">TF-IDF</th><th scope="col" className="text-right">Sentence embeddings</th><th scope="col" className="text-right">Difference</th></tr></thead>
                <tbody>
                  {r.relevance.map((x) => (
                    <tr key={x.queries}>
                      <th scope="row" className="!font-normal">{x.queries}</th>
                      <td className="num text-right text-sm">{rate(x.base_rate)}</td>
                      <td className="num text-right text-sm">{rate(x.p_at_5_tfidf)}</td>
                      <td className="num text-right text-sm">{rate(x.p_at_5_e5)}</td>
                      <td className="num whitespace-nowrap text-right text-sm">{signed(x.delta, 3)} <span className="text-xs text-muted">[{signed(x.delta_lo, 3)}, {signed(x.delta_hi, 3)}]</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="mb-3 max-w-[72ch] text-sm text-ink-2">Embeddings find the right kind of event better than keywords do. But adding what happened after similar reports to a model that already knows the market regime and the earnings calendar did not improve its error:</p>
          <div className="scroll-x">
            <table className="dtable min-w-[36rem]">
              <caption className="sr-only">Change in prediction error from adding analogue information</caption>
              <thead><tr><th scope="col">Added information</th><th scope="col">Period</th><th scope="col" className="text-right">Change in error (negative = better)</th></tr></thead>
              <tbody>
                {r.value.map((v) => (
                  <tr key={`${v.candidate}-${v.split}`}>
                    <th scope="row" className="!font-normal">{v.candidate === "C_knn" ? "Outcomes of the nearest past reports" : "Average outcome of the event type in that regime"}</th>
                    <td className="text-sm">{v.split === "test" ? "2025" : "2026"}</td>
                    <td className="num text-right text-sm">{interval(v.delta_mae, v.lo, v.hi)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {o.missing.length > 0 && <StateNotice tone="info" what="Some evidence files are not in this checkout" why={o.missing.join("; ")} />}
    </div>
  );
}

export function OutcomeCheckTab() {
  const { data, error, isLoading, refetch } = useOutcomeCheck(true);
  if (error) return <ErrorState error={error} retry={() => refetch()} />;
  if (isLoading || !data) return <Loading label="Loading the outcome check" />;
  return <OutcomeCheckView o={data} />;
}
