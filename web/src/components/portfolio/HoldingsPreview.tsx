import type { PortfolioIssue, ResolvedPortfolio } from "../../api/types";
import { ASSET_CLASS_LABEL, money, pct } from "../../lib/format";
import { currencySymbol } from "../../lib/portfolio";
import { StateNotice } from "../StateNotice";
import { StatusTag } from "../ui";

const SRC: Record<string, string> = { USER: "yours", REFERENCE: "looked up", DEFAULT_ASSUMPTION: "assumed", DERIVED: "calculated" };

/** The resolved portfolio: every holding with its weight and where each filled-in field came from, then the issues in order of seriousness. */
export function HoldingsPreview({ r }: { r: ResolvedPortfolio }) {
  const ccy = currencySymbol(r.base_currency);
  const errors = r.issues.filter((i) => i.level === "ERROR");
  const warns = r.issues.filter((i) => i.level === "WARNING");
  const infos = r.issues.filter((i) => i.level === "INFO");
  const where = (i: PortfolioIssue) => (i.holding != null && r.holdings[i.holding] ? `${r.holdings[i.holding]!.ticker}: ` : "");
  return (
    <div>
      {errors.length > 0 && (
        <StateNotice
          tone="neg"
          what={errors.length === 1 ? "One thing needs fixing before this can be saved" : `${errors.length} things need fixing before this can be saved`}
          why={
            <ul className="list-disc space-y-1 pl-4">
              {errors.map((i) => (
                <li key={`${i.code}-${i.holding}-${i.message}`}>{i.message}</li>
              ))}
            </ul>
          }
        />
      )}
      {warns.length > 0 && (
        <StateNotice
          className={errors.length ? "mt-3" : ""}
          tone="warn"
          what="Worth knowing"
          why={
            <ul className="list-disc space-y-1 pl-4">
              {warns.map((i) => (
                <li key={`${i.code}-${i.holding}-${i.message}`}>{i.message}</li>
              ))}
            </ul>
          }
        />
      )}
      {infos.length > 0 && (
        <ul className="mt-3 space-y-1 text-xs text-muted">
          {infos.map((i) => (
            <li key={`${i.code}-${i.holding}`}>{where(i)}{i.message}</li>
          ))}
        </ul>
      )}
      {r.holdings.length > 0 && (
        <div className="scroll-x mt-4">
          <table className="dtable" aria-label="Resolved holdings">
            <thead>
              <tr>
                <th>Holding</th>
                <th>Class</th>
                <th>Sector</th>
                <th className="text-right">Weight</th>
                <th className="text-right">Value</th>
                <th>Beta / duration</th>
              </tr>
            </thead>
            <tbody>
              {r.holdings.map((h) => (
                <tr key={h.asset_id}>
                  <td>
                    <span className="font-medium text-ink">{h.ticker}</span>
                    <span className="block text-xs text-muted">{h.name !== h.ticker ? h.name : ""}</span>
                    {!h.in_universe && h.asset_class === "EQUITY" && <StatusTag tone="warn">not an issuer EventShock can name</StatusTag>}
                  </td>
                  <td>{ASSET_CLASS_LABEL[h.asset_class] ?? h.asset_class}</td>
                  <td>
                    {h.sector}
                    <span className="block text-xs text-muted">{h.region}</span>
                  </td>
                  <td className="num text-right">{pct(h.weight, 1)}</td>
                  <td className="num text-right">{money(h.value, { currency: ccy })}</td>
                  <td className="text-sm">
                    {h.beta != null && (
                      <span title={h.basis.join(" · ")}>
                        β {h.beta.toFixed(2)} <span className="text-xs text-muted">({SRC[h.sources.beta ?? "DERIVED"]})</span>
                      </span>
                    )}
                    {h.duration != null && (
                      <span title={h.basis.join(" · ")}>
                        {h.duration.toFixed(1)} y <span className="text-xs text-muted">({SRC[h.sources.duration ?? "DERIVED"]})</span>
                        {h.spread_sensitivity != null && <span className="block text-xs text-muted">credit spread ×{h.spread_sensitivity.toFixed(1)} ({SRC[h.sources.spread_sensitivity ?? "DERIVED"]})</span>}
                      </span>
                    )}
                    {h.beta == null && h.duration == null && <span className="text-muted">–</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
