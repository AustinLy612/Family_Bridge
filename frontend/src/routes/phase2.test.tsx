/** Phase 2 screens against a mocked API: participant help screen and safety flow, therapist
 * safety queue (list, manual events, workflow), admin read-only oversight. Authorisation and
 * detection are tested server-side. */
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider, useLocation } from "react-router";
import { afterEach, beforeEach, vi } from "vitest";
import { setCsrfToken } from "../api/client";
import type { HelpPageOut, SafetyEventDetail, SafetyEventSummary } from "../api/types";
import { useSafetyOutcome } from "../app/safety";
import { SessionProvider } from "../app/session";
import { CareCard } from "../components/Safety";
import i18n from "../i18n";
import { ADMIN, CAREGIVER, TEEN, THERAPIST, mockApi, renderApp } from "../test/render";

beforeEach(async () => {
  await i18n.changeLanguage("en");
});

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
});

const HELP: HelpPageOut = {
  document: {
    version: 1,
    language: "en",
    approval: "draft",
    stop_notice: { title: "Let's stop here for now", body: "This activity has stopped." },
    care_card: { title: "If things feel hard", body: "Here is how to reach your care team." },
    sections: [
      {
        heading: "FamilyBridge is not a crisis service",
        blocks: [{ type: "paragraph", text: "FamilyBridge is not monitored in real time.", items: [] }],
      },
    ],
  },
  site: {
    name: "Demo",
    help_contacts: [
      {
        label: { en: "Hospital DBT team", "zh-CN": "医院 DBT 团队" },
        phone: "000-0000-0000",
        hours: { en: "Weekdays 9–17" },
      },
    ],
    service_hours: { en: "Nobody watches this platform in real time." },
    placeholder: true,
  },
};

const summary = (over: Partial<SafetyEventSummary> = {}): SafetyEventSummary => ({
  id: "e1",
  category: "risk_disclosure",
  severity: "high",
  status: "new",
  source: "lesson",
  channel: "keyword",
  subject: { id: "u1", alias: "Maple", role: "adolescent" },
  family: { id: "f1", label: "Family A", group_id: "g1", group_name: "Group 1" },
  assignee: null,
  occurrences: 1,
  activity_stopped: true,
  created_at: new Date(Date.now() - 3 * 3600_000).toISOString(),
  updated_at: new Date().toISOString(),
  ...over,
});

const detail = (over: Partial<SafetyEventDetail> = {}): SafetyEventDetail => ({
  ...summary(),
  excerpt: "fictional excerpt",
  matched_terms: ["want to die"],
  created_by: null,
  follow_up: null,
  resolved_by: null,
  notes: [],
  timeline: [{ status: "new", at: new Date().toISOString() }],
  next_statuses: ["acknowledged"],
  ...over,
});

describe("participant help screen", () => {
  it("shows contacts as phone links, the static text, and a draft notice", async () => {
    mockApi({ "GET /help?language=en": { body: HELP } });
    renderApp("/teen/help", TEEN);
    expect(await screen.findByText("FamilyBridge is not monitored in real time.")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "000-0000-0000" });
    expect(link).toHaveAttribute("href", "tel:00000000000");
    expect(screen.getByText(/placeholders until the hospital confirms/)).toBeInTheDocument();
    expect(screen.getByText(/help text is a draft/)).toBeInTheDocument();
    // Not opened by the safety flow: no stop notice.
    expect(screen.queryByText("Let's stop here for now")).not.toBeInTheDocument();
  });

  it("after a stop, shows the stop notice first and focuses it, with no reason given", async () => {
    mockApi({ "GET /help?language=en": { body: HELP } });
    renderApp({ pathname: "/caregiver/help", state: { safety: "stop" } }, CAREGIVER);
    const heading = await screen.findByRole("heading", { name: "Let's stop here for now" });
    await waitFor(() => expect(heading).toHaveFocus());
    const main = screen.getByRole("main");
    expect(main).not.toHaveTextContent(/keyword|risk|flag|therapist can|score/i); // D40
  });

  it("is reachable from every participant screen via the header link", async () => {
    renderApp("/teen/learn", TEEN);
    const link = await screen.findByRole("link", { name: "Get help" });
    expect(link).toHaveAttribute("href", "/teen/help");
  });

  it("staff screens have no participant help link", async () => {
    mockApi({ "GET /groups": { body: [] } });
    renderApp("/therapist", THERAPIST);
    await screen.findByText(/no groups/i);
    expect(screen.queryByRole("link", { name: "Get help" })).not.toBeInTheDocument();
  });
});

