/**
 * Content review (Plan §5.8; D71): cached AI explanations, practice items and quizzes that every
 * caregiver opening a skill is served. Any therapist may mark an item "reviewed" or "needs
 * change". "Needs change" withdraws it at once; the next request regenerates it (or serves the
 * authored fallback) and the new version appears here for review. Prompt files change through
 * version control only. Episode versions are approved or retired here by content approvers
 * (Plan §4.2); demo fixtures stay demo-only.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FileCheck2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { bi, joint } from "../../api/joint";
import { therapist, type CacheItem, type CacheReviewState } from "../../api/therapist";
import { ErrorNotice } from "../../components/Forms";
import { Chip } from "../../design";
import { SourceChip } from "../../features/lessons/common";
import { Page } from "../Page";
import { ChoiceGroup } from "./common";
import "../../features/joint/joint.css";
import "./therapist.css";

const FILTERS = ["unreviewed", "reviewed", "needs_change", "all"] as const;
type Filter = (typeof FILTERS)[number];

export function ContentReviewPage() {
  const { t } = useTranslation();
  const [filter, setFilter] = useState<Filter>("unreviewed");
  const [offset, setOffset] = useState(0);
  const q = useQuery({
    queryKey: ["content-cache", filter, offset],
    queryFn: () => therapist.cache({ review: filter === "all" ? undefined : filter, offset }),
  });
  const counts = q.data?.counts;
  return (
    <Page
      title={t("nav.contentReview")}
      subtitle={t("therapist.content.subtitle")}
      icon={<FileCheck2 size={22} />}
    >
      <div className="fb-stack">
        <Episodes />
        <h2 className="fb-card__title">{t("therapist.content.cacheTitle")}</h2>
        <ChoiceGroup
          label={t("therapist.content.show")}
          options={FILTERS}
          value={filter}
          onChange={(f) => {
            setFilter(f);
            setOffset(0);
          }}
          format={(f) =>
            f === "all"
              ? t("therapist.content.all")
              : `${t(`therapist.content.state.${f}`)}${counts ? ` (${counts[f]})` : ""}`
          }
        />
        <ErrorNotice error={q.error} />
        {q.data?.items.length === 0 && <p>{t("therapist.content.empty")}</p>}
        {q.data?.items.map((item) => (
          <Item key={item.id} item={item} />
        ))}
        {q.data && q.data.total > q.data.page_size && (
          <div className="fb-actions">
            <button
              type="button"
              className="fb-btn fb-btn--secondary"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - q.data.page_size))}
            >
              {t("therapist.content.previous")}
            </button>
            <button
              type="button"
              className="fb-btn fb-btn--secondary"
              disabled={offset + q.data.page_size >= q.data.total}
              onClick={() => setOffset(offset + q.data.page_size)}
            >
              {t("therapist.content.next")}
            </button>
          </div>
        )}
      </div>
    </Page>
  );
}

/** Teaching text only: render the item's strings readably, without inventing structure. */
function Output({ value }: { value: unknown }) {
  if (typeof value === "string") return <p>{value}</p>;
  if (typeof value === "number" || typeof value === "boolean") return <p>{String(value)}</p>;
  if (Array.isArray(value)) {
    return (
      <ol>
        {value.map((v, i) => (
          <li key={i}>
            <Output value={v} />
          </li>
        ))}
      </ol>
    );
  }
  if (value && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>).filter(
      ([k]) => !["source_chunk_ids", "rubric_tag", "source"].includes(k),
    );
    return (
      <dl className="fb-diary-values">
        {entries.map(([k, v]) => (
          <div key={k} style={{ display: "contents" }}>
            <dt>{k}</dt>
            <dd>
              <Output value={v} />
            </dd>
          </div>
        ))}
      </dl>
    );
  }
  return null;
}

