/**
 * Unified Portal and module hierarchy (D95): every role lands on the shared Portal, which holds
 * account details/settings and opens each module; every existing screen stays reachable at its
 * old URL and sits in exactly one place in the navigation tree.
 */
import { screen, waitFor, within } from "@testing-library/react";
import { ADMIN, CAREGIVER, TEEN, THERAPIST, mockApi, renderApp } from "../test/render";
import { ACCOUNT, MODULES, NAV, SHARED, moduleFor } from "./nav";
import { ROLES, landingFor } from "./session";

describe("Portal landing", () => {
  it("is where every onboarded role lands; participants still finish onboarding first", () => {
    for (const u of [TEEN, CAREGIVER, THERAPIST, ADMIN]) expect(landingFor(u)).toBe("/portal");
    expect(landingFor({ ...TEEN, onboarded: false })).toBe("/onboarding");
    expect(landingFor({ ...THERAPIST, onboarded: false })).toBe("/portal");
  });

  it("sends a signed-out visitor to the start page and a new participant to onboarding", async () => {
    const out = renderApp("/portal");
    await waitFor(() => expect(out.router.state.location.pathname).toBe("/"));
    out.unmount();
    const fresh = renderApp("/portal", { ...TEEN, onboarded: false });
    await waitFor(() => expect(fresh.router.state.location.pathname).toBe("/onboarding"));
  });

  it("shows a teen's account details, both modules and account links", async () => {
    mockApi({ "GET /learn/sessions/current": { body: { lesson: null } } });
    renderApp("/portal", { ...TEEN, username: "demo-teen" });
    expect(screen.getByRole("heading", { level: 1, name: "门户" })).toBeInTheDocument();
    const fb = screen.getByRole("region", { name: "家桥" });
    expect(within(fb).getByRole("link", { name: "进入家桥" })).toHaveAttribute("href", "/teen");
    for (const [name, href] of [
      ["小组回顾", "/teen/group-review"],
      ["日记卡", "/teen/diary"],
      ["共同活动", "/teen/joint"],
    ])
      expect(within(fb).getByRole("link", { name })).toHaveAttribute("href", href);
    const pl = screen.getByRole("region", { name: "个人学习" });
    expect(within(pl).getByRole("link", { name: "进入个人学习" })).toHaveAttribute("href", "/teen/learn");
    const account = screen.getByRole("region", { name: "你的账户" });
    expect(account).toHaveTextContent("demo-teen");
    expect(within(account).getByRole("link", { name: /个人资料/ })).toHaveAttribute("href", "/teen/profile");
    expect(within(account).getByRole("link", { name: /设置/ })).toHaveAttribute("href", "/teen/settings");
    expect(within(account).getByRole("link", { name: /谁能看到我的数据/ })).toHaveAttribute(
      "href",
      "/teen/privacy",
    );
    // Help stays one click away (Plan §5.7), in the page and in the header
    expect(screen.getAllByRole("link", { name: /帮助/ }).length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: "获取帮助" })).toHaveAttribute("href", "/teen/help");
  });

  it("offers an unfinished lesson as a shortcut in Personal Learning", async () => {
    mockApi({
      "GET /learn/sessions/current": { body: { lesson: { id: "L1", skill: { name: "TIPP" } } } },
    });
    renderApp("/portal", TEEN);
    const pl = screen.getByRole("region", { name: "个人学习" });
    expect(await within(pl).findByRole("link", { name: "继续上次的课" })).toHaveAttribute(
      "href",
      "/teen/learn/L1",
    );
  });

  it("gives therapists their modules plus the safety queue, without participant-only links", () => {
    renderApp("/portal", THERAPIST);
    expect(
      within(screen.getByRole("region", { name: "家桥" })).getByRole("link", { name: "进入家桥" }),
    ).toHaveAttribute("href", "/therapist");
    expect(
      within(screen.getByRole("region", { name: "个人学习" })).getByRole("link", { name: "进入个人学习" }),
    ).toHaveAttribute("href", "/therapist/progress");
    expect(screen.getAllByRole("link", { name: /安全事件队列/ })[0]).toHaveAttribute(
      "href",
      "/therapist/safety",
    );
    expect(screen.queryByRole("link", { name: "获取帮助" })).toBeNull();
    expect(screen.queryByRole("link", { name: /谁能看到我的数据/ })).toBeNull();
  });

  it("gives admins Administration and Personal Learning", () => {
    renderApp("/portal", ADMIN);
    expect(screen.getByRole("region", { name: "平台管理" })).toBeInTheDocument();
    expect(
      within(screen.getByRole("region", { name: "个人学习" })).getByRole("link", { name: "知识库" }),
    ).toHaveAttribute("href", "/admin/knowledge");
    expect(screen.queryByRole("region", { name: "家桥" })).toBeNull();
  });
});

describe("module hierarchy keeps every screen", () => {
  it("lists each routed screen exactly once across modules, shared and account items", () => {
    for (const role of ROLES) {
      const keys = [...MODULES[role].flatMap((m) => m.items), ...SHARED[role], ...ACCOUNT[role]].map(
        (i) => i.path,
      );
      expect(new Set(keys).size).toBe(keys.length);
      expect(NAV[role].map((i) => i.path).sort()).toEqual([...keys].sort());
    }
  });

  it("keeps every pre-D95 screen path", () => {
    const before: Record<string, string[]> = {
      adolescent: ["", "learn", "group-review", "diary", "joint", "help", "profile"],
      caregiver: ["", "learn", "group-review", "diary", "joint", "help"],
      therapist: ["", "schedule", "diary-review", "progress", "joint", "safety", "content", "metrics"],
      admin: ["", "site", "safety", "knowledge", "ai", "export"],
    };
    for (const role of ROLES)
      expect(NAV[role].map((i) => i.path).sort()).toEqual([...(before[role] ?? [])].sort());
  });

  it("maps paths, including detail screens, to their module", () => {
    expect(moduleFor("adolescent", "/teen")).toBe("family");
    expect(moduleFor("adolescent", "/teen/diary/new")).toBe("family");
    expect(moduleFor("adolescent", "/teen/joint/abc")).toBe("family");
    expect(moduleFor("adolescent", "/teen/learn/tests/t1")).toBe("learning");
    expect(moduleFor("adolescent", "/teen/settings")).toBeNull();
    expect(moduleFor("adolescent", "/teen/help")).toBeNull();
    expect(moduleFor("caregiver", "/caregiver/learn/lesson/x")).toBe("learning");
    expect(moduleFor("therapist", "/therapist/groups/g1")).toBe("family");
    expect(moduleFor("therapist", "/therapist/families/f1")).toBe("family");
    expect(moduleFor("therapist", "/therapist/families/f1/diary")).toBe("family");
    expect(moduleFor("therapist", "/therapist/families/f1/learning")).toBe("learning");
    expect(moduleFor("therapist", "/therapist/safety/e1")).toBeNull();
    expect(moduleFor("admin", "/admin/ai")).toBe("learning");
    expect(moduleFor("admin", "/admin")).toBe("admin");
    expect(moduleFor("admin", "/portal")).toBeNull();
  });

  it("expands only the open module in the sidebar", () => {
    renderApp("/therapist/progress", THERAPIST);
    const nav = screen.getByRole("navigation", { name: "主导航" });
    expect(within(nav).getByRole("link", { name: "内容审核" })).toBeInTheDocument();
    expect(within(nav).queryByRole("link", { name: "日程" })).toBeNull();
    expect(within(nav).getByRole("link", { name: /安全事件队列/ })).toBeInTheDocument();
  });
});
