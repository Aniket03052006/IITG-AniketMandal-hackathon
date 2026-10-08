# UI screenshots

Captured from the running app on the frozen replay data (hero event `sig_8f79c8bbd6`, the Strait of Hormuz report the Desk opens on),
so the same numbers appear on every run. Motion is forced off so every frame is the settled state.

Regenerate (the server must be running; Chrome and Node 22+ are the only requirements):

```bash
HERO=sig_8f79c8bbd6 node scripts/screenshots.mjs docs/screenshots http://127.0.0.1:8000
# SIZES="1440x900 1024x768 390x844"  THEMES="light dark"  ONLY="event-top|stress-full"  (all optional)
```

Pages are addressed by URL (`?theme=`, `?open=` for drawers, `?tab=` for tabs), so each capture is reproducible.

| File | What it shows |
|---|---|
| `before/` | The UI before the final pass (dark only, one dense page per area), kept for comparison |
| `feed-*` | Desk: the incoming wire, the selected event, the six-station signal trace, why trust it (the pipeline counts and the full list below) |
| `event-top-*` | First viewport of the flagship event page: what happened, who, when, what was detected, how severe, and the chain |
| `event-full-*` | The whole event story: Understand, Impact, Evidence (comparables, timeline), Stress bridge |
| `event-inputs-*` | **Show inputs** drawer: the model's actual inputs, grouped, with availability classes and what is deliberately not used |
| `event-math-*` | **How calculated?** drawer: typeset formulas |
| `event-timeline-end-*` | "What did EventShock know at this moment?" with the slider at the end: available at the time / learned later / realised outcome |
| `stress-full-*` | Stress Lab: scenario cards, before and after, the value bridge (book → shocks → where it lands → positions → after), waterfall, drill-down, what-if |
| `stress-drill-*` | The drill-down opened to a single position |
| `evidence-top-*` | "How much evidence supports EventShock?": four verdict tiles and the tabs |
| `evidence-pipeline-*` | The data pipeline as one picture, audit detail behind expanders |

Suffix: `light`/`dark` theme, then viewport (`1440x900` desktop, `1024x768` small laptop, `390x844` phone). Light is the default theme.
Images are palette-quantised PNGs to keep the repository small.
