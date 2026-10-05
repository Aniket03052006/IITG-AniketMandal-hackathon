import { useState } from "react";
import type { AdjustmentKnob, AdjustmentState } from "../../api/types";
import { Plus } from "../icons";
import type { Draft } from "./KnobRow";

const EDGE = /^propagation\.risk_factors\.([A-Z_]+)\.transmission\.([a-z0-9_]+)\.(weight|enabled|shock)$/;

interface EdgeKnobs { rf: string; id: string; weight?: AdjustmentKnob; enabled?: AdjustmentKnob; shock?: AdjustmentKnob }

/** The transmission table as a grid: for each risk factor, each edge's on/off, weight and whether it writes a sector shock; plus edges you add yourself. */
export function MappingEditor({ state, draft, onChange, onReset, issues }: {
  state: AdjustmentState; draft: Draft; onChange: (path: string, value: unknown) => void; onReset: (path: string) => void; issues: Record<string, string>;
}) {
  const edges = new Map<string, EdgeKnobs>();
  for (const k of state.knobs) {
    const m = EDGE.exec(k.path);
    if (!m) continue;
    const key = `${m[1]}.${m[2]}`;
    const e = edges.get(key) ?? { rf: m[1]!, id: m[2]! };
    e[m[3] as "weight" | "enabled" | "shock"] = k;
    edges.set(key, e);
  }
  const byRf = new Map<string, EdgeKnobs[]>();
  for (const e of edges.values()) byRf.set(e.rf, [...(byRf.get(e.rf) ?? []), e]);
  const val = (k?: AdjustmentKnob) => (k ? (k.path in draft ? draft[k.path] : k.value) : undefined);
  const mark = (k?: AdjustmentKnob) => !!k && (k.adjusted || k.path in draft);
  const rfIds = [...new Set([...byRf.keys(), ...state.risk_factors])].sort();
  const [form, setForm] = useState({ rf: rfIds[0] ?? "", name: "", kind: "SECTOR", key: "", weight: 0.3, shock: true, rationale: "" });
  const slug = form.name.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
  const canAdd = !!slug && !!form.key.trim() && form.rationale.trim().length > 0;
  const addedPath = (rf: string, id: string) => `propagation.risk_factors.${rf}.transmission.${id}`;

  return (
    <div className="grid gap-6">
      {[...byRf.entries()].sort().map(([rf, list]) => (
        <section key={rf} aria-label={rf}>
          <h4 className="text-sm font-semibold">{rf.replace(/_/g, " ").toLowerCase().replace(/^./, (c) => c.toUpperCase())}</h4>
          <table className="mt-2 w-full text-sm">
            <caption className="sr-only">Transmission edges of {rf}</caption>
            <thead><tr className="text-left text-xs text-muted">
              <th scope="col" className="pb-1 pr-3 font-medium">Edge</th><th scope="col" className="pb-1 pr-3 font-medium">On</th>
              <th scope="col" className="pb-1 pr-3 font-medium">Weight</th><th scope="col" className="pb-1 font-medium">Writes a sector shock</th>
            </tr></thead>
            <tbody>
              {list.map((e) => (
                <tr key={e.id} className="border-t border-rule align-middle">
                  <th scope="row" className="py-1.5 pr-3 text-left font-normal">
                    {e.id.replace(/_/g, " ")}
                    {(mark(e.weight) || mark(e.enabled) || mark(e.shock)) && <span className="ml-2 text-xs font-medium text-ink-2">adjusted</span>}
                  </th>
                  <td className="py-1.5 pr-3">{e.enabled && <input type="checkbox" aria-label={`${rf} ${e.id} on`} checked={val(e.enabled) === true} onChange={(ev) => onChange(e.enabled!.path, ev.target.checked)} />}</td>
                  <td className="py-1.5 pr-3">
                    {e.weight && (
                      <input type="number" className="field num w-24" step="0.05" min={-1} max={1} aria-label={`${rf} ${e.id} weight`} aria-invalid={!!issues[e.weight.path]}
                        value={String(val(e.weight) ?? "")} onChange={(ev) => onChange(e.weight!.path, ev.target.value === "" ? "" : Number(ev.target.value))} />
                    )}
                    {e.weight && <span className="ml-2 text-xs text-muted">default {String(e.weight.default)}</span>}
                    {e.weight && issues[e.weight.path] && <span className="block text-xs text-neg" role="alert">{issues[e.weight.path]}</span>}
                  </td>
                  <td className="py-1.5">{e.shock && <input type="checkbox" aria-label={`${rf} ${e.id} writes a sector shock`} checked={val(e.shock) === true} onChange={(ev) => onChange(e.shock!.path, ev.target.checked)} />}</td>
                  <td className="py-1.5 pl-2">
                    {(mark(e.weight) || mark(e.enabled) || mark(e.shock)) && (
                      <button type="button" className="btn" onClick={() => [e.weight, e.enabled, e.shock].forEach((k) => k && mark(k) && onReset(k.path))}>Reset</button>
                    )}
                  </td>
                </tr>
              ))}
              {state.added_edges.filter((a) => a.risk_factor === rf).map((a) => (
                <tr key={a.edge_id} className="border-t border-rule align-middle bg-paper-2">
                  <th scope="row" className="py-1.5 pr-3 text-left font-normal">{a.edge_id.replace(/_/g, " ")} <span className="text-xs font-medium text-ink-2">added by you</span></th>
                  <td className="py-1.5 pr-3 text-xs text-muted" colSpan={3}>
                    {String(a.value.kind)} {String(a.value.key)} · weight {String(a.value.weight)} · {a.value.shock ? "writes a shock" : "reach only"} — {String(a.value.rationale)}
                  </td>
                  <td className="py-1.5 pl-2"><button type="button" className="btn" onClick={() => onReset(a.path)}>Remove</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}
      <section aria-label="Add an edge" className="rounded-md border border-rule p-4">
        <h4 className="text-sm font-semibold">Add a transmission edge</h4>
        <p className="mt-0.5 text-xs text-muted">Your own assumption about how a risk factor reaches a sector, industry, asset class or region. It is labelled yours wherever it appears.</p>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <label className="block text-sm"><span className="eyebrow mb-1 block">Risk factor</span>
            <select className="field" value={form.rf} onChange={(e) => setForm({ ...form, rf: e.target.value })}>{rfIds.map((r) => <option key={r}>{r}</option>)}</select></label>
          <label className="block text-sm"><span className="eyebrow mb-1 block">Name</span>
            <input className="field" value={form.name} placeholder="e.g. healthcare costs" onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
          <label className="block text-sm"><span className="eyebrow mb-1 block">Reaches</span>
            <select className="field" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value, shock: e.target.value === "SECTOR" ? form.shock : false })}>
              {["SECTOR", "INDUSTRY", "ASSET_CLASS", "REGION"].map((k) => <option key={k} value={k}>{k.replace("_", " ").toLowerCase()}</option>)}</select></label>
          <label className="block text-sm"><span className="eyebrow mb-1 block">Which one</span>
            <input className="field" value={form.key} placeholder="e.g. Healthcare" onChange={(e) => setForm({ ...form, key: e.target.value })} /></label>
          <label className="block text-sm"><span className="eyebrow mb-1 block">Weight (−1 benefits, +1 hurts)</span>
            <input className="field num" type="number" step="0.05" min={-1} max={1} value={form.weight} onChange={(e) => setForm({ ...form, weight: Number(e.target.value) })} /></label>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.shock} disabled={form.kind !== "SECTOR"} onChange={(e) => setForm({ ...form, shock: e.target.checked })} /> Writes a propagated sector shock</label>
          <label className="block text-sm sm:col-span-2"><span className="eyebrow mb-1 block">Why (shown beside the edge)</span>
            <input className="field" value={form.rationale} onChange={(e) => setForm({ ...form, rationale: e.target.value })} /></label>
        </div>
        <button type="button" className="btn mt-3" disabled={!canAdd}
          onClick={() => {
            onChange(addedPath(form.rf, `user_${slug}`), { kind: form.kind, key: form.key.trim(), weight: form.weight, enabled: true, shock: form.kind === "SECTOR" && form.shock, rationale: form.rationale.trim() });
            setForm({ ...form, name: "", key: "", rationale: "" });
          }}>
          <Plus size={13} /> Add to my changes
        </button>
      </section>
    </div>
  );
}
