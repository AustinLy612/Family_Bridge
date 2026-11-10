/**
 * Therapist learning review for one family (Plan §5.8; D15). One panel per participant: skills
 * practised with outcomes (and caregiver practice categories), then each lesson with why the
 * skill was chosen, the AI summary, the internal understanding code, test attempts and mood
 * before/after. The participant's own words (check-in answer, chat, practice answers,
 * reflection) are not shown until the therapist opens them for one lesson; each opening is
 * recorded in the audit log.
 */
import { useQuery } from "@tanstack/react-query";
import { BookOpen, FileText } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router";
import {
  therapist,
  type CaregiverRow,
  type LearningPanel,
  type LessonDetail,
  type MasteryRow,
  type TeachingRow,
} from "../../api/therapist";
import { useFocusTime } from "../../app/focusTime";
import { ErrorNotice, Notice } from "../../components/Forms";
import { Chip } from "../../design";
import { useDateFormat } from "../../features/diary/util";
import { Section } from "../../features/lessons/common";
import { Page } from "../Page";
import "./therapist.css";

export function LearningReviewPage() {
  const { t } = useTranslation();
  const { familyId = "" } = useParams();
  useFocusTime(familyId);
  const q = useQuery({
    queryKey: ["learning-review", familyId],
    queryFn: () => therapist.learning(familyId),
  });
  return (
    <Page
      title={q.data?.family.label ?? t("therapist.learning.title")}
      subtitle={t("therapist.learning.subtitle")}
      icon={<BookOpen size={22} />}
      showBack
    >
      <div className="fb-stack">
        <ErrorNotice error={q.error} />
        {q.data?.participants.length === 0 && <p>{t("therapist.diary.noMembers")}</p>}
        <div className="fb-review-panels">
          {q.data?.participants.map((p) => (
            <Panel key={p.user_id} panel={p} familyId={familyId} />
          ))}
        </div>
      </div>
    </Page>
  );
}

function Panel({ panel, familyId }: { panel: LearningPanel; familyId: string }) {
  const { t } = useTranslation();
  return (
    <section
      className="fb-card fb-stack"
      aria-label={t("therapist.diary.panel", { alias: panel.alias, role: t(`role.${panel.role}`) })}
      data-testid={`learning-panel-${panel.role}`}
    >
      <h2 className="fb-card__title">
        {panel.alias} <Chip tone="outline">{t(`role.${panel.role}`)}</Chip>
      </h2>
      <Mastery rows={panel.mastery} caregiver={panel.role === "caregiver"} />
      <Section title={t("therapist.learning.lessons")}>
        {panel.lessons.length === 0 && <p>{t("therapist.learning.noLessons")}</p>}
        {panel.lessons.map((l) =>
          l.kind === "teaching" ? (
            <TeachingLesson key={l.id} lesson={l} familyId={familyId} />
          ) : (
            <CaregiverLesson key={l.id} lesson={l} familyId={familyId} />
          ),
        )}
      </Section>
    </section>
  );
}

function categories(c: Record<string, number>): string {
  return Object.entries(c)
    .map(([k, n]) => `${k} × ${n}`)
    .join(", ");
}

