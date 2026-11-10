/**
 * Phase 8: joint sessions (Plan §5.9).
 * - Invitations are neutral: two equal buttons, no reason asked; a decline sends only the answer.
 * - The room renders server state only; a private choice shows the "can't see yet" note and
 *   nothing of the partner's; "I need to stop" sends `stop` and the server's help action opens Help.
 * - The therapist board schedules, shows declines and offers resume/end on a safety pause.
 * - The episode registry offers approve/retire only to content approvers.
 */
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";
import { setCsrfToken } from "../api/client";
import type { BoardSession, EpisodeCard, GroupJoint, MySession, RoomView, StepView } from "../api/joint";
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

const NEGATIVE = /streak|\bscore\b|points|leaderboard|badge|overdue|failed|why not/i;

const EP: EpisodeCard = {
  id: "demo-stub-episode",
  version: 1,
  title: { en: "Placeholder walk", "zh-CN": "占位散步" },
  objective: { en: "Notice and ask", "zh-CN": "留意并询问" },
  behavioral_criterion: { en: "x", "zh-CN": "x" },
  estimated_minutes: 12,
  skill_ids: [],
  world: "w1",
  level: 1,
  modes: ["joint", "solo"],
};

const INVITE: MySession = {
  id: "S1",
  mode: "joint",
  episode: EP,
  opens_at: "2026-11-09T08:00:00Z",
  closes_at: "2026-11-16T08:00:00Z",
  status: "invited",
  can_respond: true,
  can_join: false,
};

