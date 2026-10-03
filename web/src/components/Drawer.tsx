import clsx from "clsx";
import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useSearchParams } from "react-router-dom";
import { Close } from "./icons";

const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';

/**
 * Which drawer is open lives in the URL (?open=inputs|why|math|tech|audit): a state a presenter or a screenshot can link to,
 * and one the back button leaves alone (replace, not push).
 */
export function useOpenDrawer(): [string | null, (key: string | null) => void] {
  const [params, setParams] = useSearchParams();
  const open = params.get("open");
  const set = useCallback(
    (key: string | null) => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (key) next.set("open", key);
          else next.delete("open");
          return next;
        },
        { replace: true, preventScrollReset: true },
      );
    },
    [setParams],
  );
  return [open, set];
}

/** Side sheet on wide screens, bottom sheet on narrow ones. Modal: focus moves in, Tab stays inside, Esc/scrim close, focus returns. */
export function Drawer({
  open,
  onClose,
  title,
  eyebrow,
  children,
  wide = false,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  eyebrow?: string;
  children: ReactNode;
  wide?: boolean;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const returnTo = useRef<HTMLElement | null>(null);
  const [shown, setShown] = useState(false);

  useEffect(() => {
    if (!open) {
      setShown(false);
      return;
    }
    returnTo.current = document.activeElement as HTMLElement | null;
    const raf = requestAnimationFrame(() => setShown(true));
    panel.current?.focus();
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      cancelAnimationFrame(raf);
      document.body.style.overflow = prevOverflow;
      returnTo.current?.focus?.();
    };
  }, [open]);

  if (!open) return null;

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      onClose();
      return;
    }
    if (e.key !== "Tab" || !panel.current) return;
    const items = [...panel.current.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((el) => el.offsetParent !== null || el === document.activeElement);
    if (items.length === 0) {
      e.preventDefault();
      return;
    }
    const first = items[0]!;
    const last = items[items.length - 1]!;
    if (e.shiftKey && (document.activeElement === first || document.activeElement === panel.current)) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  };

  return createPortal(
    <div className="drawer-root" data-state={shown ? "open" : "closed"} onKeyDown={onKeyDown}>
      <div className="drawer-scrim" onClick={onClose} aria-hidden="true" />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        className={clsx("drawer-panel", wide && "drawer-wide")}
      >
        <header className="drawer-head">
          <div className="min-w-0">
            {eyebrow && <p className="eyebrow">{eyebrow}</p>}
            <h2 className="font-display text-xl font-semibold">{title}</h2>
          </div>
          <button type="button" className="btn btn-ghost px-2" onClick={onClose} aria-label={`Close ${title}`}>
            <Close size={16} />
          </button>
        </header>
        <div className="drawer-body">{children}</div>
      </div>
    </div>,
    document.body,
  );
}

/** A labelled group inside a drawer body. */
export function DrawerSection({ title, note, children }: { title: string; note?: ReactNode; children: ReactNode }) {
  return (
    <section className="drawer-section">
      <h3 className="text-sm font-semibold">{title}</h3>
      {note && <p className="mt-0.5 text-xs text-muted">{note}</p>}
      <div className="mt-3">{children}</div>
    </section>
  );
}
