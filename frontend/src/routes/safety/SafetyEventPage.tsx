/**
 * One safety event (Plan §5.7): what triggered it, the status workflow
 * (new → acknowledged → in review → resolved, with follow-up), and clinician notes.
 * Therapists of the family's group can act; admins read only (D39). Every view is audited.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ShieldAlert } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router";
import { get, post } from "../../api/client";
import type { SafetyEventDetail, SafetyStatus } from "../../api/types";
import { useSession } from "../../app/session";
import { ErrorNotice, Notice, TextAreaField } from "../../components/Forms";
import { Chip, PrimaryButton } from "../../design";
import { Page } from "../Page";
import { SeverityChip, StatusChip } from "./format";
import { useDateTime } from "./time";

const ACTION_KEY: Record<SafetyStatus, string> = {
  new: "",
  acknowledged: "safety.action.acknowledge",
  in_review: "safety.action.review",
  resolved: "safety.action.resolve",
};

function Actions({ event }: { event: SafetyEventDetail }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [followUp, setFollowUp] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function run(fn: () => Promise<SafetyEventDetail>) {
    setError(null);
    setBusy(true);
    try {
      const d = await fn();
      qc.setQueryData(["safety", "event", event.id], d);
      await qc.invalidateQueries({ queryKey: ["safety", "events"] });
      return true;
    } catch (err) {
      setError(err);
      return false;
    } finally {
      setBusy(false);
    }
  }

  const move = (status: SafetyStatus) =>
    run(() =>
      post<SafetyEventDetail>(`/safety/events/${event.id}/status`, {
        status,
        follow_up: status === "resolved" ? followUp.trim() : null,
      }),
    );

  async function addNote(e: FormEvent) {
    e.preventDefault();
    if (await run(() => post<SafetyEventDetail>(`/safety/events/${event.id}/notes`, { body: note.trim() })))
      setNote("");
  }

  const canResolve = event.next_statuses.includes("resolved");
  const steps = event.next_statuses.filter((s) => s !== "resolved");
  return (
    <>
      {event.next_statuses.length > 0 && (
        <section className="fb-card" aria-labelledby="actions-title">
          <h2 id="actions-title" className="fb-card__title">
            {t("safety.nextStep")}
          </h2>
          <div className="fb-stack">
            {steps.length > 0 && (
              <div className="fb-actions">
                {steps.map((s) => (
                  <PrimaryButton key={s} disabled={busy} onClick={() => void move(s)}>
                    {t(ACTION_KEY[s])}
                  </PrimaryButton>
                ))}
              </div>
            )}
            {canResolve && (
              <form
                className="fb-form"
                noValidate
                onSubmit={(e) => {
                  e.preventDefault();
                  void move("resolved").then((ok) => ok && setFollowUp(""));
                }}
              >
                <TextAreaField
                  label={t("safety.followUp")}
                  hint={t("safety.followUpHint")}
                  value={followUp}
                  maxLength={4000}
                  onChange={(e) => setFollowUp(e.target.value)}
                />
                <div className="fb-actions">
                  <PrimaryButton type="submit" variant="secondary" disabled={busy || !followUp.trim()}>
                    {t(ACTION_KEY.resolved)}
                  </PrimaryButton>
                </div>
              </form>
            )}
          </div>
        </section>
      )}
      <ErrorNotice error={error} />
      <section className="fb-card" aria-labelledby="note-title">
        <h2 id="note-title" className="fb-card__title">
          {t("safety.addNote")}
        </h2>
        <form className="fb-form" onSubmit={addNote} noValidate>
          <TextAreaField
            label={t("safety.note")}
            hint={t("safety.noteHint")}
            value={note}
            maxLength={4000}
            onChange={(e) => setNote(e.target.value)}
          />
          <div className="fb-actions">
            <PrimaryButton type="submit" variant="secondary" disabled={busy || !note.trim()}>
              {t("safety.saveNote")}
            </PrimaryButton>
          </div>
        </form>
      </section>
    </>
  );
}

export function SafetyEventPage() {
  const { t } = useTranslation();
  const { eventId = "" } = useParams();
  const user = useSession();
  const when = useDateTime();
  const q = useQuery({
    queryKey: ["safety", "event", eventId],
    queryFn: () => get<SafetyEventDetail>(`/safety/events/${eventId}`),
  });
  const e = q.data;
  const isAdmin = user?.role === "admin";
  const person = (p: { alias: string; role: string } | null) =>
    p ? `${p.alias} (${t(`role.${p.role}`)})` : t("safety.nobody");

  return (
    <Page
      title={e ? t(`safety.category.${e.category}`) : t("nav.safetyQueue")}
      subtitle={e ? `${person(e.subject)} · ${e.family?.label ?? ""}` : undefined}
      icon={<ShieldAlert size={22} />}
      showBack
    >
      <div className="fb-stack">
        <ErrorNotice error={q.error} />
        {isAdmin && <Notice>{t("safety.readOnlyNotice")}</Notice>}
        {e && (
          <>
            <section className="fb-card" aria-labelledby="event-title">
              <h2 id="event-title" className="fb-card__title">
                {t("safety.overview")}
              </h2>
              <div className="fb-row__chips">
                <SeverityChip severity={e.severity} />
                <StatusChip status={e.status} />
                {e.activity_stopped && <Chip tone="outline">{t("safety.activityStopped")}</Chip>}
              </div>
              <dl className="fb-dl">
                <dt>{t("safety.sourceLabel")}</dt>
                <dd>{t(`safety.source.${e.source}`)}</dd>
                <dt>{t("safety.channelLabel")}</dt>
                <dd>{t(`safety.channel.${e.channel}`)}</dd>
                <dt>{t("safety.raisedAt")}</dt>
                <dd>{when(e.created_at)}</dd>
                {e.occurrences > 1 && (
                  <>
                    <dt>{t("safety.timesFlagged")}</dt>
                    <dd>{e.occurrences}</dd>
                  </>
                )}
                <dt>{t("safety.assignee")}</dt>
                <dd>{person(e.assignee)}</dd>
                {e.created_by && (
                  <>
                    <dt>{t("safety.recordedBy")}</dt>
                    <dd>{person(e.created_by)}</dd>
                  </>
                )}
                {e.family && (
                  <>
                    <dt>{t("safety.group")}</dt>
                    <dd>{e.family.group_name}</dd>
                  </>
                )}
              </dl>
            </section>

            <section className="fb-card" aria-labelledby="excerpt-title">
              <h2 id="excerpt-title" className="fb-card__title">
                {t(e.source === "manual" ? "safety.description" : "safety.excerpt")}
              </h2>
              <p className="fb-setting__hint">{t("safety.excerptPrivacy")}</p>
              {e.excerpt ? (
                <blockquote className="fb-excerpt">{e.excerpt}</blockquote>
              ) : (
                <p>{t(`safety.noExcerpt.${e.category === "urge_threshold" ? "urge" : "other"}`)}</p>
              )}
              {e.matched_terms.length > 0 && (
                <p>
                  {t("safety.matched")}{" "}
                  {e.matched_terms.map((term) => (
                    <Chip key={term} tone="outline">
                      {term}
                    </Chip>
                  ))}
                </p>
              )}
            </section>

            <section className="fb-card" aria-labelledby="timeline-title">
              <h2 id="timeline-title" className="fb-card__title">
                {t("safety.timeline")}
              </h2>
              <ol className="fb-timeline">
                {e.timeline.map((item) => (
                  <li key={item.status}>
                    <strong>{t(`safety.status.${item.status}`)}</strong> · {when(item.at)}
                  </li>
                ))}
              </ol>
              {e.follow_up && (
                <>
                  <h3>{t("safety.followUp")}</h3>
                  <p>{e.follow_up}</p>
                  <p className="fb-setting__hint">{person(e.resolved_by)}</p>
                </>
              )}
            </section>

            {e.notes.length > 0 && (
              <section className="fb-card" aria-labelledby="notes-title">
                <h2 id="notes-title" className="fb-card__title">
                  {t("safety.notes")}
                </h2>
                <ul className="fb-notes">
                  {e.notes.map((n) => (
                    <li key={n.id}>
                      <p>{n.body}</p>
                      <span className="fb-setting__hint">
                        {person(n.author)} · {when(n.created_at)}
                      </span>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {!isAdmin && <Actions event={e} />}
          </>
        )}
      </div>
    </Page>
  );
}
