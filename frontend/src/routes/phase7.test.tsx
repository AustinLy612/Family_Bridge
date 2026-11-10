/**
 * Phase 7: therapist dashboard (Plan §5.8) and homework for participants (D69).
 * - Home lists this week's homework read-only, with no overdue copy; the diary ticks it.
 * - Schedule sets days per week (D70) and shows each assignee's status.
 * - Learning review shows summaries; the participant's words load only when asked for.
 * - The coverage map has no totals; content review sends the chosen decision (D71).
 * - Metrics are tables of counts. Focus time is reported only while the page is in use.
 */
import { act, fireEvent, renderHook, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";
import { setCsrfToken } from "../api/client";
import type { DiaryEntry } from "../api/diary";
import type { CacheItem, Coverage, LearningPanel, Metrics, Schedule } from "../api/therapist";
import { useFocusTime } from "../app/focusTime";
import i18n from "../i18n";
import { TEEN, THERAPIST, mockApi, renderApp } from "../test/render";

beforeEach(async () => {
  await i18n.changeLanguage("en");
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  setCsrfToken(null);
});

const NEGATIVE = /overdue|you missed|behind|streak|failed|incomplete|\bscore\b|points|late\b/i;
const GROUPS = [{ id: "G1", name: "Demo group", family_count: 1, therapists: ["Dr Lin"], is_demo: true }];
const HW = {
  id: "T1",
  title: "Practise TIPP once",
  details: "Fictional homework",
  skill_ids: ["dt.tipp"],
  due_on: "2026-11-14",
};

describe("participant homework (D69)", () => {
  it("Home lists this week's homework read-only, with done items marked and no negative copy", async () => {
    mockApi({
      "GET /learn/current": { body: { lesson: null } },
      "GET /homework": {
        body: {
          items: [
            { ...HW, done: true },
            { ...HW, id: "T2", title: "Notice one moment", done: false },
          ],
        },
      },
    });
    renderApp("/teen", TEEN);
    const list = await screen.findByRole("list", { name: "This week's homework" });
    expect(within(list).getByText("Practise TIPP once")).toBeInTheDocument();
    expect(within(list).getAllByText("Done")).toHaveLength(1);
    expect(within(list).getByRole("link", { name: /tick homework/i })).toHaveAttribute(
      "href",
      "/teen/diary/new",
    );
    expect(screen.queryByRole("checkbox")).toBeNull(); // ticking happens in the diary only
    expect(document.body.textContent).not.toMatch(NEGATIVE);
  });

  it("the diary card's Homework checklist sends the ticked items", async () => {
    const template = {
      role: "adolescent",
      version: 1,
      title: "Diary card",
      intro: "",
      groups: [
        {
          id: "affect",
          label: "How you feel",
          fields: [
            {
              id: "sad",
              type: "scale",
              label: "Sad",
              hint: null,
              low: null,
              high: null,
              options: [],
              show_if: null,
              urge: false,
            },
          ],
        },
      ],
      skills: [],
      note_max: 1000,
    };
    const saved: DiaryEntry = {
      id: "E1",
      entry_date: "2026-11-09",
      recorded_at: "2026-11-09T10:00:00Z",
      updated_at: "2026-11-09T10:00:00Z",
      template_version: 1,
      values: {},
      note: null,
      revision_no: 1,
      editable: true,
      shares: [],
      homework: [HW],
    };
    const calls = mockApi({
      "GET /diary/template": {
        body: { template, can_share: false, today: "2026-11-09", editable_from: "2026-11-03" },
      },
      "GET /diary/homework?date=2026-11-09": { body: { items: [HW] } },
      "POST /diary/entries": { status: 201, body: { entry: saved, safety: "none" } },
      "GET /diary/entries/E1": { body: { entry: saved } },
    });
    renderApp("/teen/diary/new", TEEN);
    const box = await screen.findByRole("checkbox", { name: /Practise TIPP once/ });
    fireEvent.click(box);
    fireEvent.click(screen.getByRole("button", { name: "Save entry" }));
    await waitFor(() => expect(calls.some((c) => c.key === "POST /diary/entries")).toBe(true));
    expect(calls.find((c) => c.key === "POST /diary/entries")?.body).toMatchObject({ homework: ["T1"] });
  });
});

const SCHEDULE: Schedule = {
  group: { id: "G1", name: "Demo group" },
  diary_days_per_week: 7,
  tasks: [
    {
      id: "T1",
      title: "Practise TIPP once",
      details: null,
      for_roles: ["adolescent", "caregiver"],
      skill_ids: [],
      starts_on: "2026-11-08",
      due_on: "2026-11-14",
      archived: false,
      assignees: [
        { family_id: "F1", family: "Family A", alias: "Maple", role: "adolescent", done: true },
        { family_id: "F1", family: "Family A", alias: "Maple's mum", role: "caregiver", done: false },
      ],
    },
  ],
};

describe("therapist schedule (D69, D70)", () => {
  it("sets days per week and shows who has ticked each item", async () => {
    const calls = mockApi({
      "GET /groups": { body: GROUPS },
      "GET /groups/G1/schedule": { body: SCHEDULE },
      "GET /learn/skills": { body: { modules: [] } },
      "PUT /groups/G1/diary-expectation": { body: { diary_days_per_week: 3 } },
    });
    renderApp("/therapist/schedule", THERAPIST);
    const task = await screen.findByTestId("task");
    const rows = within(task).getAllByRole("row");
    expect(rows[1]).toHaveTextContent("Maple");
    expect(rows[1]).toHaveTextContent("Done");
    expect(rows[2]).toHaveTextContent("Not yet");
    expect(document.body.textContent).not.toMatch(/overdue|late\b/i);
    const days = screen.getByRole("radiogroup", { name: "Days per week" });
    expect(within(days).getByRole("radio", { name: "Daily" })).toHaveAttribute("aria-checked", "true");
    fireEvent.click(within(days).getByRole("radio", { name: "3" }));
    await waitFor(() =>
      expect(calls.find((c) => c.key === "PUT /groups/G1/diary-expectation")?.body).toEqual({
        days_per_week: 3,
      }),
    );
  });
});

const PANELS: LearningPanel[] = [
  {
    user_id: "U1",
    alias: "Maple",
    role: "adolescent",
    mastery: [
      {
        skill: {
          id: "dt.tipp",
          name: "TIPP skills",
          module_id: "distress_tolerance",
          module: "Distress tolerance",
        },
        lessons_completed: 1,
        outcome: "understood",
        practice_categories: {},
        last_practised_at: "2026-11-09T10:00:00Z",
      },
    ],
    lessons: [
      {
        id: "L1",
        kind: "teaching",
        skill: {
          id: "dt.tipp",
          name: "TIPP skills",
          module_id: "distress_tolerance",
          module: "Distress tolerance",
        },
        source: "recommended",
        status: "completed",
        started_at: "2026-11-09T10:00:00Z",
        completed_at: "2026-11-09T10:20:00Z",
        recommendation_reason: "Fits feeling tense before exams.",
        summary: { summary_text: "Practised TIPP.", key_points: ["Cold water helps"] },
        understanding: "good",
        checkin: "answered",
        turns: 4,
        mood_before: 2,
        mood_after: 4,
        tests: [
          { attempt_no: 1, status: "completed", outcome: "got_it", correct: 4, total: 5, mood_after: 4 },
        ],
      },
    ],
  },
];

describe("therapist learning review (D15)", () => {
  it("shows summaries and opens the participant's own words only on request", async () => {
    const calls = mockApi({
      "GET /families/F1/learning": {
        body: { family: { id: "F1", label: "Family A" }, participants: PANELS },
      },
      "GET /families/F1/learning/lessons/L1": {
        body: {
          kind: "teaching",
          checkin: { question: "How was your week?", answer: "Fictional: exams.", skipped: false },
          messages: [{ role: "student", content: "Fictional chat", at: "2026-11-09T10:05:00Z" }],
          mood_notes: [],
        },
      },
      "POST /families/F1/time": { status: 204 },
    });
    renderApp("/therapist/families/F1/learning", THERAPIST);
    const lesson = await screen.findByTestId("learning-lesson");
    expect(lesson).toHaveTextContent("Fits feeling tense before exams.");
    expect(lesson).toHaveTextContent("Practised TIPP.");
    expect(lesson).toHaveTextContent("2 → 4");
    expect(lesson).toHaveTextContent("Attempt 1: 4 of 5 correct (got it)");
    expect(screen.queryByText(/Fictional chat/)).toBeNull();
    expect(calls.some((c) => c.key.startsWith("GET /families/F1/learning/lessons"))).toBe(false);
    expect(lesson).toHaveTextContent("Opening this is recorded in the audit log.");
    fireEvent.click(within(lesson).getByRole("button", { name: "Show their own words" }));
    const detail = await screen.findByTestId("lesson-detail");
    expect(await within(detail).findByText(/Fictional: exams\./)).toBeInTheDocument();
    expect(detail).toHaveTextContent("Fictional chat");
  });
});

const COVERAGE: Coverage = {
  group: { id: "G1", name: "Demo group" },
  modules: [
    {
      id: "distress_tolerance",
      name: "Distress tolerance",
      skills: [
        { id: "dt.tipp", name: "TIPP skills" },
        { id: "dt.accepts", name: "ACCEPTS" },
      ],
    },
  ],
  participants: [
    { user_id: "U1", family_id: "F1", family: "Family A", alias: "Maple", role: "adolescent" },
    { user_id: "U2", family_id: "F1", family: "Family A", alias: "Mum", role: "caregiver" },
  ],
  cells: { "dt.tipp": { U1: { lessons: 2, outcome: "understood" } } },
  group_session_skills: ["dt.accepts"],
};

describe("therapist progress", () => {
  it("shows a coverage map without totals and links each family's learning review", async () => {
    mockApi({ "GET /groups": { body: GROUPS }, "GET /groups/G1/coverage": { body: COVERAGE } });
    renderApp("/therapist/progress", THERAPIST);
    const map = await screen.findByTestId("coverage-map");
    expect(within(map).getByLabelText("2 lessons, Understood")).toBeInTheDocument();
    expect(within(map).getByText("ACCEPTS").closest("th")).toHaveTextContent("Covered in group");
    expect(map.textContent).not.toMatch(/total|rank/i);
    expect(screen.getByRole("link", { name: /Family A/ })).toHaveAttribute(
      "href",
      "/therapist/families/F1/learning",
    );
  });
});

const ITEM: CacheItem = {
  id: "C1",
  function: "explain_skill",
  skill: { id: "dt.tipp", name: "TIPP skills" },
  role: "caregiver",
  language: "en",
  variant: "standard",
  prompt_version: 1,
  kb_version: 1,
  source: "ai_manual",
  review: "unreviewed",
  reviewed_by: null,
  reviewed_at: null,
  hits: 3,
  created_at: "2026-11-09T10:00:00Z",
  output: { summary: "Fictional explanation", source_chunk_ids: ["x"] },
};

describe("content review (D71)", () => {
  it("lists unreviewed items and sends 'needs change'", async () => {
    const calls = mockApi({
      "GET /content/cache?review=unreviewed": {
        body: {
          items: [ITEM],
          total: 1,
          offset: 0,
          page_size: 50,
          counts: { unreviewed: 1, reviewed: 0, needs_change: 0 },
        },
      },
      "POST /content/cache/C1/review": { body: { item: { ...ITEM, review: "needs_change" } } },
    });
    renderApp("/therapist/content", THERAPIST);
    const item = await screen.findByTestId("cache-item");
    expect(item).toHaveTextContent("TIPP skills · Explanation");
    expect(item).toHaveTextContent("Fictional explanation");
    expect(item.textContent).not.toContain("source_chunk_ids");
    fireEvent.click(within(item).getByRole("button", { name: "Needs change" }));
    await waitFor(() =>
      expect(calls.find((c) => c.key === "POST /content/cache/C1/review")?.body).toEqual({
        decision: "needs_change",
      }),
    );
  });
});

const METRICS: Metrics = {
  group: { id: "G1", name: "Demo group" },
  from: "2026-10-13",
  to: "2026-11-09",
  days: 28,
  enrolment: {
    families: 2,
    invitations_issued: 6,
    invitations_redeemed: 5,
    by_role: { adolescent: { members: 2, onboarded: 2 }, caregiver: { members: 3, onboarded: 2 } },
  },
  diary: {
    days_per_week: 7,
    adolescent: {
      participants: 2,
      expected_days: 56,
      days_with_entries: 28,
      entries: 40,
      added_later: 3,
      corrected: 2,
    },
    caregiver: {
      participants: 2,
      expected_days: 56,
      days_with_entries: 14,
      entries: 14,
      added_later: 0,
      corrected: 0,
    },
  },
  homework: { tasks: 2, assigned: 8, done: 5 },
  learning: {
    adolescent: {
      started: 4,
      completed: 3,
      stopped: 1,
      stopped_by_safety: 0,
      by_source: { recommended: 3, chosen: 1 },
      checkin_answered: 3,
      checkin_skipped: 1,
      test_attempts: 3,
      tests_mastered: 2,
      mood_before_mean: 2.5,
      mood_after_mean: 3.5,
    },
    caregiver: {
      started: 2,
      completed: 2,
      stopped: 0,
      by_source: { explore: 2 },
      quiz_answers: 8,
      quiz_correct: 6,
    },
  },
  safety: {
    events: 1,
    by_category: { urge_threshold: 1 },
    acknowledged: 1,
    acknowledged_within_sla: 1,
    open_now: 0,
    sla_hours: 24,
  },
  therapist_time: {
    families: [{ family_id: "F1", family: "Family A", minutes: 12.5 }],
    median_minutes: 12.5,
  },
};

describe("metrics", () => {
  it("shows counts and rates in tables", async () => {
    mockApi({ "GET /groups": { body: GROUPS }, "GET /groups/G1/metrics?days=28": { body: METRICS } });
    renderApp("/therapist/metrics", THERAPIST);
    expect((await screen.findAllByTestId("metrics-table")).length).toBeGreaterThan(5);
    expect(screen.getByRole("row", { name: /Teen: days with an entry/ })).toHaveTextContent("28 / 56 (50%)");
    expect(screen.getByRole("row", { name: /Ticked \/ assigned/ })).toHaveTextContent("5 / 8 (63%)");
    expect(screen.getByRole("row", { name: /Family A/ })).toHaveTextContent("12.5 min");
    expect(screen.getByRole("row", { name: /By category/ })).toHaveTextContent(
      "Diary urge above threshold: 1",
    );
  });
});

describe("therapist focus time", () => {
  it("reports seconds only while the page is visible, focused and in use", async () => {
    vi.useFakeTimers();
    const calls = mockApi({ "POST /families/F1/time": { status: 204 } });
    vi.spyOn(document, "hasFocus").mockReturnValue(true);
    const { unmount } = renderHook(() => useFocusTime("F1"));
    await act(async () => {
      vi.advanceTimersByTime(60_000);
    });
    expect(calls.filter((c) => c.key === "POST /families/F1/time")).toEqual([
      expect.objectContaining({ body: { seconds: 60 } }),
    ]);
    // idle for more than two minutes: nothing more is counted
    await act(async () => {
      vi.advanceTimersByTime(180_000);
    });
    unmount();
    const total = calls
      .filter((c) => c.key === "POST /families/F1/time")
      .reduce((n, c) => n + (c.body as { seconds: number }).seconds, 0);
    expect(total).toBeLessThanOrEqual(120);
  });
});
