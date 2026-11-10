/**
 * Joint room (Plan §5.9; Phase 8 task 6): a plain, accessible shell for every step type. Art and
 * storybook layout come with the real scripts (O1, O18). Neutral copy throughout: no time limits,
 * no reasons asked, contribution indicators instead of scores.
 * - Pause (header, always on screen) pauses the room for both; either can carry on.
 * - "I need to stop" pauses the room, opens Help, and only the therapist picks it up (D75).
 * - Leave ends the session for both with neutral copy.
 */
import { useQuery } from "@tanstack/react-query";
import { HeartHandshake } from "lucide-react";
import { useEffect, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router";
import { bi, joint, type ParticipantRole, type RoomView, type StepView } from "../../api/joint";
import { setRoomPause } from "../../app/roomPause";
import { useSafetyOutcome } from "../../app/safety";
import { ROLE_HOME, useSession } from "../../app/session";
import { ErrorNotice, Notice, TextAreaField } from "../../components/Forms";
import { CareCard } from "../../components/Safety";
import { Chip, PrimaryButton, ProgressBar } from "../../design";
import { Page } from "../../routes/Page";
import { ChoiceGroup } from "../../routes/therapist/common";
import { useRoom } from "./useRoom";
import "./joint.css";

type Send = ReturnType<typeof useRoom>["send"];

export function RoomPage() {
  const { sessionId = "" } = useParams();
  const { t, i18n } = useTranslation();
  const lang = i18n.language;
  const user = useSession();
  const home = user?.role === "caregiver" ? ROLE_HOME.caregiver : ROLE_HOME.adolescent;
  const info = useQuery({ queryKey: ["joint", "one", sessionId], queryFn: () => joint.one(sessionId) });
  const safety = useSafetyOutcome();
  const [location, setLocation] = useState<string | null>(null);
  const room = useRoom(sessionId, { onSafety: (a) => safety.handle(a), location });
  const [error, setError] = useState<string | null>(null);
  const view = room.view;

  const act = async (a: Parameters<Send>[0]) => {
    setError(null);
    const r = await room.send(a);
    if (!r.ok) setError(r.code ?? "unknown");
  };

  // the header Pause control pauses the room while the room is live
  const live = view && (view.phase === "running" || view.phase === "lobby");
  const send = room.send;
  useEffect(() => {
    setRoomPause(live ? () => void send({ type: "pause" }) : null);
    return () => setRoomPause(null);
  }, [live, send]);

  const ep = info.data?.episode;
  return (
    <Page
      title={ep ? bi(ep.title, lang) : t("nav.joint")}
      subtitle={view?.solo ? t("joint.solo.title") : t("joint.room.subtitle")}
      icon={<HeartHandshake size={22} />}
      visibility={{ kind: "therapist" }}
    >
      <div className="fb-stack fb-joint-room" data-testid="joint-room">
        <ErrorNotice error={info.error} />
        {safety.careCard && <CareCard helpHref={`${home}/help`} onDismiss={safety.dismissCareCard} />}
        {(error || room.error) && (
          <Notice tone="warn">{t(`apiErrors.${error ?? room.error}`, t("joint.room.tryAgain"))}</Notice>
        )}
        {room.conn === "reconnecting" && <Notice>{t("joint.room.reconnecting")}</Notice>}
        {room.conn === "closed" && !view && (
          <Notice>
            {t("joint.room.cannotJoin")} <Link to={`${home}/joint`}>{t("joint.room.back")}</Link>
          </Notice>
        )}
        {view && <Presence view={view} />}
        {view && view.phase !== "lobby" && view.step_count > 0 && (
          <div aria-label={t("joint.room.progress", { n: view.step_index + 1, total: view.step_count })}>
            <ProgressBar current={Math.min(view.step_index, view.step_count)} total={view.step_count} />
          </div>
        )}
        {view?.phase === "lobby" && (
          <Lobby
            view={view}
            minutes={ep?.estimated_minutes}
            objective={bi(ep?.objective, lang)}
            location={location}
            onLocation={(l) => {
              setLocation(l);
              room.join(l);
            }}
            onReady={() => void act({ type: "ready" })}
          />
        )}
        {view?.phase === "paused" && <Paused view={view} onResume={() => void act({ type: "resume" })} />}
        {view?.phase === "running" && view.step && <Step step={view.step} view={view} act={act} />}
        {view?.phase === "completed" && (
          <section className="fb-card fb-stack" role="status">
            <h2 className="fb-card__title">{t(view.solo ? "joint.room.doneSolo" : "joint.room.done")}</h2>
            <Link to={`${home}/joint`}>{t("joint.room.back")}</Link>
          </section>
        )}
        {view?.phase === "ended" && (
          <section className="fb-card fb-stack" role="status">
            <h2 className="fb-card__title">{t("joint.room.ended")}</h2>
            <p>{t("joint.room.endedBody")}</p>
            <Link to={`${home}/joint`}>{t("joint.room.back")}</Link>
          </section>
        )}
        {view && (view.phase === "running" || view.phase === "lobby" || view.phase === "paused") && (
          <RoomControls solo={view.solo} act={act} />
        )}
      </div>
    </Page>
  );
}

function Presence({ view }: { view: RoomView }) {
  const { t } = useTranslation();
  if (view.solo || view.phase === "completed" || view.phase === "ended") return null;
  return (
    <p className="fb-joint-presence" role="status" data-testid="partner-presence">
      {view.partner_present ? t("joint.room.partnerHere") : t("joint.room.partnerAway")}
    </p>
  );
}

function Lobby({
  view,
  minutes,
  objective,
  location,
  onLocation,
  onReady,
}: {
  view: RoomView;
  minutes?: number;
  objective: string;
  location: string | null;
  onLocation: (l: string) => void;
  onReady: () => void;
}) {
  const { t } = useTranslation();
  return (
    <section className="fb-card fb-stack" aria-labelledby="joint-lobby">
      <h2 id="joint-lobby" className="fb-card__title">
        {t("joint.room.lobby")}
      </h2>
      {objective && <p>{objective}</p>}
      {minutes ? <p className="fb-setting__hint">{t("joint.minutes", { n: minutes })}</p> : null}
      <p>{t("joint.canStop")}</p>
      {!view.solo && (
        <ChoiceGroup
          label={t("joint.room.where")}
          options={["hospital", "remote"] as const}
          value={(location ?? "") as "hospital" | "remote"}
          onChange={onLocation}
          format={(l) => t(`joint.room.location.${l}`)}
        />
      )}
      {view.ready.me ? (
        <p role="status">{view.solo ? "" : t("joint.room.waitingPartner")}</p>
      ) : (
        <div>
          <PrimaryButton onClick={onReady}>{t("joint.room.ready")}</PrimaryButton>
        </div>
      )}
    </section>
  );
}

function Paused({ view, onResume }: { view: RoomView; onResume: () => void }) {
  const { t } = useTranslation();
  return (
    <section className="fb-card fb-stack" role="status" data-testid="room-paused">
      <h2 className="fb-card__title">{t(view.pause === "hold" ? "joint.room.held" : "joint.room.paused")}</h2>
      <p>
        {t(
          view.pause === "hold"
            ? "joint.room.heldBody"
            : view.solo
              ? "joint.room.pausedSolo"
              : "joint.room.pausedBody",
        )}
      </p>
      {view.pause === "pause" && (
        <div>
          <PrimaryButton onClick={onResume}>{t("joint.room.resume")}</PrimaryButton>
        </div>
      )}
    </section>
  );
}

function RoomControls({ solo, act }: { solo: boolean; act: (a: Parameters<Send>[0]) => Promise<void> }) {
  const { t } = useTranslation();
  const [confirm, setConfirm] = useState(false);
  return (
    <div className="fb-joint-controls">
      <PrimaryButton variant="secondary" onClick={() => void act({ type: "stop" })}>
        {t("joint.room.needStop")}
      </PrimaryButton>
      {confirm ? (
        <span className="fb-joint-confirm" role="group" aria-label={t("joint.room.leaveConfirm")}>
          <span>{t(solo ? "joint.room.leaveConfirmSolo" : "joint.room.leaveConfirm")}</span>
          <PrimaryButton variant="secondary" onClick={() => void act({ type: "leave" })}>
            {t("joint.room.leaveYes")}
          </PrimaryButton>
          <PrimaryButton variant="secondary" onClick={() => setConfirm(false)}>
            {t("joint.room.leaveNo")}
          </PrimaryButton>
        </span>
      ) : (
        <PrimaryButton variant="secondary" onClick={() => setConfirm(true)}>
          {t("joint.room.leave")}
        </PrimaryButton>
      )}
    </div>
  );
}

// --- steps ------------------------------------------------------------------------------

function Step({
  step,
  view,
  act,
}: {
  step: StepView;
  view: RoomView;
  act: (a: Parameters<Send>[0]) => Promise<void>;
}) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language;
  const headingId = useId();
  const submit = (value?: unknown) => act({ type: "submit", step_id: step.id, value });
  const reviewing = step.phase === "review";
  const done = !!step.my_act;
  return (
    <section
      className="fb-card fb-stack"
      aria-labelledby={headingId}
      data-testid="joint-step"
      data-step={step.id}
    >
      <h2 id={headingId} className="fb-card__title">
        {step.title ? bi(step.title, lang) : t(`joint.step.${step.type}`)}
      </h2>
      <p className="fb-joint-text">{bi(step.text, lang)}</p>
      {step.hints.map((h, i) => (
        <Notice key={i}>{bi(h, lang)}</Notice>
      ))}
      <StepBody step={step} me={view.me} submit={submit} />
      {done ? (
        <p role="status" className="fb-setting__hint">
          {view.solo
            ? ""
            : step.partner_acted
              ? t("joint.room.bothDone")
              : t(
                  reviewing || step.type === "narration" || step.type === "feedback"
                    ? "joint.room.waitingNext"
                    : "joint.room.waitingChoice",
                )}
        </p>
      ) : (
        !view.solo && step.partner_acted && <p className="fb-setting__hint">{t("joint.room.partnerDone")}</p>
      )}
      {!done && (
        <div className="fb-joint-actions">
          {step.hints_left > 0 && (
            <PrimaryButton variant="secondary" onClick={() => void act({ type: "hint", step_id: step.id })}>
              {t("joint.room.hint")}
            </PrimaryButton>
          )}
          {step.skippable && (
            <PrimaryButton variant="secondary" onClick={() => void act({ type: "skip", step_id: step.id })}>
              {t("joint.room.skip")}
            </PrimaryButton>
          )}
        </div>
      )}
      {step.type === "distress_check" && !done && (
        <DistressScale onPick={(v) => void act({ type: "distress", step_id: step.id, value: v })} />
      )}
    </section>
  );
}

