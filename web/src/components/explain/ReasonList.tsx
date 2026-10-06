import type { Explanation, Reason, ReasonKind } from "../../api/types";
import { KIND_ORDER, REASON_KIND } from "../../lib/explain";
import { KindBadge } from "../ProvenanceKind";
import { StateNotice } from "../StateNotice";

function KindTag({ kind }: { kind: ReasonKind }) {
  const m = REASON_KIND[kind];
  return m.badge ? <KindBadge kind={m.badge} label={m.label} /> : <span className="chip" title={m.says}>{m.label}</span>;
}

function Row({ r }: { r: Reason }) {
  return (
    <li className="border-t border-rule py-3 first:border-t-0" data-code={r.code}>
      <p className="text-sm text-ink">{r.text}</p>
      {r.detail && <p className="mt-1 text-xs text-ink-2">{r.detail}</p>}
      <p className="mt-1 text-2xs text-muted">
        <span className="num">{r.code}</span> · read from {r.source_ref}
        {r.provenance[0]?.ref_id ? ` · ${r.provenance[0].ref_id}` : ""}
      </p>
    </li>
  );
}

/** The reasons, grouped by the kind of statement they are, so a model output, a rule, an assumption and a historical observation can never be read as one another. */
export function ReasonList({ e }: { e: Explanation }) {
  const groups = KIND_ORDER.map((k) => ({ k, rs: e.reasons.filter((r) => r.kind === k) })).filter((g) => g.rs.length > 0);
  return (
    <div className="space-y-5">
      {groups.map(({ k, rs }) => (
        <section key={k} aria-label={REASON_KIND[k].label}>
          <div className="flex flex-wrap items-center gap-2">
            <KindTag kind={k} />
            <span className="text-xs text-muted">{REASON_KIND[k].says}</span>
          </div>
          <ul className="mt-1 list-none p-0">{rs.map((r, i) => <Row key={`${r.code}-${i}`} r={r} />)}</ul>
        </section>
      ))}
    </div>
  );
}

export function ExplanationView({ e }: { e: Explanation }) {
  if (e.availability === "UNAVAILABLE") return <StateNotice tone="info" what="Nothing to explain here." why={e.unavailable_reason ?? "No explanation is available for this."} />;
  return (
    <div className="space-y-4">
      <p className="font-display text-lg font-semibold leading-snug">{e.headline}</p>
      {e.availability === "PARTIAL" && e.reasons.length === 0 && <p className="text-sm text-ink-2">{e.unavailable_reason ?? "No reasons are available."}</p>}
      <ReasonList e={e} />
      {e.limitations.length > 0 && (
        <details className="disclosure">
          <summary>What this does not tell you</summary>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-ink-2">{e.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
        </details>
      )}
      <p className="text-xs text-muted">{e.labels[0]}</p>
    </div>
  );
}
