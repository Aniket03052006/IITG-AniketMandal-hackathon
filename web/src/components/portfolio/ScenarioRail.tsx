import clsx from "clsx";
import type { RiskFactor, Scenario } from "../../api/types";
import { shockValue } from "../../lib/format";
import { CategoryGlyph } from "../Glyph";
import { FACTOR_ICON } from "../icons";

/** Factors that only the multi-factor scenarios move: a card that carries them says so. */
const MULTI = new Set<RiskFactor>(["FX_PCT", "COMMODITY_PCT"]);

/**
 * Every scenario the engine knows, as visible cards: the one mapped to this event is marked, and picking any card runs it.
 * Replaces a hidden select: a judge sees at once that the same event can be stressed under several assumptions.
 */
export function ScenarioRail({
  scenarios,
  selected,
  mapped,
  onPick,
  disabled = false,
  pending = false,
}: {
  scenarios: Scenario[];
  selected: string;
  mapped?: string;
  onPick: (id: string) => void;
  disabled?: boolean;
  pending?: boolean;
}) {
  const ordered = [...scenarios].sort((a, b) => Number(b.id === mapped) - Number(a.id === mapped));
  return (
    <section aria-label="Choose a scenario" className="srail-wrap">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-sans text-md font-semibold">Choose a scenario</h2>
        <p className="text-xs text-muted">Each is a set of assumed shocks, scaled by the event's severity. Picking one runs it.</p>
      </div>
      <ul className="srail" role="list">
        {ordered.map((sc) => {
          const on = sc.id === selected;
          const multi = sc.shocks.some((k) => MULTI.has(k.factor as RiskFactor));
          const factors = [...new Set(sc.shocks.map((k) => k.factor as RiskFactor))];
          return (
            <li key={sc.id}>
              <button
                type="button"
                className={clsx("srail-card", on && "is-on")}
                aria-pressed={on}
                disabled={disabled}
                data-loading={on && pending ? "true" : undefined}
                onClick={() => onPick(sc.id)}
              >
                <span className="flex items-center gap-2">
                  <CategoryGlyph category={sc.category} size="sm" tone={on ? "accent" : "neutral"} />
                  <span className="srail-name">{sc.name}</span>
                </span>
                <span className="srail-shocks num">
                  {sc.shocks
                    .slice(0, 3)
                    .map((k) => shockValue(k.factor, k.value))
                    .join(" · ")}
                  {sc.shocks.length > 3 ? ` +${sc.shocks.length - 3}` : ""}
                </span>
                <span className="srail-factors" aria-label={`Moves ${factors.length} risk factor${factors.length === 1 ? "" : "s"}`}>
                  {factors.map((f) => {
                    const F = FACTOR_ICON[f];
                    return F ? <F key={f} size={13} /> : null;
                  })}
                  {multi && <span className="srail-tag">multi-factor</span>}
                  {sc.id === mapped && <span className="srail-tag srail-tag-on">matches this event</span>}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
