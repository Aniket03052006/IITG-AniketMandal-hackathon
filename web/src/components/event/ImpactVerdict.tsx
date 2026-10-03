import clsx from "clsx";
import { Link } from "react-router-dom";
import type { RiskSignal } from "../../api/types";
import { impactKind, KIND_LABEL } from "../../lib/impact";
import { useTween } from "../../lib/motion";
import { impactSentence } from "../../lib/narrative";
import { severityBand } from "../../lib/severity";
import { ImpactLifecycleTag } from "../ImpactLifecycleTag";
import { StatusTag } from "../ui";
import { KindBadge } from "../ProvenanceKind";
import { StateNotice } from "../StateNotice";
import { ImpactMeter } from "../ui";
import { ExplainBar, INPUTS, MATH, TECH, WHY } from "./ExplainBar";

/** The verdict: how severe, as a number that resolves once, a ladder with the range comparable events realised, and what produced it. */
export function ImpactVerdict({ s }: { s: RiskSignal }) {
  const impact = s.impact;
  const score = impact?.score ?? 0;
  const shown = Math.round(useTween(score));
  const kind = impactKind(s);
  const audit = s.provenance?.impact ?? null;
  const modelled = !!audit && impact?.predicted_severity != null;
  const fixture = s.data_origin === "DEMO_FIXTURE";

  if (!impact) {
    const classified = s.event.status === "CLASSIFIED";
    return (
      <div className="verdict">
        <p className="eyebrow">Estimated impact</p>
        <div className="mt-3">
          <StateNotice
            tone="warn"
            what={classified ? "No impact estimate for this signal" : s.event.status === "NO_EVENT" ? "Not treated as a market event" : "Event type uncertain, so no impact is scored"}
            why={<>{(s.status_reason ?? "").replace(/\.?$/, ".")} EventShock never substitutes a default score, so this signal cannot trigger a stress test.</>}
            next={
              <Link className="btn" to="/?min=7">
                Browse high-impact events
              </Link>
            }
          />
        </div>
      </div>
    );
  }

  const band = severityBand(impact.score);
  const range: [number, number] | null = impact.score_low != null && impact.score_high != null ? [impact.score_low, impact.score_high] : null;
  return (
    <div className="verdict" data-kind={kind}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="eyebrow">Estimated impact</p>
        {modelled ? <KindBadge kind="model" /> : fixture ? <StatusTag tone="demo">Fixture · illustrative</StatusTag> : <ImpactLifecycleTag kind={kind} />}
      </div>
      <div className="mt-2 flex items-end gap-3">
        <span className={clsx("verdict-score num", band.text)} aria-hidden="true">
          {shown}
        </span>
        <span className="pb-2 text-lg text-muted" aria-hidden="true">
          / 10
        </span>
        <span className="pb-2">
          <span className={clsx("block font-display text-xl font-semibold", band.text)}>{band.label}</span>
          {modelled && <ImpactLifecycleTag kind={kind} />}
        </span>
      </div>
      <div className="mt-4">
        <ImpactMeter score={impact.score} size="lg" range={range} kind={kind} hideNumber wide />
        {range && (
          <p className="mt-1 text-xs text-muted">
            Bracket: the score range comparable past events actually realised ({range[0]} to {range[1]}).
          </p>
        )}
      </div>
      <p className="mt-4 max-w-[52ch] text-ink-2">{impactSentence(s)}</p>
      {!modelled && !fixture && s.provenance?.impact_note && (
        <p className="mt-2 text-sm text-muted">
          The trained model did not score this signal: {s.provenance.impact_note}.
        </p>
      )}
      <div className="mt-5">
        <ExplainBar items={modelled ? [WHY, INPUTS, MATH, TECH] : [WHY, TECH]} />
      </div>
      <p className="sr-only">{KIND_LABEL[kind]}</p>
    </div>
  );
}
