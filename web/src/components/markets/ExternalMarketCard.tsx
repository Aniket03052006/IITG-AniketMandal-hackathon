import { useExternalMarkets, useMarketTimeline, useMeta } from "../../api/hooks";
import type { EventMarketView } from "../../api/types";
import { INTERPRETATION, MARKET_LABEL, MATCH_STATUS, marketFallback, pp } from "../../lib/markets";
import { History } from "../icons";
import { WhyButtons, WhyDrawers } from "../explain/WhyDrawer";
import { StateNotice } from "../StateNotice";
import { Skeleton } from "../ui";

/** The kind of statement this is. Its own word and outline: it is never one of the four number kinds and never an input. */
export function MarketKind({ synthetic = false }: { synthetic?: boolean }) {
  return (
    <span className="kind kind-state" title="What an independent prediction market is pricing. Never an input to any EventShock number.">
      <History size={12} />
      {MARKET_LABEL}
      {synthetic ? " · SYNTHETIC FIXTURE" : ""}
    </span>
  );
}

const when = (iso: string) => new Date(iso).toLocaleString("en-GB", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "UTC" }) + " UTC";

/** The reason beneath the fixed sentence: never the sentence repeated. */
function why(v: EventMarketView): string {
  const r = v.match?.reason ?? v.reason ?? "No market was matched.";
  return r === marketFallback(v) ? (v.provider.reason ?? "Nothing was matched to this event.") : r;
}

