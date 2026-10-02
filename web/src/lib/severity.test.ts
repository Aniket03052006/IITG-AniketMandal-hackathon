import { sentimentLabel, severityBand } from "./severity";

describe("severityBand", () => {
  it.each([
    [1, "low"], [3, "low"], [4, "mod"], [6, "mod"], [7, "high"], [8, "high"], [9, "crit"], [10, "crit"],
  ])("score %i is %s", (score, band) => expect(severityBand(score).band).toBe(band));
});

describe("sentimentLabel", () => {
  it.each([[-0.72, "Negative"], [-0.1, "Neutral"], [0.1, "Neutral"], [0.2, "Positive"]])("%f -> %s", (v, l) =>
    expect(sentimentLabel(v)).toBe(l),
  );
});
