import type { GraphEdge, GraphNode, PropagationGraph, PropagationStatus } from "../api/types";

/** The contagion map's geometry, computed from the propagation graph alone: pure, deterministic, no data of its own, so it can be tested without a DOM. */

export type MapKind = "event" | "factor" | "target" | "holding";
export type Tone = "hurts" | "benefits" | "neutral";

export type MapNode = {
  id: string;
  kind: MapKind;
  /** wrapped label lines */
  lines: string[];
  full: string;
  /** the secondary text in full (tooltip, screen reader), and the same wrapped to the box */
  sub: string | null;
  subLines: string[];
  /** share of the whole book, when the node stands for holdings */
  share: number | null;
  x: number;
  y: number;
  w: number;
  h: number;
};

export type MapEdge = {
  id: string;
  source: string;
  target: string;
  status: PropagationStatus;
  tone: Tone;
  weight: number | null;
  /** what the edge says, in words (the graph's own `basis`) */
  basis: string;
  rule: string;
  /** "factor" edges come from the graph; "held" ones are a holding's membership of a sector, industry or asset class */
  origin: "graph" | "held";
  d: string;
};

export type ContagionLayout = {
  width: number;
  height: number;
  columns: { title: string; x: number }[];
  nodes: MapNode[];
  edges: MapEdge[];
  holdingsShown: number;
  holdingsReached: number;
};

export const WIDTH = 900;
const NODE_W = 196;
const COL_X = [0, 235, 470, WIDTH - NODE_W];
const LINE_H = 14;
const PAD_Y = 9;
const GAP = 12;
const TOP = 28; // room for the column titles
const COLUMNS = ["Event", "Risk factors", "Where it lands", "Largest holdings reached"];

/** Words wrapped to at most ``maxLines`` lines of ``maxChars``; what does not fit ends in an ellipsis (the full text stays in the tooltip). */
export function wrap(text: string, maxChars: number, maxLines: number): string[] {
  const words = text.trim().split(/\s+/).filter(Boolean);
  const lines: string[] = [];
  let cur = "";
  for (const w of words) {
    const word = w.length > maxChars ? `${w.slice(0, maxChars - 1)}…` : w;
    if (!cur) cur = word;
    else if (cur.length + 1 + word.length <= maxChars) cur += ` ${word}`;
    else {
      lines.push(cur);
      cur = word;
    }
  }
  if (cur) lines.push(cur);
  if (lines.length <= maxLines) return lines.length ? lines : [""];
  const kept = lines.slice(0, maxLines);
  const last = kept[maxLines - 1]!;
  kept[maxLines - 1] = `${last.length >= maxChars ? last.slice(0, maxChars - 1) : last}…`;
  return kept;
}

const toneOf = (weight: number | null): Tone => (weight == null ? "neutral" : weight > 0 ? "hurts" : weight < 0 ? "benefits" : "neutral");

/** The nodes a holding belongs to, by what the holding is (its asset class, sector and industry): a fact about the holding, not a judgement. */
function membership(h: PropagationGraph["reached"][number]): string[] {
  const ids = [`target:SECTOR:${h.sector}`, `target:ASSET_CLASS:${h.asset_type}`];
  if (h.industry) ids.push(`target:INDUSTRY:${h.industry}`);
  return ids;
}

const kindOf = (n: GraphNode): MapKind | null =>
  n.kind === "EVENT" ? "event" : n.kind === "RISK_FACTOR" ? "factor" : ["ASSET_CLASS", "SECTOR", "INDUSTRY"].includes(n.kind) ? "target" : n.kind === "POSITION" ? "holding" : null;

