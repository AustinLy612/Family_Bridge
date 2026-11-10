/** Phase 3: admin knowledge-base status page against a mocked API (read-only, no manual text). */
import { screen, within } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";
import { setCsrfToken } from "../api/client";
import type { KbStatus } from "../api/types";
import i18n from "../i18n";
import { ADMIN, THERAPIST, mockApi, renderApp } from "../test/render";

beforeEach(async () => {
  await i18n.changeLanguage("en");
});

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
});

const STATUS: KbStatus = {
  active: {
    version: 5,
    status: "active",
    created_at: "2026-11-09T06:40:00Z",
    activated_at: "2026-11-09T06:40:05Z",
    chunk_count: 93,
    embedding_model: "intfloat/multilingual-e5-large",
    source_pages: 113,
    handout_index_version: 1,
    handouts: 86,
    chunks_by_module: { mindfulness: 8, emotion_regulation: 27 },
    chunks_by_source_quality: { pdf_text: 83, manual_transcription: 10 },
    transcribed_pages: [7, 8, 15],
    header_mismatches: [{ page: 106, found: "ie.h8", expected: "ie.h7" }],
    eval: {
      passed: true,
      k: 5,
      target_recall: 0.85,
      eval_set_version: 1,
      overall: { queries: 78, recall: 0.9744, mrr: 0.81 },
      by_language: {
        en: { queries: 35, recall: 0.9714, mrr: 0.83 },
        "zh-CN": { queries: 43, recall: 0.9767, mrr: 0.8 },
      },
      misses: 2,
    },
  },
  history: [
    { version: 5, status: "active", chunk_count: 93, created_at: "2026-11-09T06:40:00Z" },
    { version: 4, status: "superseded", chunk_count: 93, created_at: "2026-11-09T06:30:00Z" },
  ],
  retrieval: { days: 7, searches: 12, insufficient: 3, median_latency_ms: 40 },
  min_score: { "zh-CN": 0.83, en: 0.775 },
};

describe("admin knowledge base", () => {
  it("shows the active version, module counts, evaluation and header checks", async () => {
    mockApi({ "GET /admin/kb": { body: STATUS } });
    renderApp("/admin/knowledge", ADMIN);
    expect(await screen.findByRole("heading", { name: "Active version 5" })).toBeInTheDocument();
    expect(screen.getByText("Handouts").previousSibling).toHaveTextContent("86");
    expect(screen.getByText("intfloat/multilingual-e5-large")).toBeInTheDocument();
    const modules = screen.getByRole("table", { name: "Chunks by module" });
    expect(within(modules).getByRole("row", { name: "Emotion regulation 27" })).toBeInTheDocument();
    expect(within(modules).getByRole("row", { name: "Orientation 0" })).toBeInTheDocument();
    expect(screen.getByText("Target met")).toBeInTheDocument();
    const evalTable = screen.getByRole("table", { name: "Retrieval evaluation" });
    expect(within(evalTable).getByRole("row", { name: "Chinese 43 97.7% 0.80" })).toBeInTheDocument();
    expect(within(evalTable).getByRole("row", { name: "English 35 97.1% 0.83" })).toBeInTheDocument();
    expect(screen.getByText("Page 106: header says ie.h8, index says ie.h7")).toBeInTheDocument();
    const history = screen.getByRole("heading", { name: "Versions" }).parentElement!;
    expect(within(history).getByText(/v4 · Superseded · 93 chunks/)).toBeInTheDocument();
  });

  it("explains an empty knowledge base", async () => {
    mockApi({
      "GET /admin/kb": {
        body: { ...STATUS, active: null, history: [], retrieval: { ...STATUS.retrieval, searches: 0 } },
      },
    });
    renderApp("/admin/knowledge", ADMIN);
    expect(await screen.findByText(/The knowledge base is empty/)).toBeInTheDocument();
  });

  it("is not reachable for therapists", async () => {
    renderApp("/admin/knowledge", THERAPIST);
    expect(screen.queryByRole("heading", { name: "Knowledge base" })).not.toBeInTheDocument();
  });
});
