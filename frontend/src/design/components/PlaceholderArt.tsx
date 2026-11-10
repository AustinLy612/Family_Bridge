/**
 * Abstract placeholder shapes for illustration slots until original FamilyBridge art is
 * commissioned (D20, O18). Sizes match the final slots so art can drop in without layout
 * changes. Decorative only: hidden from assistive tech, and callers hide it entirely when the
 * "Show illustrations" setting is off.
 */
export type ArtSlot = "hero" | "avatar" | "empty";

const SIZES: Record<ArtSlot, { w: number; h: number }> = {
  hero: { w: 200, h: 140 },
  avatar: { w: 48, h: 48 },
  empty: { w: 160, h: 120 },
};

export function PlaceholderArt({
  slot,
  size,
  className,
}: {
  slot: ArtSlot;
  size?: number;
  className?: string;
}) {
  const base = SIZES[slot];
  return (
    <svg
      className={`fb-art ${className ?? ""}`}
      width={size ?? base.w}
      height={size ?? base.h}
      viewBox={`0 0 ${base.w} ${base.h}`}
      aria-hidden="true"
      focusable="false"
      data-slot={slot}
    >
      {slot === "avatar" && (
        <>
          <rect width="48" height="48" fill="var(--color-lavender-200)" />
          <circle cx="24" cy="20" r="9" fill="var(--color-amber)" />
          <rect x="10" y="32" width="28" height="18" rx="9" fill="var(--color-decor)" opacity="0.8" />
        </>
      )}
      {slot === "hero" && (
        <>
          <circle cx="140" cy="70" r="56" fill="var(--color-lavender-300)" opacity="0.7" />
          <rect x="30" y="50" width="76" height="76" rx="22" fill="var(--color-amber)" opacity="0.85" />
          <circle cx="168" cy="28" r="14" fill="var(--color-decor)" opacity="0.75" />
          <rect x="96" y="96" width="44" height="28" rx="14" fill="var(--color-blue-100)" />
        </>
      )}
      {slot === "empty" && (
        <>
          <rect x="20" y="30" width="120" height="70" rx="20" fill="var(--color-lavender-100)" />
          <circle cx="80" cy="56" r="18" fill="var(--color-lavender-300)" />
          <rect x="56" y="82" width="48" height="10" rx="5" fill="var(--color-amber)" opacity="0.7" />
        </>
      )}
    </svg>
  );
}
