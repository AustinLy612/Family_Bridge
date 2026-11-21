/**
 * FamilyBridge brand mark (D94): two interlocking bridge arches — one for the young person, one for
 * the caregiver — that rise from their own side and overlap in a shared space in the middle, over a
 * common base line. Decorative only; the brand name is always shown as text beside it, so the SVG
 * is hidden from assistive technology.
 */
export function BrandMark({ size = 40 }: { size?: number }) {
  return (
    <svg
      className="fb-brandmark"
      width={size}
      height={size}
      viewBox="0 0 40 40"
      aria-hidden="true"
      focusable="false"
    >
      <rect width="40" height="40" rx="12" className="fb-brandmark__tile" />
      <path d="M8 26.5 C8 10.5 25 10.5 25 26.5" className="fb-brandmark__arch" />
      <path d="M15 26.5 C15 10.5 32 10.5 32 26.5" className="fb-brandmark__arch fb-brandmark__arch--warm" />
      <circle cx="20" cy="23.4" r="1.7" className="fb-brandmark__dot" />
      <path d="M7 30 H33" className="fb-brandmark__deck" />
    </svg>
  );
}
