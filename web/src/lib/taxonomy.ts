import type { EventCategory, Meta } from "../api/types";
import { titleCase } from "./format";

export function categoryLabeler(meta: Meta | undefined) {
  const map = new Map<string, string>(meta?.taxonomy.map((t) => [t.id, t.label]) ?? []);
  return (c: EventCategory | string) => map.get(c) ?? titleCase(c);
}

export function categoryDescriber(meta: Meta | undefined) {
  const map = new Map<string, string>(meta?.taxonomy.map((t) => [t.id, t.description]) ?? []);
  return (c: EventCategory | string) => map.get(c) ?? "";
}
