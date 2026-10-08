/**
 * Mark: an "E" whose middle arm is a shock spike. Colours come from tokens so it follows the theme.
 * `onChrome` draws it for the navy sidebar: the E in chrome ink, the spike in the pink brand secondary.
 */
export function LogoMark({ size = 28, className, onChrome = false }: { size?: number; className?: string; onChrome?: boolean }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      fill="none"
      strokeWidth={5.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      role="img"
      aria-label="EventShock"
      className={className}
    >
      <path d="M50 12H17V52H50" stroke={onChrome ? "var(--color-chrome-ink)" : "var(--color-ink)"} />
      <path d="M17 32H27L31 18L37 46L41 32H52" stroke={onChrome ? "var(--color-pink)" : "var(--color-accent)"} />
    </svg>
  );
}

export function Logo({ size = 28, onChrome = false }: { size?: number; onChrome?: boolean }) {
  return (
    <span className="inline-flex items-center gap-2.5">
      <LogoMark size={size} onChrome={onChrome} />
      <span className={`logo-word font-display text-[1.125rem] font-bold tracking-[-0.02em] ${onChrome ? "text-chrome-ink" : "text-ink"}`}>EventShock</span>
    </span>
  );
}
