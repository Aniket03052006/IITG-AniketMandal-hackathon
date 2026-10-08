import { useOpenDrawer } from "../Drawer";
import { Inputs, Question, Sigma, Wrench } from "../icons";

type Icon = typeof Question;

export interface Explain {
  key: string;
  label: string;
  Icon: Icon;
  /** one line saying what the drawer holds, shown under the label so every button announces where it leads */
  hint?: string;
}

export const WHY: Explain = { key: "why", label: "Why?", Icon: Question, hint: "the drivers, in plain words" };
export const INPUTS: Explain = { key: "inputs", label: "Show inputs", Icon: Inputs, hint: "what the model saw, and when" };
export const MATH: Explain = { key: "math", label: "How calculated?", Icon: Sigma, hint: "the formula, typeset" };
export const TECH: Explain = { key: "tech", label: "Technical details", Icon: Wrench, hint: "model, lifecycle, limits" };
export const SEVERITY_WHY: Explain = { key: "severity", label: "Why this severity?", Icon: Question, hint: "the four answers behind it" };
export const ASSESSED_INPUTS: Explain = { key: "assessed", label: "What the assessment used", Icon: Inputs, hint: "only what was knowable then" };
export const NLP: Explain = { key: "nlp", label: "Why?", Icon: Question, hint: "how the text was read" };

/** The progressive-disclosure group: each button opens one drawer (state lives in ?open=, so a link or a screenshot can land on it). */
export function ExplainBar({ items, size = "md" }: { items: Explain[]; size?: "sm" | "md" }) {
  const [open, setOpen] = useOpenDrawer();
  if (size === "sm")
    return (
      <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Explanations">
        {items.map(({ key, label, Icon }) => (
          <button key={key} type="button" className="btn btn-sm" aria-haspopup="dialog" onClick={() => setOpen(key)}>
            <Icon size={14} />
            {label}
          </button>
        ))}
      </div>
    );
  return (
    <div className="inspect" role="group" aria-label="Explanations">
      {items.map(({ key, label, Icon, hint }) => (
        <button key={key} type="button" className="inspect-btn" aria-label={label} aria-haspopup="dialog" aria-expanded={open === key} title={hint} onClick={() => setOpen(key)}>
          <Icon size={16} />
          <span>
            <b>{label}</b>
            {hint && <small aria-hidden="true">{hint}</small>}
          </span>
        </button>
      ))}
    </div>
  );
}
