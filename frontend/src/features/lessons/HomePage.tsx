/**
 * Family Bridge overview for participants (D95; was the participant home, Plan §5.13.1): the way
 * into group review (D24), diary cards and joint activities. One-to-one lessons moved to the
 * Personal Learning module and the Portal's shortcut; lessons are never tasks. The only list of things to do is the group's
 * homework (D69), shown read-only: ticking happens in the diary, and nothing is ever "overdue".
 */
import { useQuery } from "@tanstack/react-query";
import { Check, ClipboardList, HeartHandshake, House, NotebookPen, UsersRound } from "lucide-react";
import { useTranslation } from "react-i18next";
import { diary } from "../../api/diary";
import { ROLE_HOME, useSession } from "../../app/session";
import { Chip, HeroBanner, List, ListRow } from "../../design";
import { useDateFormat } from "../diary/util";
import { Page } from "../../routes/Page";

export function HomePage() {
  const { t } = useTranslation();
  const user = useSession();
  const teen = user?.role === "adolescent";
  const home = teen ? ROLE_HOME.adolescent : ROLE_HOME.caregiver;
  if (!user) return null;
  return (
    <Page
      title={t("nav.module.family")}
      subtitle={t("portal.familyHome.subtitle")}
      icon={<House size={22} />}
    >
      <div className="fb-stack">
        <HeroBanner
          title={t("learn.home.hello", { alias: user.displayAlias })}
          body={t(teen ? "portal.familyHome.bodyTeen" : "portal.familyHome.bodyCarer")}
        />
        <List label={t("nav.module.family")}>
          <ListRow
            icon={<UsersRound size={20} aria-hidden />}
            title={t("nav.groupReview")}
            subtitle={t("learn.home.groupHint")}
            to={`${home}/group-review`}
          />
          <ListRow
            icon={<NotebookPen size={20} aria-hidden />}
            title={t("nav.diary")}
            subtitle={t("portal.familyHome.diaryHint")}
            to={`${home}/diary`}
          />
          <ListRow
            icon={<HeartHandshake size={20} aria-hidden />}
            title={t("nav.joint")}
            subtitle={t("joint.subtitle")}
            to={`${home}/joint`}
          />
        </List>
        <Homework home={home} />
      </div>
    </Page>
  );
}

function Homework({ home }: { home: string }) {
  const { t } = useTranslation();
  const { day } = useDateFormat();
  const q = useQuery({ queryKey: ["diary", "my-homework"], queryFn: diary.myHomework });
  const items = q.data?.items ?? [];
  if (items.length === 0) return null;
  return (
    <section className="fb-stack" aria-labelledby="home-homework">
      <h2 id="home-homework" className="fb-card__title">
        {t("homework.title")}
      </h2>
      <p className="fb-setting__hint">{t("homework.hint")}</p>
      <List label={t("homework.title")}>
        {items.map((h) => (
          <ListRow
            key={h.id}
            icon={<ClipboardList size={20} aria-hidden />}
            title={h.title}
            subtitle={[h.details, t("homework.openUntil", { date: day(h.due_on) })]
              .filter(Boolean)
              .join(" · ")}
            trailing={
              h.done ? (
                <Chip tone="outline" icon={<Check size={14} aria-hidden />}>
                  {t("homework.done")}
                </Chip>
              ) : undefined
            }
          />
        ))}
        <ListRow
          icon={<ClipboardList size={20} aria-hidden />}
          title={t("homework.tickInDiary")}
          to={`${home}/diary/new`}
        />
      </List>
    </section>
  );
}
