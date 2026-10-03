import clsx from "clsx";
import { useMemo, useState } from "react";
import { useEvidence, useMeta } from "../api/hooks";
import type { EvidenceBundle, EvidenceContrast, EvidenceFeature, EvidenceIncrement, EvidenceProtocolRun, StageStatus } from "../api/types";
import { axisFor, Interval, Verdict } from "../components/Interval";
import { Card, EmptyState, ErrorState, InlineNote, Loading, PageHeader, StatusTag } from "../components/ui";
import { KIND_LABEL, type ImpactKind } from "../lib/impact";

const STAGE_NAME: Record<string, string> = { sentiment: "Sentiment", event: "Event type", impact: "Impact" };
const AVAIL_NAME: Record<string, string> = {
  a: "Known before the event",
  b: "Published at event time",
  t: "From the report itself or prices before it",
  c: "Known only after the event",
  shortcut: "Identity shortcut",
  circular: "Circular (derived from the label)",
};

function KindTag({ kind }: { kind: string }) {
  const k = kind as ImpactKind;
  const tone = k === "validated" ? "ok" : k === "experimental" ? "warn" : "demo";
  return <StatusTag tone={tone}>{KIND_LABEL[k] ?? kind}</StatusTag>;
}

function Section({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <div className="lg:col-span-12">
      <p className="eyebrow mb-2">
        <span className="num">{n}</span> · {title}
      </p>
      {children}
    </div>
  );
}

function Unavailable({ what, command }: { what: string; command: string }) {
  return (
    <InlineNote tone="warn" title={`${what} has not been produced`}>
      Nothing is shown rather than a guess. Run <code className="num">{command}</code> to produce it.
    </InlineNote>
  );
}

/* ----------------------------------------------------------------------------------------------------- 1. verdicts */
function Verdicts({ stages }: { stages: StageStatus[] }) {
  return (
    <div className="grid gap-4 md:grid-cols-3">
      {stages.map((s) => (
        <Card key={s.stage} title={STAGE_NAME[s.stage] ?? s.stage} aside={<KindTag kind={s.kind} />}>
          <p className="num text-xs text-muted">{s.model_id ?? "no model loaded"}</p>
          <p className="mt-2 text-sm text-ink-2">{s.summary}</p>
          {s.failed.length > 0 && (
            <p className="mt-3 text-xs text-ink-2">
              <span className="font-medium text-warn">Checks failed ({s.failed.length}):</span> {s.failed.join("; ")}
            </p>
          )}
          {s.not_evaluable.length > 0 && (
            <p className="mt-1 text-xs text-muted">
              <span className="font-medium">Not evaluable:</span> {s.not_evaluable.join("; ")}
            </p>
          )}
          {s.passed.length > 0 && <p className="mt-1 text-xs text-muted">Passed: {s.passed.join("; ")}</p>}
          {s.artifact_sha256 && <p className="num mt-3 truncate text-xs text-muted">sha256 {s.artifact_sha256.slice(0, 16)}…</p>}
        </Card>
      ))}
    </div>
  );
}

/* ----------------------------------------------------------------------------------------------------- 2. data */
function YearBars({ rows }: { rows: EvidenceBundle["data"]["episodes_by_year"] }) {
  const max = Math.max(1, ...rows.map((r) => r.issuer + r.market + r.filing_events));
  return (
    <ul className="space-y-1.5" aria-label="Episodes per year">
      {rows.map((r) => {
        const w = (n: number) => `${((n / max) * 100).toFixed(2)}%`;
        return (
          <li key={r.year} className="grid grid-cols-[3rem_minmax(0,1fr)_auto] items-center gap-3 text-xs">
            <span className="num text-muted">{r.year}</span>
            <span className="flex h-3 overflow-hidden rounded-sm bg-paper-3" role="img" aria-label={`${r.year}: ${r.issuer} issuer, ${r.market} market-wide, ${r.filing_events} filing events`}>
              <span className="bg-accent" style={{ width: w(r.issuer) }} />
              <span className="bg-ink-2" style={{ width: w(r.market) }} />
              <span className="bg-warn" style={{ width: w(r.filing_events) }} />
            </span>
            <span className="num text-ink-2">
              {r.issuer} · {r.market} · {r.filing_events}
            </span>
          </li>
        );
      })}
      <li className="pt-1 text-xs text-muted">
        <span className="mr-3 inline-flex items-center gap-1">
          <i className="inline-block h-2 w-2 rounded-sm bg-accent" /> issuer news episodes
        </span>
        <span className="mr-3 inline-flex items-center gap-1">
          <i className="inline-block h-2 w-2 rounded-sm bg-ink-2" /> market-wide sessions
        </span>
        <span className="inline-flex items-center gap-1">
          <i className="inline-block h-2 w-2 rounded-sm bg-warn" /> SEC 8-K event episodes
        </span>
      </li>
    </ul>
  );
}

