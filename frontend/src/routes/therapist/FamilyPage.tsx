/**
 * Therapist: one family — members, invitations (code shown once; one adolescent max),
 * staff-issued reset codes (D30) and joint-work suitability per dyad (Plan §5.8).
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { HeartHandshake } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router";
import { get, post, put } from "../../api/client";
import type { DyadOut, FamilyDetail, IssuedCode, MemberOut, Suitability } from "../../api/types";
import { CodeReveal, ErrorNotice, Notice, SelectField, TextField } from "../../components/Forms";
import { Chip, List, ListRow, PrimaryButton } from "../../design";
import { Page } from "../Page";
import { useFocusTime } from "../../app/focusTime";

const SUITABILITY: Suitability[] = ["not_assessed", "suitable", "not_suitable"];

function DyadEditor({ familyId, dyad, members }: { familyId: string; dyad: DyadOut; members: MemberOut[] }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [decision, setDecision] = useState<Suitability>(dyad.decision);
  const [note, setNote] = useState(dyad.note ?? "");
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  const alias = (id: string) => members.find((m) => m.user_id === id)?.display_alias ?? "";
  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await put(`/families/${familyId}/suitability`, {
        adolescent_id: dyad.adolescent_id,
        caregiver_id: dyad.caregiver_id,
        decision,
        note: note.trim() || null,
      });
      setSaved(true);
      await qc.invalidateQueries({ queryKey: ["family", familyId] });
    } catch (err) {
      setError(err);
    }
  }
  return (
    <form onSubmit={onSubmit} className="fb-card fb-form" noValidate>
      <h3>
        {t("therapist.dyad", {
          a: alias(dyad.adolescent_id),
          c: alias(dyad.caregiver_id),
        })}
      </h3>
      <SelectField
        label={t("therapist.suitability")}
        value={decision}
        onChange={(v) => {
          setDecision(v as Suitability);
          setSaved(false);
        }}
        options={SUITABILITY.map((s) => ({
          value: s,
          label: t(`therapist.suit.${s}`),
        }))}
      />
      <TextField
        label={t("therapist.note")}
        hint={t("therapist.noteHint")}
        value={note}
        maxLength={1000}
        onChange={(e) => {
          setNote(e.target.value);
          setSaved(false);
        }}
      />
      <ErrorNotice error={error} />
      {saved && <Notice>{t("account.saved")}</Notice>}
      <PrimaryButton type="submit" variant="secondary">
        {t("account.save")}
      </PrimaryButton>
    </form>
  );
}

export function FamilyPage() {
  const { t, i18n } = useTranslation();
  const { familyId = "" } = useParams();
  useFocusTime(familyId);
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["family", familyId],
    queryFn: () => get<FamilyDetail>(`/families/${familyId}`),
  });
  const [roleChoice, setRole] = useState<"adolescent" | "caregiver">("caregiver");
  const [relationship, setRelationship] = useState("");
  const [issued, setIssued] = useState<{
    code: IssuedCode;
    label: string;
  } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const reload = () => qc.invalidateQueries({ queryKey: ["family", familyId] });
  const date = (s: string) => new Date(s).toLocaleDateString(i18n.language);
  const hasAdolescent =
    !!q.data &&
    (q.data.members.some((m) => m.role === "adolescent") ||
      q.data.pending.some((p) => p.role === "adolescent"));
  // Only offer what the server will accept: a family has at most one teen.
  const role = hasAdolescent ? "caregiver" : roleChoice;

  async function run(fn: () => Promise<unknown>) {
    setError(null);
    try {
      await fn();
      await reload();
    } catch (err) {
      setError(err);
    }
  }

  async function invite(e: FormEvent) {
    e.preventDefault();
    await run(async () => {
      const code = await post<IssuedCode>(`/families/${familyId}/invitations`, {
        role,
        relationship_label: relationship.trim() || null,
      });
      setIssued({
        code,
        label: t("therapist.inviteCodeFor", { role: t(`role.${role}`) }),
      });
      setRelationship("");
    });
  }

  const f = q.data;
  return (
    <Page
      title={f?.label ?? ""}
      subtitle={t("therapist.familySubtitle")}
      showBack
      icon={<HeartHandshake size={22} />}
    >
      <div className="fb-stack">
        <ErrorNotice error={error ?? q.error} />
        <div className="fb-actions">
          <Link className="fb-btn fb-btn--secondary" to={`/therapist/families/${familyId}/diary`}>
            {t("therapist.diary.open")}
          </Link>
          <Link className="fb-btn fb-btn--secondary" to={`/therapist/families/${familyId}/learning`}>
            {t("therapist.learning.open")}
          </Link>
        </div>
        {issued && (
          <>
            <p>{issued.label}</p>
            <CodeReveal
              code={issued.code.code}
              expiresAt={issued.code.expires_at}
              onDone={() => setIssued(null)}
            />
          </>
        )}
        {f && (
          <>
            <h2 className="fb-card__title">{t("therapist.members")}</h2>
            {f.members.length === 0 ? (
              <p>{t("therapist.noMembers")}</p>
            ) : (
              <List label={t("therapist.members")}>
                {f.members.map((m) => (
                  <ListRow
                    key={m.user_id}
                    title={`${m.display_alias}${m.relationship_label ? ` · ${m.relationship_label}` : ""}`}
                    subtitle={`${t(`role.${m.role}`)} · ${m.pseudonym}`}
                    trailing={
                      <span className="fb-row__actions">
                        <Chip>{m.onboarded ? t("therapist.onboarded") : t("therapist.notOnboarded")}</Chip>
                        <button
                          type="button"
                          className="fb-btn fb-btn--secondary"
                          onClick={() =>
                            void run(async () => {
                              const code = await post<IssuedCode>(
                                `/families/${familyId}/members/${m.user_id}/reset-code`,
                              );
                              setIssued({
                                code,
                                label: t("admin.resetCodeFor", {
                                  alias: m.display_alias,
                                }),
                              });
                            })
                          }
                        >
                          {t("admin.resetCode")}
                        </button>
                      </span>
                    }
                  />
                ))}
              </List>
            )}

            {f.pending.length > 0 && (
              <>
                <h2 className="fb-card__title">{t("admin.pending")}</h2>
                <List label={t("admin.pending")}>
                  {f.pending.map((p) => (
                    <ListRow
                      key={p.id}
                      title={`${t(`role.${p.role}`)}${p.relationship_label ? ` · ${p.relationship_label}` : ""}`}
                      subtitle={t("codes.expires", {
                        date: date(p.expires_at),
                      })}
                      trailing={
                        <button
                          type="button"
                          className="fb-btn fb-btn--secondary"
                          onClick={() => void run(() => post(`/invitations/${p.id}/revoke`))}
                        >
                          {t("codes.revoke")}
                        </button>
                      }
                    />
                  ))}
                </List>
              </>
            )}

            <form onSubmit={(e) => void invite(e)} className="fb-card fb-form" noValidate>
              <h2 className="fb-card__title">{t("therapist.newInvitation")}</h2>
              <SelectField
                label={t("therapist.inviteRole")}
                value={role}
                onChange={(v) => setRole(v as "adolescent" | "caregiver")}
                options={[
                  ...(hasAdolescent ? [] : [{ value: "adolescent", label: t("role.adolescent") }]),
                  { value: "caregiver", label: t("role.caregiver") },
                ]}
              />
              {hasAdolescent && <p className="fb-setting__hint">{t("therapist.oneAdolescent")}</p>}
              <TextField
                label={t("therapist.relationship")}
                hint={t("therapist.relationshipHint")}
                value={relationship}
                maxLength={40}
                onChange={(e) => setRelationship(e.target.value)}
              />
              <PrimaryButton type="submit">{t("therapist.generateCode")}</PrimaryButton>
            </form>

            {f.dyads.length > 0 && (
              <>
                <h2 className="fb-card__title">{t("therapist.suitabilityTitle")}</h2>
                <p className="fb-setting__hint">{t("therapist.suitabilityHint")}</p>
                {f.dyads.map((d) => (
                  <DyadEditor
                    // Not keyed on decided_at: saving must not remount the form, or the
                    // "Saved." confirmation disappears as soon as the family refetches.
                    key={`${d.adolescent_id}-${d.caregiver_id}`}
                    familyId={familyId}
                    dyad={d}
                    members={f.members}
                  />
                ))}
              </>
            )}
          </>
        )}
      </div>
    </Page>
  );
}
