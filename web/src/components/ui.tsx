import clsx from "clsx";
import type { ReactNode } from "react";
import type { EventCategory, SourceType } from "../api/types";
import { KIND_LABEL, type ImpactKind } from "../lib/impact";
import { sentimentLabel, severityBand } from "../lib/severity";
import { Alert, CATEGORY_ICON, Info, NewsIcon, SocialIcon, Spinner } from "./icons";

/* -------------------------------------------------------------------------- impact */

/**
 * 10-segment ladder + numeric score. Colour is reinforced by the number and a text label.
 * `range` (the scores comparable historical events realised) adds a bracket under the ladder; `kind` marks what produced the number:
 * a trained, validated model is drawn plain, an experimental one gets a dashed outline, and the placeholder rule a dotted one,
 * each also stated in words (aria-label, and `showKind`) so the outline is never the only signal.
 */
export function ImpactMeter({
  score,
  size = "sm",
  showLabel = false,
  range,
  kind,
  showKind = false,
  hideNumber = false,
  wide = false,
  noun = "Impact",
}: {
  score: number | null;
  size?: "sm" | "lg";
  showLabel?: boolean;
  range?: [number, number] | null;
  kind?: ImpactKind;
  showKind?: boolean;
  /** The score is drawn large elsewhere (the verdict); the ladder keeps its accessible name. */
  hideNumber?: boolean;
  /** A full-width ladder (fills its container) instead of the fixed 10rem one. */
  wide?: boolean;
  /** What the number is called in the accessible name: "Impact" for the trained model, "Severity" for the risk assessment. */
  noun?: string;
}) {
  if (score === null) {
    return (
      <span className="inline-flex items-center gap-2 text-muted" title="Impact unavailable: the impact model produced no score">
        <span className={clsx("num font-semibold", size === "lg" ? "text-3xl" : "text-md")}>–</span>
        <span className="text-xs">unavailable</span>
      </span>
    );
  }
  const band = severityBand(score);
  const hasRange = !!range && range[0] <= range[1] && !(range[0] === score && range[1] === score);
  const kindText = kind ? KIND_LABEL[kind].toLowerCase() : null;
  const aria = `${noun} ${score} of 10${hasRange ? `, ${noun === "Impact" ? "comparable events realised" : "weight sensitivity range"} ${range![0]} to ${range![1]}` : ""}${kindText ? `, ${kindText}` : ""}, ${band.label}`;
  return (
    <span className={clsx("inline-flex items-center gap-2.5", wide && "flex w-full")} role="img" aria-label={aria}>
      {!hideNumber && (
        <span className={clsx("num font-semibold leading-none", band.text, size === "lg" ? "text-4xl" : "text-lg w-6 text-right")}>
          {score}
        </span>
      )}
      <span className={clsx("flex flex-col gap-1", wide && "w-full")}>
        <span
          data-kind={kind}
          className={clsx(
            "ladder",
            size === "lg" ? "h-3" : "h-2",
            wide ? "w-full" : size === "lg" ? "w-40" : "w-[4.5rem]",
            kind === "experimental" && "outline outline-1 outline-offset-2 outline-dashed outline-muted",
            kind === "placeholder" && "outline outline-1 outline-offset-2 outline-dotted outline-muted",
          )}
        >
          {Array.from({ length: 10 }, (_, i) => (
            <i key={i} className={i < score ? band.bg : undefined} />
          ))}
        </span>
        {hasRange && (
          <span className={clsx("relative block h-1", wide ? "w-full" : size === "lg" ? "w-40" : "w-[4.5rem]")} aria-hidden="true">
            <span
              className="absolute inset-y-0 rounded-[1px] bg-ink-2"
              style={{ left: `${((range![0] - 1) / 10) * 100}%`, width: `${((range![1] - range![0] + 1) / 10) * 100}%` }}
            />
          </span>
        )}
        {showLabel && <span className={clsx("text-xs font-medium", band.text)}>{band.label}</span>}
        {showKind && kindText && <span className="text-2xs text-muted">{kindText}</span>}
      </span>
    </span>
  );
}

/* ------------------------------------------------------------------------ sentiment */

/** Diverging bar centred on zero: negative extends left, positive right. */
export function SentimentBar({ score, wide = false }: { score: number; wide?: boolean }) {
  const w = Math.min(Math.abs(score), 1) * 50;
  const neg = score < 0;
  return (
    <span
      className="inline-flex items-center gap-2"
      role="img"
      aria-label={`Sentiment ${score.toFixed(2)}, ${sentimentLabel(score).toLowerCase()}`}
    >
      <span className={clsx("relative h-2 rounded-sm bg-paper-4", wide ? "w-32" : "w-16")}>
        <span className="absolute inset-y-0 left-1/2 w-px bg-faint" />
        <span
          className={clsx("absolute inset-y-0 rounded-sm", neg ? "bg-neg" : "bg-pos")}
          style={neg ? { right: "50%", width: `${w}%` } : { left: "50%", width: `${w}%` }}
        />
      </span>
      <span className={clsx("num w-11 text-right text-sm", score < -0.15 ? "text-neg" : score > 0.15 ? "text-pos" : "text-muted")}>
        {score > 0 ? "+" : score < 0 ? "−" : ""}
        {Math.abs(score).toFixed(2)}
      </span>
    </span>
  );
}

/* --------------------------------------------------------------------------- chips */

export function CategoryTag({ category, label }: { category: EventCategory; label: string }) {
  const Ico = CATEGORY_ICON[category];
  return (
    <span className="tag">
      <Ico size={13} />
      {label}
    </span>
  );
}

