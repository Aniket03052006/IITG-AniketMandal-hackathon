"""Draw docs/architecture.svg (and, via headless Chrome, docs/architecture.png).

The diagram is generated, not hand-edited, so it can be kept in step with the code:
    python scripts/make_architecture_diagram.py            # writes docs/architecture.svg
    python scripts/make_architecture_diagram.py --png      # also renders docs/architecture.png (needs Google Chrome)

Every box names something that exists in this repository (module, config, artifact or route group).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
W, H = 2400, 1600

# lane colours: (fill, stroke, label)
LANE = {
    "src": ("#eef3fb", "#6b86b8", "SOURCES"),
    "ing": ("#e9f5f1", "#3f9a84", "INGESTION"),
    "ml": ("#fbf1e4", "#c98a3b", "ML / SIGNAL"),
    "sto": ("#f1eefa", "#7d6bb8", "STORAGE"),
    "api": ("#e8f1fb", "#3b78c9", "API"),
    "str": ("#fbeaea", "#c95a5a", "STRESS"),
    "ui": ("#eaf6ee", "#3f9a5c", "UI"),
    "reb": ("#e7f4f8", "#3a97ad", "MODULE A: TACTICAL INDEX REBALANCER (Stage 16; a derived side-car, nothing imports it)"),
}

out: list[str] = []
PROBLEMS: list[str] = []
AR = "#44505f"


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def lane(x: int, y: int, w: int, h: int, key: str, label: str | None = None) -> None:
    fill, stroke, name = LANE[key]
    out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="22" fill="{fill}" stroke="{stroke}" stroke-width="2.5" stroke-dasharray="10 7"/>')
    out.append(f'<text x="{x + 22}" y="{y + 36}" class="lane" fill="{stroke}">{esc(label or name)}</text>')


def box(x: int, y: int, w: int, h: int, title: str, lines: list[str], key: str, bold: bool = False) -> None:
    _, stroke, _ = LANE[key]
    # text must fit: conservative average glyph widths for Helvetica at 23px bold / 19px regular
    if len(title) * 12.2 > w - 40:
        PROBLEMS.append(f"title too wide: {title!r}")
    for ln in lines:
        if len(ln) * 8.2 > w - 40:
            PROBLEMS.append(f"line too wide ({len(ln)} chars for {w}px): {ln!r}")
    if 68 + (len(lines) - 1) * 24 > h:
        PROBLEMS.append(f"box too short: {title!r}")
    out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="#ffffff" stroke="{stroke}" stroke-width="{3.5 if bold else 2}"/>')
    out.append(f'<rect x="{x}" y="{y}" width="9" height="{h}" rx="4" fill="{stroke}"/>')
    out.append(f'<text x="{x + 24}" y="{y + 34}" class="t">{esc(title)}</text>')
    for i, ln in enumerate(lines):
        out.append(f'<text x="{x + 24}" y="{y + 60 + i * 24}" class="s">{esc(ln)}</text>')


def line(pts: list[tuple[int, int]], dashed: bool = False, both: bool = False, label: str = "", lx: int = 0, ly: int = 0) -> None:
    p = " ".join(f"{x},{y}" for x, y in pts)
    dash = ' stroke-dasharray="9 7"' if dashed else ""
    start = " marker-start='url(#ah)'" if both else ""
    out.append(f'<polyline points="{p}" fill="none" stroke="{AR}" stroke-width="3.5"{dash}{start} marker-end="url(#ah)"/>')
    if label:
        out.append(f'<text x="{lx}" y="{ly}" class="l">{esc(label)}</text>')


def build() -> str:
    out.clear()
    out.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" font-family="Helvetica Neue, Arial, sans-serif">')
    out.append(
        "<defs><marker id='ah' viewBox='0 0 10 10' refX='8' refY='5' markerWidth='5.5' markerHeight='5.5' orient='auto-start-reverse'>"
        f"<path d='M0,0 L10,5 L0,10 z' fill='{AR}'/></marker></defs>"
        "<style>.t{font:700 23px 'Helvetica Neue',Arial,sans-serif;fill:#14202e}.s{font:400 19px 'Helvetica Neue',Arial,sans-serif;fill:#3a4756}"
        ".lane{font:800 21px 'Helvetica Neue',Arial,sans-serif;letter-spacing:3px}.l{font:700 18px 'Helvetica Neue',Arial,sans-serif;fill:#2c3a4a}"
        ".h1{font:800 44px 'Helvetica Neue',Arial,sans-serif;fill:#0f1c2e}.h2{font:400 22px 'Helvetica Neue',Arial,sans-serif;fill:#44505f}</style>"
    )
    out.append(f'<rect width="{W}" height="{H}" fill="#fbfcfe"/>')
    out.append('<text x="30" y="58" class="h1">EventShock: architecture</text>')
    out.append(
        '<text x="30" y="94" class="h2">news + social + filings → trained NLP risk signal → deterministic, portfolio-aware stress test → dashboard. '
        "Module B (stress) and Module A (index rebalancer) both read the signal. Numbers 1-8: the order a report takes.</text>"
    )

    # ===== row 1: the signal pipeline (y 120..730) =====
    lane(30, 120, 390, 610, "src")
    lane(440, 120, 440, 610, "ing")
    lane(900, 120, 900, 610, "ml")
    lane(1820, 120, 550, 610, "sto")

    box(50, 165, 350, 118, "News: GDELT", ["DOC 2.0 article metadata,", "GKG 2.1 bulk (title, tone, orgs)", "34 issuers + market queries"], "src")
    box(50, 297, 350, 92, "Social: Fin. tweets", ["finance tweets, MIT licence", "(300-row replay sample)"], "src")
    box(50, 403, 350, 92, "Filings and calendar", ["SEC EDGAR 8-K, FOMC dates", "event-time features; live source"], "src")
    box(50, 509, 350, 92, "Market data", ["Yahoo daily prices (not committed)", "kept only as derived statistics"], "src")
    box(50, 615, 350, 92, "Paste · Live switch", ["POST /api/analyze; GDELT/EDGAR", "poll. Live is OFF at every start"], "src")

    box(460, 165, 400, 118, "1  Source adapters", ["ingestion/{gdelt,tfn,edgar_live}.py", "hash-pinned frozen pack data/replay", "(sha256 checked at start-up)"], "ing")
    box(460, 297, 400, 92, "2  Normalise, validate", ["pipeline/{normalise,validate}.py", "bad rows -> quarantine + reason code"], "ing")
    box(460, 403, 400, 92, "3  Entity resolution", ["pipeline/entities.py: 34-issuer dictionary,", "weak-alias guard, UNKNOWN_ENTITY kept"], "ing")
    box(460, 509, 400, 92, "4  De-duplication", ["pipeline/dedup.py: exact folded; syndicated", "and near reports become corroboration"], "ing")
    box(460, 615, 400, 92, "5  RiskEngine: one door", ["pipeline/engine.py: replay, paste and", "live share every stage function"], "ing", bold=True)

    box(920, 165, 420, 118, "6  Sentiment", ["tfidf-lr-v2: TF-IDF + logistic", "regression, temperature-scaled", "score in [-1, 1]"], "ml")
    box(1360, 165, 420, 118, "6  Event type", ["hybrid-event-v2: TF-IDF + pinned e5", "vector, 8 classes + NONE, abstains", "to UNCERTAIN below P 0.5"], "ml")
    box(920, 297, 420, 92, "6  Scope (rules)", ["COMPANY, SECTOR, MARKET or", "UNRESOLVED, plus the deciding rule"], "ml")
    box(1360, 297, 420, 92, "6  Novelty, corroboration", ["independent sources; evidence kept", "apart from model confidence"], "ml")
    box(920, 403, 860, 92, "7  Impact post-pass: impact-v2 (experimental)", ["gradient boosting on market state + event calendar + TF-IDF event probabilities; rank-calibrated", "to 1-10 with an empirical interval; labelled placeholder rule where it cannot score"], "ml", bold=True)
    box(920, 509, 860, 92, "8  RiskSignal + provenance", ["every stage records model id, artifact sha256, origin; a PARTIAL signal never gets an invented", "score (domain/ Pydantic contracts; models/ artifacts integrity-checked at load)"], "ml", bold=True)
    box(920, 615, 860, 92, "Side-cars (derived on read, never stored on the signal)", ["assessment (severity-v2 scorecard, LLM optional) · intelligence · analogues · propagation ·", "monitor / watchlists / review / brief (decision intelligence) · external markets (observation only)"], "ml")

    box(1840, 165, 510, 118, "Frozen replay pack", ["data/replay: GDELT metadata, tweet sample,", "entities, book, e5 vectors, market context,", "analogue index; manifest with sha256"], "sto")
    box(1840, 297, 510, 118, "Models and configs", ["models/{sentiment,event,impact}: joblib +", "model_card.json; configs/*.yaml, all pinned", "by docs/freeze_manifest.json"], "sto")
    box(1840, 429, 510, 118, "Signal repositories (memory)", ["InMemorySignalRepository (replay) +", "LiveSignalStore (bounded) behind", "CombinedSignalRepository"], "sto")
    box(1840, 561, 510, 146, "Local state (git-ignored)", ["data/live/: journal, portfolios, overrides,", "decision store, LLM cache.", "No SQL / DuckDB in the MVP: files and", "in-memory only"], "sto")

    # ===== row 2: API, stress, UI (y 760..1290) =====
    lane(30, 760, 850, 530, "str")
    lane(900, 760, 900, 530, "api")
    lane(1820, 760, 550, 530, "ui")

    box(50, 805, 400, 130, "Scenario mapper", ["event class -> catalog template", "(8 single-factor, 4 multi-factor)", "or a generated, gated scenario"], "str")
    box(470, 805, 390, 130, "Deterministic engine", ["stress/engine.py, pure functions:", "equity beta, bond duration, loan", "PD/LGD, derivative delta"], "str", bold=True)
    box(50, 949, 400, 118, "Attribution", ["by asset class, issuer, sector, risk", "factor, position; every table", "reconciles or the builder raises"], "str")
    box(470, 949, 390, 118, "Synthetic book", ["103 positions, USD 860.1M, 34 real", "issuers; Wholesale Book v2 preset", "(read-only), shipped as data"], "str")
    box(50, 1081, 810, 92, "Personal portfolios (opt-in)", ["portfolio/: resolver, atomic file store, exposure chain, comparison;", "used only when a request carries portfolio_id; default stays the synthetic book"], "str")
    box(50, 1187, 810, 92, "Honest abstention", ["no scenario reaches a position -> NOT_APPLICABLE, never a zero P&L;", "uncovered exposure is listed, not treated as safe"], "str")

    box(920, 805, 860, 130, "FastAPI /api: 93 operations, OpenAPI at /api/docs", ["signals · assessment · intelligence · propagation · analogues · scenarios · stress-test ·", "portfolios · rebalancer · monitor · watchlists · lab · review · evidence · models · live", "typed contracts shared with the UI (make types)"], "api", bold=True)
    box(920, 949, 860, 118, "Stress service: the only door to the engine", ["trigger rule severity >= 7 (a product rule), severity scaling clamp(I/7, 0.5, 1.5),", "run id = hash of inputs (same request -> same result), audit block with the origin of the score"], "api")
    box(920, 1081, 860, 92, "Error contract", ["valid stress request -> 200 + status (COMPLETED, NOT_TRIGGERED, NO_SCENARIO,", "NOT_APPLICABLE, UNAVAILABLE); 404 unknown id; 422 invalid input"], "api")
    box(920, 1187, 860, 92, "Configuration and secrets", ["configs/*.yaml validated by strict Pydantic models; EVENTSHOCK_* env; keys only from the", "environment or the git-ignored .env; the language model is OFF unless EVENTSHOCK_LLM=1"], "api")

    box(1840, 805, 510, 160, "React 19 + Vite + TypeScript", ["Desk: wire traced from news to book", "Today · Review · Analyze · Event", "Stress Lab · Portfolios · Evidence", "Rebalancer · light/dark, phone to desktop"], "ui", bold=True)
    box(1840, 979, 510, 200, "What it shows", ["portfolio value before vs after,", "value bridge, loss heatmap, contagion", "map; index weights over time; severity", "with Why? and provenance; timeline of", "what was known when; model evidence"], "ui")
    box(1840, 1193, 510, 86, "Served by the same process", ["python src/main.py (API + built web/dist)"], "ui")

    # ===== row 3: Module A (y 1310..1500) =====
    lane(30, 1310, 2340, 190, "reb")
    box(50, 1355, 540, 120, "Sentiment to weight", ["15 stocks, equal-weight benchmark; one source, one vote;", "36 h decay, shrunk score S in [-1, 1], exponential tilt,", "bounds, 4 % turnover cap; self-checked every cycle"], "reb", bold=True)
    box(610, 1355, 540, 120, "Trade decisions and strategies", ["constraint ladder names the rule that bound each stock;", "closed registry: sentiment (baseline), sentiment_risk", "(sector, volatility, liquidity), sentiment_impact"], "reb")
    box(1170, 1355, 540, 120, "Back-test, lab and simulated ledger", ["make rebalancer-backtest / -lab: 5 bp cost, placebo;", "approval ledger: append-only, hash-chained, 409 on a", "changed proposal; nothing is sent anywhere"], "reb")
    box(1730, 1355, 620, 120, "Honest result (10 sessions)", ["+0.19 % vs equal weight, 82nd placebo percentile: within chance,", "so no skill is claimed. Reads only sentiment.score of the", "RiskSignal; severity and impact are not inputs."], "reb")

    # ===== arrows =====
    # sources -> ingestion lanes, ingestion -> ML, ML <-> storage
    line([(420, 425), (440, 425)])
    line([(880, 425), (900, 425)])
    line([(1800, 425), (1820, 425)], both=True)
    # inside ingestion: vertical chain
    # inside ML: vertical chain
    # storage: replay pack/models feed up from disk (dashed, short)
    # ML lane -> API lane
    line([(1350, 730), (1350, 760)], label="RiskSignal", lx=1362, ly=752)
    # API <-> stress, API -> UI
    line([(920, 1020), (880, 1020)], both=True)
    line([(1800, 1020), (1820, 1020)])
    line([(450, 870), (470, 870)])
    line([(1350, 1294), (1350, 1308)], both=True, label="/api/rebalancer", lx=1366, ly=1306)

    out.append(
        '<text x="30" y="1535" class="h2">Cross-cutting: fail loudly (a modified artifact or snapshot file stops start-up; no silent fallback) · deterministic replay (fixed clock, content-derived ids, pinned digests) ·</text>'
    )
    out.append(
        '<text x="30" y="1565" class="h2">four kinds of number never blurred (model prediction, historical observation, scenario assumption, realised outcome).</text>'
    )
    out.append("</svg>")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--png", action="store_true", help="also render docs/architecture.png with headless Chrome")
    args = ap.parse_args()
    svg = build()
    if PROBLEMS:
        sys.exit("text does not fit:\n  " + "\n  ".join(PROBLEMS))
    svg_path = ROOT / "docs" / "architecture.svg"
    svg_path.write_text(svg, encoding="utf-8")
    print(f"wrote {svg_path.relative_to(ROOT)}")
    if args.png:
        chrome = shutil.which("google-chrome") or "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        if not Path(chrome).exists() and not shutil.which(chrome):
            sys.exit("Google Chrome not found; open docs/architecture.svg in a browser and export a PNG")
        html = ROOT / "docs" / ".architecture_render.html"
        html.write_text(
            f'<!doctype html><meta charset="utf-8"><style>html,body{{margin:0;background:#fbfcfe}}img{{display:block}}</style><img src="architecture.svg" width="{W}" height="{H}">',
            encoding="utf-8",
        )
        png = ROOT / "docs" / "architecture.png"
        try:
            subprocess.run(
                [chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--window-size={W},{H}", f"--screenshot={png}", "--force-device-scale-factor=1", html.as_uri()],
                check=True,
                capture_output=True,
                timeout=120,
            )
        finally:
            html.unlink(missing_ok=True)
        print(f"wrote {png.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
