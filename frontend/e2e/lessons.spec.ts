/**
 * Phase 5 E2E: individual skill learning (Plan §5.5; Phase 5 acceptance), on the mock LLM.
 * - Adolescent, in zh-CN and en: an AI-recommended lesson with the check-in answered and one
 *   with it skipped, a quick check with a retake, and a group-review lesson.
 * - Caregiver: a structured lesson and a group-review lesson.
 * - Safety: a rule-violating model sentence never reaches the browser; a high-risk reply stops
 *   the lesson, shows help and appears in the therapist's queue.
 * Each run creates one therapist, group and two families (fictional data, unique names).
 */
import { expect as baseExpect, test, type Browser, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { RUN, completeOnboarding, demoAdmin, readCode, redeem, signIn, signOut } from "./helpers";

type Lang = "en" | "zh-CN";
type Tree = { [k: string]: string | Tree };
const here = dirname(fileURLToPath(import.meta.url));
const LOCALES: Record<Lang, Tree> = {
  en: JSON.parse(readFileSync(resolve(here, "../src/i18n/locales/en.json"), "utf-8")) as Tree,
  "zh-CN": JSON.parse(readFileSync(resolve(here, "../src/i18n/locales/zh-CN.json"), "utf-8")) as Tree,
};
const SKILL = { en: "TIPP skills", "zh-CN": "TIPP技能" };
const MODULE = { en: "Distress tolerance", "zh-CN": "痛苦忍受" };
// "point" alone is ordinary prose ("the point of the skill"); points as a score are not
const NO_SCORE = /\b(score|fail(ed|ure)?|points)\b|\d+\s*points?\b|\d\s*\/\s*5|分数|得分|积分|不及格/i;
test.use({ actionTimeout: 15_000 });
// AI-backed steps (retrieval, mock generation) can take several seconds on a cold API.
const expect = baseExpect.configure({ timeout: 20_000 });

const RULE_TRIGGER = "[[mock:rule-violation]]"; // mock provider only (app/ai/mock.py)

function tr(lang: Lang, key: string, vars: Record<string, string | number> = {}): string {
  let node: string | Tree = LOCALES[lang];
  for (const part of key.split(".")) node = (node as Tree)[part] ?? key;
  let s = node as string;
  for (const [k, v] of Object.entries(vars)) s = s.replaceAll(`{{${k}}}`, String(v));
  return s;
}

interface World {
  therapist: Page;
  /** Family A: the English adolescent flow, then the safety test; and the caregiver. */
  teenA: Page;
  teenAAlias: string;
  carer: Page;
  /** Family B: the Chinese adolescent flow. */
  teenB: Page;
}

/**
 * One therapist, group and two families for the whole file: invitation codes are rate-limited
 * per IP (20 per 5 minutes), so each test building its own family would trip the limiter.
 */
async function setUp(browser: Browser): Promise<World> {
  const id = RUN;
  const page = await browser.newPage();
  const admin = demoAdmin();
  await signIn(page, admin.username, admin.password);
  await page.getByRole("button", { name: "New therapist code" }).click();
  const therapistCode = await readCode(page);
  await signOut(page);
  await page.close();

  const therapist = await redeem(browser, therapistCode, `e2e-lt-${id}`, `Dr Learn ${id}`);
  await therapist.getByLabel("New group name").fill(`Learn group ${id}`);
  await therapist.getByRole("button", { name: "Create" }).click();
  await therapist.getByRole("link", { name: new RegExp(`Learn group ${id}`) }).click();
  const groupUrl = therapist.url();
  await recordGroupSkill(therapist);

  async function family(tag: string, withCarer: boolean): Promise<{ teen: Page; carer?: Page }> {
    await therapist.goto(groupUrl);
    await therapist.getByLabel("New family label").fill(`Learn family ${id}-${tag}`);
    await therapist.getByRole("button", { name: "Create" }).click();
    await therapist.getByRole("link", { name: new RegExp(`Learn family ${id}-${tag}`) }).click();
    await therapist.getByLabel("Account type").selectOption("adolescent");
    await therapist.getByRole("button", { name: "Generate code" }).click();
    const teenCode = await readCode(therapist);
    let carerCode = "";
    if (withCarer) {
      await therapist.getByRole("button", { name: "Generate code" }).click();
      carerCode = await readCode(therapist);
    }
    const teen = await redeem(browser, teenCode, `e2e-lteen-${id}-${tag}`, `Teen ${id}-${tag}`);
    await completeOnboarding(teen, "/teen");
    if (!withCarer) return { teen };
    const carer = await redeem(browser, carerCode, `e2e-lcarer-${id}-${tag}`, `Carer ${id}-${tag}`);
    await completeOnboarding(carer, "/caregiver");
    return { teen, carer };
  }

  const a = await family("a", true);
  const b = await family("b", false);
  return { therapist, teenA: a.teen, teenAAlias: `Teen ${id}-a`, carer: a.carer!, teenB: b.teen };
}

test.describe.configure({ mode: "serial" });
let world: World;
test.beforeAll(async ({ browser }) => {
  test.setTimeout(180_000);
  world = await setUp(browser);
});

async function setLanguage(page: Page, lang: Lang) {
  if ((await page.locator("html").getAttribute("lang")) === lang) return;
  // ServerPrefsSync saves the switch to the account (debounced); lessons use the account language
  const saved = page.waitForResponse(
    (r) => r.url().endsWith("/api/v1/me") && r.request().method() === "PATCH",
  );
  await page
    .getByRole("radio", { name: lang === "en" ? "English" : "简体中文" })
    .first()
    .click();
  await expect(page.locator("html")).toHaveAttribute("lang", lang);
  expect((await saved).ok()).toBe(true);
}

async function recordGroupSkill(therapist: Page) {
  await expect(therapist.getByRole("heading", { name: "Skills covered in group sessions" })).toBeVisible();
  await therapist.getByText("Distress tolerance", { exact: true }).click();
  await therapist.getByRole("checkbox", { name: "TIPP skills" }).check();
  await therapist.getByLabel("Note (therapists only)").fill("Fictional note");
  await therapist.getByRole("button", { name: "Add record" }).click();
  await expect(therapist.getByText(/TIPP skills — Fictional note/)).toBeVisible();
}

async function fillProfile(teen: Page, lang: Lang) {
  await teen.goto("/teen/learn");
  await teen.getByRole("link", { name: tr(lang, "learn.profileFirst.action") }).click();
  await teen.getByLabel(tr(lang, "learn.profile.grade")).selectOption("grade_9");
  await teen.getByRole("button", { name: tr(lang, "learn.profile.hobby.music") }).click();
  await teen.getByRole("button", { name: tr(lang, "learn.profile.concern.sleep") }).click();
  await teen.getByRole("button", { name: tr(lang, "account.save") }).click();
  await expect(teen.getByText(tr(lang, "account.saved"))).toBeVisible();
}

async function mood(page: Page, lang: Lang, value: 1 | 2 | 3 | 4 | 5, submitKey: string) {
  await page.getByRole("radio", { name: tr(lang, `learn.mood.${value}`) }).click();
  await page.getByRole("button", { name: tr(lang, submitKey) }).click();
}

async function reply(page: Page, lang: Lang, text: string) {
  await page.getByLabel(tr(lang, "learn.lesson.reply")).fill(text);
  await page.getByRole("button", { name: tr(lang, "learn.lesson.send") }).click();
  await expect(page.getByLabel(tr(lang, "learn.lesson.reply"))).toHaveValue("");
}

async function startLesson(teen: Page, lang: Lang) {
  await teen.goto("/teen/learn");
  await teen.getByRole("button", { name: tr(lang, "learn.start.action") }).click();
  await expect(teen).toHaveURL(/\/teen\/learn\/[0-9a-f-]{36}$/);
  await mood(teen, lang, 3, "learn.next");
}

async function finishWithMood(teen: Page, lang: Lang) {
  await expect(teen.getByTestId("lesson-summary")).toBeVisible();
  await mood(teen, lang, 4, "learn.lesson.finish");
  await expect(teen.getByText(tr(lang, "learn.test.intro"))).toBeVisible();
}

async function answerTest(teen: Page, lang: Lang, wrong: number) {
  for (let n = 1; n <= 5; n++) {
    const card = teen.getByTestId("test-question");
    await expect(card).toContainText(tr(lang, "learn.test.question", { n, total: 5 }));
    // the mock always puts the right answer first
    await card
      .locator(".fb-option")
      .nth(n <= wrong ? 1 : 0)
      .click();
    await expect(
      card.getByText(n <= wrong ? tr(lang, "learn.test.notQuite") : tr(lang, "learn.test.right")),
    ).toBeVisible();
    await card.getByRole("button", { name: tr(lang, "learn.next") }).click();
  }
}

for (const lang of ["en", "zh-CN"] as const) {
  test(`adolescent lessons, quick check with retake and group review (${lang})`, async () => {
    test.setTimeout(300_000);
    const teen = lang === "en" ? world.teenA : world.teenB;
    await setLanguage(teen, lang);
    await fillProfile(teen, lang);

    // 1. AI-recommended lesson with the check-in answered
    await startLesson(teen, lang);
    await expect(teen.getByRole("button", { name: tr(lang, "learn.checkin.skip") })).toBeVisible();
    await teen
      .locator("form:has(textarea) textarea")
      .fill(lang === "en" ? "School was busy this week." : "这周学校挺忙的。");
    await teen.getByRole("button", { name: tr(lang, "learn.checkin.share") }).click();
    await expect(teen.getByText(tr(lang, "learn.choose.suggested"))).toBeVisible();
    await expect(teen.getByRole("button", { name: tr(lang, "learn.choose.other") })).toBeVisible();
    await teen.getByRole("button", { name: tr(lang, "learn.choose.confirm") }).click();
    await expect(teen.getByText(tr(lang, "learn.lesson.coach")).first()).toBeVisible();
    await reply(teen, lang, lang === "en" ? "I tried it slowly." : "我慢慢试了一下。");
    await reply(teen, lang, lang === "en" ? "It felt calmer." : "感觉平静一些了。");
    await finishWithMood(teen, lang);
    await expect(teen.locator("body")).not.toContainText(NO_SCORE);
    const lessonUrl = teen.url();

    // quick check: below mastery, then a retake that gets it
    await teen.getByRole("button", { name: tr(lang, "learn.test.start") }).click();
    await expect(teen).toHaveURL(/\/teen\/learn\/tests\//);
    await answerTest(teen, lang, 2);
    await expect(teen.getByTestId("test-outcome")).toContainText(tr(lang, "learn.test.outcome.another_look"));
    await expect(teen.locator("body")).not.toContainText(NO_SCORE);
    await mood(teen, lang, 3, "learn.mood.save");
    await teen
      .getByTestId("test-outcome")
      .getByRole("button", { name: tr(lang, "learn.test.again") })
      .click();
    await answerTest(teen, lang, 0);
    await expect(teen.getByTestId("test-outcome")).toContainText(tr(lang, "learn.test.outcome.got_it"));

    // the past lesson reopens with its recap and conversation (D57)
    await teen.goto(lessonUrl);
    await expect(teen.getByTestId("lesson-summary")).toBeVisible();
    await expect(teen.getByText(tr(lang, "learn.lesson.transcript"))).toBeVisible();

    // 2. lesson with the check-in skipped, ended early
    await startLesson(teen, lang);
    await teen.getByRole("button", { name: tr(lang, "learn.checkin.skip") }).click();
    await teen.getByRole("button", { name: tr(lang, "learn.choose.confirm") }).click();
    await teen.getByRole("button", { name: tr(lang, "learn.lesson.end") }).click();
    await finishWithMood(teen, lang);

    // 3. group review: the skill is fixed, so the lesson goes straight to teaching
    await teen.goto("/teen/group-review");
    await expect(teen.getByText(tr(lang, "learn.group.optional"))).toBeVisible();
    await expect(teen.locator("body")).not.toContainText(/overdue|due date|截止日期前/i);
    await teen.getByRole("button", { name: new RegExp(SKILL[lang]) }).click();
    await mood(teen, lang, 3, "learn.next");
    await expect(teen.getByRole("heading", { name: SKILL[lang], level: 1 })).toBeVisible();
    await expect(teen.getByText(tr(lang, "learn.choose.suggested"))).toHaveCount(0);
    await reply(teen, lang, lang === "en" ? "Cold water helps me." : "冷水对我有帮助。");
    await reply(teen, lang, lang === "en" ? "I will try it this week." : "这周我会试试。");
    await finishWithMood(teen, lang);

    // progress: what and when, never a score
    await teen.goto("/teen/learn");
    await expect(teen.getByRole("heading", { name: tr(lang, "learn.progress.title") })).toBeVisible();
    await expect(teen.getByText(tr(lang, "learn.outcome.understood")).first()).toBeVisible();
    await expect(teen.locator("body")).not.toContainText(NO_SCORE);
  });
}

test("caregiver structured lesson and group-review lesson", async () => {
  test.setTimeout(240_000);
  const { carer } = world;
  const lang: Lang = "en";

  // Explore skills -> explain -> practice (second opportunity) -> quick check -> wrap-up
  await carer.goto("/caregiver/learn");
  await carer.getByText(MODULE.en, { exact: true }).click();
  await carer.getByRole("button", { name: SKILL.en, exact: true }).click();
  const explain = carer.getByTestId("cg-explain");
  await expect(explain).toBeVisible();
  await expect(explain.getByText(/AI|Authored/).first()).toBeVisible();
  await explain.getByRole("button", { name: tr(lang, "learn.cg.simpler") }).click();
  await carer.getByRole("button", { name: tr(lang, "learn.cg.toPractice") }).click();
  const practice = carer.getByTestId("cg-practice");
  await practice.locator(".fb-option").first().click();
  await expect(practice.getByText(tr(lang, "learn.cg.whatWorked")).first()).toBeVisible();
  const text = practice.getByLabel(tr(lang, "learn.cg.yourAnswer"));
  await text.fill("I would take one slow breath first.");
  await practice.getByRole("button", { name: tr(lang, "learn.cg.check") }).click();
  await expect(practice.getByText("I would take one slow breath first.")).toBeVisible();
  await carer.getByRole("button", { name: tr(lang, "learn.cg.toQuiz") }).click();
  const quiz = carer.getByTestId("cg-quiz");
  const questions = quiz.locator(".fb-card");
  await expect(questions).toHaveCount(3); // generated on entering the step; count() does not wait
  for (let i = 0; i < 3; i++) {
    await questions.nth(i).locator(".fb-option").first().click();
    await expect(questions.nth(i).getByText(tr(lang, "learn.test.right"))).toBeVisible();
  }
  await carer.getByRole("button", { name: tr(lang, "learn.cg.toWrapUp") }).click();
  await carer.getByLabel(tr(lang, "learn.cg.reflection")).fill("Maybe at dinner time.");
  await carer.getByRole("button", { name: tr(lang, "learn.cg.finish") }).click();
  await expect(carer.getByText(tr(lang, "learn.outcome.understood"))).toBeVisible();
  await expect(carer.locator("body")).not.toContainText(NO_SCORE);

  // Group review: same skill, every step skipped
  await carer.goto("/caregiver/group-review");
  await carer.getByRole("button", { name: new RegExp(SKILL.en) }).click();
  await expect(carer).toHaveURL(/\/caregiver\/learn\/lesson\//);
  await carer.getByRole("button", { name: tr(lang, "learn.cg.toPractice") }).click();
  await carer.getByRole("button", { name: tr(lang, "learn.cg.toQuiz") }).click();
  await carer.getByRole("button", { name: tr(lang, "learn.cg.toWrapUp") }).click();
  await carer.getByRole("button", { name: tr(lang, "learn.cg.skipFinish") }).click();
  await expect(carer.getByText(tr(lang, "learn.outcome.practised"))).toBeVisible();
  await carer.goto("/caregiver/learn");
  await expect(carer.getByRole("heading", { name: tr(lang, "learn.history.title") })).toBeVisible();
  await expect(carer.getByRole("link", { name: new RegExp(SKILL.en) })).toHaveCount(2);
});

test("a rule-violating model sentence never reaches the browser; high risk stops the lesson", async () => {
  test.setTimeout(240_000);
  const { therapist, teenA: teen } = world;
  const lang: Lang = "en"; // teen A already has a profile from the English flow
  await startLesson(teen, lang);
  await teen.getByRole("button", { name: tr(lang, "learn.checkin.pickForMe") }).click();
  await teen.getByRole("button", { name: tr(lang, "learn.choose.confirm") }).click();

  const bodies: string[] = [];
  teen.on("response", (r) => {
    if (r.url().endsWith("/messages")) void r.text().then((t) => bodies.push(t));
  });
  await reply(teen, lang, `Tell me more ${RULE_TRIGGER}`);
  await expect(teen.getByText("Authored content").last()).toBeVisible();
  await expect(teen.locator("body")).not.toContainText("too sensitive");
  await expect.poll(() => bodies.length).toBeGreaterThan(0);
  expect(bodies.join("")).not.toContain("too sensitive");

  // high risk mid-chat: stop, help screen with the stop notice, therapist sees an event
  await teen.getByLabel(tr(lang, "learn.lesson.reply")).fill("I want to die");
  await teen.getByRole("button", { name: tr(lang, "learn.lesson.send") }).click();
  await expect(teen).toHaveURL(/\/teen\/help$/);
  await teen.goto("/teen/learn");
  await expect(teen.getByText(tr(lang, "learn.status.stopped_by_safety"))).toBeVisible();
  await expect(teen.getByTestId("open-lesson")).toHaveCount(0);

  await therapist.goto("/therapist/safety");
  await expect(therapist.getByText(world.teenAAlias).first()).toBeVisible();
});
