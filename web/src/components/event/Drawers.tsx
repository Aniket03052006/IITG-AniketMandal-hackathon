import { subjectLine, subjectOf } from "../../lib/scope";
import clsx from "clsx";
import { useEventModel, useImpactModel, useSentimentModel } from "../../api/hooks";
import type { EventCategory, RiskAssessment, RiskSignal, SignalContext, TimelineView } from "../../api/types";
import { EVENT_CATEGORIES } from "../../api/types";
import { AVAILABILITY, featureInfo, featureSection, formatFeature, SECTION_TITLE, type InputSection } from "../../lib/featureLabels";
import * as TeX from "../../lib/formulas";
import { dateTime, pct, signed, sigma } from "../../lib/format";
import { impactKind, KIND_LABEL, LIFECYCLE_STEPS } from "../../lib/impact";
import { driverLines, driversSentence } from "../../lib/narrative";
import { ruleNote, stageKind, timestampNote } from "../../lib/provenance";
import { sentimentLabel } from "../../lib/severity";
import { Drawer, DrawerSection, useOpenDrawer } from "../Drawer";
import { Formula } from "../Math";
import { Skeleton } from "../ui";
import { AssessedInputs } from "../assessment/AssessedInputs";
import { OriginChip } from "../assessment/OriginChip";
import { ScoreBuildUp } from "../assessment/ScoreBuildUp";
import { severityLede } from "../../lib/assessment";
import { DriverBars } from "./DriverBars";

const pc = (p: number) => `${Math.round(p * 100)}%`;

