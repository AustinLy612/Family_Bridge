/**
 * Admin: knowledge-base status (Plan §5.3, §6.1; Phase 3 task 7). Read-only.
 * Shows versions, chunk counts, ingestion warnings, the last recorded retrieval evaluation and
 * search totals. Never shows manual text (D7). Ingestion and evaluation run from the CLI.
 */
import { useQuery } from "@tanstack/react-query";
import { Database, FileText, Layers, Search } from "lucide-react";
import { useTranslation } from "react-i18next";
import { get } from "../../api/client";
import type { KbStatus, KbVersion } from "../../api/types";
import { ErrorNotice, Notice } from "../../components/Forms";
import { Chip, StatTile } from "../../design";
import { Page } from "../Page";
import { useDateTime } from "../safety/time";

const MODULES = [
  "orientation",
  "mindfulness",
  "distress_tolerance",
  "walking_the_middle_path",
  "emotion_regulation",
  "interpersonal_effectiveness",
] as const;

function pct(x: number) {
  return `${Math.round(x * 1000) / 10}%`;
}

function ActiveVersion({ v }: { v: KbVersion }) {
  const { t } = useTranslation();
  const when = useDateTime();
  return (
    <>
      <section className="fb-card" aria-labelledby="kb-active">
        <h2 id="kb-active" className="fb-card__title">
          {t("kb.activeVersion", { version: v.version })}
        </h2>
        <dl className="fb-dl">
          <dt>{t("kb.activatedAt")}</dt>
          <dd>{v.activated_at ? when(v.activated_at) : "—"}</dd>
          <dt>{t("kb.embeddingModel")}</dt>
          <dd>{v.embedding_model}</dd>
          <dt>{t("kb.source")}</dt>
          <dd>{t("kb.sourceValue", { pages: v.source_pages, index: v.handout_index_version })}</dd>
          <dt>{t("kb.transcribed")}</dt>
          <dd>
            {t("kb.transcribedValue", {
              count: v.transcribed_pages.length,
              pages: v.transcribed_pages.join(", "),
            })}
          </dd>
        </dl>
      </section>

      <section className="fb-card" aria-labelledby="kb-modules">
        <h2 id="kb-modules" className="fb-card__title">
          {t("kb.chunksByModule")}
        </h2>
        <table className="fb-table" aria-labelledby="kb-modules">
          <thead>
            <tr>
              <th scope="col">{t("kb.module")}</th>
              <th scope="col">{t("kb.chunks")}</th>
            </tr>
          </thead>
          <tbody>
            {MODULES.map((m) => (
              <tr key={m}>
                <td>{t(`kb.modules.${m}`)}</td>
                <td>{v.chunks_by_module[m] ?? 0}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="fb-card" aria-labelledby="kb-eval">
        <h2 id="kb-eval" className="fb-card__title">
          {t("kb.evalTitle")}
        </h2>
        {v.eval ? (
          <>
            <p>
              <Chip tone={v.eval.passed ? "blue" : "amber"}>
                {t(v.eval.passed ? "kb.evalPassed" : "kb.evalFailed")}
              </Chip>{" "}
              {t("kb.evalTarget", { k: v.eval.k, target: pct(v.eval.target_recall) })}
            </p>
            <table className="fb-table" aria-labelledby="kb-eval">
              <thead>
                <tr>
                  <th scope="col">{t("kb.language")}</th>
                  <th scope="col">{t("kb.queries")}</th>
                  <th scope="col">{t("kb.recall", { k: v.eval.k })}</th>
                  <th scope="col">{t("kb.mrr")}</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(v.eval.by_language).map(([lang, b]) => (
                  <tr key={lang}>
                    <td>{t(`kb.lang.${lang}`)}</td>
                    <td>{b.queries}</td>
                    <td>{pct(b.recall)}</td>
                    <td>{b.mrr.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        ) : (
          <p>{t("kb.noEval")}</p>
        )}
      </section>

      <section className="fb-card" aria-labelledby="kb-warnings">
        <h2 id="kb-warnings" className="fb-card__title">
          {t("kb.headerChecks")}
        </h2>
        {v.header_mismatches.length === 0 ? (
          <p>{t("kb.noMismatches")}</p>
        ) : (
          <>
            <p className="fb-setting__hint">{t("kb.mismatchHint")}</p>
            <ul>
              {v.header_mismatches.map((m) => (
                <li key={m.page}>{t("kb.mismatch", m)}</li>
              ))}
            </ul>
          </>
        )}
      </section>
    </>
  );
}

export function KnowledgeBasePage() {
  const { t } = useTranslation();
  const when = useDateTime();
  const q = useQuery({ queryKey: ["admin", "kb"], queryFn: () => get<KbStatus>("/admin/kb") });
  const d = q.data;
  return (
    <Page title={t("nav.knowledgeBase")} subtitle={t("kb.subtitle")} icon={<Database size={22} />}>
      <div className="fb-stack">
        <Notice>{t("kb.notice")}</Notice>
        <ErrorNotice error={q.error} />
        {d && (
          <>
            <div className="fb-stats">
              <StatTile
                icon={<FileText size={20} />}
                value={d.active?.handouts ?? 0}
                caption={t("kb.handouts")}
              />
              <StatTile
                icon={<Layers size={20} />}
                value={d.active?.chunk_count ?? 0}
                caption={t("kb.chunks")}
              />
              <StatTile
                icon={<Search size={20} />}
                value={d.retrieval.searches}
                caption={t("kb.searches", { days: d.retrieval.days, insufficient: d.retrieval.insufficient })}
              />
            </div>
            {d.active ? <ActiveVersion v={d.active} /> : <p>{t("kb.empty")}</p>}
            {d.history.length > 0 && (
              <section className="fb-card" aria-labelledby="kb-history">
                <h2 id="kb-history" className="fb-card__title">
                  {t("kb.history")}
                </h2>
                <ul className="fb-timeline">
                  {d.history.map((h) => (
                    <li key={h.version}>
                      {t("kb.historyItem", {
                        version: h.version,
                        status: t(`kb.status.${h.status}`),
                        chunks: h.chunk_count,
                        when: when(h.created_at),
                      })}
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </>
        )}
      </div>
    </Page>
  );
}
