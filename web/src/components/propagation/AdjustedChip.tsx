import type { AdjustmentNotice } from "../../api/types";
import { useOpenDrawer } from "../Drawer";
import { Wrench } from "../icons";

/** Shown on a side-car answer when any of the values behind it was adjusted by hand. Opens the Adjust drawer, which shows each value against its default. */
export function AdjustedChip({ notice }: { notice: AdjustmentNotice | null | undefined }) {
  const [, setOpen] = useOpenDrawer();
  if (!notice || notice.count === 0) return null;
  return (
    <button type="button" className="kind kind-prior cursor-pointer" onClick={() => setOpen("adjust")} aria-haspopup="dialog" title={notice.note}>
      <Wrench size={12} />
      {notice.count} adjusted by you
    </button>
  );
}

/** The entry point on a panel: opens the Adjust drawer. */
export function AdjustButton({ label = "Adjust assumptions" }: { label?: string }) {
  const [, setOpen] = useOpenDrawer();
  return (
    <button type="button" className="btn" onClick={() => setOpen("adjust")} aria-haspopup="dialog">
      <Wrench size={13} /> {label}
    </button>
  );
}
