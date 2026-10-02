import clsx from "clsx";
import { useState } from "react";
import { useEventModel, useMeta } from "../api/hooks";
import type { EventEvalSet, EventModelCard } from "../api/types";
import { categoryLabeler } from "../lib/taxonomy";
import { StageStrip } from "./StageStrip";
import { Card, ErrorState, Loading, Stat, StatusTag } from "./ui";

const ROLE: Record<string, string> = {
  in_domain: "In domain",
  indicative: "Our sources, AI-labelled",
  secondary: "Old benchmark, weak labels",
};

const f3 = (x: number) => x.toFixed(3);
const pct = (x: number) => `${(x * 100).toFixed(0)}%`;
const FALLBACK = (c: string) => (c === "NONE" ? "Not an event" : c.split("_").map((w) => w[0] + w.slice(1).toLowerCase()).join(" "));

type Short = (c: string) => string;

function ResultsTable({ sets, selected, onSelect }: { sets: EventEvalSet[]; selected: string; onSelect: (id: string) => void }) {
  return (
    <div className="scroll-x">
      <table className="dtable min-w-[52rem]">
        <caption className="sr-only">Event model results by evaluation set</caption>
        <thead>
          <tr>
            <th scope="col">Evaluation set</th>
            <th scope="col" className="text-right">Rows</th>
            <th scope="col" className="text-right">Model macro-F1</th>
            <th scope="col" className="text-right">As served</th>
            <th scope="col" className="text-right">Old keywords</th>
            <th scope="col" className="text-right">Majority</th>
            <th scope="col" className="text-right">Event vs not</th>
            <th scope="col" className="text-right">Committed</th>
          </tr>
        </thead>
        <tbody>
          {sets.map((e) => (
            <tr key={e.id} className={clsx(e.id === selected && "bg-paper-3")}>
              <td>
                <button type="button" className="text-left underline-offset-2 hover:underline" aria-pressed={e.id === selected} onClick={() => onSelect(e.id)}>
                  {e.title}
                </button>
                <span className="block text-xs text-muted">{ROLE[e.role] ?? e.role}</span>
              </td>
              {e.model ? (
                <>
                  <td className="num text-right">{e.model.n}</td>
                  <td className="num text-right font-medium text-ink">{f3(e.model.macro_f1)}</td>
                  <td className="num text-right">
                    <span className="font-medium text-ink">{f3(e.model.served.macro_f1)}</span>
                    {e.model.served_f1_ci95 && (
                      <span className="block text-xs text-muted">
                        {f3(e.model.served_f1_ci95[0])}–{f3(e.model.served_f1_ci95[1])}
                      </span>
                    )}
                  </td>
                  <td className="num text-right text-muted">{e.baselines.placeholder_keywords ? f3(e.baselines.placeholder_keywords.macro_f1) : "–"}</td>
                  <td className="num text-right text-muted">{e.baselines.majority_class ? f3(e.baselines.majority_class.macro_f1) : "–"}</td>
                  <td className="num text-right">
                    {f3(e.model.served.detection.f1)}
                    <span className="block text-xs text-muted">keywords {e.baselines.placeholder_keywords?.detection_f1?.toFixed(3) ?? "–"}</span>
                  </td>
                  <td className="num text-right">{pct(e.model.served.coverage)}</td>
                </>
              ) : (
                <td colSpan={7} className="text-sm text-muted">Not run: {e.note}</td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Detail({ set, short }: { set: EventEvalSet; short: Short }) {
  const m = set.model;
  if (!m) return null;
  const total = (row: number[]) => row.reduce((a, b) => a + b, 0) || 1;
  const mix = m.served.status_mix;
  return (
    <div className="grid gap-6 xl:grid-cols-2">
      <div className="min-w-0">
        <h3 className="mb-2 text-sm font-semibold">Per class (arg-max)</h3>
        <div className="scroll-x">
          <table className="dtable">
            <thead>
              <tr>
                <th scope="col">Class</th>
                <th scope="col" className="text-right">Precision</th>
                <th scope="col" className="text-right">Recall</th>
                <th scope="col" className="text-right">F1</th>
                <th scope="col" className="text-right">Support</th>
              </tr>
            </thead>
            <tbody>
              {m.labels.map((l) => {
                const c = m.per_class[l];
                return (
                  <tr key={l}>
                    <td>{short(l)}</td>
                    <td className="num text-right">{c ? f3(c.precision) : "–"}</td>
                    <td className="num text-right">{c ? f3(c.recall) : "–"}</td>
                    <td className="num text-right">{c ? f3(c.f1) : "–"}</td>
                    <td className="num text-right text-muted">{c ? c.support.toFixed(0) : "–"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="mt-2 max-w-[60ch] text-xs text-muted">
          What the product shows on this set: {pct(mix.CLASSIFIED ?? 0)} classified
          {m.served.classified_precision != null ? ` (right ${pct(m.served.classified_precision)} of the time)` : ""}, {pct(mix.NO_EVENT ?? 0)} not an event, {pct(mix.UNCERTAIN ?? 0)} uncertain.
          {m.weighted ? " Inclusion-weighted sample." : ""} Expected calibration error {m.ece?.toFixed(2) ?? "–"}.
        </p>
      </div>
      <div className="min-w-0">
        <h3 className="mb-2 text-sm font-semibold">Where it goes wrong</h3>
        <div className="scroll-x">
          <table className="dtable">
            <caption className="sr-only">Confusion matrix, share of each true class</caption>
            <thead>
              <tr>
                <th scope="col">True ↓ / predicted →</th>
                {m.labels.map((l) => (
                  <th key={l} scope="col" className="text-right" title={short(l)}>{short(l).split(" ").map((w) => w[0]).join("")}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {m.labels.map((l, i) => (
                <tr key={l}>
                  <td>{short(l)}</td>
                  {(m.confusion[i] ?? []).map((v, j) => (
                    <td key={j} className={clsx("num text-right", i === j ? "font-medium text-ink" : "text-muted")}>
                      {pct(v / total(m.confusion[i] ?? []))}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-xs text-muted">Each row sums to 100% of the true class. Columns are the model's arg-max before abstaining.</p>
      </div>
    </div>
  );
}

function Reliability({ card, short }: { card: EventModelCard; short: Short }) {
  return (
    <div className="scroll-x">
      <table className="dtable min-w-[40rem]">
        <caption className="sr-only">Reliability of each event class</caption>
        <thead>
          <tr>
            <th scope="col">Event class</th>
            <th scope="col" className="text-right">Training rows</th>
            <th scope="col" className="text-right">Dev rows</th>
            <th scope="col" className="text-right">Dev F1</th>
            <th scope="col">Status</th>
          </tr>
        </thead>
        <tbody>
          {card.class_reliability.map((r) => (
            <tr key={r.label}>
              <td>{short(r.label)}</td>
              <td className="num text-right">{r.train_examples}</td>
              <td className="num text-right">{r.dev_support}</td>
              <td className="num text-right">{r.dev_f1 == null ? "–" : f3(r.dev_f1)}</td>
              <td>
                <StatusTag tone={r.status === "ok" ? "ok" : r.status === "unreliable" ? "neg" : "warn"}>
                  {r.status === "ok" ? "Asserted" : r.status === "unreliable" ? "Never asserted" : "Unmeasured"}
                </StatusTag>
                <span className="mt-1 block text-xs text-muted">{r.reason}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Body({ card }: { card: EventModelCard }) {
  const { data: meta } = useMeta();
  const taxonomy = categoryLabeler(meta);
  const short: Short = (c) => (c === "NONE" ? "Not an event" : taxonomy(c) === c ? FALLBACK(c) : taxonomy(c));
  const [selected, setSelected] = useState("gold_history");
  const sets = card.evaluations;
  const current = sets.find((e) => e.id === selected && e.model) ?? sets.find((e) => e.model);
  const sel = card.candidates.find((c) => c.selected);
  const cal = card.calibration;
  const t = card.training;
  const ab = card.abstention;
  const acc = card.acceptance;
  return (
    <>
      <div className="mb-4">
        <StageStrip meta={meta} />
      </div>
      <p className="max-w-[72ch] text-sm text-ink-2">
        {card.algorithm}. It reads the headline or post only and answers one of nine things: the eight event types, or “not a market event”. It commits to its best answer only when that answer is at least {pct(ab.commit_threshold)} likely, and otherwise
        says “uncertain”. Trained on {(t.rows["train/annotated"] ?? 0).toLocaleString("en-US")} rows labelled by an AI annotator ({t.annotator}), selected on {t.rows.dev?.toLocaleString("en-US")} held-out rows, and scored once on
        the frozen gold set and {t.rows.replay_check?.toLocaleString("en-US")} fresh documents from the replay pack.
      </p>

      <div className="mt-5 border-t border-rule pt-4">
        <p className="flex flex-wrap items-center gap-2 text-sm">
          <StatusTag tone={acc.met ? "ok" : "warn"}>{acc.met ? "Acceptance bar met" : "Acceptance bar not met"}</StatusTag>
          <span className="text-muted">The bar was fixed before the held-out sets were scored.</span>
        </p>
        <ul className="mt-2 max-w-[80ch] space-y-1 text-sm text-ink-2">
          {acc.checks.map((c) => (
            <li key={c.name} className="flex items-start gap-2">
              <span className={clsx("num mt-0.5 shrink-0 text-xs font-medium", c.passed ? "text-pos" : "text-warn")}>{c.passed ? "PASS" : "FAIL"}</span>
              <span>
                {c.name}
                <span className="block text-xs text-muted">{c.detail}</span>
              </span>
            </li>
          ))}
        </ul>
      </div>

      <h3 className="mt-6 mb-2 text-sm font-semibold">Results by evaluation set</h3>
      <ResultsTable sets={sets} selected={current?.id ?? ""} onSelect={setSelected} />
      <p className="mt-2 max-w-[80ch] text-xs text-muted">
        Macro-F1 over nine classes. “Model” is the arg-max; “as served” counts every “uncertain” as wrong (95% bootstrap interval below it); the old keywords and the majority class always answer, and the old keywords can never say
        “not an event”. “Event vs not” is the F1 of telling an event from a non-event. The two dev rows were used to choose and calibrate the model, so they are optimistic; no training or model-selection choice used the gold set or the replay check set (one serving-policy change was made after a first full run, see the limits below).
      </p>

      {current && (
        <div className="mt-6 border-t border-rule pt-5">
          <h3 className="mb-1 text-sm font-semibold">{current.title}</h3>
          <p className="mb-4 max-w-[72ch] text-xs text-muted">
            {current.description} {current.note}
          </p>
          <Detail set={current} short={short} />
        </div>
      )}

      <h3 className="mt-6 mb-2 text-sm font-semibold">Which event types it will assert</h3>
      <Reliability card={card} short={short} />

      <div className="mt-6 grid grid-cols-2 gap-x-6 gap-y-4 border-t border-rule pt-5 sm:grid-cols-4">
        <Stat label="Candidates compared" value={card.candidates.length} sub="on dev log-loss only" />
        <Stat label="Chosen" value={sel ? `C=${sel.C}` : "–"} sub={sel ? `${sel.preprocessing} text · ${sel.class_weight ?? "unweighted"}` : ""} />
        <Stat label="Calibration" value={`T=${cal.temperature.toFixed(2)}`} sub={`ECE ${cal.ece_dev_population_before.toFixed(3)} → ${cal.ece_dev_population_after.toFixed(3)} on dev`} />
        <Stat label="Artifact" value={`${(card.artifact_bytes / 1e6).toFixed(1)} MB`} sub={<span className="num">sha256 {card.artifact_sha256.slice(0, 12)}</span>} />
        <Stat label="Commits on" value={pct(ab.dev_coverage)} sub="of dev rows (weighted)" />
        <Stat label="Classified" value={pct(ab.dev_classified_share)} sub={ab.dev_classified_precision != null ? `right ${pct(ab.dev_classified_precision)} of the time` : ""} />
        <Stat label="“Not an event”" value={ab.dev_no_event_precision != null ? pct(ab.dev_no_event_precision) : "–"} sub="precision when it says so" />
        <Stat label="Label noise bound" value={t.consistency.agreement != null ? pct(t.consistency.agreement) : "–"} sub={`annotator agrees with itself, κ ${t.consistency.kappa?.toFixed(2) ?? "–"}`} />
      </div>
      <p className="mt-3 max-w-[80ch] text-xs text-muted">{t.silver_note}</p>

      {card.confident_errors.length > 0 && (
        <>
          <h3 className="mt-6 mb-2 text-sm font-semibold">Its most confident mistakes</h3>
          <ul className="max-w-[80ch] divide-y divide-rule border-y border-rule text-xs">
            {card.confident_errors.slice(0, 8).map((e) => (
              <li key={`${e.eval_set}-${e.text}`} className="py-2">
                <span className="text-ink-2">{e.text}</span>
                <span className="num mt-0.5 block text-muted">
                  truth {short(e.truth)} · served {e.served.replace("CLASSIFIED:", "").replace("NO_EVENT", "not an event").replace(/_/g, " ").toLowerCase()} · P(not an event) {pct(e.p_none)} · {e.eval_set}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}

      <h3 className="mt-6 mb-2 text-sm font-semibold">Limits you should know about</h3>
      <ul className="max-w-[72ch] list-disc space-y-1.5 pl-5 text-sm text-ink-2">
        {card.limitations.map((l) => (
          <li key={l}>{l}</li>
        ))}
      </ul>
    </>
  );
}

export function EventModelPanel({ enabled }: { enabled: boolean }) {
  const { data, error, isLoading, refetch } = useEventModel(enabled);
  return (
    <Card title="Event model" aside={data ? <span className="num">{data.id}</span> : undefined}>
      {error ? <ErrorState error={error} retry={() => refetch()} /> : isLoading || !data ? <Loading label="Loading model card" /> : <Body card={data} />}
    </Card>
  );
}
