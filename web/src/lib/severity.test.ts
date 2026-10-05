import { SCALE_BANDS, sentimentLabel, severityBand } from "./severity";

describe("severityBand", () => {
  it.each([
    [1, "negligible"], [2, "negligible"], [3, "low"], [4, "low"], [5, "mod"], [6, "mod"], [7, "high"], [8, "high"], [9, "crit"], [10, "crit"],
  ])("score %i is %s", (score, band) => expect(severityBand(score).band).toBe(band));

  it("labels the five semantic bands and tiles the whole scale", () => {
    expect(SCALE_BANDS.map((b) => b.label)).toEqual(["Negligible", "Low", "Moderate", "High", "Extreme"]);
    expect(SCALE_BANDS.flatMap((b) => [b.range[0], b.range[1]])).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
    for (let s = 1; s <= 10; s++) expect(SCALE_BANDS.find((b) => s >= b.range[0] && s <= b.range[1])?.id).toBe(severityBand(s).band);
  });
});

describe("sentimentLabel", () => {
  it.each([[-0.72, "Negative"], [-0.1, "Neutral"], [0.1, "Neutral"], [0.2, "Positive"]])("%f -> %s", (v, l) =>
    expect(sentimentLabel(v)).toBe(l),
  );
});
