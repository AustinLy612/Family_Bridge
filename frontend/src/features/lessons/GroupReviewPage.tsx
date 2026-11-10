/**
 * Group review (Plan §5.5.3, D24): skills from your group's sessions. Optional — no due dates,
 * no completion marks, no reminders. Opening a skill starts a lesson with that skill fixed.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { UsersRound } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";
import { ApiError } from "../../api/client";
import { learn } from "../../api/learning";
import { ROLE_HOME, useSession } from "../../app/session";
import { ErrorNotice, Notice } from "../../components/Forms";
import { Page } from "../../routes/Page";
import { OpenLessonCard, Section } from "./common";

export function GroupReviewPage() {
  const { t, i18n } = useTranslation();
  const user = useSession();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const teen = user?.role === "adolescent";
  const home = teen ? ROLE_HOME.adolescent : ROLE_HOME.caregiver;
  const q = useQuery({ queryKey: ["learn", "group-review"], queryFn: learn.groupReview });
  const [error, setError] = useState<unknown>(null);
  const [blocked, setBlocked] = useState<{ id: string; skill: string | null } | null>(null);

  async function open(recordId: string, skillId: string) {
    setError(null);
    setBlocked(null);
    try {
      if (teen) {
        const out = await learn.start({ group_record_id: recordId, skill_id: skillId });
        navigate(`${home}/learn/${out.lesson.id}`);
      } else {
        const out = await learn.caregiverStart(skillId, recordId);
        navigate(`${home}/learn/lesson/${out.lesson.id}`);
      }
      await qc.invalidateQueries({ queryKey: ["learn"] });
    } catch (err) {
      if (err instanceof ApiError && err.code === "lesson.open_exists") {
        if (teen) {
          const cur = await learn.current();
          if (cur.lesson) setBlocked({ id: cur.lesson.id, skill: cur.lesson.skill?.name ?? null });
        } else {
          const cur = await learn.caregiverCurrent();
          if (cur.lesson) setBlocked({ id: cur.lesson.id, skill: cur.lesson.skill.name });
        }
      } else if (err instanceof ApiError && err.code === "lesson.profile_required") {
        navigate(`${home}/profile`);
      } else setError(err);
    }
  }

  async function closeBlocked() {
    if (!blocked) return;
    try {
      if (teen) await learn.stop(blocked.id);
      else await learn.caregiverStop(blocked.id);
      setBlocked(null);
      await qc.invalidateQueries({ queryKey: ["learn"] });
    } catch (err) {
      setError(err);
    }
  }

  const records = q.data?.records ?? [];
  return (
    <Page title={t("nav.groupReview")} subtitle={t("learn.group.subtitle")} icon={<UsersRound size={22} />}>
      <div className="fb-stack">
        <ErrorNotice error={error ?? q.error} />
        {blocked && (
          <OpenLessonCard
            skillName={blocked.skill}
            href={teen ? `${home}/learn/${blocked.id}` : `${home}/learn/lesson/${blocked.id}`}
            onClose={() => void closeBlocked()}
          />
        )}
        <Notice>{t("learn.group.optional")}</Notice>
        {q.isSuccess && records.length === 0 && <p>{t("learn.group.empty")}</p>}
        {records.map((r) => (
          <Section
            key={r.id}
            title={t("learn.group.session", {
              date: new Date(r.session_date).toLocaleDateString(i18n.language),
            })}
          >
            <div className="fb-skill-grid">
              {r.skills.map((s) => (
                <button key={s.id} type="button" className="fb-option" onClick={() => void open(r.id, s.id)}>
                  <strong>{s.name}</strong>
                  <br />
                  <span className="fb-setting__hint">{s.module}</span>
                </button>
              ))}
            </div>
          </Section>
        ))}
      </div>
    </Page>
  );
}
