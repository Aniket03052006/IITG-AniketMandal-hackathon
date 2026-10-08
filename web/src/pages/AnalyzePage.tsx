import { useState } from "react";
import { Link } from "react-router-dom";
import { useAnalyze, useMeta, useScenarios, useSignalRelevance } from "../api/hooks";
import { MiniChain } from "../components/assessment/MiniChain";
import { ModeChip } from "../components/assessment/ModeChip";
import { ReferencePanel } from "../components/assessment/ReferencePanel";
import { IntelligenceSummary } from "../components/intelligence/IntelligencePanel";
import { OriginChip } from "../components/assessment/OriginChip";
import { ScaleBar } from "../components/assessment/ScaleBar";
import { ScoreBuildUp } from "../components/assessment/ScoreBuildUp";
import { MarketNote } from "../components/assessment/MarketNote";
import { ThresholdNotice } from "../components/assessment/ThresholdNotice";
import { UnderstandingCard } from "../components/assessment/UnderstandingCard";
import { severityLede } from "../lib/assessment";
import type { AnalyzeResponse, SignalSummary } from "../api/types";
import { ArrowRight, Spinner } from "../components/icons";
import { EventStatusTag } from "../components/EventStatusTag";
import { RelevanceTag, ScopeTag } from "../components/scope/Tags";
import { StateNotice } from "../components/StateNotice";
import { ImpactMeter, PageHeader, SentimentBar } from "../components/ui";
import { summaryKind } from "../lib/impact";
import { subjectLine, subjectOfSummary, THEME_LABEL } from "../lib/scope";
import { categoryLabeler } from "../lib/taxonomy";
import type { ScopeLevel } from "../lib/scope";

/** One of each scope, so the first minute shows what the engine does when it can name a company, a sector, the market, or nothing. */
export const EXAMPLES = [
  { id: "company", label: "A company", text: "Goldman Sachs fined $50 million over trading violations, regulators say" },
  { id: "sector", label: "A sector", text: "Chipmakers slide as semiconductor demand softens and data center spending slows" },
  { id: "macro", label: "The market", text: "Federal Reserve signals rate cuts as inflation cools; Treasury yields drop" },
  { id: "unresolved", label: "Nothing to name", text: "Shares of the company tumbled after a surprise announcement" },
] as const;

/** The wider set for the demo: one headline per event class, plus one that names a company the entity master does not hold. */
export const MORE_EXAMPLES = [
  { id: "regulatory", label: "Regulatory", text: "European regulators propose stricter capital requirements for major banks, potentially increasing funding costs." },
  { id: "monetary", label: "Monetary policy", text: "The Federal Reserve signals that interest rates may remain elevated for longer as inflation remains persistent." },
  { id: "geopolitical", label: "Geopolitical", text: "Escalating tensions threaten oil supply routes, sending crude prices sharply higher." },
  { id: "earnings", label: "Earnings", text: "A major technology company cuts its revenue outlook because of weaker cloud demand." },
  { id: "mna", label: "M&A", text: "A major semiconductor company agrees to acquire a software business in a multibillion-dollar transaction." },
  { id: "unknown", label: "Unknown company", text: "Quantum Dynamics announces a major restructuring following weaker-than-expected demand." },
] as const;

const OUTCOME_WORD: Record<string, string> = {
  NEW: "New signal",
  UPDATED: "Joined a story already in the feed",
  DUPLICATE: "Already analysed: this is the same signal",
};

function Reading({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="reading">
      <p className="eyebrow">{title}</p>
      {children}
    </div>
  );
}

/** The five steps as they happen, while the request is in flight: honest about what is being done (and that the LLM, if on, is only reading). */
function Working({ llm }: { llm: boolean }) {
  return (
    <section className="card p-5" role="status" aria-label="Analysing the text" aria-live="polite">
      <p className="eyebrow">Analysing</p>
      <ol className="mt-3 space-y-2 text-sm text-ink-2">
        <li>1 · Reading the text{llm ? " with the language model (it only reads: it does not score)" : " with the deterministic rules"}</li>
        <li>2 · Checking every entity and quote against the text</li>
        <li>3 · Computing the severity scorecard</li>
        <li>4 · Comparing it with the stress trigger</li>
      </ol>
    </section>
  );
}

