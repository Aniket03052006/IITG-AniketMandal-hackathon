import type { ScoreDriver } from "../../api/types";
import { ageText } from "../../lib/rebalancer";
import { SentimentBar } from "../ui";

const when = (iso: string) => `${new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "UTC" })} UTC`;

/** One report behind a score: the headline (linked when the source gave a URL), its outlet and publication time, its decay, its tone and its signed share of the score. */
export function DriverRow({ d, showTime = false }: { d: ScoreDriver; showTime?: boolean }) {
  const age = d.age_hours < 1 ? "under an hour ago" : d.age_hours < 48 ? `${Math.round(d.age_hours)} h ago` : `${Math.round(d.age_hours / 24)} days ago`;
  return (
    <li className="grid gap-x-4 gap-y-1 py-2.5 sm:grid-cols-[minmax(0,1fr)_auto]">
      <div className="min-w-0">
        {d.url ? <a href={d.url} target="_blank" rel="noopener noreferrer" className="break-words font-medium text-accent underline-offset-2 hover:underline">{d.headline || "(no headline)"}</a>
          : <span className="break-words font-medium">{d.headline || "(no headline)"}</span>}
        <div className="mt-0.5 text-xs text-muted">
          {d.source} · {showTime ? <><time dateTime={d.published_at}>{when(d.published_at)}</time> ({ageText(d.age_hours)} old)</> : age} · weight <span className="num">{d.decayed_weight.toFixed(2)}</span> after decay
          {d.multiplier !== 1 && <> · tone x <span className="num">{d.multiplier.toFixed(2)}</span> for its impact score</>}
        </div>
      </div>
      <div className="flex items-center gap-3 sm:justify-end">
        <SentimentBar score={d.sentiment} />
        <span className="num w-16 text-right text-sm" title="this report's share of the score">{d.contribution >= 0 ? "+" : "−"}{Math.abs(d.contribution).toFixed(3)}</span>
      </div>
    </li>
  );
}
