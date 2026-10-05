import clsx from "clsx";
import type { Origin, RiskAssessment } from "../../api/types";
import { ASSET_LABEL, ENTITY_KIND_LABEL, modeLabel, pc, signed } from "../../lib/assessment";
import { REGION_LABEL } from "../../lib/scope";
import { SentimentBar } from "../ui";
import { StateNotice } from "../StateNotice";
import { AssessmentKind } from "./AssessmentKind";
import { HighlightedText } from "./HighlightedText";
import { ModeChip } from "./ModeChip";
import { OriginChip } from "./OriginChip";

function Row({ k, origin, children }: { k: string; origin?: Origin; children: React.ReactNode }) {
  return (
    <div className="reading">
      <p className="flex flex-wrap items-center gap-2">
        <span className="eyebrow">{k}</span>
        {origin && <OriginChip origin={origin} />}
      </p>
      <div className="mt-1">{children}</div>
    </div>
  );
}

const Tags = ({ items, empty }: { items: string[]; empty: string }) =>
  items.length ? (
    <ul className="flex flex-wrap gap-1.5">
      {items.map((t) => (
        <li key={t} className="tag">
          {t}
        </li>
      ))}
    </ul>
  ) : (
    <p className="text-sm text-muted">{empty}</p>
  );

/**
 * "AI understanding": what the report says, as a structured reading. Every claim comes from the text (quoted and highlighted) or says it is an
 * inference; a company the entity master does not hold is shown as a mention, and the issuer line says UNKNOWN_ENTITY rather than guessing.
 */
