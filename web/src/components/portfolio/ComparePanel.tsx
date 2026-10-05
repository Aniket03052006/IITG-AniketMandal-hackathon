import { useState } from "react";
import { useComparePortfolios, usePortfolios } from "../../api/hooks";
import type { DiffRow, PortfolioComparison } from "../../api/types";
import { pct } from "../../lib/format";
import { KindBadge } from "../ProvenanceKind";
import { ErrorState } from "../ui";

function Table({ rows, title, a, b }: { rows: DiffRow[]; title: string; a: string; b: string }) {
  if (!rows.length) return null;
  return (
    <div className="scroll-x">
      <table className="dtable" aria-label={title}>
        <thead>
          <tr>
            <th>{title}</th>
            <th className="text-right">{a}</th>
            <th className="text-right">{b}</th>
            <th className="text-right">Gap</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key}>
              <td>{r.label}</td>
              <td className="num text-right">{pct(r.a_pct, 2, true)}</td>
              <td className="num text-right">{pct(r.b_pct, 2, true)}</td>
              <td className="num text-right font-medium">{pct(r.gap_pct, 2, true)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Result({ c }: { c: PortfolioComparison }) {
  return (
    <div className="mt-4">
      <div className="grid gap-4 sm:grid-cols-2">
        {[
          { n: c.a.name, v: c.pnl_pct_a, s: c.status_a },
          { n: c.b.name, v: c.pnl_pct_b, s: c.status_b },
        ].map((x) => (
          <div key={x.n} className="card card-pad">
            <p className="eyebrow">{x.n}</p>
            <p className="num mt-1 text-xl font-semibold">{x.v != null ? pct(x.v, 2, true) : "–"}</p>
            <p className="text-xs text-muted">{x.v != null ? "modeled change" : x.s.replace("_", " ").toLowerCase()}</p>
          </div>
        ))}
      </div>
      <p className="mt-4 max-w-[68ch] text-ink-2">{c.difference}</p>
      <div className="mt-4 grid gap-6 lg:grid-cols-2">
        <Table rows={c.by_factor} title="By risk factor" a={c.a.name} b={c.b.name} />
        <Table rows={c.by_sector} title="By sector" a={c.a.name} b={c.b.name} />
      </div>
      <p className="mt-3 text-xs text-muted">{c.note}</p>
    </div>
  );
}

/** The same event and scenario on a second portfolio. Both sides are ordinary deterministic stress runs; this only lines them up. */
export function ComparePanel({ signalId, scenarioId, activeId, force }: { signalId: string; scenarioId?: string; activeId: string | null; force: boolean }) {
  const list = usePortfolios();
  const cmp = useComparePortfolios();
  const options = (list.data ?? []).filter((p) => (p.kind === "DEFAULT" ? activeId !== null : p.id !== activeId));
  const [other, setOther] = useState("");
  const pick = other || options[0]?.id || "";
  if (options.length === 0) return null;
  return (
    <section aria-label="Compare with another portfolio">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-lg font-semibold">Compare with another portfolio</h3>
        <KindBadge kind="scenario" label="Same event, same scenario" />
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <label className="block min-w-[14rem]">
          <span className="eyebrow mb-1.5 block">Compare against</span>
          <select className="field" value={pick} onChange={(e) => setOther(e.target.value)}>
            {options.map((p) => (
              <option key={p.id} value={p.id}>
                {p.kind === "DEFAULT" ? "Default synthetic book" : p.name}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className="btn"
          disabled={!pick || cmp.isPending}
          onClick={() => cmp.mutate({ signal_id: signalId, scenario_id: scenarioId ?? null, portfolio_ids: [activeId ?? "default", pick], force })}
        >
          {cmp.isPending ? "Comparing" : "Compare"}
        </button>
      </div>
      {cmp.error && <div className="mt-3"><ErrorState error={cmp.error} /></div>}
      {cmp.data && <Result c={cmp.data} />}
    </section>
  );
}