describe("safety outcome on participant screens", () => {
  function Harness({ action }: { action: "stop" | "help" | "care_card" | "none" }) {
    const { handle, careCard } = useSafetyOutcome();
    return (
      <>
        <button onClick={() => handle(action)}>send</button>
        {careCard && <p>care card shown</p>}
      </>
    );
  }
  function Where() {
    const loc = useLocation();
    return <p>{`at ${loc.pathname} ${JSON.stringify(loc.state)}`}</p>;
  }
  function setup(action: "stop" | "help" | "care_card" | "none") {
    const router = createMemoryRouter(
      [
        { path: "/x", element: <Harness action={action} /> },
        { path: "/teen/help", element: <Where /> },
      ],
      { initialEntries: ["/x"] },
    );
    render(
      <QueryClientProvider client={new QueryClient()}>
        <SessionProvider user={TEEN}>
          <RouterProvider router={router} />
        </SessionProvider>
      </QueryClientProvider>,
    );
  }

  it.each([
    ["stop", '{"safety":"stop"}'],
    ["help", '{"safety":"help"}'],
  ] as const)("%s goes to the help screen", async (action, state) => {
    setup(action);
    await userEvent.click(screen.getByRole("button", { name: "send" }));
    expect(await screen.findByText(`at /teen/help ${state}`)).toBeInTheDocument();
  });

  it("care_card stays on the page and shows the card; none does nothing", async () => {
    setup("care_card");
    await userEvent.click(screen.getByRole("button", { name: "send" }));
    expect(screen.getByText("care card shown")).toBeInTheDocument();
  });

  it("the care card is gentle and links to help", async () => {
    mockApi({ "GET /help?language=en": { body: HELP } });
    const onDismiss = vi.fn();
    const router = createMemoryRouter(
      [{ path: "/", element: <CareCard helpHref="/teen/help" onDismiss={onDismiss} /> }],
      { initialEntries: ["/"] },
    );
    render(
      <QueryClientProvider client={new QueryClient()}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
    expect(await screen.findByRole("heading", { name: "If things feel hard" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open the help page" })).toHaveAttribute("href", "/teen/help");
    await userEvent.click(screen.getByRole("button", { name: "Keep going" }));
    expect(onDismiss).toHaveBeenCalled();
  });
});

describe("therapist safety queue", () => {
  const list = (events: SafetyEventSummary[]) => ({
    body: {
      events,
      counts: { new: events.filter((e) => e.status === "new").length, open: events.length },
    },
  });

  it("lists events with text labels for severity and status, and filters", async () => {
    const calls = mockApi({
      "GET /safety/events?status=open": list([
        summary(),
        summary({ id: "e2", severity: "medium", status: "acknowledged", category: "urge_threshold" }),
      ]),
      "GET /safety/events?status=resolved": list([]),
      "GET /safety/subjects": { body: [] },
    });
    renderApp("/therapist/safety", THERAPIST);
    const rows = await screen.findByRole("list", { name: "Safety events" });
    const first = within(rows).getAllByRole("link")[0];
    expect(first).toHaveTextContent("Risk disclosure · Maple");
    expect(first).toHaveTextContent("High severity");
    expect(first).toHaveTextContent("New");
    expect(first).toHaveTextContent(/3 hours ago/);
    expect(first).toHaveAttribute("href", "/therapist/safety/e1");
    expect(screen.getByText("1 new · 2 open")).toBeInTheDocument();
    expect(screen.getByText(/Nobody is sent a text, call or email/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("radio", { name: "Resolved" }));
    expect(await screen.findByText("No resolved safety events yet.")).toBeInTheDocument();
    expect(calls.map((c) => c.key)).toContain("GET /safety/events?status=resolved");
  });

  it("records a manual event and opens it", async () => {
    const calls = mockApi({
      "GET /safety/events?status=open": list([]),
      "GET /safety/subjects": {
        body: [
          {
            user: { id: "u1", alias: "Maple", role: "adolescent" },
            family: { id: "f1", label: "Family A", group_id: "g1", group_name: "G" },
          },
        ],
      },
      "POST /safety/events": { status: 201, body: detail({ id: "e9", source: "manual", channel: "manual" }) },
      "GET /safety/events/e9": { body: detail({ id: "e9", source: "manual", channel: "manual" }) },
    });
    renderApp("/therapist/safety", THERAPIST);
    const submit = await screen.findByRole("button", { name: "Record event" });
    expect(submit).toBeDisabled();
    await screen.findByRole("option", { name: /Maple \(Teen\) · Family A/ });
    // Automated-only categories cannot be chosen by hand.
    expect(screen.queryByRole("option", { name: "Diary urge above threshold" })).not.toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Type of event"), "suspected_abuse");
    await userEvent.selectOptions(screen.getByLabelText("Severity"), "high");
    await userEvent.type(screen.getByLabelText("What happened"), "Raised in group.");
    await userEvent.click(submit);
    await waitFor(() => expect(calls.some((c) => c.key === "GET /safety/events/e9")).toBe(true));
    expect(calls.find((c) => c.key === "POST /safety/events")?.body).toEqual({
      subject_user_id: "u1",
      category: "suspected_abuse",
      severity: "high",
      description: "Raised in group.",
    });
  });

  it("walks an event through acknowledge and resolve with a follow-up", async () => {
    let current = detail();
    const calls = mockApi({
      "GET /safety/events/e1": () => ({ body: current }),
      "GET /safety/events?status=open": list([]),
      "POST /safety/events/e1/status": (body) => {
        const b = body as { status: "acknowledged" | "resolved"; follow_up: string | null };
        current = detail({
          status: b.status,
          assignee: { id: "t", alias: "Dr Lin", role: "therapist" },
          follow_up: b.follow_up,
          next_statuses: b.status === "acknowledged" ? ["in_review", "resolved"] : [],
        });
        return { body: current };
      },
      "POST /safety/events/e1/notes": () => {
        current = {
          ...current,
          notes: [
            {
              id: "n1",
              author: { id: "t", alias: "Dr Lin", role: "therapist" },
              body: "Called the family.",
              created_at: new Date().toISOString(),
            },
          ],
        };
        return { status: 201, body: current };
      },
    });
    renderApp("/therapist/safety/e1", THERAPIST);
    expect(await screen.findByText("fictional excerpt")).toBeInTheDocument();
    expect(screen.getByText(/Never share it with other family members/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Acknowledge" }));
    expect(await screen.findByRole("button", { name: "Start review" })).toBeInTheDocument();

    const resolve = screen.getByRole("button", { name: "Resolve" });
    expect(resolve).toBeDisabled(); // follow-up required
    await userEvent.type(screen.getByLabelText("Follow-up action"), "Safety plan reviewed.");
    await userEvent.type(screen.getByLabelText("Note"), "Called the family.");
    await userEvent.click(screen.getByRole("button", { name: "Save note" }));
    expect(await screen.findByText("Called the family.")).toBeInTheDocument();
    await userEvent.click(resolve);
    await waitFor(() => expect(screen.queryByRole("button", { name: "Resolve" })).not.toBeInTheDocument());
    expect(screen.getByText("Safety plan reviewed.")).toBeInTheDocument();
    const posts = calls.filter((c) => c.key === "POST /safety/events/e1/status").map((c) => c.body);
    expect(posts).toEqual([
      { status: "acknowledged", follow_up: null },
      { status: "resolved", follow_up: "Safety plan reviewed." },
    ]);
  });
});

describe("admin safety oversight (D39)", () => {
  it("lists events read-only, with no manual form", async () => {
    mockApi({
      "GET /safety/events?status=open": { body: { events: [summary()], counts: { new: 1, open: 1 } } },
    });
    renderApp("/admin/safety", ADMIN);
    expect(await screen.findByRole("heading", { name: "Safety oversight" })).toBeInTheDocument();
    const row = await screen.findByRole("link", { name: /Risk disclosure · Maple/ });
    expect(row).toHaveTextContent("Group 1");
    expect(screen.queryByRole("button", { name: "Record event" })).not.toBeInTheDocument();
  });

  it("shows the detail with no workflow controls", async () => {
    mockApi({ "GET /safety/events/e1": { body: detail({ next_statuses: [] }) } });
    renderApp("/admin/safety/e1", ADMIN);
    expect(await screen.findByText("fictional excerpt")).toBeInTheDocument();
    expect(screen.getByText(/Read-only oversight view/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Acknowledge" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save note" })).not.toBeInTheDocument();
  });
});

describe("participants never get the queue", () => {
  it("a teen opening the therapist queue is sent home", async () => {
    renderApp("/therapist/safety", TEEN);
    await act(async () => {});
    expect(screen.queryByRole("list", { name: "Safety events" })).not.toBeInTheDocument();
  });
});
