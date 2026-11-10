import { useTranslation } from "react-i18next";
import { Link } from "react-router";

export function NotFound() {
  const { t } = useTranslation();
  return (
    <main id="main" className="start-page">
      <h1>{t("errors.notFound")}</h1>
      <Link to="/">{t("errors.goHome")}</Link>
    </main>
  );
}
