import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CAREGIVER, TEEN, THERAPIST, renderApp } from "../test/render";

describe("placeholder start page + language switch (Phase 0 acceptance)", () => {
  it("switches between Simplified Chinese and English", async () => {
    const user = userEvent.setup();
    renderApp("/");
    expect(screen.getByRole("heading", { level: 1, name: "欢迎来到 FamilyBridge" })).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("zh-CN");

    await user.click(screen.getByRole("radio", { name: "English" }));
    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: "Welcome to FamilyBridge",
      }),
    ).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("en");
    expect(localStorage.getItem("fb.language")).toBe("en");

    await user.click(screen.getByRole("radio", { name: "简体中文" }));
    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: "欢迎来到 FamilyBridge",
      }),
    ).toBeInTheDocument();
  });

  it("states the app is not monitored in real time (§9.1F)", () => {
    renderApp("/");
    expect(screen.getByText("FamilyBridge 不会被实时监看。")).toBeInTheDocument();
  });
});

describe("role-gated route trees", () => {
  it("sends a signed-out visitor to the start page", async () => {
    const { router } = renderApp("/teen/diary");
    await waitFor(() => expect(router.state.location.pathname).toBe("/"));
  });

  it("redirects a caregiver away from the adolescent tree to their own home", async () => {
    const { router } = renderApp("/teen/diary", CAREGIVER);
    await waitFor(() => expect(router.state.location.pathname).toBe("/caregiver"));
  });

  it("redirects a therapist away from the admin tree", async () => {
    const { router } = renderApp("/admin", THERAPIST);
    await waitFor(() => expect(router.state.location.pathname).toBe("/therapist"));
  });

  it("shows the adolescent navigation from Plan §5.13.1", () => {
    renderApp("/teen", TEEN);
    const nav = screen.getByRole("navigation", { name: "主导航" });
    const labels = within(nav)
      .getAllByRole("link")
      .map((a) => a.textContent);
    expect(labels).toEqual([
      "首页",
      "学习",
      "小组回顾",
      "日记卡",
      "共同活动",
      "帮助",
      "谁能看到我的数据",
      "个人资料",
    ]);
  });

  it("uses 'Explore skills' for caregivers and has no Profile entry", () => {
    renderApp("/caregiver", CAREGIVER);
    const nav = screen.getByRole("navigation", { name: "主导航" });
    expect(within(nav).getByRole("link", { name: "探索技能" })).toBeInTheDocument();
    expect(within(nav).queryByRole("link", { name: "个人资料" })).toBeNull();
  });
});

describe("participant screens (§6.2, §7.3)", () => {
  it("always show Pause and the who-can-see indicator", () => {
    renderApp("/teen/joint", TEEN);
    expect(screen.getByRole("button", { name: "暂停" })).toBeInTheDocument();
    expect(screen.getByRole("status", { name: "谁能看到这里？" })).toHaveTextContent("仅你可见");
  });

  it("therapist screens have no participant Pause control", () => {
    renderApp("/therapist", THERAPIST);
    expect(screen.queryByRole("button", { name: "暂停" })).toBeNull();
  });

  it("Pause opens a calm layer without a timer, Escape resumes and focus returns", async () => {
    const user = userEvent.setup();
    renderApp("/teen", TEEN);
    const pause = screen.getByRole("button", { name: "暂停" });
    await user.click(pause);
    const dialog = screen.getByRole("dialog", { name: "已暂停" });
    expect(dialog).toHaveTextContent("没有计时");
    expect(within(dialog).getByRole("button", { name: "准备好了再继续" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(pause).toHaveFocus();
  });
});

describe("accessibility settings", () => {
  it("defaults: sound off, illustrations on for participants, follows OS motion", () => {
    renderApp("/teen/settings", TEEN);
    expect(screen.getByRole("switch", { name: /声音/ })).toHaveAttribute("aria-checked", "false");
    expect(screen.getByRole("switch", { name: /显示插画/ })).toHaveAttribute("aria-checked", "true");
    expect(document.documentElement.dataset.reduceMotion).toBe("false");
  });

  it("illustrations default off for therapists (Plan §5.13.5)", () => {
    renderApp("/therapist/settings", THERAPIST);
    expect(screen.getByRole("switch", { name: /显示插画/ })).toHaveAttribute("aria-checked", "false");
  });

  it("applies contrast, calm palette, reduce motion and 200 % text to the document", async () => {
    const user = userEvent.setup();
    renderApp("/teen/settings", TEEN);
    await user.click(screen.getByRole("switch", { name: /高对比度/ }));
    await user.click(screen.getByRole("switch", { name: /柔和配色/ }));
    await user.click(screen.getByRole("switch", { name: /减少动效/ }));
    await user.click(screen.getByRole("radio", { name: "200%" }));
    const el = document.documentElement;
    expect(el.dataset.contrast).toBe("high");
    expect(el.dataset.palette).toBe("calm");
    expect(el.dataset.reduceMotion).toBe("true");
    expect(el.style.getPropertyValue("--text-scale")).toBe("2");
    expect(JSON.parse(localStorage.getItem("fb.a11y") ?? "{}")).toMatchObject({
      textScale: 2,
      sound: false,
    });
  });
});

describe("dev gallery", () => {
  it("renders every base component section", async () => {
    await act(async () => {
      renderApp("/dev/gallery");
    });
    const expected = [
      "HeroBanner 横幅",
      "StatTile 数据块",
      "SelectCard 选择卡片",
      "DetailBar 详情条 + 按钮",
      "Chip 标签",
      "ListRow 列表行",
      "ProgressBar 进度条",
      "ProfileHeader 个人资料头部",
    ];
    for (const name of expected) {
      expect(await screen.findByRole("heading", { level: 2, name })).toBeInTheDocument();
    }
    // CalendarGrid is therapist-only: hidden while previewing a participant shell.
    expect(screen.queryByRole("heading", { name: /CalendarGrid/ })).toBeNull();
  });
});
