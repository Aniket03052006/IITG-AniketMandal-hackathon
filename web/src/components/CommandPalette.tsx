import clsx from "clsx";
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useLocation, useNavigate } from "react-router-dom";
import { useLiveSwitch, useMeta, useSignals } from "../api/hooks";
import type { EventCategory } from "../api/types";
import { useNav } from "../lib/nav";
import { currentTheme, setTheme } from "../lib/theme";
import { useOpenDrawer } from "./Drawer";
import { CategoryGlyph } from "./Glyph";
import { Brief, Command, Database, Inputs, LabIcon, Moon, Question, Search, Sigma, Wrench } from "./icons";

type Item = {
  id: string;
  group: string;
  label: string;
  hint?: string;
  icon?: React.ReactNode;
  keywords?: string;
  run: () => void;
};

/** Drawers each page offers, so "how is this calculated?" is findable without knowing where the button lives. */
function pageActions(pathname: string, open: (k: string) => void, caps: Record<string, boolean | undefined>): Item[] {
  const a = (id: string, label: string, hint: string, icon: React.ReactNode, key: string): Item => ({ id: `act-${id}`, group: "On this page", label, hint, icon, run: () => open(key) });
  if (pathname.startsWith("/events/")) {
    return [
      a("why", "Why this score?", "the reasons, in plain words", <Question size={15} />, caps.assessment ? "severity" : "why"),
      a("inputs", "Show inputs", "what the model saw, and when it was known", <Inputs size={15} />, caps.assessment ? "assessed" : "inputs"),
      a("math", "How calculated?", "the formula, typeset", <Sigma size={15} />, "math"),
      a("tech", "Technical details", "model, lifecycle, limits", <Wrench size={15} />, "tech"),
      a("audit", "Audit trail", "ids, hashes and versions", <Command size={15} />, "audit"),
      ...(caps.executive_brief ? [a("brief", "Executive brief", "the one-page summary", <Brief size={15} />, "brief")] : []),
    ];
  }
  if (pathname.startsWith("/stress")) {
    return [
      a("math", "How the scenario is calculated", "every formula, step by step", <Sigma size={15} />, "math"),
      a("assumptions", "Scenario assumptions", "the shocks and why they were chosen", <Inputs size={15} />, "assumptions"),
      a("positions", "Show every position", "the full position table", <Command size={15} />, "positions"),
      a("audit", "Audit trail", "run id, engine and portfolio hash", <Command size={15} />, "audit"),
      ...(caps.scenario_lab ? [a("lab", "Scenario lab", "build a custom scenario or reverse-stress the book", <LabIcon size={15} />, "lab")] : []),
    ];
  }
  return [];
}

