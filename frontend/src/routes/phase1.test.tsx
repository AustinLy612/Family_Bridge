/** Phase 1 screens against a mocked API: sign-in, redemption, onboarding, visibility,
 * settings, therapist invitations (code shown once). Authorisation itself is tested server-side. */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, vi } from "vitest";
import { ApiError, api, setCsrfToken } from "../api/client";
import type { OnboardingOut, UserOut } from "../api/types";
import { CAREGIVER, mockApi, renderApp } from "../test/render";

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
});

const user = (over: Partial<UserOut>): UserOut => ({
  id: "u1",
  pseudonym: "P-AAAA1111",
  username: "maple",
  role: "adolescent",
  display_alias: "Maple",
  language: "en",
  a11y_prefs: {},
  onboarded: true,
  is_demo: true,
  ...over,
});
const signedOut = { body: { user: null, csrf_token: null } };
const session = (u: UserOut) => ({ body: { user: u, csrf_token: "csrf-1" } });

const ONBOARDING: OnboardingOut = {
  completed: false,
  document: {
    document_id: "onboarding",
    version: 1,
    language: "en",
    approval: "draft",
    sections: [
      {
        heading: "What FamilyBridge is",
        blocks: [{ type: "paragraph", text: "A practice space.", items: [] }],
      },
    ],
    categories: [
      {
        id: "platform_terms",
        required: true,
        default: true,
        grantee: "platform",
        title: "Using FamilyBridge",
        summary: "s",
      },
      {
        id: "therapist_access",
        required: true,
        default: true,
        grantee: "assigned_therapist",
        title: "Therapist access",
        summary: "s",
      },
      {
        id: "research_export",
        required: false,
        default: true,
        grantee: "research_team",
        title: "Research (optional)",
        summary: "s",
      },
    ],
  },
  help: { name: "Demo", help_contacts: [], service_hours: {}, placeholder: true },
};

describe("API client", () => {
  it("sends the CSRF token on unsafe methods only and exposes error codes", async () => {
    const calls = mockApi({
      "GET /me": { body: {} },
      "POST /auth/logout": { status: 204 },
      "PATCH /me": { status: 403, body: { detail: { code: "auth.csrf_failed" } } },
    });
    setCsrfToken("tok");
    await api("GET", "/me");
    await api("POST", "/auth/logout", {});
    const err: unknown = await api("PATCH", "/me", {}).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(403);
    expect((err as ApiError).code).toBe("auth.csrf_failed");
    expect(calls[0]?.headers["X-CSRF-Token"]).toBeUndefined();
    expect(calls[1]?.headers["X-CSRF-Token"]).toBe("tok");
  });
});

