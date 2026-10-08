import { type ReactNode, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useIntelligence } from "../../api/hooks";
import type { EventIntelligence } from "../../api/types";
import {
  AVAILABILITY_LABEL,
  CONFLICT_LABEL,
  LIFECYCLE_BLURB,
  LIFECYCLE_LABEL,
  NOVELTY_BLURB,
  NOVELTY_LABEL,
  SCOPE_TYPE_BLURB,
  SCOPE_TYPE_LABEL,
  STRENGTH_LABEL,
  TIER_LABEL,
  factorLabel,
  hoursLabel,
  when,
} from "../../lib/intelligence";
import { pct } from "../../lib/format";
import { Eye, Lifecycle, Sources, STATION_ICON } from "../icons";

const Target = STATION_ICON.exposure;
import { Chapter } from "../event/Chapter";
import { Drawer, DrawerSection, useOpenDrawer } from "../Drawer";
import { StateNotice } from "../StateNotice";
import { Skeleton, StatusTag } from "../ui";
import { KindBadge } from "../ProvenanceKind";
import { ContradictionPanel } from "./ContradictionView";
import { LifecycleTimeline } from "./LifecycleTimeline";
import { ScopeEvidence, ScopePath } from "./ScopePath";
import { ReportsTable, SourceTimeline } from "./SourceTimeline";

type Intel = EventIntelligence;

function Tile({ label, value, note, aside, children }: { label: string; value: ReactNode; note?: ReactNode; aside?: ReactNode; children?: ReactNode }) {
  return (
    <div className="intel-row" role="group" aria-label={label}>
      <p className="intel-k">{label}</p>
      <p className="intel-v">{value}</p>
      {note && <p className="intel-note">{note}</p>}
      {children}
      {aside && <div className="mt-1.5">{aside}</div>}
    </div>
  );
}

/** One question about the event, answered by a few rows: a spec sheet, not a wall of equal cards. */
function Group({ title, icon: I, lead = false, children }: { title: string; icon: (p: { size?: number }) => React.JSX.Element; lead?: boolean; children: ReactNode }) {
  return (
    <section className={lead ? "intel-group intel-lead" : "intel-group"} aria-label={title}>
      <h3 className="intel-group-title">
        <I size={15} /> {title}
      </h3>
      {children}
    </section>
  );
}

const strengthTone = (t: string) => (t === "STRONG" ? "ok" : t === "MODERATE" ? "demo" : "warn");

