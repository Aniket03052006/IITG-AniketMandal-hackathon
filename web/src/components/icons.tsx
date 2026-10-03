import type { SVGProps } from "react";
import type { EventCategory } from "../api/types";

type P = SVGProps<SVGSVGElement> & { size?: number };

function Icon({ size = 16, children, ...rest }: P) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.4}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      {children}
    </svg>
  );
}

/* ---- event categories ---- */
const Globe = (p: P) => (
  <Icon {...p}>
    <circle cx="8" cy="8" r="6" />
    <path d="M2 8h12M8 2c2 2 2.6 4 2.6 6S10 12 8 14M8 2C6 4 5.4 6 5.4 8S6 12 8 14" />
  </Icon>
);
const Macro = (p: P) => (
  <Icon {...p}>
    <path d="M2 13V3M2 13h12" />
    <path d="M4.5 10 7 7l2 2 4-5" />
  </Icon>
);
const Credit = (p: P) => (
  <Icon {...p}>
    <path d="M6.5 9.5 9.5 6.5M7 4.5l1-1a2.8 2.8 0 0 1 4 4l-1 1M9 11.5l-1 1a2.8 2.8 0 0 1-4-4l1-1" />
  </Icon>
);
const Merge = (p: P) => (
  <Icon {...p}>
    <path d="M3 3l4 4v6M13 3 9 7M7 7h2" />
  </Icon>
);
const Gavel = (p: P) => (
  <Icon {...p}>
    <path d="M8 2.5v11M4 13.5h8M3 5h10M3 5l-1.5 4a2 2 0 0 0 3 0L3 5ZM13 5l-1.5 4a2 2 0 0 0 3 0L13 5Z" />
  </Icon>
);
const Box = (p: P) => (
  <Icon {...p}>
    <path d="M8 1.8 13.5 4.6v6.8L8 14.2 2.5 11.4V4.6L8 1.8ZM2.5 4.6 8 7.4l5.500-2.8M8 7.4v6.8" />
  </Icon>
);
const Bars = (p: P) => (
  <Icon {...p}>
    <path d="M3 13V8M8 13V3M13 13v-7" />
  </Icon>
);
const Candles = (p: P) => (
  <Icon {...p}>
    <path d="M4.5 2v12M11.5 2v12" />
    <rect x="3" y="5" width="3" height="5" rx=".5" />
    <rect x="10" y="4" width="3" height="6" rx=".5" />
  </Icon>
);

export const CATEGORY_ICON: Record<EventCategory, (p: P) => React.JSX.Element> = {
  GEOPOLITICAL: Globe,
  MACROECONOMIC: Macro,
  CREDIT_FUNDING: Credit,
  MA_CORPORATE_ACTION: Merge,
  REGULATORY_LEGAL: Gavel,
  PRODUCT_OPERATIONS: Box,
  EARNINGS_FINANCIAL_PERFORMANCE: Bars,
  MARKET_VALUATION: Candles,
};

/* ---- navigation + utility ---- */
export const FeedIcon = (p: P) => (
  <Icon {...p}>
    <path d="M2.5 4h11M2.5 8h11M2.5 12h7" />
  </Icon>
);
export const EventIcon = (p: P) => (
  <Icon {...p}>
    <circle cx="8" cy="8" r="2" />
    <path d="M4.2 4.2a5.4 5.4 0 0 0 0 7.6M11.8 4.2a5.4 5.4 0 0 1 0 7.6" />
  </Icon>
);
export const StressIcon = (p: P) => (
  <Icon {...p}>
    <path d="M1.5 8h3l1.6-4.5 3 9L11 8h3.500" />
  </Icon>
);
export const NewsIcon = (p: P) => (
  <Icon {...p}>
    <rect x="2.5" y="2.5" width="11" height="11" rx="1.5" />
    <path d="M5 6h6M5 8.5h6M5 11h3.500" />
  </Icon>
);
export const SocialIcon = (p: P) => (
  <Icon {...p}>
    <path d="M2.500 3.500h11v7h-5.500L5 13v-2.500H2.500v-7Z" />
  </Icon>
);
export const ArrowRight = (p: P) => (
  <Icon {...p}>
    <path d="M3 8h10M9 4l4 4-4 4" />
  </Icon>
);
export const ArrowLeft = (p: P) => (
  <Icon {...p}>
    <path d="M13 8H3M7 4 3 8l4 4" />
  </Icon>
);
export const Alert = (p: P) => (
  <Icon {...p}>
    <path d="M8 2 14.500 13.500h-13L8 2ZM8 6.500v3.200M8 11.700v.1" />
  </Icon>
);
export const Info = (p: P) => (
  <Icon {...p}>
    <circle cx="8" cy="8" r="6" />
    <path d="M8 7.200v3.800M8 5v.1" />
  </Icon>
);
export const Check = (p: P) => (
  <Icon {...p}>
    <path d="m3 8.500 3.200 3L13 4.500" />
  </Icon>
);
export const Chevron = (p: P) => (
  <Icon {...p}>
    <path d="m6 3.500 4.500 4.500L6 12.500" />
  </Icon>
);
export const Search = (p: P) => (
  <Icon {...p}>
    <circle cx="7" cy="7" r="4.500" />
    <path d="m10.500 10.500 3 3" />
  </Icon>
);
export const Play = (p: P) => (
  <Icon {...p}>
    <path d="M4.500 3 12.500 8l-8 5V3Z" fill="currentColor" />
  </Icon>
);
export const Database = (p: P) => (
  <Icon {...p}>
    <ellipse cx="8" cy="4" rx="5" ry="2" />
    <path d="M3 4v8c0 1.100 2.200 2 5 2s5-.9 5-2V4M3 8c0 1.100 2.200 2 5 2s5-.9 5-2" />
  </Icon>
);
export const Spinner = (p: P) => (
  <Icon {...p} className={`animate-spin ${p.className ?? ""}`}>
    <path d="M8 2a6 6 0 1 0 6 6" />
  </Icon>
);