function Mastery({ rows, caregiver }: { rows: MasteryRow[]; caregiver: boolean }) {
  const { t } = useTranslation();
  const { day } = useDateFormat();
  return (
    <Section title={t("therapist.learning.mastery")}>
      {rows.length === 0 ? (
        <p>{t("therapist.learning.noSkills")}</p>
      ) : (
        <table className="fb-table fb-table--left">
          <thead>
            <tr>
              <th scope="col">{t("therapist.progress.skill")}</th>
              <th scope="col">{t("therapist.learning.lessonsDone")}</th>
              <th scope="col">{t("therapist.learning.outcome")}</th>
              {caregiver && <th scope="col">{t("therapist.learning.categories")}</th>}
              <th scope="col">{t("therapist.learning.last")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.skill?.id}>
                <th scope="row">{r.skill?.name}</th>
                <td>{r.lessons_completed}</td>
                <td>{t(`learn.outcome.${r.outcome}`)}</td>
                {caregiver && <td>{categories(r.practice_categories) || "—"}</td>}
                <td>{day(r.last_practised_at.slice(0, 10))}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Section>
  );
}

function LessonHeader({ lesson }: { lesson: TeachingRow | CaregiverRow }) {
  const { t } = useTranslation();
  const { day } = useDateFormat();
  return (
    <h3 className="fb-card__title">
      {lesson.skill?.name ?? t("therapist.learning.noSkill")} · {day(lesson.started_at.slice(0, 10))}{" "}
      <Chip tone="outline">{t(`learn.status.${lesson.status}`)}</Chip>{" "}
      {lesson.source && <Chip tone="outline">{t(`therapist.learning.source.${lesson.source}`)}</Chip>}
    </h3>
  );
}

function TeachingLesson({ lesson, familyId }: { lesson: TeachingRow; familyId: string }) {
  const { t } = useTranslation();
  return (
    <article className="fb-stack fb-review-entry" data-testid="learning-lesson">
      <LessonHeader lesson={lesson} />
      <dl className="fb-diary-values">
        {lesson.recommendation_reason && (
          <>
            <dt>{t("therapist.learning.why")}</dt>
            <dd>{lesson.recommendation_reason}</dd>
          </>
        )}
        <dt>{t("therapist.learning.checkin")}</dt>
        <dd>{t(`therapist.learning.checkinState.${lesson.checkin}`)}</dd>
        <dt>{t("therapist.learning.mood")}</dt>
        <dd>
          {t("therapist.learning.moodValues", {
            before: lesson.mood_before ?? "—",
            after: lesson.mood_after ?? "—",
          })}
        </dd>
        {lesson.understanding && (
          <>
            <dt>{t("therapist.learning.understanding")}</dt>
            <dd>{t(`therapist.learning.understandingCode.${lesson.understanding}`, lesson.understanding)}</dd>
          </>
        )}
        {lesson.tests.length > 0 && (
          <>
            <dt>{t("therapist.learning.tests")}</dt>
            <dd>
              {lesson.tests
                .map((x) =>
                  t("therapist.learning.testRow", {
                    n: x.attempt_no,
                    correct: x.correct,
                    total: x.total,
                    outcome: x.outcome
                      ? t(`therapist.learning.testOutcome.${x.outcome}`)
                      : t(`learn.status.ongoing`),
                  }),
                )
                .join("; ")}
            </dd>
          </>
        )}
      </dl>
      {lesson.summary && (
        <div className="fb-stack">
          <p>{lesson.summary.summary_text}</p>
          {lesson.summary.key_points.length > 0 && (
            <ul>
              {lesson.summary.key_points.map((k) => (
                <li key={k}>{k}</li>
              ))}
            </ul>
          )}
        </div>
      )}
      <OnDemand familyId={familyId} lessonId={lesson.id} />
    </article>
  );
}

function CaregiverLesson({ lesson, familyId }: { lesson: CaregiverRow; familyId: string }) {
  const { t } = useTranslation();
  return (
    <article className="fb-stack fb-review-entry" data-testid="learning-lesson">
      <LessonHeader lesson={lesson} />
      <dl className="fb-diary-values">
        <dt>{t("therapist.learning.quiz")}</dt>
        <dd>
          {t("therapist.learning.quizRow", { correct: lesson.quiz.correct, answered: lesson.quiz.answered })}
          {lesson.quiz.outcome && ` · ${t(`learn.outcome.${lesson.quiz.outcome}`)}`}
        </dd>
        <dt>{t("therapist.learning.categories")}</dt>
        <dd>{categories(lesson.practice_categories) || "—"}</dd>
        <dt>{t("therapist.learning.reflection")}</dt>
        <dd>{t(`therapist.learning.reflectionState.${lesson.reflection}`)}</dd>
      </dl>
      <OnDemand familyId={familyId} lessonId={lesson.id} />
    </article>
  );
}

/** The participant's own words, loaded only when asked for (audited server-side). */
function OnDemand({ familyId, lessonId }: { familyId: string; lessonId: string }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const q = useQuery({
    queryKey: ["learning-review", familyId, "lesson", lessonId],
    queryFn: () => therapist.lesson(familyId, lessonId),
    enabled: open,
    staleTime: Infinity,
  });
  if (!open) {
    return (
      <div className="fb-actions">
        <button type="button" className="fb-btn fb-btn--secondary" onClick={() => setOpen(true)}>
          <FileText size={16} aria-hidden /> {t("therapist.learning.openWords")}
        </button>
        <span className="fb-setting__hint">{t("therapist.learning.auditNote")}</span>
      </div>
    );
  }
  return (
    <div className="fb-share-preview fb-stack" data-testid="lesson-detail">
      <ErrorNotice error={q.error} />
      {q.data && <Detail detail={q.data} />}
    </div>
  );
}

function Detail({ detail }: { detail: LessonDetail }) {
  const { t } = useTranslation();
  if (detail.kind === "caregiver") {
    return (
      <>
        {(detail.practice ?? []).map((p) => (
          <p key={`${p.item}:${p.attempt_no}`}>
            <strong>{t("therapist.learning.practiceItem", { n: p.item, attempt: p.attempt_no })}</strong>{" "}
            {p.answer} <Chip tone="outline">{p.category}</Chip>
          </p>
        ))}
        <p>
          <strong>{t("therapist.learning.reflection")}:</strong> {detail.reflection ?? "—"}
        </p>
      </>
    );
  }
  return (
    <>
      {detail.checkin && (
        <p>
          <strong>{detail.checkin.question}</strong>{" "}
          {detail.checkin.skipped
            ? t("therapist.learning.checkinState.skipped")
            : (detail.checkin.answer ?? "—")}
        </p>
      )}
      {(detail.mood_notes ?? []).map((m, i) => (
        <p key={i}>
          <strong>{t("therapist.learning.moodNote", { value: m.value })}</strong> {m.note}
        </p>
      ))}
      {(detail.messages ?? []).length === 0 && <Notice>{t("therapist.learning.noMessages")}</Notice>}
      <ol className="fb-transcript">
        {(detail.messages ?? []).map((m, i) => (
          <li key={i} className={`fb-transcript__${m.role}`}>
            <strong>{t(`therapist.learning.speaker.${m.role}`, m.role)}:</strong> {m.content}
          </li>
        ))}
      </ol>
    </>
  );
}
