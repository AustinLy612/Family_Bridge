/**
 * Participant home (Plan §5.13.1): continue an open lesson, start learning, and Group review as
 * its own area (D24). Lessons are never tasks. The only list of things to do is the group's
 * homework (D69), shown read-only: ticking happens in the diary, and nothing is ever "overdue".
 */
import { useQuery } from "@tanstack/react-query";
import { BookOpen, Check, ClipboardList, House, UsersRound } from "lucide-react";
import { useTranslation } from "react-i18next";
import { diary } from "../../api/diary";
import { learn } from "../../api/learning";
import { ROLE_HOME, useSession } from "../../app/session";
import { Chip, HeroBanner, List, ListRow } from "../../design";
import { useDateFormat } from "../diary/util";
import { Page } from "../../routes/Page";

export function HomePage() {
  const { t } = useTranslation();
  const user = useSession();
  const teen = user?.role === "adolescent";
  const home = teen ? ROLE_HOME.adolescent : ROLE_HOME.caregiver;
  const current = useQuery({
    queryKey: ["learn", teen ? "current" : "caregiver-current"],
    queryFn: async () => {
      if (teen) {
        const l = (await learn.current()).lesson;
        return l ? { id: l.id, href: `${home}/learn/${l.id}`, skill: l.skill?.name ?? null } : null;
      }
      const l = (await learn.caregiverCurrent()).lesson;
      return l ? { id: l.id, href: `${home}/learn/lesson/${l.id}`, skill: l.skill.name } : null;
    },
    enabled: !!user,
  });
  const open = current.data ?? null;
  if (!user) return null;
  return (
    <Page title={t("nav.home")} icon={<House size={22} />}>
      <div className="fb-stack">
        <HeroBanner
          title={t("learn.home.hello", { alias: user.displayAlias })}
          body={t(teen ? "learn.home.bodyTeen" : "learn.home.bodyCarer")}
        />
        <List label={t("nav.home")}>
          {open && (
            <ListRow
              icon={<BookOpen size={20} aria-hidden />}
              title={t("learn.open.title")}
              subtitle={open.skill ?? undefined}
              to={open.href}
            />
          )}
          <ListRow
            icon={<BookOpen size={20} aria-hidden />}
            title={t(teen ? "nav.learn" : "nav.exploreSkills")}
            subtitle={t(teen ? "learn.home.learnHint" : "learn.home.exploreHint")}
            to={`${home}/learn`}
          />
          <ListRow
            icon={<UsersRound size={20} aria-hidden />}
            title={t("nav.groupReview")}
            subtitle={t("learn.home.groupHint")}
            to={`${home}/group-review`}
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
