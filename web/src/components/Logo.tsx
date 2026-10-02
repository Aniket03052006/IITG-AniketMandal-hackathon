/** Mark: an "E" whose middle arm is a shock spike. Colours come from tokens so it follows the theme. */
export function LogoMark({ size = 28, className }: { size?: number; className?: string }) {
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
      <path d="M50 12H17V52H50" stroke="var(--color-ink)" />
      <path d="M17 32H27L31 18L37 46L41 32H52" stroke="var(--color-accent)" />
    </svg>
  );
}

export function Logo({ size = 28 }: { size?: number }) {
  return (
    <span className="inline-flex items-center gap-2.5">
      <LogoMark size={size} />
      <span className="font-display text-[1.125rem] font-semibold tracking-[-0.02em] text-ink">EventShock</span>
    </span>
  );
}