/** ⌘K / Ctrl-K / "/": jump to any page, signal or explanation. The discoverability backbone of the app. */
export function CommandPalette() {
  const [isOpen, setIsOpen] = useState(false);
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const returnTo = useRef<HTMLElement | null>(null);
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const nav = useNav();
  const { data: meta } = useMeta();
  const signals = useSignals({});
  const [, setDrawer] = useOpenDrawer();
  const liveSwitch = useLiveSwitch();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      const typing = !!t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable);
      if ((e.key === "k" || e.key === "K") && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setIsOpen((o) => !o);
      } else if (e.key === "/" && !typing && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        setIsOpen(true);
      }
    };
    const onOpen = () => setIsOpen(true);
    window.addEventListener("keydown", onKey);
    window.addEventListener("eventshock-palette", onOpen);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("eventshock-palette", onOpen);
    };
  }, []);

  useEffect(() => {
    if (!isOpen) return;
    returnTo.current = document.activeElement as HTMLElement | null;
    setQ("");
    setActive(0);
    const raf = requestAnimationFrame(() => input.current?.focus());
    return () => {
      cancelAnimationFrame(raf);
      returnTo.current?.focus?.();
    };
  }, [isOpen]);

  const items = useMemo<Item[]>(() => {
    const close = () => setIsOpen(false);
    const go = (to: string) => () => {
      close();
      navigate(to);
    };
    const caps = (meta?.capabilities ?? {}) as unknown as Record<string, boolean | undefined>;
    const pages: Item[] = nav.map((n) => ({ id: `nav-${n.label}`, group: "Go to", label: n.label, hint: n.hint, icon: <n.icon size={15} />, run: go(n.to) }));
    const acts = pageActions(pathname, (k) => {
      close();
      setDrawer(k);
    }, caps);
    const settings: Item[] = [
      ...(caps.adjustments ? [{ id: "adjust", group: "Settings", label: "Adjust assumptions", hint: "change scenario sizes, thresholds and transmission weights", icon: <Wrench size={15} />, run: () => { close(); setDrawer("adjust"); } }] : []),
      ...(meta?.profile === "replay"
        ? [{ id: "live", group: "Settings", label: caps.live_enabled ? "Turn live feed off" : "Turn live feed on", hint: caps.live_enabled ? "stop polling; keeps the signals received" : "start polling the news feed (outbound requests)", icon: <Database size={15} />, keywords: "live feed gdelt switch on off poll", run: () => { close(); liveSwitch.mutate({ enabled: !caps.live_enabled, source: null }); } }]
        : []),
      { id: "theme", group: "Settings", label: currentTheme() === "light" ? "Switch to dark theme" : "Switch to light theme", hint: "light is the default", icon: <Moon size={15} />, keywords: "dark light mode appearance", run: () => { close(); setTheme(currentTheme() === "light" ? "dark" : "light"); } },
    ];
    const pool = (signals.data?.items ?? []).filter((s) => s.event_status === "CLASSIFIED");
    const ranked = [...pool].sort((a, b) => (b.severity_score ?? b.impact_score ?? 0) - (a.severity_score ?? a.impact_score ?? 0));
    const sigs: Item[] = ranked.map((s) => ({
      id: `sig-${s.id}`,
      group: "Signals",
      label: s.headline,
      hint: [s.ticker ?? s.entity_name, (s.severity_score ?? s.impact_score) != null ? `${s.severity_score != null ? "severity" : "impact"} ${s.severity_score ?? s.impact_score}` : null].filter(Boolean).join(" · "),
      icon: <CategoryGlyph category={s.category as EventCategory} size="sm" />,
      keywords: `${s.entity_name ?? ""} ${s.ticker ?? ""} ${s.sector ?? ""}`,
      run: go(`/events/${s.id}`),
    }));
    const needle = q.trim().toLowerCase();
    const match = (i: Item) => !needle || `${i.label} ${i.hint ?? ""} ${i.keywords ?? ""}`.toLowerCase().includes(needle);
    return [...pages.filter(match), ...acts.filter(match), ...settings.filter(match), ...sigs.filter(match).slice(0, needle ? 12 : 6)];
  }, [nav, pathname, meta, signals.data, q, navigate, setDrawer, liveSwitch.mutate]);

  useEffect(() => setActive(0), [q]);

  if (!isOpen) return null;

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      e.preventDefault();
      setIsOpen(false);
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => Math.min(a + 1, items.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      items[active]?.run();
    } else if (e.key === "Tab") {
      e.preventDefault(); // focus stays in the palette: the input is the only stop
    }
  };

  let lastGroup = "";
  return createPortal(
    <div className="palette-root" onKeyDown={onKeyDown}>
      <div className="drawer-scrim" aria-hidden="true" onClick={() => setIsOpen(false)} />
      <div role="dialog" aria-modal="true" aria-label="Jump to anything" className="palette">
        <div className="palette-search">
          <Search size={16} />
          <input
            ref={input}
            role="combobox"
            aria-expanded="true"
            aria-controls="palette-list"
            aria-activedescendant={items[active] ? `pal-${items[active]!.id}` : undefined}
            aria-label="Search pages, signals and explanations"
            placeholder="Search pages, signals, explanations…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <kbd className="kbd">Esc</kbd>
        </div>
        <ul id="palette-list" role="listbox" aria-label="Results" className="palette-list">
          {items.length === 0 && <li className="palette-empty">Nothing matches “{q}”. Try a company, a ticker or a page name.</li>}
          {items.map((it, i) => {
            const head = it.group !== lastGroup ? it.group : null;
            lastGroup = it.group;
            return (
              <li key={it.id} role="presentation">
                {head && <p className="palette-group" aria-hidden="true">{head}</p>}
                <div
                  id={`pal-${it.id}`}
                  role="option"
                  aria-selected={i === active}
                  className={clsx("palette-item", i === active && "is-active")}
                  onMouseMove={() => setActive(i)}
                  onClick={() => it.run()}
                >
                  <span className="palette-icon">{it.icon}</span>
                  <span className="min-w-0 flex-1">
                    <span className="palette-label">{it.label}</span>
                    {it.hint && <span className="palette-hint">{it.hint}</span>}
                  </span>
                </div>
              </li>
            );
          })}
        </ul>
        <p className="palette-foot"><kbd className="kbd">↑</kbd><kbd className="kbd">↓</kbd> move · <kbd className="kbd">Enter</kbd> open · <kbd className="kbd">/</kbd> or <kbd className="kbd">⌘K</kbd> anywhere</p>
      </div>
    </div>,
    document.body,
  );
}

/** The visible way in: a search pill in the top bar that opens the palette. */
export function PalettePill({ compact = false }: { compact?: boolean }) {
  const open = () => window.dispatchEvent(new Event("eventshock-palette"));
  if (compact)
    return (
      <button type="button" className="btn btn-icon" aria-label="Jump to anything" data-tip="Jump to anything (⌘K)" onClick={open}>
        <Search size={16} />
      </button>
    );
  return (
    <button type="button" className="palette-pill" onClick={open} aria-label="Jump to anything" aria-keyshortcuts="Meta+K Control+K /">
      <Search size={15} />
      <span>Jump to anything…</span>
      <kbd className="kbd">⌘K</kbd>
    </button>
  );
}