/** Four questions, kept apart on purpose: how well it is evidenced (corroboration) and the model's own confidence are different rows. */
export function IntelligenceTiles({ i }: { i: Intel }) {
  const e = i.evidence;
  const conf = e.model_confidence;
  const ev = conf.find((m) => m.stage === "event");
  const se = conf.find((m) => m.stage === "sentiment");
  const strength = e.evidence_strength;
  return (
    <div className="intel-groups" aria-label="Event intelligence at a glance">
      <Group title="How well it is evidenced" icon={Sources} lead>
        <Tile
          label="Evidence strength"
          value={<StatusTag tone={strengthTone(strength.tier)}>{STRENGTH_LABEL[strength.tier] ?? strength.tier}</StatusTag>}
          note={`${e.independent_sources} independent source${e.independent_sources === 1 ? "" : "s"} among ${e.source_count} report${e.source_count === 1 ? "" : "s"}.`}
        />
        <Tile
          label="Corroboration"
          value={e.source_diversity != null ? `Diversity ${e.source_diversity.toFixed(2)}` : "n/a"}
          note={`${e.syndicated_copies} cop${e.syndicated_copies === 1 ? "y" : "ies"} of another report. ${e.authoritative_supported ? `${e.authoritative_sources} authoritative source${e.authoritative_sources === 1 ? "" : "s"}.` : "No source is known to be authoritative."}`}
        />
        <Tile
          label="Conflicts"
          value={CONFLICT_LABEL[i.contradiction.state]}
          note={i.contradiction.claims_extracted === 0 ? "No tracked claim was found, so none could be compared." : `${i.contradiction.claims_extracted} claim${i.contradiction.claims_extracted === 1 ? "" : "s"} compared.`}
        />
        <Tile
          label="Model confidence"
          value={ev?.value != null ? `Event ${pct(ev.value, 0)}` : "Event n/a"}
          note={`${se?.value != null ? `Sentiment ${pct(se.value, 0)}. ` : ""}What the models say of their own output; it does not measure corroboration.`}
          aside={<KindBadge kind="model" />}
        />
      </Group>
      <Group title="What it is" icon={Eye}>
        <Tile
          label="Event"
          value={i.event.event_label ?? (i.event.event_status === "CLASSIFIED" ? i.event.event_type : "Not a classified event")}
          note={<>{i.event.event_subtype_label && i.event.event_subtype_label !== "Other" ? `${i.event.event_subtype_label} · ` : ""}tone {i.event.sentiment_label ?? ""} ({i.event.sentiment >= 0 ? "+" : "−"}{Math.abs(i.event.sentiment).toFixed(2)})</>}
        />
        <Tile
          label="Scope"
          value={i.scope.scope_value ? `${SCOPE_TYPE_LABEL[i.scope.scope_type]} · ${i.scope.scope_value}` : SCOPE_TYPE_LABEL[i.scope.scope_type]}
          note={`${SCOPE_TYPE_BLURB[i.scope.scope_type]} Confidence tier: ${TIER_LABEL[i.scope.scope_confidence.tier]}.`}
        />
        <Tile
          label="Impact"
          value={i.event.severity_score != null ? `Severity ${i.event.severity_score}/10` : "Severity unavailable"}
          note={
            <>
              {i.event.severity_band ? `${i.event.severity_band}. ` : ""}A triage scale, not outcome-calibrated.
              {i.event.impact_score != null ? ` The trained impact stage says ${i.event.impact_score}/10 (${i.event.impact_origin === "MODEL" ? "experimental model" : "placeholder rule"}).` : " No trained impact was scored."}
            </>
          }
        />
      </Group>
      <Group title="How it is moving" icon={Lifecycle}>
        <Tile
          label="Lifecycle"
          value={i.lifecycle.state ? LIFECYCLE_LABEL[i.lifecycle.state] : AVAILABILITY_LABEL[i.lifecycle.availability]}
          note={i.lifecycle.state ? LIFECYCLE_BLURB[i.lifecycle.state] : i.lifecycle.reason}
        />
        <Tile label="Novelty" value={NOVELTY_LABEL[i.novelty.label] ?? i.novelty.label} note={i.novelty.reason ?? NOVELTY_BLURB[i.novelty.label]} />
        <Tile
          label="Narrative velocity"
          value={i.velocity.velocity_per_hour != null ? `${i.velocity.velocity_per_hour.toFixed(2)} sources/h` : AVAILABILITY_LABEL[i.velocity.availability]}
          note={i.velocity.source_growth ?? i.velocity.reason}
        />
      </Group>
      <Group title="Who it touches" icon={Target}>
        <Tile
          label="Affected entities"
          value={i.affected.entities.length ? `${i.affected.entities.length} named` : "None named"}
          note={i.affected.entities.length ? i.affected.entities.slice(0, 3).map((x) => `${x.name}${x.resolved ? "" : " (not in the entity master)"}`).join("; ") : "No company, institution or regulator was identified."}
        />
        <Tile
          label="Affected sectors"
          value={i.affected.sectors.length ? i.affected.sectors.map((s) => s.sector).join(", ") : "None identified"}
          note={i.affected.regions.length ? `Regions: ${i.affected.regions.join(", ")}.` : undefined}
        />
      </Group>
    </div>
  );
}

function Section({ title, hint, open, children }: { title: string; hint?: ReactNode; open?: boolean; children: ReactNode }) {
  return (
    <details className="disclosure mt-5" open={open}>
      <summary>
        {title}
        {hint && <span className="ml-2 font-normal text-muted">{hint}</span>}
      </summary>
      <div className="mt-4">{children}</div>
    </details>
  );
}

