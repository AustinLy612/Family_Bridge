/** Frame for signed-out screens: brand, language switch, content card. */
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";
import { LanguageSwitch } from "../../components/Controls";

export function PublicFrame({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  const { t } = useTranslation();
  return (
    <div className="shell-backdrop">
      <main id="main" className={`start-page${wide ? " start-page--wide" : ""}`}>
        <header className="start-page__header">
          <Link to="/" className="shell-brand">
            <span className="shell-brand__mark" aria-hidden>
              FB
            </span>
            <span className="shell-brand__name">{t("app.name")}</span>
          </Link>
          <LanguageSwitch />
        </header>
        {children}
        <p className="fb-setting__hint">{t("placeholder.notMonitored")}</p>
      </main>
    </div>
  );
}