function DataCard({ d }: { d: EvidenceBundle["data"] }) {
  if (!d.available) return <Unavailable what="The data summary" command={d.command} />;
  return (
    <div className="grid gap-5 lg:grid-cols-12">
      <div className="lg:col-span-7">
        <Card title="Sources" aside="what the models learned from">
          <div className="scroll-x">
            <table className="dtable min-w-[40rem]">
              <caption className="sr-only">Data sources with period, size and timestamp quality</caption>
              <thead>
                <tr>
                  <th scope="col">Source</th>
                  <th scope="col">Period</th>
                  <th scope="col" className="text-right">Records</th>
                  <th scope="col">Timestamps</th>
                </tr>
              </thead>
              <tbody>
                {d.sources.map((s) => (
                  <tr key={s.name}>
                    <th scope="row" className="font-medium">
                      {s.name}
                      {s.note && <span className="block text-xs font-normal text-muted">{s.note}</span>}
                    </th>
                    <td className="num text-xs">{s.period}</td>
                    <td className="num text-right text-xs">{s.records != null ? s.records.toLocaleString("en-US") : "–"}</td>
                    <td className="text-xs text-ink-2">{s.timestamps}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
      <div className="lg:col-span-5">
        <Card title="Coverage by year" aside="issuer · market · filings">
          <YearBars rows={d.episodes_by_year} />
        </Card>
      </div>
      <div className="lg:col-span-6">
        <Card title="Labels" aside="evaluation truth">
          <ul className="space-y-3 text-sm">
            {d.gold.map((g) => (
              <li key={g.name}>
                <p className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="font-medium">{g.name}</span>
                  <span className="num text-xs text-muted">{g.rows} rows</span>
                </p>
                <p className="text-xs text-ink-2">{g.labelled_by}</p>
                {g.kappa != null && g.agreement != null && (
                  <p className="num text-xs text-muted">
                    agreement {(g.agreement * 100).toFixed(1)}% · kappa {g.kappa.toFixed(2)} · {g.agreed_rows} rows agreed
                  </p>
                )}
                <p className="num text-xs text-muted">human-reviewed rows: {g.human_reviewed}</p>
                <p className="text-xs text-muted">{g.note}</p>
              </li>
            ))}
          </ul>
        </Card>
      </div>
      <div className="lg:col-span-6">
        <Card title="Known gaps" aside="stated, not hidden">
          <ul className="list-disc space-y-1.5 pl-5 text-sm text-ink-2">
            {d.known_gaps.map((g) => (
              <li key={g}>{g}</li>
            ))}
          </ul>
        </Card>
      </div>
    </div>
  );
}

/* ----------------------------------------------------------------------------------------------------- 3. features */
function FeatureTable({ rows }: { rows: EvidenceFeature[] }) {
  return (
    <div className="scroll-x">
      <table className="dtable min-w-[44rem]">
        <caption className="sr-only">Features with their availability class</caption>
        <thead>
          <tr>
            <th scope="col">Feature</th>
            <th scope="col">Family</th>
            <th scope="col">Why it is, or is not, allowed</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((f) => (
            <tr key={f.name}>
              <th scope="row" className="num text-xs font-medium">{f.name}</th>
              <td className="text-xs text-ink-2">{f.group}</td>
              <td className="text-xs text-muted">{f.why}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FeaturesCard({ features }: { features: EvidenceFeature[] }) {
  const by = useMemo(() => {
    const m: Record<string, EvidenceFeature[]> = {};
    for (const f of features) (m[f.availability] ??= []).push(f);
    return m;
  }, [features]);
  const refused = [...(by.c ?? []), ...(by.shortcut ?? []), ...(by.circular ?? [])];
  return (
    <div className="grid gap-5 lg:grid-cols-12">
      <div className="lg:col-span-12">
        <Card title="What a model may see" aside="every feature carries one availability class; a model that asks for a refused one does not run">
          <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
            {(["a", "b", "t"] as const).map((k) => (
              <div key={k}>
                <dt className="eyebrow">{AVAIL_NAME[k]}</dt>
                <dd className="num mt-1 text-2xl font-semibold">{(by[k] ?? []).length}</dd>
              </div>
            ))}
            <div>
              <dt className="eyebrow text-warn">Refused</dt>
              <dd className="num mt-1 text-2xl font-semibold">{refused.length}</dd>
            </div>
          </dl>
        </Card>
      </div>
      <div className="lg:col-span-6">
        <Card title="Structured calendar (known in advance, or published before the report)">
          <FeatureTable rows={[...(by.a ?? []), ...(by.b ?? [])]} />
        </Card>
      </div>
      <div className="lg:col-span-6">
        <Card title="Refused: only known after the event, or an identity shortcut">
          <FeatureTable rows={refused} />
        </Card>
      </div>
      <div className="lg:col-span-12">
        <details className="card card-pad">
          <summary className="cursor-pointer text-sm font-medium">Prices, timing and the text models ({(by.t ?? []).length} features, all taken from the report itself or from sessions before it)</summary>
          <div className="mt-4">
            <FeatureTable rows={by.t ?? []} />
          </div>
        </details>
      </div>
    </div>
  );
}

/* ----------------------------------------------------------------------------------------------------- 4. the study */
const RUN_NAME: Record<string, string> = { P1_legacy: "Legacy protocol (impact-v1's 2022 hold-out)", P2_extended: "Extended protocol (val 2024, test 2025, live 2026 news)" };

function Increments({ rows }: { rows: EvidenceIncrement[] }) {
  const families = useMemo(() => [...new Set(rows.map((r) => r.family))], [rows]);
  const [family, setFamily] = useState<string | null>(null);
  const active = family && families.includes(family) ? family : (families.includes("full") ? "full" : families[0]);
  const shown = useMemo(() => rows.filter((r) => r.family === active), [rows, active]);
  const axis = useMemo(() => axisFor(shown.map((r) => r.delta_mae)), [shown]);
  if (!rows.length) return <p className="text-sm text-muted">No increments were evaluated for this run.</p>;
  return (
    <>
      <p className="mb-2 max-w-[80ch] text-xs text-muted">
        Paired difference in error of a model with the block over the same learner without it (log-severity MAE), on episodes it never saw. Left of the line the block
        helps, right of it the block hurts; the bar is the 95% interval. The learner changes how much the block can help, not whether it can.
      </p>
      <div role="group" aria-label="Learner" className="mb-3 flex flex-wrap items-center gap-2 text-xs">
        <span className="text-muted">Learner</span>
        {families.map((f) => (
          <button key={f} type="button" aria-pressed={f === active} className={clsx("btn", f === active && "border-accent")} onClick={() => setFamily(f)}>
            {f === "full" ? "boosting (interactions)" : f === "additive" ? "boosting (additive)" : f}
          </button>
        ))}
      </div>
      <div className="scroll-x">
        <table className="dtable min-w-[40rem]">
          <caption className="sr-only">Error change from adding each feature block, with intervals</caption>
          <thead>
            <tr>
              <th scope="col">Block added</th>
              <th scope="col">Evaluated on</th>
              <th scope="col">Reading</th>
              <th scope="col">◀ helps · hurts ▶</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((r, i) => (
              <tr key={`${r.block}-${r.family}-${r.where}-${i}`}>
                <th scope="row">{r.block}</th>
                <td className="num text-xs text-ink-2">{r.where === "oof" ? "out of fold (train period)" : r.where === "live" ? "live 2026 news" : r.where}</td>
                <td>
                  <Verdict v={r.verdict} />
                </td>
                <td>
                  <Interval e={r.delta_mae} axis={axis} digits={4} label={`${r.block}, ${r.family}, ${r.where}`} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function Checks({ run }: { run: EvidenceProtocolRun }) {
  if (!run.checks.length) return <p className="text-sm text-muted">{run.verdict}</p>;
  return (
    <ul className="max-w-[88ch] space-y-1.5 text-sm text-ink-2">
      {run.checks.map((c) => (
        <li key={c.id} className="flex items-start gap-2">
          <span className={clsx("num mt-0.5 w-[3.2rem] shrink-0 text-xs font-medium", c.passed === true ? "text-pos" : c.passed === false ? "text-warn" : "text-muted")}>
            {c.passed === true ? "PASS" : c.passed === false ? "FAIL" : "N/A"}
          </span>
          <span className="min-w-0">
            <span className="num text-muted">{c.id}</span> {c.label}
            <span className="num block text-xs text-muted">{c.value}</span>
            <span className="block text-xs text-muted">{c.detail}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

function Battery({ run }: { run: EvidenceProtocolRun }) {
  const axis = useMemo(() => axisFor(run.battery.map((b) => b.neutral_skill)), [run.battery]);
  if (!run.battery.length) return null;
  return (
    <div className="mt-6">
      <h3 className="text-sm font-semibold">Regime or event?</h3>
      <p className="mt-1 max-w-[80ch] text-xs text-muted">
        Volatility clusters, so a model that only knows which stocks are in a volatile stretch ranks severity above chance for every report. Removing the issuer and
        volatility regime from both prediction and outcome leaves the skill that is about the event. A placebo gap below zero means the model predicts the window
        before the event as well as the window after it.
      </p>
      <div className="scroll-x mt-2">
        <table className="dtable min-w-[48rem]">
          <caption className="sr-only">Regime-neutral rank skill by model and evaluation set</caption>
          <thead>
            <tr>
              <th scope="col">Model</th>
              <th scope="col">Role</th>
              <th scope="col">Set</th>
              <th scope="col">Skill within the regime</th>
              <th scope="col" className="text-right">Within-issuer</th>
              <th scope="col" className="text-right">Real − placebo</th>
            </tr>
          </thead>
          <tbody>
            {run.battery.map((b, i) => (
              <tr key={`${b.model}-${b.set}-${i}`}>
                <th scope="row" className="num text-xs font-medium">{b.model}</th>
                <td className="text-xs text-ink-2">{b.role.replace("_", " ")}</td>
                <td className="num text-xs">{b.set}</td>
                <td>
                  <Interval e={b.neutral_skill} axis={axis} label={`${b.model} on ${b.set}`} />
                </td>
                <td className="num text-right text-xs">{b.within_issuer_skill == null ? "–" : b.within_issuer_skill.toFixed(3)}</td>
                <td className="num text-right text-xs">{b.placebo_gap == null ? "–" : b.placebo_gap.toFixed(3)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {run.ablation.length > 0 && (
        <>
          <h3 className="mt-5 text-sm font-semibold">Take a block away</h3>
          <p className="mt-1 max-w-[80ch] text-xs text-muted">
            Without refitting: shuffle a block among comparable episodes (same issuer, same month) or replace it by its training median, and see what the model loses.
          </p>
          <div className="scroll-x mt-2">
            <table className="dtable min-w-[40rem]">
              <caption className="sr-only">Skill and error change when a feature block is shuffled or removed</caption>
              <thead>
                <tr>
                  <th scope="col">Block</th>
                  <th scope="col">How</th>
                  <th scope="col" className="text-right">Rank skill lost</th>
                  <th scope="col" className="text-right">Error added</th>
                </tr>
              </thead>
              <tbody>
                {run.ablation.map((a, i) => (
                  <tr key={`${a.block}-${i}`}>
                    <th scope="row" className="text-xs font-medium">{a.block.replace(/_/g, " ")}</th>
                    <td className="text-xs text-ink-2">{a.method}</td>
                    <td className="num text-right text-xs">{a.spearman_lost.toFixed(4)}</td>
                    <td className="num text-right text-xs">
                      {a.mae_added.toFixed(4)}
                      {a.mae_added_lo != null && a.mae_added_hi != null && (
                        <span className="block text-muted">
                          {a.mae_added_lo.toFixed(4)} to {a.mae_added_hi.toFixed(4)}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

function StudyCard({ s }: { s: EvidenceBundle["study"] }) {
  const [sel, setSel] = useState(0);
  if (!s.available) return <Unavailable what="The incremental-value study" command={s.command} />;
  const run = s.runs[Math.min(sel, s.runs.length - 1)];
  return (
    <Card title="Does reading the event add anything beyond market state?" aside={s.preregistration ? <span className="num">pre-registered · sha256 {s.preregistration.sha256?.slice(0, 12)}</span> : null}>
      <p className="max-w-[80ch] text-sm text-ink-2">
        Every comparison below was fixed in a configuration file before any 2023-2025 episode existed. Blocks are added to market state one at a time and judged only by a
        paired error difference on later periods. {s.p1_regression && <span className="text-muted">Regression gate: {s.p1_regression}</span>}
      </p>
      <div role="tablist" aria-label="Protocol and scope" className="mt-4 flex flex-wrap gap-2">
        {s.runs.map((r, i) => (
          <button key={`${r.protocol}/${r.scope}`} role="tab" aria-selected={i === sel} className={clsx("btn", i === sel && "border-accent")} onClick={() => setSel(i)}>
            {r.protocol === "P2_extended" ? "Extended" : "Legacy"} · {r.scope === "ISSUER" ? "issuer events" : "market-wide"}
          </button>
        ))}
      </div>
      {run && (
        <div className="mt-4" role="tabpanel">
          <p className="text-xs text-muted">
            {RUN_NAME[run.protocol] ?? run.protocol} · episodes {Object.entries(run.episodes).map(([k, v]) => `${k} ${v}`).join(" · ")}
            {run.selected && <> · selected by the pre-registered rule: <span className="num">{run.selected}</span></>}
            {run.best_block && <> · best block model <span className="num">{run.best_block}</span> vs best market-state model <span className="num">{run.best_state}</span></>}
          </p>
          {run.years_helpful && <p className="mt-1 text-xs text-ink-2">The block lowered error in {run.years_helpful}.</p>}
          <div className="mt-4">
            <Increments rows={run.increments} />
          </div>
          <h3 className="mt-6 text-sm font-semibold">Pre-registered checks</h3>
          <div className="mt-2">
            <Checks run={run} />
          </div>
          <Battery run={run} />
        </div>
      )}
    </Card>
  );
}

function ContrastRows({ rows, axis }: { rows: EvidenceContrast[]; axis: [number, number] }) {
  return (
    <div className="scroll-x">
      <table className="dtable min-w-[40rem]">
        <caption className="sr-only">Severity lift of an event over a matched quiet session</caption>
        <thead>
          <tr>
            <th scope="col">Group</th>
            <th scope="col" className="text-right">Pairs</th>
            <th scope="col">Lift in log-severity (event − quiet)</th>
            <th scope="col" className="text-right">AUC</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.label}>
              <th scope="row" className="text-xs font-medium">{r.label}</th>
              <td className="num text-right text-xs">{r.pairs}</td>
              <td>
                <Interval e={r.lift} axis={axis} label={r.label} />
              </td>
              <td className="num text-right text-xs">{r.auc == null ? "–" : r.auc.toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TrackFCard({ t }: { t: EvidenceBundle["study"]["track_f"] }) {
  const rows = useMemo(() => [...(t.headline ? [t.headline] : []), ...t.by_item], [t]);
  const axis = useMemo(() => axisFor(rows.map((r) => r.lift)), [rows]);
  const yrs = useMemo(() => [...t.earnings_by_year, ...t.non_earnings_by_year], [t]);
  const axisY = useMemo(() => axisFor(yrs.map((r) => r.lift)), [yrs]);
  if (!t.available) return null;
  return (
    <Card title="Event versus a quiet session" aside="SEC 8-K filings: official type, exact timestamp">
      <p className="max-w-[80ch] text-sm text-ink-2">
        An 8-K is the cleanest event we can get for free: the filer picks its item code to match a legal trigger and the SEC stamps the moment it was accepted. Each filing is
        paired with a session of the same issuer in the same volatility regime that had no filing nearby, so a lift here is about the event, not the regime.
      </p>
      <div className="mt-4">
        <ContrastRows rows={rows} axis={axis} />
      </div>
      {yrs.length > 0 && (
        <>
          <h3 className="mt-6 text-sm font-semibold">Earnings against everything else, by year</h3>
          <p className="mt-1 text-xs text-muted">The first block of rows is earnings filings, the second every other event type.</p>
          <div className="mt-2">
            <ContrastRows rows={[...t.earnings_by_year.map((r) => ({ ...r, label: `earnings ${r.label}` })), ...t.non_earnings_by_year.map((r) => ({ ...r, label: `other ${r.label}` }))]} axis={axisY} />
          </div>
        </>
      )}
      {t.item_code_increment.length > 0 && (
        <>
          <h3 className="mt-6 text-sm font-semibold">Does knowing the filing's own type predict how big the reaction is?</h3>
          <div className="mt-2">
            <Increments rows={t.item_code_increment} />
          </div>
        </>
      )}
      <p className="mt-4 text-xs text-muted">{t.note}</p>
    </Card>
  );
}

/* ----------------------------------------------------------------------------------------------------- 5. representation */
function RepresentationCard({ r }: { r: EvidenceBundle["representation"] }) {
  const axis = useMemo(() => axisFor(r.candidates.map((c) => c.pooled_delta_f1)), [r.candidates]);
  if (!r.available) return <Unavailable what="The representation comparison" command={r.command} />;
  return (
    <Card title="Keywords, semantics or both?" aside={<span className="num">baseline {r.baseline}</span>}>
      <p className="max-w-[80ch] text-sm text-ink-2">{r.decision}</p>
      <p className="mt-1 text-xs text-muted">
        Served macro-F1 counts every abstention as wrong. Scored on pooled held-out sets ({Object.entries(r.sets).map(([k, v]) => `${k} ${v}`).join(", ")}); a candidate must also hold on the
        set with semantic near-duplicates of training text removed. {r.baseline_pooled_f1 != null && <>Baseline pooled served macro-F1: <span className="num">{r.baseline_pooled_f1.toFixed(3)}</span>.</>}
      </p>
      <div className="scroll-x mt-3">
        <table className="dtable min-w-[56rem]">
          <caption className="sr-only">Candidate representations against the shipped TF-IDF model</caption>
          <thead>
            <tr>
              <th scope="col">Candidate</th>
              <th scope="col">Built on</th>
              <th scope="col">◀ worse · better ▶ (served macro-F1)</th>
              <th scope="col">Checks</th>
              <th scope="col">Decision</th>
            </tr>
          </thead>
          <tbody>
            {r.candidates.map((c) => (
              <tr key={c.id}>
                <th scope="row" className="num text-xs font-medium">{c.id}</th>
                <td className="text-xs text-ink-2">{c.detail}</td>
                <td>
                  <Interval e={c.pooled_delta_f1} axis={axis} label={c.id} />
                </td>
                <td className="text-xs text-ink-2">
                  {c.checks_failed.length ? <span className="text-warn">failed: {c.checks_failed.join(", ").replace(/_/g, " ")}</span> : <span className="text-pos">all {c.checks_passed.length} passed</span>}
                </td>
                <td>{c.adopt ? <StatusTag tone="ok">adopt</StatusTag> : <StatusTag tone="demo">not adopted</StatusTag>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <div>
          <h3 className="text-sm font-semibold">Cost of the encoders</h3>
          <div className="scroll-x mt-2">
            <table className="dtable min-w-[28rem]">
              <caption className="sr-only">Encoder cost per text</caption>
              <thead>
                <tr>
                  <th scope="col">Encoder</th>
                  <th scope="col" className="text-right">ms/text (batch 32)</th>
                  <th scope="col" className="text-right">peak MB</th>
                </tr>
              </thead>
              <tbody>
                {r.cost.map((c) => (
                  <tr key={c.model}>
                    <th scope="row" className="text-xs font-medium">
                      {c.model}
                      <span className="block text-xs font-normal text-muted">{c.kind}{c.controlled ? " · controlled benchmark" : " · measured while loaded"}</span>
                    </th>
                    <td className="num text-right text-xs">{c.ms_per_text_batch32?.toFixed(1) ?? "–"}</td>
                    <td className="num text-right text-xs">{c.peak_rss_mb ?? "–"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        <div>
          <h3 className="text-sm font-semibold">Does it read finance in context?</h3>
          <p className="mt-1 text-xs text-muted">
            Thirty minimal pairs where one phrase flips meaning with context ("crushing earnings" against "a crushing debt load"). Share of pairs whose good-news sentence scores higher. A diagnostic only; never used to choose.
          </p>
          <ul className="mt-2 space-y-1.5 text-sm">
            {r.probe.map((p) => (
              <li key={p.channel} className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="text-xs text-ink-2">{p.channel}</span>
                <span className="num text-xs">
                  {(p.share_correct * 100).toFixed(0)}% <span className="text-muted">({(p.lo * 100).toFixed(0)} to {(p.hi * 100).toFixed(0)})</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </Card>
  );
}

/* ----------------------------------------------------------------------------------------------------- page */
export function EvidencePage() {
  const { data: meta } = useMeta();
  const enabled = !!meta?.replay;
  const { data: b, error, isLoading, refetch } = useEvidence(enabled);
  if (meta && !meta.replay) {
    return (
      <EmptyState title="No evidence in the demo profile">
        The demo profile serves hand-authored fixtures. Start with the default replay profile to see how far the model outputs can be trusted.
      </EmptyState>
    );
  }
  if (error) return <ErrorState error={error} retry={() => refetch()} />;
  if (isLoading || !b) return <Loading label="Loading the evidence" />;
  return (
    <>
      <PageHeader
        title="Model evidence"
        sub="What each stage is, what it learned from, what it was allowed to see, and what the measurements say. Nothing is promoted without its pre-registered bar, and what is missing is named."
      />
      <div className="grid gap-8 lg:grid-cols-12">
        <Section n={1} title="What each stage is">
          <Verdicts stages={b.stages} />
        </Section>
        <Section n={2} title="What it learned from">
          <DataCard d={b.data} />
        </Section>
        <Section n={3} title="What it was allowed to see">
          <FeaturesCard features={b.features} />
        </Section>
        <Section n={4} title="Does event information add value, or only the volatility regime?">
          <div className="grid gap-5">
            <StudyCard s={b.study} />
            {b.study.available && <TrackFCard t={b.study.track_f} />}
          </div>
        </Section>
        <Section n={5} title="Which representation of the text">
          <RepresentationCard r={b.representation} />
        </Section>
        <Section n={6} title="How to reproduce it">
          <Card title="Inputs and hashes" aside="every number above is read from these files">
            <ul className="space-y-1.5 text-sm">
              {b.generated_from.length === 0 && <li className="text-muted">No evidence files have been produced yet.</li>}
              {b.generated_from.map((f) => (
                <li key={f.file} className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="num text-xs">{f.file}</span>
                  <span className="num text-xs text-muted">{f.sha256?.slice(0, 20)}…</span>
                </li>
              ))}
              {b.study.preregistration && (
                <li className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="num text-xs">{b.study.preregistration.file} (pre-registration)</span>
                  <span className="num text-xs text-muted">{b.study.preregistration.sha256?.slice(0, 20)}…</span>
                </li>
              )}
            </ul>
          </Card>
        </Section>
        <Section n={7} title="Limits, stated plainly">
          <Card>
            <ul className="list-disc space-y-1.5 pl-5 text-sm text-ink-2">
              {b.limitations.map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
          </Card>
        </Section>
      </div>
    </>
  );
}
