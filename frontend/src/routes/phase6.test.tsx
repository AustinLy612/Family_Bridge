/**
 * Phase 6: Diary Cards (Plan §5.6). Missed days get no negative copy; follow-up items appear
 * only after "Yes"; saving with a high urge opens Help; sharing is choose → preview → share and
 * can be stopped; the therapist review keeps each person's card separate.
 */
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";
import { setCsrfToken } from "../api/client";
import type { DiaryEntry, DiaryTemplate, FamilyReview } from "../api/diary";
import i18n from "../i18n";
import { CAREGIVER, TEEN, THERAPIST, mockApi, renderApp } from "../test/render";

beforeEach(async () => {
  await i18n.changeLanguage("en");
});

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
});

const NEGATIVE = /overdue|you missed|behind|streak|failed|incomplete|\bscore\b|points/i;

const scale = (id: string, label: string, extra: Partial<DiaryTemplate["groups"][0]["fields"][0]> = {}) => ({
  id,
  type: "scale" as const,
  label,
  hint: null,
  low: "Not at all",
  high: "Very much",
  options: [],
  show_if: null,
  urge: false,
  ...extra,
});

const TEMPLATE: DiaryTemplate = {
  role: "adolescent",
  version: 1,
  title: "Diary card",
  intro: "A quick note of how you feel right now.",
  groups: [
    { id: "affect", label: "How you feel right now", fields: [scale("sad", "Sad")] },
    {
      id: "urges",
      label: "Urges",
      fields: [scale("self_harm_urge", "Urge to harm yourself", { urge: true })],
    },
    {
      id: "skills",
      label: "Skills",
      fields: [
        {
          id: "skill_used",
          type: "boolean",
          label: "Have you used a DBT skill since your last entry?",
          hint: null,
          low: null,
          high: null,
          options: [],
          show_if: null,
          urge: false,
        },
        {
          id: "skills_used",
          type: "skills",
          label: "Which skills?",
          hint: null,
          low: null,
          high: null,
          options: [],
          show_if: "skill_used",
          urge: false,
        },
      ],
    },
    {
      id: "note",
      label: "Note",
      fields: [
        {
          id: "note",
          type: "note",
          label: "Anything else you want to note (optional)",
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
  skills: [
    {
      id: "distress_tolerance",
      name: "Distress tolerance",
      skills: [{ id: "dt.tipp", name: "TIPP skills" }],
    },
  ],
  note_max: 1000,
};

const WINDOW = { today: "2026-11-09", editable_from: "2026-11-03" };

function entry(over: Partial<DiaryEntry> = {}): DiaryEntry {
  return {
    id: "E1",
    entry_date: "2026-11-09",
    recorded_at: "2026-11-09T10:00:00Z",
    updated_at: "2026-11-09T10:00:00Z",
    template_version: 1,
    values: { sad: 6, skill_used: true, skills_used: ["dt.tipp"] },
    note: "A fictional note",
    revision_no: 1,
    editable: true,
    shares: [],
    homework: [],
    ...over,
  };
}

describe("diary home", () => {
  it("says missed entries are okay, shows who can see it, and lists entries", async () => {
    mockApi({
      "GET /diary/template": { body: { template: TEMPLATE, can_share: true, ...WINDOW } },
      "GET /diary/entries?days=30": {
        body: {
          entries: [
            entry({
              shares: [
                {
                  id: "S1",
                  recipient: "Mum",
                  fields: ["sad"],
                  created_at: "2026-11-09T11:00:00Z",
                  revoked_at: null,
                },
              ],
            }),
          ],
          ...WINDOW,
        },
      },
      "GET /diary/shared-with-me": { body: { items: [] } },
    });
    renderApp("/teen/diary", TEEN);
    expect(await screen.findByText("Missed entries are okay — add one when you can.")).toBeInTheDocument();
    expect(screen.getByRole("status", { name: "Who can see this?" })).toHaveTextContent(
      "Your therapist can see",
    );
    const row = await screen.findByRole("link", { name: /Entry for/ });
    expect(row).toHaveAttribute("href", "/teen/diary/E1");
    expect(row).toHaveTextContent("Shared with Mum");
    expect(screen.getByRole("link", { name: "New entry" })).toHaveAttribute("href", "/teen/diary/new");
    expect(document.body.textContent).not.toMatch(NEGATIVE);
  });

  it("an empty diary has no negative copy", async () => {
    mockApi({
      "GET /diary/template": { body: { template: TEMPLATE, can_share: true, ...WINDOW } },
      "GET /diary/entries?days=30": { body: { entries: [], ...WINDOW } },
      "GET /diary/shared-with-me": { body: { items: [] } },
    });
    renderApp("/teen/diary", TEEN);
    expect(await screen.findByText("No entries in the last 30 days.")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(NEGATIVE);
  });

  it("caregivers see items shared with them, attributed and dated", async () => {
    mockApi({
      "GET /diary/template": {
        body: { template: { ...TEMPLATE, role: "caregiver" }, can_share: false, ...WINDOW },
      },
      "GET /diary/entries?days=30": { body: { entries: [], ...WINDOW } },
      "GET /diary/shared-with-me": {
        body: {
          items: [
            {
              id: "S1",
              from: "Sky",
              entry_date: "2026-11-08",
              shared_at: "2026-11-09T09:00:00Z",
              items: [
                { field_id: "sad", label: "Sad", type: "scale", value: 6, display: null },
                {
                  field_id: "skills_used",
                  label: "Which skills?",
                  type: "skills",
                  value: ["dt.tipp"],
                  display: "TIPP skills",
                },
              ],
            },
          ],
        },
      },
    });
    renderApp("/caregiver/diary", CAREGIVER);
    const card = await screen.findByTestId("shared-item");
    expect(within(card).getByRole("heading")).toHaveTextContent(/From Sky/);
    expect(card).toHaveTextContent("6 (1–10)");
    expect(card).toHaveTextContent("TIPP skills");
  });
});

describe("diary entry", () => {
  it("shows follow-up items only after Yes, and posts only what is shown", async () => {
    const calls = mockApi({
      "GET /diary/template": { body: { template: TEMPLATE, can_share: true, ...WINDOW } },
      "POST /diary/entries": (body) => ({
        status: 201,
        body: { entry: entry({ id: "E9", ...(body as object) }), safety: "none" },
      }),
      "GET /diary/entries/E9": { body: { entry: entry({ id: "E9" }) } },
      "GET /diary/share-recipients": { body: { recipients: [] } },
    });
    renderApp("/teen/diary/new", TEEN);
    const sad = await screen.findByRole("radiogroup", { name: "Sad" });
    fireEvent.click(within(sad).getByRole("radio", { name: "6" }));
    expect(screen.queryByText("Which skills?")).toBeNull();
    const used = screen.getByRole("radiogroup", { name: /Have you used a DBT skill/ });
    fireEvent.click(within(used).getByRole("radio", { name: "Yes" }));
    fireEvent.click(await screen.findByRole("checkbox", { name: "TIPP skills" }));
    // change of mind: the follow-up disappears and is not sent
    fireEvent.click(within(used).getByRole("radio", { name: "No" }));
    expect(screen.queryByRole("checkbox", { name: "TIPP skills" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Save entry" }));
    await waitFor(() => expect(calls.some((c) => c.key === "POST /diary/entries")).toBe(true));
    expect(calls.find((c) => c.key === "POST /diary/entries")?.body).toEqual({
      entry_date: "2026-11-09",
      values: { sad: 6, skill_used: false },
      note: null,
      homework: [],
    });
    expect(await screen.findByText("Saved.")).toBeInTheDocument();
  });

  it("a high urge opens Help after saving", async () => {
    mockApi({
      "GET /diary/template": { body: { template: TEMPLATE, can_share: true, ...WINDOW } },
      "POST /diary/entries": { status: 201, body: { entry: entry(), safety: "help" } },
      "GET /help?language=en": { body: { help: null, site: null } },
      "GET /site/help": { body: { contacts: [], service_hours: {} } },
    });
    const { router } = renderApp("/teen/diary/new", TEEN);
    const urge = await screen.findByRole("radiogroup", { name: "Urge to harm yourself" });
    fireEvent.click(within(urge).getByRole("radio", { name: "8" }));
    fireEvent.click(screen.getByRole("button", { name: "Save entry" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/teen/help"));
  });

  it("older entries are read-only", async () => {
    mockApi({
      "GET /diary/template": { body: { template: TEMPLATE, can_share: false, ...WINDOW } },
      "GET /diary/entries/E1": { body: { entry: entry({ editable: false, entry_date: "2026-10-30" }) } },
    });
    renderApp("/caregiver/diary/E1", CAREGIVER);
    expect(
      await screen.findByText("Entries older than 7 days can be read but not changed."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save entry" })).toBeNull();
    expect(screen.getByText("A fictional note")).toBeInTheDocument();
  });
});

describe("sharing", () => {
  it("choose, preview exactly what will be shared, share, then stop sharing", async () => {
    const shared = {
      id: "S1",
      recipient: "Mum",
      fields: ["sad", "note"],
      created_at: "2026-11-09T11:00:00Z",
      revoked_at: null,
    };
    let current = entry();
    const calls = mockApi({
      "GET /diary/template": { body: { template: TEMPLATE, can_share: true, ...WINDOW } },
      "GET /diary/entries/E1": () => ({ body: { entry: current } }),
      "GET /diary/share-recipients": { body: { recipients: [{ id: "M1", alias: "Mum" }] } },
      "POST /diary/entries/E1/shares": () => {
        current = entry({ shares: [shared] });
        return { status: 201, body: { share: shared } };
      },
      "DELETE /diary/shares/S1": () => {
        current = entry({ shares: [{ ...shared, revoked_at: "2026-11-09T12:00:00Z" }] });
        return { body: { share: current.shares[0] } };
      },
    });
    renderApp("/teen/diary/E1", TEEN);
    const panel = await screen.findByTestId("share-panel");
    const mum = await within(panel).findByRole("radio", { name: "Mum" });
    const preview = within(panel).getByRole("button", { name: "Preview" });
    expect(preview).toBeDisabled();
    fireEvent.click(mum);
    fireEvent.click(within(panel).getByRole("checkbox", { name: "Sad" }));
    fireEvent.click(
      within(panel).getByRole("checkbox", { name: "Anything else you want to note (optional)" }),
    );
    fireEvent.click(preview);
    const box = within(panel).getByTestId("share-preview");
    expect(box).toHaveTextContent("Mum will see:");
    expect(box).toHaveTextContent("6 (1–10)");
    expect(box).toHaveTextContent("A fictional note");
    expect(box).not.toHaveTextContent("TIPP skills"); // not chosen
    fireEvent.click(within(panel).getByRole("button", { name: "Share" }));
    await waitFor(() => expect(calls.some((c) => c.key === "POST /diary/entries/E1/shares")).toBe(true));
    expect(calls.find((c) => c.key === "POST /diary/entries/E1/shares")?.body).toEqual({
      recipient: "M1",
      fields: ["sad", "note"],
    });
    fireEvent.click(await within(panel).findByRole("button", { name: "Stop sharing" }));
    await waitFor(() => expect(calls.some((c) => c.key === "DELETE /diary/shares/S1")).toBe(true));
    expect(await within(panel).findByText(/Stopped sharing with Mum/)).toBeInTheDocument();
  });
});

describe("therapist diary review", () => {
  it("shows each person's card separately with trends and a neutral calendar", async () => {
    const review: FamilyReview = {
      from: "2026-11-03",
      to: "2026-11-09",
      days: 7,
      days_per_week: 7,
      participants: [
        {
          user_id: "U1",
          alias: "Sky",
          role: "adolescent",
          series: [
            {
              field_id: "sad",
              label: "Sad",
              urge: false,
              points: [{ date: "2026-11-08", at: "2026-11-08T10:00:00Z", value: 6 }],
            },
            { field_id: "self_harm_urge", label: "Urge to harm yourself", urge: true, points: [] },
          ],
          skill_use: {
            entries_with_skill: 1,
            skills: [{ skill_id: "dt.tipp", name: "TIPP skills", count: 1 }],
          },
          completion: { days_with_entries: 1, days: 7, entries: 1, days_per_week: 7, expected_days: 7 },
          entries: [
            {
              ...entry({ entry_date: "2026-11-08" }),
              added_later: true,
              items: [{ field_id: "sad", label: "Sad", type: "scale", value: 6, display: null }],
              shares: [],
              homework: [],
            },
          ],
        },
        {
          user_id: "U2",
          alias: "Mum",
          role: "caregiver",
          series: [{ field_id: "sad", label: "Sad", urge: false, points: [] }],
          skill_use: { entries_with_skill: 0, skills: [] },
          completion: { days_with_entries: 0, days: 7, entries: 0, days_per_week: 7, expected_days: 7 },
          entries: [],
        },
      ],
    };
    mockApi({ "GET /families/F1/diary?days=30": { body: review } });
    renderApp("/therapist/families/F1/diary", THERAPIST);
    const teen = await screen.findByTestId("diary-panel-adolescent");
    const carer = screen.getByTestId("diary-panel-caregiver");
    expect(within(teen).getByRole("img", { name: /Feelings and distress/ })).toBeInTheDocument();
    expect(within(teen).getByText("TIPP skills: 1")).toBeInTheDocument();
    expect(within(teen).getByText("Added later")).toBeInTheDocument();
    expect(within(teen).getAllByTestId("review-entry")).toHaveLength(1);
    expect(within(carer).queryAllByTestId("review-entry")).toHaveLength(0);
    expect(within(carer).getByText("No entries in this period.")).toBeInTheDocument();
    expect(within(carer).queryByRole("img", { name: /Urges/ })).toBeNull();
  });
});
