import clsx from "clsx";
import { type ReactNode, useRef } from "react";
import { useSearchParams } from "react-router-dom";

export interface TabDef {
  id: string;
  label: string;
}

/** Accessible tabs whose state lives in ?tab= (a presenter or a screenshot can land on one). Arrow keys, Home and End move between tabs. */
export function useTab(ids: readonly string[], fallback: string): [string, (id: string) => void] {
  const [params, setParams] = useSearchParams();
  const raw = params.get("tab");
  const tab = raw && ids.includes(raw) ? raw : fallback;
  const set = (id: string) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (id === fallback) next.delete("tab");
        else next.set("tab", id);
        next.delete("open");
        return next;
      },
      { replace: true, preventScrollReset: true },
    );
  return [tab, set];
}

export function Tabs({ tabs, active, onChange, label, children }: { tabs: TabDef[]; active: string; onChange: (id: string) => void; label: string; children: ReactNode }) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const onKey = (e: React.KeyboardEvent, i: number) => {
    const last = tabs.length - 1;
    const to = e.key === "ArrowRight" ? (i === last ? 0 : i + 1) : e.key === "ArrowLeft" ? (i === 0 ? last : i - 1) : e.key === "Home" ? 0 : e.key === "End" ? last : null;
    if (to == null) return;
    e.preventDefault();
    refs.current[to]?.focus();
    onChange(tabs[to]!.id);
  };
  return (
    <div>
      <div role="tablist" aria-label={label} className="tabs">
        {tabs.map((t, i) => (
          <button
            key={t.id}
            ref={(el) => {
              refs.current[i] = el;
            }}
            role="tab"
            id={`tab-${t.id}`}
            aria-selected={active === t.id}
            aria-controls={`panel-${t.id}`}
            tabIndex={active === t.id ? 0 : -1}
            className={clsx("tab", active === t.id && "tab-on")}
            onClick={() => onChange(t.id)}
            onKeyDown={(e) => onKey(e, i)}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`panel-${active}`} aria-labelledby={`tab-${active}`} tabIndex={0} className="tabpanel">
        {children}
      </div>
    </div>
  );
}
