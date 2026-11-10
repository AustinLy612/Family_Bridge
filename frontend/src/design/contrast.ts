/**
 * WCAG 2.1 contrast utilities and the list of every token pairing used by components
 * (Plan §5.13.4 "Every token pairing used in components is checked by an automated contrast test").
 *
 * When a component starts using a new foreground/background combination, add it here.
 * `text` = normal text (4.5:1), `large` = ≥ 24 px or ≥ 18.66 px bold (3:1),
 * `ui` = non-text UI indicator such as a focus ring or icon (3:1, WCAG 1.4.11).
 */

export type PairKind = "text" | "large" | "ui";
export interface TokenPair {
  fg: string;
  bg: string;
  kind: PairKind;
  where: string;
}

export const MIN_RATIO: Record<PairKind, number> = {
  text: 4.5,
  large: 3,
  ui: 3,
};

export const TOKEN_PAIRS: TokenPair[] = [
  // Body text
  {
    fg: "--color-ink",
    bg: "--color-bg",
    kind: "text",
    where: "page text on backdrop",
  },
  {
    fg: "--color-ink",
    bg: "--color-surface",
    kind: "text",
    where: "card text",
  },
  {
    fg: "--color-ink-muted",
    bg: "--color-surface",
    kind: "text",
    where: "subtitles, captions",
  },
  {
    fg: "--color-ink-muted",
    bg: "--color-bg",
    kind: "text",
    where: "captions on backdrop",
  },
  {
    fg: "--color-ink-muted",
    bg: "--color-lavender-50",
    kind: "text",
    where: "captions in hero/tiles",
  },
  {
    fg: "--color-ink-muted",
    bg: "--color-card-lavender",
    kind: "text",
    where: "SelectCard caption",
  },
  {
    fg: "--color-ink-muted",
    bg: "--color-card-pink",
    kind: "text",
    where: "SelectCard caption",
  },
  {
    fg: "--color-ink-muted",
    bg: "--color-card-amber",
    kind: "text",
    where: "SelectCard caption",
  },
  {
    fg: "--color-ink-muted",
    bg: "--color-card-blue",
    kind: "text",
    where: "SelectCard caption",
  },
  // Lavender family
  {
    fg: "--color-ink",
    bg: "--color-lavender-50",
    kind: "text",
    where: "tile backgrounds",
  },
  { fg: "--color-ink", bg: "--color-chip-bg", kind: "text", where: "Chip" },
  {
    fg: "--color-ink",
    bg: "--color-nav-active-bg",
    kind: "text",
    where: "active nav pill",
  },
  {
    fg: "--color-ink",
    bg: "--color-lavender-300",
    kind: "text",
    where: "lavender emphasis",
  },
  // CTA, cards, decorative
  {
    fg: "--color-cta-ink",
    bg: "--color-cta-bg",
    kind: "text",
    where: "PrimaryButton",
  },
  {
    fg: "--color-ink",
    bg: "--color-card-pink",
    kind: "text",
    where: "SelectCard pink",
  },
  {
    fg: "--color-ink",
    bg: "--color-card-amber",
    kind: "text",
    where: "SelectCard amber",
  },
  {
    fg: "--color-ink",
    bg: "--color-card-blue",
    kind: "text",
    where: "SelectCard blue",
  },
  {
    fg: "--color-ink",
    bg: "--color-card-lavender",
    kind: "text",
    where: "SelectCard lavender",
  },
  {
    fg: "--color-ink",
    bg: "--color-accent-pink",
    kind: "large",
    where: "display shapes with ink text",
  },
  // Blue / links / focus
  { fg: "--color-link", bg: "--color-surface", kind: "text", where: "links" },
  {
    fg: "--color-surface",
    bg: "--color-blue",
    kind: "text",
    where: "secondary filled button",
  },
  {
    fg: "--color-focus",
    bg: "--color-surface",
    kind: "ui",
    where: "focus ring on cards",
  },
  {
    fg: "--color-focus",
    bg: "--color-bg",
    kind: "ui",
    where: "focus ring on backdrop",
  },
  // Selection indicator: ink check mark on the amber badge (border colour is supplementary)
  {
    fg: "--color-ink",
    bg: "--color-amber",
    kind: "ui",
    where: "SelectCard check badge",
  },
  {
    fg: "--color-border-strong",
    bg: "--color-surface",
    kind: "ui",
    where: "input/secondary borders",
  },
  // Therapist-only destructive action
  // White on the plan red is 4.48:1, so the destructive label is always large bold text (≥ 19 px bold).
  {
    fg: "--color-surface",
    bg: "--color-red",
    kind: "large",
    where: "therapist End session button (19px bold)",
  },
  // Phase 1 notices (info / warning / error) and the optional consent row
  { fg: "--color-ink", bg: "--color-lavender-50", kind: "text", where: "info notice, optional consent row" },
  { fg: "--color-ink", bg: "--color-amber-100", kind: "text", where: "warning notice" },
  { fg: "--color-ink", bg: "--color-pink-100", kind: "text", where: "error notice" },
  {
    fg: "--color-ink-muted",
    bg: "--color-lavender-50",
    kind: "text",
    where: "hint text in optional consent row",
  },
  { fg: "--color-border-strong", bg: "--color-surface", kind: "ui", where: "text input border" },
];

function channel(c: number): number {
  const s = c / 255;
  return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
}

export function parseHex(hex: string): [number, number, number] {
  const m = /^#([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m || !m[1]) throw new Error(`not a #rrggbb colour: ${hex}`);
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

export function luminance(hex: string): number {
  const [r, g, b] = parseHex(hex);
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

export function contrastRatio(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

/** Parse the custom properties of each palette block in tokens.css. */
export function parseTokenBlocks(css: string): Record<string, Record<string, string>> {
  const blocks: Record<string, Record<string, string>> = {};
  const clean = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const re = /([^{}]+)\{([^{}]*)\}/g;
  for (const m of clean.matchAll(re)) {
    const selector = (m[1] ?? "").trim();
    const vars: Record<string, string> = {};
    for (const d of (m[2] ?? "").matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) {
      if (d[1] && d[2]) vars[d[1]] = d[2].trim();
    }
    blocks[selector] = { ...(blocks[selector] ?? {}), ...vars };
  }
  return blocks;
}

/** Resolve var(--x) chains to a final value. */
export function resolveToken(vars: Record<string, string>, name: string, depth = 0): string {
  if (depth > 10) throw new Error(`token cycle at ${name}`);
  const v = vars[name];
  if (v === undefined) throw new Error(`unknown token ${name}`);
  const ref = /^var\((--[\w-]+)\)$/.exec(v);
  return ref?.[1] ? resolveToken(vars, ref[1], depth + 1) : v;
}
