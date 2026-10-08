import { usePortfolioExposureDetail } from "../../api/hooks";
import type { ExposureRowV2, PortfolioMetric } from "../../api/types";
import { ASSET_CLASS_LABEL, money, pct } from "../../lib/format";
import { currencySymbol } from "../../lib/portfolio";
import { KindBadge } from "../ProvenanceKind";
import { Heatmap } from "./Heatmap";
import { ErrorState, Skeleton, Stat } from "../ui";

function Bars({ rows, label, max = 6 }: { rows: ExposureRowV2[]; label?: (r: ExposureRowV2) => string; max?: number }) {
  const top = rows.slice(0, max);
  const peak = Math.max(...top.map((r) => r.share), 0.0001);
  return (
    <ul className="space-y-2">
      {top.map((r) => (
        <li key={r.key} className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)_4.5rem] items-center gap-3 text-sm">
          <span className="truncate text-ink-2">{label ? label(r) : r.label}</span>
          <span className="h-2 rounded-sm bg-paper-4" aria-hidden="true">
            <span className="block h-full rounded-sm bg-faint" style={{ width: `${(r.share / peak) * 100}%` }} />
          </span>
          <span className="num text-right text-muted">{pct(r.share, 1)}</span>
        </li>
      ))}
      {rows.length > max && <li className="text-xs text-muted">+ {rows.length - max} more</li>}
    </ul>
  );
}

const fmtMetric = (m: PortfolioMetric, ccy: string): string => {
  if (m.value == null) return "–";
  switch (m.unit) {
    case "fraction":
      return pct(m.value, 1);
    case "years":
      return `${m.value.toFixed(1)} y`;
    case "currency":
      return money(m.value, { currency: ccy });
    case "count":
      return m.value.toFixed(1);
    default:
      return m.value.toFixed(2);
  }
};

/** What a portfolio is exposed to, from its holdings alone: no event, no scenario. Every metric says how it is computed. */
export function ExposurePanel({ id }: { id: string | null }) {
  const { data: d, isLoading, error, refetch } = usePortfolioExposureDetail(id);
  if (isLoading) return <Skeleton className="h-64 w-full" />;
  if (error || !d) return <ErrorState error={error ?? new Error("The exposure could not be loaded.")} retry={() => refetch()} />;
  const ccy = currencySymbol(d.base_currency);
  return (
    <section aria-label={`Exposure of ${d.name}`}>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-lg font-semibold">What this portfolio is exposed to</h3>
        <KindBadge kind="historical" label={d.kind === "USER" ? "Your holdings" : "Synthetic holdings"} />
      </div>
      <div className="grid grid-cols-3 gap-4">
        <Stat label="Total value" value={money(d.total_value, { currency: ccy })} sub={d.base_currency} />
        <Stat label="Positions" value={d.position_count} />
        <Stat label="Effective positions" value={d.metrics.find((m) => m.key === "effective_n")?.value?.toFixed(1) ?? "–"} sub="1 / concentration" />
      </div>
      <div className="mt-5 grid gap-6 md:grid-cols-2">
        <div>
          <h4 className="mb-2 text-sm font-semibold">By asset class</h4>
          <Bars rows={d.by_asset_class} label={(r) => ASSET_CLASS_LABEL[r.key] ?? r.label} />
        </div>
        <div>
          <h4 className="mb-2 text-sm font-semibold">By sector</h4>
          <Bars rows={d.by_sector} />
        </div>
        <div>
          <h4 className="mb-2 text-sm font-semibold">By region</h4>
          <Bars rows={d.by_region} />
        </div>
        <div>
          <h4 className="mb-2 text-sm font-semibold">Largest issuers</h4>
          <Bars rows={d.by_issuer} max={5} />
        </div>
      </div>
      {d.matrix && (
        <div className="mt-6">
          <Heatmap tab={d.matrix} title="Where the value sits: sector by asset class" unitLabel="share of the whole book; hover a cell for the amount and positions" />
        </div>
      )}
      <div className="mt-6">
        <h4 className="mb-2 text-sm font-semibold">Concentration and sensitivity</h4>
        <dl className="grid gap-x-8 gap-y-3 sm:grid-cols-2">
          {d.metrics
            .filter((m) => m.key !== "total_value")
            .map((m) => (
              <div key={m.key} className="min-w-0">
                <dt className="flex items-baseline justify-between gap-3 text-sm">
                  <span className="text-ink-2">{m.label}</span>
                  <span className="num font-medium text-ink">{fmtMetric(m, ccy)}</span>
                </dt>
                <dd className="mt-0.5 text-xs text-muted">{m.formula}</dd>
              </div>
            ))}
        </dl>
      </div>
      {d.notes.length > 0 && (
        <ul className="mt-4 space-y-1 text-xs text-muted">
          {d.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}
    </section>
  );
}
