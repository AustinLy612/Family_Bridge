/**
 * Caregiver structured lesson (Plan §5.5.2): explain (with "simpler" / "another example") ->
 * guided practice (second opportunity) -> quick check -> wrap-up with an optional, private
 * reflection. Every step can be skipped; leaving keeps the lesson open (D56).
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router";
import { ApiError } from "../../api/client";
import { learn, type CaregiverLesson, type CaregiverOut, type Feedback } from "../../api/learning";
import { helpPath, useSafetyOutcome } from "../../app/safety";
import { ROLE_HOME } from "../../app/session";
import { ErrorNotice, Notice, TextAreaField } from "../../components/Forms";
import { PauseControl } from "../../components/Controls";
import { CareCard } from "../../components/Safety";
import { PrimaryButton, ProgressBar } from "../../design";
import { Page } from "../../routes/Page";
import { OutcomeChip, SourceChip } from "./common";

const HOME = ROLE_HOME.caregiver;
const STEPS = ["explain", "practice", "quiz", "wrap_up"] as const;

function FeedbackCard({ fb }: { fb: Feedback }) {
  const { t } = useTranslation();
  return (
    <div className="fb-stack" aria-live="polite">
      <p>
        <strong>{t("learn.cg.whatWorked")}</strong> {fb.what_worked}
      </p>
      {fb.why && (
        <p>
          <strong>{t("learn.cg.why")}</strong> {fb.why}
        </p>
      )}
      {fb.try_next && (
        <p>
          <strong>{t("learn.cg.tryNext")}</strong> {fb.try_next}
        </p>
      )}
    </div>
  );
}

export function CaregiverLessonPage() {
  const { t } = useTranslation();
  const { lessonId = "" } = useParams();
  const qc = useQueryClient();
  const safety = useSafetyOutcome();
  const key = ["learn", "cg", lessonId];
  const q = useQuery({ queryKey: key, queryFn: () => learn.caregiverLesson(lessonId) });
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [texts, setTexts] = useState<Record<number, string>>({});
  const [reflection, setReflection] = useState("");
  const lesson = q.data?.lesson;

  async function run(fn: () => Promise<CaregiverOut>) {
    setError(null);
    setBusy(true);
    try {
      const out = await fn();
      qc.setQueryData(key, out);
      void qc.invalidateQueries({ queryKey: ["learn", "caregiver-current"] });
      safety.handle(out.safety);
    } catch (err) {
      setError(err);
      if (err instanceof ApiError && err.status === 409) void q.refetch();
    } finally {
      setBusy(false);
    }
  }

  if (!lesson) {
    return (
      <Page title={t("nav.exploreSkills")} icon={<BookOpen size={22} />} showBack>
        <ErrorNotice error={q.error} />
      </Page>
    );
  }

  const open = lesson.status === "ongoing";
  const stepIndex = Math.max(0, STEPS.indexOf(lesson.step as (typeof STEPS)[number]));
  const next = (from: "explain" | "practice" | "quiz") => run(() => learn.next(lessonId, from));

  return (
    <Page
      title={lesson.skill.name}
      subtitle={lesson.skill.module}
      icon={<BookOpen size={22} />}
      showBack
      headerPills={open ? <PauseControl /> : undefined}
    >
      <div className="fb-stack">
        <ErrorNotice error={error} />
        {safety.careCard && <CareCard helpHref={helpPath("caregiver")} onDismiss={safety.dismissCareCard} />}
        {open && <ProgressBar current={stepIndex + 1} total={STEPS.length} tone="lavender" />}
        {!open && (
          <Notice>
            {t(`learn.closed.${lesson.status}`, {
              date: new Date(lesson.started_at).toLocaleDateString(),
            })}
          </Notice>
        )}
        {lesson.outcome && (
          <p>
            <OutcomeChip outcome={lesson.outcome} />
          </p>
        )}

        {(lesson.step === "explain" || !open) && explain(lesson)}
        {(lesson.step === "practice" || (!open && lesson.practice)) && practice(lesson)}
        {(lesson.step === "quiz" || (!open && lesson.quiz)) && quiz(lesson)}
        {open && lesson.step === "wrap_up" && wrapUp(lesson)}
        {!open && lesson.reflection && (
          <div className="fb-card fb-stack">
            <h2 className="fb-card__title">{t("learn.cg.reflectionTitle")}</h2>
            <p>{lesson.reflection}</p>
          </div>
        )}

        {open && (
          <div className="fb-actions">
            <Link className="fb-btn fb-btn--secondary" to={`${HOME}/learn`}>
              {t("learn.lesson.saveExit")}
            </Link>
            <button
              type="button"
              className="fb-btn fb-btn--secondary"
              disabled={busy}
              onClick={() => void run(() => learn.caregiverStop(lessonId))}
            >
              {t("learn.lesson.stop")}
            </button>
          </div>
        )}
      </div>
    </Page>
  );

  function explain(l: CaregiverLesson) {
    const ex = l.explanation;
    if (!ex) return null;
    return (
      <div className="fb-card fb-stack" data-testid="cg-explain">
        <span className="fb-turn__meta">
          {t("learn.cg.explainTitle")} <SourceChip source={ex.source} />
        </span>
        <p>{ex.summary}</p>
        {ex.key_points.length > 0 && (
          <ul className="fb-plan">
            {ex.key_points.map((k, i) => (
              <li key={i}>{k}</li>
            ))}
          </ul>
        )}
        {ex.everyday_example && (
          <p>
            <strong>{t("learn.cg.example")}</strong> {ex.everyday_example}
          </p>
        )}
        {ex.check_question && <p className="fb-turn__question">{ex.check_question}</p>}
        {ex.references.length > 0 && (
          <>
            <p className="fb-setting__hint">{t("learn.cg.basedOn")}</p>
            <ul className="fb-refs">
              {ex.references.map((r, i) => (
                <li key={i}>
                  {r.module} · {r.handout ? `${r.handout}. ` : ""}
                  {r.title}
                </li>
              ))}
            </ul>
          </>
        )}
        {open && l.step === "explain" && (
          <div className="fb-actions">
            <PrimaryButton onClick={() => void next("explain")} disabled={busy}>
              {t("learn.cg.toPractice")}
            </PrimaryButton>
            <button
              type="button"
              className="fb-btn fb-btn--secondary"
              disabled={busy}
              onClick={() => void run(() => learn.adapt(lessonId, "simpler"))}
            >
              {t("learn.cg.simpler")}
            </button>
            <button
              type="button"
              className="fb-btn fb-btn--secondary"
              disabled={busy}
              onClick={() => void run(() => learn.adapt(lessonId, "another_example"))}
            >
              {t("learn.cg.anotherExample")}
            </button>
          </div>
        )}
      </div>
    );
  }

  function practice(l: CaregiverLesson) {
    const p = l.practice;
    if (!p) return null;
    const live = open && l.step === "practice";
    return (
      <div className="fb-stack" data-testid="cg-practice">
        <span className="fb-turn__meta">
          {t("learn.cg.practiceTitle")} <SourceChip source={p.source} />
        </span>
        <p className="fb-setting__hint">{t("learn.cg.practiceHint")}</p>
        {p.items.map((it, i) => {
          const last = it.attempts[it.attempts.length - 1];
          const canAnswer = live && (it.attempts.length === 0 || it.can_retry);
          return (
            <div key={i} className="fb-card fb-stack">
              <p>{it.scenario}</p>
              <h3>{it.prompt}</h3>
              {it.answer_mode === "choice" ? (
                <div className="fb-options">
                  {it.options.map((o, oi) => (
                    <button
                      key={oi}
                      type="button"
                      className={`fb-option${last?.answer === o ? " fb-option--chosen" : ""}`}
                      disabled={!canAnswer || busy}
                      onClick={() => void run(() => learn.practise(lessonId, i, { option_index: oi }))}
                    >
                      {o}
                    </button>
                  ))}
                </div>
              ) : (
                <>
                  {it.attempts.map((a) => (
                    <p key={a.attempt_no} className="fb-turn fb-turn--student">
                      {a.answer}
                    </p>
                  ))}
                  {canAnswer && (
                    <form
                      className="fb-form"
                      onSubmit={(e) => {
                        e.preventDefault();
                        const text = (texts[i] ?? "").trim();
                        if (!text) return;
                        void run(() => learn.practise(lessonId, i, { text })).then(() =>
                          setTexts((s) => ({ ...s, [i]: "" })),
                        );
                      }}
                    >
                      <TextAreaField
                        label={t("learn.cg.yourAnswer")}
                        hint={t("learn.cg.noPersonal")}
                        value={texts[i] ?? ""}
                        maxLength={500}
                        onChange={(e) => setTexts((s) => ({ ...s, [i]: e.target.value }))}
                      />
                      <PrimaryButton
                        type="submit"
                        variant="secondary"
                        disabled={busy || !(texts[i] ?? "").trim()}
                      >
                        {t("learn.cg.check")}
                      </PrimaryButton>
                    </form>
                  )}
                </>
              )}
              {last && <FeedbackCard fb={last.feedback} />}
              {live && last && it.can_retry && (
                <p className="fb-setting__hint">{t("learn.cg.tryAgainHint")}</p>
              )}
            </div>
          );
        })}
        {live && (
          <PrimaryButton onClick={() => void next("practice")} disabled={busy}>
            {t("learn.cg.toQuiz")}
          </PrimaryButton>
        )}
      </div>
    );
  }

  function quiz(l: CaregiverLesson) {
    const z = l.quiz;
    if (!z) return null;
    const live = open && l.step === "quiz";
    return (
      <div className="fb-stack" data-testid="cg-quiz">
        <span className="fb-turn__meta">
          {t("learn.cg.quizTitle")} <SourceChip source={z.source} />
        </span>
        {z.questions.map((qq, i) => (
          <div key={i} className="fb-card fb-stack">
            <h3>{qq.stem}</h3>
            <div className="fb-options">
              {qq.options.map((o, oi) => {
                const done = qq.answer_index !== null;
                const cls = !done
                  ? ""
                  : oi === qq.correct_index
                    ? " fb-option--right"
                    : oi === qq.answer_index
                      ? " fb-option--chosen"
                      : "";
                return (
                  <button
                    key={oi}
                    type="button"
                    className={`fb-option${cls}`}
                    disabled={done || !live || busy}
                    onClick={() => void run(() => learn.quiz(lessonId, i, oi))}
                  >
                    {o}
                  </button>
                );
              })}
            </div>
            {qq.answer_index !== null && (
              <p aria-live="polite">
                <strong>{qq.is_correct ? t("learn.test.right") : t("learn.test.notQuite")}</strong>{" "}
                {qq.explanation}
              </p>
            )}
          </div>
        ))}
        {live && (
          <PrimaryButton onClick={() => void next("quiz")} disabled={busy}>
            {t("learn.cg.toWrapUp")}
          </PrimaryButton>
        )}
      </div>
    );
  }

  function wrapUp(l: CaregiverLesson) {
    return (
      <form
        className="fb-card fb-form"
        data-testid="cg-wrapup"
        onSubmit={(e) => {
          e.preventDefault();
          void run(() => learn.finish(lessonId, reflection.trim() || null));
        }}
      >
        <h2 className="fb-card__title">{t("learn.cg.wrapUpTitle")}</h2>
        {l.explanation && l.explanation.key_points.length > 0 && (
          <ul className="fb-plan">
            {l.explanation.key_points.map((k, i) => (
              <li key={i}>{k}</li>
            ))}
          </ul>
        )}
        <TextAreaField
          label={t("learn.cg.reflection")}
          hint={t("learn.cg.reflectionHint")}
          value={reflection}
          maxLength={500}
          onChange={(e) => setReflection(e.target.value)}
        />
        <div className="fb-actions">
          <PrimaryButton type="submit" disabled={busy}>
            {t("learn.cg.finish")}
          </PrimaryButton>
          <button
            type="button"
            className="fb-btn fb-btn--secondary"
            disabled={busy}
            onClick={() => void run(() => learn.finish(lessonId, null))}
          >
            {t("learn.cg.skipFinish")}
          </button>
        </div>
      </form>
    );
  }
}
