/**
 * App shell (Plan §5.13.1): soft backdrop + large rounded white frame, left sidebar
 * (brand, user card, navigation tree — Portal, then each module with only the open module's
 * screens listed, then shared items such as Help (D95) — with profile/Settings/Log out pinned at
 * the bottom), content header
 * (back, icon tile, title/subtitle, tag pill, right pills), optional right rail.
 * Participant screens always show a "Get help" link (Plan §5.7). A "who can see this" indicator
 * appears only where someone other than the participant can see the page (diary, joint room);
 * Pause lives in the joint room only, where it pauses the room for both people (D92).
 * Below 900 px the frame goes edge-to-edge and the sidebar becomes a bottom tab bar;
 * the right rail collapses below 1200 px.
 */
import { ArrowLeft, ChevronDown, LayoutGrid, LifeBuoy, LogOut, Settings } from "lucide-react";
import { useEffect, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link, NavLink, useLocation, useNavigate } from "react-router";
import { Chip, PlaceholderArt, PrivacyIndicator, type Visibility } from "../design";
import { LanguageSwitch } from "../components/Controls";
import { useAccessibility } from "./accessibility";
import {
  ACCOUNT,
  MODULES,
  PORTAL_PATH,
  SHARED,
  isParticipant,
  moduleFor,
  moduleHref,
  navHref,
  type NavItem,
} from "./nav";
import { BrandMark } from "../design/components/BrandMark";
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
  /** Shown when someone other than the participant can see this page (D92). */
  visibility?: Visibility;
  rail?: ReactNode;
  onLogout?: () => void;
  children: ReactNode;
}

function NavItemLink({ role, item }: { role: Role; item: NavItem }) {
  const { t } = useTranslation();
  const Icon = item.icon;
  return (
    <NavLink to={navHref(role, item)} end={item.path === ""} className="shell-nav__link">
      <Icon size={20} aria-hidden />
      <span>{t(`nav.${item.key}`)}</span>
    </NavLink>
  );
}

function Sidebar({ role, alias, onLogout }: { role: Role; alias: string; onLogout?: () => void }) {
  const { t } = useTranslation();
  const { illustrationsVisible } = useAccessibility();
  const { pathname } = useLocation();
  const home = ROLE_HOME[role];
  const current = moduleFor(role, pathname);
  return (
    <aside className="shell-sidebar">
      <NavLink to={PORTAL_PATH} className="shell-brand">
        <BrandMark />
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
          </span>
        </span>
      </div>

      <nav className="shell-nav" aria-label={t("nav.main")}>
        <ul>
          <li>
            <NavLink to={PORTAL_PATH} className="shell-nav__link">
              <LayoutGrid size={20} aria-hidden />
              <span>{t("nav.portal")}</span>
            </NavLink>
          </li>
          {MODULES[role].map((m) => {
            const Icon = m.icon;
            const open = current === m.id;
            const first = m.items[0];
            const single = m.items.length === 1 && first ? first : null;
            return (
              <li key={m.id} className={`shell-module${open ? " shell-module--open" : ""}`}>
                {single ? (
                  <NavItemLink role={role} item={{ ...single, key: `module.${m.id}`, icon: Icon }} />
                ) : (
                  <Link
                    to={moduleHref(role, m)}
                    className={`shell-nav__link shell-module__head${open ? " shell-module__head--current" : ""}`}
                    aria-expanded={open}
                  >
                    <Icon size={20} aria-hidden />
                    <span>{t(`nav.module.${m.id}`)}</span>
                    <ChevronDown size={16} aria-hidden className="shell-module__chevron" />
                  </Link>
                )}
                {open && !single && (
                  <ul className="shell-module__items" aria-label={t(`nav.module.${m.id}`)}>
                    {m.items.map((item) => (
                      <li key={item.key}>
                        <NavItemLink role={role} item={item} />
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            );
          })}
          {SHARED[role].map((item) => (
            <li key={item.key}>
              <NavItemLink role={role} item={item} />
            </li>
          ))}
        </ul>
      </nav>

      <div className="shell-sidebar__bottom">
        {ACCOUNT[role].map((item) => (
          <NavItemLink key={item.key} role={role} item={item} />
        ))}
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
