/**
 * Unified Portal (D95): the shared landing page for every role after sign-in. It shows the
 * account's own details and links to profile/settings, and opens each functional module
 * (Family Bridge, Personal Learning, Administration). It only links to existing screens; it adds
 * no new data, counts or prompts (no streaks, scores or "to do" pressure).
 */
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, BookOpen, LayoutGrid, Settings, ShieldCheck, UserRound } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link, Navigate } from "react-router";
import { learn } from "../api/learning";
import { ACCOUNT, MODULES, SHARED, isParticipant, moduleHref, navHref, type NavModule } from "../app/nav";
import { ROLE_HOME, landingFor, useSessionControls, type Role } from "../app/session";
import { Chip, HeroBanner, List, ListRow } from "../design";
import { Page } from "./Page";
import "./portal.css";

const TONES = ["lavender", "amber", "blue"] as const;

/** An unfinished lesson, offered as a shortcut on the Personal Learning card. */
function useOpenLesson(role: Role) {
  const teen = role === "adolescent";
  const home = ROLE_HOME[role];
  return useQuery({
    queryKey: ["learn", teen ? "current" : "caregiver-current"],
    queryFn: async () => {
      if (teen) {
        const l = (await learn.current()).lesson;
        return l ? { href: `${home}/learn/${l.id}`, skill: l.skill?.name ?? null } : null;
      }
      const l = (await learn.caregiverCurrent()).lesson;
      return l ? { href: `${home}/learn/lesson/${l.id}`, skill: l.skill.name } : null;
    },
    enabled: isParticipant(role),
  });
}

function ModuleCard({ role, module, tone }: { role: Role; module: NavModule; tone: string }) {
  const { t } = useTranslation();
  const Icon = module.icon;
  const open = useOpenLesson(role);
  const lesson = module.id === "learning" ? (open.data ?? null) : null;
  const titleId = `portal-module-${module.id}`;
  return (
    <section className={`portal-module portal-module--${tone}`} aria-labelledby={titleId}>
      <div className="portal-module__head">
        <span className="fb-icon-tile" aria-hidden>
          <Icon size={22} />
        </span>
        <h3 id={titleId} className="portal-module__title">
          {t(`nav.module.${module.id}`)}
        </h3>
      </div>
      <p className="portal-module__body">{t(`portal.modules.${module.id}.${role}`)}</p>
      <ul className="portal-module__features" aria-label={t("portal.includes")}>
        {module.items.map((item) => (
          <li key={item.key}>
            <Link to={navHref(role, item)} className="fb-chip portal-module__feature">
              {t(`nav.${item.key}`)}
            </Link>
          </li>
        ))}
      </ul>
      <div className="portal-module__actions">
        <Link to={moduleHref(role, module)} className="fb-btn fb-btn--primary">
          {t("portal.enter", { module: t(`nav.module.${module.id}`) })}
          <ArrowRight size={18} aria-hidden />
        </Link>
        {lesson && (
          <Link to={lesson.href} className="fb-btn fb-btn--secondary">
            <BookOpen size={18} aria-hidden />
            {t("portal.continueLesson")}
          </Link>
        )}
      </div>
    </section>
  );
}

export function PortalPage() {
  const { t } = useTranslation();
  const { user, loading } = useSessionControls();
  if (loading) return null;
  if (!user) return <Navigate to="/" replace />;
  if (landingFor(user) === "/onboarding") return <Navigate to="/onboarding" replace />;
  const role = user.role;
  const home = ROLE_HOME[role];
  const participant = isParticipant(role);
  return (
    <Page title={t("nav.portal")} subtitle={t("portal.subtitle")} icon={<LayoutGrid size={22} />}>
      <div className="fb-stack">
        <HeroBanner title={t("portal.hello", { alias: user.displayAlias })} body={t("portal.body")} />

        <section className="fb-stack" aria-labelledby="portal-modules">
          <h2 id="portal-modules" className="fb-card__title">
            {t("portal.modulesTitle")}
          </h2>
          <div className="portal-modules">
            {MODULES[role].map((m, i) => (
              <ModuleCard key={m.id} role={role} module={m} tone={TONES[i % TONES.length] ?? "lavender"} />
            ))}
          </div>
          <List label={t("portal.alwaysHere")}>
            {SHARED[role].map((item) => {
              const Icon = item.icon;
              return (
                <ListRow
                  key={item.key}
                  icon={<Icon size={20} aria-hidden />}
                  title={t(`nav.${item.key}`)}
                  subtitle={t(`portal.shared.${item.key}`)}
                  to={navHref(role, item)}
                />
              );
            })}
          </List>
        </section>

        <section className="fb-stack" aria-labelledby="portal-account">
          <h2 id="portal-account" className="fb-card__title">
            {t("portal.accountTitle")}
          </h2>
          <div className="fb-card portal-account">
            <dl className="portal-account__facts">
              <div>
                <dt>{t("auth.alias")}</dt>
                <dd>{user.displayAlias}</dd>
              </div>
              {user.username && (
                <div>
                  <dt>{t("portal.username")}</dt>
                  <dd>{user.username}</dd>
                </div>
              )}
              <div>
                <dt>{t("portal.role")}</dt>
                <dd>
                  <Chip>{t(`role.${role}`)}</Chip>
                </dd>
              </div>
            </dl>
          </div>
          <List label={t("portal.accountTitle")}>
            {ACCOUNT[role].map((item) => (
              <ListRow
                key={item.key}
                icon={<UserRound size={20} aria-hidden />}
                title={t(`nav.${item.key}`)}
                subtitle={t(`portal.account.${item.key}`)}
                to={navHref(role, item)}
              />
            ))}
            <ListRow
              icon={<Settings size={20} aria-hidden />}
              title={t("nav.settings")}
              subtitle={t("portal.account.settings")}
              to={`${home}/settings`}
            />
            {participant && (
              <ListRow
                icon={<ShieldCheck size={20} aria-hidden />}
                title={t("nav.privacy")}
                subtitle={t("account.privacyHint")}
                to={`${home}/privacy`}
              />
            )}
          </List>
        </section>
      </div>
    </Page>
  );
}
