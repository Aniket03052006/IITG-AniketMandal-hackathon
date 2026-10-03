import clsx from "clsx";
import { useMemo, useState } from "react";
import type { Contribution, PositionResult, StressResult } from "../../api/types";
import { ASSET_CLASS_LABEL, FACTOR_LABEL, money, pct } from "../../lib/format";
import { Chevron } from "../icons";
import { KindBadge } from "../ProvenanceKind";

type Dim = "asset" | "sector" | "factor";
interface Path {
  dim: Dim;
  key?: string;
  entity?: string;
}

const DIM_LABEL: Record<Dim, string> = { asset: "Asset class", sector: "Sector", factor: "Risk factor" };

interface Row {
  key: string;
  label: string;
  delta: number;
  baseline: number;
  share: number | null;
}

function Bars({ rows, onPick, picked }: { rows: Row[]; onPick?: (k: string) => void; picked?: string }) {
  const max = Math.max(1, ...rows.map((r) => Math.abs(r.delta)));
  return (
    <ul className="space-y-1" aria-label="Largest contributions first">
      {rows.map((r) => {
        const neg = r.delta < 0;
        const inner = (
          <>
            <span className="min-w-0 truncate text-left text-ink-2" title={r.label}>
              {r.label}
            </span>
            <span className="h-2.5 rounded-sm bg-paper-4" aria-hidden="true">
              <span className={clsx("block h-full rounded-sm bar-grow", neg ? "bg-neg" : r.delta > 0 ? "bg-pos" : "bg-faint")} style={{ width: `${(Math.abs(r.delta) / max) * 100}%`, minWidth: r.delta === 0 ? 0 : 3 }} />
            </span>
            <span className={clsx("num text-right", neg ? "text-neg" : r.delta > 0 ? "text-pos" : "text-muted")}>{money(r.delta, { signed: true })}</span>
            <span className="num text-right text-xs text-muted">{r.share == null ? "" : pct(r.share, 0)}</span>
            {onPick && <Chevron size={13} className="text-muted" />}
          </>
        );
        const cls = "grid grid-cols-[minmax(0,1fr)_minmax(4rem,9rem)_4.75rem_2.5rem_1rem] items-center gap-3 rounded-md px-2 py-1.5 text-sm";
        return (
          <li key={r.key}>
            {onPick ? (
              <button type="button" className={clsx(cls, "w-full hover:bg-paper-3", picked === r.key && "bg-paper-3")} onClick={() => onPick(r.key)} aria-label={`${r.label}, ${money(r.delta, { signed: true })}. Drill into issuers`}>
                {inner}
              </button>
            ) : (
              <div className={cls}>{inner}</div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function fromContribution(c: Contribution[], dim: Dim): Row[] {
  return c
    .map((x) => ({
      key: x.key,
      label: dim === "asset" ? (ASSET_CLASS_LABEL[x.key] ?? x.label) : dim === "factor" ? (FACTOR_LABEL[x.key] ?? x.label) : x.label,
      delta: x.delta,
      baseline: x.baseline_value,
      share: x.share_of_loss,
    }))
    .sort((a, b) => a.delta - b.delta);
}

/** PORTFOLIO -> (asset class | sector | risk factor) -> ISSUER -> POSITION. Every level is computed from the same run, largest loss first. */
export function ContributionDrill({ r, entityNames }: { r: StressResult; entityNames: Map<string, string> }) {
  const [path, setPath] = useState<Path>({ dim: "asset" });
  const c = r.contributions;
  const total = r.summary?.pnl ?? 0;

  const inSelection = useMemo(() => {
    return (p: PositionResult): number | null => {
      if (path.key == null) return null;
      if (path.dim === "asset") return p.asset_class === path.key ? p.delta : null;
      if (path.dim === "sector") return p.sector === path.key ? p.delta : null;
      return p.by_factor[path.key] ?? null;
    };
  }, [path.dim, path.key]);

  const issuerRows: Row[] = useMemo(() => {
    if (path.key == null) return [];
    const m = new Map<string, Row>();
    for (const p of r.positions) {
      const d = inSelection(p);
      if (d == null) continue;
      const cur = m.get(p.entity_id) ?? { key: p.entity_id, label: entityNames.get(p.entity_id) ?? p.entity_id, delta: 0, baseline: 0, share: null };
      cur.delta += d;
      cur.baseline += p.baseline_value;
      m.set(p.entity_id, cur);
    }
    const rows = [...m.values()].filter((x) => Math.abs(x.delta) > 0.5);
    const sum = rows.reduce((a, x) => a + x.delta, 0);
    return rows.map((x) => ({ ...x, share: sum !== 0 ? x.delta / sum : null })).sort((a, b) => a.delta - b.delta);
  }, [path.key, r.positions, entityNames, inSelection]);

  const positions = useMemo(
    () => (path.entity ? r.positions.filter((p) => p.entity_id === path.entity && inSelection(p) != null).sort((a, b) => a.delta - b.delta) : []),
    [r.positions, path.entity, inSelection],
  );

  if (!c) return null;
  const sets: Record<Dim, Contribution[]> = { asset: c.by_asset_class, sector: c.by_sector, factor: c.by_factor };
  const keyLabel =
    path.key == null ? "" : path.dim === "asset" ? (ASSET_CLASS_LABEL[path.key] ?? path.key) : path.dim === "factor" ? (FACTOR_LABEL[path.key] ?? path.key) : path.key;
  const level = path.entity ? 2 : path.key != null ? 1 : 0;

  return (
    <section className="drill" aria-label="Where the change comes from">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-lg font-semibold">Where the change comes from</h3>
        <KindBadge kind="scenario" label="Sensitivity, not cause" />
      </div>
      <p className="mb-4 max-w-[68ch] text-sm text-muted">
        How much each part of the book moves under this scenario's shocks. It shows exposure to the assumptions, not what caused the event. Click a bar to go one level down.
      </p>

      <nav aria-label="Drill-down path" className="mb-3 flex flex-wrap items-center gap-1 text-sm">
        <button type="button" className={clsx("crumb", level === 0 && "crumb-here")} onClick={() => setPath({ dim: path.dim })} aria-current={level === 0 ? "location" : undefined}>
          Portfolio
        </button>
        {path.key != null && (
          <>
            <Chevron size={12} className="text-muted" />
            <button type="button" className={clsx("crumb", level === 1 && "crumb-here")} onClick={() => setPath({ dim: path.dim, key: path.key })} aria-current={level === 1 ? "location" : undefined}>
              {DIM_LABEL[path.dim]}: {keyLabel}
            </button>
          </>
        )}
        {path.entity && (
          <>
            <Chevron size={12} className="text-muted" />
            <span className="crumb crumb-here" aria-current="location">
              {entityNames.get(path.entity) ?? path.entity}
            </span>
          </>
        )}
      </nav>

      {level === 0 && (
        <>
          <div role="group" aria-label="Group by" className="mb-3 flex flex-wrap gap-1.5">
            {(Object.keys(sets) as Dim[]).map((d) => (
              <button key={d} type="button" className="chip" aria-pressed={path.dim === d} onClick={() => setPath({ dim: d })}>
                {DIM_LABEL[d]}
              </button>
            ))}
          </div>
          <Bars rows={fromContribution(sets[path.dim], path.dim)} onPick={(k) => setPath({ dim: path.dim, key: k })} />
          {path.dim === "asset" && c.top_positions.length > 0 && (
            <div className="mt-6">
              <h4 className="mb-1 text-sm font-semibold">Largest single positions</h4>
              <Bars rows={c.top_positions.slice(0, 5).map((t) => ({ key: t.key, label: t.label, delta: t.delta, baseline: t.baseline_value, share: t.share_of_loss }))} />
            </div>
          )}
        </>
      )}

      {level === 1 && (
        <>
          <p className="mb-2 text-sm text-muted">Issuers inside {keyLabel.toLowerCase()}, largest change first.</p>
          {issuerRows.length === 0 ? <p className="text-sm text-muted">No issuer's value changed here.</p> : <Bars rows={issuerRows} onPick={(k) => setPath({ ...path, entity: k })} />}
        </>
      )}

      {level === 2 && (
        <>
          <p className="mb-2 text-sm text-muted">Positions of this issuer inside {keyLabel.toLowerCase()}.</p>
          <ul className="divide-y divide-rule border-y border-rule">
            {positions.map((p) => (
              <li key={p.asset_id} className="py-2.5 text-sm">
                <div className="flex flex-wrap items-baseline justify-between gap-x-4">
                  <span className="min-w-0 font-medium">{p.name}</span>
                  <span className="num text-neg">{money(p.delta, { signed: true })}</span>
                </div>
                <p className="num mt-0.5 text-xs text-muted">
                  {money(p.baseline_value)} → {money(p.stressed_value)} ({pct(p.delta_pct, 1, true)}) · {ASSET_CLASS_LABEL[p.asset_class] ?? p.asset_class}
                </p>
                <details className="disclosure mt-1">
                  <summary>Show the arithmetic</summary>
                  <p className="num mt-1 break-words text-xs text-ink-2">{p.formula}</p>
                </details>
              </li>
            ))}
          </ul>
        </>
      )}

      <p className="mt-4 text-xs text-muted">
        Total change <span className="num text-ink-2">{money(total, { signed: true })}</span>. A share can exceed 100% when gains elsewhere offset a larger loss.
      </p>
    </section>
  );
}
