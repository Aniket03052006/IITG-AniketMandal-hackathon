import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = join(__dirname, "..");
const tokensCss = readFileSync(join(__dirname, "tokens.css"), "utf8");

/** Parse `--color-x: oklch(L% C H [/ A]);` declarations of a block. */
function parseColors(block: string): Record<string, [number, number, number]> {
  const out: Record<string, [number, number, number]> = {};
  for (const m of block.matchAll(/--color-([a-z0-9-]+):\s*oklch\(\s*([\d.]+)%\s+([\d.]+)\s+([\d.]+)/g)) {
    out[m[1]!] = [Number(m[2]) / 100, Number(m[3]), Number(m[4])];
  }
  return out;
}

const lightBlock = tokensCss.slice(tokensCss.indexOf("@theme"), tokensCss.indexOf(':root[data-theme="dark"]'));
const darkBlock = tokensCss.slice(tokensCss.indexOf(':root[data-theme="dark"]'));
const LIGHT = parseColors(lightBlock);
const DARK = { ...LIGHT, ...parseColors(darkBlock) };

function oklchToLinear([L, C, h]: [number, number, number]): [number, number, number] {
  const a = C * Math.cos((h * Math.PI) / 180);
  const b = C * Math.sin((h * Math.PI) / 180);
  const l_ = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m_ = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s_ = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
  const clamp = (x: number) => Math.min(1, Math.max(0, x));
  return [
    clamp(4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_),
    clamp(-1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_),
    clamp(-0.0041960863 * l_ - 0.7034186147 * m_ + 1.707614701 * s_),
  ];
}

const luminance = (c: [number, number, number]) => {
  const [r, g, b] = oklchToLinear(c);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};

export function contrast(a: [number, number, number], b: [number, number, number]): number {
  const la = luminance(a);
  const lb = luminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

/** [foreground, background, minimum ratio, why]. Text pairs need 4.5; large/graphic marks 3. */
const PAIRS: [string, string, number, string][] = [
  ["ink", "paper", 7, "body text on page"],
  ["ink", "paper-2", 7, "body text on card"],
  ["ink-2", "paper-2", 4.5, "secondary text on card"],
  ["muted", "paper-2", 4.5, "muted text on card"],
  ["muted", "paper", 4.5, "muted text on page"],
  ["muted", "paper-3", 4.5, "muted text on hover fill"],
  ["faint", "paper-2", 3, "placeholder / decorative"],
  ["accent", "paper-2", 4.5, "accent text/links on card"],
  ["accent-ink", "accent", 4.5, "primary button label"],
  ["ink", "accent-dim", 4.5, "active chip"],
  ["sev-low", "paper-2", 4.5, "severity text: low"],
  ["sev-mod", "paper-2", 4.5, "severity text: moderate"],
  ["sev-high", "paper-2", 4.5, "severity text: high"],
  ["sev-crit", "paper-2", 4.5, "severity text: critical"],
  ["neg", "paper-2", 4.5, "loss / negative text"],
  ["pos", "paper-2", 4.5, "gain / positive text"],
  ["warn", "paper-2", 4.5, "warning text"],
  ["neg", "neg-dim", 4.5, "negative tag"],
  ["pos", "pos-dim", 4.5, "positive tag"],
  ["warn", "warn-dim", 4.5, "warning tag"],
  ["focus", "paper-2", 3, "focus ring"],
  ["rule-strong", "paper-2", 1.5, "control border (non-text)"],
];

describe.each([
  ["light", LIGHT],
  ["dark", DARK],
] as const)("%s theme contrast (WCAG)", (_name, palette) => {
  it.each(PAIRS)("%s on %s ≥ %s (%s)", (fg, bg, min) => {
    const f = palette[fg];
    const b = palette[bg];
    expect(f, `token ${fg}`).toBeDefined();
    expect(b, `token ${bg}`).toBeDefined();
    expect(contrast(f!, b!)).toBeGreaterThanOrEqual(min);
  });
});

describe("token coverage", () => {
  it("dark overrides only tokens that exist in the light base", () => {
    for (const k of Object.keys(parseColors(darkBlock))) expect(LIGHT[k], `--color-${k}`).toBeDefined();
  });
  it("every light colour token has a dark counterpart", () => {
    const dark = parseColors(darkBlock);
    for (const k of Object.keys(LIGHT)) expect(dark[k], `dark --color-${k}`).toBeDefined();
  });
});

/** Locked tokens: no raw colour literal anywhere in app source except tokens.css (convention made mechanical). */
describe("no inline colours", () => {
  const files: string[] = [];
  const walk = (dir: string) => {
    for (const f of readdirSync(dir)) {
      const p = join(dir, f);
      if (statSync(p).isDirectory()) walk(p);
      else if (/\.(tsx?|css)$/.test(f) && !/(\.test\.|schema\.d\.ts|tokens\.css)/.test(f)) files.push(p);
    }
  };
  walk(SRC);
  const LITERAL = /#[0-9a-fA-F]{3,8}\b|\b(?:rgb|rgba|hsl|hsla|oklch|oklab|lab|lch)\(/;
  it.each(files.map((f) => [f.replace(SRC, "src")]))("%s", (rel) => {
    const text = readFileSync(join(SRC, "..", rel as string), "utf8");
    // strip comments so documentation may mention formats
    const code = text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");
    expect(code.match(LITERAL), `raw colour literal in ${rel}`).toBeNull();
  });
});
