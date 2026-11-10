/** Placeholder screen for each navigation item until its phase is built. */
import { useTranslation } from "react-i18next";
import { Page } from "./Page";

export function RolePlaceholder({ titleKey }: { titleKey: string }) {
  const { t } = useTranslation();
  return (
    <Page title={t(titleKey)}>
      <p>{t("placeholder.comingLater")}</p>
    </Page>
  );
}
