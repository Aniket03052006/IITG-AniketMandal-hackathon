import { render, screen } from "@testing-library/react";
import { ImpactMeter, SentimentBar } from "./ui";

describe("ImpactMeter", () => {
  it("exposes score and band to assistive tech, not just colour", () => {
    render(<ImpactMeter score={9} />);
    expect(screen.getByRole("img", { name: "Impact 9 of 10, Extreme" })).toBeInTheDocument();
  });
  it("fills exactly `score` segments", () => {
    const { container } = render(<ImpactMeter score={7} />);
    expect(container.querySelectorAll(".ladder > i.bg-sev-high")).toHaveLength(7);
    expect(container.querySelectorAll(".ladder > i")).toHaveLength(10);
  });
  it("shows an explicit unavailable state instead of inventing a score", () => {
    render(<ImpactMeter score={null} />);
    expect(screen.getByText("unavailable")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });
});

describe("ImpactMeter lifecycle and uncertainty", () => {
  it("states the range and what produced the number in words, not only in outline style", () => {
    render(<ImpactMeter score={6} range={[4, 8]} kind="experimental" showKind />);
    expect(screen.getByRole("img", { name: "Impact 6 of 10, comparable events realised 4 to 8, experimental model, Moderate" })).toBeInTheDocument();
    expect(screen.getByText("experimental model")).toBeInTheDocument();
  });
  it("marks the three kinds differently and leaves an unmarked meter plain", () => {
    const cls = (["placeholder", "experimental", "validated"] as const).map((k) => render(<ImpactMeter score={3} kind={k} />).container.querySelector(".ladder")?.className ?? "");
    expect(cls[0]).toMatch(/dotted/);
    expect(cls[1]).toMatch(/dashed/);
    expect(cls[2]).not.toMatch(/dashed|dotted/);
    expect(render(<ImpactMeter score={3} />).container.querySelector(".ladder")!.className).not.toMatch(/dashed|dotted/);
  });
  it("draws no bracket when the range is the score itself", () => {
    render(<ImpactMeter score={5} range={[5, 5]} />);
    expect(screen.getByRole("img", { name: "Impact 5 of 10, Moderate" })).toBeInTheDocument();
  });
});

describe("SentimentBar", () => {
  it("labels negative sentiment with a true minus and words", () => {
    render(<SentimentBar score={-0.72} />);
    expect(screen.getByRole("img", { name: "Sentiment -0.72, negative" })).toBeInTheDocument();
    expect(screen.getByText("−0.72")).toBeInTheDocument();
  });
  it("treats small magnitudes as neutral", () => {
    render(<SentimentBar score={0.1} />);
    expect(screen.getByRole("img", { name: "Sentiment 0.10, neutral" })).toBeInTheDocument();
  });
});