/** The result when a risk assessment exists: the chain on top, then what the text means, how serious it is and why, and what happens at the trigger. */
function AssessedResult({ r, threshold }: { r: AnalyzeResponse; threshold: number }) {
  const { data: meta } = useMeta();
  const label = categoryLabeler(meta);
  const scenarios = useScenarios();
  const s = r.signal as SignalSummary;
  const a = r.assessment!;
  const rel = useSignalRelevance(s.id);
  const sev = a.severity;
  const scenarioName = s.assessed_category
    ? scenarios.data?.scenarios.find((x) => x.id === scenarios.data?.default_by_category[s.assessed_category as keyof typeof scenarios.data.default_by_category])?.name
    : undefined;
  return (
    <section className="space-y-6" aria-label="Assessment result" aria-live="polite">
      <div className="card p-5">
        <div className="flex flex-wrap items-center gap-2">
          <ModeChip a={a} />
          <ScopeTag level={s.scope_level as ScopeLevel} sector={s.scope_sector} strength={s.scope_strength} />
          <span className="text-xs text-muted">{OUTCOME_WORD[r.outcome] ?? r.outcome}</span>
        </div>
        <h2 className="mt-3 font-display text-xl font-semibold leading-snug">{r.headline}</h2>
        <div className="mt-5">
          <MiniChain
            s={s}
            threshold={threshold}
            label={label}
            scenarioName={scenarioName}
            portfolioText={rel.data ? (rel.data.share != null ? `${(rel.data.share * 100).toFixed(0)}% of the book reached` : rel.data.summary) : undefined}
          />
        </div>
        {r.notes.length > 0 && (
          <ul className="mt-5 space-y-1 border-t border-rule pt-4 text-sm text-muted">
            {r.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        )}
      </div>

      <div className="card p-5">
        <p className="eyebrow">AI understanding</p>
        <div className="mt-3">
          <UnderstandingCard a={a} />
        </div>
      </div>

      <div className="card p-5">
        <p className="eyebrow">Risk signal</p>
        {sev ? (
          <div className="mt-3 space-y-4">
            <p className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <span className="num text-4xl font-semibold">{sev.score}</span>
              <span className="text-lg text-muted">/ 10 · {sev.band_label.toLowerCase()}</span>
              <OriginChip origin={sev.rubric.some((r) => r.origin === "HYBRID") ? "HYBRID" : "RULES"} />
            </p>
            <ScaleBar score={sev.score} />
            <p className="max-w-[70ch] text-sm text-ink-2">{severityLede(sev)}</p>
            <ul className="flex flex-wrap gap-1.5" aria-label="The four answers behind the score">
              {sev.rubric.map((f) => (
                <li key={f.id} className="tag" title={f.final_says}>
                  <span className="text-muted">{f.label}:</span> {f.final_label}
                </li>
              ))}
            </ul>
            <MarketNote m={sev.market} />
            <details className="disclosure">
              <summary>How the score is built</summary>
              <div className="mt-3">
                <ScoreBuildUp steps={sev.steps} score={sev.score} points={sev.points} />
              </div>
            </details>
            <ThresholdNotice score={sev.score} threshold={threshold} signalId={s.id} />
          </div>
        ) : (
          <div className="mt-3">
            <ThresholdNotice score={null} threshold={threshold} />
            <p className="mt-2 text-sm text-muted">{a.severity_note}</p>
          </div>
        )}
        {a.conflict && <p className="mt-3 text-sm text-warn">{a.conflict.note}</p>}
      </div>

      {r.intelligence && <IntelligenceSummary i={r.intelligence} />}
      <ReferencePanel a={a} />
      <div className="flex flex-wrap items-center gap-3">
        <Link className="btn btn-primary" to={`/events/${s.id}`}>
          Open the full analysis <ArrowRight size={14} />
        </Link>
      </div>
    </section>
  );
}

function Result({ r, threshold }: { r: AnalyzeResponse; threshold: number }) {
  const { data: meta } = useMeta();
  const label = categoryLabeler(meta);
  const s: SignalSummary | null = r.signal;
  const rel = useSignalRelevance(s?.id);
  if (r.outcome === "QUARANTINED" || !s) {
    return (
      <StateNotice
        tone="warn"
        what="This text could not be analysed"
        why={`${r.rejection?.detail ?? "It could not be scored."} EventShock rejects text it cannot score instead of guessing a value.`}
        details={<span className="num text-xs text-muted">{r.rejection?.code}</span>}
        next={<span className="text-sm text-muted">Try a full headline or a sentence of the story.</span>}
      />
    );
  }
  if (r.assessment) return <AssessedResult r={r} threshold={threshold} />;
  const triggers = (s.impact_score ?? 0) >= threshold;
  const kind = s.impact_score === null ? undefined : summaryKind(s);
  return (
    <section className="card p-5" aria-label="Analysis result" aria-live="polite">
      <div className="flex flex-wrap items-center gap-2">
        <ScopeTag level={s.scope_level as ScopeLevel} sector={s.scope_sector} strength={s.scope_strength} />
        <EventStatusTag status={s.event_status} category={s.category} label={label} />
        <span className="text-xs text-muted">{OUTCOME_WORD[r.outcome] ?? r.outcome}</span>
      </div>
      <h2 className="mt-3 font-display text-xl font-semibold leading-snug">{r.headline}</h2>

      <div className="mt-5 grid gap-x-8 gap-y-6 sm:grid-cols-2 xl:grid-cols-4">
        <Reading title="About">
          <p className="reading-value">
            {subjectLine(subjectOfSummary(s))}
          </p>
          {s.scope_themes.length > 0 && <p className="mt-1 text-sm text-muted">{s.scope_themes.map(THEME_LABEL).join(", ")}</p>}
        </Reading>
        <Reading title="Tone">
          <p className="mt-1">
            <SentimentBar score={s.sentiment_score} wide />
          </p>
        </Reading>
        <Reading title="Impact">
          <div className="mt-1">
            <ImpactMeter
              score={s.impact_score}
              kind={kind}
              showKind
              range={s.impact_score_low != null && s.impact_score_high != null ? [s.impact_score_low, s.impact_score_high] : null}
            />
          </div>
          {s.impact_score === null && (
            <p className="mt-1 text-sm text-muted">
              {s.event_status === "NO_EVENT" ? "Not a market event, so no impact is scored." : "The event type is uncertain, so no impact is scored."}
            </p>
          )}
        </Reading>
        <Reading title="Portfolio">
          <p className="mt-1">
            <RelevanceTag level={s.relevance_level} share={s.relevance_share} />
          </p>
          {rel.data && <p className="mt-2 text-sm text-ink-2">{rel.data.summary}</p>}
        </Reading>
      </div>

      {r.notes.length > 0 && (
        <ul className="mt-5 space-y-1 border-t border-rule pt-4 text-sm text-muted">
          {r.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}

      <div className="mt-5 flex flex-wrap items-center gap-3">
        <Link className="btn btn-primary" to={`/events/${s.id}`}>
          Open the full analysis <ArrowRight size={14} />
        </Link>
        {s.impact_score !== null && (
          <Link className="btn" to={`/stress?signal=${s.id}${triggers ? "&run=1" : ""}`}>
            {triggers ? "Run the scenario" : "Run as a what-if"}
          </Link>
        )}
      </div>
    </section>
  );
}

export function AnalyzePage() {
  const { data: meta } = useMeta();
  const [text, setText] = useState("");
  const [source, setSource] = useState<"NEWS" | "SOCIAL">("NEWS");
  const [when, setWhen] = useState("");
  const [from, setFrom] = useState("");
  const [head, setHead] = useState("");
  const [url, setUrl] = useState("");
  const analyze = useAnalyze();
  const llm = meta?.capabilities.llm;
  const available = meta?.capabilities.analyze ?? true;

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!text.trim()) return;
    analyze.mutate({ text, source_type: source, published_at: when ? new Date(when).toISOString() : undefined, source: from.trim() || undefined, headline: head.trim() || undefined, url: url.trim() || undefined });
  };

  return (
    <>
      <PageHeader
        title="Analyze"
        sub="Paste a headline, a post, or the opening of an article. EventShock reads it, says what it is about, how serious it may be and why, whether that crosses the stress trigger, and what it means for the portfolio."
      />
      {!available && (
        <StateNotice
          tone="warn"
          what="Analysis is not available in this profile"
          why="Analysis runs the trained models, which the demo profile does not load. Start the default (replay) profile."
        />
      )}
      <form onSubmit={submit} className="card mb-6 p-5">
        <label className="block">
          <span className="eyebrow">Text to analyse</span>
          <textarea
            className="field mt-2 min-h-32 resize-y"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="e.g. Regulators open an investigation into a bank over money laundering"
            maxLength={20000}
            disabled={!available}
          />
        </label>
        <div className="mt-3 flex flex-wrap items-center gap-2" role="group" aria-label="Try an example">
          <span className="text-sm text-muted">Try:</span>
          {EXAMPLES.map((ex) => (
            <button key={ex.id} type="button" className="chip" onClick={() => setText(ex.text)}>
              {ex.label}
            </button>
          ))}
        </div>
        <details className="disclosure mt-2">
          <summary>More examples: one per event class</summary>
          <div className="mt-2 flex flex-wrap items-center gap-2" role="group" aria-label="More examples">
            {MORE_EXAMPLES.map((ex) => (
              <button key={ex.id} type="button" className="chip" onClick={() => setText(ex.text)}>
                {ex.label}
              </button>
            ))}
          </div>
        </details>
        <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-3">
          <div className="flex items-center gap-1.5" role="group" aria-label="What kind of text">
            {(
              [
                ["NEWS", "News"],
                ["SOCIAL", "Social post"],
              ] as const
            ).map(([v, l]) => (
              <button key={v} type="button" className="chip" aria-pressed={source === v} onClick={() => setSource(v)}>
                {l}
              </button>
            ))}
          </div>
          <details className="disclosure">
            <summary>Set where and when it was published</summary>
            <label className="mt-2 flex items-center gap-2 text-sm text-muted">
              Source
              <input className="field !w-auto" type="text" maxLength={80} placeholder="e.g. Reuters, @analyst" value={from} onChange={(e) => setFrom(e.target.value)} />
            </label>
            <label className="mt-2 flex items-center gap-2 text-sm text-muted">
              Published
              <input className="field !w-auto" type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} />
            </label>
            <p className="mt-1 max-w-[46ch] text-xs text-muted">
              Left empty, the time you paste it is used. A time you set is taken at your word and marked as such.
            </p>
          </details>
          <details className="disclosure">
            <summary>Add a headline or a link</summary>
            <label className="mt-2 flex items-center gap-2 text-sm text-muted">
              Headline
              <input className="field !w-auto min-w-0 flex-1" type="text" maxLength={240} placeholder="optional: the text above is then read as the article body" value={head} onChange={(e) => setHead(e.target.value)} />
            </label>
            <label className="mt-2 flex items-center gap-2 text-sm text-muted">
              Link
              <input className="field !w-auto min-w-0 flex-1" type="url" maxLength={2048} placeholder="https://… (used to credit the outlet; never fetched)" value={url} onChange={(e) => setUrl(e.target.value)} />
            </label>
          </details>
          <button type="submit" className="btn btn-primary ml-auto" disabled={!available || !text.trim() || analyze.isPending}>
            {analyze.isPending ? <Spinner size={14} /> : null} Analyze
          </button>
        </div>
      </form>

      {analyze.error && (
        <StateNotice tone="neg" what="The request failed" why={analyze.error.message} next={<button className="btn" onClick={() => analyze.reset()}>Dismiss</button>} />
      )}
      {analyze.isPending && <Working llm={llm?.mode === "LLM"} />}
      {analyze.data && !analyze.isPending && <Result r={analyze.data} threshold={meta?.trigger_threshold ?? 7} />}
      {!analyze.data && !analyze.error && !analyze.isPending && (
        <div className="max-w-[66ch] space-y-2 text-sm text-muted">
          {llm ? (
            <p>
              <span className="mr-2 inline-block align-middle">
                <ModeChip llm={llm} />
              </span>
              {llm.mode === "LLM"
                ? `The text is sent to the language model (${llm.model}) to be read. Nothing else leaves this server, and the same text is never sent twice (answers are cached on this machine).`
                : "Nothing leaves this server: the text is read by deterministic rules. Set an API key and EVENTSHOCK_LLM=1 to have a language model read it instead."}
            </p>
          ) : (
            <p>Nothing leaves this server.</p>
          )}
          <p>
            A pasted text becomes an ordinary signal: it appears on the Desk as “Pasted”, joins a story if the same one is already there, and can be stress-tested like any other. Long
            articles are read by their opening 2,000 characters, because the models were fitted on headlines and short posts.
          </p>
        </div>
      )}
    </>
  );
}
