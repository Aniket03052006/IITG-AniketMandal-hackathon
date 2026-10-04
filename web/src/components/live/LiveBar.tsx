import clsx from "clsx";
import { useLiveRefresh } from "../../api/hooks";
import type { LiveStatus } from "../../api/types";
import { dateTime } from "../../lib/format";
import { Spinner } from "../icons";

const STATE_WORD: Record<string, string> = {
  OFF: "Live feed off",
  OK: "Live",
  DEGRADED: "Live, degraded",
  ERROR: "Live source unreachable",
  IDLE: "Capture finished",
};

function dot(state: string): string {
  return state === "OK" ? "bg-pos" : state === "DEGRADED" ? "bg-warn" : state === "ERROR" ? "bg-neg" : "bg-faint";
}

/** The feed's honest status line: what is arriving, from where, and what is wrong when something is. Replay data is always served. */
export function LiveBar({ st, newCount, onJumpNew }: { st: LiveStatus; newCount: number; onJumpNew: () => void }) {
  const refresh = useLiveRefresh();
  const on = st.enabled;
  return (
    <section className="card mb-6 flex flex-wrap items-center gap-x-5 gap-y-3 px-4 py-3" aria-label="Live feed status" aria-live="polite">
      <p className="flex items-center gap-2 font-medium text-ink">
        <span className={clsx("inline-block size-2.5 rounded-full", dot(st.state))} aria-hidden="true" />
        {STATE_WORD[st.state] ?? st.state}
        {st.simulated && <span className="text-sm font-normal text-muted">· simulated: a captured file replayed as if live</span>}
      </p>
      {!on && (
        <p className="text-sm text-muted">
          Replay data only. Start with <code className="num">make run-live</code> to poll GDELT, or paste a text on the Analyze page.
        </p>
      )}
      {on && (
        <p className="text-sm text-muted">
          {st.live_signal_count.toLocaleString("en-US")} live signals ·{" "}
          {st.last_success_at ? `last poll ${dateTime(st.last_success_at)}` : "no successful poll yet"}
          {st.next_attempt_at && st.state !== "IDLE" ? ` · next ${dateTime(st.next_attempt_at)}` : ""}
        </p>
      )}
      {on && st.last_error && (
        <p className="w-full text-sm text-warn" role="status">
          {st.state === "ERROR" ? "The source could not be reached" : "Some queries failed"}: {st.last_error}. Nothing was invented; the signals already here are unchanged
          {st.consecutive_failures > 0 ? ` (${st.consecutive_failures} failed ${st.consecutive_failures === 1 ? "poll" : "polls in a row"}, backing off)` : ""}.
        </p>
      )}
      <p className="w-full text-xs text-muted">
        Event type for new text is scored by <span className="num text-ink-2">{st.event_model}</span>
        {st.event_model_note ? ` (${st.event_model_note})` : ""}. Reports after {st.market_context_through ?? "the market data"} get the labelled placeholder impact rule, not the trained model.
      </p>
      <div className="ml-auto flex items-center gap-2">
        {newCount > 0 && (
          <button type="button" className="btn btn-sm btn-primary" onClick={onJumpNew}>
            {newCount} new {newCount === 1 ? "signal" : "signals"}
          </button>
        )}
        {on && st.state !== "IDLE" && (
          <button type="button" className="btn btn-sm" disabled={refresh.isPending} onClick={() => refresh.mutate()}>
            {refresh.isPending ? <Spinner size={13} /> : null} Poll now
          </button>
        )}
      </div>
    </section>
  );
}
