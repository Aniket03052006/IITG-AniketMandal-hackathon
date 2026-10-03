import type { ImpactKind } from "../lib/impact";
import { KIND_LABEL } from "../lib/impact";
import { Check, Alert, Info } from "./icons";
import { StatusTag } from "./ui";

const TONE = { placeholder: "demo", experimental: "warn", validated: "ok" } as const;
const ICON = { placeholder: <Info size={12} />, experimental: <Alert size={12} />, validated: <Check size={12} /> } as const;

/** What produced an impact number, in words and a tone: placeholder rule, experimental model, validated model. */
export function ImpactLifecycleTag({ kind, detail }: { kind: ImpactKind; detail?: string }) {
  return (
    <StatusTag tone={TONE[kind]} icon={ICON[kind]}>
      {KIND_LABEL[kind]}
      {detail ? <span className="text-muted"> · {detail}</span> : null}
    </StatusTag>
  );
}
