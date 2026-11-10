/** Caregiver "Explore skills" (Plan §5.5.2 step 1): taxonomy by module, past lessons, progress. */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";
import { learn } from "../../api/learning";
import { ROLE_HOME } from "../../app/session";
import { ErrorNotice } from "../../components/Forms";
import { Page } from "../../routes/Page";
import { HistorySection, OpenLessonCard, ProgressSection, Section } from "./common";

const HOME = ROLE_HOME.caregiver;

export function ExplorePage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const skills = useQuery({ queryKey: ["learn", "skills"], queryFn: learn.skills });
  const current = useQuery({ queryKey: ["learn", "caregiver-current"], queryFn: learn.caregiverCurrent });
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const open = current.data?.lesson ?? null;

  async function start(skillId: string) {
    setError(null);
    setBusy(true);
    try {
      const out = await learn.caregiverStart(skillId);
      await qc.invalidateQueries({ queryKey: ["learn"] });
      navigate(`${HOME}/learn/lesson/${out.lesson.id}`);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function closeOpen() {
    if (!open) return;
    try {
      await learn.caregiverStop(open.id);
      await qc.invalidateQueries({ queryKey: ["learn"] });
    } catch (err) {
      setError(err);
    }
  }

  return (
    <Page title={t("nav.exploreSkills")} subtitle={t("learn.explore.subtitle")} icon={<BookOpen size={22} />}>
      <div className="fb-stack">
        <ErrorNotice error={error ?? skills.error} />
        {open && (
          <OpenLessonCard
            skillName={open.skill.name}
            href={`${HOME}/learn/lesson/${open.id}`}
            onClose={() => void closeOpen()}
          />
        )}
        <Section title={t("learn.explore.title")}>
          {(skills.data?.modules ?? [])
            .filter((m) => m.id !== "orientation")
            .map((m) => (
              <details key={m.id} className="fb-card">
                <summary className="fb-card__title">{m.name}</summary>
                <div className="fb-skill-grid">
                  {m.skills.map((s) => (
                    <button
                      key={s.id}
                      type="button"
                      className="fb-option"
                      disabled={busy || !!open}
                      onClick={() => void start(s.id)}
                    >
                      {s.name}
                    </button>
                  ))}
                </div>
              </details>
            ))}
        </Section>
        <ProgressSection />
        <HistorySection hrefFor={(h) => `${HOME}/learn/lesson/${h.id}`} />
      </div>
    </Page>
  );
}
