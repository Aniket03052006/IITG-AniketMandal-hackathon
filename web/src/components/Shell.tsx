import clsx from "clsx";
import { useEffect } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useMeta } from "../api/hooks";
import { dateTime } from "../lib/format";
import { profileLabel, profileNote } from "../lib/provenance";
import { Database, EventIcon, EvidenceIcon, FeedIcon, StressIcon } from "./icons";
import { Logo } from "./Logo";
import { StatusTag } from "./ui";

const NAV = [
  { to: "/", label: "Risk Feed", icon: FeedIcon, end: true, match: (p: string) => p === "/" },
  { to: "/stress", label: "Portfolio Stress", icon: StressIcon, end: false, match: (p: string) => p.startsWith("/stress") },
];

function ModeBadge() {
  const { data } = useMeta();
  return (
    <div className="rounded-md border border-rule bg-paper-2 p-3 text-xs">
      <div className="flex items-center gap-1.5 font-medium text-ink">
        <Database size={13} />
        {profileLabel(data)}
      </div>
      {data && (
        <p className="mt-1.5 leading-snug text-muted">
          {profileNote(data)} Clock pinned to{" "}
          <span className="num text-ink-2">{dateTime(data.as_of)}</span>.
        </p>
      )}
    </div>
  );
}

export function Shell() {
  const { pathname } = useLocation();
  const { data: meta } = useMeta();
  const eventActive = pathname.startsWith("/events/");
  const nav = meta?.replay
    ? [
        ...NAV,
        { to: "/pipeline", label: "Data Pipeline", icon: Database, end: false, match: (p: string) => p.startsWith("/pipeline") },
        { to: "/evidence", label: "Model Evidence", icon: EvidenceIcon, end: false, match: (p: string) => p.startsWith("/evidence") },
      ]
    : NAV;

  useEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);

  const link = (active: boolean, rail = false) =>
    clsx(
      "flex min-h-10 items-center gap-2.5 rounded-md px-3 text-sm font-medium whitespace-nowrap transition-colors",
      "duration-[var(--duration-fast)] ease-[var(--ease-out)]",
      active ? clsx("bg-paper-3 text-ink", rail && "shadow-[inset_2px_0_0_var(--color-accent)]") : "text-ink-2 hover:bg-paper-2 hover:text-ink",
    );

  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[15rem_minmax(0,1fr)]">
      {/* Mobile / tablet top bar */}
      <header className="sticky top-0 z-20 flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-rule bg-paper px-4 py-2 lg:hidden">
        <NavLink to="/" aria-label="EventShock home" className="rounded-md py-1">
          <Logo size={24} />
        </NavLink>
        <nav aria-label="Primary" className="flex gap-1">
          {nav.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end} className={() => link(n.match(pathname))}>
              <n.icon /> <span>{n.label}</span>
            </NavLink>
          ))}
        </nav>
      </header>

      {/* Desktop rail */}
      <aside className="sticky top-0 hidden h-dvh flex-col gap-6 border-r border-rule bg-paper px-3 py-5 lg:flex">
        <NavLink to="/" aria-label="EventShock home" className="rounded-md px-3 py-1">
          <Logo />
        </NavLink>
        <nav aria-label="Primary" className="flex flex-col gap-1">
          {nav.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end} className={() => link(n.match(pathname), true)}>
              <n.icon /> {n.label}
            </NavLink>
          ))}
          <span className={clsx(link(eventActive, true), !eventActive && "pointer-events-none opacity-50")} aria-current={eventActive ? "page" : undefined}>
            <EventIcon /> Event Intelligence
          </span>
        </nav>
        <div className="mt-auto flex flex-col gap-3">
          <ModeBadge />
          <a className="px-3 text-xs text-muted underline-offset-2 hover:text-ink hover:underline" href="/api/docs" target="_blank" rel="noreferrer">
            API reference
          </a>
        </div>
      </aside>

      <main className="min-w-0 px-4 py-6 sm:px-6 lg:px-10 lg:py-8">
        {meta && (
          <div className="mb-6 flex flex-wrap items-center gap-2 lg:hidden">
            <StatusTag tone="demo" icon={<Database size={12} />}>
              {profileLabel(meta)}
            </StatusTag>
          </div>
        )}
        <div className="mx-auto max-w-[78rem]">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
