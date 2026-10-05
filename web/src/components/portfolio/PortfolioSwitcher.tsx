import { useEffect } from "react";
import { Link } from "react-router-dom";
import { useActivePortfolioItem, usePortfolios } from "../../api/hooks";
import { setActivePortfolio } from "../../lib/portfolio";
import { PortfolioIcon } from "../icons";
import { StatusTag } from "../ui";

/**
 * Which portfolio is being stressed. Personal portfolios are OPTIONAL: with none chosen EventShock uses its synthetic wholesale book, and
 * "Use default portfolio" always puts it back. A stored choice that no longer exists falls back to the default by itself.
 */
export function PortfolioSwitcher({ compact = false }: { compact?: boolean }) {
  const list = usePortfolios();
  const { id, item, stale } = useActivePortfolioItem();
  useEffect(() => {
    if (stale) setActivePortfolio(null);
  }, [stale]);
  const personal = !!id;
  return (
    <div className="rounded-md border border-rule bg-paper-2 p-3 text-xs" aria-label="Portfolio in use">
      <p className="eyebrow flex items-center gap-1.5">
        <PortfolioIcon size={12} /> Portfolio
      </p>
      <label className="mt-1.5 block">
        <span className="sr-only">Portfolio to use</span>
        <select
          className="field w-full"
          value={id ?? "default"}
          onChange={(e) => setActivePortfolio(e.target.value === "default" ? null : e.target.value)}
          disabled={!list.data}
        >
          {(list.data ?? []).map((p) => (
            <option key={p.id} value={p.id}>
              {p.kind === "DEFAULT" ? "Default synthetic book" : p.name}
            </option>
          ))}
          {!list.data && <option value="default">Default synthetic book</option>}
        </select>
      </label>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <StatusTag tone={personal ? "ok" : "demo"}>{personal ? "Your portfolio" : "Default · synthetic"}</StatusTag>
        {item && personal && <span className="num text-muted">{item.holding_count} holdings</span>}
      </div>
      {!compact && (
        <p className="mt-2 leading-snug text-muted">
          {personal ? "Relevance and stress results below use your holdings." : "Optional: create your own portfolio to see how an event affects it."}
        </p>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
        {personal && (
          <button type="button" className="text-ink underline underline-offset-2 hover:text-accent" onClick={() => setActivePortfolio(null)}>
            Use default portfolio
          </button>
        )}
        <Link className="text-ink-2 underline underline-offset-2 hover:text-ink" to="/portfolios">
          {personal ? "Manage" : "Create or manage"}
        </Link>
      </div>
    </div>
  );
}
