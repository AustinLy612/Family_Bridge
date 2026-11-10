import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { MIN_RATIO, TOKEN_PAIRS, contrastRatio, parseTokenBlocks, resolveToken } from "./contrast";

const tokensCss = readFileSync(resolve(process.cwd(), "src/design/tokens.css"), "utf-8");
const blocks = parseTokenBlocks(tokensCss);
const base = blocks[":root"] ?? {};
const calm = blocks[':root[data-palette="calm"]'] ?? {};
const high = blocks[':root[data-contrast="high"]'] ?? {};

// Every palette combination a participant can choose.
const VARIANTS: Record<string, Record<string, string>> = {
  default: base,
  calm: { ...base, ...calm },
  "high-contrast": { ...base, ...high },
  "calm + high-contrast": { ...base, ...calm, ...high },
};

describe("design token contrast (WCAG 2.1 AA, Plan §5.13.4)", () => {
  it("parses the token file", () => {
    expect(Object.keys(base).length).toBeGreaterThan(30);
    expect(Object.keys(calm).length).toBeGreaterThan(0);
  });

  it("keeps the reference palette values from the plan", () => {
    expect(base["--color-bg"]).toBe("#f7f4f6");
    expect(base["--color-ink"]).toBe("#1f2323");
    expect(base["--color-lavender-300"]).toBe("#c1aace");
    expect(base["--color-amber"]).toBe("#f1a412");
    expect(base["--color-blue"]).toBe("#2e24f4");
    expect(base["--color-red"]).toBe("#d24734");
  });

  for (const [variant, vars] of Object.entries(VARIANTS)) {
    for (const pair of TOKEN_PAIRS) {
      it(`${variant}: ${pair.fg} on ${pair.bg} (${pair.kind}, ${pair.where})`, () => {
        const ratio = contrastRatio(resolveToken(vars, pair.fg), resolveToken(vars, pair.bg));
        expect(ratio).toBeGreaterThanOrEqual(MIN_RATIO[pair.kind]);
      });
    }
  }

  it("confirms white body text on the accent pink fails, so pink never carries small white text", () => {
    expect(contrastRatio("#ffffff", "#ff38c2")).toBeLessThan(4.5);
  });
});