export function layoutContagion(g: PropagationGraph, maxHoldings = 8): ContagionLayout | null {
  if (g.availability !== "AVAILABLE") return null;
  const byId = new Map(g.nodes.map((n) => [n.id, n]));
  const reached = new Map(g.reached.map((r) => [r.asset_id, r]));
  const subjects = g.nodes.filter((n) => n.kind === "SCOPE" || n.kind === "GEOGRAPHY").map((n) => n.label);

  const columns: GraphNode[][] = [[], [], [], []];
  const col = { event: 0, factor: 1, target: 2, holding: 3 } as const;
  for (const n of g.nodes) {
    const k = kindOf(n);
    if (k) columns[col[k]]!.push(n);
  }
  if (columns[1]!.length === 0 || columns[2]!.length === 0) return null; // no risk factor or no landing place: there is no map to draw
  columns[2]!.sort((a, b) => (b.share ?? 0) - (a.share ?? 0) || a.id.localeCompare(b.id));
  const holdings = columns[3]!.slice(0, maxHoldings);
  columns[3] = holdings;

  const boxes = columns.map((nodes, ci) =>
    nodes.map((n) => {
      const sub = ci === 0 ? (subjects.length ? `About: ${subjects.join(" · ")}` : null) : n.share != null ? `${(n.share * 100).toFixed(1)}% of the book` : null;
      // character limits are conservative for a 196 px box with 14 px of padding each side (12 px bold labels, 11 px sub-lines)
      const lines = wrap(n.label.replace(/ - /, " · "), 23, ci === 0 ? 4 : 2);
      const subLines = sub ? wrap(sub, 26, ci === 0 ? 3 : 1) : [];
      return { n, lines, sub, subLines, h: PAD_Y * 2 + LINE_H * (lines.length + subLines.length) };
    }),
  );
  const heightOf = (bs: { h: number }[]) => bs.reduce((s, b) => s + b.h, 0) + Math.max(0, bs.length - 1) * GAP;
  const inner = Math.max(...boxes.map(heightOf));
  const nodes: MapNode[] = [];
  boxes.forEach((bs, ci) => {
    let y = TOP + (inner - heightOf(bs)) / 2; // each column is centred on the tallest one
    for (const b of bs) {
      nodes.push({
        id: b.n.id, kind: (["event", "factor", "target", "holding"] as const)[ci]!, lines: b.lines, full: b.n.label, sub: b.sub, subLines: b.subLines,
        share: b.n.share ?? null, x: COL_X[ci]!, y, w: NODE_W, h: b.h,
      });
      y += b.h + GAP;
    }
  });
  const at = new Map(nodes.map((n) => [n.id, n]));

  const path = (a: MapNode, b: MapNode) => {
    const x1 = a.x + a.w;
    const y1 = a.y + a.h / 2;
    const x2 = b.x;
    const y2 = b.y + b.h / 2;
    const mx = (x1 + x2) / 2;
    return `M${x1} ${y1} C${mx} ${y1} ${mx} ${y2} ${x2} ${y2}`;
  };
  const edges: MapEdge[] = [];
  const seen = new Set<string>();
  for (const e of g.edges as GraphEdge[]) {
    const a = at.get(e.source);
    const b = at.get(e.target);
    if (!a || !b || a.kind === "holding" || b.kind === "holding" || a.x >= b.x) continue;
    const id = `${e.source}>${e.target}`;
    if (seen.has(id)) continue;
    seen.add(id);
    edges.push({ id, source: e.source, target: e.target, status: e.status, tone: toneOf(e.weight ?? null), weight: e.weight ?? null, basis: e.basis, rule: e.rule_id, origin: "graph", d: path(a, b) });
  }
  for (const n of holdings) {
    const h = reached.get(n.id.replace(/^pos:/, ""));
    const b = at.get(n.id);
    if (!h || !b) continue;
    for (const tid of membership(h)) {
      const a = at.get(tid);
      if (!a || !byId.has(tid)) continue;
      edges.push({ id: `${tid}>${n.id}`, source: tid, target: n.id, status: "OBSERVED", tone: "neutral", weight: null, basis: `${h.name} is a ${h.asset_type.toLowerCase()} holding in ${a.full}`, rule: "held_in", origin: "held", d: path(a, b) });
    }
  }
  const used = columns.map((c, i) => (c.length ? COLUMNS[i]! : null));
  return {
    width: WIDTH, height: TOP + inner + 8, nodes, edges,
    columns: COLUMNS.map((title, i) => ({ title, x: COL_X[i]! })).filter((_, i) => used[i] != null),
    holdingsShown: holdings.length, holdingsReached: g.reached.length,
  };
}
