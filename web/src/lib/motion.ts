import { useEffect, useRef, useState } from "react";

export const prefersReducedMotion = (): boolean =>
  typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** A number that resolves from `from` to `to` once (ease-out, ~450 ms): a state transition, never ambient motion. Jumps straight there under reduced motion. */
export function useTween(to: number, { from = 0, ms = 450 }: { from?: number; ms?: number } = {}): number {
  const [v, setV] = useState(prefersReducedMotion() ? to : from);
  const start = useRef<number | null>(null);
  const origin = useRef(from);
  useEffect(() => {
    if (prefersReducedMotion() || typeof requestAnimationFrame !== "function") {
      setV(to);
      return;
    }
    origin.current = v;
    start.current = null;
    let raf = 0;
    const step = (t: number) => {
      start.current ??= t;
      const p = Math.min(1, (t - start.current) / ms);
      const e = 1 - Math.pow(1 - p, 3);
      setV(origin.current + (to - origin.current) * e);
      if (p < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    // A hidden or throttled tab never fires animation frames: the true value must still arrive, never a stuck 0.
    const settle = setTimeout(() => setV(to), ms + 150);
    return () => {
      cancelAnimationFrame(raf);
      clearTimeout(settle);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [to, ms]);
  return v;
}

/** Which chapter of a long page is in view (the one crossing the upper third of the viewport). Falls back to the first where there is no observer. */
export function useChapterSpy<T extends string>(ids: readonly T[], enabled = true): [T, (id: T) => void] {
  const [active, setActive] = useState<T>(ids[0] as T);
  useEffect(() => {
    if (!enabled || typeof IntersectionObserver === "undefined") return;
    const seen = new Map<string, boolean>();
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) seen.set(e.target.id, e.isIntersecting);
        const hit = [...ids].reverse().find((id) => seen.get(id));
        if (hit) setActive(hit);
      },
      { rootMargin: "-25% 0px -60% 0px" },
    );
    for (const id of ids) {
      const el = document.getElementById(id);
      if (el) io.observe(el);
    }
    return () => io.disconnect();
  }, [ids, enabled]);
  const go = (id: T) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "start" });
    setActive(id);
  };
  return [active, go];
}
