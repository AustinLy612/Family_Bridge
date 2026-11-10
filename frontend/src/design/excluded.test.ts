/**
 * Plan §5.13.3: excluded Velin elements must not exist — streaks, numeric scores, activity-volume
 * badges/levels/XP, participant-facing activity calendars, partners/community/followers/messaging,
 * leaderboards or parent-vs-teen comparison. Scans user-facing strings and component code.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import en from "../i18n/locales/en.json";
import zhCN from "../i18n/locales/zh-CN.json";

const FORBIDDEN_EN =
  /\b(streaks?|leaderboards?|rank(ing)?s?|xp|level ?up|badges?|achievements?|followers?|following|community|practice partners?|messages?|messaging|chat with|score|points?|active days)\b/i;
const FORBIDDEN_ZH =
  /(连续打卡|连胜|排行|排名|积分|经验值|等级|徽章|成就|粉丝|关注者|社区|私信|消息|得分|分数|活跃天数)/;

function strings(tree: unknown, out: string[] = []): string[] {
  if (typeof tree === "string") out.push(tree);
  else if (tree && typeof tree === "object") for (const v of Object.values(tree)) strings(v, out);
  return out;
}

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) return sourceFiles(p);
    return /\.(tsx|ts)$/.test(name) && !/\.test\.tsx?$/.test(name) ? [p] : [];
  });
}

const SRC = resolve(process.cwd(), "src");

describe("excluded Velin elements (Plan §5.13.3)", () => {
  it("no user-facing English string mentions streaks, scores, badges, leaderboards or messaging", () => {
    expect(strings(en).filter((s) => FORBIDDEN_EN.test(s))).toEqual([]);
  });

  it("no user-facing Chinese string does either", () => {
    expect(strings(zhCN).filter((s) => FORBIDDEN_ZH.test(s))).toEqual([]);
  });

  it("no component, prop or route implements them", () => {
    const code =
      /\b(Streak|Leaderboard|Badge|Achievement|Xp|LevelBar|Follower|Messag(e|ing)|Score)\w*\s*[=(:<]/;
    const offenders = sourceFiles(SRC)
      .filter((f) => code.test(readFileSync(f, "utf-8")))
      .map((f) => f.replace(SRC, "src"));
    expect(offenders).toEqual([]);
  });

  it("StatTile has no target/goal/delta props", () => {
    const src = readFileSync(join(SRC, "design/components/Display.tsx"), "utf-8");
    const sig = /export function StatTile\(\{([^}]*)\}/.exec(src)?.[1] ?? "";
    expect(sig.replace(/\s/g, "")).toBe("icon,value,caption");
  });

  it("CalendarGrid is only used in the design system, the gallery and therapist screens", () => {
    const offenders = sourceFiles(SRC)
      .filter((f) => !/design[\\/]|Gallery\.tsx$|routes[\\/]therapist[\\/]/.test(f))
      .filter((f) => readFileSync(f, "utf-8").includes("<CalendarGrid"));
    expect(offenders).toEqual([]);
  });
});
