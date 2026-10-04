import { useScopeInfo } from "../../api/hooks";
import { pct } from "../../lib/format";
import { REGION_LABEL, SCOPE_LABEL, THEME_LABEL, type ScopeLevel } from "../../lib/scope";
import { KindBadge } from "../ProvenanceKind";
import { ErrorState, Loading } from "../ui";

const LEVELS: ScopeLevel[] = ["COMPANY", "SECTOR", "MARKET", "UNRESOLVED"];

function Mix({ title, mix }: { title: string; mix: Record<string, number> }) {
  const total = Object.values(mix).reduce((a, b) => a + b, 0);
  return (
    <div>
      <p className="eyebrow">{title}</p>
      {total === 0 ? (
        <p className="mt-2 text-sm text-muted">None yet.</p>
      ) : (
        <ul className="mt-2 space-y-1.5">
          {LEVELS.map((l) => (
            <li key={l} className="grid grid-cols-[6.5rem_minmax(0,1fr)_3.5rem] items-center gap-3 text-sm">
              <span>{SCOPE_LABEL[l]}</span>
              <span className="h-1.5 rounded-sm bg-paper-4" aria-hidden="true">
                <span className="block h-full rounded-sm bg-accent" style={{ width: `${((mix[l] ?? 0) / total) * 100}%` }} />
              </span>
              <span className="num text-right">{(mix[l] ?? 0).toLocaleString("en-US")}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** How "what is this about?" is decided, and how well the sector vocabulary was measured to work. Rules, not a trained model. */
export function ScopeTab() {
  const { data: d, error, isLoading } = useScopeInfo(true);
  if (error) return <ErrorState error={error} />;
  if (isLoading || !d) return <Loading label="Loading the scope rules" />;
  const ev = d.evaluation;
  return (
    <div className="grid gap-10">
      <section aria-labelledby="scope-rules">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-lg font-semibold" id="scope-rules">How the subject of a signal is decided</h2>
          <KindBadge kind="historical" />
        </div>
        <p className="mt-2 max-w-[68ch] text-ink-2">
          Naming a company is one way to find a subject, not a requirement. When no company is named, the text can still be about a sector or the market. The rules run in this
          order, from a configured vocabulary ({d.version}); they are deterministic, they are not a trained model, and a “weak” or “strong” tier is a rule tier, not a probability.
        </p>
        <ol className="mt-4 list-decimal space-y-1.5 pl-5 text-ink-2">
          {d.rules.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ol>
        <p className="mt-4 max-w-[68ch] text-sm text-muted">
          Sectors are the portfolio's six ({Object.entries(d.sectors).map(([k, n]) => `${k}: ${n} terms`).join(", ")}). Market themes: {Object.keys(d.themes).map(THEME_LABEL).join(", ")}.
          Regions: {d.regions.map((r) => REGION_LABEL[r] ?? r).join(", ")}. There is no industry level, because the entity master has no industry data and none is invented.
        </p>
      </section>

      <section aria-labelledby="scope-mix" className="grid gap-8 sm:grid-cols-2">
        <h2 className="sr-only" id="scope-mix">What the data looks like</h2>
        <Mix title="Replayed signals by scope" mix={d.replay_mix} />
        <Mix title="Live and pasted signals by scope" mix={d.live_mix} />
      </section>

      <section aria-labelledby="scope-eval">
        <h2 className="text-lg font-semibold" id="scope-eval">How well does the sector vocabulary work?</h2>
        {ev ? (
          <>
            <p className="mt-2 max-w-[68ch] text-ink-2">
              Measured on {ev.single_issuer_documents.toLocaleString("en-US")} replayed documents that name exactly one company, whose sector is therefore known. The vocabulary never sees the company's name,
              only the words around it. It fired on {ev.vocabulary_fired.toLocaleString("en-US")} of them ({ev.coverage != null ? pct(ev.coverage, 0) : "–"}); headlines are short, so it often finds nothing.
            </p>
            <table className="mt-4 w-full max-w-xl text-sm">
              <thead>
                <tr className="text-left text-muted">
                  <th className="py-1.5 font-medium">Rule tier</th>
                  <th className="py-1.5 text-right font-medium">Named a sector</th>
                  <th className="py-1.5 text-right font-medium">Agreed with the company's sector</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(ev.by_strength).map(([k, v]) => (
                  <tr key={k} className="border-t border-rule">
                    <td className="py-1.5">{k === "STRONG" ? "Strong (two or more terms)" : "Weak (one term)"}</td>
                    <td className="num py-1.5 text-right">{v.predicted}</td>
                    <td className="num py-1.5 text-right">{v.precision != null ? pct(v.precision, 0) : "–"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <details className="disclosure mt-4">
              <summary>By sector</summary>
              <table className="mt-2 w-full max-w-xl text-sm">
                <thead>
                  <tr className="text-left text-muted">
                    <th className="py-1.5 font-medium">Sector</th>
                    <th className="py-1.5 text-right font-medium">Documents</th>
                    <th className="py-1.5 text-right font-medium">Found</th>
                    <th className="py-1.5 text-right font-medium">Correct when named</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(ev.per_sector).map(([k, v]) => (
                    <tr key={k} className="border-t border-rule">
                      <td className="py-1.5">{k}</td>
                      <td className="num py-1.5 text-right">{v.documents}</td>
                      <td className="num py-1.5 text-right">{v.recall != null ? pct(v.recall, 0) : "–"}</td>
                      <td className="num py-1.5 text-right">{v.precision != null ? pct(v.precision, 0) : "–"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
            <ul className="mt-4 list-disc space-y-1.5 pl-5 text-sm text-muted">
              {ev.limits.map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
          </>
        ) : (
          <p className="mt-2 text-muted">No evaluation file is present. Run <code className="num">python -m eventshock.modeling.scope_eval</code>.</p>
        )}
      </section>
    </div>
  );
}
