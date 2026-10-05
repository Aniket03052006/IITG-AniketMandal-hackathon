import type { MarketUse } from "../../api/types";
import { StatusTag } from "../ui";
import { OriginChip } from "./OriginChip";

/** Market data in the score, or the reason it is not: always with the date and how stale it was. */
export function MarketNote({ m }: { m: MarketUse }) {
  return (
    <div className="flex flex-wrap items-start gap-x-2 gap-y-1 text-sm text-ink-2">
      <OriginChip origin="DATA" />
      {m.used ? <StatusTag tone="ok">Market data used</StatusTag> : <StatusTag tone="warn">Market data not used</StatusTag>}
      <span className="min-w-0 flex-1">{m.reason}</span>
    </div>
  );
}
