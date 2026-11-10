/** Adolescent "Learn": start or continue a lesson, past lessons, progress (Plan §5.5.1; D56/D57). */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router";
import { ROLE_HOME } from "../../app/session";
import { learn } from "../../api/learning";
import { ErrorNotice } from "../../components/Forms";
import { HeroBanner, PrimaryButton } from "../../design";
import { Page } from "../../routes/Page";
import { HistorySection, OpenLessonCard, ProgressSection } from "./common";

const HOME = ROLE_HOME.adolescent;

export function LearnPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const profile = useQuery({ queryKey: ["learn", "profile"], queryFn: learn.profile });
  const current = useQuery({ queryKey: ["learn", "current"], queryFn: learn.current });
  const open = current.data?.lesson ?? null;

  async function startLesson() {
    setError(null);
    setBusy(true);
    try {
      const out = await learn.start();
      await qc.invalidateQueries({ queryKey: ["learn"] });
      navigate(`${HOME}/learn/${out.lesson.id}`);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function closeOpen() {
    if (!open) return;
    setError(null);
    try {
      await learn.stop(open.id);
      await qc.invalidateQueries({ queryKey: ["learn"] });
    } catch (err) {
      setError(err);
    }
  }

  const needsProfile = profile.isSuccess && profile.data.profile === null;
  return (
    <Page title={t("nav.learn")} subtitle={t("learn.subtitle")} icon={<BookOpen size={22} />}>
      <div className="fb-stack">
        <ErrorNotice error={error ?? current.error ?? profile.error} />
        {needsProfile ? (
          <HeroBanner
            title={t("learn.profileFirst.title")}
            body={t("learn.profileFirst.body")}
            action={
              <Link className="fb-btn fb-btn--primary" to={`${HOME}/profile`}>
                {t("learn.profileFirst.action")}
              </Link>
            }
          />
        ) : open ? (
          <OpenLessonCard
            skillName={open.skill?.name ?? null}
            href={`${HOME}/learn/${open.id}`}
            onClose={() => void closeOpen()}
          />
        ) : (
          <HeroBanner
            title={t("learn.start.title")}
            body={t("learn.start.body")}
            action={
              <PrimaryButton onClick={() => void startLesson()} disabled={busy || !profile.isSuccess}>
                {t("learn.start.action")}
              </PrimaryButton>
            }
          />
        )}
        <ProgressSection />
        <HistorySection hrefFor={(h) => `${HOME}/learn/${h.id}`} />
      </div>
    </Page>
  );
}
