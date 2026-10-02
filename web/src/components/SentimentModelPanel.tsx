import clsx from "clsx";
import { useState } from "react";
import { useMeta, useSentimentModel } from "../api/hooks";
import type { EvalSet, SentimentModelCard } from "../api/types";
import { StageStrip } from "./StageStrip";
import { Card, ErrorState, Loading, Stat } from "./ui";

const ROLE: Record<string, string> = {
  in_domain: "In domain",
  external: "External",
  indicative: "Our sources, AI-labelled",
};

const f3 = (x: number) => x.toFixed(3);
const pct = (x: number) => `${(x * 100).toFixed(0)}%`;

function ResultsTable({ sets, selected, onSelect }: { sets: EvalSet[]; selected: string; onSelect: (id: string) => void }) {
  return (
    <div className="scroll-x">
      <table className="dtable min-w-[44rem]">
        <caption className="sr-only">Sentiment model results by evaluation set</caption>
        <thead>
          <tr>
            <th scope="col">Evaluation set</th>
            <th scope="col" className="text-right">Rows</th>
            <th scope="col" className="text-right">Model macro-F1</th>
            <th scope="col" className="text-right">Old lexicon</th>
            <th scope="col" className="text-right">Majority</th>
            <th scope="col" className="text-right">Rank corr.</th>
            <th scope="col" className="text-right">ECE</th>
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
                  <td className="num text-right">
                    <span className="font-medium text-ink">{f3(e.model.macro_f1)}</span>
                    {e.model.macro_f1_ci95 && (
                      <span className="block text-xs text-muted">
                        {f3(e.model.macro_f1_ci95[0])}–{f3(e.model.macro_f1_ci95[1])}
                      </span>
                    )}
                  </td>
                  <td className="num text-right text-muted">{e.baselines.placeholder_lexicon ? f3(e.baselines.placeholder_lexicon.macro_f1) : "–"}</td>
                  <td className="num text-right text-muted">{e.baselines.majority_class ? f3(e.baselines.majority_class.macro_f1) : "–"}</td>
                  <td className="num text-right">{e.model.spearman_score_vs_label?.toFixed(2) ?? "–"}</td>
                  <td className="num text-right">{e.model.ece?.toFixed(2) ?? "–"}</td>
                </>
              ) : (
                <td colSpan={6} className="text-sm text-muted">Not run: {e.note}</td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Detail({ set }: { set: EvalSet }) {
  const m = set.model;
  if (!m) return null;
  const total = (row: number[]) => row.reduce((a, b) => a + b, 0) || 1;
  return (
    <div className="grid gap-6 md:grid-cols-2">
      <div>
        <h3 className="mb-2 text-sm font-semibold">Per class</h3>
        <div className="scroll-x">
          <table className="dtable">
            <thead>
              <tr>
                <th scope="col">Class</th>
                <th scope="col" className="text-right">Precision</th>
                <th scope="col" className="text-right">Recall</th>
                <th scope="col" className="text-right">F1</th>
                <th scope="col" className="text-right">Mean score</th>
              </tr>
            </thead>
            <tbody>
              {m.labels.map((l) => {
                const c = m.per_class[l];
                return (
                  <tr key={l}>
                    <td className="capitalize">{l}</td>
                    <td className="num text-right">{c ? f3(c.precision) : "–"}</td>
                    <td className="num text-right">{c ? f3(c.recall) : "–"}</td>
                    <td className="num text-right">{c ? f3(c.f1) : "–"}</td>
                    <td className="num text-right">{m.mean_score_by_class?.[l]?.toFixed(2) ?? "–"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {m.product_rule && (
          <p className="mt-2 text-xs text-muted">
            Labelling by the score cut the UI uses (|score| ≥ 0.15) instead of the arg-max: macro-F1 <span className="num text-ink-2">{f3(m.product_rule.macro_f1)}</span> vs{" "}
            <span className="num text-ink-2">{f3(m.macro_f1)}</span>.
          </p>
        )}
      </div>
      <div>
        <h3 className="mb-2 text-sm font-semibold">Where it goes wrong</h3>
        <div className="scroll-x">
          <table className="dtable">
            <caption className="sr-only">Confusion matrix, share of each true class</caption>
            <thead>
              <tr>
                <th scope="col">True ↓ / predicted →</th>
                {m.labels.map((l) => (
                  <th key={l} scope="col" className="text-right capitalize">{l}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {m.labels.map((l, i) => (
                <tr key={l}>
                  <td className="capitalize">{l}</td>
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
        <p className="mt-2 text-xs text-muted">Each row sums to 100% of the true class{m.weighted ? " (inclusion-weighted sample)" : ""}.</p>
      </div>
    </div>
  );
}

function Body({ card }: { card: SentimentModelCard }) {
  const { data: meta } = useMeta();
  const [selected, setSelected] = useState("tfn_test");
  const sets = card.evaluations;
  const current = sets.find((e) => e.id === selected && e.model) ?? sets.find((e) => e.model);
  const sel = card.candidates.find((c) => c.selected);
  const cal = card.calibration;
  const t = card.training;
  return (
    <>
      <div className="mb-4">
        <StageStrip meta={meta} />
      </div>
      <p className="max-w-[72ch] text-sm text-ink-2">
        {card.algorithm}. Score = P(positive) − P(negative). Trained on {t.rows.train?.toLocaleString("en-US")} human-labelled {t.dataset} rows ({t.licence}), tuned on {t.rows.valid?.toLocaleString("en-US")}, scored once on {t.rows.test?.toLocaleString("en-US")} held-out.
        Gold labels and PhraseBank were never trained on or used to choose the model.
      </p>

      <h3 className="mt-6 mb-2 text-sm font-semibold">Results by evaluation set</h3>
      <ResultsTable sets={sets} selected={current?.id ?? ""} onSelect={setSelected} />
      <p className="mt-2 max-w-[72ch] text-xs text-muted">
        Macro-F1 by arg-max class, with a 95% bootstrap interval. “Old lexicon” is the placeholder this model replaces. Rank corr. is Spearman between the score and the −1/0/+1 label; ECE is calibration error (lower is better).
      </p>

      {current && (
        <div className="mt-6 border-t border-rule pt-5">
          <h3 className="mb-1 text-sm font-semibold">{current.title}</h3>
          <p className="mb-4 max-w-[72ch] text-xs text-muted">
            {current.description} {current.note}
          </p>
          <Detail set={current} />
        </div>
      )}

      <div className="mt-6 grid grid-cols-2 gap-x-6 gap-y-4 border-t border-rule pt-5 sm:grid-cols-4">
        <Stat label="Candidates compared" value={card.candidates.length} sub="on validation log-loss only" />
        <Stat label="Chosen" value={sel ? `C=${sel.C}` : "–"} sub={sel ? `${sel.preprocessing} text · ${sel.class_weight ?? "unweighted"}` : ""} />
        <Stat label="Calibration" value={`T=${cal.temperature.toFixed(2)}`} sub={`ECE ${cal.ece_test_before.toFixed(3)} → ${cal.ece_test_after.toFixed(3)} on TFN test`} />
        <Stat label="Artifact" value={`${(card.artifact_bytes / 1e6).toFixed(1)} MB`} sub={<span className="num">sha256 {card.artifact_sha256.slice(0, 12)}</span>} />
      </div>

      <h3 className="mt-6 mb-2 text-sm font-semibold">Limits you should know about</h3>
      <ul className="max-w-[72ch] list-disc space-y-1.5 pl-5 text-sm text-ink-2">
        {card.limitations.map((l) => (
          <li key={l}>{l}</li>
        ))}
      </ul>
    </>
  );
}

export function SentimentModelPanel({ enabled }: { enabled: boolean }) {
  const { data, error, isLoading, refetch } = useSentimentModel(enabled);
  return (
    <Card title="Sentiment model" aside={data ? <span className="num">{data.id}</span> : undefined}>
      {error ? <ErrorState error={error} retry={() => refetch()} /> : isLoading || !data ? <Loading label="Loading model card" /> : <Body card={data} />}
    </Card>
  );
}
