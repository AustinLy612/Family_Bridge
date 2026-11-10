/**
 * App shell (Plan §5.13.1): soft backdrop + large rounded white frame, left sidebar
 * (brand, user card, role navigation, Settings/Log out pinned at the bottom), content header
 * (back, icon tile, title/subtitle, tag pill, right pills), optional right rail.
 * Participant screens always show the Pause control, a "Get help" link (Plan §5.7) and the
 * "Who can see this?" indicator (§7.3).
 * Below 900 px the frame goes edge-to-edge and the sidebar becomes a bottom tab bar;
 * the right rail collapses below 1200 px.
 */
import { ArrowLeft, LifeBuoy, LogOut, Settings } from "lucide-react";
import { useEffect, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { NavLink, useNavigate } from "react-router";
import { Chip, PlaceholderArt, PrivacyIndicator, type Visibility } from "../design";
import { LanguageSwitch, PauseControl } from "../components/Controls";
import { useAccessibility } from "./accessibility";
import { NAV, isParticipant, navHref } from "./nav";
import { ROLE_HOME, type Role } from "./session";

export interface AppShellProps {
  role: Role;
  alias: string;
  title: string;
  subtitle?: string;
  icon?: ReactNode;
  tag?: string;
  showBack?: boolean;
  headerPills?: ReactNode;
  /** Required on participant screens: who can see what is on this page. */
  visibility?: Visibility;
  rail?: ReactNode;
  onLogout?: () => void;
  children: ReactNode;
}

function Sidebar({ role, alias, onLogout }: { role: Role; alias: string; onLogout?: () => void }) {
  const { t, i18n } = useTranslation();
  const { illustrationsVisible } = useAccessibility();
  const home = ROLE_HOME[role];
  return (
    <aside className="shell-sidebar">
      <NavLink to={home} className="shell-brand">
        <span className="shell-brand__mark" aria-hidden>
          FB
        </span>
        <span className="shell-brand__name">FamilyBridge</span>
      </NavLink>

      <div className="shell-user">
        <span className="fb-avatar" aria-hidden>
          {illustrationsVisible && <PlaceholderArt slot="avatar" />}
        </span>
        <span className="shell-user__text">
          <span className="shell-user__alias">{alias}</span>
          <span className="shell-user__meta">
            <Chip>{t(`role.${role}`)}</Chip>
            <span className="shell-user__lang">{t(`language.${i18n.language}`)}</span>
          </span>
        </span>
      </div>

      <nav className="shell-nav" aria-label={t("nav.main")}>
        <ul>
          {NAV[role].map((item) => {
            const Icon = item.icon;
            return (
              <li key={item.key}>
                <NavLink to={navHref(role, item)} end={item.path === ""} className="shell-nav__link">
                  <Icon size={20} aria-hidden />
                  <span>{t(`nav.${item.key}`)}</span>
                </NavLink>
              </li>
            );
          })}
        </ul>
      </nav>

      <div className="shell-sidebar__bottom">
        <NavLink to={`${home}/settings`} className="shell-nav__link">
          <Settings size={20} aria-hidden />
          <span>{t("nav.settings")}</span>
        </NavLink>
        <button type="button" className="shell-nav__link" onClick={onLogout}>
          <LogOut size={20} aria-hidden />
          <span>{t("nav.logout")}</span>
        </button>
      </div>
    </aside>
  );
}

export function AppShell({
  role,
  alias,
  title,
  subtitle,
  icon,
  tag,
  showBack = false,
  headerPills,
  visibility,
  rail,
  onLogout,
  children,
}: AppShellProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const participant = isParticipant(role);
  const { setDensity } = useAccessibility();
  // Participant vs therapist/admin density and illustration defaults follow the role (Plan §5.13.6).
  useEffect(() => {
    setDensity(participant ? "participant" : "therapist");
  }, [participant, setDensity]);
  if (participant && !visibility && import.meta.env.DEV) {
    console.warn(`AppShell: participant screen "${title}" has no visibility indicator (Plan §7.3).`);
  }
  return (
    <div className="shell-backdrop">
      <a className="skip-link" href="#main">
        {title}
      </a>
      <div className={`shell-frame${rail ? " shell-frame--rail" : ""}`}>
        <Sidebar role={role} alias={alias} onLogout={onLogout} />
        <main id="main" className="shell-main" tabIndex={-1}>
          <header className="shell-header">
            <div className="shell-header__lead">
              {showBack && (
                <button
                  type="button"
                  className="shell-icon-btn"
                  aria-label={t("shell.back")}
                  onClick={() => navigate(-1)}
                >
                  <ArrowLeft size={20} aria-hidden />
                </button>
              )}
              {icon && (
                <span className="fb-icon-tile" aria-hidden>
                  {icon}
                </span>
              )}
              <div className="shell-header__titles">
                <div className="shell-header__titleRow">
                  <h1 className="shell-header__title">{title}</h1>
                  {tag && <Chip>{tag}</Chip>}
                </div>
                {subtitle && <p className="shell-header__subtitle">{subtitle}</p>}
              </div>
            </div>
            <div className="shell-header__pills">
              {headerPills}
              <LanguageSwitch />
              {participant && visibility && <PrivacyIndicator visibility={visibility} />}
              {participant && (
                <NavLink to={`${ROLE_HOME[role]}/help`} className="fb-btn fb-btn--secondary">
                  <LifeBuoy size={18} aria-hidden />
                  {t("shell.getHelp")}
                </NavLink>
              )}
              {participant && <PauseControl />}
            </div>
          </header>
          <div className="shell-content">{children}</div>
        </main>
        {rail && (
          <aside className="shell-rail" aria-label={t("shell.secondaryPanel")}>
            {rail}
          </aside>
        )}
      </div>
    </div>
  );
}
