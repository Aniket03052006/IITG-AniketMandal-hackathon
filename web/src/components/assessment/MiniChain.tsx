import clsx from "clsx";
import type { SignalSummary } from "../../api/types";
import { dateTime } from "../../lib/format";
import { sentimentLabel } from "../../lib/severity";
import { signed } from "../../lib/assessment";
import { STATION_ICON, type Station } from "../icons";

const STATIONS: Station[] = ["source", "reading", "severity", "scenario", "portfolio"];

/** The whole product in five steps, drawn small: news -> AI understanding -> risk signal -> scenario -> portfolio impact. Each step says what it holds, or that it is not reached. */
export function MiniChain({
  s,
  threshold,
  scenarioName,
  portfolioText,
  label,
}: {
  s: SignalSummary;
  threshold: number;
  scenarioName?: string;
  portfolioText?: string;
  label: (c: string) => string;
}) {
  const scored = s.severity_score != null;
  const above = scored && (s.severity_score ?? 0) >= threshold;
  const steps = [
    { k: "News", v: s.source, sub: dateTime(s.published_at), on: true },
    {
      k: "AI understanding",
      v: s.assessed_category && s.assessed_category !== "NO_EVENT" ? label(s.assessed_category) : "Not a market event",
      sub: `${sentimentLabel(s.sentiment_score).toLowerCase()} ${signed(s.sentiment_score)} · ${s.extraction_mode === "LLM" ? "AI-assisted" : "rule-based"}`,
      on: true,
    },
    {
      k: "Risk signal",
      v: scored ? `Severity ${s.severity_score}/10` : "Not scored",
      sub: scored ? (above ? `above the trigger (${threshold})` : `below the trigger (${threshold})`) : "nothing is invented",
      on: scored,
    },
    {
      k: "Scenario",
      v: scored ? (scenarioName ?? "No scenario mapped") : "None",
      sub: scored ? (above ? "suggested, can run now" : "runs only as a what-if") : "needs a severity score",
      on: above,
    },
    {
      k: "Portfolio impact",
      v: portfolioText ?? "Value before vs after",
      sub: above ? "deterministic engine" : "run it to see",
      on: above,
    },
  ];
  return (
    <ol className="mini-chain" aria-label="How EventShock got from this text to a portfolio result">
      {steps.map((st, i) => (
        <li key={st.k} className="mini-step" data-state={st.on ? "on" : "off"}>
          <MiniNode station={STATIONS[i]!} />
          <p className="mini-step-k">
            <span className="num">{i + 1}</span> · {st.k}
          </p>
          <p className={clsx("mini-step-v", !st.on && "text-ink-2")}>{st.v}</p>
          <p className="mini-step-s">{st.sub}</p>
        </li>
      ))}
    </ol>
  );
}

function MiniNode({ station }: { station: Station }) {
  const I = STATION_ICON[station];
  return (
    <span className="mini-node" aria-hidden="true">
      <I size={13} />
    </span>
  );
}
