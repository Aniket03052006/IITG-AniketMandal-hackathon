import { useMemo, useState } from "react";
import type { PropagationGraph } from "../../api/types";
import { layoutContagion, type MapEdge, type MapNode } from "../../lib/contagion";
import { STATUS_LABEL } from "../../lib/propagation";

const DASH: Record<string, string | undefined> = { OBSERVED: undefined, SCENARIO_ASSUMPTION: "7 5", USER_ASSUMPTION: "2 4" };
const TONE_WORD = { hurts: "hurts it", benefits: "benefits it", neutral: "" } as const;

const strokeWidth = (e: MapEdge) => (e.origin === "held" ? 1 : e.weight == null ? 1.5 : 1.5 + Math.min(Math.abs(e.weight), 1) * 2.5);

function describe(e: MapEdge, nodes: Map<string, MapNode>): string {
  const a = nodes.get(e.source)?.full ?? e.source;
  const b = nodes.get(e.target)?.full ?? e.target;
  const w = e.weight != null ? `, weight ${e.weight > 0 ? "+" : ""}${e.weight.toFixed(2)}${TONE_WORD[e.tone] ? ` (${TONE_WORD[e.tone]})` : ""}` : "";
  return `${a} → ${b}: ${STATUS_LABEL[e.status].toLowerCase()}${w}. ${e.basis} [${e.rule}]`;
}

/**
 * The exposure chain as a picture: event → risk factors → where it lands (asset class, sector, industry, each with its share of the book) → the
 * largest holdings it reaches. Solid lines are facts, dashed ones are configured assumptions, dotted ones are yours; red hurts the target, green
 * benefits it. It draws the propagation graph and nothing else (a mapping, never a causal model, and not a forecast): hover or focus a node to follow
 * its lines. The list of edges below it carries every edge with its rule and evidence, so nothing here is only visual.
 */
export function ContagionMap({ g }: { g: PropagationGraph }) {
  const layout = useMemo(() => layoutContagion(g), [g]);
  const [active, setActive] = useState<string | null>(null);
  if (!layout) return null;
  const nodes = new Map(layout.nodes.map((n) => [n.id, n]));
  const incident = active ? layout.edges.filter((e) => e.source === active || e.target === active) : [];
  const lit = new Set<string>(active ? [active, ...incident.flatMap((e) => [e.source, e.target])] : []);
  const factors = layout.nodes.filter((n) => n.kind === "factor").length;
  const targets = layout.nodes.filter((n) => n.kind === "target").length;
  const summary = `Contagion map: one event reaches ${factors} risk ${factors === 1 ? "factor" : "factors"}, which land on ${targets} parts of the book, and ${layout.holdingsShown} of the ${layout.holdingsReached} holdings reached are shown.`;
  const hold = (id: string | null) => ({ onMouseEnter: () => setActive(id), onMouseLeave: () => setActive(null), onFocus: () => setActive(id), onBlur: () => setActive(null) });
  return (
    <figure className="cmap" aria-label="Contagion map">
      <figcaption className="mb-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-sm font-semibold">How it spreads: event → risk factor → book → holdings</span>
        <span className="text-xs text-muted">hover or focus a box to follow its lines</span>
      </figcaption>
      <div className="cmap-scroll">
        <svg viewBox={`0 0 ${layout.width} ${layout.height}`} className="cmap-svg" role="group" aria-label={summary}>
          {layout.columns.map((c) => (
            <text key={c.title} x={c.x} y={14} className="cmap-colhead">
              {c.title}
            </text>
          ))}
          <g aria-hidden="true">
            {layout.edges.map((e) => (
              <path
                key={e.id}
                d={e.d}
                className="cmap-edge"
                data-tone={e.tone}
                data-origin={e.origin}
                data-dim={active && !(e.source === active || e.target === active) ? "true" : undefined}
                strokeWidth={strokeWidth(e)}
                strokeDasharray={DASH[e.status]}
              >
                <title>{describe(e, nodes)}</title>
              </path>
            ))}
          </g>
          {layout.nodes.map((n) => {
            const dim = active != null && !lit.has(n.id);
            return (
              <g key={n.id} className="cmap-node" data-kind={n.kind} data-dim={dim ? "true" : undefined} data-active={active === n.id ? "true" : undefined} tabIndex={0} role="img" aria-label={`${n.full}${n.sub ? `, ${n.sub}` : ""}`} {...hold(n.id)}>
                <title>{`${n.full}${n.sub ? ` · ${n.sub}` : ""}`}</title>
                <rect x={n.x} y={n.y} width={n.w} height={n.h} rx={6} className="cmap-box" />
                <rect x={n.x} y={n.y} width={4} height={n.h} rx={2} className="cmap-bar" />
                {n.lines.map((l, i) => (
                  <text key={i} x={n.x + 14} y={n.y + 9 + 14 * (i + 1) - 3} className="cmap-label">
                    {l}
                  </text>
                ))}
                {n.subLines.map((l, i) => (
                  <text key={`s${i}`} x={n.x + 14} y={n.y + 9 + 14 * (n.lines.length + i + 1) - 3} className="cmap-sub">
                    {l}
                  </text>
                ))}
                {n.kind === "target" && n.share != null && (
                  <rect x={n.x + 14} y={n.y + n.h - 7} width={Math.max(2, (n.w - 28) * Math.min(1, n.share))} height={3} rx={1.5} className="cmap-share" />
                )}
              </g>
            );
          })}
        </svg>
      </div>
      <p className="mt-2 min-h-[2.5rem] max-w-[70ch] text-xs text-ink-2" aria-live="polite">
        {incident.length > 0
          ? incident.slice(0, 3).map((e) => describe(e, nodes)).join("  ·  ") + (incident.length > 3 ? `  ·  +${incident.length - 3} more in the list below` : "")
          : layout.holdingsReached > layout.holdingsShown
            ? `The ${layout.holdingsShown} largest of ${layout.holdingsReached} holdings reached are shown; the table below lists them all.`
            : ""}
      </p>
      <ul className="cmap-legend" aria-label="How to read the map">
        <li><svg width="30" height="8" aria-hidden="true"><line x1="0" y1="4" x2="30" y2="4" className="cmap-key" data-tone="neutral" strokeWidth="2" /></svg> a fact (a holding, a sensitivity, a quoted phrase)</li>
        <li><svg width="30" height="8" aria-hidden="true"><line x1="0" y1="4" x2="30" y2="4" className="cmap-key" data-tone="neutral" strokeWidth="2" strokeDasharray="7 5" /></svg> a configured assumption, not measured</li>
        <li><svg width="30" height="8" aria-hidden="true"><line x1="0" y1="4" x2="30" y2="4" className="cmap-key" data-tone="neutral" strokeWidth="2" strokeDasharray="2 4" /></svg> your assumption</li>
        <li><svg width="30" height="8" aria-hidden="true"><line x1="0" y1="4" x2="30" y2="4" className="cmap-key" data-tone="hurts" strokeWidth="3" /></svg> hurts</li>
        <li><svg width="30" height="8" aria-hidden="true"><line x1="0" y1="4" x2="30" y2="4" className="cmap-key" data-tone="benefits" strokeWidth="3" /></svg> benefits</li>
      </ul>
    </figure>
  );
}
