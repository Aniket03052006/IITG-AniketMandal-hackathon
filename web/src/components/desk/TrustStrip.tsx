import { Link } from "react-router-dom";
import { useAssessment, useIntelligence, useMeta, useSignal } from "../../api/hooks";
import { Lifecycle, Model, Quote, Sources } from "../icons";
import { Glyph } from "../Glyph";

type Item = { key: string; icon: (p: { size?: number }) => React.JSX.Element; head: React.ReactNode; sub: string };

/**
 * "Why trust it": the evidence behind the selected signal, never a generic confidence badge. Each item says what kind of number
 * it is (source count, a model's own confidence, a verbatim quote check, a rule-driven lifecycle) and links to the full evidence chapter.
 */
export function TrustStrip({ signalId }: { signalId: string }) {
  const { data: meta } = useMeta();
  const sig = useSignal(signalId);
  const a = useAssessment(signalId, meta?.capabilities.assessment === true);
  const intel = useIntelligence(signalId, meta?.capabilities.intelligence === true);
  const s = sig.data;
  if (!s) return null;
  const ev = intel.data?.evidence;
  const items: Item[] = [];
  const srcN = ev?.independent_sources ?? s.evidence.source_count;
  const domains = ev?.unique_domains ?? s.evidence.unique_domain_count;
  items.push({
    key: "sources",
    icon: Sources,
    head: (
      <>
        <span className="num">{srcN}</span> {ev ? "independent" : ""} source{srcN === 1 ? "" : "s"}
        {ev && ev.evidence_strength ? <span className="text-muted">, {ev.evidence_strength.tier.toLowerCase()} evidence</span> : null}
      </>
    ),
    sub: `${domains} domain${domains === 1 ? "" : "s"}${ev && ev.syndicated_copies > 0 ? `, ${ev.syndicated_copies} syndicated cop${ev.syndicated_copies === 1 ? "y" : "ies"} not counted twice` : ""} · source count`,
  });
  const quotes = a.data?.reading.evidence.length ?? 0;
  if (a.data) {
    items.push({
      key: "quotes",
      icon: Quote,
      head: quotes > 0 ? (<><span className="num">{quotes}</span> quote{quotes === 1 ? "" : "s"} checked against the text</>) : "No verbatim quote supports the reading",
      sub: `${a.data.extraction.mode === "LLM" ? "AI reading, grounded" : "rule-based reading"}${a.data.severity ? ` · reliability ${a.data.severity.reliability.level}` : ""}`,
    });
  } else if (s.evidence.model_confidence != null) {
    items.push({
      key: "confidence",
      icon: Model,
      head: (<>Model confidence <span className="num">{Math.round(s.evidence.model_confidence * 100)}%</span></>),
      sub: "the classifier's own probability · not a validated accuracy",
    });
  }
  const lc = intel.data?.lifecycle;
  const nov = intel.data?.novelty;
  if (lc && lc.availability === "AVAILABLE" && lc.state) {
    items.push({ key: "lifecycle", icon: Lifecycle, head: <>Lifecycle: {lc.state.toLowerCase()}</>, sub: `${nov && nov.availability === "AVAILABLE" ? `${nov.label} · ` : ""}rule-driven, never from falling volume` });
  } else if (s.evidence.novelty_measured) {
    items.push({ key: "novelty", icon: Lifecycle, head: (<>Novelty <span className="num">{s.evidence.novelty_score.toFixed(2)}</span></>), sub: "how new the story was when it appeared · measured" });
  }
  return (
    <section className="trust" aria-label="Why trust it">
      <h3 className="trust-title">Why trust it</h3>
      <ul className="trust-list">
        {items.map((it) => (
          <li key={it.key}>
            <Glyph icon={it.icon} size="md" />
            <span className="min-w-0">
              <span className="block font-semibold">{it.head}</span>
              <span className="block text-xs text-muted">{it.sub}</span>
            </span>
          </li>
        ))}
      </ul>
      <Link className="btn btn-ghost" to={`/events/${s.id}#evidence`}>
        All the evidence
      </Link>
    </section>
  );
}