export function UnderstandingCard({ a }: { a: RiskAssessment }) {
  const r = a.reading;
  const e = a.extraction;
  const issuer = r.primary_issuer;
  const origin = (part: string): Origin | undefined => a.provenance.find((l) => l.part === part)?.origin;
  const quoted = r.severity_indicators.filter((h) => h.basis !== "INFERRED");
  const inferred = r.severity_indicators.filter((h) => h.basis === "INFERRED");
  return (
    <div className="space-y-5" aria-label="AI understanding">
      <div className="flex flex-wrap items-center gap-2">
        <ModeChip a={a} />
        <AssessmentKind kind="EXTRACTION" />
        <span className="text-xs text-muted">{modeLabel(a)}</span>
      </div>

      {e.fallback_reason && (
        <StateNotice
          tone="warn"
          what="The language model could not be used for this text"
          why={`${e.fallback_reason}. The deterministic rules read it instead; everything below is still checked against the text.`}
        />
      )}

      <div className="understand">
        <div className="understand-in">
          <p className="eyebrow">Report text · quoted evidence is marked</p>
          <blockquote className="quote">
            <HighlightedText text={r.text} spans={r.evidence} />
          </blockquote>
          <p className="mt-2 text-xs text-muted">
            {r.evidence.length > 0 ? `${r.evidence.length} excerpt${r.evidence.length === 1 ? "" : "s"} are verbatim from the text and support the reading.` : "No excerpt supports a specific claim, so none is marked."}
          </p>
          {r.rationale && (
            <p className="mt-3 text-sm text-ink-2">
              <span className="font-medium text-ink">The model's reason: </span>
              {r.rationale}
            </p>
          )}
        </div>
        <div className="understand-arrow" aria-hidden="true" />
        <div className="understand-out">
          <Row k="Event" origin={origin("Event class and subtype")}>
            {r.event_type === "NO_EVENT" ? (
              <p className="reading-value text-ink-2">Not a market event</p>
            ) : (
              <>
                <p className="reading-value">{r.event_label}</p>
                {r.event_subtype !== "other" && <p className="text-sm text-ink-2">{r.event_subtype_label}</p>}
                {r.event_confidence != null ? (
                  <>
                    <div className="meter" role="img" aria-label={`Confidence ${pc(r.event_confidence)}`}>
                      <span className="meter-fill bar-grow" style={{ width: pc(r.event_confidence) }} />
                    </div>
                    <p className="mt-1 text-xs text-muted">
                      {pc(r.event_confidence)} confidence ({e.mode === "LLM" ? "stated by the model" : "the trained event model's calibrated probability for this class"})
                    </p>
                  </>
                ) : (
                  <p className="mt-1 text-xs text-muted">No calibrated confidence: the cue phrases decided this, not a trained probability.</p>
                )}
              </>
            )}
          </Row>
          <Row k="Tone" origin={origin("Tone")}>
            <p className="reading-value">
              <span className={clsx(r.sentiment_label === "negative" ? "text-neg" : r.sentiment_label === "positive" ? "text-pos" : "text-ink-2")}>
                {r.sentiment_label[0]!.toUpperCase() + r.sentiment_label.slice(1)}
              </span>{" "}
              <span className="num text-xl text-ink-2">{signed(r.sentiment)}</span>
            </p>
            <div className="mt-2">
              <SentimentBar score={r.sentiment} wide />
            </div>
            <p className="mt-1 text-xs text-muted">
              {r.sentiment_intensity} intensity. Tone is not impact: a calm notice can matter more than a loud opinion.
            </p>
          </Row>
          <Row k="Who" origin={origin("Entities")}>
            <p className="reading-value num">{issuer.resolved ? `${issuer.name} (${issuer.ticker})` : issuer.entity_id}</p>
            <p className="mt-1 text-xs text-muted">{issuer.note}</p>
            {r.entities.length > 0 && (
              <ul className="mt-2 space-y-1.5">
                {r.entities.map((en) => (
                  <li key={en.name} className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
                    <span className="font-medium text-ink">{en.name}</span>
                    <span className="tag">{ENTITY_KIND_LABEL[en.kind] ?? en.kind}</span>
                    <span className="text-xs text-muted">
                      {en.resolved ? `matched the entity master${en.ticker ? ` (${en.ticker})` : ""}` : "named in the text, not in the entity master: no company data is used"}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Row>
          <Row k="Affected">
            <p className="text-xs text-muted">Sectors</p>
            <Tags items={r.sectors} empty="No sector identified" />
            <p className="mt-2 text-xs text-muted">Geography</p>
            <Tags items={r.regions.map((x) => REGION_LABEL[x] ?? x)} empty="No geography identified" />
            <p className="mt-2 text-xs text-muted">Asset classes</p>
            <Tags items={r.asset_classes.map((x) => ASSET_LABEL[x] ?? x)} empty="No asset class identified" />
          </Row>
          <Row k="Severity indicators" origin={origin("Severity indicators")}>
            {r.severity_indicators.length === 0 ? (
              <p className="text-sm text-muted">None found in the text</p>
            ) : (
              <div className="space-y-3">
                {quoted.length > 0 && (
                  <div>
                    <p className="text-xs text-muted">Shown by the report itself</p>
                    <ul className="mt-1 space-y-1">
                      {quoted.map((h) => (
                        <li key={h.id} className="text-sm text-ink-2">
                          <span className="font-medium text-ink">{h.label}</span> · <span className="text-muted">“{h.quote}”</span>
                          <span className="ml-1 text-2xs text-faint">{h.basis === "QUOTED" ? "quoted by the AI" : "matched phrase"}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {inferred.length > 0 && (
                  <div>
                    <p className="text-xs text-muted">AI inference: no phrase in the report shows these, so they are not quotes</p>
                    <ul className="mt-1 space-y-1">
                      {inferred.map((h) => (
                        <li key={h.id} className="text-sm text-ink-2">
                          <span className="font-medium text-ink">{h.label}</span> <span className="tag">inferred</span>
                          {h.reason && <span className="block text-xs text-muted">The AI's reason: {h.reason}</span>}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </Row>
        </div>
      </div>

      <details className="disclosure">
        <summary>How this was read, and what was checked</summary>
        <div className="mt-2 space-y-2 text-sm text-ink-2">
          <p>{e.basis}</p>
          {r.uncertainty != null && <p>Uncertainty stated for this reading: {pc(r.uncertainty)}.</p>}
          <p>{a.agreement.note}</p>
          {e.notes.length > 0 && (
            <ul className="list-disc space-y-0.5 pl-5">
              {e.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          )}
        </div>
      </details>
    </div>
  );
}
