import clsx from "clsx";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useAssessment, useIntelligence, useMeta, usePropagation, useScenarios, useSignal, useSignalRelevance } from "../../api/hooks";
import type { EventCategory, RiskFactor, Scenario } from "../../api/types";
import { ASSET_CLASS_LABEL, dateTime, money, pct, shockValue, SCOPE_LABEL } from "../../lib/format";
import { impactKind, KIND_LABEL } from "../../lib/impact";
import { useTween } from "../../lib/motion";
import { sentimentLabel, severityBand } from "../../lib/severity";
import { categoryLabeler } from "../../lib/taxonomy";
import { CategoryGlyph, Glyph } from "../Glyph";
import { ASSET_ICON, FACTOR_ICON, STATION_ICON, type Station as StationId } from "../icons";
import { Skeleton } from "../ui";

const STATION_TITLE: Record<StationId, string> = {
  source: "What happened",
  reading: "What the AI read",
  severity: "How severe",
  scenario: "Scenario it triggers",
  exposure: "What it reaches",
  portfolio: "Portfolio impact",
};

/** One stop on the wire: its icon sits on the connector, its title says the question it answers, one action goes deeper. */
function Station({
  id,
  n,
  tone = "wire",
  action,
  children,
}: {
  id: StationId;
  n: number;
  tone?: "wire" | "dashed" | "sev-high" | "sev-crit" | "sev-mod" | "sev-low" | "neg" | "off";
  action?: { to: string; label: string };
  children: ReactNode;
}) {
  const I = STATION_ICON[id];
  return (
    <li className="station" data-station={id} style={{ ["--i" as string]: n - 1 }}>
      <span className={clsx("station-node", `station-node-${tone}`)} aria-hidden="true">
        <I size={16} />
      </span>
      <span className="station-title">
        <span className="num">{n}</span> {STATION_TITLE[id]}
      </span>
      <div className="station-body">{children}</div>
      {action && (
        <Link className="station-action" to={action.to}>
          {action.label}
        </Link>
      )}
    </li>
  );
}

function Missing({ children }: { children: ReactNode }) {
  return <p className="station-missing">{children}</p>;
}

function Delta({ value, pctValue }: { value: number; pctValue: number | null }) {
  const v = useTween(value);
  return (
    <>
      <span className={clsx("station-big num", value < 0 ? "text-neg" : value > 0 ? "text-pos" : "text-ink")}>{money(v, { signed: true })}</span>
      {pctValue != null && <span className={clsx("num text-sm", value < 0 ? "text-neg" : "text-ink-2")}>{pct(pctValue, 2, true)} of the book</span>}
    </>
  );
}

/**
 * The product in one row: Source → Reading → Severity → Scenario → Exposure → Portfolio, joined by the wire.
 * Every value comes from an existing read-only endpoint (signal, assessment, intelligence, propagation, relevance); a station with no
 * data says so and never shows a stand-in number. No stress run is started from here: the portfolio figure is the intelligence
 * endpoint's stress preview, and the action opens the Stress Lab to run it.
 */
