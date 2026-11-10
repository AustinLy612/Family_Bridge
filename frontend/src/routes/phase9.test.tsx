/**
 * Phase 9: research instrumentation and export (Plan §5.10; D80-D83).
 * - The admin export screen lists files and row counts (never values) and downloads the zip.
 * - Retention has no screen (cancelled, D83).
 * - Therapists record recruitment denominators for their group.
 * - Usability reports carry only a closed vocabulary: an error kind and a screen key.
 */
import { act, fireEvent, renderHook, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";
import { setCsrfToken } from "../api/client";
import type { ExportFile } from "../api/research";
import { areaOf, reportError, useTaskOutcome } from "../app/research";
import i18n from "../i18n";
import { ADMIN, THERAPIST, mockApi, renderApp } from "../test/render";

beforeEach(async () => {
  await i18n.changeLanguage("en");
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  setCsrfToken(null);
});

const FILES: ExportFile[] = [
  { path: "shared/groups.csv", scope: "shared", description: "x", rows: 1 },
  { path: "adolescent/participants.csv", scope: "adolescent", description: "x", rows: 2 },
  { path: "caregiver/participants.csv", scope: "caregiver", description: "x", rows: 3 },
];

describe("research export (admin)", () => {
  it("lists files by scope with row counts and downloads with the demo choice", async () => {
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: () => "blob:x", revokeObjectURL: () => {} }));
    setCsrfToken("csrf-1");
    const calls = mockApi({
      "GET /admin/research-export?include_demo=false": { body: { include_demo: false, files: FILES } },
      "GET /admin/research-export?include_demo=true": { body: { include_demo: true, files: FILES } },
      "POST /admin/research-export": { body: {} },
    });
    renderApp("/admin/export", ADMIN);
    const teens = await screen.findByTestId("export-adolescent");
    expect(within(teens).getByText("adolescent/participants.csv")).toBeInTheDocument();
    expect(within(teens).getByText("2")).toBeInTheDocument();
    expect(screen.getByTestId("export-caregiver")).toHaveTextContent("caregiver/participants.csv");
    expect(screen.getByText(/separate folders/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("checkbox", { name: "Include demo groups and accounts" }));
    await waitFor(() =>
      expect(calls.some((c) => c.key === "GET /admin/research-export?include_demo=true")).toBe(true),
    );
    const button = screen.getByRole("button", { name: "Download export" });
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
    expect(await screen.findByText(/^Export downloaded/)).toBeInTheDocument();
    const post = calls.find((c) => c.key === "POST /admin/research-export");
    expect(post?.body).toEqual({ include_demo: true });
    expect(post?.headers["X-CSRF-Token"]).toBe("csrf-1");
  });

  it("has no Retention screen (D83)", async () => {
    mockApi({ "GET /admin/therapists": { body: [] } });
    renderApp("/admin", ADMIN);
    expect(await screen.findByRole("link", { name: "Research export" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Retention/ })).toBeNull();
  });
});

describe("recruitment numbers (therapist)", () => {
  it("saves the funnel counts for a period and shows the current figures", async () => {
    const GROUPS = [{ id: "G1", name: "Demo group", family_count: 1, therapists: ["Dr Lin"], is_demo: true }];
    const ROW = {
      id: "R1",
      period_start: "2026-10-01",
      period_end: "2026-10-31",
      screened: 12,
      eligible: 9,
      approached: 8,
      consented: 5,
      recorded_at: "2026-11-09T10:00:00Z",
      recorded_by: "Dr Lin",
    };
    let saved = false;
    const calls = mockApi({
      "GET /groups": { body: GROUPS },
      "GET /groups/G1/metrics?days=28": { status: 404, body: { detail: { code: "not_found" } } },
      "GET /groups/G1/recruitment": () => ({ body: { items: saved ? [ROW] : [] } }),
      "POST /groups/G1/recruitment": () => {
        saved = true;
        return { status: 201, body: ROW };
      },
    });
    renderApp("/therapist/metrics", THERAPIST);
    const save = await screen.findByRole("button", { name: "Save numbers" });
    expect(save).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Period start"), { target: { value: "2026-10-01" } });
    fireEvent.change(screen.getByLabelText("Period end"), { target: { value: "2026-10-31" } });
    for (const [label, v] of [
      ["Screened", "12"],
      ["Eligible", "9"],
      ["Approached", "8"],
      ["Consented", "5"],
    ] as const) {
      fireEvent.change(screen.getByLabelText(label), { target: { value: v } });
    }
    fireEvent.click(save);
    const table = await screen.findByTestId("recruitment-table");
    expect(table).toHaveTextContent("2026-10-01 – 2026-10-31");
    expect(calls.find((c) => c.key === "POST /groups/G1/recruitment")?.body).toEqual({
      period_start: "2026-10-01",
      period_end: "2026-10-31",
      screened: 12,
      eligible: 9,
      approached: 8,
      consented: 5,
    });
  });
});

describe("usability reports", () => {
  it("maps paths to screen keys without ids or query strings", () => {
    expect(areaOf("/teen/diary/0f8c-uuid")).toBe("adolescent:diary");
    expect(areaOf("/caregiver")).toBe("caregiver:");
    expect(areaOf("/onboarding")).toBe("onboarding");
    expect(areaOf("/somewhere?q=I feel sad")).toBe("other");
  });

  it("sends only kind and area, deduplicated, and nothing when signed out", () => {
    const calls = mockApi({ "POST /research/client-events": { status: 204 } });
    reportError("js");
    expect(calls).toHaveLength(0); // no session, no report
    setCsrfToken("csrf-2");
    window.history.pushState({}, "", "/teen/diary/abc?x=private");
    reportError("api_5xx");
    reportError("api_5xx");
    expect(calls).toHaveLength(1);
    expect(calls[0]?.body).toEqual({ type: "client.error", kind: "api_5xx", area: "adolescent:diary" });
    window.history.pushState({}, "", "/");
  });

  it("reports a task abandoned when left, and success once only", async () => {
    vi.useFakeTimers();
    setCsrfToken("csrf-3");
    const calls = mockApi({ "POST /research/client-events": { status: 204 } });
    const left = renderHook(() => useTaskOutcome("diary_entry"));
    left.unmount();
    act(() => vi.runAllTimers());
    expect(calls.map((c) => c.body)).toEqual([
      { type: "task.outcome", task: "diary_entry", outcome: "abandoned" },
    ]);
    const done = renderHook(() => useTaskOutcome("onboarding"));
    act(() => {
      done.result.current();
      done.result.current();
    });
    done.unmount();
    act(() => vi.runAllTimers());
    expect(calls.map((c) => c.body).slice(1)).toEqual([
      { type: "task.outcome", task: "onboarding", outcome: "success" },
    ]);
  });
});
