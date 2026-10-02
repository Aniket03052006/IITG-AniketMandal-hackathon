import { render, screen } from "@testing-library/react";
import { ImpactMeter, SentimentBar } from "./ui";

describe("ImpactMeter", () => {
  it("exposes score and band to assistive tech, not just colour", () => {
    render(<ImpactMeter score={9} />);
    expect(screen.getByRole("img", { name: "Impact 9 of 10, Critical" })).toBeInTheDocument();
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
