import { useState } from "react";
import { useCompareScenarios, useLabOptions, useMeta, useRunScenario } from "../../api/hooks";
import type { LabComparison, LabResult } from "../../api/types";
import type { ScenarioRequest } from "../../api/types";
import { type Draft, blankRow, fromValue, newId, toRequest } from "../../lib/lab";
import { ErrorState, StatusTag } from "../ui";
import { CompareView } from "./CompareView";
import { LabResultView } from "./LabResultView";
import { ReverseStress } from "./ReverseStress";
import { ScenarioEditor, riskUnit } from "./ScenarioEditor";

const customDraft = (name = ""): Draft => ({ id: newId("d"), type: "CUSTOM", name, rows: [blankRow()], exposurePriors: false, signalId: null });

/** The scenario lab: build up to three scenarios (a baseline, the event's own assessed scenario, and ones you choose), run them on the unchanged engine and compare them. */
export function ScenarioLab({ signalId }: { signalId?: string | null }) {
  const { data: meta } = useMeta();
  const on = meta?.capabilities.scenario_lab === true;
  const opts = useLabOptions(on);
  const run = useRunScenario();
  const compare = useCompareScenarios();
  const [drafts, setDrafts] = useState<Draft[]>([customDraft()]);
  const [results, setResults] = useState<Record<string, LabResult>>({});
  const [reqs, setReqs] = useState<Record<string, ScenarioRequest>>({});
  const [running, setRunning] = useState<string | null>(null);
  const [cmp, setCmp] = useState<LabComparison | null>(null);
  const [note, setNote] = useState<string | null>(null);
  if (!on) return null;
  const max = opts.data?.max_compared ?? 3;
  const ru = (t: string) => riskUnit(opts.data, t);
  const set = (d: Draft) => setDrafts(drafts.map((x) => (x.id === d.id ? d : x)));
  const add = (d: Draft) => drafts.length < max && setDrafts([...drafts, d]);

  /** A combination found by reverse stress becomes a custom scenario you can edit and run. */
  const fork = (req: ScenarioRequest) => {
    const rows = (req.assumptions ?? []).map((a) => ({ ...blankRow(a.kind), target: a.target ?? "", value: fromValue(a.value, opts.data?.kinds.find((k) => k.kind === a.kind)?.unit ?? "fraction"), rationale: a.rationale ?? "" }));
    const d: Draft = { id: newId("d"), type: "CUSTOM", name: req.name ?? "From reverse stress", rows, exposurePriors: !!req.exposure_priors, signalId: null };
    setDrafts(drafts.length >= max ? [...drafts.slice(0, max - 1), d] : [...drafts, d]);
  };

  const runOne = (d: Draft) => {
    const { body, skipped } = toRequest(d, opts.data?.kinds, ru);
    setNote(skipped ? `${skipped} assumption${skipped === 1 ? " has" : "s have"} no size yet and ${skipped === 1 ? "was" : "were"} left out.` : null);
    setRunning(d.id);
    run.mutate(body, { onSuccess: (r) => { setResults((p) => ({ ...p, [d.id]: r })); setReqs((p) => ({ ...p, [d.id]: body })); }, onSettled: () => setRunning(null) });
  };
  const runCompare = () => {
    const reqs = drafts.map((d) => toRequest(d, opts.data?.kinds, ru).body);
    compare.mutate(reqs, { onSuccess: (c) => { setCmp(c); setResults(Object.fromEntries(drafts.map((d, i) => [d.id, c.results[i] as LabResult]))); } });
  };

  return (
    <section aria-label="Scenario lab" className="space-y-4">
      <div className="max-w-[72ch]">
        <p className="eyebrow">Scenario lab</p>
        <h2 className="font-display text-xl font-semibold">What if…? Build your own scenarios.</h2>
        <p className="mt-1 text-sm text-ink-2">Choose the shocks yourself: every size you set is a <strong>scenario assumption</strong>, run through the same deterministic engine as an event's scenario. The results are hypothetical stress analysis, not predictions.</p>
      </div>
      <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Add a scenario">
        <button type="button" className="btn btn-sm" disabled={drafts.length >= max} onClick={() => add(customDraft())}>Add a custom scenario</button>
        <button type="button" className="btn btn-sm" disabled={drafts.length >= max || drafts.some((d) => d.type === "BASE")} onClick={() => add({ id: newId("d"), type: "BASE", name: "", rows: [], exposurePriors: false, signalId: null })}>Add the base case</button>
        {signalId && <button type="button" className="btn btn-sm" disabled={drafts.length >= max || drafts.some((d) => d.type === "ASSESSED")} onClick={() => add({ id: newId("d"), type: "ASSESSED", name: "", rows: [], exposurePriors: false, signalId })}>Add this event's assessed scenario</button>}
        <StatusTag tone="demo">{drafts.length} of {max}</StatusTag>
        {drafts.length >= 2 && <button type="button" className="btn btn-primary btn-sm" disabled={compare.isPending} onClick={runCompare}>{compare.isPending ? "Comparing…" : `Run and compare ${drafts.length}`}</button>}
      </div>
      {note && <p role="status" className="text-sm text-warn">{note}</p>}
      {(run.error || compare.error) && <ErrorState error={(run.error ?? compare.error) as Error} />}
      <div className="space-y-4">
        {drafts.map((d) => (
          <div key={d.id} className="space-y-3">
            <ScenarioEditor draft={d} onChange={set} onRun={() => runOne(d)} running={running === d.id} canRemove={drafts.length > 1}
                            onRemove={() => { setDrafts(drafts.filter((x) => x.id !== d.id)); setResults(({ [d.id]: _gone, ...rest }) => rest); setCmp(null); }} />
            {results[d.id] && !cmp && <LabResultView r={results[d.id] as LabResult} req={reqs[d.id]} />}
          </div>
        ))}
      </div>
      {cmp && <CompareView c={cmp} />}
      <div className="border-t border-rule pt-6"><ReverseStress onFork={fork} /></div>
    </section>
  );
}
