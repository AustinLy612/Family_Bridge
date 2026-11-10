/** Therapist: own groups and their families (Plan §5.1; Phase 1 task 4). */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Users, UsersRound } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router";
import { get, post } from "../../api/client";
import type { FamilySummary, GroupDetail, GroupSummary } from "../../api/types";
import { ErrorNotice, TextField } from "../../components/Forms";
import { List, ListRow, PrimaryButton } from "../../design";
import { Page } from "../Page";
import { GroupSkillRecords } from "./GroupSkillRecords";

function CreateForm({ label, onCreate }: { label: string; onCreate: (name: string) => Promise<void> }) {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  const [error, setError] = useState<unknown>(null);
  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await onCreate(name.trim());
      setName("");
    } catch (err) {
      setError(err);
    }
  }
  return (
    <form onSubmit={onSubmit} className="fb-form fb-form--inline" noValidate>
      <TextField label={label} value={name} maxLength={120} onChange={(e) => setName(e.target.value)} />
      <PrimaryButton type="submit" disabled={!name.trim()}>
        {t("therapist.create")}
      </PrimaryButton>
      <ErrorNotice error={error} />
    </form>
  );
}

export function GroupsPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["groups"],
    queryFn: () => get<GroupSummary[]>("/groups"),
  });
  return (
    <Page title={t("nav.groups")} subtitle={t("therapist.groupsSubtitle")} icon={<Users size={22} />}>
      <div className="fb-stack">
        <ErrorNotice error={q.error} />
        {q.data &&
          (q.data.length === 0 ? (
            <p>{t("therapist.noGroups")}</p>
          ) : (
            <List label={t("nav.groups")}>
              {q.data.map((g) => (
                <ListRow
                  key={g.id}
                  icon={<UsersRound size={20} />}
                  title={g.name}
                  subtitle={t("therapist.groupMeta", {
                    count: g.family_count,
                    therapists: g.therapists.join(", "),
                  })}
                  to={`/therapist/groups/${g.id}`}
                />
              ))}
            </List>
          ))}
        <section className="fb-card">
          <CreateForm
            label={t("therapist.newGroup")}
            onCreate={async (name) => {
              await post("/groups", { name });
              await qc.invalidateQueries({ queryKey: ["groups"] });
            }}
          />
        </section>
      </div>
    </Page>
  );
}

export function GroupPage() {
  const { t } = useTranslation();
  const { groupId = "" } = useParams();
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["group", groupId],
    queryFn: () => get<GroupDetail>(`/groups/${groupId}`),
  });
  return (
    <Page
      title={q.data?.name ?? t("nav.groups")}
      subtitle={t("therapist.groupSubtitle")}
      showBack
      icon={<UsersRound size={22} />}
    >
      <div className="fb-stack">
        <ErrorNotice error={q.error} />
        {q.data &&
          (q.data.families.length === 0 ? (
            <p>{t("therapist.noFamilies")}</p>
          ) : (
            <List label={t("therapist.families")}>
              {q.data.families.map((f: FamilySummary) => (
                <ListRow
                  key={f.id}
                  title={f.label}
                  subtitle={t("therapist.familyMeta", {
                    count: f.member_count,
                    pending: f.pending_invites,
                  })}
                  to={`/therapist/families/${f.id}`}
                />
              ))}
            </List>
          ))}
        <section className="fb-card">
          <CreateForm
            label={t("therapist.newFamily")}
            onCreate={async (label) => {
              await post(`/groups/${groupId}/families`, { label });
              await qc.invalidateQueries({ queryKey: ["group", groupId] });
            }}
          />
          <p className="fb-setting__hint">{t("therapist.familyLabelHint")}</p>
        </section>
        {q.data && <GroupSkillRecords groupId={groupId} />}
      </div>
    </Page>
  );
}
