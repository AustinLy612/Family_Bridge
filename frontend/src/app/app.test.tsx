import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PauseControl } from "../components/Controls";
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

  it("redirects a caregiver away from the adolescent tree to the Portal", async () => {
    const { router } = renderApp("/teen/diary", CAREGIVER);
    await waitFor(() => expect(router.state.location.pathname).toBe("/portal"));
  });

  it("redirects a therapist away from the admin tree", async () => {
    const { router } = renderApp("/admin", THERAPIST);
    await waitFor(() => expect(router.state.location.pathname).toBe("/portal"));
  });

  it("shows the adolescent navigation tree with only the open module expanded (D95)", () => {
    renderApp("/teen", TEEN);
    const nav = screen.getByRole("navigation", { name: "主导航" });
    const labels = within(nav)
      .getAllByRole("link")
      .map((a) => a.textContent);
    expect(labels).toEqual(["门户", "家桥", "概览", "小组回顾", "日记卡", "共同活动", "个人学习", "帮助"]);
    // profile is personal information: pinned with Settings, outside the module tree
    expect(screen.getByRole("link", { name: "个人资料" })).toHaveAttribute("href", "/teen/profile");
  });

  it("caregivers reach Explore skills through Personal Learning and have no Profile entry", () => {
    renderApp("/caregiver", CAREGIVER);
    const nav = screen.getByRole("navigation", { name: "主导航" });
    expect(within(nav).getByRole("link", { name: "个人学习" })).toHaveAttribute("href", "/caregiver/learn");
    expect(screen.queryByRole("link", { name: "个人资料" })).toBeNull();
  });
});

describe("participant screens (§6.2, §7.3)", () => {
  it("show Get help, without a header Pause or an 'only you' label (D92)", () => {
    renderApp("/teen/joint", TEEN);
    expect(screen.getByRole("link", { name: "获取帮助" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "暂停" })).toBeNull();
    expect(screen.queryByText("仅你可见")).toBeNull();
  });

  it("still say when the therapist can see the page (no hidden monitoring)", () => {
    renderApp("/teen/diary", TEEN);
    expect(screen.getByRole("status", { name: "谁能看到这里？" })).toHaveTextContent("你的治疗师可见");
  });

  it("reach 'Who can see my data' from Settings, not the sidebar (D92)", () => {
    renderApp("/teen/settings", TEEN);
    expect(screen.getByRole("link", { name: "查看" })).toHaveAttribute("href", "/teen/privacy");
  });

  it("therapist screens have no participant Pause control", () => {
    renderApp("/therapist", THERAPIST);
    expect(screen.queryByRole("button", { name: "暂停" })).toBeNull();
  });

  it("Pause opens a calm layer without a timer, Escape resumes and focus returns", async () => {
    const user = userEvent.setup();
    render(<PauseControl />); // shown in the joint room header (D92)
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