describe("sign in", () => {
  it("signs a therapist in and lands on their groups", async () => {
    const u = user({ role: "therapist", display_alias: "Dr Lin", username: "dr-lin" });
    const calls = mockApi({
      "GET /auth/session": signedOut,
      "POST /auth/login": session(u),
      "GET /groups": { body: [] },
      "PATCH /me": { body: u },
    });
    const ui = userEvent.setup();
    const { router } = renderApp("/", "server");
    await ui.type(await screen.findByLabelText("用户名"), "dr-lin");
    await ui.type(screen.getByLabelText("密码"), "calm-river-stone-42");
    await ui.click(screen.getByRole("button", { name: "登录" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/therapist"));
    expect(calls.find((c) => c.key === "POST /auth/login")?.body).toEqual({
      username: "dr-lin",
      password: "calm-river-stone-42",
    });
  });

  it("shows a translated error and clears the password", async () => {
    mockApi({
      "GET /auth/session": signedOut,
      "POST /auth/login": { status: 401, body: { detail: { code: "auth.invalid_credentials" } } },
    });
    const ui = userEvent.setup();
    renderApp("/", "server");
    await ui.type(await screen.findByLabelText("用户名"), "x-user");
    await ui.type(screen.getByLabelText("密码"), "wrong-password");
    await ui.click(screen.getByRole("button", { name: "登录" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("用户名和密码不匹配。");
    expect(screen.getByLabelText("密码")).toHaveValue("");
  });
});

describe("onboarding cannot be skipped (Plan §5.2)", () => {
  it("redirects a participant who has not onboarded", async () => {
    mockApi({ "GET /onboarding?language=zh-CN": { body: ONBOARDING } });
    const { router } = renderApp("/caregiver/diary", { ...CAREGIVER, onboarded: false });
    await waitFor(() => expect(router.state.location.pathname).toBe("/onboarding"));
  });

  it("required items start unticked, research is visible and ON, declining asks to talk to the therapist", async () => {
    const u = user({ onboarded: false });
    const calls = mockApi({
      "GET /auth/session": session(u),
      "GET /onboarding?language=en": { body: ONBOARDING },
      "POST /onboarding/accept": { body: { ...u, onboarded: true } },
      "PATCH /me": { body: u },
    });
    const ui = userEvent.setup();
    const { router } = renderApp("/", "server");
    await waitFor(() => expect(router.state.location.pathname).toBe("/onboarding"));
    const research = await screen.findByRole("switch", { name: /Research \(optional\)/ });
    expect(research).toBeChecked();
    const terms = screen.getByRole("checkbox", { name: "Using FamilyBridge" });
    const access = screen.getByRole("checkbox", { name: "Therapist access" });
    expect(terms).not.toBeChecked();
    expect(access).not.toBeChecked();

    await ui.click(screen.getByRole("button", { name: "Agree and continue" }));
    expect(screen.getByRole("alert")).toHaveTextContent("talk to your therapist");
    expect(calls.some((c) => c.key === "POST /onboarding/accept")).toBe(false);

    await ui.click(terms);
    await ui.click(access);
    await ui.click(screen.getByRole("button", { name: "Agree and continue" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/teen"));
    expect(calls.find((c) => c.key === "POST /onboarding/accept")?.body).toEqual({
      version: 1,
      language: "en",
      decisions: { platform_terms: true, therapist_access: true, research_export: true },
    });
  });
});

describe("redeem an invitation", () => {
  it("checks the code, then asks for username (not real name), alias, language, password", async () => {
    const u = user({ role: "caregiver", onboarded: false, username: "willow" });
    const calls = mockApi({
      "GET /auth/session": signedOut,
      "POST /auth/codes/inspect": {
        body: { purpose: "invite", role: "caregiver", expires_at: "2026-12-01T00:00:00Z", username: null },
      },
      "POST /auth/redeem": session(u),
      "GET /onboarding?language=en": { body: ONBOARDING },
      "PATCH /me": { body: u },
    });
    const ui = userEvent.setup();
    const { router } = renderApp("/redeem", "server");
    await ui.click(screen.getByRole("radio", { name: "English" }));
    await ui.type(screen.getByLabelText("Code"), "ABCD EFGH JKLM NPQR");
    await ui.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByText("This invitation is for a Caregiver account.")).toBeInTheDocument();
    const username = screen.getByLabelText("Choose a username");
    expect(username).toHaveAccessibleDescription(/don't use your real name/);
    await ui.type(username, "willow");
    await ui.type(screen.getByLabelText("Display name"), "Willow");
    await ui.type(screen.getByLabelText("New password"), "bright-maple-leaf-9");
    await ui.type(screen.getByLabelText("Type the password again"), "bright-maple-leaf-8");
    expect(screen.getByText("The two passwords don't match.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create account" })).toBeDisabled();
    await ui.clear(screen.getByLabelText("Type the password again"));
    await ui.type(screen.getByLabelText("Type the password again"), "bright-maple-leaf-9");
    await ui.click(screen.getByRole("button", { name: "Create account" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/onboarding"));
    expect(calls.find((c) => c.key === "POST /auth/redeem")?.body).toMatchObject({
      username: "willow",
      display_alias: "Willow",
      language: "en",
    });
  });
});

describe("who can see my data", () => {
  it("lists the real viewers from the server", async () => {
    const u = user({});
    mockApi({
      "GET /auth/session": session(u),
      "GET /me/visibility": {
        body: {
          viewers: [
            { kind: "self", alias: null, role: null, sees: ["visibility.sees.everything_own"] },
            {
              kind: "assigned_therapist",
              alias: "Dr Lin",
              role: "therapist",
              sees: ["visibility.sees.diary_cards"],
            },
            {
              kind: "family_member",
              alias: "Maple's mum",
              role: "caregiver",
              sees: ["visibility.sees.only_what_you_share"],
            },
          ],
        },
      },
      "PATCH /me": { body: u },
    });
    renderApp("/teen/privacy", "server");
    const list = await screen.findByRole("list", { name: "People and services that can see your data" });
    expect(within(list).getByText("Dr Lin (Therapist)")).toBeInTheDocument();
    expect(within(list).getByText("Only what you choose to share")).toBeInTheDocument();
  });
});

describe("account settings are saved on the server", () => {
  it("saves accessibility changes to the account", async () => {
    const u = user({});
    const calls = mockApi({
      "GET /auth/session": session(u),
      "GET /me/consent": {
        body: [{ category: "research_export", required: false, granted: true, recorded_at: null }],
      },
      "PATCH /me": (body) => ({ body: { ...u, a11y_prefs: (body as { a11y_prefs: object }).a11y_prefs } }),
    });
    const ui = userEvent.setup();
    renderApp("/teen/settings", "server");
    await ui.click(await screen.findByRole("switch", { name: "High contrast" }));
    await waitFor(
      () =>
        expect(
          calls.some(
            (c) =>
              c.key === "PATCH /me" &&
              (c.body as { a11y_prefs: { highContrast: boolean } }).a11y_prefs.highContrast,
          ),
        ).toBe(true),
      { timeout: 2000 },
    );
    expect(calls.find((c) => c.key === "PATCH /me")?.headers["X-CSRF-Token"]).toBe("csrf-1");
  });
});

describe("therapist invitations", () => {
  it("shows a new code once, then it is gone", async () => {
    const u = user({ role: "therapist", display_alias: "Dr Lin" });
    const family = {
      id: "f1",
      group_id: "g1",
      label: "Family A",
      members: [
        {
          user_id: "a1",
          pseudonym: "P-TEEN0001",
          display_alias: "Maple",
          role: "adolescent",
          relationship_label: null,
          onboarded: true,
          status: "active",
        },
      ],
      pending: [],
      dyads: [],
    };
    const calls = mockApi({
      "GET /auth/session": session(u),
      "GET /families/f1": { body: family },
      "POST /families/f1/invitations": {
        status: 201,
        body: { invitation_id: "i1", code: "K7QM-3F9X-PLR2-8VDA", expires_at: "2026-11-22T00:00:00Z" },
      },
      "PATCH /me": { body: u },
    });
    const ui = userEvent.setup();
    renderApp("/therapist/families/f1", "server");
    // The family already has a teen, so only caregiver invitations are offered.
    const roleSelect = await screen.findByLabelText("Account type");
    expect(within(roleSelect).queryByRole("option", { name: "Teen" })).toBeNull();
    await ui.type(screen.getByLabelText("Relationship (optional)"), "aunt");
    await ui.click(screen.getByRole("button", { name: "Generate code" }));
    expect(await screen.findByText("K7QM-3F9X-PLR2-8VDA")).toBeInTheDocument();
    expect(screen.getByText("Write this code down now. It is shown only once.")).toBeInTheDocument();
    expect(calls.find((c) => c.key === "POST /families/f1/invitations")?.body).toEqual({
      role: "caregiver",
      relationship_label: "aunt",
    });
    await ui.click(screen.getByRole("button", { name: "I've noted it" }));
    expect(screen.queryByText("K7QM-3F9X-PLR2-8VDA")).toBeNull();
  });
});

describe("therapist invitations: one teen per family", () => {
  it("after issuing a teen code, the next invitation defaults to caregiver and is enabled", async () => {
    const u = user({ role: "therapist" });
    let teenInvited = false;
    const family = () => ({
      id: "f2",
      group_id: "g1",
      label: "Family B",
      members: [],
      pending: teenInvited
        ? [
            {
              id: "i1",
              role: "adolescent",
              relationship_label: null,
              expires_at: "2026-11-22T00:00:00Z",
              created_at: "2026-11-08T00:00:00Z",
            },
          ]
        : [],
      dyads: [],
    });
    const calls = mockApi({
      "GET /auth/session": session(u),
      "GET /families/f2": () => ({ body: family() }),
      "POST /families/f2/invitations": (body) => {
        if ((body as { role: string }).role === "adolescent") teenInvited = true;
        return {
          status: 201,
          body: { invitation_id: "i", code: "AAAA-BBBB-CCCC-DDDD", expires_at: "2026-11-22T00:00:00Z" },
        };
      },
      "PATCH /me": { body: u },
    });
    const ui = userEvent.setup();
    renderApp("/therapist/families/f2", "server");
    await ui.selectOptions(await screen.findByLabelText("Account type"), "adolescent");
    await ui.click(screen.getByRole("button", { name: "Generate code" }));
    await ui.click(await screen.findByRole("button", { name: "I've noted it" }));
    await waitFor(() =>
      expect(
        within(screen.getByLabelText("Account type")).queryByRole("option", { name: "Teen" }),
      ).toBeNull(),
    );
    const generate = screen.getByRole("button", { name: "Generate code" });
    expect(generate).toBeEnabled();
    await ui.click(generate);
    await waitFor(() =>
      expect(calls.filter((c) => c.key === "POST /families/f2/invitations").map((c) => c.body)).toEqual([
        { role: "adolescent", relationship_label: null },
        { role: "caregiver", relationship_label: null },
      ]),
    );
  });
});
