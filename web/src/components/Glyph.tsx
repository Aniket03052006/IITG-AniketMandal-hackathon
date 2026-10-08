import clsx from "clsx";
import type { EventCategory } from "../api/types";
import { CATEGORY_ICON } from "./icons";

type IconComp = (p: { size?: number }) => React.JSX.Element;

/**
 * An icon in a shaped tile: the visual identity of an event type, a risk factor or an asset class wherever it appears
 * (event stream, trace stations, scenario cards, the value bridge). Decorative: the label next to it carries the meaning.
 */
export function Glyph({
  icon: I,
  tone = "neutral",
  size = "md",
  shape = "tile",
  className,
}: {
  icon: IconComp;
  tone?: "neutral" | "accent" | "solid";
  size?: "sm" | "md" | "lg";
  shape?: "tile" | "round" | "dashed";
  className?: string;
}) {
  const px = size === "sm" ? 13 : size === "lg" ? 20 : 15;
  return (
    <span className={clsx("glyph", `glyph-${size}`, `glyph-${tone}`, `glyph-${shape}`, className)} aria-hidden="true">
      <I size={px} />
    </span>
  );
}

export function CategoryGlyph({ category, ...rest }: { category: EventCategory } & Omit<Parameters<typeof Glyph>[0], "icon">) {
  const I = CATEGORY_ICON[category];
  return I ? <Glyph icon={I} {...rest} /> : null;
}
