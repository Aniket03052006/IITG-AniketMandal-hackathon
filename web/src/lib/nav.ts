import { useLocation } from "react-router-dom";
import { useMeta, useSignals } from "../api/hooks";
import { AnalyzeIcon, DeskIcon, EventIcon, EvidenceIcon, LabIcon, PortfolioIcon, ReviewIcon, TodayIcon } from "../components/icons";
import { FEATURED, lastEvent, pickFeatured } from "./featured";

export type NavItem = {
  to: string;
  label: string;
  /** what you can do there, in one line: shown in the ⌘K palette */
  hint: string;
  icon: (p: { size?: number }) => React.JSX.Element;
  active: boolean;
  /** visual group in the top bar: monitor | investigate | trust */
  group: 0 | 1 | 2;
};

/** The places the story visits, gated by what this server can do. One source for the top bar and the ⌘K palette. */
export function useNav(): NavItem[] {
  const { pathname } = useLocation();
  const { data: meta } = useMeta();
  const all = useSignals({});
  const featured = pickFeatured(all.data?.items ?? [])?.id ?? FEATURED.hero.id;
  const eventTo = `/events/${lastEvent() ?? featured}`;
  return [
    { to: "/", label: "Desk", hint: "The current signal, traced from the news to the portfolio", icon: DeskIcon, active: pathname === "/", group: 0 },
    ...(meta?.capabilities.monitor === true
      ? [{ to: "/today", label: "Today", hint: "What changed, ranked for your portfolio", icon: TodayIcon, active: pathname.startsWith("/today"), group: 0 as const }]
      : []),
    ...(meta?.capabilities.review === true
      ? [{ to: "/review", label: "Review", hint: "Events a person should look at, with the rule that queued each", icon: ReviewIcon, active: pathname.startsWith("/review"), group: 0 as const }]
      : []),
    ...(meta?.capabilities.analyze !== false
      ? [{ to: "/analyze", label: "Analyze", hint: "Paste any financial text and score it", icon: AnalyzeIcon, active: pathname.startsWith("/analyze"), group: 0 as const }]
      : []),
    { to: eventTo, label: "Event", hint: "One event's full story: text, severity, evidence, stress", icon: EventIcon, active: pathname.startsWith("/events/"), group: 1 },
    { to: "/stress", label: "Stress Lab", hint: "Run a scenario on the portfolio and see where the loss lands", icon: LabIcon, active: pathname.startsWith("/stress"), group: 1 },
    { to: "/portfolios", label: "Portfolios", hint: "Your own holdings, watchlists and the scenario lab", icon: PortfolioIcon, active: pathname.startsWith("/portfolios"), group: 1 },
    ...(meta?.replay
      ? [{ to: "/evidence", label: "Evidence", hint: "How far to trust each model, with the numbers", icon: EvidenceIcon, active: pathname.startsWith("/evidence") || pathname.startsWith("/pipeline"), group: 2 as const }]
      : []),
  ];
}
