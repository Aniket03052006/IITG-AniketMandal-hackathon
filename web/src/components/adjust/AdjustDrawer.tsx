import { useMemo, useState } from "react";
import { useAdjustmentMutations, useAdjustments, useMeta } from "../../api/hooks";
import type { AdjustmentKnob, ValidationIssue } from "../../api/types";
import { GROUPS } from "../../lib/propagation";
import { Drawer, DrawerSection, useOpenDrawer } from "../Drawer";
import { StateNotice } from "../StateNotice";
import { Tabs } from "../Tabs";
import { ErrorState, Loading } from "../ui";
import { type Draft, KnobRow } from "./KnobRow";
import { MappingEditor } from "./MappingEditor";

const SECTION_LABEL: Record<string, string> = {
  generation: "When a scenario is generated", templates: "Scenario templates", shock_overrides: "Scenario shock sizes", materiality: "Relevance lookup", concentration: "Concentration and overlap",
  relevance_bands: "Feed relevance bands", scope: "Scope", sources: "Sources", grouping: "Event grouping", evidence: "Evidence strength", novelty: "Novelty", velocity: "Narrative velocity",
  claims: "Contradiction", lifecycle: "Lifecycle", category_risk_factors: "Risk factors assumed per event class",
};

const sectionOf = (k: AdjustmentKnob): string => {
  const p = k.path.split(".");
  return p[2] === "templates" || p[1] === "templates" ? (k.path.includes(".shock_overrides.") ? "shock_overrides" : "templates") : (p[1] ?? "");
};

function Body() {
  const state = useAdjustments(true);
  const m = useAdjustmentMutations();
  const [group, setGroup] = useState("scenario");
  const [draft, setDraft] = useState<Draft>({});
  const [issues, setIssues] = useState<Record<string, string>>({});
  const [general, setGeneral] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const busy = m.validate.isPending || m.save.isPending || m.reset.isPending || m.resetAll.isPending;

  const sections = useMemo(() => {
    const out = new Map<string, AdjustmentKnob[]>();
    for (const k of state.data?.knobs ?? []) {
      if (k.group !== group) continue;
      const key = sectionOf(k);
      out.set(key, [...(out.get(key) ?? []), k]);
    }
    return [...out.entries()];
  }, [state.data, group]);

  if (state.isLoading) return <Loading label="Loading adjustable settings" />;
  if (state.error || !state.data) return <ErrorState error={(state.error as Error) ?? new Error("No settings")} retry={() => state.refetch()} />;
  const st = state.data;
  const pending = Object.keys(draft).length;
  const set = (path: string, value: unknown) => { setSaved(false); setIssues((x) => { const n = { ...x }; delete n[path]; return n; }); setDraft((d) => ({ ...d, [path]: value })); };
  const dropDraft = (path: string) => setDraft((d) => { const n = { ...d }; delete n[path]; return n; });
  const reset = (path: string) => {
    setSaved(false);
    dropDraft(path);
    if (st.knobs.some((k) => k.path === path && k.adjusted) || st.added_edges.some((a) => a.path === path)) m.reset.mutate(path);
  };
  const save = async () => {
    setGeneral(null);
    setSaved(false);
    const values = Object.fromEntries(Object.entries(draft));
    const bad = Object.entries(values).filter(([, v]) => v === "" || (typeof v === "number" && !Number.isFinite(v)));
    if (bad.length) { setIssues(Object.fromEntries(bad.map(([p]) => [p, "Enter a number."]))); return; }
    try {
      const report = await m.validate.mutateAsync(values);
      if (!report.ok) {
        const byPath: Record<string, string> = {};
        report.issues.forEach((i: ValidationIssue) => { if (i.path) byPath[i.path] = i.message; else setGeneral(i.message); });
        setIssues(byPath);
        return;
      }
      await m.save.mutateAsync(values);
      setDraft({});
      setIssues({});
      setSaved(true);
    } catch (e) {
      setGeneral((e as Error).message);
    }
  };

  return (
    <>
      <DrawerSection title="What this changes" note="Every value here is one of your own assumptions. The shipped defaults in configs/ are never edited.">
        <p className="max-w-[60ch] text-sm text-ink-2">{st.note}</p>
        <p className="mt-2 text-sm" role="status">
          {st.count === 0 ? "Nothing is adjusted: every side-car runs on its shipped defaults." : `${st.count} value${st.count > 1 ? "s are" : " is"} adjusted from the defaults (version ${st.version}).`}
          {st.count > 0 && (
            <button type="button" className="ml-3 underline underline-offset-2 hover:text-accent" disabled={busy} onClick={() => { setDraft({}); setIssues({}); m.resetAll.mutate(); }}>
              Reset everything to the defaults
            </button>
          )}
        </p>
      </DrawerSection>
      <div className="mt-5">
        <Tabs tabs={GROUPS.map((g) => ({ id: g.id, label: g.label }))} active={group} onChange={setGroup} label="Group of settings">
          <div role="presentation" className="mt-3">
            <p className="mb-3 text-sm text-muted">{GROUPS.find((g) => g.id === group)?.blurb}</p>
            {group === "mapping" ? (
              <>
                <MappingEditor state={st} draft={draft} onChange={set} onReset={reset} issues={issues} />
                {sections.filter(([k]) => k === "category_risk_factors").map(([k, knobs]) => (
                  <details key={k} className="disclosure mt-5"><summary>{SECTION_LABEL[k]}</summary>
                    <div className="mt-2">{knobs.map((kn) => <KnobRow key={kn.path} k={kn} draft={draft} onChange={set} onReset={reset} issue={issues[kn.path]} />)}</div>
                  </details>
                ))}
              </>
            ) : (
              sections.map(([key, knobs], i) => (
                <details key={key} className="disclosure mb-3" open={i === 0 || knobs.some((k) => k.adjusted || k.path in draft)}>
                  <summary>{SECTION_LABEL[key] ?? key} <span className="text-xs text-muted">({knobs.length})</span></summary>
                  <div className="mt-2">{knobs.map((k) => <KnobRow key={k.path} k={k} draft={draft} onChange={set} onReset={reset} issue={issues[k.path]} />)}</div>
                </details>
              ))
            )}
          </div>
        </Tabs>
      </div>
      <div className="sticky bottom-0 mt-6 flex flex-wrap items-center gap-3 border-t border-rule bg-paper py-3">
        <button type="button" className="btn btn-primary" disabled={pending === 0 || busy} onClick={save}>{busy ? "Saving" : `Save ${pending || ""} change${pending === 1 ? "" : "s"}`}</button>
        <button type="button" className="btn" disabled={pending === 0 || busy} onClick={() => { setDraft({}); setIssues({}); setGeneral(null); }}>Discard</button>
        <span className="text-sm text-muted" role="status" aria-live="polite">{saved ? "Saved. The side-cars were rebuilt on your values." : pending ? `${pending} unsaved` : ""}</span>
      </div>
      {(general || Object.keys(issues).length > 0) && (
        <StateNotice tone="warn" what="Not saved" why={general ?? "Fix the highlighted values: nothing was changed."} className="mt-3" />
      )}
    </>
  );
}

/** The one drawer for manual adjustment. It lives in the shell, so `?open=adjust` works from every page. */
export function AdjustHost() {
  const [open, setOpen] = useOpenDrawer();
  const { data: meta } = useMeta();
  if (meta?.capabilities.adjustments === false) return null;
  return (
    <Drawer open={open === "adjust"} onClose={() => setOpen(null)} title="Adjust assumptions" eyebrow="Manual control" wide>
      {open === "adjust" && <Body />}
    </Drawer>
  );
}
