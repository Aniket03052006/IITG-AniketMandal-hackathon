"""Draw docs/architecture_detailed.svg / .png: every component of EventShock, module by module.

    python scripts/make_detailed_diagram.py --png      # the PNG needs Google Chrome

Every box names a module, artifact, config or route group that exists in this repository. Heights are computed from the wrapped text, so
nothing overflows. The simplified views are docs/architecture.png and docs/architecture_simple.png.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
W = 3600
MARGIN, GAP = 30, 28
ARROW = "#3a4655"
COL = {
    "src": "#5f7fb5", "ing": "#2f9a82", "pipe": "#2f9a82", "ml": "#c4811f", "core": "#7a63b8",
    "side": "#b8567a", "reb": "#2f93a8", "str": "#c94f4f", "api": "#2f74c8", "ui": "#2f9a55", "qa": "#6b7a8c",
}
out: list[str] = []
PROBLEMS: list[str] = []


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def wrap(text: str, px: float, size: float) -> list[str]:
    return textwrap.wrap(text, width=max(10, int(px / (size * 0.56)))) or [""]


class Group:
    def __init__(self, title: str, key: str, items: list[tuple[str, str]], w: int, sub: str = ""):
        self.title, self.key, self.items, self.w, self.sub = title, key, items, w, sub
        self.x = self.y = self.h = 0

    def natural_height(self) -> int:
        h = 74 + (28 if self.sub else 0)
        for name, desc in self.items:
            h += 26 * len(wrap(name, self.w - 56, 21)) + 22 * (len(wrap(desc, self.w - 56, 18)) if desc else 0) + 14
        return h + 10

    def draw(self) -> None:
        c = COL[self.key]
        out.append(f'<rect x="{self.x}" y="{self.y}" width="{self.w}" height="{self.h}" rx="20" fill="#ffffff" stroke="{c}" stroke-width="3.5"/>')
        out.append(f'<path d="M{self.x} {self.y + 20} a20 20 0 0 1 20 -20 h{self.w - 40} a20 20 0 0 1 20 20 v38 h-{self.w} z" fill="{c}"/>')
        out.append(f'<text x="{self.x + 22}" y="{self.y + 40}" class="gt">{esc(self.title)}</text>')
        yy = self.y + 84
        if self.sub:
            out.append(f'<text x="{self.x + 22}" y="{yy}" class="gs">{esc(self.sub)}</text>')
            yy += 28
        for name, desc in self.items:
            ln = wrap(name, self.w - 56, 21)
            out.append(f'<circle cx="{self.x + 26}" cy="{yy - 7}" r="5" fill="{c}"/>')
            for i, t in enumerate(ln):
                out.append(f'<text x="{self.x + 42}" y="{yy + i * 26}" class="in">{esc(t)}</text>')
            yy += 26 * len(ln)
            if desc:
                for t in wrap(desc, self.w - 56, 18):
                    out.append(f'<text x="{self.x + 42}" y="{yy - 2}" class="id">{esc(t)}</text>')
                    yy += 22
            yy += 14
        if yy - 14 > self.y + self.h:
            PROBLEMS.append(f"{self.title}: overflow")

    @property
    def cx(self) -> int:
        return self.x + self.w // 2

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    @property
    def cy(self) -> int:
        return self.y + self.h // 2


def band(groups: list[Group], y: int, x0: int = MARGIN) -> int:
    h = max(g.natural_height() for g in groups)
    x = x0
    for g in groups:
        g.x, g.y, g.h = x, y, h
        x += g.w + GAP
    for g in groups:
        g.draw()
    return y + h


def line(pts: list[tuple[int, int]], dashed: bool = False, both: bool = False, label: str = "", lx: int = 0, ly: int = 0) -> None:
    p = " ".join(f"{x},{y}" for x, y in pts)
    d = ' stroke-dasharray="12 9"' if dashed else ""
    ms = " marker-start='url(#ah)'" if both else ""
    out.append(f'<polyline points="{p}" fill="none" stroke="{ARROW}" stroke-width="4.5"{d}{ms} marker-end="url(#ah)"/>')
    if label:
        out.append(f'<rect x="{lx - 6}" y="{ly - 22}" width="{int(len(label) * 10.4) + 12}" height="30" rx="6" fill="#fbfcfe" fill-opacity="0.92"/>')
        out.append(f'<text x="{lx}" y="{ly}" class="lb">{esc(label)}</text>')


def build() -> tuple[str, int]:
    out.clear()
    PROBLEMS.clear()
    body_start = len(out)

    # ---------------- band 1: the signal pipeline ----------------
    A = Group("EXTERNAL INPUTS", "src", [
        ("GDELT DOC 2.0 · GKG 2.1", "news article metadata, tone, organisations; free with citation"),
        ("Twitter Financial News", "finance posts with human sentiment labels (MIT); the social source"),
        ("SEC EDGAR 8-K", "filings with exact acceptance times; live Atom feed (opt-in)"),
        ("FOMC calendars", "decision dates, public domain"),
        ("Yahoo Finance prices", "daily prices; only derived statistics are kept"),
        ("Kaggle card transactions", "merchant-category spend mix only (Apache-2.0)"),
        ("Kalshi prediction markets", "public API or captured snapshot; observation only"),
        ("Pasted text · personal portfolios", "POST /api/analyze · /api/portfolios"),
        ("LLM provider (optional)", "Groq or Anthropic; OFF unless EVENTSHOCK_LLM=1"),
    ], 470)
    B = Group("INGESTION  ingestion/ + services/live.py", "ing", [
        ("gdelt.py · gkg.py · tfn.py · edgar.py · fomc.py · prices.py", "provider adapters: RawDocument or Rejected(reason)"),
        ("edgar_live.py · live.py", "live sources, CombinedSource, CaptureSource (simulated live from a committed capture)"),
        ("fetch.py", "the ONLY module that opens a network socket: throttle, retry, resumable"),
        ("snapshot.py · replay.py", "sha256-verified frozen pack; a changed file stops start-up"),
        ("LiveService", "runtime ON/OFF switch (PUT /api/live/state), poller, status OFF/OK/DEGRADED/ERROR/IDLE"),
        ("data/replay/", "manifest, GDELT + tweet sample, entities, synthetic book, e5 vectors, market context; replay clock 2026-10-01 12:00Z"),
    ], 540)
    C = Group("PIPELINE  pipeline/", "pipe", [
        ("normalize.py → validate.py", "clean documents; closed reject codes; bad rows to quarantine with a reason"),
        ("entities.py", "dictionary resolver for 34 issuers: cashtag > legal name > alias > weak alias (finance-context guard) > restrained fuzzy; UNKNOWN_ENTITY is a state"),
        ("dedup.py", "exact duplicates folded; syndicated, near and same-event reports become corroboration"),
        ("scope.py + configs/scope.yaml", "COMPANY / SECTOR / MARKET / UNRESOLVED with the matched terms"),
        ("engine.py  RiskEngine", "prepare_record, cluster_items, build_signal: replay, paste and live share every stage function"),
        ("enrich.py", "ModelEnricher, ImpactModelEnricher (post-pass after novelty), PlaceholderEnricher (labelled fallback)"),
    ], 600)
    D = Group("MODELS  models/ + pipeline/*_model.py", "ml", [
        ("sentiment_model.py  tfidf-lr-v2 (v1 = impact reference)", "TF-IDF word + char n-grams, class-balanced logistic regression, temperature scaling; score = P(pos) - P(neg)"),
        ("hybrid_event_model.py  hybrid-event-v2 (tfidf-lr-event-v1 = reference)", "TF-IDF + pinned e5-large vectors (embeddings.py), 9-way LR, abstains below P 0.5"),
        ("impact_model.py  impact-v2 (impact-v1 fallback)", "additive gradient boosting, scopes ISSUER and MARKET, rank-calibrated to 1-10 with an empirical interval"),
        ("impact_features(_v2).py · market_context.py · event_context.py", "event-time features, frozen market context, EventCalendar (FOMC, 8-K schedule)"),
        ("modeling/leakage.py", "feature availability registry AT_EVENT_TIME / POST_EVENT; future-invariance checks"),
        ("*_card.py → model_card.json", "metrics, pre-registered acceptance verdict, lifecycle, artifact sha256; integrity-checked at load"),
    ], 760)
    E = Group("SIGNAL CORE  domain/ + store.py", "core", [
        ("RiskSignal", "entity, scope, sentiment, event, impact, evidence; status COMPLETE or PARTIAL"),
        ("SignalProvenance · ModelVersions", "model id, artifact sha256 and origin recorded per stage"),
        ("InMemorySignalRepository", "the frozen replay run, digest 078a70ae"),
        ("LiveSignalStore", "bounded overlay of live and pasted signals; git-ignored journal"),
        ("CombinedSignalRepository", "what every reader sees; change counter seq"),
    ], 440)
    F = Group("OFFLINE RESEARCH AND QA", "qa", [
        ("modeling/ + make train-*", "tables, training, impact study, outcome audit, evidence studies; deterministic"),
        ("docs/evidence/*.json", "committed results the Evidence page reads"),
        ("configs/ (30 YAML)", "taxonomy, scenarios, severity, live, decision, propagation; pre-registered bars never edited after results"),
        ("docs/freeze_manifest.json", "sha256 of models, configs, gold sets, replay, evidence; make freeze-check"),
        ("tests/", "pytest 2,368 (unit 117 files, integration 21, e2e 17); Vitest 782; architecture tests enforce import rules"),
        ("scripts/smoke_e2e.py", "make smoke: real server, API, model hashes, stress, UI"),
    ], 590)
    row1 = [A, B, C, D, E, F]
    y1 = 150
    end1 = band(row1, y1)

    # ---------------- band 2: side-cars ----------------
    y2 = end1 + 120
    S1 = Group("ASSESSMENT  assessment/ + llm/", "side", [
        ("service.py  AssessmentService", "derives a RiskAssessment from a signal; memoised; never stored on it"),
        ("extractor.py → grounding.py", "LLM (forced tool call, closed enums) is checked against the text; any failure falls back to the rule extractor"),
        ("rubric.py · cues.py · rules.py · vocab.py", "four anchored answers (intensity, reach, certainty, direction); AI may move one by one step"),
        ("severity.py · freshness.py", "fixed matrix, certainty x direction scaling, VIX-regime and novelty adjustments; market data at most one session old"),
        ("views.py · benchmark.py · reference.py", "provenance AI / DATA / RULES / HYBRID / ASSUMPTION; 64 + 32 headline benchmark; impact-v2 as labelled reference"),
        ("llm/ client · cache · schema · prompt · config", "urllib only; 30 s budget, 30 calls/min; cached by text + model + prompt"),
    ], 640)
    S2 = Group("EVENT INTELLIGENCE  intelligence/", "side", [
        ("scope.py", "COMPANY, INDUSTRY, SECTOR, GEOGRAPHY, MACRO, MARKET, THEME, UNRESOLVED path"),
        ("grouping.py", "report clusters to events; first report of each outlet is independent"),
        ("evidence.py", "evidence tier from independent sources, kept apart from model confidence"),
        ("novelty.py · velocity.py", "NEW / CONTINUATION / UPDATE / RECURRING; narrative velocity; unavailable on replay-assigned clocks"),
        ("claims.py", "closed-lexicon claims and contradiction, never from tone"),
        ("lifecycle.py · service.py", "rule-driven state machine with timeline; every section may abstain"),
    ], 520)
    S3 = Group("ANALOGUES AND CONTEXT", "side", [
        ("retrieval/ index · search · corpus", "6,531 trusted-clock episodes as pinned e5 vectors; point-in-time, story-collapsed"),
        ("retrieval/ relevance_eval · outcome_value", "pre-registered tests; similarity floor read from evidence, not typed"),
        ("services/analogues.py", "display-only: no analogue quantity enters any score"),
        ("services/signal_context.py", "model inputs by availability class; filings before / after; realised outcome"),
        ("services/outcome_check.py · relevance.py", "severity vs realised moves; what the event means for the book"),
    ], 480)
    S4 = Group("PROPAGATION  propagation/ + adjust/", "side", [
        ("mapping.py", "event, scope, risk factor, holdings graph; each edge has a rule and a basis"),
        ("materiality.py", "LOW..CRITICAL by exposure x severity lookup; abstains"),
        ("scenario_gen.py", "catalog scenario of the class plus propagated sector shocks; gated"),
        ("attribution.py · concentration.py", "loss by shock, issuer, sector, factor, class, position; concentration and overlaps"),
        ("adjust/ registry · store · service", "whitelisted manual overrides, patched into raw YAML before validation, rolled back on failure"),
    ], 560)
    S5 = Group("DECISION INTELLIGENCE", "side", [
        ("monitor/", "EventState, diff_states to RiskChange by named rule, digest, event memory; replay is a pure function over frozen signals"),
        ("watchlist/ · review/", "watchlists matched on resolved scope; review queue by named rules, append-only decisions"),
        ("lab/", "scenario lab (base, assessed, custom) and bounded-grid reverse stress"),
        ("explain/ · brief/", "structured reasons; 16-section executive brief, template-written, every statement sourced"),
        ("feedback/ · markets/", "append-only feedback; Kalshi observation, never an input to a score"),
    ], 700)
    R = Group("REBALANCER (Module A)  rebalancer/", "reb", [
        ("scoring.py · config.py", "shrunk, decayed, one-source-one-vote sentiment score per company; strict YAML, every number a judgement prior"),
        ("weights.py", "exponential tilt, exact projection onto bounds (and a sector cap), turnover-capped step; pure functions"),
        ("service.py · decisions.py", "6 h cycle grid, self-check (sum 1, bounds, cap), constraint ladder, named reasons, proposal sha256"),
        ("risk.py · lab.py · backtest.py", "sentiment_risk and sentiment_impact strategies; point-in-time back-test, 5 bp cost, 200-shuffle placebo"),
        ("ledger.py", "simulated approval: append-only, hash-chained JSONL; 409 on a changed proposal; nothing is sent anywhere"),
    ], 500)
    row2 = [S1, S2, S3, S4, S5, R]
    end2 = band(row2, y2)
    # band-2 frame
    frame_y = y2 - 62
    out.insert(body_start, f'<rect x="{MARGIN - 12}" y="{frame_y}" width="{sum(g.w for g in row2) + GAP * (len(row2) - 1) + 24}" height="{end2 - frame_y + 22}" rx="26" fill="#fdf0f4" stroke="#b8567a" stroke-width="3" stroke-dasharray="14 9"/>')
    out.append(f'<text x="{MARGIN + 6}" y="{frame_y + 38}" class="gt2" fill="#b8567a">SIDE-CARS: derived on read from a RiskSignal, never stored on it (core packages may not import them; tests enforce it)</text>')

    # ---------------- band 3: stress, API, UI ----------------
    y3 = end2 + 150
    T = Group("STRESS AND PORTFOLIO  stress/ + portfolio/", "str", [
        ("services/stress_service.py  StressService", "the only door to the engine: trigger severity >= 7, scale clamp(sev/7, 0.5, 1.5), shocks bound by scope, run id = sha256 of inputs, audit block"),
        ("stress/scenarios.py", "catalog: 8 single-factor and 4 multi-factor scenarios; event class to default scenario"),
        ("stress/engine.py", "pure revaluation: equity beta x shock; bond -D(drates + dspread) (+ convexity); loan EAD(PD'LGD' - PD LGD) (+ spread link, CVA); derivative delta (+ gamma); FX/commodity only where a position carries it"),
        ("stress/attribution.py · history_check.py", "per-factor attribution that reconciles; shocks ranked against 1/5/21-session history"),
        ("portfolio/ resolve · store · exposure · chain · compare · crosstab", "personal portfolios (atomic files), exposure matrix, event > shock > exposure chain"),
        ("portfolio/ book_v2 · betas · catalog", "read-only Wholesale Book v2 preset; Vasicek-shrunk betas; instrument catalog"),
        ("data/replay/portfolio.json", "synthetic book: 103 positions, USD 860.1M, 34 real issuers (34 equities, 41 bonds, 19 loans, 9 derivatives)"),
    ], 1180)
    P = Group("API  api/ (FastAPI, 93 operations)", "api", [
        ("main.py · deps.py · schemas.py", "app factory, CORS, serves web/dist; builds the service container and rebuilds side-cars after an override; typed Pydantic responses"),
        ("routers: signals · analyze · stress · scenarios · propagation · events", "feed, paste, stress-test, scenario catalog and lab, event-to-portfolio, brief/analogues/timeline"),
        ("routers: portfolio · portfolios · adjustments · scope · pipeline", "default book, personal portfolios, overrides, scope vocabulary, ingestion report"),
        ("router: rebalancer", "overview, timeline, cycles and decisions, back-test, lab, simulated approval and ledger (Module A)"),
        ("routers: monitor · watchlists · lab · review · feedback", "digest and changes, watchlists, reverse stress, review queue, feedback"),
        ("routers: evidence · models · live · meta", "model cards and lifecycle, outcome check, live switch, capabilities that gate the UI"),
        ("contract", "valid stress request always 200 with a status (COMPLETED, NOT_TRIGGERED, NO_SCENARIO, NOT_APPLICABLE, UNAVAILABLE); 404 unknown id; 422 invalid input"),
        ("OpenAPI → web/src/api/schema.d.ts", "make types: the UI and API cannot drift silently"),
    ], 1170)
    U = Group("DASHBOARD  web/ (React 19, Vite, TypeScript, Tailwind v4)", "ui", [
        ("pages/", "Desk · Today · Review · Analyze · Event · Stress Lab · Portfolios · Portfolio editor · Rebalancer · Evidence · Pipeline"),
        ("components/", "trace (six-station wire), desk, event, assessment, intelligence, propagation (contagion map), portfolio (heatmaps, value bridge), lab, monitor, watchlist, markets, brief, adjust, live switch, review, rebalancer (weights, decisions, lab, ledger)"),
        ("lib/", "pure, tested view-models: timeline (no future fact in an earlier state), contagion layout, severity, formulas, nav"),
        ("api/", "TanStack Query hooks over generated types"),
        ("styles/tokens.css", "Harbour tokens, light and dark, WCAG pairs checked by tests"),
        ("Shell · CommandPalette", "sidebar and top bar, portfolio and live switches, Cmd-K jump to anything"),
    ], 1130)
    # stretch band 3 to the right edge
    row3 = [T, P, U]
    end3 = band(row3, y3)

    # ---------------- arrows ----------------
    mid1 = A.y + 520
    line([(A.right, mid1), (B.x, mid1)])
    line([(B.right, mid1), (C.x, mid1)])
    line([(C.right, mid1), (D.x, mid1)])
    line([(D.right, mid1), (E.x, mid1)])
    # signal core down to side-cars
    line([(E.cx, E.bottom), (E.cx, frame_y)], label="RiskSignal read by every side-car", lx=E.cx + 14, ly=(E.bottom + frame_y) // 2 + 20)
    # LLM provider -> assessment
    line([(A.cx, A.bottom), (A.cx, frame_y)], dashed=True, label="optional LLM reader", lx=A.cx + 14, ly=(A.bottom + frame_y) // 2 + 20)
    # side-cars -> stress and API
    line([(S1.cx + 120, end2 + 22), (S1.cx + 120, T.y)], label="severity (trigger, scaling)", lx=S1.cx + 134, ly=end2 + 90)
    line([(S4.cx, end2 + 22), (S4.cx, T.y - 40), (T.cx + 300, T.y - 40), (T.cx + 300, T.y)], label="generated scenario", lx=S4.cx + 14, ly=end2 + 90)
    line([(S5.x + 160, end2 + 22), (S5.x + 160, T.y - 90), (P.right - 520, T.y - 90), (P.right - 520, P.y)], label="side-car services", lx=S5.x + 174, ly=end2 + 90)
    # stress <-> api, api -> ui
    line([(T.right, T.y + 130), (P.x, T.y + 130)], both=True, label="runs", lx=T.right - 18, ly=T.y - 12)
    line([(P.right, P.y + 130), (U.x, P.y + 130)], label="JSON", lx=P.right - 18, ly=P.y - 12)

    # legend / footer
    ly = end3 + 80
    out.append(f'<text x="{MARGIN}" y="{ly}" class="foot">Solid arrow: data flow. Dashed: optional or read-only. Colours: grey-blue inputs, green ingestion and UI, amber models, purple signal core, pink side-cars, teal rebalancer, red stress, blue API.</text>')
    out.append(f'<text x="{MARGIN}" y="{ly + 34}" class="foot">Storage: no SQL database; files (JSON, JSONL, NPZ, joblib) and in-memory repositories behind Protocols (ports.py).</text>')
    out.append(f'<text x="{MARGIN}" y="{ly + 68}" class="foot">All trained models are experimental; the portfolio is synthetic; scenario shocks are assumptions. Plainer views: docs/architecture.png and docs/architecture_simple.png.</text>')
    height = ly + 110

    head = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {height}" width="{W}" height="{height}" font-family="Helvetica Neue, Arial, sans-serif">',
        "<defs><marker id='ah' viewBox='0 0 10 10' refX='7' refY='5' markerWidth='5' markerHeight='5' orient='auto-start-reverse'>"
        f"<path d='M0,0 L10,5 L0,10 z' fill='{ARROW}'/></marker></defs>",
        "<style>.t1{font:800 60px 'Helvetica Neue',Arial,sans-serif;fill:#0f1c2e}.t2{font:400 28px 'Helvetica Neue',Arial,sans-serif;fill:#44505f}"
        ".gt{font:800 24px 'Helvetica Neue',Arial,sans-serif;fill:#fff;letter-spacing:0.5px}.gt2{font:800 26px 'Helvetica Neue',Arial,sans-serif;letter-spacing:0.5px}"
        ".gs{font:600 18px 'Helvetica Neue',Arial,sans-serif;fill:#44505f}"
        ".in{font:700 21px 'Helvetica Neue',Arial,sans-serif;fill:#14202e}.id{font:400 18px 'Helvetica Neue',Arial,sans-serif;fill:#3a4756}"
        ".lb{font:700 18px 'Helvetica Neue',Arial,sans-serif;fill:#2c3a4a}.foot{font:400 23px 'Helvetica Neue',Arial,sans-serif;fill:#4b5a6b}</style>",
        f'<rect width="{W}" height="{height}" fill="#fbfcfe"/>',
        f'<text x="{MARGIN}" y="70" class="t1">EventShock: component architecture</text>',
        f'<text x="{MARGIN}" y="110" class="t2">Every module, model, store and route group, left to right along the life of one report, then down through side-cars, stress, API and dashboard.</text>',
    ]
    return "\n".join(head + out + ["</svg>"]), height


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--png", action="store_true")
    args = ap.parse_args()
    svg, height = build()
    if PROBLEMS:
        sys.exit("layout problems:\n  " + "\n  ".join(PROBLEMS))
    svg_path = ROOT / "docs" / "architecture_detailed.svg"
    svg_path.write_text(svg, encoding="utf-8")
    print(f"wrote {svg_path.relative_to(ROOT)} ({W} x {height})")
    if args.png:
        chrome = shutil.which("google-chrome") or "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        if not Path(chrome).exists():
            sys.exit("Google Chrome not found; open the SVG in a browser and export a PNG")
        html = ROOT / "docs" / ".architecture_detailed_render.html"
        html.write_text(
            f'<!doctype html><meta charset="utf-8"><style>html,body{{margin:0;background:#fbfcfe}}img{{display:block}}</style><img src="architecture_detailed.svg" width="{W}" height="{height}">',
            encoding="utf-8",
        )
        png = ROOT / "docs" / "architecture_detailed.png"
        try:
            subprocess.run(
                [chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--window-size={W},{height}", f"--screenshot={png}", "--force-device-scale-factor=1", html.as_uri()],
                check=True, capture_output=True, timeout=180,
            )
        finally:
            html.unlink(missing_ok=True)
        print(f"wrote {png.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
