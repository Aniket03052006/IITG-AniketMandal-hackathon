import { useMeta, useScenarioHistoryCheck } from "../../api/hooks";
import type { ScenarioHistoryCheck, ShockCheck } from "../../api/types";
import { FACTOR_LABEL, SCOPE_LABEL } from "../../lib/format";
import { StateNotice } from "../StateNotice";
import { Skeleton } from "../ui";

const valueText = (c: ShockCheck) =>
  c.unit === "bp" ? `${c.value > 0 ? "+" : "−"}${Math.abs(c.value).toFixed(0)} bp` : c.unit === "x" ? `×${c.value.toFixed(2)}` : `${c.value > 0 ? "+" : "−"}${Math.abs(c.value * 100).toFixed(1)}%`;

export function HistoryCheckView({ check }: { check: ScenarioHistoryCheck }) {
  return (
    <div>
      <div className="scroll-x">
        <table className="dtable min-w-[40rem]">
          <caption className="sr-only">Each scenario shock against history</caption>
          <thead>
            <tr>
              <th scope="col">Shock as applied</th>
              <th scope="col">Against history</th>
            </tr>
          </thead>
          <tbody>
            {check.checks.map((c) => (
              <tr key={`${c.factor}-${c.scope}`}>
                <th scope="row" className="!font-normal">
                  <span className="block text-ink">{FACTOR_LABEL[c.factor] ?? c.factor}</span>
                  <span className="text-xs text-muted">{SCOPE_LABEL[c.scope] ?? c.scope} · <span className="num">{valueText(c)}</span></span>
                </th>
                <td className="text-sm text-ink-2">
                  {c.reading}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="mt-3 max-w-[78ch] list-disc space-y-1 pl-5 text-xs text-muted">
        {check.caveats.map((t) => (
          <li key={t}>{t}</li>
        ))}
        <li>History used: {check.first_session} to {check.last_session}.</li>
      </ul>
    </div>
  );
}

/** Where the scenario's shocks fall in the history of market moves. Read-only: it never changes a shock or a result. */
export function HistoryCheck({ scenarioId, scale }: { scenarioId: string | undefined; scale: number }) {
  const { data: meta } = useMeta();
  const on = !!meta?.capabilities?.history_check;
  const { data, isLoading, error } = useScenarioHistoryCheck(scenarioId, Math.round(scale * 100) / 100, on && !!scenarioId);
  if (!on || !scenarioId) return null;
  return (
    <section className="mt-6" aria-label="The shocks against history">
      <h4 className="text-sm font-semibold">How large are these shocks by historical standards?</h4>
      <p className="mb-3 mt-1 max-w-[66ch] text-sm text-muted">
        A reality check, not a change: the same magnitudes ranked against 1-, 5- and 21-session moves since 2014. A percentile is a historical frequency, not a probability that this happens.
      </p>
      {isLoading ? <Skeleton className="h-32 w-full" /> : error || !data ? <StateNotice tone="warn" what="The history check could not be loaded" why={error instanceof Error ? error.message : "The request failed."} /> : <HistoryCheckView check={data} />}
    </section>
  );
}
