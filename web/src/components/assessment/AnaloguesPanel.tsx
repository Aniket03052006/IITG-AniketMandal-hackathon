import { useSignalAnalogues } from "../../api/hooks";
import type { Analogue, AnalogueSet } from "../../api/types";
import { pct } from "../../lib/format";
import { StateNotice } from "../StateNotice";
import { Skeleton } from "../ui";
import { AssessmentKind } from "./AssessmentKind";
import { OriginChip } from "./OriginChip";

const sessionDate = (iso: string) => new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" });

/** What the market did after one past report, as a signed percent with the volatility-adjusted size beside it (words and signs, never colour alone). */
const move = (a: Analogue) => `${pct(a.car_pct / 100, 2, true)} (${a.z >= 0 ? "+" : "−"}${Math.abs(a.z).toFixed(1)}σ)`;

function AnalogueTable({ items, caption }: { items: Analogue[]; caption: string }) {
  return (
    <div className="scroll-x">
      <table className="dtable min-w-[44rem]">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            <th scope="col">Past report</th>
            <th scope="col">Reacted</th>
            <th scope="col" className="text-right">Similarity</th>
            <th scope="col" className="text-right">Move after it</th>
            <th scope="col" className="text-right">VIX then</th>
          </tr>
        </thead>
        <tbody>
          {items.map((a) => (
            <tr key={a.id}>
              <th scope="row" className="max-w-[28rem] !font-normal">
                <span className="block text-ink">{a.headline}</span>
                <span className="text-xs text-muted">
                  {a.ticker ?? "market-wide"}
                  {a.sector ? ` · ${a.sector}` : ""}
                  {a.model_event_type ? ` · read by the event model as ${a.model_event_type.toLowerCase().replaceAll("_", " ")}` : ""}
                </span>
              </th>
              <td className="num whitespace-nowrap text-sm">{sessionDate(a.reaction_session)}</td>
              <td className="num text-right text-sm">{a.similarity.toFixed(2)}</td>
              <td className="num whitespace-nowrap text-right text-sm">{move(a)}</td>
              <td className="num text-right text-sm">{a.vix_level != null ? a.vix_level.toFixed(1) : "n/a"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function AnaloguesView({ set }: { set: AnalogueSet }) {
  if (set.status === "UNAVAILABLE") {
    return <StateNotice tone="info" what="Analogue search is not available for this report" why={set.reason} />;
  }
  if (set.status === "NO_RELIABLE_ANALOGUE") {
    return (
      <div className="space-y-4">
        <StateNotice
          tone="info"
          what="No reliable historical analogue found"
          why={set.reason}
          details="EventShock does not pad the list with weaker matches, and it does not invent a precedent. Read this report on its own evidence above."
        />
        {set.below_bar.length > 0 && (
          <details className="disclosure">
            <summary>The nearest past reports, below the reliability bar (not precedent)</summary>
            <p className="mb-3 mt-3 max-w-[70ch] text-sm text-muted">
              Listed for transparency only. They are too few, too alike one another, or not similar enough to say anything about what the market might do.
            </p>
            <AnalogueTable items={set.below_bar} caption="Nearest past reports below the reliability bar" />
          </details>
        )}
        <p className="text-xs text-muted">
          Searched {set.eligible.toLocaleString("en-GB")} past reports that were old enough to use ({set.above_floor} above the similarity floor of {set.similarity_floor?.toFixed(2)}).
        </p>
      </div>
    );
  }
  const g = set.aggregate;
  return (
    <div className="space-y-5">
      {g && (
        <div className="card p-5" aria-label="What the analogues say as a group">
          <p className="font-display text-lg font-semibold">{g.reading}</p>
          <dl className="mt-3 grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <dt className="text-xs text-muted">Statistics are based on</dt>
              <dd className="num">{g.n_used} <span className="text-xs text-muted">most similar of {g.n_stories} distinct past stories</span></dd>
            </div>
            <div>
              <dt className="text-xs text-muted">Typical move after them (median, 10th to 90th)</dt>
              <dd className="num">
                {pct(g.car_pct_q50 / 100, 2, true)} <span className="text-xs text-muted">({pct(g.car_pct_q10 / 100, 1, true)} to {pct(g.car_pct_q90 / 100, 1, true)})</span>
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted">Moves of 2σ or more</dt>
              <dd className="num">
                {pct(g.share_move_ge_2sigma, 0)} <span className="text-xs text-muted">({pct(g.share_lo, 0)} to {pct(g.share_hi, 0)})</span>
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted">The same on an ordinary day</dt>
              <dd className="num">
                {pct(g.quiet_day_share, 1)} {g.lift != null && <span className="text-xs text-muted">(lift {g.lift.toFixed(1)}×)</span>}
              </dd>
            </div>
          </dl>
        </div>
      )}
      <AnalogueTable items={set.items} caption="Past reports that resemble this one and the market's move after each" />
      <ul className="max-w-[78ch] list-disc space-y-1 pl-5 text-xs text-muted">
        {set.caveats.map((c) => (
          <li key={c}>{c}</li>
        ))}
        <li>{set.outcome_note}</li>
      </ul>
    </div>
  );
}

/** Chapter 4 panel: precedent retrieved from history, kept apart (and labelled) from this report's own evidence and never fed back into the score. */
export function AnaloguesPanel({ signalId, enabled }: { signalId: string; enabled: boolean }) {
  const { data, isLoading, error } = useSignalAnalogues(signalId, enabled);
  if (!enabled) return null;
  return (
    <section className="mt-10" aria-label="Historical analogues">
      <div className="flex flex-wrap items-center gap-3">
        <h3 className="text-lg font-semibold">Historical analogues</h3>
        <AssessmentKind kind="RETRIEVED" />
        <OriginChip origin="RETRIEVED" />
      </div>
      <p className="mb-5 mt-1 max-w-[70ch] text-sm text-muted">
        Past reports that look like this one and what the market did after them. This is precedent about other events: it is shown for context and never changes the severity score.
      </p>
      {isLoading ? (
        <Skeleton className="h-40 w-full" />
      ) : error || !data ? (
        <StateNotice tone="warn" what="Analogues could not be loaded" why={error instanceof Error ? error.message : "The request failed."} />
      ) : (
        <AnaloguesView set={data} />
      )}
    </section>
  );
}