function Item({ item }: { item: CacheItem }) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const [error, setError] = useState<unknown>(null);
  async function decide(decision: "reviewed" | "needs_change") {
    setError(null);
    try {
      await therapist.reviewCache(item.id, decision);
      await qc.invalidateQueries({ queryKey: ["content-cache"] });
    } catch (err) {
      setError(err);
    }
  }
  const state: CacheReviewState = item.review;
  return (
    <article className="fb-card fb-stack" data-testid="cache-item">
      <h2 className="fb-card__title">
        {item.skill.name} · {t(`therapist.content.function.${item.function}`, item.function)}{" "}
        <Chip tone="outline">{t(`therapist.content.state.${state}`)}</Chip>
      </h2>
      <p className="fb-setting__hint">
        {t("therapist.content.meta", {
          language: t(`language.${item.language}`, item.language),
          variant: t(`therapist.content.variant.${item.variant}`, item.variant),
          prompt: item.prompt_version,
          kb: item.kb_version,
          hits: item.hits,
          date: new Date(item.created_at).toLocaleDateString(i18n.language),
        })}{" "}
        <SourceChip source={item.source as Parameters<typeof SourceChip>[0]["source"]} />
      </p>
      {item.reviewed_by && item.reviewed_at && (
        <p className="fb-setting__hint">
          {t("therapist.content.reviewedBy", {
            alias: item.reviewed_by,
            date: new Date(item.reviewed_at).toLocaleDateString(i18n.language),
          })}
        </p>
      )}
      <details>
        <summary>{t("therapist.content.read")}</summary>
        <div className="fb-content-output">
          <Output value={item.output} />
        </div>
      </details>
      <ErrorNotice error={error} />
      {state !== "needs_change" && (
        <div className="fb-actions">
          {state !== "reviewed" && (
            <button
              type="button"
              className="fb-btn fb-btn--secondary"
              onClick={() => void decide("reviewed")}
            >
              {t("therapist.content.markReviewed")}
            </button>
          )}
          <button
            type="button"
            className="fb-btn fb-btn--secondary"
            onClick={() => void decide("needs_change")}
          >
            {t("therapist.content.markNeedsChange")}
          </button>
        </div>
      )}
      {state === "needs_change" && <p className="fb-setting__hint">{t("therapist.content.withdrawn")}</p>}
    </article>
  );
}

/** Episode registry (Plan §4.1 `Episode`, §4.2): approve or retire versions; demo stays demo. */
function Episodes() {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["episodes"], queryFn: joint.episodes });
  const [error, setError] = useState<unknown>(null);
  async function decide(id: string, version: number, status: "approved" | "retired") {
    setError(null);
    try {
      await joint.decide(id, version, status);
      await qc.invalidateQueries({ queryKey: ["episodes"] });
    } catch (err) {
      setError(err);
    }
  }
  return (
    <section className="fb-card fb-stack" aria-labelledby="episode-registry" data-testid="episode-registry">
      <h2 id="episode-registry" className="fb-card__title">
        {t("therapist.content.episodes")}
      </h2>
      <p className="fb-setting__hint">
        {q.data?.can_approve
          ? t("therapist.content.episodesHint")
          : t("therapist.content.episodesNotApprover")}
      </p>
      <ErrorNotice error={error ?? q.error} />
      <ul className="fb-joint-past">
        {q.data?.episodes.map((e) => (
          <li key={`${e.id}@${e.version}`}>
            <strong>{bi(e.title, i18n.language)}</strong> v{e.version}{" "}
            <Chip tone="outline">{t(`therapist.content.episodeState.${e.status}`)}</Chip>{" "}
            {q.data.can_approve && e.status === "draft" && (
              <button
                type="button"
                className="fb-btn fb-btn--secondary"
                onClick={() => void decide(e.id, e.version, "approved")}
              >
                {t("therapist.content.approve")}
              </button>
            )}{" "}
            {q.data.can_approve && (e.status === "draft" || e.status === "approved") && (
              <button
                type="button"
                className="fb-btn fb-btn--secondary"
                onClick={() => void decide(e.id, e.version, "retired")}
              >
                {t("therapist.content.retire")}
              </button>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