function StepBody({
  step,
  me,
  submit,
}: {
  step: StepView;
  me: ParticipantRole;
  submit: (v?: unknown) => Promise<void>;
}) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language;
  const done = !!step.my_act;
  switch (step.type) {
    case "narration":
      return done ? null : <Continue onClick={() => void submit()} />;
    case "distress_check":
      return <p className="fb-setting__hint">{t("joint.room.distressPrivate")}</p>;
    case "private_choice":
      if (step.phase === "review") {
        return (
          <>
            <Revealed step={step} me={me} />
            {!done && <Continue onClick={() => void submit()} />}
          </>
        );
      }
      return (
        <>
          {step.prompt && <p>{bi(step.prompt, lang)}</p>}
          <p className="fb-setting__hint">{t("joint.room.choicePrivate")}</p>
          <Choose
            options={step.options ?? []}
            chosen={step.my_choice}
            disabled={done}
            onChoose={(id) => void submit(id)}
          />
        </>
      );
    case "transfer_probe":
      return (
        <>
          <Choose
            options={step.options ?? []}
            chosen={step.my_choice}
            disabled={done}
            onChoose={(id) => void submit(id)}
          />
          {step.my_feedback && <Notice>{bi(step.my_feedback, lang)}</Notice>}
        </>
      );
    case "cooperative_compose":
      return <Compose step={step} onSubmit={(ids) => void submit(ids)} />;
    case "retry":
      if (step.phase === "review") {
        return (
          <>
            <Composition step={step} me={me} />
            {!done && <Continue onClick={() => void submit()} />}
          </>
        );
      }
      return <Compose step={step} onSubmit={(ids) => void submit(ids)} />;
    case "feedback":
      return (
        <>
          <Composition step={step} me={me} />
          {!done && <Continue onClick={() => void submit()} />}
        </>
      );
    case "private_reflection":
      return <Reflection step={step} onSave={(text) => void submit(text)} />;
  }
}

