import { describe, expect, it } from "vitest";
import type { Meta } from "../api/types";
import { originChip, originLabel, profileNote, sentimentIsModel, stageKind, stageKindText } from "./provenance";

const meta = (sentiment: string | null, profile = "replay") =>
  ({ profile, replay: sentiment === null ? null : { stage_origins: { sentiment, event: "PLACEHOLDER", impact: "PLACEHOLDER" } } }) as unknown as Meta;

describe("stageKind", () => {
  it.each([
    ["MODEL", "model"],
    ["MODEL (tfidf-lr-v1, trained on Twitter Financial News)", "model"],
    ["SOURCE_LABEL", "source-label"],
    ["PLACEHOLDER_RULES", "placeholder"],
    ["PLACEHOLDER (TFN: source label)", "placeholder"],
    ["anything else", "placeholder"],
    [undefined, "placeholder"],
  ])("%s -> %s", (origin, kind) => expect(stageKind(origin as string | undefined)).toBe(kind));

  it("never calls an unknown stage a model", () => expect(stageKindText("MODELLED")).toBe("Trained model")); // prefix match is deliberate: only the backend writes these
});

describe("profile copy follows the pipeline report, not a constant", () => {
  it("names the model when sentiment is MODEL", () => {
    expect(sentimentIsModel(meta("MODEL (tfidf-lr-v1)"))).toBe(true);
    expect(profileNote(meta("MODEL (tfidf-lr-v1)"))).toMatch(/Sentiment is a trained model; event type and impact are placeholder rules/);
  });
  it("keeps the all-placeholder wording otherwise", () => {
    expect(sentimentIsModel(meta("PLACEHOLDER (TFN: source label)"))).toBe(false);
    expect(profileNote(meta("PLACEHOLDER (TFN: source label)"))).toMatch(/Sentiment, event type and impact are placeholder rules/);
  });
  it("says fixtures for the demo profile", () => {
    expect(profileNote(meta(null, "demo"))).toMatch(/hand-authored fixtures/);
    expect(sentimentIsModel(undefined)).toBe(false);
  });
});

describe("origin labels", () => {
  it("distinguishes all three data origins", () => {
    expect(originChip("REAL_SOURCE_MIXED_NLP")).toBe("Real source · model sentiment");
    expect(originChip("REAL_SOURCE_PLACEHOLDER_NLP")).toBe("Real source · placeholder NLP");
    expect(originChip("DEMO_FIXTURE")).toBe("Demo fixture");
    expect(originLabel("REAL_SOURCE_MIXED_NLP")).toMatch(/trained sentiment, placeholder event and impact/);
  });
});
