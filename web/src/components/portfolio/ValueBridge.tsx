import clsx from "clsx";
import { useState } from "react";
import type { AssetClass, RiskFactor, StressResult } from "../../api/types";
import { ASSET_CLASS_LABEL, FACTOR_LABEL, money, pct, SCOPE_LABEL, shockValue } from "../../lib/format";
import { Glyph } from "../Glyph";
import { ASSET_ICON, FACTOR_ICON } from "../icons";

const CLASS_ORDER: AssetClass[] = ["EQUITY", "BOND", "LOAN", "DERIVATIVE", "CASH", "OTHER"];

/** How far apart the class table and the headline total may be before the bridge refuses to pretend they agree. */
const TOLERANCE = 0.01;

/**
 * The mechanism, left to right on the wire: the book by asset class → the shocks applied → where the loss lands → the positions that
 * carry it → the book after. Built only from the stress result (summary, contributions, shocks, top positions). The class rows must add up
 * to the reported change within a cent, or the bridge says so instead of drawing a story that does not reconcile. Hovering a class lights
 * it in both bars.
 */
export function ValueBridge({ r }: { r: StressResult }) {
  const [hover, setHover] = useState<string | null>(null);
  const sum = r.summary;
  const rows = r.contributions?.by_asset_class ?? [];
  if (!sum || rows.length === 0) return null;
  const classes = [...rows].sort((a, b) => CLASS_ORDER.indexOf(a.key as AssetClass) - CLASS_ORDER.indexOf(b.key as AssetClass));
  const classSum = classes.reduce((t, x) => t + x.delta, 0);
  const reconciled = Math.abs(classSum - sum.pnl) <= TOLERANCE;
  const losses = [...classes].filter((x) => x.delta !== 0).sort((a, b) => a.delta - b.delta);
  const maxAbs = Math.max(...classes.map((x) => Math.abs(x.delta)), 1e-9);
  const applied = r.shocks.filter((s) => s.applicable);
  const top = (r.contributions?.top_positions ?? []).filter((p) => p.delta !== 0).slice(0, 5);
  const topMax = Math.max(...top.map((p) => Math.abs(p.delta)), 1e-9);
  const removed = Math.max(0, -sum.pnl);

  const bar = (after: boolean) => (
    <div className="vb-bar" role="img" aria-label={after ? `The book after: ${money(sum.stressed_value)}` : `The book before, by asset class: ${money(sum.baseline_value)}`}>
      {classes.map((c) => {
        const v = after ? c.baseline_value + c.delta : c.baseline_value;
        if (v <= 0) return null;
        return (
          <span
            key={c.key}
            className={clsx("vb-seg", `vb-${c.key.toLowerCase()}`, hover === c.key && "is-hover", hover && hover !== c.key && "is-dim")}
            style={{ flexGrow: v }}
            onMouseEnter={() => setHover(c.key)}
            onMouseLeave={() => setHover(null)}
          >
            {v / sum.baseline_value > 0.09 && (
              <>
                {ASSET_CLASS_LABEL[c.key] ?? c.label}
                <span className="num">{money(v)}</span>
              </>
            )}
          </span>
        );
      })}
      {after && removed > 0 && <span className="vb-seg vb-removed" style={{ flexGrow: Math.max(removed, sum.baseline_value * 0.004) }} title={`${money(removed)} removed`} />}
    </div>
  );

  return (
    <div className="vb" aria-label="How the scenario moves the portfolio">
      <span className="vb-wire" aria-hidden="true" />
      <div className="vb-col">
        <p className="vb-k">The book</p>
        {bar(false)}
        <p className="vb-foot">
          {r.positions.length} positions · <span className="num">{money(sum.baseline_value)}</span>
        </p>
      </div>

      <div className="vb-col">
        <p className="vb-k">Shocks applied{r.severity ? ` · ×${r.severity.scale.toFixed(2)}` : ""}</p>
        <ul className="vb-shocks">
          {applied.slice(0, 5).map((k, i) => {
            const F = FACTOR_ICON[k.factor as RiskFactor];
            return (
              <li key={i} title={k.rationale}>
                {F && <Glyph icon={F} size="sm" shape="dashed" />}
                <span className="min-w-0">
                  <span className="num block font-semibold">{shockValue(k.factor, k.scaled_value)}</span>
                  <span className="block truncate text-xs text-muted">
                    {FACTOR_LABEL[k.factor] ?? k.factor} · {k.sector ?? k.currency ?? SCOPE_LABEL[k.scope] ?? k.scope}
                  </span>
                </span>
              </li>
            );
          })}
          {applied.length > 5 && <li className="text-xs text-muted">+{applied.length - 5} more shocks</li>}
        </ul>
      </div>

      <div className="vb-col">
        <p className="vb-k">Where it lands</p>
        <ul className="vb-lands">
          {losses.map((c) => {
            const A = ASSET_ICON[c.key as AssetClass];
            return (
              <li
                key={c.key}
                className={clsx(hover === c.key && "is-hover")}
                onMouseEnter={() => setHover(c.key)}
                onMouseLeave={() => setHover(null)}
              >
                <span className="flex items-center gap-2">
                  {A && <A size={15} />}
                  <span className="font-medium">{ASSET_CLASS_LABEL[c.key] ?? c.label}</span>
                  <span className={clsx("num ml-auto font-semibold", c.delta < 0 ? "text-neg" : "text-pos")}>{money(c.delta, { signed: true })}</span>
                </span>
                <span className="vb-meter" aria-hidden="true">
                  <i className={c.delta < 0 ? "bg-neg" : "bg-pos"} style={{ width: `${(Math.abs(c.delta) / maxAbs) * 100}%` }} />
                </span>
              </li>
            );
          })}
          {classes
            .filter((c) => c.delta === 0)
            .map((c) => (
              <li key={c.key} className="text-sm text-muted">
                {ASSET_CLASS_LABEL[c.key] ?? c.label} <span className="num">{money(0)}</span>: untouched
              </li>
            ))}
        </ul>
      </div>

      <div className="vb-col">
        <p className="vb-k">Largest positions hit</p>
        <ul className="vb-pos">
          {top.map((p) => (
            <li key={p.key}>
              <span className="flex gap-2">
                <b className="min-w-0 flex-1 truncate font-normal">{p.label}</b>
                <span className={clsx("num", p.delta < 0 ? "text-neg" : "text-pos")}>{money(p.delta, { signed: true })}</span>
              </span>
              <span className="vb-meter vb-meter-thin" aria-hidden="true">
                <i className={p.delta < 0 ? "bg-neg" : "bg-pos"} style={{ width: `${(Math.abs(p.delta) / topMax) * 100}%` }} />
              </span>
            </li>
          ))}
        </ul>
      </div>

      <div className="vb-col">
        <p className="vb-k">After</p>
        {bar(true)}
        <p className={clsx("vb-foot", sum.pnl < 0 ? "text-neg" : "text-ink-2")}>
          {removed > 0 ? (
            <>
              <span className="num">{money(removed)}</span> removed · {pct(removed / sum.baseline_value, 2)}
            </>
          ) : (
            <span className="num">{money(sum.pnl, { signed: true })}</span>
          )}
        </p>
      </div>

      {!reconciled && (
        <p className="vb-warn" role="status">
          The asset-class rows add up to {money(classSum, { signed: true })}, not the reported {money(sum.pnl, { signed: true })}: the breakdown is shown as reported, but it does not reconcile.
        </p>
      )}
    </div>
  );
}
