import clsx from "clsx";
import { useEffect } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useActivePortfolioItem, useAdjustments, useMeta, useSignals } from "../api/hooks";
import { useOpenDrawer } from "./Drawer";
import { FEATURED, lastEvent, pickFeatured } from "../lib/featured";
import { dateTime } from "../lib/format";
import { profileLabel, profileNote } from "../lib/provenance";
import { currencySymbol } from "../lib/portfolio";
import { setDisplayCurrency } from "../lib/format";
import { AdjustHost } from "./adjust/AdjustDrawer";
import { PortfolioSwitcher } from "./portfolio/PortfolioSwitcher";
import { AnalyzeIcon, Database, EventIcon, EvidenceIcon, FeedIcon, PortfolioIcon, StressIcon, Wrench } from "./icons";
import { Logo } from "./Logo";
import { ThemeSwitch } from "./ThemeSwitch";

function ModeBadge() {
  const { data } = useMeta();
  return (
    <div className="rounded-md border border-rule bg-paper-2 p-3 text-xs">
      <div className="flex items-center gap-1.5 font-medium text-ink">
        <Database size={13} />
        {profileLabel(data)}
      </div>
      {data && (
        <>
          <p className="mt-1.5 leading-snug text-muted">
            Clock pinned to <span className="num text-ink-2">{dateTime(data.as_of)}</span>, so every run reads the same.
          </p>
          <details className="disclosure mt-1.5">
            <summary>What is real here?</summary>
            <p className="mt-1.5 leading-snug text-muted">{profileNote(data)}</p>
          </details>
        </>
      )}
    </div>
  );
}

/** Opens the adjustment drawer from anywhere; shows how many values are adjusted. */
function AdjustLink() {
  const { data: meta } = useMeta();
  const [, setOpen] = useOpenDrawer();
  const adj = useAdjustments(meta?.capabilities.adjustments === true);
  if (meta?.capabilities.adjustments !== true) return null;
  const n = adj.data?.count ?? 0;
  return (
    <button type="button" className="flex min-h-10 items-center gap-2.5 rounded-md px-3 text-left text-sm font-medium text-ink-2 hover:bg-paper-3 hover:text-ink" onClick={() => setOpen("adjust")} aria-haspopup="dialog">
      <Wrench size={15} /> Adjust assumptions
      {n > 0 && <span className="num ml-auto rounded-sm border border-dashed border-ink-2 px-1.5 text-xs" aria-label={`${n} adjusted`}>{n}</span>}
    </button>
  );
}

/** The four places the story visits. Event Intelligence is a real link: the event you last opened, else the featured one. */
export function Shell() {
  const { pathname } = useLocation();
  const { data: meta } = useMeta();
  const all = useSignals({});
  const featured = pickFeatured(all.data?.items ?? [])?.id ?? FEATURED.hero.id;
  const eventTo = `/events/${lastEvent() ?? featured}`;
  // money() reads the active portfolio's currency; pages remount on a switch so nothing keeps the previous portfolio's numbers
  const { id: activePf, item: activeItem } = useActivePortfolioItem();
  setDisplayCurrency(currencySymbol(activeItem?.base_currency));

  const nav = [
    { to: "/", label: "Risk Feed", icon: FeedIcon, active: pathname === "/" },
    ...(meta?.capabilities.analyze !== false ? [{ to: "/analyze", label: "Analyze", icon: AnalyzeIcon, active: pathname.startsWith("/analyze") }] : []),
    { to: eventTo, label: "Event Intelligence", icon: EventIcon, active: pathname.startsWith("/events/") },
    { to: "/stress", label: "Portfolio Stress", icon: StressIcon, active: pathname.startsWith("/stress") },
    { to: "/portfolios", label: "Portfolios", icon: PortfolioIcon, active: pathname.startsWith("/portfolios") },
    ...(meta?.replay ? [{ to: "/evidence", label: "Evidence", icon: EvidenceIcon, active: pathname.startsWith("/evidence") || pathname.startsWith("/pipeline") }] : []),
  ];

  useEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);

  const link = (active: boolean, rail = false) =>
    clsx(
      "flex min-h-10 items-center gap-2.5 rounded-md px-3 text-sm font-medium whitespace-nowrap transition-colors",
      "duration-[var(--duration-fast)] ease-[var(--ease-out)]",
      active ? clsx("bg-paper-3 text-ink", rail && "shadow-[inset_2px_0_0_var(--color-accent)]") : "text-ink-2 hover:bg-paper-3 hover:text-ink",
    );

  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[15rem_minmax(0,1fr)]">
      {/* Mobile / tablet top bar (scrolls away so the sticky flow rail gets the room) */}
      <header className="border-b border-rule bg-paper px-4 pt-2 lg:hidden">
        <div className="flex items-center justify-between">
          <NavLink to="/" aria-label="EventShock home" className="rounded-md py-1">
            <Logo size={24} />
          </NavLink>
          <ThemeSwitch compact />
        </div>
        <div className="pb-2">
          <PortfolioSwitcher compact />
          <AdjustLink />
        </div>
        <nav aria-label="Primary" className="-mx-4 flex gap-1 overflow-x-auto px-4 pb-2">
          {nav.map((n) => (
            <NavLink key={n.label} to={n.to} className={() => link(n.active)}>
              <n.icon /> <span>{n.label}</span>
            </NavLink>
          ))}
        </nav>
      </header>

      {/* Desktop rail */}
      <aside className="sticky top-0 hidden h-dvh flex-col gap-6 overflow-y-auto border-r border-rule bg-paper px-3 py-5 lg:flex">
        <NavLink to="/" aria-label="EventShock home" className="rounded-md px-3 py-1">
          <Logo />
        </NavLink>
        <nav aria-label="Primary" className="flex flex-col gap-1">
          {nav.map((n) => (
            <NavLink key={n.label} to={n.to} className={() => link(n.active, true)} aria-current={n.active ? "page" : undefined}>
              <n.icon /> {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto flex flex-col gap-3">
          <AdjustLink />
          <PortfolioSwitcher />
          <ModeBadge />
          <ThemeSwitch />
          <a className="px-3 text-xs text-muted underline-offset-2 hover:text-ink hover:underline" href="/api/docs" target="_blank" rel="noreferrer">
            API reference
          </a>
        </div>
      </aside>

      <main className="min-w-0 px-4 py-6 sm:px-6 lg:px-10 lg:py-8">
        <div className="mx-auto max-w-[78rem]">
          <div key={activePf ?? "default"}>
            <Outlet />
          </div>
        </div>
      </main>
      <AdjustHost />
    </div>
  );
}
