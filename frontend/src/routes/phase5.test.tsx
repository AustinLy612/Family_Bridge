/**
 * Phase 5: individual skill learning screens (Plan §5.5). Checks the D21/D22 flow on the client,
 * the D56 "one open lesson" handling, streamed replies (sentence deltas, replace, safety stop),
 * non-competitive wording (no scores / "fail"), and the caregiver structured lesson.
 */
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";
import { setCsrfToken } from "../api/client";
import type { CaregiverLesson, Lesson, SkillTest } from "../api/learning";
import i18n from "../i18n";
import { CAREGIVER, TEEN, THERAPIST, mockApi, renderApp } from "../test/render";

beforeEach(async () => {
  await i18n.changeLanguage("en");
});

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
});

const NO_SCORE = /\b(score|fail(ed|ure)?|points?|\d\s*\/\s*5)\b/i;

const OPTIONS = {
  hobby_tags: ["sports", "music", "art_craft", "reading", "writing", "games"],
  concern_tags: ["study_pressure", "sleep", "worry", "anger", "focus", "low_mood", "prefer_not_to_say"],
  grades: ["grade_7", "grade_8", "grade_9", "grade_10", "grade_11", "grade_12"],
  genders: ["male", "female", "other", "prefer_not_to_say"],
  max_tags: 5,
  age_min: 10,
  age_max: 19,
};
const PROFILE = {
  gender: null,
  age: 15,
  grade: "grade_9",
  hobby_tags: [],
  concern_tags: [],
  other_hobby_text: null,
  other_concern_text: null,
};

function lesson(over: Partial<Lesson> = {}): Lesson {
  return {
    id: "L1",
    phase: "pre_mood_recording",
    status: "ongoing",
    source: null,
    language: "en",
    started_at: "2026-11-09T08:00:00Z",
    completed_at: null,
    checkin: null,
    recommendation: null,
    skill: null,
    plan: [],
    plan_source: null,
    messages: [],
    summary: null,
    busy: false,
    tests: [],
    ...over,
  };
}

const SKILL = { id: "dt.tipp", name: "TIPP skills", module: "Distress tolerance" };
const ALT = { id: "mf.what_skills", name: "What skills", module: "Mindfulness" };

// --- Learn page and D56 ------------------------------------------------------------------------

describe("adolescent learn page", () => {
  it("asks for the profile before the first lesson", async () => {
    mockApi({
      "GET /learn/profile": { body: { profile: null, options: OPTIONS } },
      "GET /learn/sessions/current": { body: { lesson: null } },
      "GET /learn/progress": { body: { skills: [] } },
      "GET /learn/history": { body: { lessons: [] } },
    });
    renderApp("/teen/learn", TEEN);
    expect(await screen.findByRole("link", { name: "Fill in my profile" })).toHaveAttribute(
      "href",
      "/teen/profile",
    );
  });

  it("offers to continue or close an open lesson, with no penalty", async () => {
    const calls = mockApi({
      "GET /learn/profile": { body: { profile: PROFILE, options: OPTIONS } },
      "GET /learn/sessions/current": { body: { lesson: lesson({ phase: "teaching", skill: SKILL }) } },
      "GET /learn/progress": {
        body: {
          skills: [
            {
              skill: SKILL,
              module_id: "distress_tolerance",
              lessons_completed: 2,
              outcome: "worth_revisiting",
              first_practised_at: "2026-11-01T00:00:00Z",
              last_practised_at: "2026-11-08T00:00:00Z",
            },
          ],
        },
      },
      "GET /learn/history": { body: { lessons: [] } },
      "POST /learn/sessions/L1/stop": {
        body: { lesson: lesson({ status: "user_terminated" }), safety: "none" },
      },
    });
    renderApp("/teen/learn", TEEN);
    const card = await screen.findByTestId("open-lesson");
    expect(within(card).getByText(/TIPP skills/)).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: "Continue" })).toHaveAttribute("href", "/teen/learn/L1");
    expect(within(card).getByText(/no downside/)).toBeInTheDocument();
    expect(await screen.findByText("Worth revisiting")).toBeInTheDocument();
    fireEvent.click(within(card).getByRole("button", { name: "Close it" }));
    await waitFor(() => expect(calls.some((c) => c.key === "POST /learn/sessions/L1/stop")).toBe(true));
    expect(document.body.textContent).not.toMatch(NO_SCORE);
  });
});

