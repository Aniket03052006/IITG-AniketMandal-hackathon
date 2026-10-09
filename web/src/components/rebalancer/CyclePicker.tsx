const when = (iso: string) => `${new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "UTC" })} UTC`;

/** Choose the cycle the other panels follow. */
export function CyclePicker({ times, cycle, onChange, id = "rb-cycle" }: { times: string[]; cycle: number; onChange: (i: number | null) => void; id?: string }) {
  const last = times.length - 1;
  return (
    <div className="flex flex-wrap items-center gap-3">
      <label htmlFor={id} className="text-sm font-medium">Cycle</label>
      <input id={id} type="range" min={0} max={last} step={1} value={cycle} onChange={(e) => onChange(Number(e.target.value))} className="min-w-40 flex-1" aria-valuetext={when(times[cycle]!)} />
      <span className="num text-sm">{when(times[cycle]!)}</span>
      <button type="button" className="btn btn-sm" onClick={() => onChange(null)} disabled={cycle === last}>Latest</button>
    </div>
  );
}
