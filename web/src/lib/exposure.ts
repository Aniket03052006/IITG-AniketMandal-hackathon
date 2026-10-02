import type { Contribution } from "../api/types";

/** Largest |delta| across rows, used to scale bars consistently within one chart. */
export function maxAbs(rows: Contribution[]): number {
  return rows.reduce((m, r) => Math.max(m, Math.abs(r.delta)), 0);
}
