"""Draw docs/architecture_simple.svg / .png: the same system for a reader with no technical background.

    python scripts/make_simple_diagram.py --png      # needs Google Chrome for the PNG

Plain words, functions and flow only. The worked example is a real signal of the shipped replay (see README section 2).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
W, H = 2400, 1590
CW, CH, GAP, X0 = 520, 600, 80, 40  # card width/height, gap, left margin
INK, MUTED, ARROW = "#14202e", "#4b5a6b", "#44505f"

# (number, title, subtitle, colour, who does the work, bullets, example)
ROW1 = [
    ("1", "COLLECT", "Gather the raw material", "#3b78c9", "READS PUBLIC DATA",
     ["News articles (GDELT)", "Finance posts (Twitter)", "Company filings (SEC), if switched on", "Or any text you paste in"],
     "“Iran Says Strait of Hormuz Is Closed Again, Oil Risk to Economy Rises”"),
    ("2", "CLEAN UP", "Make sure it is usable", "#3f9a84", "SIMPLE RULES",
     ["Reject broken records and say why", "Merge copies of the same story, so one story is not counted five times", "Work out which company it is about, or say “none”"],
     "No company named, so it is treated as a market-wide story"),
    ("3", "UNDERSTAND", "Three questions about the text", "#c98a3b", "TRAINED PROGRAMS + SCORECARD",
     ["Tone: is it good or bad news? (−1 to +1)", "Type: what happened? (8 kinds, such as geopolitical or credit)", "Seriousness: how big is it? (1 to 10)"],
     "Neutral tone · Geopolitical · seriousness 8 out of 10"),
    ("4", "CHECK THE TRUST", "How sure can we be?", "#7d6bb8", "SIMPLE RULES",
     ["Count the independent sources", "Keep quotes from the text as proof", "Record which program produced each number"],
     "Only 1 source, so the screen says: weak evidence"),
]
ROW2 = [
    ("5", "WHAT-IF TEST", "Pretend it really happens", "#c95a5a", "SIMPLE RULES",
     ["Runs only if seriousness is 7 or more", "Picks a scenario, for example “investors flee to safety”: shares fall", "The sizes are assumptions, not predictions"],
     "Shares −8%, energy companies −14%"),
    ("6", "RE-PRICE HOLDINGS", "Do the sums for every holding", "#c95a5a", "FIXED FORMULAS, NO AI",
     ["103 pretend holdings: shares, bonds, loans, derivatives", "Same inputs always give the same answer", "Shows which holdings lose the most"],
     "$860.1M becomes $822.8M  (−$37.3M, −4.3%)"),
    ("7", "SHOW THE RESULT", "A dashboard anyone can read", "#3f9a5c", "WEB DASHBOARD",
     ["Value before and after", "Where the loss comes from", "A “Why?” button behind every number", "What was known at each moment"],
     "News in, portfolio consequence out, on one screen"),
]
SAFETY = [
    "Unsure? It says “unknown” instead of guessing a number.",
    "Every number shows where it came from.",
    "Nothing is called “validated” unless it passed a test fixed in advance (so far, nothing has).",
    "The demo runs on saved real data. The live feed is OFF unless you turn it on.",
]

out: list[str] = []
PROBLEMS: list[str] = []


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def wrap(text: str, px: int, size: int) -> list[str]:
    return textwrap.wrap(text, width=max(8, int(px / (size * 0.52))))


def card(x: int, y: int, num: str, title: str, sub: str, col: str, who: str, bullets: list[str], example: str) -> None:
    out.append(f'<rect x="{x}" y="{y}" width="{CW}" height="{CH}" rx="26" fill="#ffffff" stroke="{col}" stroke-width="4"/>')
    out.append(f'<rect x="{x}" y="{y}" width="{CW}" height="92" rx="26" fill="{col}"/>')
    out.append(f'<rect x="{x}" y="{y + 60}" width="{CW}" height="32" fill="{col}"/>')
    out.append(f'<circle cx="{x + 56}" cy="{y + 46}" r="30" fill="#ffffff"/>')
    out.append(f'<text x="{x + 56}" y="{y + 58}" text-anchor="middle" class="num" fill="{col}">{num}</text>')
    out.append(f'<text x="{x + 104}" y="{y + 58}" class="title">{esc(title)}</text>')
    out.append(f'<text x="{x + 28}" y="{y + 140}" class="sub">{esc(sub)}</text>')
    # who does the work
    pw = int(len(who) * 11.2) + 34
    out.append(f'<rect x="{x + 28}" y="{y + 160}" width="{pw}" height="34" rx="17" fill="{col}" fill-opacity="0.14"/>')
    out.append(f'<text x="{x + 45}" y="{y + 184}" class="pill" fill="{col}">{esc(who)}</text>')
    yy = y + 238
    for b in bullets:
        lines = wrap(b, CW - 90, 25)
        for i, ln in enumerate(lines):
            if i == 0:
                out.append(f'<circle cx="{x + 38}" cy="{yy - 8}" r="5" fill="{col}"/>')
            out.append(f'<text x="{x + 56}" y="{yy}" class="body">{esc(ln)}</text>')
            yy += 31
        yy += 9
    # example box
    ex = wrap(example, CW - 80, 22)
    bh = 48 + 28 * len(ex)
    by = y + CH - bh - 22
    if yy > by - 8:
        PROBLEMS.append(f"card {num}: bullets overlap the example box ({yy} > {by - 8})")
    out.append(f'<rect x="{x + 20}" y="{by}" width="{CW - 40}" height="{bh}" rx="14" fill="#f3f6fb"/>')
    out.append(f'<text x="{x + 36}" y="{by + 28}" class="exh">REAL EXAMPLE</text>')
    for i, ln in enumerate(ex):
        out.append(f'<text x="{x + 36}" y="{by + 56 + i * 28}" class="ex">{esc(ln)}</text>')


def arrow(x1: int, y1: int, x2: int, y2: int) -> None:
    out.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{ARROW}" stroke-width="6" marker-end="url(#ah)"/>')


def build() -> str:
    out.clear()
    PROBLEMS.clear()
    out.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" font-family="Helvetica Neue, Arial, sans-serif">')
    out.append(
        "<defs><marker id='ah' viewBox='0 0 10 10' refX='7' refY='5' markerWidth='5' markerHeight='5' orient='auto'>"
        f"<path d='M0,0 L10,5 L0,10 z' fill='{ARROW}'/></marker></defs>"
        "<style>.h1{font:800 56px 'Helvetica Neue',Arial,sans-serif;fill:#0f1c2e}.h2{font:400 29px 'Helvetica Neue',Arial,sans-serif;fill:#44505f}"
        ".num{font:800 34px 'Helvetica Neue',Arial,sans-serif}.title{font:800 31px 'Helvetica Neue',Arial,sans-serif;fill:#fff;letter-spacing:1px}"
        ".sub{font:700 27px 'Helvetica Neue',Arial,sans-serif;fill:#14202e}.pill{font:800 15px 'Helvetica Neue',Arial,sans-serif;letter-spacing:1.2px}"
        ".body{font:400 25px 'Helvetica Neue',Arial,sans-serif;fill:#26323f}.exh{font:800 15px 'Helvetica Neue',Arial,sans-serif;fill:#6b7a8c;letter-spacing:1.5px}"
        ".ex{font:italic 400 22px 'Helvetica Neue',Arial,sans-serif;fill:#26323f}.sh{font:800 28px 'Helvetica Neue',Arial,sans-serif;fill:#14202e}"
        ".sb{font:400 24px 'Helvetica Neue',Arial,sans-serif;fill:#26323f}.foot{font:400 23px 'Helvetica Neue',Arial,sans-serif;fill:#4b5a6b}</style>"
    )
    out.append(f'<rect width="{W}" height="{H}" fill="#fbfcfe"/>')
    out.append('<text x="40" y="76" class="h1">EventShock: from a headline to a portfolio loss, in 7 steps</text>')
    out.append(
        '<text x="40" y="122" class="h2">It reads financial news, works out how serious each story is, then asks: what would this do to a bank’s investments if it really happened?</text>'
    )
    y1, y2 = 160, 160 + CH + 110
    for i, c in enumerate(ROW1):
        x = X0 + i * (CW + GAP)
        card(x, y1, *c)
        if i < 3:
            arrow(x + CW + 8, y1 + CH // 2, x + CW + GAP - 8, y1 + CH // 2)
    # connector from card 4 down to card 5 (row 2 starts at the left)
    x4 = X0 + 3 * (CW + GAP)
    out.append(f'<polyline points="{x4 + CW // 2},{y1 + CH + 6} {x4 + CW // 2},{y1 + CH + 55} {X0 + CW // 2},{y1 + CH + 55} {X0 + CW // 2},{y2 - 8}" fill="none" stroke="{ARROW}" stroke-width="6" marker-end="url(#ah)"/>')
    for i, c in enumerate(ROW2):
        x = X0 + i * (CW + GAP)
        card(x, y2, *c)
        if i < 2:
            arrow(x + CW + 8, y2 + CH // 2, x + CW + GAP - 8, y2 + CH // 2)
    # safety box in the 4th slot
    sx = X0 + 3 * (CW + GAP)
    out.append(f'<rect x="{sx}" y="{y2}" width="{CW}" height="{CH}" rx="26" fill="#fff8e6" stroke="#d9a62e" stroke-width="4" stroke-dasharray="12 8"/>')
    out.append(f'<text x="{sx + 28}" y="{y2 + 56}" class="sh">BUILT-IN SAFETY RULES</text>')
    yy = y2 + 112
    for s in SAFETY:
        lines = wrap(s, CW - 90, 24)
        for i, ln in enumerate(lines):
            if i == 0:
                out.append(f'<text x="{sx + 28}" y="{yy}" class="sb" fill="#d9a62e">✓</text>')
            out.append(f'<text x="{sx + 66}" y="{yy}" class="sb">{esc(ln)}</text>')
            yy += 31
        yy += 20
    if yy > y2 + CH - 8:
        PROBLEMS.append(f"safety box overflows ({yy} > {y2 + CH - 8})")
    out.append(
        f'<text x="40" y="{y2 + CH + 52}" class="foot">Under the hood, for the curious: Python and FastAPI on the server, scikit-learn for the trained programs, React for the dashboard. '
        "All numbers on this page come from the shipped demo data.</text>"
    )
    out.append(
        f'<text x="40" y="{y2 + CH + 86}" class="foot">All models are experimental and the portfolio is made up (real companies, invented positions): this is decision support, not a forecast. '
        "The detailed technical diagram is docs/architecture.png.</text>"
    )
    out.append("</svg>")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--png", action="store_true", help="also render docs/architecture_simple.png with headless Chrome")
    args = ap.parse_args()
    svg = build()
    if PROBLEMS:
        sys.exit("layout problems:\n  " + "\n  ".join(PROBLEMS))
    svg_path = ROOT / "docs" / "architecture_simple.svg"
    svg_path.write_text(svg, encoding="utf-8")
    print(f"wrote {svg_path.relative_to(ROOT)}")
    if args.png:
        chrome = shutil.which("google-chrome") or "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        if not Path(chrome).exists():
            sys.exit("Google Chrome not found; open docs/architecture_simple.svg in a browser and export a PNG")
        html = ROOT / "docs" / ".architecture_simple_render.html"
        html.write_text(
            f'<!doctype html><meta charset="utf-8"><style>html,body{{margin:0;background:#fbfcfe}}img{{display:block}}</style><img src="architecture_simple.svg" width="{W}" height="{H}">',
            encoding="utf-8",
        )
        png = ROOT / "docs" / "architecture_simple.png"
        try:
            subprocess.run(
                [chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--window-size={W},{H}", f"--screenshot={png}", "--force-device-scale-factor=1", html.as_uri()],
                check=True, capture_output=True, timeout=120,
            )
        finally:
            html.unlink(missing_ok=True)
        print(f"wrote {png.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
