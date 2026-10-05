import type { AdjustmentKnob } from "../../api/types";
import { Wrench } from "../icons";

export type Draft = Record<string, unknown>;

function fmt(v: unknown): string {
  if (v === null || v === undefined) return "none";
  if (Array.isArray(v)) return v.join(", ") || "empty";
  if (typeof v === "boolean") return v ? "on" : "off";
  return String(v);
}

/** One adjustable setting: its label, an input fitted to its type and bounds, the shipped default, and a way back to it. */
export function KnobRow({ k, draft, onChange, onReset, issue }: { k: AdjustmentKnob; draft: Draft; onChange: (path: string, value: unknown) => void; onReset: (path: string) => void; issue?: string }) {
  const edited = k.path in draft;
  const value = edited ? draft[k.path] : k.value;
  const id = `knob-${k.path}`;
  const changed = k.adjusted || edited;
  let input: React.ReactNode;
  if (k.kind === "boolean") {
    input = <input id={id} type="checkbox" checked={value === true} onChange={(e) => onChange(k.path, e.target.checked)} aria-invalid={!!issue} />;
  } else if (k.kind === "choice") {
    input = (
      <select id={id} className="field" value={String(value ?? "")} onChange={(e) => onChange(k.path, e.target.value)} aria-invalid={!!issue}>
        {k.choices.map((c) => <option key={c} value={c}>{c}</option>)}
      </select>
    );
  } else if (k.kind === "text_list") {
    input = (
      <input id={id} className="field" value={Array.isArray(value) ? value.join(", ") : String(value ?? "")} aria-invalid={!!issue}
        onChange={(e) => onChange(k.path, e.target.value.split(",").map((x) => x.trim()).filter(Boolean))} />
    );
  } else if (k.kind === "text") {
    input = <input id={id} className="field" value={String(value ?? "")} onChange={(e) => onChange(k.path, e.target.value)} aria-invalid={!!issue} />;
  } else {
    input = (
      <input id={id} className="field num" type="number" inputMode="decimal" step={k.kind === "integer" ? 1 : "any"} min={k.min ?? undefined} max={k.max ?? undefined}
        value={typeof value === "number" || typeof value === "string" ? String(value) : ""} aria-invalid={!!issue}
        onChange={(e) => onChange(k.path, e.target.value === "" ? "" : Number(e.target.value))} />
    );
  }
  return (
    <div className="grid gap-1 border-t border-rule py-3 first:border-t-0 sm:grid-cols-[minmax(0,1fr)_14rem] sm:items-start sm:gap-4">
      <div className="min-w-0">
        <label htmlFor={id} className="text-sm font-medium text-ink">{k.label}</label>
        {k.description && <p className="text-xs text-muted">{k.description}</p>}
        <p className="mt-0.5 text-xs text-muted">
          Default <span className="num">{fmt(k.default)}</span>
          {k.unit ? ` ${k.unit}` : ""}
          {k.min != null && k.max != null ? ` · allowed ${k.min} to ${k.max}` : ""}
        </p>
        {issue && <p className="mt-1 text-xs font-medium text-neg" role="alert">{issue}</p>}
      </div>
      <div className="flex items-center gap-2">
        {input}
        {changed && (
          <button type="button" className="btn" onClick={() => onReset(k.path)} aria-label={`Reset ${k.label} to its default`} title="Back to the default">
            <Wrench size={12} /> Reset
          </button>
        )}
      </div>
    </div>
  );
}