function Dl({ rows }: { rows: [string, React.ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[minmax(0,12rem)_minmax(0,1fr)] gap-x-4 gap-y-1.5 text-sm">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted">{k}</dt>
          <dd className="num min-w-0 break-words text-ink-2">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

/* ------------------------------------------------------------------------------------------------ NLP */
function NlpBody({ s, label }: { s: RiskSignal; label: (c: string) => string }) {
  const audit = s.provenance?.event;
  const sent = s.provenance?.sentiment;
  const isEvent = stageKind(s.provenance?.stage_origins.event) === "model" && !!audit;
  const isSent = stageKind(s.provenance?.stage_origins.sentiment) === "model" && !!sent;
  const { data: ec } = useEventModel(isEvent);
  const { data: sc } = useSentimentModel(isSent);
  const gold = ec?.evaluations.find((e) => e.id === "gold_history")?.model;
  const heldOut = sc?.evaluations.find((e) => e.id === "tfn_test")?.model;
  const ownSent = sc?.evaluations.find((e) => e.id === "gold_history")?.model;
  const goldEval = ec?.evaluations.find((e) => e.id === "gold_history");
  const keywordF1 = goldEval?.baselines.placeholder_keywords?.detection_f1;
  const rows = EVENT_CATEGORIES.map((c) => ({ c, p: s.event.probabilities[c as EventCategory] ?? 0 })).sort((a, b) => b.p - a.p);
  const rel = ec?.class_reliability.find((r) => r.label === s.event.category);
  return (
    <>
      <DrawerSection
        title="Event type"
        note="Eight event types plus “not an event”. The eight shares below are conditional on the text being an event; the last line is the chance it is not one."
      >
        <ul className="space-y-1.5">
          {rows.map(({ c, p }, i) => (
            <li key={c} className="grid grid-cols-[minmax(0,1fr)_6rem_2.75rem] items-center gap-3 text-sm">
              <span className={clsx("truncate", i === 0 ? "font-medium text-ink" : "text-muted")}>{label(c)}</span>
              <span className="h-2 rounded-sm bg-paper-4" aria-hidden="true">
                <span className={clsx("block h-full rounded-sm", i === 0 ? "bg-accent" : "bg-faint")} style={{ width: pc(p) }} />
              </span>
              <span className="num text-right">{pc(p)}</span>
            </li>
          ))}
          {audit && (
            <li className="grid grid-cols-[minmax(0,1fr)_6rem_2.75rem] items-center gap-3 border-t border-rule pt-2 text-sm">
              <span className="text-muted">Not an event</span>
              <span className="h-2 rounded-sm bg-paper-4" aria-hidden="true">
                <span className="block h-full rounded-sm bg-faint" style={{ width: pc(audit.no_event_probability) }} />
              </span>
              <span className="num text-right">{pc(audit.no_event_probability)}</span>
            </li>
          )}
        </ul>
        {ec && <div className="mt-4"><Formula tex={TeX.eventDecision(ec.abstention.commit_threshold)} reading={TeX.EVENT_READING} /></div>}
        {audit?.unreliable_class && rel && <p className="mt-3 text-sm text-warn">{rel.reason}, so a lean towards this type is shown as uncertain.</p>}
        {audit?.seen_in_training && <p className="mt-3 text-sm text-warn">In-sample: the model trained on this exact text, so its output here is not evidence of accuracy.</p>}
        {gold && (
          <p className="mt-3 text-sm text-muted">
            On sources we labelled ourselves (labels are AI-annotated) the model separates events from non-events with F1 {gold.served.detection.f1.toFixed(2)}
            {keywordF1 != null ? ` (the old keyword rules: ${keywordF1.toFixed(2)})` : ""}; picking the exact type is far less reliable.
          </p>
        )}
      </DrawerSection>
      <DrawerSection title="Sentiment" note="Tone of the wording. It is one reading of the text, not the market impact.">
        <Dl rows={[["Negative", pc(s.sentiment.negative)], ["Neutral", pc(s.sentiment.neutral)], ["Positive", pc(s.sentiment.positive)], ["Score", `${signed(s.sentiment.score)} · ${sentimentLabel(s.sentiment.score).toLowerCase()}`]]} />
        <div className="mt-4"><Formula tex={TeX.SENTIMENT} reading={TeX.SENTIMENT_READING} /></div>
        {heldOut && <p className="mt-3 text-sm text-muted">On held-out Twitter Financial News posts the model scores macro-F1 {heldOut.macro_f1.toFixed(2)}. {ownSent ? ` On our own AI-labelled sources only ${ownSent.macro_f1.toFixed(2)}, so read scores from our sources as indicative.` : " Read scores from other sources as indicative."}</p>}
      </DrawerSection>
      <DrawerSection title="Which models">
        <Dl
          rows={[
            ["Event type", audit ? `${audit.model_id} · sha256 ${audit.artifact_sha256.slice(0, 12)}` : "keyword rules (placeholder)"],
            ["Sentiment", sent ? `${sent.model_id} · sha256 ${sent.artifact_sha256.slice(0, 12)}` : "lexicon / source label (placeholder)"],
          ]}
        />
      </DrawerSection>
    </>
  );
}

/* ------------------------------------------------------------------------------------------------ WHY */
function WhyBody({ s, label }: { s: RiskSignal; label: (c: string) => string }) {
  const i = s.impact!;
  const audit = s.provenance?.impact;
  const lines = driverLines(i, label);
  const base = i.drivers.find((d) => d.feature === "baseline");
  const lump = i.drivers.find((d) => /^\d+ other features$/.test(d.feature));
  return (
    <>
      <DrawerSection title="In one line">
        <p className="text-ink-2">{audit ? driversSentence(lines) : "A fixed placeholder rule set this score: a prior for the event type, plus the strength of the tone, plus how many outlets carried it."}</p>
      </DrawerSection>
      <DrawerSection
        title={audit ? "Everything that moved the estimate" : "The rule's three terms"}
        note={audit ? "Each bar is that input's share of the model's arithmetic for this report. It explains the model, not why the market moves." : "Hand-set weights: not a measurement and not a model explanation."}
      >
        <DriverBars lines={lines} max={12} />
        {audit && base && (
          <p className="mt-4 text-sm text-muted">
            Starts from <span className="num text-ink-2">{signed(base.contribution, 3)}</span>, {base.note}. {lump ? `${lump.feature} add ${signed(lump.contribution, 3)} in total. ` : ""}
            {i.driver_basis ? `Units: ${i.driver_basis}.` : ""}
          </p>
        )}
      </DrawerSection>
      <DrawerSection title="What this score does not tell you">
        <ul className="list-disc space-y-1.5 pl-5 text-sm text-ink-2">
          <li>It is not a probability of loss.</li>
          <li>It does not say whether the move is up or down; direction is not modelled.</li>
          <li>It is not a price forecast: it ranks how large a reaction is likely against past events.</li>
        </ul>
      </DrawerSection>
    </>
  );
}

/* --------------------------------------------------------------------------------------------- INPUTS */
function InputsBody({ s, ctx, loading, label }: { s: RiskSignal; ctx: SignalContext | undefined; loading: boolean; label: (c: string) => string }) {
  const audit = s.provenance?.impact;
  const i = s.impact;
  const groups: Record<InputSection, NonNullable<typeof ctx>["inputs"]> = { report: [], text: [], calendar: [], market: [] };
  for (const x of ctx?.inputs ?? []) groups[featureSection(x.name)].push(x);
  if (!audit) {
    return (
      <p className="text-ink-2">
        This signal has no model inputs: {s.provenance?.impact_note ?? "the trained impact model did not score it"}. The placeholder rule reads only the event type, the strength of the tone and how many outlets carried the story.
      </p>
    );
  }
  return (
    <>
      <DrawerSection title="The report" note={SECTION_TITLE.report.note}>
        <Dl
          rows={[
            ["Headline", <span key="h" className="font-sans">{s.document.headline}</span>],
            ["Source", s.document.source],
            ["Published", `${dateTime(s.document.published_at)} · ${timestampNote(s.provenance?.timestamp_origin ?? "SOURCE")}`],
            ["Subject", `${subjectLine(subjectOf(s))} · ${s.scope.level === "COMPANY" ? ruleNote(s.provenance?.entity_audit.rule ?? "") : `${s.scope.basis.toLowerCase().replace(/_/g, " ")} (${s.scope.resolver_version})`}`],
            ["Reaction measured from", audit.session === "NEXT" ? "the next session (not yet traded)" : audit.session],
          ]}
        />
        {loading ? <Skeleton className="mt-3 h-20 w-full" /> : <InputRows rows={groups.report} label={label} />}
      </DrawerSection>
      <DrawerSection title={SECTION_TITLE.text.title} note={SECTION_TITLE.text.note}>
        {loading ? <Skeleton className="h-24 w-full" /> : <InputRows rows={groups.text} label={label} />}
      </DrawerSection>
      <DrawerSection title={SECTION_TITLE.calendar.title} note={SECTION_TITLE.calendar.note}>
        {loading ? <Skeleton className="h-24 w-full" /> : <InputRows rows={groups.calendar} label={label} />}
      </DrawerSection>
      <DrawerSection title={SECTION_TITLE.market.title} note={`${SECTION_TITLE.market.note} Market data as of ${audit.market_context_as_of}.`}>
        {loading ? <Skeleton className="h-24 w-full" /> : <InputRows rows={groups.market} label={label} />}
      </DrawerSection>
      <DrawerSection title="Model output">
        <Dl
          rows={[
            ["Raw prediction", i?.predicted_severity != null ? `${sigma(i.predicted_severity)} expected move` : "n/a"],
            ["Calibrated score", i ? `${i.score} of 10 (continuous ${i.raw.toFixed(3)})` : "n/a"],
            ["Range comparable events realised", i?.score_low != null && i.score_high != null ? `${i.score_low} to ${i.score_high} (10th to 90th percentile)` : "none: no uncertainty for this score"],
            ["Scope", audit.scope === "ISSUER" ? "the company's own abnormal move" : "the S&P 500's move"],
            ["Lifecycle", `${audit.lifecycle.toLowerCase()} · ${KIND_LABEL[impactKind(s)].toLowerCase()}`],
          ]}
        />
      </DrawerSection>
      {ctx && (
        <DrawerSection title="Deliberately not used" note="These exist, but reading them would use information from after the report.">
          <ul className="list-disc space-y-1 pl-5 text-sm text-ink-2">
            {ctx.not_used.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
          {ctx.missing_inputs.length > 0 && <p className="mt-3 text-sm text-muted">Absent at event time (the model handles this natively): {ctx.missing_inputs.map((m) => featureInfo(m, label).label).join(", ")}.</p>}
        </DrawerSection>
      )}
    </>
  );
}

function InputRows({ rows, label }: { rows: NonNullable<SignalContext["inputs"]>; label: (c: string) => string }) {
  if (rows.length === 0) return null;
  const flags = rows.filter((r) => r.name.startsWith("t_"));
  const main = rows.filter((r) => !r.name.startsWith("t_"));
  return (
    <>
      <InputList rows={main} label={label} />
      {flags.length > 0 && (
        <details className="disclosure mt-2">
          <summary>Timing flags ({flags.length})</summary>
          <InputList rows={flags} label={label} />
        </details>
      )}
    </>
  );
}

function InputList({ rows, label }: { rows: NonNullable<SignalContext["inputs"]>; label: (c: string) => string }) {
  return (
    <ul className="mt-3 divide-y divide-rule border-y border-rule">
      {rows.map((r) => {
        const info = featureInfo(r.name, label);
        const av = AVAILABILITY[r.availability];
        return (
          <li key={r.name} className="grid grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-4 gap-y-0.5 py-2 text-sm">
            <span className="min-w-0 text-ink-2">
              {info.label}
              <span className="num block text-2xs text-faint">{r.name}</span>
            </span>
            <span className="text-right">
              <span className="num text-ink">{formatFeature(info.fmt, r.value)}</span>
              {av && (
                <span className="block text-2xs text-muted" title={av.says}>
                  {av.label}
                </span>
              )}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

/* ---------------------------------------------------------------------------------------------- MATH */
function MathBody({ s }: { s: RiskSignal }) {
  const i = s.impact!;
  const modelled = !!s.provenance?.impact && i.predicted_severity != null;
  if (!modelled) {
    return (
      <p className="text-ink-2">
        The placeholder rule is a weighted sum: a prior for the event type, plus 0.20 times the strength of the tone, plus 0.10 times a corroboration term, then the same ceiling to a 1–10 score. It is a hand-set rule, not a fitted model.
      </p>
    );
  }
  return (
    <>
      <p className="mb-4 max-w-[60ch] text-ink-2">Impact is converted from the model's continuous estimate and calibrated against the severity that comparable events actually realised.</p>
      <DrawerSection title="1 · What is predicted"><Formula tex={TeX.TARGET} reading={TeX.TARGET_READING} /><div className="mt-4"><Formula tex={TeX.PREDICTION} reading={TeX.PREDICTION_READING} /></div></DrawerSection>
      <DrawerSection title="2 · From prediction to a 1–10 score">
        <Formula tex={TeX.SCORE_CHAIN} reading={TeX.SCORE_CHAIN_READING} />
        <div className="scroll-x mt-4">
          <table className="dtable">
            <caption className="mb-1 text-left text-xs text-muted">The fixed severity ladder (realised |z|, in σ, to score)</caption>
            <thead>
              <tr>
                <th scope="col">|z|</th>
                {TeX.SCORE_KNOTS.map((k) => (
                  <td key={k.z} className="num text-right">{k.z}</td>
                ))}
              </tr>
              <tr>
                <th scope="col">score</th>
                {TeX.SCORE_KNOTS.map((k) => (
                  <td key={k.z} className="num text-right">{k.v}</td>
                ))}
              </tr>
            </thead>
          </table>
        </div>
      </DrawerSection>
      <DrawerSection title="3 · This report"><Formula tex={TeX.quantise(i.raw, i.score)} reading={`The continuous estimate r = ${i.raw.toFixed(3)} gives a score of ${i.score}.`} /></DrawerSection>
      <DrawerSection title="4 · The range shown"><Formula tex={TeX.INTERVAL} reading="The bracket is empirical: what comparable past events actually realised, not a statistical guarantee." /></DrawerSection>
    </>
  );
}

/* ---------------------------------------------------------------------------------------------- TECH */
function TechBody({ s }: { s: RiskSignal }) {
  const audit = s.provenance?.impact ?? null;
  const { data: card } = useImpactModel(!!audit);
  const scope = audit ? card?.scopes.find((x) => x.scope === audit.scope) : undefined;
  const kind = impactKind(s);
  if (!audit) {
    return (
      <>
        <p className="text-ink-2">This score comes from a hand-set placeholder rule, not a trained model: it has no uncertainty range and has never been tested against market outcomes.</p>
        {s.provenance?.impact_note && <p className="mt-3 text-sm text-muted">Why the trained model did not score it: {s.provenance.impact_note}.</p>}
      </>
    );
  }
  const cal = scope?.calibration;
  return (
    <>
      <DrawerSection title="Model">
        <Dl
          rows={[
            ["Model", `${audit.model_id} · ${audit.model_version}`],
            ["Artifact", `sha256 ${audit.artifact_sha256.slice(0, 16)}…`],
            ["Features", audit.feature_schema],
            ["Scope", audit.scope],
            ["Status", `${KIND_LABEL[kind]} (${audit.lifecycle.toLowerCase()})`],
          ]}
        />
      </DrawerSection>
      <DrawerSection title="Lifecycle" note="A model moves up only by passing pre-registered acceptance checks, fixed before results were seen.">
        <ol className="space-y-1.5 text-sm">
          {LIFECYCLE_STEPS.map((st) => (
            <li key={st.id} className={clsx("flex gap-3", st.id === audit.lifecycle ? "font-medium text-ink" : "text-muted")} aria-current={st.id === audit.lifecycle ? "step" : undefined}>
              <span className="w-24 shrink-0">{st.label}{st.id === audit.lifecycle ? " (here)" : ""}</span>
              <span>{st.says}</span>
            </li>
          ))}
        </ol>
      </DrawerSection>
      {scope && (
        <>
          <DrawerSection title="Acceptance checks" note={scope.acceptance.rule}>
            <ul className="space-y-1.5 text-sm">
              {scope.acceptance.checks.map((c) => (
                <li key={c.label} className="flex gap-2">
                  <span className={clsx("w-14 shrink-0 font-medium", c.passed === true ? "text-pos" : c.passed === false ? "text-neg" : "text-muted")}>{c.passed === true ? "Passed" : c.passed === false ? "Not met" : "Not evaluable"}</span>
                  <span className="text-ink-2">{c.label}</span>
                </li>
              ))}
            </ul>
          </DrawerSection>
          {cal && (
            <DrawerSection title="Calibration" note="Checked on later periods the model did not train on.">
              <Dl
                rows={[
                  ["Stated range coverage", cal.heldout_coverage.value != null ? `${pct(cal.heldout_coverage.value, 1)} of held-out events fell inside the range shown (target ${pct(cal.nominal_coverage, 0)})` : "not evaluable"],
                  ["Extreme-move base rate", pct(cal.base_rate_extreme, 1)],
                  ["Reference history", `${cal.reference_episodes.toLocaleString("en-US")} episodes · ${cal.reference_period}`],
                ]}
              />
            </DrawerSection>
          )}
          <DrawerSection title="Limitations">
            <ul className="list-disc space-y-1.5 pl-5 text-sm text-ink-2">
              {scope.limitations.map((l) => (
                <li key={l}>{l}</li>
              ))}
              <li>There is no per-event retrieval: "comparable events" are statistics of the model's own score bucket, not individual past events.</li>
            </ul>
          </DrawerSection>
        </>
      )}
    </>
  );
}

/* --------------------------------------------------------------------------------------------- AUDIT */
function AuditBody({ s }: { s: RiskSignal }) {
  const p = s.provenance;
  return (
    <>
      <DrawerSection title="Source record">
        {p ? (
          <Dl rows={[["Adapter", p.adapter], ["Snapshot", p.snapshot_id], ["Record", p.record_ref], ["sha256", `${p.content_sha256.slice(0, 20)}…`], ["Time is", timestampNote(p.timestamp_origin)], ["URL", s.document.url ?? "none"]]} />
        ) : (
          <p className="text-sm text-muted">A demo fixture: hand-authored, no source record.</p>
        )}
      </DrawerSection>
      {p && (
        <>
          <DrawerSection title="Entity and de-duplication">
            <Dl
              rows={[
                ["Resolved by", `${ruleNote(p.entity_audit.rule)}${p.entity_audit.matched_text ? ` · matched ${p.entity_audit.matched_text}` : ""}`],
                ...(p.entity_audit.multi_entity ? [["Several companies", "mentioned: link confidence is capped"] as [string, React.ReactNode]] : []),
                ...(p.entity_audit.rejected.length > 0 ? [["Refused", `Refused: ${p.entity_audit.rejected.map((r) => `${r.matched_text} (${r.reason})`).join("; ")}`] as [string, React.ReactNode]] : []),
                ...(p.entity_audit.unmatched_cashtags.length > 0 ? [["Not in the entity list", p.entity_audit.unmatched_cashtags.map((t) => `$${t}`).join(" ")] as [string, React.ReactNode]] : []),
                ["Story cluster", `${p.dedup.cluster_id} · ${p.dedup.member_count} report${p.dedup.member_count === 1 ? "" : "s"}${p.dedup.exact_duplicates_folded ? ` · ${p.dedup.exact_duplicates_folded} exact duplicate${p.dedup.exact_duplicates_folded === 1 ? "" : "s"} folded away` : ""}`],
              ]}
            />
          </DrawerSection>
          <DrawerSection title="Versions">
            <Dl
              rows={[
                ["Signal", s.id],
                ["Sentiment model", s.model_versions.sentiment],
                ["Event model", s.model_versions.event],
                ["Impact model", s.model_versions.impact ?? "unavailable"],
                ["Entity resolver", s.model_versions.entity_resolver],
                ...(p.impact ? [["Impact artifact", `sha256 ${p.impact.artifact_sha256.slice(0, 16)}… · ${p.impact.feature_schema} · ${p.impact.lifecycle.toLowerCase()}`] as [string, React.ReactNode]] : []),
                ["Pipeline", p.pipeline_version],
                ["Scored at", `${dateTime(s.created_at)} (the replay clock)`],
              ]}
            />
          </DrawerSection>
        </>
      )}
    </>
  );
}

/* ----------------------------------------------------------------------------------------- SEVERITY WHY */
function SeverityWhyBody({ a }: { a: RiskAssessment }) {
  const sev = a.severity;
  if (!sev) return <p className="text-sm text-ink-2">{a.severity_note}</p>;
  return (
    <>
      <DrawerSection title="In one line">
        <p className="text-ink-2">
          {a.summary} {severityLede(sev)}
          {sev.omitted.length ? ` ${sev.omitted.length} input${sev.omitted.length > 1 ? "s" : ""} could not be used from what was known at the time and ${sev.omitted.length > 1 ? "were" : "was"} left out, with the reason.` : ""}
        </p>
      </DrawerSection>
      <DrawerSection title="How the score is built" note="Every line says where it comes from. The matrix is the starting point; the rest are bounded changes.">
        <ScoreBuildUp steps={sev.steps} score={sev.score} points={sev.points} />
      </DrawerSection>
      <DrawerSection title="Where the numbers come from">
        <p className="flex flex-wrap items-center gap-2 text-sm text-ink-2">
          <OriginChip origin="ASSUMPTION" /> The matrix anchors, the certainty and direction factors and the data adjustments are documented judgements in{" "}
          <span className="num">configs/severity.yaml</span>, fixed before the benchmark and not fitted to outcomes. No outcome labels are used, so the score is not supervised
          and not validated. Changing the judgement parameters moves it between {sev.low} and {sev.high}.
        </p>
      </DrawerSection>
      <DrawerSection title="What this score does not tell you">
        <ul className="list-disc space-y-1.5 pl-5 text-sm text-ink-2">
          <li>It is not a forecast of a price move, and not a probability of loss.</li>
          <li>It does not say whether prices go up or down.</li>
          <li>It is a triage level: how serious this kind of development usually is for a financial book, given what the report says.</li>
        </ul>
      </DrawerSection>
    </>
  );
}

/** All the event page's drawers, selected by ?open=. Closing removes the parameter. */
export function EventDrawers({
  s,
  ctx,
  ctxLoading,
  label,
  assessment,
  timeline,
}: {
  s: RiskSignal;
  ctx: SignalContext | undefined;
  ctxLoading: boolean;
  label: (c: string) => string;
  assessment?: RiskAssessment;
  timeline?: TimelineView;
}) {
  const [open, setOpen] = useOpenDrawer();
  const close = () => setOpen(null);
  const impact = !!s.impact;
  return (
    <>
      <Drawer open={open === "nlp"} onClose={close} title="How EventShock read this text" eyebrow="Understand">
        <NlpBody s={s} label={label} />
      </Drawer>
      <Drawer open={open === "why" && impact} onClose={close} title="Why this impact?" eyebrow="Impact">
        {impact && <WhyBody s={s} label={label} />}
      </Drawer>
      {assessment && (
        <>
          <Drawer open={open === "severity"} onClose={close} title="Why this severity?" eyebrow="Severity">
            <SeverityWhyBody a={assessment} />
          </Drawer>
          <Drawer open={open === "assessed"} onClose={close} title="What the assessment used" eyebrow="Only what was knowable when the report appeared" wide>
            <AssessedInputs a={assessment} tl={timeline} />
          </Drawer>
        </>
      )}
      <Drawer open={open === "inputs"} onClose={close} title={assessment ? "What the reference model saw" : "What the model saw"} eyebrow="Inputs, as available at event time" wide>
        <InputsBody s={s} ctx={ctx} loading={ctxLoading} label={label} />
      </Drawer>
      <Drawer open={open === "math" && impact} onClose={close} title="How impact is calculated" eyebrow="Mathematics" wide>
        {impact && <MathBody s={s} />}
      </Drawer>
      <Drawer open={open === "tech"} onClose={close} title="Technical details" eyebrow="Model, lifecycle, limits" wide>
        <TechBody s={s} />
      </Drawer>
      <Drawer open={open === "audit"} onClose={close} title="Audit trail" eyebrow="Provenance and reproducibility">
        <AuditBody s={s} />
      </Drawer>
    </>
  );
}