export function SignalTrace({ signalId, className }: { signalId: string; className?: string }) {
  const { data: meta } = useMeta();
  const caps = meta?.capabilities;
  const sig = useSignal(signalId);
  const a = useAssessment(signalId, caps?.assessment === true);
  const intel = useIntelligence(signalId, caps?.intelligence === true);
  const flow = usePropagation(signalId, caps?.propagation === true);
  const rel = useSignalRelevance(caps?.propagation === true ? undefined : signalId);
  const scenarios = useScenarios();
  const label = categoryLabeler(meta);
  const s = sig.data;

  if (sig.isLoading || !s)
    return (
      <div className={clsx("trace", className)} aria-busy="true" aria-label="Loading the signal trace">
        <Skeleton className="h-40 w-full" />
      </div>
    );

  const ev = s.event;
  const assessment = a.data;
  const sev = assessment?.severity ?? null;
  const reading = assessment?.reading;
  const category = ((reading && reading.event_type !== "NO_EVENT" ? reading.event_type : ev.category) ?? ev.category) as EventCategory;
  const isEvent = reading ? reading.event_type !== "NO_EVENT" : ev.status === "CLASSIFIED";
  const conf = reading?.event_confidence ?? ev.probabilities?.[ev.category] ?? null;
  const sentiment = reading?.sentiment ?? s.sentiment.score;
  const score = sev?.score ?? s.impact?.score ?? null;
  const band = score != null ? severityBand(score) : null;
  const ikind = !sev && s.impact ? impactKind(s) : null;
  const evidence = intel.data?.evidence;
  const stress = intel.data?.stress;
  const gen = flow.data?.scenario;
  const mat = flow.data?.materiality;
  const graph = flow.data?.graph;
  const fallbackScenario: Scenario | undefined = (() => {
    const dflt = meta?.taxonomy?.find((t) => t.id === category)?.default_scenario;
    return scenarios.data?.scenarios.find((x) => x.id === (stress?.scenario_id ?? dflt));
  })();
  const scenario = gen?.scenario ?? fallbackScenario ?? null;
  const failedGate = gen && gen.availability !== "AVAILABLE" ? gen.gates.find((g) => !g.passed) : undefined;
  const assetNodes = (graph?.nodes ?? []).filter((n) => n.kind === "ASSET_CLASS" && (n.share ?? 0) >= 0.005).sort((x, y) => (y.share ?? 0) - (x.share ?? 0));
  const reached = graph && graph.availability !== "UNAVAILABLE" ? graph.reached_share : rel.data?.share ?? null;
  const ev_id = `/events/${s.id}`;
  const sevTone = band ? (`sev-${band.band === "negligible" ? "low" : band.band}` as const) : "off";

  return (
    <section className={clsx("trace hero-surface", className)} aria-label="Signal trace">
      <span key={s.id} className="trace-wire" aria-hidden="true" />
      <ol className="trace-row" aria-label="From the news to the portfolio">
        <Station id="source" n={1} action={{ to: `${ev_id}#event`, label: "Read the source" }}>
          <p className="station-main">{s.document.source}</p>
          <p className="station-sub num">{dateTime(s.document.published_at)}</p>
          <p className="station-sub">
            <span className="num">{evidence?.independent_sources ?? s.evidence.source_count}</span>{" "}
            {evidence ? "independent source" : "report"}
            {(evidence?.independent_sources ?? s.evidence.source_count) === 1 ? "" : "s"}
            {s.document.body ? "" : " · headline only"}
          </p>
          {evidence && evidence.availability !== "UNAVAILABLE" && (
            <span className="pips" role="img" aria-label={`Evidence strength ${evidence.evidence_strength.tier.toLowerCase()}`}>
              {["INSUFFICIENT", "WEAK", "MODERATE", "STRONG"].map((t, i) => (
                <i key={t} data-on={i <= ["INSUFFICIENT", "WEAK", "MODERATE", "STRONG"].indexOf(evidence.evidence_strength.tier) && i > 0 ? "true" : undefined} />
              ))}
              <span className="text-xs text-muted">{evidence.evidence_strength.tier.toLowerCase()} evidence</span>
            </span>
          )}
        </Station>

        <Station id="reading" n={2} action={{ to: `${ev_id}#understand`, label: "What the text says" }}>
          {isEvent ? (
            <p className="station-main flex items-center gap-2">
              <CategoryGlyph category={category} size="sm" tone="accent" />
              {reading?.event_label ?? label(category)}
            </p>
          ) : (
            <p className="station-main">{ev.status === "UNCERTAIN" ? "Type uncertain" : "Not a market event"}</p>
          )}
          {conf != null && <p className="station-sub num">{Math.round(conf * 100)}% confident</p>}
          <span className="tone-gauge" role="img" aria-label={`Sentiment ${sentiment.toFixed(2)}, ${sentimentLabel(sentiment).toLowerCase()}`}>
            <i style={{ left: `${50 + Math.max(-1, Math.min(1, sentiment)) * 50}%` }} />
          </span>
          <p className="station-sub">
            Tone <span className="num">{sentiment > 0 ? "+" : sentiment < 0 ? "−" : "±"}{Math.abs(sentiment).toFixed(2)}</span> {sentimentLabel(sentiment).toLowerCase()}
          </p>
          <p className="station-note">{assessment ? (assessment.extraction.mode === "LLM" ? "AI-assisted reading" : "rule-based reading") : "trained text models"}</p>
        </Station>

        <Station id="severity" n={3} tone={sevTone} action={score != null ? { to: `${ev_id}?open=${sev ? "severity" : "why"}`, label: `Why ${score}?` } : undefined}>
          {score != null && band ? (
            <>
              <p className="flex items-baseline gap-1.5">
                <span className={clsx("station-score num", band.text)}>{score}</span>
                <span className="num text-muted">/10</span>
                <span className={clsx("font-semibold", band.text)}>{sev?.band_label ?? band.label}</span>
              </p>
              <span className="ladder h-1.5 w-full" aria-hidden="true">
                {Array.from({ length: 10 }, (_, i) => (
                  <i key={i} className={i < score ? band.bg : undefined} />
                ))}
              </span>
              <p className="station-sub">
                {sev ? (
                  <>
                    Range <span className="num">{sev.low}–{sev.high}</span> · {sev.version}
                  </>
                ) : s.impact?.score_low != null && s.impact?.score_high != null ? (
                  <>
                    Range <span className="num">{s.impact.score_low}–{s.impact.score_high}</span> · {ikind ? KIND_LABEL[ikind].toLowerCase() : ""}
                  </>
                ) : (
                  ikind && KIND_LABEL[ikind].toLowerCase()
                )}
              </p>
            </>
          ) : (
            <Missing>No severity for this signal{assessment?.severity_note ? `: ${assessment.severity_note}` : ". EventShock never substitutes a default score."}</Missing>
          )}
        </Station>

        <Station id="scenario" n={4} tone="dashed" action={{ to: `/stress?signal=${s.id}`, label: "See every shock" }}>
          {scenario && !failedGate ? (
            <>
              <p className="station-main">{scenario.name}</p>
              <ul className="shock-chips" aria-label="Shocks">
                {scenario.shocks.slice(0, 3).map((k, i) => {
                  const F = FACTOR_ICON[k.factor as RiskFactor];
                  return (
                    <li key={i} className="shock-chip" title={k.rationale}>
                      {F && <F size={12} />}
                      <span className="num">{shockValue(k.factor, k.value)}</span>
                      <span className="text-muted">{k.sector ?? SCOPE_LABEL[k.scope]?.toLowerCase() ?? k.scope.toLowerCase()}</span>
                    </li>
                  );
                })}
                {scenario.shocks.length > 3 && <li className="text-xs text-muted">+{scenario.shocks.length - 3} more</li>}
              </ul>
              <p className="station-note">Scenario simulation, not a prediction</p>
            </>
          ) : failedGate ? (
            <>
              <p className="station-main">Scenario unavailable</p>
              <Missing>{failedGate.label}: {failedGate.detail}</Missing>
            </>
          ) : (
            <Missing>No scenario maps to this event type.</Missing>
          )}
        </Station>

        <Station id="exposure" n={5} action={{ to: `${ev_id}#stress`, label: "Exposure path" }}>
          {mat && mat.availability !== "UNAVAILABLE" && <p className="station-main">{mat.level.charAt(0) + mat.level.slice(1).toLowerCase()} materiality</p>}
          {!mat && rel.data && <p className="station-main">{rel.data.level.charAt(0) + rel.data.level.slice(1).toLowerCase().replace("_", " ")} exposure</p>}
          {reached != null ? (
            <>
              <span className="reach-bar" role="img" aria-label={`${pct(reached)} of the book reached`}>
                <i style={{ width: `${Math.min(100, reached * 100)}%` }} />
              </span>
              <p className="station-sub">
                <span className="num">{pct(reached)}</span> of the book reached
              </p>
            </>
          ) : (
            !mat && !rel.data && <Missing>Exposure not available for this portfolio.</Missing>
          )}
          {assetNodes.length > 0 && (
            <ul className="asset-mini">
              {assetNodes.slice(0, 2).map((n) => {
                const key = (n.id.split(":").pop() ?? "OTHER") as keyof typeof ASSET_ICON;
                const A = ASSET_ICON[key];
                return (
                  <li key={n.id}>
                    {A && <A size={12} />} {ASSET_CLASS_LABEL[key] ?? n.label} <span className="num">{pct(n.share ?? 0, 0)}</span>
                  </li>
                );
              })}
            </ul>
          )}
          {!assetNodes.length && rel.data?.summary && <p className="station-note">{rel.data.summary}</p>}
        </Station>

        <Station id="portfolio" n={6} tone={stress?.pnl != null && stress.pnl < 0 ? "neg" : "wire"} action={{ to: `/stress?signal=${s.id}&run=1`, label: "Open in Stress Lab" }}>
          {stress && stress.availability === "AVAILABLE" && stress.pnl != null && stress.baseline_value != null && stress.stressed_value != null ? (
            <>
              <p className="station-sub num">
                {money(stress.baseline_value)} → {money(stress.stressed_value)}
              </p>
              <Delta value={stress.pnl} pctValue={stress.pnl_pct} />
              <p className="station-note">Deterministic engine · {stress.scenario_name ?? "scenario"} assumptions</p>
            </>
          ) : stress ? (
            <>
              <p className="station-main">{stress.status === "NOT_TRIGGERED" ? "Below the trigger" : "Not run here"}</p>
              <Missing>{stress.reason ?? stress.note}</Missing>
            </>
          ) : (
            <Missing>Run the scenario in the Stress Lab to see the before and after.</Missing>
          )}
        </Station>
      </ol>
    </section>
  );
}

/** The same six stations, one line each: for the Analyze result and narrow spaces. */
export function TraceGlyphRow() {
  return (
    <ol className="trace-glyphs" aria-hidden="true">
      {(Object.keys(STATION_TITLE) as StationId[]).map((k) => (
        <li key={k}>
          <Glyph icon={STATION_ICON[k]} size="sm" shape="round" />
          {STATION_TITLE[k]}
        </li>
      ))}
    </ol>
  );
}