export function SourceBadge({ type, name }: { type: SourceType; name?: string }) {
  const Ico = type === "NEWS" ? NewsIcon : SocialIcon;
  return (
    <span className="inline-flex items-center gap-1.5 text-muted" title={type === "NEWS" ? "News source" : "Social post"}>
      <Ico size={14} />
      <span className="text-xs">{name ?? (type === "NEWS" ? "News" : "Social")}</span>
    </span>
  );
}

export function StatusTag({ tone, children, icon }: { tone: "demo" | "warn" | "ok" | "neg"; children: ReactNode; icon?: ReactNode }) {
  const tones = {
    demo: "border-rule-strong text-ink-2 bg-paper-3",
    warn: "border-warn text-warn bg-warn-dim",
    ok: "border-pos text-pos bg-pos-dim",
    neg: "border-neg text-neg bg-neg-dim",
  } as const;
  return (
    <span className={clsx("inline-flex items-center gap-1.5 rounded-sm border px-2 py-0.5 text-xs font-medium whitespace-nowrap", tones[tone])}>
      {icon}
      {children}
    </span>
  );
}

/* -------------------------------------------------------------------------- layout */

export function PageHeader({ title, sub, actions }: { title: string; sub?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
      <div className="min-w-0">
        <h1 className="text-3xl">{title}</h1>
        {sub && <p className="mt-1 max-w-[72ch] text-ink-2">{sub}</p>}
      </div>
      {actions}
    </header>
  );
}

export function Card({ title, aside, children, className, pad = true }: { title?: string; aside?: ReactNode; children: ReactNode; className?: string; pad?: boolean }) {
  return (
    <section className={clsx("card", pad && "card-pad", className)}>
      {title && (
        <div className={clsx("card-head", !pad && "px-4 pt-4")}>
          <h2 className="card-title">{title}</h2>
          {aside && <div className="text-xs text-muted">{aside}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

export function Stat({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: "neg" | "pos" | "high" }) {
  return (
    <div className="min-w-0">
      <div className="eyebrow">{label}</div>
      <div className={clsx("num mt-1 text-xl font-medium", tone === "neg" && "text-neg", tone === "pos" && "text-pos", tone === "high" && "text-sev-high")}>
        {value}
      </div>
      {sub && <div className="mt-0.5 text-xs text-muted">{sub}</div>}
    </div>
  );
}

export function Notice({ tone = "info", title, children, action }: { tone?: "info" | "warn" | "neg"; title: string; children?: ReactNode; action?: ReactNode }) {
  const tones = {
    info: "border-rule-strong bg-paper-2 text-ink-2",
    warn: "border-warn bg-warn-dim text-ink",
    neg: "border-neg bg-neg-dim text-ink",
  } as const;
  const Ico = tone === "info" ? Info : Alert;
  return (
    <div role={tone === "neg" ? "alert" : "status"} className={clsx("flex items-start gap-3 rounded-lg border p-4", tones[tone])}>
      <Ico size={18} className={clsx("mt-0.5 shrink-0", tone === "warn" && "text-warn", tone === "neg" && "text-neg", tone === "info" && "text-accent")} />
      <div className="min-w-0 flex-1">
        <p className="font-medium">{title}</p>
        {children && <div className="mt-1 text-sm text-ink-2">{children}</div>}
      </div>
      {action}
    </div>
  );
}

/** Quiet in-card callout: icon + text, no nested box (cards never contain cards). */
export function InlineNote({ tone = "info", title, children }: { tone?: "info" | "warn"; title: string; children?: ReactNode }) {
  const Ico = tone === "warn" ? Alert : Info;
  return (
    <div role="status" className="flex items-start gap-2.5 border-t border-rule pt-3">
      <Ico size={16} className={clsx("mt-0.5 shrink-0", tone === "warn" ? "text-warn" : "text-accent")} />
      <div className="min-w-0 text-sm">
        <p className="font-medium text-ink">{title}</p>
        {children && <p className="mt-0.5 text-ink-2">{children}</p>}
      </div>
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx("skeleton", className)} aria-hidden="true" />;
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-10 text-muted" role="status">
      <Spinner size={16} /> {label}…
    </div>
  );
}

export function ErrorState({ error, retry }: { error: Error; retry?: () => void }) {
  return (
    <Notice
      tone="neg"
      title="Something went wrong"
      action={retry && <button className="btn" onClick={retry}>Retry</button>}
    >
      {error.message}
    </Notice>
  );
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-rule-strong px-6 py-12 text-center">
      <p className="font-display text-lg font-semibold">{title}</p>
      {children && <p className="mx-auto mt-1 max-w-[46ch] text-muted">{children}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

/** Horizontal stacked probability bar used for sentiment. */
export function StackBar({ parts }: { parts: { label: string; value: number; className: string }[] }) {
  return (
    <div>
      <div className="flex h-3 overflow-hidden rounded-sm bg-paper-4" role="img" aria-label={parts.map((p) => `${p.label} ${(p.value * 100).toFixed(0)}%`).join(", ")}>
        {parts.map((p) => (
          <span key={p.label} className={p.className} style={{ width: `${p.value * 100}%` }} />
        ))}
      </div>
      <dl className="mt-2 grid grid-cols-3 gap-2 text-xs">
        {parts.map((p) => (
          <div key={p.label}>
            <dt className="flex items-center gap-1.5 text-muted">
              <span className={clsx("inline-block h-2 w-2 rounded-[1px]", p.className)} />
              {p.label}
            </dt>
            <dd className="num text-sm">{(p.value * 100).toFixed(0)}%</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