describe("joint invitations", () => {
  it("shows the activity, duration and 'you can stop', with two equal answers and no reason field", async () => {
    const calls = mockApi({
      "GET /joint/sessions": { body: { sessions: [INVITE] } },
      "POST /joint/sessions/S1/respond": { body: { ...INVITE, status: "you_declined", can_respond: false } },
    });
    renderApp("/teen/joint", TEEN);
    const card = await screen.findByTestId("joint-invitation");
    expect(card).toHaveTextContent("Placeholder walk");
    expect(card).toHaveTextContent("Notice and ask");
    expect(card).toHaveTextContent("12 minutes");
    expect(card).toHaveTextContent(/stop at any time/);
    expect(within(card).queryByRole("textbox")).toBeNull();
    expect(document.body.textContent).not.toMatch(NEGATIVE);
    fireEvent.click(within(card).getByRole("button", { name: "Not this time" }));
    await waitFor(() =>
      expect(calls.find((c) => c.key === "POST /joint/sessions/S1/respond")?.body).toEqual({
        response: "declined",
      }),
    );
  });

  it("offers Join once the session is ready, and lists past sessions without reasons", async () => {
    mockApi({
      "GET /joint/sessions": {
        body: {
          sessions: [
            { ...INVITE, status: "ready", can_respond: false, can_join: true },
            { ...INVITE, id: "S0", status: "wont_run", can_respond: false },
          ],
        },
      },
    });
    renderApp("/teen/joint", TEEN);
    const join = await screen.findByRole("link", { name: "Join" });
    expect(join).toHaveAttribute("href", "/teen/joint/S1");
    expect(screen.getByText(/won't run this time/)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/declined/i);
  });
});

// --- room, with a fake WebSocket -----------------------------------------------------------

class FakeSocket {
  static OPEN = 1;
  static last: FakeSocket | null = null;
  readyState = 0;
  sent: Record<string, unknown>[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: ((ev: { code: number }) => void) | null = null;
  constructor(public url: string) {
    FakeSocket.last = this;
    setTimeout(() => {
      this.readyState = 1;
      this.onopen?.();
    }, 0);
  }
  send(data: string) {
    this.sent.push(JSON.parse(data) as Record<string, unknown>);
  }
  close() {
    this.readyState = 3;
  }
  push(msg: unknown) {
    this.onmessage?.({ data: JSON.stringify(msg) });
  }
}

const CHOICE: StepView = {
  id: "s3",
  type: "private_choice",
  title: { en: "Your pick", "zh-CN": "你的选择" },
  text: { en: "Pick one quietly.", "zh-CN": "悄悄选一个。" },
  skippable: false,
  requires: "both",
  hints: [],
  hints_left: 0,
  my_act: null,
  partner_acted: true,
  phase: "input",
  prompt: null,
  options: [
    { id: "a-apple", text: { en: "An apple", "zh-CN": "苹果" } },
    { id: "a-book", text: { en: "A book", "zh-CN": "书" } },
  ],
  my_choice: null,
};

const VIEW: RoomView = {
  phase: "running",
  pause: null,
  me: "adolescent",
  solo: false,
  ready: { me: true, partner: true },
  partner_present: true,
  step_index: 2,
  step_count: 8,
  step: CHOICE,
  end_reason: null,
};

async function openRoom() {
  vi.stubGlobal("WebSocket", FakeSocket);
  mockApi({
    "GET /joint/sessions/S1": { body: { ...INVITE, status: "active", can_respond: false, can_join: true } },
    "GET /help?language=en": { body: { sections: [], contacts: [] } },
  });
  renderApp("/teen/joint/S1", TEEN);
  await waitFor(() => expect(FakeSocket.last?.readyState).toBe(1));
  const sock = FakeSocket.last!;
  act(() => sock.push({ type: "state", seq: 5, state: VIEW }));
  return sock;
}

describe("joint room", () => {
  it("joins, shows a private choice without the partner's pick, and sends the chosen option", async () => {
    const sock = await openRoom();
    expect(sock.sent[0]).toMatchObject({ type: "join" });
    const step = await screen.findByTestId("joint-step");
    expect(step).toHaveAttribute("data-step", "s3");
    expect(step).toHaveTextContent("can't see your choice yet");
    expect(step).toHaveTextContent("Your family member has chosen.");
    expect(screen.queryByTestId("joint-reveal")).toBeNull();
    expect(screen.getByTestId("partner-presence")).toHaveTextContent("is here");
    fireEvent.click(within(step).getByRole("radio", { name: "A book" }));
    fireEvent.click(within(step).getByRole("button", { name: "Choose" }));
    await waitFor(() => expect(sock.sent.some((m) => m.type === "submit")).toBe(true));
    expect(sock.sent.find((m) => m.type === "submit")).toMatchObject({ step_id: "s3", value: "a-book" });
    expect(document.body.textContent).not.toMatch(NEGATIVE);
  });

  it("after the reveal, labels the two answers 'You' and 'Your family member'", async () => {
    const sock = await openRoom();
    act(() =>
      sock.push({
        type: "state",
        seq: 6,
        state: {
          ...VIEW,
          step: {
            ...CHOICE,
            phase: "review",
            my_act: null,
            revealed: {
              adolescent: { text: { en: "A book", "zh-CN": "书" } },
              caregiver: { text: { en: "An apple", "zh-CN": "苹果" } },
            },
          },
        },
      }),
    );
    const reveal = await screen.findByTestId("joint-reveal");
    expect(reveal).toHaveTextContent(/You\s*A book/);
    expect(reveal).toHaveTextContent(/Your family member\s*An apple/);
  });

  it("ignores stale state, and shows a neutral hold when the room is safety-paused", async () => {
    const sock = await openRoom();
    act(() => sock.push({ type: "state", seq: 4, state: { ...VIEW, phase: "ended" } }));
    expect(screen.getByTestId("joint-step")).toBeInTheDocument();
    act(() => sock.push({ type: "state", seq: 7, state: { ...VIEW, phase: "paused", pause: "hold" } }));
    const paused = await screen.findByTestId("room-paused");
    expect(paused).toHaveTextContent("paused for now");
    expect(within(paused).queryByRole("button", { name: "Carry on" })).toBeNull();
    expect(paused.textContent).not.toMatch(/safety|risk|crisis/i);
  });

  it("'I need to stop' sends stop, and the server's help action opens Help", async () => {
    const sock = await openRoom();
    fireEvent.click(screen.getByRole("button", { name: "I need to stop" }));
    await waitFor(() => expect(sock.sent.some((m) => m.type === "stop")).toBe(true));
    const id = sock.sent.find((m) => m.type === "stop")?.id;
    act(() => {
      sock.push({ type: "ack", id });
      sock.push({ type: "safety", action: "help" });
    });
    await waitFor(() => expect(screen.queryByTestId("joint-room")).toBeNull());
  });
});

// --- therapist ----------------------------------------------------------------------------

const GROUPS = [{ id: "G1", name: "Demo group", family_count: 1, therapists: ["Dr Lin"], is_demo: true }];

const SESSION: BoardSession = {
  id: "S1",
  family_id: "F1",
  mode: "joint",
  episode: EP,
  opens_at: INVITE.opens_at,
  closes_at: INVITE.closes_at,
  status: "active",
  time_passed: false,
  adolescent: { alias: "Teen A", response: "accepted", present: true },
  caregiver: { alias: "Carer A", response: "accepted", present: false },
  board: {
    phase: "paused_safety",
    pause_by: "safety",
    ready: { adolescent: true, caregiver: true },
    step_index: 2,
    step_count: 8,
    step_id: "s3",
    step_type: "private_choice",
    acted: { adolescent: true, caregiver: false },
    end_reason: null,
  },
};

const GROUP: GroupJoint = {
  families: [
    {
      id: "F1",
      label: "Family A",
      is_demo: true,
      pairs: [{ caregiver_id: "C1", caregiver_alias: "Carer A", adolescent_alias: "Teen A", suitable: true }],
    },
  ],
  episodes: [{ ...EP, status: "demo", assignable_families: ["F1"] }],
  catalog: [
    {
      id: "w1",
      name: { en: "Lantern Forest", "zh-CN": "灯笼森林" },
      levels: [
        { level: 2, focus: { en: "Validation", "zh-CN": "认可" }, skill_ids: [], target_minutes: [15, 20] },
      ],
    },
  ],
  sessions: [
    SESSION,
    {
      ...SESSION,
      id: "S2",
      status: "declined",
      board: null,
      adolescent: { alias: "Teen A", response: "declined", present: false },
    },
  ],
};

describe("therapist joint board", () => {
  it("schedules the chosen pair and episode, shows declines, and offers resume/end on a safety pause", async () => {
    const calls = mockApi({
      "GET /groups": { body: GROUPS },
      "GET /groups/G1/joint": { body: GROUP },
      "POST /groups/G1/joint-sessions": { status: 201, body: { id: "S3" } },
      "POST /joint-sessions/S1/control": { body: { board: null } },
    });
    renderApp("/therapist/joint", THERAPIST);
    const rows = await screen.findAllByTestId("joint-session-row");
    const live = rows[0]!;
    expect(live).toHaveTextContent("Safety pause");
    expect(live).toHaveTextContent("needs you to resume or end");
    expect(live).toHaveTextContent("Step 3 of 8");
    expect(within(live).queryByRole("button", { name: "Pause" })).toBeNull();
    expect(rows[1]).toHaveTextContent("Declined");
    expect(screen.getByTestId("joint-catalog")).toHaveTextContent("Lantern Forest, part 2");

    fireEvent.click(within(live).getByRole("button", { name: "Resume" }));
    await waitFor(() =>
      expect(calls.find((c) => c.key === "POST /joint-sessions/S1/control")?.body).toEqual({
        action: "resume",
      }),
    );

    fireEvent.click(screen.getByRole("button", { name: "Send invitation" }));
    await waitFor(() => expect(calls.some((c) => c.key === "POST /groups/G1/joint-sessions")).toBe(true));
    expect(calls.find((c) => c.key === "POST /groups/G1/joint-sessions")?.body).toMatchObject({
      family_id: "F1",
      caregiver_id: "C1",
      episode_id: "demo-stub-episode",
      episode_version: 1,
    });
    expect(await screen.findByText("Invitation sent.")).toBeInTheDocument();
  });
});

describe("episode registry", () => {
  const CACHE = {
    "GET /content/cache?review=unreviewed": {
      body: {
        items: [],
        total: 0,
        offset: 0,
        page_size: 50,
        counts: { unreviewed: 0, reviewed: 0, needs_change: 0 },
      },
    },
  };
  const ROWS = [
    { ...EP, status: "demo", file_status: "demo" },
    { ...EP, id: "lantern", status: "draft", file_status: "draft" },
  ];

  it("lets a content approver approve a draft but never a demo version", async () => {
    const calls = mockApi({
      ...CACHE,
      "GET /episodes": { body: { can_approve: true, episodes: ROWS } },
      "POST /episodes/lantern/versions/1/decision": { body: { ...ROWS[1], status: "approved" } },
    });
    renderApp("/therapist/content", THERAPIST);
    const reg = await screen.findByTestId("episode-registry");
    const items = await within(reg).findAllByRole("listitem");
    expect(within(items[0]!).queryByRole("button")).toBeNull();
    fireEvent.click(within(items[1]!).getByRole("button", { name: "Approve" }));
    await waitFor(() =>
      expect(calls.find((c) => c.key === "POST /episodes/lantern/versions/1/decision")?.body).toEqual({
        status: "approved",
      }),
    );
  });

  it("shows no decision buttons to other therapists", async () => {
    mockApi({ ...CACHE, "GET /episodes": { body: { can_approve: false, episodes: ROWS } } });
    renderApp("/therapist/content", THERAPIST);
    const reg = await screen.findByTestId("episode-registry");
    await within(reg).findAllByRole("listitem");
    expect(reg).toHaveTextContent("Only content approvers");
    expect(within(reg).queryByRole("button")).toBeNull();
  });
});
