import { describe, expect, it } from "vitest";
import type { Meta } from "../api/types";
import { eventIsModel, originChip, originLabel, profileNote, sentimentIsModel, stageKind, stageKindText } from "./provenance";

const meta = (sentiment: string | null, profile = "replay", event = "PLACEHOLDER") =>
  ({ profile, replay: sentiment === null ? null : { stage_origins: { sentiment, event, impact: "PLACEHOLDER" } } }) as unknown as Meta;

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
  it("names both models, and keeps impact a placeholder, when event is MODEL too", () => {
    const m = meta("MODEL (tfidf-lr-v1)", "replay", "MODEL (tfidf-lr-event-v1)");
    expect(eventIsModel(m)).toBe(true);
    expect(profileNote(m)).toMatch(/Sentiment and event type are trained models/);
    expect(profileNote(m)).toMatch(/impact is a placeholder rule/);
    expect(eventIsModel(meta("MODEL (x)"))).toBe(false);
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
  const both = { sentiment: "MODEL", event: "MODEL", impact: "PLACEHOLDER_RULES" };
  const sentOnly = { sentiment: "MODEL", event: "PLACEHOLDER_RULES", impact: "PLACEHOLDER_RULES" };
  it("distinguishes all three data origins", () => {
    expect(originChip("REAL_SOURCE_PLACEHOLDER_NLP")).toBe("Real source · placeholder NLP");
    expect(originChip("DEMO_FIXTURE")).toBe("Demo fixture");
    expect(originChip("REAL_SOURCE_MIXED_NLP", both)).toBe("Real source · trained sentiment and event");
    expect(originLabel("REAL_SOURCE_MIXED_NLP", both)).toBe("Real source · trained sentiment and event, placeholder impact");
  });
  it("names only the stages the signal's own provenance says are models", () => {
    expect(originChip("REAL_SOURCE_MIXED_NLP", sentOnly)).toBe("Real source · trained sentiment");
    expect(originLabel("REAL_SOURCE_MIXED_NLP", sentOnly)).toBe("Real source · trained sentiment, placeholder event type and impact");
    expect(originChip("REAL_SOURCE_MIXED_NLP")).toBe("Real source · trained models");
  });
});

describe("impact lifecycle copy", () => {
  const withImpact = (scopes: Record<string, string>, served = Object.keys(scopes)) =>
    ({ ...meta("MODEL (tfidf-lr-v1)", "replay", "MODEL (tfidf-lr-event-v1)"), impact: { mode: "MODEL", model_id: "impact-v1", scopes, served_scopes: served, reason: null } }) as never;

  it("maps lifecycles to the three words the UI uses", async () => {
    const { lifecycleKind } = await import("./impact");
    expect(lifecycleKind("PRODUCTION")).toBe("validated");
    expect(lifecycleKind("CALIBRATED")).toBe("experimental");
    expect(lifecycleKind("TRAINED")).toBe("experimental");
    for (const l of ["BASELINE", "DATASET", "NOT_AVAILABLE", null, undefined]) expect(lifecycleKind(l)).toBe("placeholder");
  });
  it("derives the profile note from what the app serves instead of hard-coding it", () => {
    expect(profileNote(withImpact({ ISSUER: "CALIBRATED", MARKET: "CALIBRATED" }))).toMatch(/impact is a trained model \(experimental\) where it can score a signal, and a labelled placeholder rule elsewhere/);
    expect(profileNote(withImpact({ ISSUER: "PRODUCTION", MARKET: "CALIBRATED" }))).toMatch(/\(validated \/ experimental\)/);
    expect(profileNote(meta("MODEL (tfidf-lr-v1)", "replay", "MODEL (tfidf-lr-event-v1)"))).toMatch(/impact is a placeholder rule/);
  });
  it("counts impact among a signal's trained stages only when its own origin says MODEL", () => {
    const all = { sentiment: "MODEL", event: "MODEL", impact: "MODEL" };
    expect(originChip("REAL_SOURCE_MIXED_NLP", all)).toBe("Real source · trained sentiment, event and impact");
    expect(originLabel("REAL_SOURCE_MIXED_NLP", all)).toBe("Real source · trained sentiment, event and impact");
  });
  it("labels a signal's impact from its own provenance, not a version string", async () => {
    const { impactKind } = await import("./impact");
    const sig = (impact: unknown, stage: string) => ({ impact: { score: 3 }, provenance: { stage_origins: { impact: stage }, impact } }) as never;
    expect(impactKind(sig(null, "PLACEHOLDER_RULES"))).toBe("placeholder");
    expect(impactKind(sig({ lifecycle: "CALIBRATED" }, "MODEL"))).toBe("experimental");
    expect(impactKind(sig({ lifecycle: "PRODUCTION" }, "MODEL"))).toBe("validated");
  });
});
