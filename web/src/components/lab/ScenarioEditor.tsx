import { useLabOptions } from "../../api/hooks";
import type { AssumptionKind, LabOptions } from "../../api/types";
import { ASSUMPTION_LABEL, type Draft, type Row, blankRow, displayUnit, fromValue, infoOf } from "../../lib/lab";
import { KindBadge } from "../ProvenanceKind";
import { Plus } from "../icons";

/** Targets a row may name, from the same vocabulary the validator enforces. A subject EventShock does not know cannot be typed in. */
function targetOptions(o: LabOptions, r: Row): { value: string; label: string }[] {
  switch (r.kind) {
    case "SECTOR":
    case "CREDIT_SPREAD":
      return o.sectors;
    case "ISSUER":
      return o.issuers;
    case "FX":
      return o.currencies;
    case "RISK_FACTOR":
      return [...o.risk_factors.map((x) => ({ value: x.value, label: `${x.label} (${x.detail ?? ""})` })), ...o.currencies.map((c) => ({ value: `FX:${c.value}`, label: `Currency ${c.value} (FX)` }))].filter((x) => x.value !== "FX");
    default:
      return [];
  }
}

export function riskUnit(o: LabOptions | undefined, target: string): string {
  const d = o?.risk_factors.find((x) => x.value === target.split(":")[0])?.detail ?? "";
  return d.endsWith("bp") ? "bp" : d.endsWith("multiplier") ? "multiplier" : "fraction";
}

