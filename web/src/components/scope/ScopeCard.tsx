import { Link } from "react-router-dom";
import type { RiskSignal } from "../../api/types";
import { REGION_LABEL, SCOPE_BLURB, SCOPE_LABEL, subjectLine, subjectOf, THEME_LABEL } from "../../lib/scope";
import { ScopeTag } from "./Tags";

/** "What is this about?" The reading that comes before the event type: a company, a sector, the market, or nothing. */
export function ScopeCard({ s }: { s: RiskSignal }) {
  const sc = s.scope;
  const terms = sc.matched_terms;
  return (
    <div className="reading">
      <p className="eyebrow">What it is about</p>
      <p className="reading-value">{subjectLine(subjectOf(s))}</p>
      <p className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted">
        <ScopeTag level={sc.level} sector={sc.sector} strength={sc.strength} />
        <span>{SCOPE_BLURB[sc.level]}</span>
      </p>
      <p className="mt-3 max-w-[60ch] text-sm text-ink-2">{sc.note}</p>
      {(sc.themes.length > 0 || sc.regions.length > 0 || Object.keys(terms).length > 0) && (
        <dl className="mt-3 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1.5 text-sm">
          {sc.themes.length > 0 && (
            <>
              <dt className="text-muted">Themes</dt>
              <dd>{sc.themes.map(THEME_LABEL).join(", ")}</dd>
            </>
          )}
          {sc.regions.length > 0 && (
            <>
              <dt className="text-muted">Regions</dt>
              <dd>{sc.regions.map((r) => REGION_LABEL[r] ?? r).join(", ")}</dd>
            </>
          )}
          {Object.entries(terms).map(([dim, list]) => (
            <div key={dim} className="contents">
              <dt className="text-muted">Matched {dim} terms</dt>
              <dd className="num">{list.join(", ")}</dd>
            </div>
          ))}
        </dl>
      )}
      <p className="mt-3 text-xs text-muted">
        {sc.level === "COMPANY"
          ? "Dictionary entity resolution."
          : sc.level === "UNRESOLVED"
            ? `${SCOPE_LABEL.UNRESOLVED} is a result, not a failure: EventShock does not invent a subject.`
            : "Vocabulary rules (scope-v1), not a trained model; a rule tier is not a probability."}
        {" "}
        <Link className="text-accent underline underline-offset-2" to="/evidence?tab=scope">How this was measured</Link>
      </p>
    </div>
  );
}
