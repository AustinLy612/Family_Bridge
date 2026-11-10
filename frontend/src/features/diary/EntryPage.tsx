/**
 * One diary entry: new, edit (today and the previous 6 days, D65) or read-only (older).
 * After saving, the safety flow may open Help (urge threshold or a worrying note; Plan §5.7) —
 * the entry is already saved. Adolescents can share chosen items with a caregiver (D66).
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { History, NotebookPen } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate, useParams } from "react-router";
import {
  diary,
  visibleValues,
  type DiaryEntry,
  type DiaryTemplate,
  type DiaryValue,
  type DiaryValues,
  type DiaryWindow,
  type HomeworkItem,
} from "../../api/diary";
import { helpPath, useSafetyOutcome } from "../../app/safety";
import { ROLE_HOME, useSession } from "../../app/session";
import { ErrorNotice, Notice, SelectField, TextAreaField } from "../../components/Forms";
import { CareCard } from "../../components/Safety";
import { PrimaryButton } from "../../design";
import { Page } from "../../routes/Page";
import { FieldInput } from "./fields";
import { useDateFormat, useValueText } from "./util";
import { ValueList } from "./values";
import { SharePanel } from "./SharePanel";
import "./diary.css";
import { useTaskOutcome } from "../../app/research";

function datesBetween(from: string, to: string): string[] {
  const out: string[] = [];
  const d = new Date(`${to}T00:00:00Z`);
  const end = new Date(`${from}T00:00:00Z`);
  while (d >= end) {
    out.push(d.toISOString().slice(0, 10));
    d.setUTCDate(d.getUTCDate() - 1);
  }
  return out;
}

export function EntryPage() {
  const { t } = useTranslation();
  const { entryId } = useParams();
  const tq = useQuery({ queryKey: ["diary", "template"], queryFn: diary.template });
  const eq = useQuery({
    queryKey: ["diary", "entry", entryId],
    queryFn: () => diary.entry(entryId ?? ""),
    enabled: !!entryId,
  });
  const entry = eq.data?.entry;
  const version = entry?.template_version;
  const current = tq.data?.template;
  const oldTq = useQuery({
    queryKey: ["diary", "template", version],
    queryFn: () => diary.templateVersion(version ?? 1),
    enabled: !!current && version !== undefined && version !== current.version,
  });
  const template = entry && current && version !== current.version ? oldTq.data?.template : current;

  return (
    <Page
      title={t("nav.diary")}
      subtitle={entryId ? undefined : t("diary.new")}
      icon={<NotebookPen size={22} />}
      visibility={{ kind: "therapist" }}
      showBack
    >
      <div className="fb-stack">
        <ErrorNotice error={tq.error ?? eq.error ?? oldTq.error} />
        {tq.data && template && (!entryId || entry) && (
          <EntryBody
            key={entry ? `${entry.id}:${entry.revision_no}` : "new"}
            template={template}
            window={tq.data}
            canShare={tq.data.can_share}
            entry={entry}
          />
        )}
      </div>
    </Page>
  );
}

function EntryBody({
  template,
  window,
  canShare,
  entry,
}: {
  template: DiaryTemplate;
  window: DiaryWindow;
  canShare: boolean;
  entry: DiaryEntry | undefined;
}) {
  const { t } = useTranslation();
  const { day, time } = useDateFormat();
  const user = useSession();
  const home = user ? ROLE_HOME[user.role] : "";
  const navigate = useNavigate();
  const qc = useQueryClient();
  const safety = useSafetyOutcome();
  const [values, setValues] = useState<DiaryValues>(entry?.values ?? {});
  const [note, setNote] = useState(entry?.note ?? "");
  const [date, setDate] = useState(entry?.entry_date ?? window.today);
  const [homework, setHomework] = useState<string[]>(entry?.homework.map((h) => h.id) ?? []);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  // a new entry redirects to its own page and keeps the confirmation
  const justSaved = (useLocation().state as { saved?: boolean } | null)?.saved === true;
  const [saved, setSaved] = useState(justSaved);
  const editable = !entry || entry.editable;
  // usability (§8.4): a new card that is left before saving counts as abandoned
  const taskDone = useTaskOutcome("diary_entry", !entry);

  const set = (id: string, v: DiaryValue | undefined) => {
    setSaved(false);
    setValues((prev) => {
      const next = { ...prev };
      if (v === undefined) delete next[id];
      else next[id] = v;
      return next;
    });
  };

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const clean = visibleValues(template, values);
      const text = note.trim() || null;
      const out = entry
        ? await diary.update(entry.id, clean, text, entry.revision_no, homework)
        : await diary.create(date, clean, text, homework);
      if (!entry) taskDone();
      await qc.invalidateQueries({ queryKey: ["diary"] });
      if (safety.handle(out.safety)) return; // Help screen; the entry is saved
      // A new entry opens on its own page, which shows the confirmation (no flicker).
      if (entry) setSaved(true);
      else navigate(`${home}/diary/${out.entry.id}`, { replace: true, state: { saved: true } });
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  if (!editable && entry) return <ReadOnly template={template} entry={entry} canShare={canShare} />;

  return (
    <>
      {safety.careCard && user && (
        <CareCard helpHref={helpPath(user.role)} onDismiss={safety.dismissCareCard} />
      )}
      <form className="fb-stack" onSubmit={(e) => void onSubmit(e)} noValidate>
        <div className="fb-card fb-form">
          {entry ? (
            <p className="fb-card__title">
              {t("diary.entryFor", { date: day(entry.entry_date) })} ·{" "}
              {t("diary.savedAt", { time: time(entry.recorded_at) })}
            </p>
          ) : (
            <SelectField
              label={t("diary.date")}
              value={date}
              onChange={setDate}
              options={datesBetween(window.editable_from, window.today).map((d) => ({
                value: d,
                label: d === window.today ? t("diary.todayOption", { date: day(d) }) : day(d),
              }))}
            />
          )}
          <p className="fb-setting__hint">{t("diary.skipAnything")}</p>
        </div>
        {template.groups.map((g) => {
          const fields = g.fields.filter(
            (f) => f.type !== "note" && (!f.show_if || values[f.show_if] === true),
          );
          const noteField = g.fields.find((f) => f.type === "note");
          if (!fields.length && !noteField) return null;
          return (
            <section key={g.id} className="fb-card fb-diary-group" aria-label={g.label}>
              <h2 className="fb-card__title">{g.label}</h2>
              {fields.map((f) => (
                <FieldInput
                  key={f.id}
                  field={f}
                  template={template}
                  value={values[f.id]}
                  onChange={(v) => set(f.id, v)}
                />
              ))}
              {noteField && (
                <TextAreaField
                  label={noteField.label}
                  hint={noteField.hint ?? undefined}
                  value={note}
                  maxLength={template.note_max}
                  onChange={(e) => {
                    setSaved(false);
                    setNote(e.target.value);
                  }}
                />
              )}
            </section>
          );
        })}
        <HomeworkChecklist
          date={date}
          ticked={entry?.homework ?? []}
          value={homework}
          onChange={(ids) => {
            setSaved(false);
            setHomework(ids);
          }}
        />
        <div className="fb-card fb-form">
          <ErrorNotice error={error} />
          {saved && <Notice>{t("diary.saved")}</Notice>}
          <PrimaryButton type="submit" disabled={busy}>
            {t("diary.save")}
          </PrimaryButton>
        </div>
      </form>
      {entry && canShare && <SharePanel template={template} entry={entry} />}
      {entry && <Versions template={template} entry={entry} />}
    </>
  );
}

/** The diary card's Homework group (Plan §5.6, D69): open group homework for this day. */
function HomeworkChecklist({
  date,
  ticked,
  value,
  onChange,
}: {
  date: string;
  ticked: HomeworkItem[];
  value: string[];
  onChange: (ids: string[]) => void;
}) {
  const { t } = useTranslation();
  const q = useQuery({ queryKey: ["diary", "homework", date], queryFn: () => diary.homework(date) });
  const items = [...(q.data?.items ?? [])];
  for (const h of ticked) if (!items.some((i) => i.id === h.id)) items.push(h);
  if (items.length === 0) return null;
  return (
    <section className="fb-card fb-diary-group" aria-label={t("diary.homework.title")}>
      <h2 className="fb-card__title">{t("diary.homework.title")}</h2>
      <p className="fb-setting__hint">{t("diary.homework.hint")}</p>
      {items.map((h) => (
        <label key={h.id} className="fb-checkbox">
          <input
            type="checkbox"
            checked={value.includes(h.id)}
            onChange={(e) => onChange(e.target.checked ? [...value, h.id] : value.filter((x) => x !== h.id))}
          />
          <span>
            {h.title}
            {h.details && <span className="fb-setting__hint"> — {h.details}</span>}
          </span>
        </label>
      ))}
    </section>
  );
}

