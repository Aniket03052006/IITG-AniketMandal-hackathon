import clsx from "clsx";
import { Link } from "react-router-dom";
import { useEventModel } from "../../api/hooks";
import type { EventAudit, EventCategory, RiskAssessment, RiskSignal } from "../../api/types";
import { EVENT_CATEGORIES } from "../../api/types";
import { dateTime } from "../../lib/format";
import { stageKind, stageKindText } from "../../lib/provenance";
import { sentimentLabel } from "../../lib/severity";
import { Check } from "../icons";
import { ScopeCard } from "../scope/ScopeCard";
import { StateNotice } from "../StateNotice";
import { StatusTag } from "../ui";
import { Chapter } from "./Chapter";
import { UnderstandingCard } from "../assessment/UnderstandingCard";
import { ExplainBar, NLP } from "./ExplainBar";

const pc = (p: number) => `${Math.round(p * 100)}%`;
const signedScore = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(2)}`;

function EventReading({ s, label }: { s: RiskSignal; label: (c: string) => string }) {
  const audit = s.provenance?.event;
  const isModel = stageKind(s.provenance?.stage_origins.event) === "model" && !!audit;
  const { data: card } = useEventModel(isModel);
  const commit = card?.abstention.commit_threshold;
  const ev = s.event;
  const lean = EVENT_CATEGORIES.map((c) => ({ c, p: ev.probabilities[c as EventCategory] ?? 0 })).sort((a, b) => b.p - a.p);
  const rows = ev.status === "NO_EVENT" ? [] : lean.slice(0, 3);
  const conf = audit?.confidence ?? 0;
  return (
    <div className="reading">
      <p className="eyebrow">Event type</p>
      {ev.status === "CLASSIFIED" && (
        <>
          <p className="reading-value">{label(ev.category)}</p>
          {audit && (
            <>
              <div className="meter" role="img" aria-label={`Calibrated confidence ${pc(conf)}${commit != null ? `, the model commits at ${pc(commit)} or more` : ""}`}>
                <span className="meter-fill bar-grow" style={{ width: pc(conf) }} />
                {commit != null && <span className="meter-tick" style={{ left: pc(commit) }} />}
              </div>
              <p className="mt-1 text-xs text-muted">
                {pc(conf)} calibrated confidence{commit != null ? ` · commits at ${pc(commit)} or more` : ""}
              </p>
            </>
          )}
        </>
      )}
      {ev.status === "NO_EVENT" && (
        <>
          <p className="reading-value text-ink-2">Not a market event</p>
          <p className="mt-1 text-sm text-muted">
            EventShock judged this text {audit ? `${pc(audit.no_event_probability)} ` : ""}likely not to describe a market event, so it scores no impact.
          </p>
        </>
      )}
      {ev.status === "UNCERTAIN" && (
        <>
          <p className="reading-value text-warn">Type uncertain</p>
          <p className="mt-1 text-sm text-muted">The model will not commit to a type here. It abstains rather than guess.</p>
        </>
      )}
      {rows.length > 0 && (
        <ul className="mt-3 space-y-1.5" aria-label={ev.status === "CLASSIFIED" ? "Most likely types" : "If this were an event, the model's lean"}>
          {ev.status !== "CLASSIFIED" && <li className="text-xs text-muted">If it were an event, the model's lean (a share among event types, not a finding):</li>}
          {rows.map(({ c, p }, i) => (
            <li key={c} className="grid grid-cols-[minmax(0,1fr)_4rem_2.5rem] items-center gap-3 text-sm">
              <span className={clsx(i === 0 ? "text-ink" : "text-muted")}>{label(c)}</span>
              <span className="h-1.5 rounded-sm bg-paper-4" aria-hidden="true">
                <span className={clsx("block h-full rounded-sm bar-grow", i === 0 && ev.status === "CLASSIFIED" ? "bg-accent" : "bg-faint")} style={{ width: pc(p) }} />
              </span>
              <span className="num text-right text-xs text-muted">{pc(p)}</span>
            </li>
          ))}
        </ul>
      )}
      {audit?.unreliable_class && (
        <p className="mt-3 text-sm text-warn">This event type is one the model does not assert; a lean towards it is shown as uncertain.</p>
      )}
      {audit?.seen_in_training && (
        <p className="mt-3 text-sm text-warn">In-sample: the model trained on this exact text, so its output here is not evidence of accuracy.</p>
      )}
    </div>
  );
}

function SentimentReading({ s }: { s: RiskSignal }) {
  const { score, positive, negative, neutral } = s.sentiment;
  const audit = s.provenance?.sentiment;
  const at = ((Math.max(-1, Math.min(1, score)) + 1) / 2) * 100;
  const tone = score < -0.15 ? "text-neg" : score > 0.15 ? "text-pos" : "text-ink-2";
  return (
    <div className="reading">
      <p className="eyebrow">Sentiment</p>
      <p className="reading-value">
        <span className={tone}>{sentimentLabel(score)}</span> <span className={clsx("num text-xl", tone)}>{signedScore(score)}</span>
      </p>
      <div
        className="gauge mt-3"
        role="img"
        aria-label={`Sentiment ${signedScore(score)}, ${sentimentLabel(score).toLowerCase()}: ${pc(negative)} negative, ${pc(neutral)} neutral, ${pc(positive)} positive`}
      >
        <span className="gauge-neg" />
        <span className="gauge-neu" />
        <span className="gauge-pos" />
        <span className="gauge-marker" style={{ left: `${at}%` }} />
      </div>
      <div className="mt-1 flex justify-between text-2xs text-muted" aria-hidden="true">
        <span>Negative</span>
        <span>Neutral</span>
        <span>Positive</span>
      </div>
      <p className="mt-3 text-sm text-muted">
        Tone of the wording, from −1 to +1{audit ? ` (${pc(audit.confidence)} confident in its top class)` : ""}. Tone is not impact: a calm regulatory notice can matter more than a loud opinion.
      </p>
      {audit?.seen_in_training && <p className="mt-2 text-sm text-warn">In-sample: this text is in the data the model learned from.</p>}
    </div>
  );
}

function TrainedReadings({ s, label, evModel, audit, hybrid }: { s: RiskSignal; label: (c: string) => string; evModel: boolean; audit: EventAudit | null | undefined; hybrid: boolean }) {
  return (
    <div className="understand">
        <div className="understand-in">
          <p className="eyebrow">Input text</p>
          <blockquote className="quote">{s.document.headline}</blockquote>
          <p className="mt-2 text-xs text-muted">
            {s.document.source} · <span className="num">{dateTime(s.document.published_at)}</span>
            {s.document.body ? "" : " · headline only: this source supplies no article text"}
          </p>
          {s.document.body && <p className="mt-3 text-sm leading-relaxed text-ink-2">{s.document.body}</p>}
          {evModel && audit && (
            <p className="mt-4 text-xs text-muted">
              Read by <span className="num text-ink-2">{audit.model_id}</span>
              {hybrid ? ": word statistics plus semantic text embeddings (multilingual-e5-large) feed one calibrated classifier. The embeddings carry the meaning of the sentence; they are not shown, and are not claimed to explain any single answer." : "."}
              {s.provenance?.sentiment ? <> Tone by <span className="num text-ink-2">{s.provenance.sentiment.model_id}</span>.</> : null}
            </p>
          )}
        </div>
        <div className="understand-arrow" aria-hidden="true" />
        <div className="understand-out">
          <ScopeCard s={s} />
          <EventReading s={s} label={label} />
          <SentimentReading s={s} />
        </div>
    </div>
  );
}

/** Chapter 2: NLP as a real analytical stage: the text goes in, an event type and a sentiment come out. */
export function UnderstandChapter({ s, label, a }: { s: RiskSignal; label: (c: string) => string; a?: RiskAssessment }) {
  const audit = s.provenance?.event;
  const evModel = stageKind(s.provenance?.stage_origins.event) === "model" && !!audit;
  const hybrid = audit?.model_id.startsWith("hybrid");
  return (
    <Chapter
      id="understand"
      eyebrow="Understand"
      title="What the text says"
      lede={
        a ? (
          a.summary
        ) : (
        <>
          EventShock interpreted this text as{" "}
          {s.event.status === "CLASSIFIED" ? <strong className="font-medium text-ink">{label(s.event.category)}</strong> : s.event.status === "NO_EVENT" ? "not a market event" : "an event whose type it cannot settle"}
          , with {sentimentLabel(s.sentiment.score).toLowerCase()} tone.
        </>
        )
      }
      badge={
        evModel ? (
          <StatusTag tone="ok" icon={<Check size={12} />}>
            Trained text models
          </StatusTag>
        ) : (
          <StatusTag tone="warn">{stageKindText(s.provenance?.stage_origins.event)}</StatusTag>
        )
      }
    >
      {a && <UnderstandingCard a={a} />}
      {a && (
        <details className="disclosure mt-6">
          <summary>The trained models' own readings, for comparison</summary>
          <div className="mt-4">
            <TrainedReadings s={s} label={label} evModel={evModel} audit={audit} hybrid={!!hybrid} />
          </div>
        </details>
      )}
      {!a && <TrainedReadings s={s} label={label} evModel={evModel} audit={audit} hybrid={!!hybrid} />}
      {(a ? !a.severity : s.event.status !== "CLASSIFIED") && (
        <div className="mt-5 max-w-[64ch]">
          <StateNotice
            tone="info"
            what={a ? "No severity will be scored" : s.event.status === "NO_EVENT" ? "No impact will be scored" : "No impact will be scored while the type is uncertain"}
            why="EventShock abstains instead of guessing: a score built on a guessed event type would look more certain than it is."
            next={<Link className="btn" to="/?min=7">{a ? "Browse high-severity events" : "Browse high-impact events"}</Link>}
          />
        </div>
      )}
      {a && s.event.status !== "CLASSIFIED" && !!a.severity && (
        <div className="mt-5 max-w-[64ch]">
          <StateNotice
            tone="info"
            what="The trained event model abstained; the assessment still read the text"
            why={`The trained model judged this ${s.event.status === "NO_EVENT" ? "probably not a market event" : "an event whose type it could not settle"}. The reading above comes from the text's own cue phrases and is checked against it; its confidence is stated, and a trained model's probability is not claimed.`}
          />
        </div>
      )}
      <div className="mt-5">
        <ExplainBar items={[NLP]} />
      </div>
    </Chapter>
  );
}
