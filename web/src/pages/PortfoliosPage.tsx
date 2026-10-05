import { useState } from "react";
import { Link } from "react-router-dom";
import { useActivePortfolioItem, usePortfolioMutations, usePortfolios } from "../api/hooks";
import type { PortfolioListItem } from "../api/types";
import { ExposurePanel } from "../components/portfolio/ExposurePanel";
import { Plus } from "../components/icons";
import { StateNotice } from "../components/StateNotice";
import { EmptyState, ErrorState, Loading, PageHeader, StatusTag } from "../components/ui";
import { dateTime, money } from "../lib/format";
import { currencySymbol, setActivePortfolio } from "../lib/portfolio";

function PortfolioCard({ p, active, onFocus, focused }: { p: PortfolioListItem; active: boolean; onFocus: () => void; focused: boolean }) {
  const m = usePortfolioMutations();
  const [confirm, setConfirm] = useState(false);
  const user = p.kind === "USER";
  return (
    <li className={`card card-pad ${focused ? "ring-1 ring-accent" : ""}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="font-display text-lg font-semibold leading-snug">{p.name}</h2>
          <p className="mt-1 text-sm text-muted">
            {user ? "Your portfolio" : "Synthetic wholesale-banking book on real issuers · read-only"} · {p.holding_count} position{p.holding_count === 1 ? "" : "s"} ·{" "}
            <span className="num">{money(p.total_value, { currency: currencySymbol(p.base_currency) })}</span>
            {p.updated_at ? ` · updated ${dateTime(p.updated_at)}` : ""}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {active ? <StatusTag tone="ok">In use</StatusTag> : null}
          {!user && <StatusTag tone="demo">Default</StatusTag>}
        </div>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {!active && (
          <button type="button" className="btn btn-primary" onClick={() => setActivePortfolio(user ? p.id : null)}>
            {user ? "Use this portfolio" : "Use default portfolio"}
          </button>
        )}
        <button type="button" className="btn" onClick={onFocus} aria-pressed={focused}>
          {focused ? "Showing exposure" : "Show exposure"}
        </button>
        {user && (
          <>
            <Link className="btn" to={`/portfolios/${p.id}`}>
              Edit
            </Link>
            <button type="button" className="btn" onClick={() => m.duplicate.mutate(p.id)} disabled={m.duplicate.isPending}>
              Duplicate
            </button>
            {confirm ? (
              <span className="flex items-center gap-2 text-sm">
                Delete “{p.name}”?
                <button
                  type="button"
                  className="btn"
                  onClick={() =>
                    m.remove.mutate(p.id, {
                      onSuccess: () => {
                        if (active) setActivePortfolio(null);
                      },
                    })
                  }
                >
                  Yes, delete
                </button>
                <button type="button" className="btn btn-ghost" onClick={() => setConfirm(false)}>
                  Keep
                </button>
              </span>
            ) : (
              <button type="button" className="btn btn-ghost" onClick={() => setConfirm(true)}>
                Delete
              </button>
            )}
          </>
        )}
      </div>
      {(m.duplicate.error || m.remove.error) && <div className="mt-3"><ErrorState error={(m.duplicate.error ?? m.remove.error) as Error} /></div>}
    </li>
  );
}

/** Optional personal portfolios. With none chosen EventShock stresses its synthetic book; "Use default portfolio" always puts it back. */
export function PortfoliosPage() {
  const list = usePortfolios();
  const { id: activeId } = useActivePortfolioItem();
  const [focus, setFocus] = useState<string | null | undefined>(undefined);
  const shown = focus === undefined ? activeId : focus;
  const personal = (list.data ?? []).filter((p) => p.kind === "USER");
  return (
    <>
      <PageHeader
        title="Portfolios"
        sub="Optional. EventShock stresses a synthetic wholesale-banking book unless you choose a portfolio of your own."
        actions={
          <Link className="btn btn-primary" to="/portfolios/new">
            <Plus size={14} /> Create a portfolio
          </Link>
        }
      />
      {activeId && (
        <div className="mb-6 max-w-[64ch]">
          <StateNotice
            tone="info"
            what="You are using your own portfolio"
            why="Event relevance and stress results use its holdings. The synthetic default is untouched."
            next={
              <button type="button" className="btn" onClick={() => setActivePortfolio(null)}>
                Use default portfolio
              </button>
            }
          />
        </div>
      )}
      {list.isLoading && <Loading label="Loading portfolios" />}
      {list.error && <ErrorState error={list.error} retry={() => list.refetch()} />}
      {list.data && (
        <ul className="grid gap-4">
          {list.data.map((p) => (
            <PortfolioCard
              key={p.id}
              p={p}
              active={p.kind === "USER" ? p.id === activeId : !activeId}
              focused={(p.kind === "USER" ? p.id : null) === shown}
              onFocus={() => setFocus(p.kind === "USER" ? p.id : null)}
            />
          ))}
        </ul>
      )}
      {list.data && personal.length === 0 && (
        <div className="mt-6">
          <EmptyState title="You have not created a portfolio yet">
            That is fine: everything works on the synthetic default. Create one to see how an event would affect what you hold.
          </EmptyState>
        </div>
      )}
      {list.data && (
        <div className="mt-10">
          <ExposurePanel id={shown ?? null} />
        </div>
      )}
    </>
  );
}