function ReadOnly({
  template,
  entry,
  canShare,
}: {
  template: DiaryTemplate;
  entry: DiaryEntry;
  canShare: boolean;
}) {
  const { t } = useTranslation();
  const { day, time } = useDateFormat();
  const text = useValueText(template);
  return (
    <>
      <div className="fb-card fb-stack">
        <p className="fb-card__title">
          {t("diary.entryFor", { date: day(entry.entry_date) })} ·{" "}
          {t("diary.savedAt", { time: time(entry.recorded_at) })}
        </p>
        <Notice>{t("diary.readOnly")}</Notice>
        <ValueList template={template} values={entry.values} note={entry.note} text={text} />
        {entry.homework.length > 0 && (
          <section className="fb-stack" aria-label={t("diary.homework.title")}>
            <h2 className="fb-card__title">{t("diary.homework.title")}</h2>
            <ul>
              {entry.homework.map((h) => (
                <li key={h.id}>{h.title}</li>
              ))}
            </ul>
          </section>
        )}
      </div>
      {canShare && <SharePanel template={template} entry={entry} />}
      <Versions template={template} entry={entry} />
    </>
  );
}

function Versions({ template, entry }: { template: DiaryTemplate; entry: DiaryEntry }) {
  const { t, i18n } = useTranslation();
  const [open, setOpen] = useState(false);
  const text = useValueText(template);
  const q = useQuery({
    queryKey: ["diary", "revisions", entry.id, entry.revision_no],
    queryFn: () => diary.revisions(entry.id),
    enabled: open,
  });
  if (entry.revision_no < 2) return null;
  return (
    <details className="fb-card" onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary>
        <History size={16} aria-hidden /> {t("diary.versions", { n: entry.revision_no })}
      </summary>
      <div className="fb-stack">
        {(q.data?.revisions ?? [])
          .slice()
          .reverse()
          .map((r) => (
            <section key={r.revision_no} className="fb-stack">
              <h3 className="fb-card__title">
                {t("diary.versionN", {
                  n: r.revision_no,
                  time: new Date(r.saved_at).toLocaleString(i18n.language),
                })}
              </h3>
              <ValueList template={template} values={r.values} note={r.note} text={text} />
            </section>
          ))}
      </div>
    </details>
  );
}
