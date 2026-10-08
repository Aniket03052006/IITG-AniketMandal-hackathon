import clsx from "clsx";
import { Link } from "react-router-dom";
import type { RiskAssessment, RiskSignal } from "../../api/types";
import { dateTime } from "../../lib/format";
import { impactKind } from "../../lib/impact";
import { stageKind } from "../../lib/provenance";
import { sentimentLabel, severityBand } from "../../lib/severity";
import { signed as signedScore } from "../../lib/assessment";
import { useIntelligence, useMeta } from "../../api/hooks";
import { money, pct } from "../../lib/format";
import { ArrowRight, STATION_ICON, type Station } from "../icons";

const STATION_OF: Record<number, Station> = { 1: "source", 2: "reading", 3: "severity", 4: "scenario", 5: "portfolio" };

const INPUT_CHIPS = ["Event type", "Sentiment", "Calendar", "Market state", "Timing"];

function Node({ i, n, title, to, onGo, children }: { i: number; n: number; title: string; to?: string; onGo?: () => void; children: React.ReactNode }) {
  const I = STATION_ICON[STATION_OF[n] ?? "source"];
  const head = (
    <span className="chain-head">
      <span className={clsx("chain-n", n === 4 && "chain-n-dashed")} aria-hidden="true">
        <I size={15} />
      </span>
      <span>
        <span className="num text-muted">{n} · </span>
        {title}
      </span>
    </span>
  );
  return (
    <li className="chain-node" style={{ ["--i" as string]: i }}>
      {onGo ? (
        <button type="button" className="chain-link" onClick={onGo}>
          {head}
        </button>
      ) : to ? (
        <Link className="chain-link" to={to}>
          {head}
        </Link>
      ) : (
        head
      )}
      <div className="chain-body">{children}</div>
    </li>
  );
}

/** The intelligence endpoint's stress preview, when it ran: the before/after the chain ends in, without starting a run from here. */
function PortfolioPreview({ id }: { id: string }) {
  const { data: meta } = useMeta();
  const q = useIntelligence(id, meta?.capabilities.intelligence === true);
  const st = q.data?.stress;
  if (!st || st.availability !== "AVAILABLE" || st.pnl == null || st.baseline_value == null || st.stressed_value == null) return null;
  return (
    <>
      <p className="chain-sub num">
        {money(st.baseline_value)} → {money(st.stressed_value)}
      </p>
      <p className={clsx("chain-result num", st.pnl < 0 ? "text-neg" : "text-ink")}>{money(st.pnl, { signed: true })}</p>
      {st.pnl_pct != null && <p className="chain-sub num">{pct(st.pnl_pct, 2, true)} of the book</p>}
    </>
  );
}

/**
 * The EventShock chain drawn once, in the page itself: text -> NLP reading (event type and sentiment) -> impact model -> scenario -> portfolio.
 * Event type and sentiment are drawn as readings of the TEXT and, separately, as two of several inputs the impact model reads. No arrow runs
 * from sentiment to the score, and the note under it says what our evaluation found about which inputs carry the skill.
 */
export function ChainGraphic({
  s,
  label,
  scenarioName,
  triggers,
  threshold,
  onGo,
  a,
}: {
  s: RiskSignal;
  label: (c: string) => string;
  scenarioName?: string;
  triggers: boolean;
  threshold: number;
  onGo: (stage: "understand" | "impact") => void;
  a?: RiskAssessment;
}) {
  if (a) return <AssessedChain s={s} a={a} label={label} scenarioName={scenarioName} threshold={threshold} onGo={onGo} />;
  const ev = s.event;
  const audit = s.provenance?.event;
  const isEventModel = stageKind(s.provenance?.stage_origins.event) === "model";
  const sentModel = stageKind(s.provenance?.stage_origins.sentiment) === "model";
  const impact = s.impact;
  const band = impact ? severityBand(impact.score) : null;
  const kind = impactKind(s);
  const score = s.sentiment.score;
  const eventText =
    ev.status === "CLASSIFIED" ? label(ev.category) : ev.status === "NO_EVENT" ? "Not a market event" : "Type uncertain";
  return (
    <div className="chain-wrap">
      <ol className="chain" aria-label="How EventShock got from this text to a portfolio result">
        <Node i={0} n={1} title="Report">
          <p className="chain-main">{s.document.source}</p>
          <p className="chain-sub num">{dateTime(s.document.published_at)}</p>
          <p className="chain-sub">{s.document.body ? "Full text" : "Headline only"}</p>
        </Node>
        <Node i={1} n={2} title="NLP reads the text" onGo={() => onGo("understand")}>
          <div className="chain-reading">
            <p className="chain-k">Event type</p>
            <p className="chain-main">{eventText}</p>
            {ev.status === "CLASSIFIED" && audit && <p className="chain-sub num">{Math.round(audit.confidence * 100)}% confident</p>}
          </div>
          <div className="chain-reading">
            <p className="chain-k">Sentiment</p>
            <p className="chain-main">
              {sentimentLabel(score)} <span className="num text-muted">{score > 0 ? "+" : score < 0 ? "−" : ""}{Math.abs(score).toFixed(2)}</span>
            </p>
          </div>
          <p className="chain-sub">{isEventModel && sentModel ? "Trained text models" : "Includes placeholder rules"}</p>
        </Node>
        <Node i={2} n={3} title="Impact estimate" onGo={() => onGo("impact")}>
          <p className="chain-k">reads, among others</p>
          <ul className="chain-chips">
            {INPUT_CHIPS.map((c) => (
              <li key={c} className={clsx("chain-chip", (c === "Event type" || c === "Sentiment") && "chain-chip-text")}>
                {c}
              </li>
            ))}
          </ul>
          {impact && band ? (
            <p className={clsx("chain-result num", band.text)}>
              {impact.score}
              <span className="text-base text-muted"> / 10</span>
            </p>
          ) : (
            <p className="chain-sub">Not scored</p>
          )}
          <p className="chain-sub">{kind === "placeholder" ? "Placeholder rule" : kind === "validated" ? "Validated model" : "Experimental model"}</p>
        </Node>
        <Node i={3} n={4} title="Scenario">
          <p className="chain-main">{scenarioName ?? "No scenario mapped"}</p>
          <p className="chain-sub">
            {impact ? (triggers ? `Triggered: impact ≥ ${threshold}` : `Below the trigger (≥ ${threshold}); runs as a what-if`) : "Needs an impact score"}
          </p>
          <p className="chain-sub">Assumptions, scaled by impact</p>
        </Node>
        <Node i={4} n={5} title="Portfolio stress">
          <p className="chain-main">Value before vs after</p>
          <p className="chain-sub">Deterministic engine</p>
          {impact && (
            <Link className="btn btn-sm mt-2" to={`/stress?signal=${s.id}${triggers ? "&run=1" : ""}`}>
              Run scenario <ArrowRight size={13} />
            </Link>
          )}
        </Node>
      </ol>
      <p className="chain-note">
        Sentiment is tone, not impact. In the trained reaction model's own evaluation, the calendar and market state carried its measurable skill and its text-model
        inputs added none: that is a finding about that model, not about the news.
      </p>
    </div>
  );
}


