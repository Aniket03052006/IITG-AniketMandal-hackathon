import "@testing-library/jest-dom/vitest";

// Tests read the settled state: motion is a transition, not content (the real preference is honoured by lib/motion.ts).
// Defined on window (not stubGlobal) so a test's vi.unstubAllGlobals() cannot remove it.
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (q: string) => ({
    matches: q.includes("prefers-reduced-motion"),
    media: q,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false,
  }),
});
