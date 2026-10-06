import { STORY } from "../../lib/digest";

/** The whole product in one line: information to decision brief. Every step is derived from the one before it, and nothing downstream feeds back into the score. */
export function StoryChain() {
  return (
    <details className="disclosure">
      <summary>How it fits together: from information to a decision brief</summary>
      <ol className="mt-3 grid list-none gap-2 p-0 sm:grid-cols-2 lg:grid-cols-4" aria-label="From information to decision brief">
        {STORY.map((s, i) => (
          <li key={s.id} className="rounded-sm border border-rule bg-paper-3 p-3">
            <p className="eyebrow">{String(i + 1).padStart(2, "0")}</p>
            <p className="font-medium text-ink">{s.label}</p>
            <p className="mt-1 text-xs text-ink-2">{s.says}</p>
          </li>
        ))}
      </ol>
    </details>
  );
}
