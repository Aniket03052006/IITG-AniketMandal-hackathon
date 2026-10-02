"""Build the logo lockup with the wordmark converted to outlines (no font dependency at view time).

Dev-time tool, not a runtime dependency:
    uv run --with fonttools --with brotli python scripts/build_logo.py
Needs `npm ci` in web/ first (reads Space Grotesk from @fontsource-variable/space-grotesk).
"""

from __future__ import annotations

from pathlib import Path

from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

ROOT = Path(__file__).resolve().parents[1]
FONT = ROOT / "web/node_modules/@fontsource-variable/space-grotesk/files/space-grotesk-latin-wght-normal.woff2"
PUBLIC = ROOT / "web/public"

INK, ACCENT, PAPER = "#e8ebf1", "#43d5dc", "#0f141b"
INK_L, ACCENT_L = "#111827", "#0b8a94"  # variant for light backgrounds
def mark_paths(ink: str, accent: str) -> str:
    return (f'<path d="M50 12H17V52H50" stroke="{ink}" stroke-width="5.5"/>'
            f'<path d="M17 32H27L31 18L37 46L41 32H52" stroke="{accent}" stroke-width="5.5"/>')


GROUP = 'fill="none" stroke-linecap="round" stroke-linejoin="round"'


def wordmark(text: str, size: float, weight: int, tracking_em: float) -> tuple[str, float, float, float]:
    font = instantiateVariableFont(TTFont(FONT), {"wght": weight})
    gs, cmap, upm = font.getGlyphSet(), font.getBestCmap(), font["head"].unitsPerEm
    scale, x, parts = size / upm, 0.0, []
    top, bottom = 0.0, 0.0
    for ch in text:
        name = cmap[ord(ch)]
        pen = SVGPathPen(gs)
        gs[name].draw(TransformPen(pen, (scale, 0, 0, -scale, x, 0)))
        parts.append(pen.getCommands())
        bp = BoundsPen(gs)
        gs[name].draw(bp)
        if bp.bounds:
            top, bottom = min(top, -bp.bounds[3] * scale), max(bottom, -bp.bounds[1] * scale)
        x += gs[name].width * scale + tracking_em * size
    return " ".join(parts), x - tracking_em * size, top, bottom


def lockup(d: str, width: float, top: float, bottom: float, ink: str, accent: str, plate: str | None) -> str:
    pad, mark_h, gap = 14, 40, 12
    text_h = bottom - top
    height = max(mark_h, text_h) + pad * 2
    baseline = (height - text_h) / 2 - top  # vertically centre the glyph bounds
    s, mark_y = mark_h / 64, (height - mark_h) / 2
    total_w = pad + mark_h + gap + width + pad
    bg = f'<rect width="{total_w:.1f}" height="{height:.1f}" rx="14" fill="{plate}"/>' if plate else ""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total_w:.1f} {height:.1f}" '
        f'width="{total_w * 2:.0f}" height="{height * 2:.0f}" role="img" aria-label="EventShock">{bg}'
        f'<g transform="translate({pad} {mark_y:.2f}) scale({s:.4f})" {GROUP}>{mark_paths(ink, accent)}</g>'
        f'<path transform="translate({pad + mark_h + gap} {baseline:.2f})" fill="{ink}" d="{d}"/></svg>\n'
    )


def main() -> None:
    d, width, top, bottom = wordmark("EventShock", 30, 600, -0.02)
    mark = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" '
            f'aria-label="EventShock"><g {GROUP}>{mark_paths(INK, ACCENT)}</g></svg>\n')
    favicon = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" '
               f'rx="14" fill="{PAPER}"/><g {GROUP} transform="translate(8 8) scale(.75)">'
               f'{mark_paths(INK, ACCENT)}</g></svg>\n')
    files = {
        "logo.svg": lockup(d, width, top, bottom, INK, ACCENT, PAPER),  # dark plate: readable anywhere
        "logo-on-light.svg": lockup(d, width, top, bottom, INK_L, ACCENT_L, None),
        "logo-mark.svg": mark,
        "favicon.svg": favicon,
    }
    for name, svg in files.items():
        (PUBLIC / name).write_text(svg, encoding="utf-8")
    print("wrote", ", ".join(files))


if __name__ == "__main__":
    main()