// --- lesson flow ---------------------------------------------------------------------------------

describe("adolescent lesson", () => {
  it("records the mood, then offers an optional check-in with Skip and Pick for me (D22)", async () => {
    let current = lesson();
    const calls = mockApi({
      "GET /learn/sessions/L1": () => ({ body: { lesson: current, safety: "none" } }),
      "POST /learn/sessions/L1/mood": () => {
        current = lesson({
          phase: "personal_inquiry",
          checkin: {
            greeting: "Thanks for sharing.",
            question: "Anything from the last few days?",
            source: "ai_manual",
            skipped: null,
          },
        });
        return { body: { lesson: current, safety: "none" } };
      },
      "POST /learn/sessions/L1/checkin": () => {
        current = lesson({
          phase: "skill_selection",
          recommendation: {
            skill: SKILL,
            reason: "A calm first step.",
            alternatives: [ALT],
            is_repeat: false,
            source: "ai_general",
          },
        });
        return { body: { lesson: current, safety: "none" } };
      },
    });
    renderApp("/teen/learn/L1", TEEN);
    const group = await screen.findByRole("radiogroup", { name: /how are you feeling/ });
    expect(within(group).getAllByRole("radio")).toHaveLength(5);
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
    fireEvent.click(screen.getByRole("radio", { name: /Okay/ }));
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText("Thanks for sharing.")).toBeInTheDocument();
    // provenance is shown once, on the lesson steps, not on every coach message (D92)
    expect(screen.queryByText("AI-generated from the manual")).toBeNull();
    expect(screen.getByRole("button", { name: "Share" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Just pick a skill for me" }));
    expect(await screen.findByText("A calm first step.")).toBeInTheDocument();
    expect(calls.find((c) => c.key === "POST /learn/sessions/L1/checkin")?.body).toEqual({ skip: true });
    expect(calls.find((c) => c.key === "POST /learn/sessions/L1/mood")?.body).toEqual({
      value: 3,
      note: null,
    });
    // confirm / alternative / choose another are all offered
    expect(screen.getByRole("button", { name: "Let's do this one" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /What skills/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Choose another skill" })).toBeInTheDocument();
    expect(screen.queryByText("AI · general DBT knowledge")).toBeNull();
  });

  it("streams a reply sentence by sentence and discards it on replace", async () => {
    const teaching = lesson({
      phase: "teaching",
      skill: SKILL,
      messages: [{ seq: 1, role: "coach", content: "Let's begin.", question: "Ready?", source: "ai_manual" }],
    });
    const after = lesson({
      ...teaching,
      messages: [
        ...teaching.messages,
        { seq: 2, role: "student", content: "yes", question: null, source: null },
        { seq: 3, role: "coach", content: "Authored fallback text.", question: null, source: "authored" },
      ],
    });
    let served = teaching;
    const seen: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
        const url = String(input);
        if (url.endsWith("/messages")) {
          served = after;
          const body =
            'event: delta\ndata: {"text": "First sentence."}\n\n' +
            "event: replace\ndata: {}\n\n" +
            'event: final\ndata: {"message": {"seq": 3}, "completed": false}\n\n';
          return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
        }
        seen.push(`${init.method ?? "GET"} ${url}`);
        return new Response(JSON.stringify({ lesson: served, safety: "none" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }),
    );
    renderApp("/teen/learn/L1", TEEN);
    fireEvent.change(await screen.findByLabelText("Your reply"), { target: { value: "yes" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("Authored fallback text.")).toBeInTheDocument();
    expect(screen.queryByText("First sentence.")).not.toBeInTheDocument();
  });

  it("goes to the help screen when the server stops the lesson mid-reply", async () => {
    const teaching = lesson({ phase: "teaching", skill: SKILL, messages: [] });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/messages")) {
          return new Response('event: safety\ndata: {"action": "stop"}\n\n', {
            status: 200,
            headers: { "Content-Type": "text/event-stream" },
          });
        }
        if (url.includes("/help")) {
          return new Response(JSON.stringify({ detail: { code: "unknown" } }), { status: 500 });
        }
        return new Response(JSON.stringify({ lesson: teaching, safety: "none" }), { status: 200 });
      }),
    );
    const { router } = renderApp("/teen/learn/L1", TEEN);
    fireEvent.change(await screen.findByLabelText("Your reply"), { target: { value: "help" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/teen/help"));
    expect(router.state.location.state).toEqual({ safety: "stop" });
  });

  it("shows a finished lesson's recap and transcript without internal codes (D57)", async () => {
    mockApi({
      "GET /learn/sessions/L1": {
        body: {
          lesson: lesson({
            phase: "done",
            status: "completed",
            skill: SKILL,
            messages: [
              { seq: 1, role: "coach", content: "Opening line.", question: null, source: "ai_manual" },
            ],
            summary: {
              summary_text: "Today you practised TIPP.",
              key_points: ["Cool down"],
              recommendations: ["Try it once"],
              source: "ai_manual",
            },
          }),
          safety: "none",
        },
      },
    });
    renderApp("/teen/learn/L1", TEEN);
    expect(await screen.findByText("Today you practised TIPP.")).toBeInTheDocument();
    expect(screen.getByText("Key ideas")).toBeInTheDocument();
    expect(screen.getByText("Conversation from this lesson")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start the quick check" })).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/understanding|good|fair|needs_review/i);
    expect(document.body.textContent).not.toMatch(NO_SCORE);
  });
});

// --- quick check -----------------------------------------------------------------------------------

function skillTest(over: Partial<SkillTest> = {}): SkillTest {
  return {
    id: "T1",
    session_id: "L1",
    attempt_no: 1,
    status: "ready",
    source: "ai_manual",
    outcome: null,
    mood_recorded: false,
    created_at: "2026-11-09T09:00:00Z",
    questions: [1, 2, 3, 4, 5].map((n) => ({
      position: n,
      scenario: `Scene ${n}`,
      question: `Question text ${n}`,
      options: ["A", "B", "C", "D"],
      answer_index: null,
      is_correct: null,
      correct_index: null,
      explanation: null,
    })),
    ...over,
  };
}

describe("quick check", () => {
  it("answers one at a time with an explanation", async () => {
    const answered = skillTest();
    answered.questions = answered.questions.map((q) =>
      q.position === 1
        ? {
            ...q,
            answer_index: 1,
            is_correct: false,
            correct_index: 0,
            explanation: "Because A pauses first.",
          }
        : q,
    );
    const calls = mockApi({
      "GET /learn/tests/T1": { body: { test: skillTest() } },
      "POST /learn/tests/T1/answers": { body: { question: answered.questions[0], test: answered } },
    });
    renderApp("/teen/learn/tests/T1", TEEN);
    expect(await screen.findByText("Question text 1")).toBeInTheDocument();
    expect(screen.queryByText("Question text 2")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "B" }));
    expect(await screen.findByText("Not quite.")).toBeInTheDocument();
    expect(screen.getByText("Because A pauses first.")).toBeInTheDocument();
    expect(calls.find((c) => c.key === "POST /learn/tests/T1/answers")?.body).toEqual({
      position: 1,
      answer_index: 1,
    });
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText("Question text 2")).toBeInTheDocument();
  });

  it("shows the last question's explanation before the outcome", async () => {
    const answer = (q: SkillTest["questions"][number]) => ({
      ...q,
      answer_index: 0,
      is_correct: true,
      correct_index: 0,
      explanation: `Why ${q.position}`,
    });
    const before = skillTest();
    before.questions = before.questions.map((q) => (q.position < 5 ? answer(q) : q));
    const done = skillTest({ status: "completed", outcome: "got_it" });
    done.questions = done.questions.map(answer);
    mockApi({
      "GET /learn/tests/T1": { body: { test: before } },
      "POST /learn/tests/T1/answers": { body: { question: done.questions[4], test: done } },
    });
    renderApp("/teen/learn/tests/T1", TEEN);
    expect(await screen.findByText("Question text 5")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "A" }));
    expect(await screen.findByText("That's it!")).toBeInTheDocument();
    expect(screen.getByText("Why 5")).toBeInTheDocument();
    expect(screen.queryByTestId("test-outcome")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByTestId("test-outcome")).toBeInTheDocument();
  });

  it("ends with 'worth another look' and a retake — never a score or 'fail'", async () => {
    const done = skillTest({ status: "completed", outcome: "another_look" });
    done.questions = done.questions.map((q, i) => ({
      ...q,
      answer_index: 0,
      is_correct: i < 3,
      correct_index: i < 3 ? 0 : 1,
      explanation: "x",
    }));
    const calls = mockApi({
      "GET /learn/tests/T1": { body: { test: done } },
      "POST /learn/sessions/L1/tests": {
        body: { test: skillTest({ id: "T2", attempt_no: 2, status: "generating", questions: [] }) },
      },
      "GET /learn/tests/T2": {
        body: { test: skillTest({ id: "T2", attempt_no: 2, status: "generating", questions: [] }) },
      },
    });
    const { router } = renderApp("/teen/learn/tests/T1", TEEN);
    const outcome = await screen.findByTestId("test-outcome");
    expect(within(outcome).getByText("Worth another look")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(NO_SCORE);
    expect(screen.getByText("How are you feeling after the quick check?")).toBeInTheDocument();
    fireEvent.click(within(outcome).getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/teen/learn/tests/T2"));
    expect(calls.some((c) => c.key === "POST /learn/sessions/L1/tests")).toBe(true);
    expect(await screen.findByText("Getting the questions ready…")).toBeInTheDocument();
  });
});

// --- profile -----------------------------------------------------------------------------------------

describe("profile questionnaire", () => {
  it("allows at most five concerns, keeps 'prefer not to say' on its own, and saves", async () => {
    const calls = mockApi({
      "GET /learn/profile": { body: { profile: null, options: OPTIONS } },
      "PUT /learn/profile": (body) => ({ body: { profile: body, options: OPTIONS } }),
    });
    renderApp("/teen/profile", TEEN);
    expect(await screen.findByText(/can't see any of this/)).toBeInTheDocument();
    const save = screen.getByRole("button", { name: "Save" });
    expect(save).toBeDisabled(); // grade is required
    fireEvent.change(screen.getByLabelText("Grade"), { target: { value: "grade_9" } });
    for (const name of [
      "Pressure from schoolwork",
      "Sleep troubles",
      "Worrying a lot",
      "Getting angry or overwhelmed easily",
      "Hard to concentrate",
      "Feeling low",
    ]) {
      fireEvent.click(screen.getByRole("button", { name }));
    }
    expect(screen.getByRole("button", { name: "Feeling low" })).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(screen.getByRole("button", { name: "Prefer not to say" }));
    expect(screen.getByRole("button", { name: "Sleep troubles" })).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(save);
    await waitFor(() => expect(calls.some((c) => c.key === "PUT /learn/profile")).toBe(true));
    const body = calls.find((c) => c.key === "PUT /learn/profile")?.body as {
      concern_tags: string[];
      grade: string;
    };
    expect(body.concern_tags).toEqual(["prefer_not_to_say"]);
    expect(body.grade).toBe("grade_9");
  });
});

// --- group review (D24) -------------------------------------------------------------------------------

describe("group review", () => {
  it("lists skills without due dates and starts a fixed-skill lesson", async () => {
    const calls = mockApi({
      "GET /learn/group-review": {
        body: { records: [{ id: "R1", session_date: "2026-11-05", skills: [SKILL] }] },
      },
      "POST /learn/sessions": { status: 409, body: { detail: { code: "lesson.open_exists" } } },
      "GET /learn/sessions/current": { body: { lesson: lesson({ id: "L9", skill: ALT }) } },
    });
    renderApp("/teen/group-review", TEEN);
    expect(await screen.findByText(/entirely optional/)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/due|overdue|deadline (is|on)|complete by/i);
    fireEvent.click(await screen.findByRole("button", { name: /TIPP skills/ }));
    const card = await screen.findByTestId("open-lesson");
    expect(within(card).getByText(/What skills/)).toBeInTheDocument();
    expect(calls.find((c) => c.key === "POST /learn/sessions")?.body).toEqual({
      group_record_id: "R1",
      skill_id: "dt.tipp",
    });
  });

  it("lets a therapist record the skills covered in a session", async () => {
    const calls = mockApi({
      "GET /groups/G1": { body: { id: "G1", name: "Group A", is_demo: true, therapists: [], families: [] } },
      "GET /groups/G1/skill-records": { body: { records: [] } },
      "GET /learn/skills": {
        body: {
          modules: [
            {
              id: "distress_tolerance",
              name: "Distress tolerance",
              skills: [{ id: "dt.tipp", name: "TIPP skills" }],
            },
          ],
        },
      },
      "POST /groups/G1/skill-records": {
        status: 201,
        body: { record: { id: "R1", session_date: "2026-11-05", skills: [SKILL] } },
      },
    });
    renderApp("/therapist/groups/G1", THERAPIST);
    expect(await screen.findByText("Skills covered in group sessions")).toBeInTheDocument();
    const add = screen.getByRole("button", { name: "Add record" });
    expect(add).toBeDisabled();
    fireEvent.click(await screen.findByLabelText("TIPP skills"));
    fireEvent.click(add);
    await waitFor(() => expect(calls.some((c) => c.key === "POST /groups/G1/skill-records")).toBe(true));
    const body = calls.find((c) => c.key === "POST /groups/G1/skill-records")?.body as {
      skill_ids: string[];
    };
    expect(body.skill_ids).toEqual(["dt.tipp"]);
  });
});

// --- caregiver structured lesson ------------------------------------------------------------------------

function cgLesson(over: Partial<CaregiverLesson> = {}): CaregiverLesson {
  return {
    id: "C1",
    kind: "caregiver",
    step: "explain",
    status: "ongoing",
    source: "explore",
    language: "en",
    skill: SKILL,
    variant: "standard",
    explanation: {
      title: "TIPP",
      summary: "TIPP helps the body calm down fast.",
      key_points: ["Temperature", "Intense exercise", "Paced breathing"],
      everyday_example: "After a hard call, splash cool water.",
      check_question: "When might you use this?",
      source: "ai_manual",
      grounding: "manual",
      references: [{ module: "Distress tolerance", handout: "6", title: "TIPP skills" }],
    },
    practice: null,
    quiz: null,
    outcome: null,
    reflection: null,
    started_at: "2026-11-09T08:00:00Z",
    completed_at: null,
    ...over,
  };
}

describe("caregiver structured lesson", () => {
  it("explains with provenance and references, and adapts on request", async () => {
    const calls = mockApi({
      "GET /learn/caregiver/lessons/C1": { body: { lesson: cgLesson(), safety: "none" } },
      "POST /learn/caregiver/lessons/C1/adapt": {
        body: { lesson: cgLesson({ variant: "simpler" }), safety: "none" },
      },
    });
    renderApp("/caregiver/learn/lesson/C1", CAREGIVER);
    const ex = await screen.findByTestId("cg-explain");
    expect(within(ex).getByText("AI-generated from the manual")).toBeInTheDocument();
    expect(within(ex).getByText("Based on:")).toBeInTheDocument();
    expect(within(ex).getByText(/Distress tolerance · 6\. TIPP skills/)).toBeInTheDocument();
    fireEvent.click(within(ex).getByRole("button", { name: "Explain more simply" }));
    await waitFor(() =>
      expect(calls.find((c) => c.key === "POST /learn/caregiver/lessons/C1/adapt")?.body).toEqual({
        variant: "simpler",
      }),
    );
    expect(screen.getByRole("button", { name: "Next: practise (optional)" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pause" })).toBeNull(); // Pause is in the joint room only (D92)
  });

  it("wrap-up reflection is optional and private", async () => {
    const calls = mockApi({
      "GET /learn/caregiver/lessons/C1": { body: { lesson: cgLesson({ step: "wrap_up" }), safety: "none" } },
      "POST /learn/caregiver/lessons/C1/finish": {
        body: {
          lesson: cgLesson({ step: "done", status: "completed", outcome: "practised" }),
          safety: "none",
        },
      },
    });
    renderApp("/caregiver/learn/lesson/C1", CAREGIVER);
    const form = await screen.findByTestId("cg-wrapup");
    expect(within(form).getByText(/optional, private/)).toBeInTheDocument();
    fireEvent.click(within(form).getByRole("button", { name: "Skip and finish" }));
    await waitFor(() =>
      expect(calls.find((c) => c.key === "POST /learn/caregiver/lessons/C1/finish")?.body).toEqual({
        reflection: null,
      }),
    );
    expect(await screen.findByText("Practised")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(NO_SCORE);
  });
});