function AssumptionRow({ o, r, onChange, onRemove, index }: { o: LabOptions; r: Row; onChange: (r: Row) => void; onRemove: () => void; index: number }) {
  const info = infoOf(o.kinds, r.kind);
  const unit = r.kind === "RISK_FACTOR" ? riskUnit(o, r.target) : (info?.unit ?? "fraction");
  const targets = targetOptions(o, r);
  const needs = info?.needs_target;
  const bounds = r.kind === "RISK_FACTOR" ? o.risk_factors.find((x) => x.value === r.target.split(":")[0])?.detail : info?.min != null && info?.max != null ? `${fromValue(info.min, unit)} to ${fromValue(info.max, unit)} ${displayUnit(unit)}` : null;
  return (
    <li className="grid gap-3 border-t border-rule py-3 first:border-t-0 md:grid-cols-[minmax(0,1.2fr)_minmax(0,1.2fr)_8rem_auto]" aria-label={`Assumption ${index + 1}`}>
      <label>
        <span className="eyebrow block">Shock</span>
        <select className="field mt-1 w-full" value={r.kind} onChange={(e) => onChange({ ...r, kind: e.target.value as AssumptionKind, target: "" })}>
          {o.kinds.map((k) => <option key={k.kind} value={k.kind}>{k.label}</option>)}
        </select>
      </label>
      <label>
        <span className="eyebrow block">{needs ? needs.charAt(0).toUpperCase() + needs.slice(1) : "Applies to"}</span>
        {targets.length > 0 ? (
          <select className="field mt-1 w-full" value={r.target} onChange={(e) => onChange({ ...r, target: e.target.value })} aria-label={`Target of assumption ${index + 1}`}>
            <option value="">{r.kind === "CREDIT_SPREAD" ? "All sectors" : "Choose…"}</option>
            {targets.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
        ) : (
          <span className="mt-1 block py-2 text-sm text-muted">{info?.reaches ?? ""}</span>
        )}
      </label>
      <label>
        <span className="eyebrow block">Size ({displayUnit(unit)})</span>
        <input className="field num mt-1 w-full" inputMode="decimal" value={r.value} onChange={(e) => onChange({ ...r, value: e.target.value })} placeholder="e.g. -10" aria-label={`Size of assumption ${index + 1} in ${displayUnit(unit)}`} />
        {bounds && <span className="mt-0.5 block text-2xs text-muted">limits {bounds}</span>}
      </label>
      <div className="flex items-end justify-between gap-2 md:flex-col md:items-end">
        <KindBadge kind="scenario" label={ASSUMPTION_LABEL} />
        <button type="button" className="btn btn-ghost btn-sm" onClick={onRemove} aria-label={`Remove assumption ${index + 1}`}>Remove</button>
      </div>
    </li>
  );
}

/** One scenario you build: each row is a shock you choose, labelled SCENARIO ASSUMPTION. A shock only reaches positions that carry the exposure it acts on. */
export function ScenarioEditor({ draft, onChange, onRun, onRemove, running, canRemove }: { draft: Draft; onChange: (d: Draft) => void; onRun: () => void; onRemove: () => void; running: boolean; canRemove: boolean }) {
  const q = useLabOptions();
  const o = q.data;
  const custom = draft.type === "CUSTOM";
  const hasOil = draft.rows.some((r) => r.kind === "COMMODITY" || (r.kind === "RISK_FACTOR" && r.target === "OIL_ENERGY"));
  return (
    <section className="card card-pad space-y-3" aria-label={`Scenario ${draft.name || draft.type}`}>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <label className="min-w-48 flex-1">
          <span className="eyebrow block">Name</span>
          <input className="field mt-1 w-full" value={draft.name} maxLength={80} onChange={(e) => onChange({ ...draft, name: e.target.value })}
                 placeholder={draft.type === "BASE" ? "Base (no shock)" : draft.type === "ASSESSED" ? "Assessed scenario for this event" : "Custom scenario"} />
        </label>
        <span className="chip" aria-label="Scenario type">{draft.type === "BASE" ? "Base: the book as it is" : draft.type === "ASSESSED" ? "Assessed: EventShock's scenario for this event" : "Custom: your assumptions"}</span>
      </div>
      {draft.type === "ASSESSED" && <p className="text-sm text-ink-2">Runs the scenario EventShock generated for this event, with its own configured assumptions. It is kept apart from the scenarios you build.</p>}
      {draft.type === "BASE" && <p className="text-sm text-ink-2">No shock: the portfolio as it is. A baseline to compare against.</p>}
      {custom && (
        <>
          {q.isLoading && <p className="text-sm text-muted">Loading what can be shocked…</p>}
          {o && (
            <>
              <ul className="list-none p-0" aria-label="Assumptions">
                {draft.rows.map((r, i) => (
                  <AssumptionRow key={r.key} o={o} r={r} index={i} onChange={(nr) => onChange({ ...draft, rows: draft.rows.map((x) => (x.key === r.key ? nr : x)) })} onRemove={() => onChange({ ...draft, rows: draft.rows.filter((x) => x.key !== r.key) })} />
                ))}
              </ul>
              {draft.rows.length === 0 && <p className="text-sm text-ink-2">No assumptions yet. Add a shock below.</p>}
              <div className="flex flex-wrap items-center gap-3">
                <button type="button" className="btn btn-sm" disabled={draft.rows.length >= o.max_assumptions} onClick={() => onChange({ ...draft, rows: [...draft.rows, blankRow()] })}><Plus size={12} /> Add a shock</button>
                {hasOil && (
                  <label className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={draft.exposurePriors} onChange={(e) => onChange({ ...draft, exposurePriors: e.target.checked })} />
                    Estimate oil exposure from sector priors <span className="text-xs text-muted">(a judgement prior, shown with the result)</span>
                  </label>
                )}
              </div>
              {o.held_currencies.length === 0 && draft.rows.some((r) => r.kind === "FX") && (
                <p className="text-xs text-muted">This portfolio holds nothing in another currency, so a currency shock reaches nothing. A personal portfolio can hold a position in a foreign currency.</p>
              )}
            </>
          )}
        </>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" className="btn btn-primary" onClick={onRun} disabled={running || (custom && !draft.rows.some((r) => r.value.trim() !== "")) || (draft.type === "ASSESSED" && !draft.signalId)}>{running ? "Running…" : "Run scenario"}</button>
        {canRemove && <button type="button" className="btn btn-ghost" onClick={onRemove}>Remove scenario</button>}
      </div>
    </section>
  );
}
