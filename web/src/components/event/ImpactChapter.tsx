import { useImpactModel } from "../../api/hooks";
import type { RiskSignal } from "../../api/types";
import { pct, sigma } from "../../lib/format";
import { impactKind, KIND_LABEL } from "../../lib/impact";
import { driverLines, driversSentence } from "../../lib/narrative";
import { ImpactLifecycleTag } from "../ImpactLifecycleTag";
import { KindBadge } from "../ProvenanceKind";
import { StatusTag } from "../ui";
import { StateNotice } from "../StateNotice";
import { Chapter } from "./Chapter";
import { DriverBars } from "./DriverBars";
import { ExplainBar, INPUTS, MATH, TECH, WHY } from "./ExplainBar";

const TIMING_TEXT: Record<string, string> = {
  OFF_HOURS: "published after the close or on a non-trading day: the whole reaction follows the report",
  PRE_OPEN: "published before the open",
  IN_SESSION: "published during the session: part of the move may precede the report",
  DATE_ONLY: "the source gave a date but no time",
  FIRST_SEEN: "a crawl time, which lags publication: the reaction may precede it",
};

function Fact({ label, value, note, kind }: { label: string; value: React.ReactNode; note: React.ReactNode; kind?: "model" | "historical" }) {
  return (
    <div className="fact">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="eyebrow">{label}</p>
        {kind && <KindBadge kind={kind} />}
      </div>
      <p className="fact-value num">{value}</p>
      <p className="mt-0.5 text-sm text-muted">{note}</p>
    </div>
  );
}

/** Chapter 3: why this score. Plain-named drivers and three facts; every number says what kind of number it is. */
export function ImpactChapter({ s, label }: { s: RiskSignal; label: (c: string) => string }) {
  const impact = s.impact;
  const audit = s.provenance?.impact ?? null;
  const modelled = !!audit && impact?.predicted_severity != null;
  const kind = impactKind(s);
  const fixture = s.data_origin === "DEMO_FIXTURE";
  const { data: card } = useImpactModel(modelled);
  const scope = audit ? card?.scopes.find((x) => x.scope === audit.scope) : undefined;
  const failed = scope?.acceptance.checks.filter((c) => c.passed !== true) ?? [];

  if (!impact) {
    return (
      <Chapter id="impact" eyebrow="Impact" title="How severe a reaction is likely" lede="There is no impact estimate to explain for this signal: see the reason at the top of the page.">
        <ExplainBar items={[TECH]} />
      </Chapter>
    );
  }
  const lines = driverLines(impact, label);
  return (
    <Chapter
      id="impact"
      eyebrow="Impact"
      title="How severe a reaction is likely"
      lede={modelled ? driversSentence(lines) : fixture ? "A hand-authored fixture value. The drivers below are illustrative, not attributions of a model." : "A fixed placeholder rule set this score, not a model. Its three terms are shown below."}
      badge={modelled ? <KindBadge kind="model" /> : fixture ? <StatusTag tone="demo">Fixture · illustrative</StatusTag> : <ImpactLifecycleTag kind={kind} />}
    >
      <div className="impact-grid">
        <div>
          <h3 className="text-sm font-semibold">{modelled ? "What moves the estimate" : "What sets the score"}</h3>
          <p className="mb-3 mt-0.5 text-xs text-muted">
            {modelled ? "Attributions of the model's own arithmetic, not causes in the market." : "Hand-set terms, not a measurement and not a model explanation."}
          </p>
          <DriverBars lines={lines} />
        </div>
        <div className="space-y-5">
          {modelled && impact.predicted_severity != null && (
            <Fact
              label="Model estimate"
              kind="model"
              value={sigma(impact.predicted_severity)}
              note={`expected size of ${audit!.scope === "MARKET" ? "the S&P 500's" : "the issuer's"} abnormal move over the next two sessions, in units of its usual daily volatility. Not a probability of loss and not a direction.`}
            />
          )}
          {modelled && impact.p_extreme != null && (
            <Fact
              label="Chance of an extreme move"
              kind="historical"
              value={pct(impact.p_extreme, 1)}
              note={`of ${impact.comparable_events?.toLocaleString("en-US")} comparable past events realised 3σ or more${scope?.calibration ? `, against ${pct(scope.calibration.base_rate_extreme, 1)} of all events` : ""}.`}
            />
          )}
          {audit && (
            <div className="fact">
              <p className="eyebrow">Timing</p>
              <p className="mt-1 text-sm text-ink-2">
                {TIMING_TEXT[audit.timing] ?? audit.timing}.{" "}
                {audit.timing_reliable ? "The model's evidence on this kind of timestamp is solid." : <span className="text-warn">The model's evidence on such timestamps is thinner, so read the score as less certain than the range suggests.</span>}
              </p>
            </div>
          )}
        </div>
      </div>
      {modelled && kind !== "validated" && (
        <div className="mt-6 max-w-[72ch]">
          <StateNotice
            tone="warn"
            what={`${KIND_LABEL[kind]}: ${audit!.lifecycle.toLowerCase()}, not production`}
            why={
              failed.length > 0
                ? `Not every pre-registered acceptance check was met: ${failed.slice(0, 2).map((c) => c.label.toLowerCase()).join("; ")}${failed.length > 2 ? `; and ${failed.length - 2} more` : ""}. Treat the score as a guide to relative severity, not a forecast.`
                : "It is calibrated, but not every acceptance check could be evaluated. Treat the score as a guide to relative severity, not a forecast."
            }
          />
        </div>
      )}
      <div className="mt-6">
        <ExplainBar items={modelled ? [WHY, INPUTS, MATH, TECH] : [WHY, TECH]} />
      </div>
    </Chapter>
  );
}
