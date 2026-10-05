import type { RiskAssessment, TimelineView } from "../../api/types";
import { ASSET_LABEL, pc, signed } from "../../lib/assessment";
import { REGION_LABEL } from "../../lib/scope";
import { DrawerSection, useOpenDrawer } from "../Drawer";
import { AssessmentKind } from "./AssessmentKind";

function Line({ k, v, kind, note }: { k: string; v: React.ReactNode; kind: string; note?: React.ReactNode }) {
  return (
    <div className="grid gap-x-4 gap-y-0.5 border-t border-rule py-2 first:border-t-0 sm:grid-cols-[10rem_minmax(0,1fr)]">
      <dt className="text-sm text-muted">{k}</dt>
      <dd className="min-w-0 text-sm text-ink">
        <span className="font-medium">{v}</span> <AssessmentKind kind={kind} />
        {note && <span className="mt-0.5 block text-xs text-muted">{note}</span>}
      </dd>
    </div>
  );
}

/** "What the assessment used": only inputs that actually enter the score or the reading, grouped as NLP signals, market state, calendar, and what is deliberately left out. */
export function AssessedInputs({ a, tl }: { a: RiskAssessment; tl: TimelineView | undefined }) {
  const [, setOpen] = useOpenDrawer();
  const r = a.reading;
  const sev = a.severity;
  const omitted = (id: string) => sev?.omitted.find((o) => o.id === id);
  const filings = tl?.items.filter((i) => i.kind === "FILING") ?? [];
  return (
    <>
      <DrawerSection title="NLP signals" note="What the text says. Each line is a reading, by a language model or by rules (the mode is stated at the top of the page).">
        <dl>
          <Line k="Event" v={`${r.event_label}${r.event_subtype !== "other" ? ` · ${r.event_subtype_label}` : ""}`} kind="EXTRACTION"
            note={r.event_confidence != null ? `Event confidence ${pc(r.event_confidence)}` : "No calibrated confidence (cue phrases decided)"} />
          <Line k="Sentiment" v={`${r.sentiment_label} ${signed(r.sentiment)}`} kind="EXTRACTION" note={`${r.sentiment_intensity} intensity`} />
          <Line k="Sector" v={r.sectors.length ? r.sectors.join(", ") : "None identified"} kind="EXTRACTION" />
          <Line k="Geography" v={r.regions.length ? r.regions.map((x) => REGION_LABEL[x] ?? x).join(", ") : "None identified"} kind="EXTRACTION" />
          <Line k="Entity" v={r.primary_issuer.resolved ? `${r.primary_issuer.name} (${r.primary_issuer.ticker})` : r.entities.length ? `${r.entities.map((e) => e.name).join(", ")} (mentioned, not an issuer)` : "None identified"}
            kind="SOURCE" note={r.primary_issuer.resolved ? undefined : "Issuer: UNKNOWN_ENTITY. A name outside the entity master is never given company data."} />
          <Line k="Asset classes" v={r.asset_classes.length ? r.asset_classes.map((x) => ASSET_LABEL[x] ?? x).join(", ") : "None identified"} kind="EXTRACTION" />
          <Line k="Severity indicators" v={r.severity_indicators.length ? r.severity_indicators.map((h) => h.label).join(", ") : "None found"} kind="EXTRACTION" />
          <Line k="Novelty" v={omitted("novelty") ? "Not measurable" : "Measured against earlier reports of the same issuer"} kind="SOURCE" note={omitted("novelty")?.reason} />
          {sev?.rubric.map((f) => (
            <Line key={f.id} k={f.label} v={f.final_label} kind="EXTRACTION" note={`Rules: ${f.baseline_label}${f.ai_label ? `; AI: ${f.ai_label}` : ""}. ${f.note}`} />
          ))}
        </dl>
      </DrawerSection>
      <DrawerSection title="Market state" note="Observations of the market from before the report. Left out when none existed at the report's time.">
        <dl>
          <Line k="Volatility regime" v={sev?.market.used ? `VIX ${sev.market.vix?.toFixed(1)}` : "Not used"} kind="MARKET_STATE" note={sev?.market.reason} />
        </dl>
        <p className="mt-2 text-xs text-muted">
          Prices, yields and index returns beyond the VIX level are read only by the trained reference model.{" "}
          <button type="button" className="text-accent underline underline-offset-2" onClick={() => setOpen("inputs")}>
            See the reference model's inputs
          </button>
        </p>
      </DrawerSection>
      <DrawerSection title="Calendar" note="Scheduled and filed items around the report. The severity score does not read them; the reference model reads those marked below.">
        {filings.length === 0 ? (
          <p className="text-sm text-muted">No SEC filing or scheduled item is on record for this issuer around the report.</p>
        ) : (
          <ul className="space-y-1.5 text-sm">
            {filings.map((f, n) => (
              <li key={n} className="text-ink-2">
                <span className="font-medium text-ink">{f.label}</span> · <span className="text-muted">{f.phase === "AFTER_REPORT" ? "after the report: never used" : f.used_by_reference_model ? "reference model only" : "before, not used"}</span>
              </li>
            ))}
          </ul>
        )}
      </DrawerSection>
      <DrawerSection title="Deliberately excluded" note="These exist, and are shown for audit, but can never change the score.">
        <ul className="list-disc space-y-1 pl-5 text-sm text-ink-2">
          {(tl?.excluded ?? ["Later coverage", "Later filings", "The realised market move"]).map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      </DrawerSection>
    </>
  );
}