function Affected({ i }: { i: Intel }) {
  const a = i.affected;
  return (
    <div className="grid gap-6 md:grid-cols-3">
      <div>
        <p className="eyebrow">Entities</p>
        {a.entities.length === 0 ? <p className="mt-1 text-sm text-muted">None identified.</p> : (
          <ul className="mt-1 space-y-1 text-sm">
            {a.entities.map((x) => (
              <li key={`${x.name}-${x.role}`}>
                <span className="font-medium text-ink">{x.name}</span> <span className="text-muted">{x.kind.toLowerCase()} · {x.role}</span>
                {!x.resolved && <span className="ml-1 text-xs text-muted">(a mention only: not in the entity master)</span>}
              </li>
            ))}
          </ul>
        )}
      </div>
      <div>
        <p className="eyebrow">Sectors and regions</p>
        <ul className="mt-1 space-y-1 text-sm">
          {a.sectors.length === 0 && <li className="text-muted">No sector identified.</li>}
          {a.sectors.map((s) => (
            <li key={s.sector}><span className="font-medium text-ink">{s.sector}</span> <span className="text-xs text-muted">{s.basis}</span></li>
          ))}
          {a.regions.map((r) => <li key={r}>{r}</li>)}
        </ul>
      </div>
      <div>
        <p className="eyebrow">Risk factors <KindBadge kind="scenario" label="Assumption" className="ml-1" /></p>
        <ul className="mt-1 space-y-1 text-sm">
          {a.risk_factors.length === 0 && <li className="text-muted">None linked.</li>}
          {a.risk_factors.map((f) => (
            <li key={f.factor}><span className="font-medium text-ink">{factorLabel(f.factor)}</span> <span className="text-xs text-muted">{f.basis}</span></li>
          ))}
        </ul>
      </div>
      <p className="max-w-[72ch] text-xs text-muted md:col-span-3">{a.note}</p>
    </div>
  );
}

