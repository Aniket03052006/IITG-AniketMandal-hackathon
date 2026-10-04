import { CHANNEL_LABEL, relevanceShort, SCOPE_LABEL, type ScopeLevel } from "../../lib/scope";
import { StatusTag } from "../ui";

/** What the signal is about. Words carry the meaning; the tone only reinforces it. */
export function ScopeTag({ level, sector, strength }: { level: ScopeLevel; sector?: string | null; strength?: string | null }) {
  const tone = level === "UNRESOLVED" ? "warn" : "demo";
  return (
    <StatusTag tone={tone}>
      {SCOPE_LABEL[level]}
      {level === "SECTOR" && sector ? ` · ${sector}` : ""}
      {level === "SECTOR" && strength === "WEAK" ? " (weak hint)" : ""}
    </StatusTag>
  );
}

export function ChannelTag({ channel }: { channel: string }) {
  if (channel === "REPLAY") return null;
  return <StatusTag tone="ok">{CHANNEL_LABEL[channel] ?? channel}</StatusTag>;
}

export function RelevanceTag({ level, share }: { level: string; share: number | null | undefined }) {
  return <StatusTag tone={level === "UNDETERMINED" || level === "NONE" ? "demo" : "ok"}>{relevanceShort(level, share)}</StatusTag>;
}
