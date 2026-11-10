/**
 * Therapist diary review (Plan §5.6, §5.8; D15). One panel per participant — adolescent and
 * caregiver cards are never merged (§5.3). Trend lines for the 1–10 items, skill use, a neutral
 * completion calendar (missing days are empty cells, never red) and the entries themselves.
 * Every load is audited server-side.
 */
import { useQueries, useQuery } from "@tanstack/react-query";
import { History, NotebookPen, Share2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router";
import { get } from "../../api/client";
import { diaryReview, REVIEW_DAYS, type ReviewPanel, type SeriesPoint } from "../../api/diary";
import type { GroupDetail, GroupSummary } from "../../api/types";
import { ROLE_HOME } from "../../app/session";
import { ErrorNotice } from "../../components/Forms";
import { CalendarGrid, Chip, List, ListRow, StatTile } from "../../design";
import { Page } from "../Page";
import { useFocusTime } from "../../app/focusTime";
import { Section } from "../../features/lessons/common";
import { useDateFormat } from "../../features/diary/util";
import { RenderedValues } from "../../features/diary/values";
import "../../features/diary/diary.css";

const HOME = ROLE_HOME.therapist;
const COLORS = [
  "var(--color-lavender)",
  "var(--color-blue)",
  "var(--color-amber)",
  "var(--color-accent-pink)",
  "var(--color-progress)",
  "var(--color-ink-muted)",
];

export function DiaryReviewPage() {
  const { familyId } = useParams();
  return familyId ? <FamilyDiary familyId={familyId} /> : <FamilyPicker />;
}

function FamilyPicker() {
  const { t } = useTranslation();
  const groups = useQuery({ queryKey: ["groups"], queryFn: () => get<GroupSummary[]>("/groups") });
  const details = useQueries({
    queries: (groups.data ?? []).map((g) => ({
      queryKey: ["group", g.id],
      queryFn: () => get<GroupDetail>(`/groups/${g.id}`),
    })),
  });
  return (
    <Page title={t("nav.diaryReview")} subtitle={t("therapist.diary.pick")} icon={<NotebookPen size={22} />}>
      <div className="fb-stack">
        <ErrorNotice error={groups.error} />
        {groups.isSuccess && groups.data.length === 0 && <p>{t("therapist.diary.noGroups")}</p>}
        {details.map((d) =>
          d.data ? (
            <Section key={d.data.id} title={d.data.name}>
              {d.data.families.length === 0 ? (
                <p>{t("therapist.diary.noFamilies")}</p>
              ) : (
                <List label={d.data.name}>
                  {d.data.families.map((f) => (
                    <ListRow
                      key={f.id}
                      icon={<NotebookPen size={20} />}
                      title={f.label}
                      to={`${HOME}/families/${f.id}/diary`}
                    />
                  ))}
                </List>
              )}
            </Section>
          ) : null,
        )}
      </div>
    </Page>
  );
}

function FamilyDiary({ familyId }: { familyId: string }) {
  const { t } = useTranslation();
  useFocusTime(familyId);
  const [days, setDays] = useState<number>(30);
  const q = useQuery({
    queryKey: ["diary-review", familyId, days],
    queryFn: () => diaryReview.family(familyId, days),
  });
  const rangeId = "diary-range";
  return (
    <Page
      title={t("nav.diaryReview")}
      subtitle={t("therapist.diary.subtitle")}
      icon={<NotebookPen size={22} />}
      showBack
    >
      <div className="fb-stack">
        <div className="fb-diary-field">
          <span id={rangeId} className="fb-diary-field__label">
            {t("therapist.diary.range")}
          </span>
          <div className="fb-choice" role="radiogroup" aria-labelledby={rangeId}>
            {REVIEW_DAYS.map((d) => (
              <button
                key={d}
                type="button"
                role="radio"
                aria-checked={days === d}
                className={`fb-choice__option${days === d ? " fb-choice__option--on" : ""}`}
                onClick={() => setDays(d)}
              >
                {t("therapist.diary.days", { n: d })}
              </button>
            ))}
          </div>
        </div>
        <ErrorNotice error={q.error} />
        {q.data && q.data.participants.length === 0 && <p>{t("therapist.diary.noMembers")}</p>}
        <div className="fb-review-panels">
          {q.data?.participants.map((p) => (
            <Panel key={p.user_id} panel={p} from={q.data.from} to={q.data.to} familyId={familyId} />
          ))}
        </div>
      </div>
    </Page>
  );
}

function dayList(from: string, to: string): string[] {
  const out: string[] = [];
  const d = new Date(`${from}T00:00:00Z`);
  const end = new Date(`${to}T00:00:00Z`);
  while (d <= end) {
    out.push(d.toISOString().slice(0, 10));
    d.setUTCDate(d.getUTCDate() + 1);
  }
  return out;
}

function Panel({
  panel,
  from,
  to,
  familyId,
}: {
  panel: ReviewPanel;
  from: string;
  to: string;
  familyId: string;
}) {
  const { t } = useTranslation();
  const { day, time } = useDateFormat();
  const filled = new Set(panel.entries.map((e) => e.entry_date));
  const feelings = panel.series.filter((s) => !s.urge);
  const urges = panel.series.filter((s) => s.urge);
  return (
    <section
      className="fb-card fb-stack"
      aria-label={t("therapist.diary.panel", { alias: panel.alias, role: t(`role.${panel.role}`) })}
      data-testid={`diary-panel-${panel.role}`}
    >
      <h2 className="fb-card__title">
        {panel.alias} <Chip tone="outline">{t(`role.${panel.role}`)}</Chip>
      </h2>
      <div className="fb-actions">
        <StatTile
          icon={<NotebookPen size={18} />}
          value={panel.completion.entries}
          caption={t("therapist.diary.entries")}
        />
        <StatTile
          icon={<NotebookPen size={18} />}
          value={panel.completion.days_with_entries}
          caption={t("therapist.diary.daysWithExpected", {
            n: panel.completion.days,
            expected: panel.completion.expected_days,
            perWeek: panel.completion.days_per_week,
          })}
        />
        <StatTile
          icon={<NotebookPen size={18} />}
          value={panel.skill_use.entries_with_skill}
          caption={t("therapist.diary.withSkill")}
        />
      </div>
      <CalendarGrid
        label={t("therapist.diary.calendar")}
        days={dayList(from, to).map((d) => ({ date: d, filled: filled.has(d) }))}
      />
      {panel.entries.length > 0 && (
        <>
          <TrendChart title={t("therapist.diary.feelings")} series={feelings} from={from} to={to} />
          {urges.length > 0 && (
            <TrendChart title={t("therapist.diary.urges")} series={urges} from={from} to={to} />
          )}
        </>
      )}
      {panel.skill_use.skills.length > 0 && (
        <Section title={t("therapist.diary.skills")}>
          <ul>
            {panel.skill_use.skills.map((s) => (
              <li key={s.skill_id}>{t("therapist.diary.skillCount", { name: s.name, n: s.count })}</li>
            ))}
          </ul>
        </Section>
      )}
      <Section title={t("therapist.diary.entryList")}>
        {panel.entries.length === 0 && <p>{t("therapist.diary.noEntries")}</p>}
        {panel.entries.map((e) => (
          <article key={e.id} className="fb-stack fb-review-entry" data-testid="review-entry">
            <h3 className="fb-card__title">
              {t("diary.entryFor", { date: day(e.entry_date) })} ·{" "}
              {t("diary.savedAt", { time: time(e.recorded_at) })}{" "}
              {e.added_later && <Chip tone="outline">{t("therapist.diary.addedLater")}</Chip>}
            </h3>
            <RenderedValues items={e.items} />
            {e.homework.length > 0 && (
              <p className="fb-setting__hint">
                {t("therapist.diary.homeworkDone", { items: e.homework.join(" · ") })}
              </p>
            )}
            {e.shares.map((s) => (
              <p key={s.id} className="fb-setting__hint">
                <Share2 size={14} aria-hidden />{" "}
                {s.revoked_at
                  ? t("diary.share.revoked", { alias: s.recipient, date: day(s.revoked_at.slice(0, 10)) })
                  : t("diary.share.sharedWith", { alias: s.recipient, date: day(s.created_at.slice(0, 10)) })}
              </p>
            ))}
            {e.revision_no > 1 && <ReviewVersions familyId={familyId} entryId={e.id} n={e.revision_no} />}
          </article>
        ))}
      </Section>
    </section>
  );
}

function ReviewVersions({ familyId, entryId, n }: { familyId: string; entryId: string; n: number }) {
  const { t, i18n } = useTranslation();
  const [open, setOpen] = useState(false);
  const q = useQuery({
    queryKey: ["diary-review", "revisions", entryId, n],
    queryFn: () => diaryReview.revisions(familyId, entryId),
    enabled: open,
  });
  return (
    <details onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary>
        <History size={14} aria-hidden /> {t("diary.versions", { n })}
      </summary>
      <ol>
        {(q.data?.revisions ?? []).map((r) => (
          <li key={r.revision_no}>
            {new Date(r.saved_at).toLocaleString(i18n.language)}:{" "}
            {Object.entries(r.values)
              .map(([k, v]) => `${k}=${Array.isArray(v) ? v.join("+") : String(v)}`)
              .join(", ")}
            {r.note ? ` · ${r.note}` : ""}
          </li>
        ))}
      </ol>
    </details>
  );
}

/** 1–10 lines over the date range. Accessible: summary text and a data table alternative. */
function TrendChart({
  title,
  series,
  from,
  to,
}: {
  title: string;
  series: { field_id: string; label: string; points: SeriesPoint[] }[];
  from: string;
  to: string;
}) {
  const { t } = useTranslation();
  const { day } = useDateFormat();
  const W = 640;
  const H = 220;
  const pad = { l: 32, r: 12, t: 12, b: 28 };
  const t0 = new Date(`${from}T00:00:00Z`).getTime();
  const t1 = new Date(`${to}T23:59:59Z`).getTime();
  const x = (p: SeriesPoint) => {
    const ts = new Date(`${p.date}T00:00:00Z`).getTime() + (new Date(p.at).getUTCHours() / 24) * 86_400_000;
    return pad.l + ((ts - t0) / Math.max(1, t1 - t0)) * (W - pad.l - pad.r);
  };
  const y = (v: number) => pad.t + ((10 - v) / 9) * (H - pad.t - pad.b);
  const shown = series.filter((s) => s.points.length > 0);
  return (
    <figure className="fb-stack" style={{ margin: 0 }}>
      <figcaption className="fb-card__title">{title}</figcaption>
      <svg className="fb-chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={title}>
        {[1, 4, 7, 10].map((v) => (
          <g key={v}>
            <line className="fb-chart__grid" x1={pad.l} x2={W - pad.r} y1={y(v)} y2={y(v)} />
            <text x={pad.l - 8} y={y(v) + 4} textAnchor="end" fontSize="11" fill="currentColor">
              {v}
            </text>
          </g>
        ))}
        <text x={pad.l} y={H - 8} fontSize="11" fill="currentColor">
          {day(from)}
        </text>
        <text x={W - pad.r} y={H - 8} fontSize="11" textAnchor="end" fill="currentColor">
          {day(to)}
        </text>
        {shown.map((s, i) => {
          const color = COLORS[i % COLORS.length];
          const d = s.points
            .map((p, j) => `${j ? "L" : "M"}${x(p).toFixed(1)},${y(p.value).toFixed(1)}`)
            .join(" ");
          return (
            <g key={s.field_id}>
              <path
                className="fb-chart__line"
                d={d}
                stroke={color}
                strokeDasharray={i >= COLORS.length ? "4 3" : undefined}
              />
              {s.points.map((p) => (
                <circle key={p.at} cx={x(p)} cy={y(p.value)} r={3.5} fill={color} />
              ))}
            </g>
          );
        })}
      </svg>
      <ul className="fb-chart__legend">
        {shown.map((s, i) => (
          <li key={s.field_id}>
            <span
              className="fb-chart__swatch"
              style={{ background: COLORS[i % COLORS.length] }}
              aria-hidden
            />
            {s.label}
          </li>
        ))}
      </ul>
      <details>
        <summary>{t("therapist.diary.asTable")}</summary>
        <table className="fb-table">
          <thead>
            <tr>
              <th scope="col">{t("therapist.diary.item")}</th>
              <th scope="col">{t("therapist.diary.values")}</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((s) => (
              <tr key={s.field_id}>
                <th scope="row">{s.label}</th>
                <td>{s.points.map((p) => `${day(p.date)}: ${p.value}`).join("; ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}
