import type { LabComparison } from "../../api/types";
import { money, pct } from "../../lib/format";
import { SIMULATION_LABEL } from "../../lib/lab";
import { Waterfall } from "../portfolio/Waterfall";
import { KindBadge } from "../ProvenanceKind";
import { StatusTag } from "../ui";

/** Two or three scenarios side by side on one portfolio: value before and after, loss, dominant driver, sectors, risk factors, holdings and the assumptions that differ. */
export function CompareView({ c }: { c: LabComparison }) {
  return (
    <section className="card card-pad space-y-5" aria-label="Scenario comparison">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="font-display text-lg font-semibold">Comparison on {c.portfolio_name}</h3>
        <KindBadge kind="scenario" label={SIMULATION_LABEL} />
      </div>
      <div className="scroll-x">
        <table className="dtable min-w-[44rem]">
          <caption className="sr-only">Scenarios compared</caption>
          <thead>
            <tr>
              <th scope="col">&nbsp;</th>
              {c.rows.map((r) => (
                <th key={r.scenario_id} scope="col">
                  {r.name}
                  <span className="mt-1 block"><StatusTag tone="demo">{r.scenario_type}</StatusTag>{r.scenario_id === c.worst_scenario_id && <span className="ml-2"><StatusTag tone="neg">Largest loss</StatusTag></span>}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr><th scope="row">Value before</th>{c.rows.map((r) => <td key={r.scenario_id} className="num">{r.baseline_value != null ? money(r.baseline_value) : "–"}</td>)}</tr>
            <tr><th scope="row">Value after</th>{c.rows.map((r) => <td key={r.scenario_id} className="num">{r.stressed_value != null ? money(r.stressed_value) : "–"}</td>)}</tr>
            <tr><th scope="row">Absolute change</th>{c.rows.map((r) => <td key={r.scenario_id} className={`num ${r.pnl != null && r.pnl < 0 ? "text-neg" : ""}`}>{r.pnl != null ? money(r.pnl, { signed: true }) : r.status === "NOT_APPLICABLE" ? "Reaches nothing" : "–"}</td>)}</tr>
            <tr><th scope="row">Percentage change</th>{c.rows.map((r) => <td key={r.scenario_id} className="num">{r.pnl_pct != null ? pct(r.pnl_pct, 2, true) : "–"}</td>)}</tr>
            <tr><th scope="row">Dominant driver</th>{c.rows.map((r) => <td key={r.scenario_id}>{r.dominant_driver ?? "–"}</td>)}</tr>
            <tr><th scope="row">Most affected sectors</th>{c.rows.map((r) => <td key={r.scenario_id}>{r.top_sectors.join(", ") || "–"}</td>)}</tr>
            <tr><th scope="row">Risk factors</th>{c.rows.map((r) => <td key={r.scenario_id}>{r.top_risk_factors.join(", ") || "–"}</td>)}</tr>
            <tr><th scope="row">Most affected holdings</th>{c.rows.map((r) => <td key={r.scenario_id}>{r.top_holdings.join(", ") || "–"}</td>)}</tr>
            <tr><th scope="row">Assumptions</th>{c.rows.map((r) => <td key={r.scenario_id} className="num">{r.assumption_count}</td>)}</tr>
          </tbody>
        </table>
      </div>

      {c.assumption_diff.length > 0 && (
        <div className="scroll-x">
          <table className="dtable min-w-[36rem]">
            <caption className="sr-only">The assumptions of each scenario</caption>
            <thead><tr><th scope="col">Assumption</th>{c.rows.map((r) => <th key={r.scenario_id} scope="col">{r.name}</th>)}</tr></thead>
            <tbody>
              {c.assumption_diff.map((d) => (
                <tr key={d.key} data-differs={d.differs}>
                  <th scope="row">{d.label}{d.differs && <span className="ml-2"><StatusTag tone="warn">Differs</StatusTag></span>}</th>
                  {d.values.map((v, i) => <td key={`${d.key}-${i}`} className="num">{v ?? "–"}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        {c.results.map((r) => (
          <figure key={r.scenario_id} className="m-0">
            <figcaption className="mb-1 text-sm font-medium text-ink">{r.name}</figcaption>
            {r.attribution && r.attribution.drivers.rows.length > 0 ? (
              <Waterfall rows={r.attribution.drivers.rows.map((x) => ({ key: x.key, label: x.label, baseline_value: x.baseline_value, delta: x.delta, share_of_loss: x.share_of_total ?? null }))} total={r.attribution.total_pnl} />
            ) : (
              <p className="text-sm text-muted">{r.status === "COMPLETED" ? "Nothing moved." : r.reason}</p>
            )}
          </figure>
        ))}
      </div>
      <p className="text-xs text-muted">{c.note}</p>
    </section>
  );
}
