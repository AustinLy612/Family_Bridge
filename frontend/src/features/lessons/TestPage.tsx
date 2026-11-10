/**
 * Quick check after a lesson (Plan §5.5.1 step 7): questions are generated in the background
 * (status poll), answered one at a time with an explanation. The end says "You've got it" or
 * "Worth another look" — never a score or "fail" (§5.13.3). Retakes are always allowed.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ClipboardCheck } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router";
import { learn, type SkillTest } from "../../api/learning";
import { useSafetyOutcome } from "../../app/safety";
import { ROLE_HOME } from "../../app/session";
import { ErrorNotice, Notice } from "../../components/Forms";
import { PrimaryButton, ProgressBar } from "../../design";
import { Page } from "../../routes/Page";
import { MoodPicker, SourceChip } from "./common";

const HOME = ROLE_HOME.adolescent;

export function TestPage() {
  const { t } = useTranslation();
  const { testId = "" } = useParams();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const safety = useSafetyOutcome();
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [shown, setShown] = useState<number | null>(null); // question whose feedback is showing
  const key = ["learn", "test", testId];
  const q = useQuery({
    queryKey: key,
    queryFn: () => learn.test(testId),
    refetchInterval: (query) => (query.state.data?.test.status === "generating" ? 1500 : false),
  });
  const test = q.data?.test;

  function set(next: SkillTest) {
    qc.setQueryData(key, { test: next });
  }

  async function answer(position: number, index: number) {
    setError(null);
    setBusy(true);
    try {
      const out = await learn.answer(testId, position, index);
      set(out.test);
      setShown(position);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  if (!test) {
    return (
      <Page title={t("learn.test.title")} icon={<ClipboardCheck size={22} />} showBack>
        <ErrorNotice error={q.error} />
      </Page>
    );
  }

  const lessonHref = `${HOME}/learn/${test.session_id}`;
  const answered = test.questions.filter((x) => x.answer_index !== null).length;
  const current =
    shown !== null
      ? test.questions.find((x) => x.position === shown)
      : test.questions.find((x) => x.answer_index === null);

  return (
    <Page
      title={t("learn.test.title")}
      subtitle={t("learn.test.attempt", { n: test.attempt_no })}
      icon={<ClipboardCheck size={22} />}
      showBack
    >
      <div className="fb-stack">
        <ErrorNotice error={error} />
        {test.status === "generating" && <Notice>{t("learn.test.generating")}</Notice>}
        {test.status === "unavailable" && <Notice tone="warn">{t("learn.test.unavailable")}</Notice>}
        {test.status === "user_terminated" && <Notice>{t("learn.test.stopped")}</Notice>}

        {/* The last answer completes the test; keep its explanation on screen until "Next". */}
        {(test.status === "ready" || (test.status === "completed" && shown !== null)) && current && (
          <div className="fb-card fb-stack" data-testid="test-question">
            <ProgressBar current={answered} total={test.questions.length} />
            <span className="fb-turn__meta">
              {t("learn.test.question", { n: current.position, total: test.questions.length })}{" "}
              <SourceChip source={test.source} />
            </span>
            <p>{current.scenario}</p>
            <h2 className="fb-card__title">{current.question}</h2>
            <div className="fb-options" role="group" aria-label={current.question}>
              {current.options.map((o, i) => {
                const done = current.answer_index !== null;
                const cls = !done
                  ? ""
                  : i === current.correct_index
                    ? " fb-option--right"
                    : i === current.answer_index
                      ? " fb-option--chosen"
                      : "";
                return (
                  <button
                    key={i}
                    type="button"
                    className={`fb-option${cls}`}
                    disabled={done || busy}
                    onClick={() => void answer(current.position, i)}
                  >
                    {o}
                  </button>
                );
              })}
            </div>
            {current.answer_index !== null && (
              <div className="fb-stack" aria-live="polite">
                <p className="fb-card__title">
                  {current.is_correct ? t("learn.test.right") : t("learn.test.notQuite")}
                </p>
                <p>{current.explanation}</p>
                <PrimaryButton onClick={() => setShown(null)}>{t("learn.next")}</PrimaryButton>
              </div>
            )}
          </div>
        )}

        {test.status === "completed" && shown === null && (
          <div className="fb-stack">
            <div className="fb-card fb-stack" data-testid="test-outcome">
              <h2 className="fb-card__title">{t(`learn.test.outcome.${test.outcome}`)}</h2>
              <p>{t(`learn.test.outcomeBody.${test.outcome}`)}</p>
              <div className="fb-actions">
                <PrimaryButton
                  variant={test.outcome === "got_it" ? "secondary" : "primary"}
                  disabled={busy}
                  onClick={() =>
                    void (async () => {
                      setError(null);
                      try {
                        const out = await learn.startTest(test.session_id);
                        setShown(null);
                        navigate(`${HOME}/learn/tests/${out.test.id}`);
                      } catch (err) {
                        setError(err);
                      }
                    })()
                  }
                >
                  {t("learn.test.again")}
                </PrimaryButton>
                <Link className="fb-btn fb-btn--secondary" to={lessonHref}>
                  {t("learn.test.backToLesson")}
                </Link>
              </div>
            </div>
            {!test.mood_recorded && (
              <MoodPicker
                title={t("learn.mood.afterTest")}
                submitLabel={t("learn.mood.save")}
                busy={busy}
                onSubmit={(v, note) =>
                  void (async () => {
                    setError(null);
                    try {
                      const out = await learn.testMood(testId, v, note);
                      set(out.test);
                      safety.handle(out.safety);
                    } catch (err) {
                      setError(err);
                    }
                  })()
                }
              />
            )}
          </div>
        )}

        {(test.status === "ready" || test.status === "generating") && (
          <div className="fb-actions">
            <Link className="fb-btn fb-btn--secondary" to={lessonHref}>
              {t("learn.lesson.saveExit")}
            </Link>
            <button
              type="button"
              className="fb-btn fb-btn--secondary"
              onClick={() =>
                void learn
                  .stopTest(testId)
                  .then((out) => set(out.test))
                  .catch(setError)
              }
            >
              {t("learn.test.stop")}
            </button>
          </div>
        )}
      </div>
    </Page>
  );
}
