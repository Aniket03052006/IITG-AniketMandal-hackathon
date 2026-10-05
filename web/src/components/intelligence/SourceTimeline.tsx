import type { EventGroup, VelocityView } from "../../api/types";
import { hoursLabel, when } from "../../lib/intelligence";

const W = 640;
const H = 170;
const PAD = { l: 34, r: 12, t: 12, b: 28 };

/** Cumulative independent sources over time, as a step line. Words and numbers sit beside it: the chart is never the only carrier of the figures. */
export function SourceTimeline({ velocity }: { velocity: VelocityView }) {
  const pts = velocity.series;
  if (pts.length < 2) {
    return <p className="text-sm text-muted">{velocity.reason ?? "One report so far, so there is no spread to draw."}</p>;
  }
  const t0 = new Date(pts[0]!.at).getTime();
  const t1 = new Date(pts[pts.length - 1]!.at).getTime();
  const span = Math.max(1, t1 - t0);
  const max = Math.max(...pts.map((p) => p.independent_sources), 2);
  const x = (iso: string) => PAD.l + ((new Date(iso).getTime() - t0) / span) * (W - PAD.l - PAD.r);
  const y = (n: number) => PAD.t + (1 - n / max) * (H - PAD.t - PAD.b);
  let d = `M ${x(pts[0]!.at).toFixed(1)} ${y(pts[0]!.independent_sources).toFixed(1)}`;
  for (let i = 1; i < pts.length; i++) {
    d += ` H ${x(pts[i]!.at).toFixed(1)} V ${y(pts[i]!.independent_sources).toFixed(1)}`;
  }
  const summary = `${velocity.source_growth ?? "independent sources over time"}; ${pts.length} points`;
  return (
    <figure>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={summary} className="h-auto w-full max-w-[44rem] text-accent">
        <line x1={PAD.l} x2={W - PAD.r} y1={H - PAD.b} y2={H - PAD.b} stroke="currentColor" className="text-rule-strong" strokeWidth="1" />
        <line x1={PAD.l} x2={PAD.l} y1={PAD.t} y2={H - PAD.b} stroke="currentColor" className="text-rule-strong" strokeWidth="1" />
        <text x={PAD.l - 6} y={y(max) + 4} textAnchor="end" fontSize="11" fill="currentColor" className="text-muted">{max}</text>
        <text x={PAD.l - 6} y={y(0) + 4} textAnchor="end" fontSize="11" fill="currentColor" className="text-muted">0</text>
        <path d={d} fill="none" stroke="currentColor" strokeWidth="2" />
        {pts.map((p) => (
          <circle key={p.at} cx={x(p.at)} cy={y(p.independent_sources)} r="3.5" fill="currentColor" />
        ))}
        <text x={PAD.l} y={H - 8} fontSize="11" fill="currentColor" className="text-muted">{when(pts[0]!.at)}</text>
        <text x={W - PAD.r} y={H - 8} textAnchor="end" fontSize="11" fill="currentColor" className="text-muted">{when(pts[pts.length - 1]!.at)}</text>
      </svg>
      <figcaption className="mt-2 text-sm text-ink-2">
        {velocity.source_growth}
        {velocity.velocity_per_hour != null && <> · {velocity.velocity_per_hour.toFixed(2)} sources per hour</>}
        {velocity.acceleration != null && <> · pace {velocity.acceleration >= 0 ? "rising" : "falling"} by {Math.abs(velocity.acceleration).toFixed(2)} per hour between the two halves</>}
      </figcaption>
    </figure>
  );
}

/** Every report beneath the event, with whether it is an independent outlet or a copy of another's text. */
export function ReportsTable({ group }: { group: EventGroup }) {
  return (
    <div className="scroll-x">
      <table className="dtable min-w-[40rem]">
        <caption className="sr-only">Reports of this event in time order</caption>
        <thead>
          <tr>
            <th scope="col">Report</th>
            <th scope="col">Outlet</th>
            <th scope="col">Published</th>
            <th scope="col">Counts as</th>
          </tr>
        </thead>
        <tbody>
          {group.reports.map((r) => (
            <tr key={r.id} data-phase={r.phase}>
              <th scope="row" className="max-w-[26rem] !font-normal">
                {r.url ? (
                  <a href={r.url} target="_blank" rel="noreferrer" className="text-accent underline underline-offset-2">{r.headline}</a>
                ) : (
                  <span className="text-ink">{r.headline}</span>
                )}
                {r.phase === "AT_REPORT" && <span className="ml-2 tag">this report</span>}
              </th>
              <td className="text-sm">{r.source}<span className="block text-xs text-muted">{r.domain}</span></td>
              <td className="num whitespace-nowrap text-sm">{when(r.published_at)}</td>
              <td className="text-sm">{r.independent ? "independent source" : r.relation === "SYNDICATED" || r.relation === "NEAR_DUPLICATE" ? "copy of another report" : "same outlet again"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {group.report_count > group.reports.length && <p className="mt-2 text-xs text-muted">Showing {group.reports.length} of {group.report_count} reports.</p>}
      <p className="mt-2 text-xs text-muted">
        First seen {when(group.first_seen)} · last {when(group.last_seen)}
        {group.first_seen && group.last_seen && <> · covered over {hoursLabel((new Date(group.last_seen).getTime() - new Date(group.first_seen).getTime()) / 3.6e6)}</>}
      </p>
    </div>
  );
}
