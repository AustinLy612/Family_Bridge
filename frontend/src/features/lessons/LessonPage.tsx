/**
 * One adolescent lesson (Plan §5.5.1, D21). The server owns the phase; this screen renders it:
 * mood -> optional check-in (D22) -> recommendation (confirm / alternative / choose another) ->
 * streamed practice conversation -> summary + mood -> optional quick check.
 * Pause is leaving: the lesson stays open (D56). Stop is always there, without penalty.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, Send } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router";
import { ApiError, postStream } from "../../api/client";
import { learn, type Lesson, type LessonOut, type Turn } from "../../api/learning";
import type { ContentSource } from "../../api/types";
import { helpPath, useSafetyOutcome } from "../../app/safety";
import { ROLE_HOME } from "../../app/session";
import { ErrorNotice, Notice, TextAreaField } from "../../components/Forms";
import { PauseControl } from "../../components/Controls";
import { CareCard } from "../../components/Safety";
import { PrimaryButton, SelectCard } from "../../design";
import { Page } from "../../routes/Page";
import { MoodPicker, Section, SourceChip } from "./common";

const HOME = ROLE_HOME.adolescent;

function Conversation({ turns, live }: { turns: Turn[]; live: string | null }) {
  const { t } = useTranslation();
  return (
    <div className="fb-convo" aria-live="polite" aria-label={t("learn.lesson.conversation")}>
      {turns.map((m) => (
        <div key={m.seq} className={`fb-turn fb-turn--${m.role}`}>
          {m.role === "coach" && (
            <span className="fb-turn__meta">
              {t("learn.lesson.coach")} <SourceChip source={m.source} />
            </span>
          )}
          <span>{m.content}</span>
          {m.question && <span className="fb-turn__question">{m.question}</span>}
        </div>
      ))}
      {live !== null && (
        <div className="fb-turn fb-turn--coach" data-testid="live-reply">
          <span className="fb-turn__meta">{t("learn.lesson.coachWriting")}</span>
          <span>{live || "…"}</span>
        </div>
      )}
    </div>
  );
}

function ChooseOther({ onPick }: { onPick: (skillId: string) => void }) {
  const { t } = useTranslation();
  const q = useQuery({ queryKey: ["learn", "skills"], queryFn: learn.skills });
  return (
    <Section title={t("learn.choose.otherTitle")}>
      {(q.data?.modules ?? [])
        .filter((m) => m.id !== "orientation")
        .map((m) => (
          <details key={m.id} className="fb-card">
            <summary className="fb-card__title">{m.name}</summary>
            <div className="fb-skill-grid">
              {m.skills.map((s) => (
                <button key={s.id} type="button" className="fb-option" onClick={() => onPick(s.id)}>
                  {s.name}
                </button>
              ))}
            </div>
          </details>
        ))}
    </Section>
  );
}

export function LessonPage() {
  const { t } = useTranslation();
  const { sessionId = "" } = useParams();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const safety = useSafetyOutcome();
  const q = useQuery({ queryKey: ["learn", "lesson", sessionId], queryFn: () => learn.lesson(sessionId) });
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [checkin, setCheckin] = useState("");
  const [reply, setReply] = useState("");
  const [live, setLive] = useState<string | null>(null);
  const [showOther, setShowOther] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);
  const lesson = q.data?.lesson;

  useEffect(() => {
    bottom.current?.scrollIntoView?.({ block: "end" });
  }, [lesson?.messages.length, live]);

  function apply(out: LessonOut) {
    qc.setQueryData(["learn", "lesson", sessionId], out);
    void qc.invalidateQueries({ queryKey: ["learn", "current"] });
    safety.handle(out.safety);
  }

  async function run(fn: () => Promise<LessonOut>) {
    setError(null);
    setBusy(true);
    try {
      apply(await fn());
    } catch (err) {
      setError(err);
      if (err instanceof ApiError && err.status === 409) void q.refetch();
    } finally {
      setBusy(false);
    }
  }

  async function send(e: FormEvent) {
    e.preventDefault();
    const text = reply.trim();
    if (!text || !lesson) return;
    setError(null);
    setBusy(true);
    setLive("");
    const optimistic: Turn = { seq: -1, role: "student", content: text, question: null, source: null };
    qc.setQueryData<LessonOut>(["learn", "lesson", sessionId], (old) =>
      old ? { ...old, lesson: { ...old.lesson, messages: [...old.lesson.messages, optimistic] } } : old,
    );
    setReply("");
    let stopped = false;
    try {
      await postStream(`/learn/sessions/${sessionId}/messages`, { message: text }, (ev) => {
        if (ev.event === "delta") {
          const sep = lesson.language === "zh-CN" ? "" : " ";
          setLive((s) => `${s ?? ""}${s ? sep : ""}${String(ev.data.text ?? "")}`);
        } else if (ev.event === "replace") setLive("");
        else if (ev.event === "safety") {
          const action = ev.data.action as "stop" | "care_card";
          if (action === "stop") stopped = true;
          safety.handle(action);
        } else if (ev.event === "error") setError(new ApiError(500, String(ev.data.code ?? "unknown")));
      });
    } catch (err) {
      setError(err);
    } finally {
      setLive(null);
      setBusy(false);
      if (!stopped) await q.refetch();
    }
  }

  if (!lesson) {
    return (
      <Page title={t("nav.learn")} icon={<BookOpen size={22} />} showBack>
        <ErrorNotice error={q.error} />
      </Page>
    );
  }

  const open = lesson.status === "ongoing";
  const title = lesson.skill?.name ?? t("learn.lesson.title");
  return (
    <Page
      title={title}
      subtitle={lesson.skill?.module}
      icon={<BookOpen size={22} />}
      showBack
      headerPills={open ? <PauseControl /> : undefined}
    >
      <div className="fb-stack">
        <ErrorNotice error={error} />
        {safety.careCard && <CareCard helpHref={helpPath("adolescent")} onDismiss={safety.dismissCareCard} />}
        {!open && <ClosedNotice lesson={lesson} />}
        {open && phase()}
        {(lesson.phase === "summary" || lesson.phase === "done" || !open) && lesson.summary && (
          <Summary lesson={lesson} />
        )}
        {(!open || lesson.phase === "done") && lesson.messages.length > 0 && (
          <details className="fb-card">
            <summary className="fb-card__title">{t("learn.lesson.transcript")}</summary>
            <Conversation turns={lesson.messages} live={null} />
          </details>
        )}
        {lesson.status === "completed" && testEntry(lesson)}
        {open && (
          <div className="fb-actions">
            <Link className="fb-btn fb-btn--secondary" to={`${HOME}/learn`}>
              {t("learn.lesson.saveExit")}
            </Link>
            <button
              type="button"
              className="fb-btn fb-btn--secondary"
              disabled={busy}
              onClick={() => void run(() => learn.stop(sessionId))}
            >
              {t("learn.lesson.stop")}
            </button>
          </div>
        )}
        <div ref={bottom} />
      </div>
    </Page>
  );

  // Plain render helpers (not components), so inputs keep focus across re-renders.
  function phase() {
    if (!lesson) return null;
    switch (lesson.phase) {
      case "pre_mood_recording":
        return (
          <MoodPicker
            title={t("learn.mood.before")}
            submitLabel={t("learn.next")}
            busy={busy}
            onSubmit={(v, note) => void run(() => learn.mood(sessionId, v, note))}
          />
        );
      case "personal_inquiry":
        return (
          <form
            className="fb-card fb-form"
            onSubmit={(e) => {
              e.preventDefault();
              void run(() => learn.checkin(sessionId, checkin.trim() || null));
            }}
          >
            <span className="fb-turn__meta">
              {t("learn.lesson.coach")} <SourceChip source={lesson.checkin?.source} />
            </span>
            <p>{lesson.checkin?.greeting}</p>
            <TextAreaField
              label={lesson.checkin?.question ?? ""}
              hint={t("learn.checkin.hint")}
              value={checkin}
              maxLength={500}
              onChange={(e) => setCheckin(e.target.value)}
            />
            <div className="fb-actions">
              <PrimaryButton type="submit" disabled={busy || !checkin.trim()}>
                {t("learn.checkin.share")}
              </PrimaryButton>
              <button
                type="button"
                className="fb-btn fb-btn--secondary"
                disabled={busy}
                onClick={() => void run(() => learn.checkin(sessionId, null))}
              >
                {t("learn.checkin.skip")}
              </button>
              <button
                type="button"
                className="fb-btn fb-btn--secondary"
                disabled={busy}
                onClick={() => void run(() => learn.checkin(sessionId, null))}
              >
                {t("learn.checkin.pickForMe")}
              </button>
            </div>
          </form>
        );
      case "skill_selection": {
        const rec = lesson.recommendation;
        if (!rec) return null;
        return (
          <div className="fb-stack">
            <div className="fb-card fb-stack">
              <span className="fb-turn__meta">
                {t("learn.choose.suggested")} <SourceChip source={rec.source} />
              </span>
              <h2 className="fb-card__title">{rec.skill.name}</h2>
              <p className="fb-setting__hint">{rec.skill.module}</p>
              <p>{rec.reason}</p>
              <PrimaryButton
                disabled={busy}
                onClick={() => void run(() => learn.choose(sessionId, rec.skill.id, "recommended"))}
              >
                {t("learn.choose.confirm")}
              </PrimaryButton>
            </div>
            {rec.alternatives.length > 0 && (
              <Section title={t("learn.choose.alternatives")}>
                <div className="fb-select-grid">
                  {rec.alternatives.map((a) => (
                    <SelectCard
                      key={a.id}
                      title={a.name}
                      caption={a.module}
                      selected={false}
                      onSelect={() => void run(() => learn.choose(sessionId, a.id, "alternative"))}
                    />
                  ))}
                </div>
              </Section>
            )}
            {showOther ? (
              <ChooseOther onPick={(id) => void run(() => learn.choose(sessionId, id, "chosen"))} />
            ) : (
              <button type="button" className="fb-btn fb-btn--secondary" onClick={() => setShowOther(true)}>
                {t("learn.choose.other")}
              </button>
            )}
          </div>
        );
      }
      case "rag_retrieval_for_teaching":
        return <Notice>{t("learn.lesson.preparing")}</Notice>;
      case "teaching":
        return (
          <div className="fb-stack">
            {lesson.plan.length > 0 && (
              <details className="fb-card">
                <summary className="fb-card__title">
                  {t("learn.lesson.plan")} <SourceChip source={lesson.plan_source} />
                </summary>
                <ol className="fb-plan">
                  {lesson.plan.map((p, i) => (
                    <li key={i}>{p.title}</li>
                  ))}
                </ol>
              </details>
            )}
            <Conversation turns={lesson.messages} live={live} />
            <form className="fb-card fb-form" onSubmit={(e) => void send(e)}>
              <TextAreaField
                label={t("learn.lesson.reply")}
                value={reply}
                maxLength={500}
                onChange={(e) => setReply(e.target.value)}
              />
              <div className="fb-actions">
                <PrimaryButton
                  type="submit"
                  disabled={busy || !reply.trim()}
                  icon={<Send size={18} aria-hidden />}
                >
                  {t("learn.lesson.send")}
                </PrimaryButton>
                <button
                  type="button"
                  className="fb-btn fb-btn--secondary"
                  disabled={busy}
                  onClick={() => void run(() => learn.end(sessionId))}
                >
                  {t("learn.lesson.end")}
                </button>
              </div>
            </form>
          </div>
        );
      case "summary":
        return (
          <MoodPicker
            title={t("learn.mood.after")}
            submitLabel={t("learn.lesson.finish")}
            busy={busy}
            onSubmit={(v, note) => void run(() => learn.postMood(sessionId, v, note))}
          />
        );
      default:
        return null;
    }
  }

  function testEntry(l: Lesson) {
    const last = l.tests[l.tests.length - 1];
    const pending = last && (last.status === "generating" || last.status === "ready");
    return (
      <div className="fb-card fb-stack">
        <h2 className="fb-card__title">{t("learn.test.title")}</h2>
        <p>{t("learn.test.intro")}</p>
        {l.tests
          .filter((x) => x.outcome)
          .map((x) => (
            <p key={x.id} className="fb-setting__hint">
              {t("learn.test.attempt", { n: x.attempt_no })} · {t(`learn.test.outcome.${x.outcome}`)}
            </p>
          ))}
        <PrimaryButton
          disabled={busy}
          onClick={() =>
            void (async () => {
              setError(null);
              try {
                const out = pending ? { test: last } : await learn.startTest(l.id);
                navigate(`${HOME}/learn/tests/${out.test.id}`);
              } catch (err) {
                setError(err);
              }
            })()
          }
        >
          {pending
            ? t("learn.test.continue")
            : l.tests.length
              ? t("learn.test.again")
              : t("learn.test.start")}
        </PrimaryButton>
      </div>
    );
  }
}

function Summary({ lesson }: { lesson: Lesson }) {
  const { t } = useTranslation();
  const s = lesson.summary;
  if (!s) return null;
  return (
    <div className="fb-card fb-stack" data-testid="lesson-summary">
      <span className="fb-turn__meta">
        {t("learn.summary.title")} <SourceChip source={s.source as ContentSource | null} />
      </span>
      <p>{s.summary_text}</p>
      {s.key_points.length > 0 && (
        <>
          <h3>{t("learn.summary.keyIdeas")}</h3>
          <ul className="fb-plan">
            {s.key_points.map((k, i) => (
              <li key={i}>{k}</li>
            ))}
          </ul>
        </>
      )}
      {s.recommendations.length > 0 && (
        <>
          <h3>{t("learn.summary.tryNext")}</h3>
          <ul className="fb-plan">
            {s.recommendations.map((k, i) => (
              <li key={i}>{k}</li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

function ClosedNotice({ lesson }: { lesson: Lesson }) {
  const { t, i18n } = useTranslation();
  const when = new Date(lesson.started_at).toLocaleDateString(i18n.language);
  return <Notice>{t(`learn.closed.${lesson.status}`, { date: when })}</Notice>;
}
