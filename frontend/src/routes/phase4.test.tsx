/** Phase 4: admin AI status page (counts and codes only) and provenance labels (D6). */
import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";
import { setCsrfToken } from "../api/client";
import type { AiStatus } from "../api/types";
import { ProvenanceChip, provenanceOf } from "../design";
import i18n from "../i18n";
import { ADMIN, THERAPIST, Providers, mockApi, renderApp } from "../test/render";

beforeEach(async () => {
  await i18n.changeLanguage("en");
});

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
});

const STATUS: AiStatus = {
  provider: "deepseek",
  model: "deepseek-flash",
  breaker: "closed",
  days: 7,
  calls: 40,
  fallbacks: 2,
  functions: [
    {
      function: "explain_skill",
      calls: 10,
      fallbacks: 0,
      repaired: 1,
      retried: 2,
      general: 3,
      median_latency_ms: 2100,
    },
    {
      function: "teaching_turn",
      calls: 30,
      fallbacks: 2,
      repaired: 0,
      retried: 0,
      general: 0,
      median_latency_ms: null,
    },
  ],
  failure_codes: { "pattern:blame_shame": 1, "language:not_chinese": 3 },
  prompts: [
    { function: "hint", role: "caregiver", language: "en", version: 1, approval: "draft" },
    { function: "hint", role: "caregiver", language: "zh-CN", version: 1, approval: "draft" },
  ],
  fallback_files: 26,
  cache_items: 5,
  cache_by_review: { unreviewed: 4, needs_change: 1 },
  eval_runs: [
    {
      kind: "adversarial",
      created_at: "2026-11-09T06:40:00Z",
      provider: "deepseek",
      model: "deepseek-flash",
      passed: true,
      headline: { by_severity: { high: { cases: 48, passed: 48 } } },
    },
    {
      kind: "sweep_sample",
      created_at: "2026-11-09T06:30:00Z",
      provider: "deepseek",
      model: "deepseek-flash",
      passed: true,
      headline: { calls: 120, fallback_rate: 0.025 },
    },
  ],
};

describe("admin AI layer", () => {
  it("shows provider, usage by function, rejection codes and evaluation runs", async () => {
    mockApi({ "GET /admin/ai": { body: STATUS } });
    renderApp("/admin/ai", ADMIN);
    expect(await screen.findByText("Normal")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "AI layer", level: 1 })).toBeInTheDocument();
    expect(screen.getByText("deepseek-flash", { selector: "dd" })).toBeInTheDocument();
    expect(screen.getByText("5%")).toBeInTheDocument(); // 2 of 40
    const fns = screen.getByRole("table", { name: "By function" });
    expect(within(fns).getByRole("row", { name: "explain_skill 10 0 1 2 3 2100 ms" })).toBeInTheDocument();
    expect(within(fns).getByRole("row", { name: "teaching_turn 30 2 0 0 0 —" })).toBeInTheDocument();
    const codes = screen.getByRole("table", { name: "Why answers were rejected" });
    const rows = within(codes).getAllByRole("row");
    expect(rows[1]).toHaveTextContent("language:not_chinese3"); // most frequent first
    expect(screen.getByText("High severity: 48 of 48 handled safely")).toBeInTheDocument();
    expect(screen.getByText("120 calls, fallback rate 2.5%")).toBeInTheDocument();
    expect(screen.getByText("Draft: 2")).toBeInTheDocument();
    expect(screen.getByText("Needs change: 1")).toBeInTheDocument();
  });

  it("explains empty states", async () => {
    mockApi({
      "GET /admin/ai": {
        body: {
          ...STATUS,
          calls: 0,
          fallbacks: 0,
          functions: [],
          failure_codes: {},
          eval_runs: [],
          breaker: "open",
        },
      },
    });
    renderApp("/admin/ai", ADMIN);
    expect(await screen.findByText("No AI calls in this period.")).toBeInTheDocument();
    expect(screen.getByText(/No evaluation has been run yet/)).toBeInTheDocument();
    expect(screen.getByText("Paused after errors")).toBeInTheDocument();
  });

  it("is listed in the admin navigation", async () => {
    mockApi({ "GET /admin/ai": { body: STATUS } });
    renderApp("/admin/ai", ADMIN);
    const links = await screen.findAllByRole("link", { name: "AI layer" });
    expect(links.some((l) => l.getAttribute("href") === "/admin/ai")).toBe(true);
  });

  it("is not reachable for therapists", async () => {
    renderApp("/admin/ai", THERAPIST);
    expect(screen.queryByRole("heading", { name: "AI layer" })).not.toBeInTheDocument();
  });
});

describe("provenance labels (D6)", () => {
  it("maps backend content sources to the three labels", () => {
    expect(provenanceOf("ai_manual")).toBe("ai");
    expect(provenanceOf("ai_general")).toBe("general");
    expect(provenanceOf("authored")).toBe("authored");
    expect(provenanceOf("none")).toBeNull();
  });

  it.each([
    ["en", ["AI-generated from the manual", "AI · general DBT knowledge", "Authored content"]],
    ["zh-CN", ["AI 根据手册生成", "AI · 通用 DBT 知识", "人工编写内容"]],
  ])("labels every source in %s", async (lang, labels) => {
    await i18n.changeLanguage(lang);
    render(
      <Providers>
        <ProvenanceChip kind="ai" />
        <ProvenanceChip kind="general" />
        <ProvenanceChip kind="authored" />
      </Providers>,
    );
    for (const label of labels) expect(screen.getByText(label)).toBeInTheDocument();
  });
});