/** A scale: what the evidence weighs. */
export const EvidenceIcon = (p: P) => (
  <Icon {...p}>
    <path d="M8 2v11M4 13h8M3 5h10" />
    <path d="M3 5l-1.6 4a1.8 1.8 0 0 0 3.2 0L3 5zM13 5l-1.6 4a1.8 1.8 0 0 0 3.2 0L13 5z" />
  </Icon>
);

/* ---- theme, disclosure, provenance-of-number kinds ---- */
export const Sun = (p: P) => (
  <Icon {...p}>
    <circle cx="8" cy="8" r="2.8" />
    <path d="M8 1.5v1.8M8 12.7v1.8M1.5 8h1.8M12.7 8h1.8M3.4 3.4l1.3 1.3M11.3 11.3l1.3 1.3M12.6 3.4l-1.3 1.3M4.7 11.3l-1.3 1.3" />
  </Icon>
);
export const Moon = (p: P) => (
  <Icon {...p}>
    <path d="M13.2 9.6A5.6 5.6 0 0 1 6.4 2.8a5.6 5.6 0 1 0 6.8 6.8Z" />
  </Icon>
);
export const Close = (p: P) => (
  <Icon {...p}>
    <path d="m3.5 3.5 9 9M12.5 3.5l-9 9" />
  </Icon>
);
export const Question = (p: P) => (
  <Icon {...p}>
    <circle cx="8" cy="8" r="6" />
    <path d="M6.2 6.4a1.9 1.9 0 1 1 2.6 1.8c-.5.3-.8.7-.8 1.3M8 11.6v.1" />
  </Icon>
);
export const Inputs = (p: P) => (
  <Icon {...p}>
    <path d="M2 4.5h8M12.5 4.5H14M2 8h3M7.5 8H14M2 11.5h9M13.5 11.5H14" />
    <circle cx="11.2" cy="4.5" r="1.3" />
    <circle cx="6.2" cy="8" r="1.3" />
    <circle cx="12.3" cy="11.5" r="1.3" />
  </Icon>
);
export const Sigma = (p: P) => (
  <Icon {...p}>
    <path d="M12.5 3H4l4.2 5L4 13h8.5" />
  </Icon>
);
export const Wrench = (p: P) => (
  <Icon {...p}>
    <path d="M10.2 2.4a3.2 3.2 0 0 0-3.6 4.2L2.5 10.7a1.4 1.4 0 0 0 2 2l4.1-4.1a3.2 3.2 0 0 0 4.2-3.6L10.5 7.3 8.7 5.500l1.5-3.100Z" />
  </Icon>
);
export const Model = (p: P) => (
  <Icon {...p}>
    <path d="M2 11.5 5 5l3 4 2-3 4 5.500" />
    <circle cx="5" cy="5" r="1" />
    <circle cx="8" cy="9" r="1" />
    <circle cx="10" cy="6" r="1" />
  </Icon>
);
export const History = (p: P) => (
  <Icon {...p}>
    <path d="M2.5 8a5.500 5.500 0 1 0 1.700-4M2.500 2.500v3h3M8 5v3.200l2 1.300" />
  </Icon>
);
export const Scenario = (p: P) => (
  <Icon {...p}>
    <path d="M2 12.500 6 7l2.500 2.500L14 3.500M10.500 3.500H14V7" strokeDasharray="2 2" />
  </Icon>
);
export const Realised = (p: P) => (
  <Icon {...p}>
    <path d="M3 8.500 6.500 12 13 4" />
    <rect x="1.5" y="1.5" width="13" height="13" rx="2" />
  </Icon>
);
export const Lock = (p: P) => (
  <Icon {...p}>
    <rect x="3" y="7" width="10" height="7" rx="1.500" />
    <path d="M5.500 7V5a2.500 2.500 0 0 1 5 0v2" />
  </Icon>
);
export const ShieldGlyph = (p: P) => (
  <Icon {...p}>
    <path d="M8 1.800 13.200 3.800v4c0 3-2.100 5-5.200 6.400C4.900 12.800 2.800 10.800 2.800 7.800v-4L8 1.800Z" />
    <path d="m5.800 8 1.600 1.600 2.800-3" />
  </Icon>
);