function Novelty({ i }: { i: Intel }) {
  const n = i.novelty;
  return (
    <div className="space-y-3 text-sm">
      <p className="text-ink-2">
        <span className="font-medium text-ink">{NOVELTY_LABEL[n.label]}.</span> {NOVELTY_BLURB[n.label]} <span className="text-muted">(rule {n.rule})</span>
      </p>
      {n.continuation_indicators.length > 0 && <ul className="list-disc space-y-1 pl-5 text-ink-2">{n.continuation_indicators.map((c) => <li key={c}>{c}</li>)}</ul>}
      {n.new_information.length > 0 && <p className="text-ink-2">New in this event (numbers and names the earlier one did not carry): <span className="font-medium text-ink">{n.new_information.join(", ")}</span></p>}
      {n.nearest_prior.length > 0 && (
        <div className="scroll-x">
          <table className="dtable min-w-[36rem]">
            <caption className="sr-only">Nearest earlier events of the same subject</caption>
            <thead><tr><th scope="col">Earlier event</th><th scope="col">First seen</th><th scope="col" className="text-right">Similarity</th><th scope="col">Then</th></tr></thead>
            <tbody>
              {n.nearest_prior.map((p) => (
                <tr key={p.event_id}>
                  <th scope="row" className="max-w-[24rem] !font-normal"><Link to={`/events/${p.signal_id}`} className="text-accent underline underline-offset-2">{p.headline}</Link></th>
                  <td className="num whitespace-nowrap text-sm">{when(p.first_seen)}</td>
                  <td className="num text-right text-sm">{p.similarity.toFixed(2)}</td>
                  <td className="text-sm">{p.lifecycle_then ? LIFECYCLE_LABEL[p.lifecycle_then] ?? p.lifecycle_then : "n/a"}{p.same_event_class ? "" : " · different class"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="text-xs text-muted">The pipeline's own novelty score ({n.novelty_score.toFixed(2)}{n.novelty_measured ? "" : ", not measured: no issuer to compare against"}) is unchanged and separate from this label.</p>
    </div>
  );
}

function Downstream({ i }: { i: Intel }) {
  const r = i.relevance;
  const s = i.stress;
  return (
    <div className="space-y-4 text-sm">
      {r && (
        <div>
          <p className="eyebrow">Portfolio relevance <KindBadge kind="historical" label="Book's holdings" className="ml-1" /></p>
          <p className="mt-1 text-ink-2">{r.summary}</p>
        </div>
      )}
      <div>
        <p className="eyebrow">Stress under the default scenario <KindBadge kind="scenario" className="ml-1" /></p>
        {s.availability === "AVAILABLE" && s.pnl != null && s.pnl_pct != null && s.baseline_value != null && s.stressed_value != null ? (
          <p className="mt-1 text-ink-2">
            {s.scenario_name}: the book moves from {s.baseline_value.toLocaleString("en-US", { maximumFractionDigits: 0 })} to {s.stressed_value.toLocaleString("en-US", { maximumFractionDigits: 0 })} ({pct(s.pnl_pct, 2, true)}). {s.note}
          </p>
        ) : (
          <p className="mt-1 text-ink-2">Not run: {s.reason ?? "no defensible scenario mapping."} You can still run it as a what-if on the Stress page.</p>
        )}
        {i.event.severity_score != null && <p className="mt-1 text-xs text-muted">Severity {i.event.severity_score}/10{s.trigger_threshold != null ? `, automatic trigger ${s.trigger_threshold}` : ""}.</p>}
        <Link to={`/stress?signal=${i.signal_id}`} className="mt-2 inline-block text-accent underline underline-offset-2">Open the Stress Lab</Link>
      </div>
    </div>
  );
}

function Abstentions({ i }: { i: Intel }) {
  if (i.abstentions.length === 0) return null;
  return (
    <StateNotice
      tone="info"
      what="What EventShock does not claim here"
      why="Each of these is left blank on purpose. A missing fact is never filled in."
      details={
        <ul className="space-y-1">
          {i.abstentions.map((a) => (
            <li key={a.field}><span className="font-medium text-ink">{a.field}: {a.state.replaceAll("_", " ").toLowerCase()}</span>. {a.reason}</li>
          ))}
        </ul>
      }
    />
  );
}

/** The whole view, for a response already in hand (the Event page fetches it; the Analyze page receives it). */
export function IntelligenceView({ i, asOfControl }: { i: Intel; asOfControl?: ReactNode }) {
  const [open, setOpen] = useOpenDrawer();
  const e = i.evidence;
  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="eyebrow">Scope</p>
          <div className="mt-1.5"><ScopePath scope={i.scope} /></div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {asOfControl}
          <button type="button" className="btn btn-sm" onClick={() => setOpen("intelligence")}>How is this worked out?</button>
        </div>
      </div>
      <div className="mt-5"><IntelligenceTiles i={i} /></div>
      <div className="mt-5"><Abstentions i={i} /></div>

      <Section title="Where the subject came from" hint={`${SCOPE_TYPE_LABEL[i.scope.scope_type]}, ${i.scope.resolution_status.toLowerCase()}`}>
        <ScopeEvidence scope={i.scope} />
      </Section>
      <Section title="Evidence and corroboration" hint={`${e.independent_sources} independent of ${e.source_count} reports`} open={e.independent_sources > 1}>
        <div className="space-y-5">
          <div>
            <p className="font-medium text-ink">Evidence strength: {STRENGTH_LABEL[e.evidence_strength.tier]} <span className="font-normal text-muted">(rule {e.evidence_strength.rule})</span></p>
            <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-ink-2">{e.evidence_strength.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
            <p className="mt-2 max-w-[72ch] text-xs text-muted">{e.note}</p>
          </div>
          <div>
            <p className="eyebrow">How the event was reported over time</p>
            <div className="mt-2"><SourceTimeline velocity={i.velocity} /></div>
          </div>
          <ReportsTable group={i.group} />
          <p className="text-xs text-muted">{i.group.grouping_note}</p>
          <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
            <div><dt className="eyebrow">Entity confidence</dt><dd>{e.entity_confidence != null ? `${pct(e.entity_confidence, 0)} (${e.entity_basis})` : e.entity_basis}</dd></div>
            <div><dt className="eyebrow">Scope confidence tier</dt><dd>{TIER_LABEL[e.scope_confidence]}</dd></div>
            {e.model_confidence.map((m) => (
              <div key={m.stage}><dt className="eyebrow">Model confidence: {m.stage}</dt><dd>{m.value != null ? pct(m.value, 0) : "no probability"}<span className="block text-xs text-muted">{m.status}; {m.basis}</span></dd></div>
            ))}
          </dl>
        </div>
      </Section>
      <Section title="Conflicting reports" hint={CONFLICT_LABEL[i.contradiction.state]} open={i.contradiction.state !== "NO_CONFLICT"}>
        <ContradictionPanel v={i.contradiction} />
      </Section>
      <Section title="Lifecycle timeline" hint={i.lifecycle.state ? LIFECYCLE_LABEL[i.lifecycle.state] : "unavailable"}>
        <LifecycleTimeline life={i.lifecycle} />
      </Section>
      <Section title="Novelty: what it was compared with" hint={NOVELTY_LABEL[i.novelty.label]}>
        <Novelty i={i} />
      </Section>
      <Section title="Affected entities, sectors and risk factors">
        <Affected i={i} />
      </Section>
      <Section title="Portfolio relevance and stress">
        <Downstream i={i} />
      </Section>

      <Drawer open={open === "intelligence"} onClose={() => setOpen(null)} title="How event intelligence is worked out" eyebrow="Method and limits" wide>
        <DrawerSection title="What each part is">
          <ul className="list-disc space-y-1.5 pl-5 text-sm text-ink-2">{i.labels.map((l) => <li key={l}>{l}</li>)}</ul>
        </DrawerSection>
        <DrawerSection title="Where it came from" note="Provenance of this view.">
          <p className="text-sm text-ink-2">
            Channel {i.provenance.channel.toLowerCase()} · adapter {i.provenance.adapter} · timestamp {i.provenance.timestamp_origin.toLowerCase().replaceAll("_", " ")}
            {i.provenance.clock_trusted ? "" : " (assigned by the replay, not trusted)"} · computed from reports up to {when(i.as_of)}. Event {i.group.event_id}.
          </p>
        </DrawerSection>
        <DrawerSection title="Limits">
          <ul className="list-disc space-y-1.5 pl-5 text-sm text-ink-2">{i.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
        </DrawerSection>
      </Drawer>
    </div>
  );
}

/** The Event page's panel: fetches the view, lets the reader step back to an earlier report, and hides itself where the layer is absent. */
export function IntelligencePanel({ signalId, enabled }: { signalId: string; enabled: boolean }) {
  const [asOf, setAsOf] = useState<string | null>(null);
  const { data: i, isLoading, error, isFetching } = useIntelligence(signalId, enabled, asOf);
  const times = useRef<string[]>([]);
  useEffect(() => {
    setAsOf(null);
    times.current = [];
  }, [signalId]);
  if (asOf === null && i) times.current = [...new Set(i.group.reports.map((r) => r.published_at))].sort();
  if (!enabled) return null;
  return (
    <Chapter
      id="intelligence"
      eyebrow="Event intelligence"
      title="What is known about this event"
      lede="Its subject, how well it is evidenced, how it is moving, whether reports disagree, and where it is in its life. Every part can say “not enough evidence”."
      badge={i ? <span className="num text-xs text-muted">as of {when(i.as_of)}</span> : undefined}
    >
      {isLoading && <div role="status" aria-label="Loading event intelligence" className="space-y-3"><Skeleton className="h-8 w-1/2" /><Skeleton className="h-40 w-full" /></div>}
      {error && <StateNotice tone="warn" what="Event intelligence is not available for this event" why={error.message} />}
      {i && (
        <div aria-busy={isFetching}>
          <IntelligenceView
            i={i}
            asOfControl={
              times.current.length > 1 ? (
                <label className="flex items-center gap-2 text-sm text-ink-2">
                  View as of
                  <select className="field !w-auto" value={asOf ?? ""} onChange={(ev) => setAsOf(ev.target.value || null)} aria-label="View the event as it stood at an earlier report">
                    <option value="">the latest report</option>
                    {times.current.slice(0, -1).map((t) => <option key={t} value={t}>{when(t)}</option>)}
                  </select>
                </label>
              ) : undefined
            }
          />
        </div>
      )}
    </Chapter>
  );
}

/** A compact result for the Analyze page: the headline facts and a link to the whole view. */
export function IntelligenceSummary({ i, hours }: { i: Intel; hours?: boolean }) {
  return (
    <div className="card card-pad" aria-label="Event intelligence">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="card-title">Event intelligence</h3>
        <Link to={`/events/${i.signal_id}#intelligence`} className="text-sm text-accent underline underline-offset-2">Open the full view</Link>
      </div>
      <div className="mt-3"><ScopePath scope={i.scope} /></div>
      <dl className="mt-4 grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
        <div><dt className="eyebrow">Lifecycle</dt><dd>{i.lifecycle.state ? LIFECYCLE_LABEL[i.lifecycle.state] : AVAILABILITY_LABEL[i.lifecycle.availability]}</dd></div>
        <div><dt className="eyebrow">Novelty</dt><dd>{NOVELTY_LABEL[i.novelty.label]}</dd></div>
        <div><dt className="eyebrow">Evidence strength</dt><dd>{STRENGTH_LABEL[i.evidence.evidence_strength.tier]} · {i.evidence.independent_sources} independent of {i.evidence.source_count}</dd></div>
        <div><dt className="eyebrow">Conflicts</dt><dd>{CONFLICT_LABEL[i.contradiction.state]}</dd></div>
        {hours && <div><dt className="eyebrow">Covered over</dt><dd>{hoursLabel(i.group.first_seen && i.group.last_seen ? (new Date(i.group.last_seen).getTime() - new Date(i.group.first_seen).getTime()) / 3.6e6 : null)}</dd></div>}
      </dl>
      {i.abstentions.length > 0 && (
        <p className="mt-3 text-xs text-muted">Not claimed: {i.abstentions.map((a) => a.field).join(", ")}. The full view says why.</p>
      )}
    </div>
  );
}
