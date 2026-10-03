import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useTween } from "./motion";

function Num({ to }: { to: number }) {
  return <span data-testid="n">{Math.round(useTween(to))}</span>;
}

describe("useTween", () => {
  beforeEach(() => {
    // motion allowed, and no animation frame ever fires (a hidden or throttled tab)
    vi.stubGlobal("matchMedia", (q: string) => ({ matches: false, media: q, addEventListener: () => undefined, removeEventListener: () => undefined }));
    vi.stubGlobal("requestAnimationFrame", () => 1);
    vi.stubGlobal("cancelAnimationFrame", () => undefined);
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("still lands on the true value when no animation frame ever fires", () => {
    render(<Num to={7} />);
    expect(screen.getByTestId("n").textContent).toBe("0");
    act(() => {
      vi.advanceTimersByTime(700);
    });
    expect(screen.getByTestId("n").textContent).toBe("7");
  });

  it("jumps straight to the value under reduced motion", () => {
    vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("reduce"), media: q, addEventListener: () => undefined, removeEventListener: () => undefined }));
    render(<Num to={9} />);
    expect(screen.getByTestId("n").textContent).toBe("9");
  });
});
