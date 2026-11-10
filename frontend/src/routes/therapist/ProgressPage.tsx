/**
 * Therapist progress (Plan §5.8 "Skill-mastery summaries"): a group coverage map of which skills
 * each participant has practised, and links to each family's learning review. The map is not a
 * ranking: columns keep a fixed family order and there are no per-person totals. Shades show
 * how many lessons, never a judgement; nothing is red.
 */
import { useQuery } from "@tanstack/react-query";
import { BookOpen, ChartLine } from "lucide-react";
import { useTranslation } from "react-i18next";
import { therapist, type Coverage } from "../../api/therapist";
import { ROLE_HOME } from "../../app/session";
import { ErrorNotice } from "../../components/Forms";
import { Chip, List, ListRow } from "../../design";
import { Section } from "../../features/lessons/common";
import { Page } from "../Page";
import { GroupSelect } from "./common";
import { useGroupChoice } from "./groups";
import "./therapist.css";

const MARK: Record<string, string> = { understood: "✓", worth_revisiting: "↻", practised: "•" };

export function ProgressPage() {
  const { t } = useTranslation();
  const { groups, list, groupId, setGroupId } = useGroupChoice();
  const q = useQuery({
    queryKey: ["coverage", groupId],
    queryFn: () => therapist.coverage(groupId ?? ""),
    enabled: !!groupId,
  });
  const families = q.data
    ? [...new Map(q.data.participants.map((p) => [p.family_id, p.family])).entries()]
    : [];
  return (
    <Page
      title={t("nav.progress")}
      subtitle={t("therapist.progress.subtitle")}
      icon={<ChartLine size={22} />}
    >
      <div className="fb-stack">
        <ErrorNotice error={groups.error ?? q.error} />
        {groups.isSuccess && list.length === 0 && <p>{t("therapist.diary.noGroups")}</p>}
        <GroupSelect groups={list} value={groupId} onChange={setGroupId} />
        {q.data && (
          <>
            <Section title={t("therapist.progress.families")}>
              {families.length === 0 ? (
                <p>{t("therapist.diary.noFamilies")}</p>
              ) : (
                <List label={t("therapist.progress.families")}>
                  {families.map(([id, label]) => (
                    <ListRow
                      key={id}
                      icon={<BookOpen size={20} aria-hidden />}
                      title={label}
                      subtitle={t("therapist.learning.open")}
                      to={`${ROLE_HOME.therapist}/families/${id}/learning`}
                    />
                  ))}
                </List>
              )}
            </Section>
            <CoverageMap data={q.data} />
          </>
        )}
      </div>
    </Page>
  );
}

function CoverageMap({ data }: { data: Coverage }) {
  const { t } = useTranslation();
  const people = data.participants;
  const inGroup = new Set(data.group_session_skills);
  if (people.length === 0) return null;
  return (
    <Section title={t("therapist.progress.coverage")}>
      <p className="fb-setting__hint">{t("therapist.progress.coverageHint")}</p>
      <ul className="fb-chart__legend" aria-label={t("therapist.progress.legend")}>
        {(["practised", "understood", "worth_revisiting"] as const).map((o) => (
          <li key={o}>
            {MARK[o]} {t(`learn.outcome.${o}`)}
          </li>
        ))}
        <li>
          <Chip tone="outline">{t("therapist.progress.inGroup")}</Chip>
        </li>
      </ul>
      <div className="fb-heat__scroll">
        <table className="fb-heat" data-testid="coverage-map">
          <caption className="visually-hidden">{t("therapist.progress.coverage")}</caption>
          <thead>
            <tr>
              <th scope="col">{t("therapist.progress.skill")}</th>
              {people.map((p) => (
                <th key={p.user_id} scope="col">
                  <span className="fb-heat__alias">{p.alias}</span>
                  <span className="fb-setting__hint">
                    {p.family} · {t(`role.${p.role}`)}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          {data.modules.map((m) => (
            <tbody key={m.id}>
              <tr>
                <th scope="colgroup" colSpan={people.length + 1} className="fb-heat__module">
                  {m.name}
                </th>
              </tr>
              {m.skills.map((s) => (
                <tr key={s.id}>
                  <th scope="row">
                    {s.name}{" "}
                    {inGroup.has(s.id) && <Chip tone="outline">{t("therapist.progress.inGroup")}</Chip>}
                  </th>
                  {people.map((p) => {
                    const c = data.cells[s.id]?.[p.user_id];
                    const level = c ? Math.min(3, c.lessons) : 0;
                    return (
                      <td key={p.user_id} className={`fb-heat__cell fb-heat__cell--${level}`}>
                        {c ? (
                          <span
                            aria-label={t("therapist.progress.cell", {
                              n: c.lessons,
                              outcome: t(`learn.outcome.${c.outcome}`),
                            })}
                          >
                            {MARK[c.outcome] ?? "•"} {c.lessons}
                          </span>
                        ) : (
                          <span className="visually-hidden">{t("therapist.progress.none")}</span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          ))}
        </table>
      </div>
    </Section>
  );
}
