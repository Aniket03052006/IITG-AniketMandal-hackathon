import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../../api/client";
import { useEventBrief, useMeta } from "../../api/hooks";
import type { Brief } from "../../api/types";
import { useActivePortfolio } from "../../lib/portfolio";
import { BRIEF_KEY, STATEMENT_KIND, sectionAnchor } from "../../lib/brief";
import { Drawer, useOpenDrawer } from "../Drawer";
import { Question } from "../icons";
import { ErrorState, Skeleton } from "../ui";

/** The button that opens the executive brief drawer (`?open=brief`). Hidden where the brief is not served. */
export function BriefButton({ size = "sm" }: { size?: "sm" | "md" }) {
  const { data: meta } = useMeta();
  const [, setOpen] = useOpenDrawer();
  if (meta?.capabilities.executive_brief !== true) return null;
  return (
    <button type="button" className={size === "sm" ? "btn btn-sm" : "btn"} aria-haspopup="dialog" onClick={() => setOpen(BRIEF_KEY)}>
      <Question size={14} /> Executive brief
    </button>
  );
}

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString("en-GB", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "UTC" }) + " UTC" : "n/a");

export function BriefView({ b }: { b: Brief }) {
  const idx = new Map(b.sources.map((s, n) => [s.id, n + 1]));
  return (
    <article className="space-y-6" aria-label="Executive risk brief">
      <header>
        <h2 className="font-display text-xl font-semibold leading-snug">{b.headline}</h2>
        <p className="mt-1 text-xs text-muted">
          {b.mode} · as of {when(b.as_of)} · portfolio: {b.portfolio_name ?? "default"}
        </p>
        <p className="mt-2 max-w-[70ch] text-sm text-ink-2">{b.note}</p>
      </header>
      <nav aria-label="Sections" className="flex flex-wrap gap-x-3 gap-y-1 text-xs">
        {b.sections.map((s, n) => (
          <a key={s.id} href={`#${sectionAnchor(s.id)}`} className="text-ink-2 underline-offset-2 hover:text-ink hover:underline">
            {n + 1}. {s.title}
          </a>
        ))}
      </nav>
      {b.sections.map((sec, n) => (
        <section key={sec.id} id={sectionAnchor(sec.id)} aria-labelledby={`${sectionAnchor(sec.id)}-h`}>
          <h3 id={`${sectionAnchor(sec.id)}-h`} className="text-sm font-semibold tracking-wide">
            {n + 1}. {sec.title}
            {sec.availability !== "AVAILABLE" && <span className="ml-2 text-xs font-normal text-muted">({sec.availability.toLowerCase()})</span>}
          </h3>
          <ul className="mt-2 list-none space-y-2 p-0">
            {sec.statements.map((st, i) => (
              <li key={i} className="text-sm leading-relaxed">
                {st.text}{" "}
                <span className="whitespace-nowrap text-xs text-muted">
                  <span className="chip" role="note">{STATEMENT_KIND[st.kind] ?? st.kind}</span>{" "}
                  {st.source_refs.map((r) => (
                    <a key={r} href="#brief-sources" aria-label={`source ${idx.get(r)}`} className="mr-0.5 underline-offset-2 hover:underline">[{idx.get(r)}]</a>
                  ))}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ))}
      <section id="brief-sources" aria-label="Sources">
        <h3 className="text-sm font-semibold tracking-wide">Sources</h3>
        <ol className="mt-2 list-decimal space-y-1 pl-5 text-xs text-ink-2">
          {b.sources.map((s) => (
            <li key={s.id}>
              {s.label}
              {s.endpoint ? <> — <code>{s.endpoint}</code></> : null}
            </li>
          ))}
        </ol>
      </section>
    </article>
  );
}

/** The drawer itself. Fetched only while open; Markdown copy and print are offered once it has loaded. */
export function BriefDrawer({ eventId }: { eventId: string | undefined }) {
  const [open, setOpen] = useOpenDrawer();
  const [params] = useSearchParams();
  const pf = useActivePortfolio();
  const { data: meta } = useMeta();
  const on = meta?.capabilities.executive_brief === true;
  const isOpen = open === BRIEF_KEY;
  const cycleRaw = params.get("cycle");
  const cycle = cycleRaw != null && /^\d+$/.test(cycleRaw) ? Number(cycleRaw) : null;
  const q = useEventBrief(eventId, on && isOpen, cycle);
  const [note, setNote] = useState<string | null>(null);
  if (!on) return null;
  const copy = async () => {
    try {
      const md = await api.eventBriefMarkdown(eventId as string, { pf, cycle });
      await navigator.clipboard.writeText(md);
      setNote("Markdown copied.");
    } catch {
      setNote("Could not copy. Open /api/events/<id>/brief?format=md instead.");
    }
  };
  return (
    <Drawer open={isOpen} onClose={() => setOpen(null)} title="Executive risk brief" eyebrow="Brief" wide>
      {q.isLoading && <div className="space-y-3"><Skeleton className="h-6 w-2/3" /><Skeleton className="h-40 w-full" /></div>}
      {q.error && <ErrorState error={q.error} retry={() => q.refetch()} />}
      {q.data && (
        <>
          <div className="mb-4 flex flex-wrap items-center gap-2 print:hidden">
            <button type="button" className="btn btn-sm" onClick={copy}>Copy as Markdown</button>
            <button type="button" className="btn btn-sm" onClick={() => window.print()}>Print</button>
            {note && <span role="status" className="text-xs text-muted">{note}</span>}
          </div>
          <BriefView b={q.data} />
        </>
      )}
    </Drawer>
  );
}
