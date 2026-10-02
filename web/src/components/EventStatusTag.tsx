import type { EventStatus } from "../api/types";
import { CategoryTag, StatusTag } from "./ui";
import type { EventCategory } from "../api/types";

/** What the event stage is willing to claim: a type (finding), "no market event", or "type uncertain" (never a guessed type). */
export function EventStatusTag({ status, category, label }: { status: EventStatus; category: EventCategory; label: (c: string) => string }) {
  if (status === "CLASSIFIED") return <CategoryTag category={category} label={label(category)} />;
  if (status === "NO_EVENT") return <span className="tag text-muted">No market event</span>;
  return <StatusTag tone="warn">Type uncertain</StatusTag>;
}
