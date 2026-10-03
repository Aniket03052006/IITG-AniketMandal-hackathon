import { useOpenDrawer } from "../Drawer";
import { Inputs, Question, Sigma, Wrench } from "../icons";

type Icon = typeof Question;

export interface Explain {
  key: string;
  label: string;
  Icon: Icon;
}

export const WHY: Explain = { key: "why", label: "Why?", Icon: Question };
export const INPUTS: Explain = { key: "inputs", label: "Show inputs", Icon: Inputs };
export const MATH: Explain = { key: "math", label: "How calculated?", Icon: Sigma };
export const TECH: Explain = { key: "tech", label: "Technical details", Icon: Wrench };
export const NLP: Explain = { key: "nlp", label: "Why?", Icon: Question };

/** The progressive-disclosure row: each button opens one drawer (state lives in ?open=, so a link or a screenshot can land on it). */
export function ExplainBar({ items, size = "md" }: { items: Explain[]; size?: "sm" | "md" }) {
  const [, setOpen] = useOpenDrawer();
  return (
    <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Explanations">
      {items.map(({ key, label, Icon }) => (
        <button key={key} type="button" className={size === "sm" ? "btn btn-sm" : "btn"} aria-haspopup="dialog" onClick={() => setOpen(key)}>
          <Icon size={14} />
          {label}
        </button>
      ))}
    </div>
  );
}
