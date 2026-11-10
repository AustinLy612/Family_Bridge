/** Admin: site name, help contacts and service hours (Plan §5.1/§5.2; O4 placeholders). */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Settings2, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { get, put } from "../../api/client";
import type { HelpContact, SiteOut } from "../../api/types";
import { ErrorNotice, Notice, TextField } from "../../components/Forms";
import { PrimaryButton } from "../../design";
import { Page } from "../Page";

const emptyContact = (): HelpContact => ({
  label: { "zh-CN": "", en: "" },
  phone: "",
  hours: { "zh-CN": "", en: "" },
});

export function SiteSettingsPage() {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ["admin", "site"],
    queryFn: () => get<SiteOut>("/admin/site"),
    retry: false,
  });
  return (
    <Page title={t("nav.siteSettings")} subtitle={t("admin.siteSubtitle")} icon={<Settings2 size={22} />}>
      {q.isPending ? null : <SiteForm initial={q.data ?? null} />}
    </Page>
  );
}

function SiteForm({ initial }: { initial: SiteOut | null }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [name, setName] = useState(initial?.name ?? "");
  const [timezone, setTimezone] = useState(initial?.timezone ?? "Asia/Shanghai");
  const [contacts, setContacts] = useState<HelpContact[]>(() =>
    (initial?.help_contacts ?? []).map((c) => ({
      label: { "zh-CN": c.label["zh-CN"] ?? "", en: c.label.en ?? "" },
      phone: c.phone,
      hours: { "zh-CN": c.hours?.["zh-CN"] ?? "", en: c.hours?.en ?? "" },
    })),
  );
  const [hoursZh, setHoursZh] = useState(initial?.service_hours["zh-CN"] ?? "");
  const [hoursEn, setHoursEn] = useState(initial?.service_hours.en ?? "");
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const setContact = (i: number, fn: (c: HelpContact) => HelpContact) =>
    setContacts((cs) => cs.map((c, j) => (j === i ? fn(c) : c)));

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSaved(false);
    try {
      const data = await put<SiteOut>("/admin/site", {
        name,
        timezone,
        help_contacts: contacts,
        service_hours: { "zh-CN": hoursZh, en: hoursEn },
      });
      qc.setQueryData(["admin", "site"], data);
      setSaved(true);
    } catch (err) {
      setError(err);
    }
  }

  return (
    <form onSubmit={onSubmit} className="fb-form fb-stack" noValidate>
      <Notice tone="warn">{t("admin.placeholderNotice")}</Notice>
      <section className="fb-card">
        <TextField label={t("admin.siteName")} value={name} onChange={(e) => setName(e.target.value)} />
        <TextField
          label={t("admin.timezone")}
          value={timezone}
          onChange={(e) => setTimezone(e.target.value)}
        />
        <TextField label={t("admin.hoursZh")} value={hoursZh} onChange={(e) => setHoursZh(e.target.value)} />
        <TextField label={t("admin.hoursEn")} value={hoursEn} onChange={(e) => setHoursEn(e.target.value)} />
      </section>
      <h2 className="fb-card__title">{t("help.whereToGetHelp")}</h2>
      {contacts.map((c, i) => (
        <fieldset key={i} className="fb-card fb-fieldset">
          <legend>{t("admin.contactN", { n: i + 1 })}</legend>
          <TextField
            label={t("admin.labelZh")}
            value={c.label["zh-CN"] ?? ""}
            onChange={(e) =>
              setContact(i, (x) => ({
                ...x,
                label: { ...x.label, "zh-CN": e.target.value },
              }))
            }
          />
          <TextField
            label={t("admin.labelEn")}
            value={c.label.en ?? ""}
            onChange={(e) =>
              setContact(i, (x) => ({
                ...x,
                label: { ...x.label, en: e.target.value },
              }))
            }
          />
          <TextField
            label={t("admin.phone")}
            value={c.phone}
            inputMode="tel"
            onChange={(e) => setContact(i, (x) => ({ ...x, phone: e.target.value }))}
          />
          <TextField
            label={t("admin.contactHoursZh")}
            value={c.hours["zh-CN"] ?? ""}
            onChange={(e) =>
              setContact(i, (x) => ({
                ...x,
                hours: { ...x.hours, "zh-CN": e.target.value },
              }))
            }
          />
          <TextField
            label={t("admin.contactHoursEn")}
            value={c.hours.en ?? ""}
            onChange={(e) =>
              setContact(i, (x) => ({
                ...x,
                hours: { ...x.hours, en: e.target.value },
              }))
            }
          />
          <button
            type="button"
            className="fb-btn fb-btn--secondary"
            onClick={() => setContacts((cs) => cs.filter((_, j) => j !== i))}
          >
            <Trash2 size={18} aria-hidden /> {t("admin.removeContact")}
          </button>
        </fieldset>
      ))}
      <div className="fb-actions">
        <button
          type="button"
          className="fb-btn fb-btn--secondary"
          onClick={() => setContacts((cs) => [...cs, emptyContact()])}
        >
          <Plus size={18} aria-hidden /> {t("admin.addContact")}
        </button>
        <PrimaryButton type="submit">{t("account.save")}</PrimaryButton>
      </div>
      <ErrorNotice error={error} />
      {saved && <Notice>{t("account.saved")}</Notice>}
    </form>
  );
}
