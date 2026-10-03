import clsx from "clsx";
import { useEffect, useState } from "react";

type Katex = typeof import("katex").default;

let katexPromise: Promise<Katex> | null = null;

/** KaTeX and its stylesheet load on first use only (drawers), so the first screen never pays for them. */
function loadKatex(): Promise<Katex> {
  katexPromise ??= Promise.all([import("katex"), import("katex/dist/katex.min.css")]).then(([m]) => m.default);
  return katexPromise;
}

/**
 * A formula rendered with KaTeX. `tex` must be a fixed template written in code (never user or API text), with numbers
 * interpolated from structured fields. `label` is the plain-language reading for assistive tech and for the moment before KaTeX loads.
 */
export function Tex({ tex, label, display = false, className }: { tex: string; label: string; display?: boolean; className?: string }) {
  const [html, setHtml] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    loadKatex()
      .then((k) => {
        if (live) setHtml(k.renderToString(tex, { displayMode: display, throwOnError: false, trust: false, output: "htmlAndMathml" }));
      })
      .catch(() => {
        if (live) setHtml(null);
      });
    return () => {
      live = false;
    };
  }, [tex, display]);
  const Wrapper = display ? "div" : "span";
  return html ? (
    <Wrapper className={clsx("tex", display && "tex-display", className)} data-tex="ready" dangerouslySetInnerHTML={{ __html: html }} />
  ) : (
    <Wrapper className={clsx("tex num text-ink-2", display && "tex-display", className)} data-tex="pending" role="math" aria-label={label}>
      {label}
    </Wrapper>
  );
}

/** A formula with its plain-language reading underneath: the reading is for people, the typeset form is for checking. */
export function Formula({ tex, reading, label }: { tex: string; reading: string; label?: string }) {
  return (
    <figure className="formula">
      <Tex tex={tex} display label={label ?? reading} />
      <figcaption className="mt-1 text-sm text-muted">{reading}</figcaption>
    </figure>
  );
}