export function ExternalMarketView({ v }: { v: EventMarketView }) {
  const m = v.match;
  const o = m?.market ?? null;
  const status = m ? (MATCH_STATUS[m.status] ?? { label: m.status, says: "" }) : null;
  return (
    <div className="space-y-4">
      {!o ? (
        <StateNotice tone="info" what={marketFallback(v)} why={why(v)} details={v.provider.reason ?? undefined} />
      ) : (
        <div className="card p-5" aria-label="The matched external market">
          <p className="font-display text-lg font-semibold">{o.question}</p>
          <dl className="mt-3 grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <dt className="text-xs text-muted">Implied probability of YES</dt>
              <dd className="num text-xl">{o.probability == null ? "not priced" : `${(o.probability * 100).toFixed(0)}%`}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted">Change since the previous observation</dt>
              <dd className="num text-xl">{pp(o.probability_change_pp)}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted">Open interest · volume</dt>
              <dd className="num">
                {o.open_interest != null ? o.open_interest.toLocaleString("en-GB") : "n/a"} · {o.volume != null ? o.volume.toLocaleString("en-GB") : "n/a"}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted">Observed · status</dt>
              <dd className="num">
                {when(o.observed_at)} · {o.market_status.toLowerCase()}
              </dd>
            </div>
          </dl>
          {v.interpretation && (
            <div className="mt-4 border-t border-rule pt-3">
              <p className="text-sm">
                <span className="chip" role="note">{INTERPRETATION[v.interpretation.code] ?? v.interpretation.code}</span>{" "}
                <span className="text-ink-2">{v.interpretation.text}</span>
              </p>
              <p className="mt-1 text-xs text-muted">{v.interpretation.reason}</p>
            </div>
          )}
          {o.source_url && (
            <p className="mt-3 text-xs">
              <a className="link" href={o.source_url} target="_blank" rel="noreferrer noopener">
                Source market
              </a>
            </p>
          )}
        </div>
      )}
      {m && (
        <details className="disclosure">
          <summary>
            How it was matched: {status?.label}
            {m.theme_label ? ` · theme ${m.theme_label}` : ""}
          </summary>
          <p className="mb-2 mt-2 max-w-[70ch] text-sm text-muted">{status?.says}</p>
          {m.event_gates.length > 0 && (
            <ul className="space-y-1 text-sm">
              {m.event_gates.map((g) => (
                <li key={g.id}>
                  <span className="font-medium">{g.passed ? "Passed" : "Failed"}</span> · {g.label}: <span className="text-muted">{g.detail}</span>
                </li>
              ))}
            </ul>
          )}
          {m.candidates.length > 0 && (
            <div className="scroll-x mt-3">
              <table className="dtable min-w-[36rem]">
                <caption className="sr-only">Candidate markets in the matched theme and the gates each faced</caption>
                <thead>
                  <tr>
                    <th scope="col">Market</th>
                    <th scope="col">Gates</th>
                    <th scope="col">Chosen</th>
                  </tr>
                </thead>
                <tbody>
                  {m.candidates.map((c) => (
                    <tr key={c.market_id}>
                      <th scope="row" className="!font-normal">{c.question}</th>
                      <td className="text-xs">{c.gates.map((g) => `${g.id.toLowerCase()} ${g.passed ? "passed" : "failed"}`).join(" · ")}</td>
                      <td>{c.chosen ? "yes" : "no"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </details>
      )}
      <ul className="max-w-[78ch] list-disc space-y-1 pl-5 text-xs text-muted">
        <li>{v.note}</li>
        {v.caveats.map((c) => (
          <li key={c}>{c}</li>
        ))}
      </ul>
    </div>
  );
}

/** The EXTERNAL MARKET VIEW of an event: what an independent prediction market appears to price about its theme, kept apart from EventShock's own assessment and from historical analogues. */
export function ExternalMarketCard({ eventId }: { eventId: string }) {
  const { data: meta } = useMeta();
  const on = meta?.capabilities?.external_markets === true;
  const { data, isLoading, error } = useExternalMarkets(eventId, on);
  if (!on) return null;
  return (
    <section className="mt-10" aria-label="External market view">
      <div className="flex flex-wrap items-center gap-3">
        <h3 className="text-lg font-semibold">External market view</h3>
        <MarketKind synthetic={data?.provider.synthetic} />
      </div>
      <p className="mb-5 mt-1 max-w-[70ch] text-sm text-muted">
        What an independent prediction market appears to price about this event&apos;s theme. It is shown beside EventShock&apos;s assessment, never inside it: it does not change the severity score, the portfolio mapping or any stress figure.
      </p>
      {isLoading ? (
        <Skeleton className="h-32 w-full" />
      ) : error || !data ? (
        <StateNotice tone="warn" what="External market data unavailable." why={error instanceof Error ? error.message : "The request failed."} />
      ) : (
        <>
          <ExternalMarketView v={data} />
          {data.match?.market && <MarketTimelineTable eventId={eventId} />}
          <div className="mt-4">
            <WhyButtons subjects={["MARKET"]} />
          </div>
          <WhyDrawers eventId={eventId} subjects={["MARKET"]} />
        </>
      )}
    </section>
  );
}

/** The four kinds of statement an event page mixes, with the external market kept as its own. */
export function FourWayLegend() {
  const items = [
    ["MODEL ASSESSMENT", "EventShock's own reading and scorecard: a triage, not outcome-calibrated."],
    ["HISTORICAL OBSERVATION", "What happened after similar past reports: precedent, never a forecast."],
    ["EXTERNAL MARKET OBSERVATION", "What an independent prediction market is pricing: never an input."],
    ["SCENARIO ASSUMPTION", "A chosen shock run through the stress engine: a simulation, not a prediction."],
  ];
  return (
    <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2" aria-label="Four kinds of statement">
      {items.map(([k, says]) => (
        <div key={k} className="min-w-0">
          <dt className="text-xs font-semibold tracking-wide">{k}</dt>
          <dd className="mt-1 text-sm text-muted">{says}</dd>
        </div>
      ))}
    </dl>
  );
}

const KIND_WORD: Record<string, string> = {
  SOURCE_EVENT: "Source event",
  EVENTSHOCK_ASSESSMENT: "EventShock assessment",
  EXTERNAL_MARKET_OBSERVATION: "External market observation",
  SCENARIO_ASSUMPTION: "Scenario assumption",
  REALISED_OUTCOME: "Realised outcome",
};

/** The event's timeline with the matched market's probability path merged in. Every row says what KIND of statement it is; they are never blurred. */
export function MarketTimelineTable({ eventId }: { eventId: string }) {
  const { data, isLoading } = useMarketTimeline(eventId, true);
  if (isLoading) return <Skeleton className="mt-4 h-24 w-full" />;
  if (!data || data.items.length === 0) return null;
  return (
    <details className="disclosure mt-4">
      <summary>Event and market timeline ({data.items.length} items)</summary>
      <div className="scroll-x mt-3">
        <table className="dtable min-w-[40rem]">
          <caption className="sr-only">The event timeline with the external market&apos;s probability path, each row labelled by the kind of statement it is</caption>
          <thead>
            <tr>
              <th scope="col">When (UTC)</th>
              <th scope="col">Kind</th>
              <th scope="col">What</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((i, n) => (
              <tr key={`${i.at}-${i.kind}-${n}`}>
                <td className="num whitespace-nowrap text-sm">{when(i.at)}</td>
                <td className="text-xs">{KIND_WORD[i.kind] ?? i.kind}</td>
                <td className="text-sm">
                  <span className="font-medium">{i.label}</span> <span className="text-muted">{i.detail}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}