function Continue({ onClick }: { onClick: () => void }) {
  const { t } = useTranslation();
  return (
    <div>
      <PrimaryButton onClick={onClick}>{t("joint.room.continue")}</PrimaryButton>
    </div>
  );
}

function Choose({
  options,
  chosen,
  disabled,
  onChoose,
}: {
  options: { id: string; text: { "zh-CN": string; en: string } }[];
  chosen?: string | null;
  disabled: boolean;
  onChoose: (id: string) => void;
}) {
  const { t, i18n } = useTranslation();
  const [pick, setPick] = useState<string | null>(null);
  const value = chosen ?? pick;
  return (
    <div className="fb-stack">
      <div className="fb-joint-options" role="radiogroup" aria-label={t("joint.room.options")}>
        {options.map((o) => (
          <button
            key={o.id}
            type="button"
            role="radio"
            aria-checked={value === o.id}
            disabled={disabled}
            className={`fb-option${value === o.id ? " fb-option--on" : ""}`}
            onClick={() => setPick(o.id)}
          >
            {bi(o.text, i18n.language)}
          </button>
        ))}
      </div>
      {!disabled && (
        <div>
          <PrimaryButton disabled={!pick} onClick={() => pick && onChoose(pick)}>
            {t("joint.room.choose")}
          </PrimaryButton>
        </div>
      )}
    </div>
  );
}

