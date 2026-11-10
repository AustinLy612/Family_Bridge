import en from "./locales/en.json";
import zhCN from "./locales/zh-CN.json";

type Tree = { [k: string]: string | Tree };

function flatten(tree: Tree, prefix = ""): Map<string, string> {
  const out = new Map<string, string>();
  for (const [k, v] of Object.entries(tree)) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (typeof v === "string") out.set(key, v);
    else for (const [ck, cv] of flatten(v, key)) out.set(ck, cv);
  }
  return out;
}

const enKeys = flatten(en as Tree);
const zhKeys = flatten(zhCN as Tree);

describe("locale files (Plan §7.2: every user-facing key exists in zh-CN and en)", () => {
  it("have identical key sets", () => {
    const missingInZh = [...enKeys.keys()].filter((k) => !zhKeys.has(k));
    const missingInEn = [...zhKeys.keys()].filter((k) => !enKeys.has(k));
    expect({ missingInZh, missingInEn }).toEqual({
      missingInZh: [],
      missingInEn: [],
    });
  });

  it("have no empty strings", () => {
    const empty = [...enKeys, ...zhKeys].filter(([, v]) => v.trim() === "").map(([k]) => k);
    expect(empty).toEqual([]);
  });

  it("use the same interpolation variables in both languages", () => {
    const vars = (s: string) => [...s.matchAll(/{{\s*(\w+)\s*}}/g)].map((m) => m[1]).sort();
    const mismatched = [...enKeys].filter(([k, v]) => {
      const zh = zhKeys.get(k);
      return zh !== undefined && JSON.stringify(vars(v)) !== JSON.stringify(vars(zh));
    });
    expect(mismatched.map(([k]) => k)).toEqual([]);
  });
});
