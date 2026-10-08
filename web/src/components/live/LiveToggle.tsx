import clsx from "clsx";
import { useId, useState } from "react";
import { useLiveRefresh, useLiveStatus, useLiveSwitch, useMeta } from "../../api/hooks";
import { LIVE_SOURCE_KINDS, type LiveSourceKind, type LiveStatus } from "../../api/types";
import { dateTime } from "../../lib/format";
import { Spinner } from "../icons";

const ADAPTER_LABEL: Record<string, string> = { "gdelt-live": "news", "sec-edgar-live": "SEC filings" };
const asKind = (k: string | null | undefined): LiveSourceKind | null => (LIVE_SOURCE_KINDS as readonly string[]).includes(k ?? "") ? (k as LiveSourceKind) : null;

/** "news 120 · SEC filings 3": which sources actually delivered, so "two sources" is something you can see. */
export function deliveredBySource(st: LiveStatus): string {
  return Object.entries(st.fetched_by_adapter ?? {}).map(([k, n]) => `${ADAPTER_LABEL[k] ?? k} ${n.toLocaleString("en-US")}`).join(" · ");
}

const STATE_WORD: Record<string, string> = {
  OFF: "Off",
  IDLE: "Waiting for first poll",
  OK: "On",
  DEGRADED: "On, degraded",
  ERROR: "Source unreachable",
};

const dotClass = (state: string) => (state === "OK" ? "bg-pos" : state === "DEGRADED" ? "bg-warn" : state === "ERROR" ? "bg-neg" : "bg-faint");

/** What the one-line status says: the state, and for a capture that it is simulated. */
export function liveSummary(st: LiveStatus): string {
  if (!st.enabled) return "Off";
  const finished = st.simulated && st.state === "IDLE" && st.last_success_at ? "Capture finished" : (STATE_WORD[st.state] ?? st.state);
  return st.simulated ? `${finished} · simulated` : finished;
}

/**
 * The Live switch: one place, on every page, to turn the live feed on and off. Off is the default at every start. The switch reflects what
 * the server says (never an optimistic guess), and turning it on is the explicit act that allows outbound requests to the chosen source.
 */
export function LiveToggle() {
  const { data: meta } = useMeta();
  const replay = meta?.profile === "replay";
  const on = meta?.capabilities.live_enabled === true;
  const status = useLiveStatus(replay, on);
  const flip = useLiveSwitch();
  const refresh = useLiveRefresh();
  const st = status.data;
  // the user's pick, else what is running, else the first source the server can start (two live sources when both are available)
  const [picked, setKind] = useState<LiveSourceKind | null>(null);
  const consent = useId();

  if (!replay || !st) return null;
  const pending = flip.isPending;
  const checked = st.enabled;
  const available = (k: LiveSourceKind | null) => (k && st.source_choices.find((c) => c.kind === k)?.available ? k : null);
  const kind: LiveSourceKind = (checked ? asKind(st.source_kind) : null) ?? available(picked) ?? asKind(st.source_choices.find((c) => c.available)?.kind) ?? "gdelt";
  const choice = st.source_choices.find((c) => c.kind === kind);
  const label = checked ? "Turn live off" : `Turn live on${choice ? `, source: ${choice.label}` : ""}`;
  const toggle = () => flip.mutate({ enabled: !checked, source: checked ? null : kind });
  const pick = (k: LiveSourceKind) => {
    setKind(k);
    if (checked && k !== st.source_kind) flip.mutate({ enabled: true, source: k });
  };

  return (
    <div className="ctx-item live-ctl" aria-label="Live feed">
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        aria-describedby={consent}
        aria-busy={pending}
        className="live-switch"
        data-error={flip.isError ? "true" : undefined}
        disabled={pending}
        onClick={toggle}
      >
        <span className="live-track" aria-hidden="true">
          <span className="live-knob" />
        </span>
        <span className="font-medium text-ink">Live</span>
        {pending && <Spinner size={13} />}
      </button>
      <details className="ctx-pop">
        <summary>
          <span className={clsx("ctx-dot", dotClass(st.state))} aria-hidden="true" />
          <span>{liveSummary(st)}</span>
        </summary>
        <div className="ctx-pop-body" role="group" aria-label="Live feed settings">
          <p className="font-medium text-ink">Live feed</p>
          <fieldset className="mt-2 grid gap-1.5">
            <legend className="sr-only">Source</legend>
            {st.source_choices.map((c) => (
              <label key={c.kind} className={clsx("flex items-start gap-2", !c.available && "text-muted")}>
                <input
                  type="radio"
                  name="live-source"
                  className="mt-1"
                  checked={kind === c.kind}
                  disabled={!c.available || pending}
                  onChange={() => { const k = asKind(c.kind); if (k) pick(k); }}
                />
                <span>
                  <span className="text-ink">{c.label}</span>
                  <span className="block text-xs text-muted">{c.available ? (c.network ? "makes outbound requests" : "reads a local file; no news-feed requests") : c.reason}</span>
                </span>
              </label>
            ))}
          </fieldset>
          {checked && (
            <p className="num mt-2 text-xs text-muted">
              {st.live_signal_count.toLocaleString("en-US")} live signals · {st.last_success_at ? `last poll ${dateTime(st.last_success_at)}` : "no successful poll yet"}
              {st.next_attempt_at && st.state !== "IDLE" ? ` · next ${dateTime(st.next_attempt_at)}` : ""}
              {deliveredBySource(st) ? ` · received: ${deliveredBySource(st)}` : ""}
            </p>
          )}
          {checked && st.last_poll_note && <p className="num mt-1 text-xs text-muted">{st.last_poll_note}</p>}
          {(flip.error || st.last_error) && (
            <p className="mt-2 text-xs text-warn" role="alert">
              {flip.error ? flip.error.message : `${st.last_error}. The signals already here are unchanged.`}
            </p>
          )}
          <div className="mt-2.5 flex items-center gap-2">
            <button type="button" className="btn btn-sm btn-primary" disabled={pending} onClick={toggle}>
              {checked ? "Turn off" : "Turn on"}
            </button>
            {checked && st.state !== "IDLE" && (
              <button type="button" className="btn btn-sm" disabled={refresh.isPending || pending} onClick={() => refresh.mutate()}>
                {refresh.isPending ? <Spinner size={13} /> : null} Poll now
              </button>
            )}
          </div>
          <p id={consent} className="mt-2.5 text-xs leading-snug text-muted">
            {checked
              ? "Turning it off stops new requests and keeps the signals already received."
              : "Off by default. Turning it on makes outbound requests to the chosen source. Text you paste is never sent to it."}
          </p>
        </div>
      </details>
    </div>
  );
}
