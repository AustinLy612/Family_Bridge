/** Admin: therapist accounts (Plan §5.1; Phase 1 task 3). Codes are shown once. */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Users } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { get, post, put } from "../../api/client";
import type { IssuedCode, PendingInvite, TherapistOut } from "../../api/types";
import { CodeReveal, ErrorNotice } from "../../components/Forms";
import { Chip, List, ListRow, PrimaryButton } from "../../design";
import { Page } from "../Page";

interface TherapistList {
  therapists: TherapistOut[];
  pending: PendingInvite[];
}

export function TherapistsPage() {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["admin", "therapists"],
    queryFn: () => get<TherapistList>("/admin/therapists"),
  });
  const [issued, setIssued] = useState<{
    code: IssuedCode;
    label: string;
  } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const reload = () => qc.invalidateQueries({ queryKey: ["admin", "therapists"] });
  const date = (s: string) => new Date(s).toLocaleDateString(i18n.language);

  async function run(fn: () => Promise<unknown>) {
    setError(null);
    try {
      await fn();
      await reload();
    } catch (err) {
      setError(err);
    }
  }

  return (
    <Page title={t("nav.therapists")} subtitle={t("admin.therapistsSubtitle")} icon={<Users size={22} />}>
      <div className="fb-stack">
        <div className="fb-actions">
          <PrimaryButton
            onClick={() =>
              void run(async () => {
                const code = await post<IssuedCode>("/admin/therapists");
                setIssued({ code, label: t("admin.newTherapistCode") });
              })
            }
          >
            {t("admin.inviteTherapist")}
          </PrimaryButton>
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
        <ErrorNotice error={error ?? q.error} />
        {q.data && (
          <>
            <h2 className="fb-card__title">{t("admin.accounts")}</h2>
            {q.data.therapists.length === 0 ? (
              <p>{t("admin.noTherapists")}</p>
            ) : (
              <List label={t("admin.accounts")}>
                {q.data.therapists.map((th) => (
                  <ListRow
                    key={th.id}
                    title={`${th.display_alias} (${th.username})`}
                    subtitle={t("admin.therapistMeta", {
                      groups: th.group_count,
                      last: th.last_login_at ? date(th.last_login_at) : t("admin.never"),
                    })}
                    trailing={
                      <span className="fb-row__actions">
                        <Chip>{t(`admin.status.${th.status}`)}</Chip>
                        {th.content_approver && <Chip tone="outline">{t("admin.contentApprover")}</Chip>}
                        <button
                          type="button"
                          className="fb-btn fb-btn--secondary"
                          onClick={() =>
                            void run(() =>
                              put(`/admin/therapists/${th.id}/content-approver`, {
                                content_approver: !th.content_approver,
                              }),
                            )
                          }
                        >
                          {th.content_approver ? t("admin.removeApprover") : t("admin.makeApprover")}
                        </button>
                        <button
                          type="button"
                          className="fb-btn fb-btn--secondary"
                          onClick={() =>
                            void run(async () => {
                              const code = await post<IssuedCode>(`/admin/therapists/${th.id}/reset-code`);
                              setIssued({
                                code,
                                label: t("admin.resetCodeFor", {
                                  alias: th.display_alias,
                                }),
                              });
                            })
                          }
                        >
                          {t("admin.resetCode")}
                        </button>
                        <button
                          type="button"
                          className="fb-btn fb-btn--secondary"
                          onClick={() =>
                            void run(() =>
                              put(`/admin/therapists/${th.id}/status`, {
                                status: th.status === "active" ? "disabled" : "active",
                              }),
                            )
                          }
                        >
                          {th.status === "active" ? t("admin.disable") : t("admin.enable")}
                        </button>
                      </span>
                    }
                  />
                ))}
              </List>
            )}
            {q.data.pending.length > 0 && (
              <>
                <h2 className="fb-card__title">{t("admin.pending")}</h2>
                <List label={t("admin.pending")}>
                  {q.data.pending.map((p) => (
                    <ListRow
                      key={p.id}
                      title={t("admin.pendingTherapist")}
                      subtitle={t("codes.expires", {
                        date: date(p.expires_at),
                      })}
                      trailing={
                        <button
                          type="button"
                          className="fb-btn fb-btn--secondary"
                          onClick={() => void run(() => post(`/admin/invitations/${p.id}/revoke`))}
                        >
                          {t("codes.revoke")}
                        </button>
                      }
                    />
                  ))}
                </List>
              </>
            )}
          </>
        )}
      </div>
    </Page>
  );
}