/**
 * The chain when a risk assessment exists: news -> AI understanding -> risk signal -> scenario -> portfolio impact. The risk-signal step lists
 * only the factors that actually entered the score (with their weights), so nothing is drawn as an input that is not one.
 */
function AssessedChain({
  s,
  a,
  label,
  scenarioName,
  threshold,
  onGo,
}: {
  s: RiskSignal;
  a: RiskAssessment;
  label: (c: string) => string;
  scenarioName?: string;
  threshold: number;
  onGo: (stage: "understand" | "impact") => void;
}) {
  const r = a.reading;
  const sev = a.severity;
  const band = sev ? severityBand(sev.score) : null;
  const crosses = !!sev && sev.score >= threshold;
  const eventText = r.event_type === "NO_EVENT" ? "Not a market event" : label(r.event_type);
  const toneWord = r.sentiment_label[0]!.toUpperCase() + r.sentiment_label.slice(1);
  return (
    <div className="chain-wrap">
      <ol className="chain" aria-label="How EventShock got from this text to a portfolio result">
        <Node i={0} n={1} title="News">
          <p className="chain-main">{s.document.source}</p>
          <p className="chain-sub num">{dateTime(s.document.published_at)}</p>
          <p className="chain-sub">{s.document.body ? "Full text" : "Headline only"}</p>
        </Node>
        <Node i={1} n={2} title="AI understanding" onGo={() => onGo("understand")}>
          <div className="chain-reading">
            <p className="chain-k">Event</p>
            <p className="chain-main">{eventText}</p>
            {r.event_confidence != null && <p className="chain-sub num">{Math.round(r.event_confidence * 100)}% confident</p>}
          </div>
          <div className="chain-reading">
            <p className="chain-k">Tone</p>
            <p className="chain-main">
              {toneWord} <span className="num text-muted">{signedScore(r.sentiment)}</span>
            </p>
          </div>
          <p className="chain-sub">{a.extraction.mode === "LLM" ? "AI-assisted reading, checked against the text" : "Rule-based reading"}</p>
        </Node>
        <Node i={2} n={3} title="Risk signal" onGo={() => onGo("impact")}>
          {sev && band ? (
            <>
              <p className="chain-k">four answers + data</p>
              <ul className="chain-chips">
                {sev.rubric.map((f) => (
                  <li key={f.id} className="chain-chip">
                    {f.final_label}
                  </li>
                ))}
              </ul>
              <p className={clsx("chain-result num", band.text)}>
                {sev.score}
                <span className="text-base text-muted"> / 10</span>
              </p>
              <p className="chain-sub">
                {sev.band_label} · scorecard, not validated
              </p>
            </>
          ) : (
            <p className="chain-sub">Not scored: not a market event</p>
          )}
        </Node>
        <Node i={3} n={4} title="Scenario">
          <p className="chain-main">{sev ? (scenarioName ?? "No scenario mapped") : "None"}</p>
          <p className="chain-sub">
            {sev ? (crosses ? `Suggested: severity ≥ ${threshold}` : `Below the trigger (≥ ${threshold}); runs as a what-if`) : "Needs a severity score"}
          </p>
          <p className="chain-sub">Assumptions, scaled by severity</p>
        </Node>
        <Node i={4} n={5} title="Portfolio impact">
          <p className="chain-main">Value before vs after</p>
          <PortfolioPreview id={s.id} />
          <p className="chain-sub">Deterministic engine</p>
          {sev && (
            <Link className="btn btn-sm mt-2" to={`/stress?signal=${s.id}${crosses ? "&run=1" : ""}`}>
              {crosses ? "Run scenario" : "Run as what-if"} <ArrowRight size={13} />
            </Link>
          )}
        </Node>
      </ol>
      <p className="chain-note">
        Tone and confidence are not inputs: severity is the event's own scale. The trained market-reaction model is kept as a reference and does not drive the trigger.
      </p>
    </div>
  );
}