function Revealed({ step, me }: { step: StepView; me: ParticipantRole }) {
  const { t, i18n } = useTranslation();
  const r = step.revealed ?? {};
  return (
    <dl className="fb-joint-reveal" data-testid="joint-reveal">
      {(["adolescent", "caregiver"] as const).map((role) => {
        const item = r[role];
        if (!item) return null;
        return (
          <div key={role}>
            <dt>{role === me ? t("joint.room.you") : t("joint.room.partner")}</dt>
            <dd>
              {item.text ? bi(item.text, i18n.language) : (item.rubric_tag ?? "").replace(/[_-]/g, " ")}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}

function Compose({ step, onSubmit }: { step: StepView; onSubmit: (ids: string[]) => void }) {
  const { t, i18n } = useTranslation();
  const [picked, setPicked] = useState<string[]>([]);
  const rules = step.rules ?? { min_per_role: 1, max_per_role: 3 };
  const done = !!step.my_act;
  const mine = step.my_fragments ?? picked;
  const toggle = (id: string) =>
    setPicked((p) =>
      p.includes(id) ? p.filter((x) => x !== id) : p.length < rules.max_per_role ? [...p, id] : p,
    );
  return (
    <div className="fb-stack">
      <p className="fb-setting__hint">
        {t("joint.room.composeRule", { min: rules.min_per_role, max: rules.max_per_role })}
      </p>
      <div className="fb-joint-options" role="group" aria-label={t("joint.room.pieces")}>
        {(step.fragments ?? []).map((f) => (
          <button
            key={f.id}
            type="button"
            aria-pressed={mine.includes(f.id)}
            disabled={done}
            className={`fb-option${mine.includes(f.id) ? " fb-option--on" : ""}`}
            onClick={() => toggle(f.id)}
          >
            {bi(f.text, i18n.language)}
          </button>
        ))}
      </div>
      {typeof step.partner_count === "number" && step.partner_count > 0 && (
        <p className="fb-setting__hint">{t("joint.room.partnerPieces", { count: step.partner_count })}</p>
      )}
      {!done && (
        <div>
          <PrimaryButton
            disabled={picked.length < Math.max(1, rules.min_per_role)}
            onClick={() => onSubmit(picked)}
          >
            {t("joint.room.addPieces")}
          </PrimaryButton>
        </div>
      )}
    </div>
  );
}

function Composition({ step, me }: { step: StepView; me: ParticipantRole }) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language;
  const pieces = step.composition ?? [];
  return (
    <div className="fb-stack" data-testid="joint-feedback">
      {pieces.length > 0 && (
        <blockquote className="fb-joint-composition">
          {pieces.map((p) => (
            <span key={p.id}>
              {bi(p.text, lang)}{" "}
              {p.by.map((r) => (
                <Chip key={r} tone="outline">
                  {r === me ? t("joint.room.you") : t("joint.room.partner")}
                </Chip>
              ))}{" "}
            </span>
          ))}
        </blockquote>
      )}
      {step.feedback && (
        <>
          <h3 className="fb-card__title">{bi(step.feedback.title, lang)}</h3>
          <p>{bi(step.feedback.text, lang)}</p>
          {step.feedback.notes.length > 0 && (
            <ul>
              {step.feedback.notes.map((n, i) => (
                <li key={i}>{bi(n, lang)}</li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}

function Reflection({ step, onSave }: { step: StepView; onSave: (text: string) => void }) {
  const { t } = useTranslation();
  const [text, setText] = useState("");
  if (step.my_act) return <p className="fb-setting__hint">{t("joint.room.reflectionSaved")}</p>;
  return (
    <div className="fb-stack">
      <TextAreaField
        label={t("joint.room.reflection")}
        value={text}
        onChange={(e) => setText(e.target.value)}
        maxLength={step.max_chars}
        hint={t("joint.room.reflectionPrivate")}
      />
      <div>
        <PrimaryButton disabled={!text.trim()} onClick={() => onSave(text)}>
          {t("joint.room.save")}
        </PrimaryButton>
      </div>
    </div>
  );
}

function DistressScale({ onPick }: { onPick: (v: number) => void }) {
  const { t } = useTranslation();
  const id = useId();
  return (
    <div className="fb-diary-field">
      <span id={id} className="fb-diary-field__label">
        {t("joint.room.distress")}
      </span>
      <div className="fb-choice" role="radiogroup" aria-labelledby={id}>
        {Array.from({ length: 11 }, (_, v) => (
          <button
            key={v}
            type="button"
            role="radio"
            aria-checked={false}
            className="fb-choice__option"
            onClick={() => onPick(v)}
          >
            {v}
          </button>
        ))}
      </div>
    </div>
  );
}
