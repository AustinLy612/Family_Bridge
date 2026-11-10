/** "Who can see my data" (Plan §5.2, §6.2 transparency) — built from the server's real list. */
import { useQuery } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import { useTranslation } from "react-i18next";
import { get } from "../../api/client";
import type { Viewer } from "../../api/types";
import { ErrorNotice } from "../../components/Forms";
import { List, ListRow } from "../../design";
import { Page } from "../Page";

export function ViewerList() {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ["visibility"],
    queryFn: () => get<{ viewers: Viewer[] }>("/me/visibility"),
  });
  if (q.isError) return <ErrorNotice error={q.error} />;
  if (!q.data) return null;
  return (
    <List label={t("visibility.listTitle")}>
      {q.data.viewers.map((v, i) => (
        <ListRow
          key={i}
          title={
            v.alias
              ? t(`visibility.kind.${v.kind}_named`, {
                  alias: v.alias,
                  role: v.role ? t(`role.${v.role}`) : "",
                })
              : t(`visibility.kind.${v.kind}`)
          }
          subtitle={v.sees.map((s) => t(s)).join(" · ")}
        />
      ))}
    </List>
  );
}

export function VisibilityPage() {
  const { t } = useTranslation();
  return (
    <Page title={t("nav.privacy")} subtitle={t("visibility.subtitle")} icon={<ShieldCheck size={22} />}>
      <ViewerList />
      <p className="fb-setting__hint">{t("visibility.changeHint")}</p>
    </Page>
  );
}
