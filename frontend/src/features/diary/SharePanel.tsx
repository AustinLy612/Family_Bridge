/**
 * Share chosen items from one entry with a caregiver (Plan §5.2; D66): choose → preview exactly
 * what they will see → share. Each share can be stopped at any time, which removes access at
 * once. The recipient sees the entry as it was when it was shared.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Share2 } from "lucide-react";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { diary, type DiaryEntry, type DiaryTemplate, type DiaryValues } from "../../api/diary";
import { ErrorNotice } from "../../components/Forms";
import { List, ListRow, PrimaryButton } from "../../design";
import { allFields, useDateFormat, useValueText } from "./util";
import { ValueList } from "./values";

const NOTE = "note";

export function SharePanel({ template, entry }: { template: DiaryTemplate; entry: DiaryEntry }) {
  const { t } = useTranslation();
  const { day } = useDateFormat();
  const qc = useQueryClient();
  const text = useValueText(template);
  const whoId = useId();
  const rq = useQuery({ queryKey: ["diary", "recipients"], queryFn: diary.recipients });
  const [recipient, setRecipient] = useState<string | null>(null);
  const [fields, setFields] = useState<string[]>([]);
  const [previewing, setPreviewing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const recipients = rq.data?.recipients ?? [];
  const answered = allFields(template).filter((f) =>
    f.type === "note" ? !!entry.note : entry.values[f.id] !== undefined,
  );
  const alias = recipients.find((r) => r.id === recipient)?.alias ?? "";
  const chosenValues: DiaryValues = Object.fromEntries(
    fields.filter((f) => f !== NOTE).map((f) => [f, entry.values[f]!]),
  );
  const toggle = (id: string) =>
    setFields((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));

  async function run(fn: () => Promise<unknown>) {
    setError(null);
    setBusy(true);
    try {
      await fn();
      await qc.invalidateQueries({ queryKey: ["diary"] });
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="fb-card fb-stack" aria-labelledby={`${whoId}-title`} data-testid="share-panel">
      <h2 id={`${whoId}-title`} className="fb-card__title">
        <Share2 size={18} aria-hidden /> {t("diary.share.title")}
      </h2>
      <p>{t("diary.share.intro")}</p>
      <ErrorNotice error={error ?? rq.error} />

      {entry.shares.length > 0 && (
        <List label={t("diary.share.existing")}>
          {entry.shares.map((s) => (
            <ListRow
              key={s.id}
              icon={<Share2 size={18} />}
              title={
                s.revoked_at
                  ? t("diary.share.revoked", { alias: s.recipient, date: day(s.revoked_at.slice(0, 10)) })
                  : t("diary.share.sharedWith", { alias: s.recipient, date: day(s.created_at.slice(0, 10)) })
              }
              subtitle={s.fields
                .map((f) => allFields(template).find((x) => x.id === f)?.label ?? f)
                .join(t("diary.listSep"))}
              trailing={
                s.revoked_at ? undefined : (
                  <button
                    type="button"
                    className="fb-btn fb-btn--secondary"
                    disabled={busy}
                    onClick={() => void run(() => diary.revoke(s.id))}
                  >
                    {t("diary.share.revoke")}
                  </button>
                )
              }
            />
          ))}
        </List>
      )}

      {rq.isSuccess && recipients.length === 0 && <p>{t("diary.share.noRecipients")}</p>}
      {recipients.length > 0 && !previewing && (
        <div className="fb-stack">
          <div className="fb-diary-field">
            <span id={whoId} className="fb-diary-field__label">
              {t("diary.share.who")}
            </span>
            <div className="fb-choice" role="radiogroup" aria-labelledby={whoId}>
              {recipients.map((r) => (
                <button
                  key={r.id}
                  type="button"
                  role="radio"
                  aria-checked={recipient === r.id}
                  className={`fb-choice__option${recipient === r.id ? " fb-choice__option--on" : ""}`}
                  onClick={() => setRecipient(r.id)}
                >
                  {r.alias}
                </button>
              ))}
            </div>
          </div>
          <fieldset className="fb-diary-field">
            <legend className="fb-diary-field__label">{t("diary.share.what")}</legend>
            <div className="fb-diary-skills">
              {answered.map((f) => (
                <label key={f.id} className="fb-checkbox">
                  <input type="checkbox" checked={fields.includes(f.id)} onChange={() => toggle(f.id)} />
                  {f.label}
                </label>
              ))}
            </div>
          </fieldset>
          <PrimaryButton disabled={!recipient || fields.length === 0} onClick={() => setPreviewing(true)}>
            {t("diary.share.preview")}
          </PrimaryButton>
        </div>
      )}

      {previewing && (
        <div className="fb-stack">
          <div className="fb-share-preview" data-testid="share-preview">
            <p className="fb-card__title">{t("diary.share.previewTitle", { alias })}</p>
            <ValueList
              template={template}
              values={chosenValues}
              note={fields.includes(NOTE) ? entry.note : null}
              text={text}
            />
            <p className="fb-setting__hint">{t("diary.share.snapshot")}</p>
          </div>
          <div className="fb-actions">
            <PrimaryButton
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  await diary.share(entry.id, recipient ?? "", fields);
                  setPreviewing(false);
                  setFields([]);
                  setRecipient(null);
                })
              }
            >
              {t("diary.share.confirm")}
            </PrimaryButton>
            <button type="button" className="fb-btn fb-btn--secondary" onClick={() => setPreviewing(false)}>
              {t("diary.share.change")}
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
