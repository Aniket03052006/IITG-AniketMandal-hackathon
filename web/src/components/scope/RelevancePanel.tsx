import clsx from "clsx";
import { useSignalRelevance } from "../../api/hooks";
import type { ExposureSlice } from "../../api/types";
import { money, pct } from "../../lib/format";
import { RELEVANCE_LABEL } from "../../lib/scope";
import { KindBadge } from "../ProvenanceKind";
import { Skeleton } from "../ui";

const KIND_WORD: Record<string, string> = { ISSUER: "Issuer", SECTOR: "Sector", REGION: "Region", BOOK: "Whole book" };

function SliceRow({ sl }: { sl: ExposureSlice }) {
  return (
    <li className="grid grid-cols-[6.5rem_minmax(0,1fr)_4rem] items-center gap-3 text-sm sm:grid-cols-[7rem_minmax(0,1fr)_5rem_6rem]">
      <span className="text-muted">{KIND_WORD[sl.kind] ?? sl.kind}</span>
      <span className="min-w-0">
        <span className="block truncate text-ink">{sl.label}</span>
        <span className="mt-1 block h-1.5 rounded-sm bg-paper-4" aria-hidden="true">
          <span className={clsx("block h-full rounded-sm bg-accent bar-grow")} style={{ width: `${Math.max(2, sl.share * 100)}%` }} />
        </span>
      </span>
      <span className="num text-right">{pct(sl.share)}</span>
      <span className="num hidden text-right text-xs text-muted sm:block">{sl.asset_count} positions · {money(sl.market_value)}</span>
    </li>
  );
}

/** What the event means for the book. Exposure is the portfolio's own holdings; the scenario's shock sizes are separate and illustrative. */
export function RelevancePanel({ signalId }: { signalId: string }) {
  const { data: r, isLoading, error } = useSignalRelevance(signalId);
  if (isLoading) return <Skeleton className="mt-5 h-28 w-full" />;
  if (error || !r) return null;
  return (
    <div className="mt-6 border-t border-rule pt-5" aria-label="Portfolio relevance">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="eyebrow">What it means for this portfolio</p>
        <KindBadge kind="historical" />
      </div>
      <p className="mt-2 font-display text-lg font-semibold">{RELEVANCE_LABEL[r.level] ?? r.level}</p>
      <p className="mt-1 max-w-[66ch] text-ink-2">{r.summary}</p>
      {r.path.length > 0 && (
        <ol className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted" aria-label="Path from the event to the book">
          {r.path.map((p, i) => (
            <li key={p} className="flex items-center gap-2">
              {i > 0 && <span aria-hidden="true">→</span>}
              <span>{p}</span>
            </li>
          ))}
        </ol>
      )}
      {r.slices.length > 0 && (
        <ul className="mt-4 grid max-w-[52rem] gap-3">{r.slices.map((sl) => <SliceRow key={`${sl.kind}-${sl.key}`} sl={sl} />)}</ul>
      )}
      {r.reach && (
        <p className="mt-4 max-w-[66ch] text-sm text-muted">
          Scenario “{r.reach.scenario_name}”: {r.reach.shocks_bound} of {r.reach.shocks_total} of its shocks reach this kind of event — {r.reach.note}.
        </p>
      )}
    </div>
  );
}
