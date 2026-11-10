/**
 * After-session summary for the therapist (Plan §4.2, §5.8): the shared completion record,
 * rubric-coded outputs per participant, attendance and join location, distress ratings (D76)
 * and private reflections (D77). Opening this page is audited. Partners never see this.
 */
import { useQuery } from "@tanstack/react-query";
import { HeartHandshake } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router";
import { bi, joint, type ParticipantRole } from "../../api/joint";
import { ErrorNotice, Notice } from "../../components/Forms";
import { Chip } from "../../design";
import { Section } from "../../features/lessons/common";
import { Page } from "../Page";
import "../../features/joint/joint.css";
import "./therapist.css";

const ROLES: ParticipantRole[] = ["adolescent", "caregiver"];

export function JointSummaryPage() {
  const { sessionId = "" } = useParams();
  const { t, i18n } = useTranslation();
  const q = useQuery({ queryKey: ["joint-summary", sessionId], queryFn: () => joint.summary(sessionId) });
  const s = q.data;
  const tag = (x: string) => x.replace(/[_-]/g, " ");
  const name = (r: ParticipantRole | null) => (r ? (s?.aliases[r] ?? t(`therapist.joint.role.${r}`)) : "");
  return (
    <Page
      title={s?.episode ? bi(s.episode.title, i18n.language) : t("therapist.joint.summary")}
      subtitle={t("therapist.joint.summarySubtitle")}
      icon={<HeartHandshake size={22} />}
    >
      <div className="fb-stack" data-testid="joint-summary">
        <ErrorNotice error={q.error} />
        <Link to="/therapist/joint">{t("therapist.joint.back")}</Link>
        {s && (
          <>
            <Notice>{t("therapist.joint.audited")}</Notice>
            <Section title={t("therapist.joint.record")}>
              {s.record ? (
                <dl className="fb-joint-reveal">
                  <div>
                    <dt>{t("therapist.joint.outcome")}</dt>
                    <dd>{t(`therapist.joint.outcomes.${s.record.status}`)}</dd>
                  </div>
                  <div>
                    <dt>{t("therapist.joint.stepsDone")}</dt>
                    <dd>
                      {s.record.completed_step_ids.length} / {s.steps.length}
                      {s.record.skipped_step_ids.length > 0 &&
                        ` · ${t("therapist.joint.skipped", { n: s.record.skipped_step_ids.length })}`}
                    </dd>
                  </div>
                  <div>
                    <dt>{t("therapist.joint.sharedTags")}</dt>
                    <dd>
                      {s.record.shared_rubric_tags.map((x) => (
                        <Chip key={x} tone="outline">
                          {tag(x)}
                        </Chip>
                      ))}
                    </dd>
                  </div>
                </dl>
              ) : (
                <p className="fb-setting__hint">{t("therapist.joint.noRecord")}</p>
              )}
            </Section>
            <Section title={t("therapist.joint.rubric")}>
              <table className="fb-joint-table" data-testid="joint-rubric">
                <thead>
                  <tr>
                    <th scope="col">{t("therapist.joint.stepCol")}</th>
                    {ROLES.filter((r) => s.rubric[r]).map((r) => (
                      <th key={r} scope="col">
                        {name(r)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {s.steps
                    .filter((st) => ROLES.some((r) => s.rubric[r]?.[st.id]))
                    .map((st) => (
                      <tr key={st.id}>
                        <th scope="row">{t(`joint.step.${st.type}`)}</th>
                        {ROLES.filter((r) => s.rubric[r]).map((r) => (
                          <td key={r}>{(s.rubric[r]?.[st.id] ?? []).map(tag).join(", ")}</td>
                        ))}
                      </tr>
                    ))}
                </tbody>
              </table>
            </Section>
            <Section title={t("therapist.joint.attendance")}>
              <ul className="fb-joint-past">
                {ROLES.filter((r) => s.responses[r]).map((r) => (
                  <li key={r}>
                    {name(r)}: {t(`therapist.joint.response.${s.responses[r]?.response ?? "none"}`)}
                    {s.responses[r]?.join_location &&
                      ` · ${t(`joint.room.location.${s.responses[r]?.join_location}`)}`}
                  </li>
                ))}
              </ul>
            </Section>
            <Section title={t("therapist.joint.distress")}>
              {s.distress.length === 0 ? (
                <p className="fb-setting__hint">{t("therapist.joint.none")}</p>
              ) : (
                <ul className="fb-joint-past">
                  {s.distress.map((d, i) => (
                    <li key={i}>
                      {name(d.role)}: {d.value ?? t("therapist.joint.skippedOne")}
                    </li>
                  ))}
                </ul>
              )}
            </Section>
            <Section title={t("therapist.joint.reflections")}>
              {s.reflections.length === 0 ? (
                <p className="fb-setting__hint">{t("therapist.joint.none")}</p>
              ) : (
                s.reflections.map((r, i) => (
                  <blockquote key={i} className="fb-joint-composition" data-testid="joint-reflection">
                    <strong>{name(r.role)}</strong>: {r.text}
                    {r.flagged && (
                      <>
                        {" "}
                        <Chip tone="outline">{t("therapist.joint.flagged")}</Chip>
                      </>
                    )}
                  </blockquote>
                ))
              )}
            </Section>
            {s.safety_event_ids.length > 0 && (
              <Section title={t("therapist.joint.safetyEvents")}>
                <ul className="fb-joint-past">
                  {s.safety_event_ids.map((id) => (
                    <li key={id}>
                      <Link to={`/therapist/safety/${id}`}>{t("therapist.joint.openEvent")}</Link>
                    </li>
                  ))}
                </ul>
              </Section>
            )}
          </>
        )}
      </div>
    </Page>
  );
}
