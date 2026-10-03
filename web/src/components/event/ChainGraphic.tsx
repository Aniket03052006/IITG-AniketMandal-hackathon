import clsx from "clsx";
import { Link } from "react-router-dom";
import type { RiskSignal } from "../../api/types";
import { dateTime } from "../../lib/format";
import { impactKind } from "../../lib/impact";
import { stageKind } from "../../lib/provenance";
import { sentimentLabel, severityBand } from "../../lib/severity";
import { ArrowRight } from "../icons";

const INPUT_CHIPS = ["Event type", "Sentiment", "Calendar", "Market state", "Timing"];

function Node({ i, n, title, to, onGo, children }: { i: number; n: number; title: string; to?: string; onGo?: () => void; children: React.ReactNode }) {
  const head = (
    <span className="chain-head">
      <span className="chain-n num">{n}</span>
      {title}
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
}: {
  s: RiskSignal;
  label: (c: string) => string;
  scenarioName?: string;
  triggers: boolean;
  threshold: number;
  onGo: (stage: "understand" | "impact") => void;
}) {
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
        Sentiment is tone, not impact. The impact estimate reads it next to event-time calendar and market state; in our evaluation the calendar and
        market state carry the measurable skill, and the text models' outputs add none.
      </p>
    </div>
  );
}
