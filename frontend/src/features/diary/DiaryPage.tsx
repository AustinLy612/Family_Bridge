/**
 * Diary Card home (Plan §5.6). Private card, several entries a day (D64), the last 30 days listed.
 * Missing days are never mentioned except to say that is okay. Items shared with you by a family
 * member appear under "Shared with me", attributed and dated.
 */
import { useQuery } from "@tanstack/react-query";
import { NotebookPen, Share2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";
import { diary, type DiaryEntry, type RenderedItem } from "../../api/diary";
import { ROLE_HOME, useSession } from "../../app/session";
import { ErrorNotice, Notice } from "../../components/Forms";
import { List, ListRow } from "../../design";
import { Page } from "../../routes/Page";
import { Section } from "../lessons/common";
import { useDateFormat } from "./util";
import { RenderedValues } from "./values";
import "./diary.css";

export function DiaryPage() {
  const { t } = useTranslation();
  const user = useSession();
  const home = user ? ROLE_HOME[user.role] : "";
  const tq = useQuery({ queryKey: ["diary", "template"], queryFn: diary.template });
  const q = useQuery({ queryKey: ["diary", "entries"], queryFn: () => diary.entries(30) });
  const shared = useQuery({ queryKey: ["diary", "shared"], queryFn: diary.sharedWithMe });
  const entries = q.data?.entries ?? [];
  const items = shared.data?.items ?? [];

  return (
    <Page
      title={t("nav.diary")}
      subtitle={tq.data?.template.intro}
      icon={<NotebookPen size={22} />}
      visibility={{ kind: "therapist" }}
    >
      <div className="fb-stack">
        <ErrorNotice error={tq.error ?? q.error ?? shared.error} />
        <Notice>{t("diary.missedOkay")}</Notice>
        <div className="fb-actions">
          <Link className="fb-btn fb-btn--primary" to={`${home}/diary/new`}>
            {t("diary.new")}
          </Link>
        </div>
        <Section title={t("diary.recent")}>
          {q.isSuccess && entries.length === 0 && <p>{t("diary.empty")}</p>}
          {entries.length > 0 && <EntryList entries={entries} home={home} />}
        </Section>
        {(items.length > 0 || user?.role === "caregiver") && (
          <Section title={t("diary.sharedWithMe.title")}>
            {shared.isSuccess && items.length === 0 && <p>{t("diary.sharedWithMe.empty")}</p>}
            {items.map((s) => (
              <SharedCard
                key={s.id}
                from={s.from}
                date={s.entry_date}
                sharedAt={s.shared_at}
                items={s.items}
              />
            ))}
          </Section>
        )}
      </div>
    </Page>
  );
}

function EntryList({ entries, home }: { entries: DiaryEntry[]; home: string }) {
  const { t } = useTranslation();
  const { day, time } = useDateFormat();
  return (
    <List label={t("diary.recent")}>
      {entries.map((e) => {
        const active = e.shares.filter((s) => !s.revoked_at);
        return (
          <ListRow
            key={e.id}
            icon={<NotebookPen size={20} />}
            title={t("diary.entryFor", { date: day(e.entry_date) })}
            subtitle={[
              t("diary.savedAt", { time: time(e.recorded_at) }),
              ...active.map((s) => t("privacy.sharedWith", { alias: s.recipient })),
            ].join(" · ")}
            to={`${home}/diary/${e.id}`}
            trailing={active.length ? <Share2 size={18} aria-hidden /> : undefined}
          />
        );
      })}
    </List>
  );
}

function SharedCard({
  from,
  date,
  sharedAt,
  items,
}: {
  from: string;
  date: string;
  sharedAt: string;
  items: RenderedItem[];
}) {
  const { t } = useTranslation();
  const { day } = useDateFormat();
  return (
    <article className="fb-card fb-stack" data-testid="shared-item">
      <h3 className="fb-card__title">{t("diary.sharedWithMe.from", { alias: from, date: day(date) })}</h3>
      <p className="fb-setting__hint">
        {t("diary.sharedWithMe.sharedOn", { date: day(sharedAt.slice(0, 10)) })}
      </p>
      <RenderedValues items={items} />
    </article>
  );
}
