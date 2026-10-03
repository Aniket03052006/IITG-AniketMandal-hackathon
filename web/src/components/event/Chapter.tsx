import clsx from "clsx";
import type { ReactNode } from "react";

/** One chapter of the event story. `scroll-margin` leaves room for the sticky flow rail. */
export function Chapter({
  id,
  eyebrow,
  title,
  lede,
  badge,
  children,
  className,
}: {
  id: string;
  eyebrow: string;
  title: string;
  lede?: ReactNode;
  badge?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className={clsx("chapter", className)}>
      <header className="chapter-head">
        <div className="min-w-0">
          <p className="eyebrow">{eyebrow}</p>
          <h2 id={`${id}-title`} className="chapter-title">
            {title}
          </h2>
          {lede && <p className="chapter-lede">{lede}</p>}
        </div>
        {badge && <div className="shrink-0">{badge}</div>}
      </header>
      {children}
    </section>
  );
}
