/**
 * Therapist: skills covered in a group session (Plan §5.5.3, D24). Minimal in Phase 5;
 * the full therapist dashboard comes in Phase 7. Participants see these under Group review.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { learn } from "../../api/learning";
import { ErrorNotice, TextField } from "../../components/Forms";
import { List, ListRow, PrimaryButton } from "../../design";

export function GroupSkillRecords({ groupId }: { groupId: string }) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const key = ["group-skill-records", groupId];
  const records = useQuery({ queryKey: key, queryFn: () => learn.groupRecords(groupId) });
  const skills = useQuery({ queryKey: ["learn", "skills"], queryFn: learn.skills });
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [picked, setPicked] = useState<string[]>([]);
  const [note, setNote] = useState("");
  const [error, setError] = useState<unknown>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await learn.createGroupRecord(groupId, {
        session_date: date,
        skill_ids: picked,
        note: note.trim() || null,
      });
      setPicked([]);
      setNote("");
      await qc.invalidateQueries({ queryKey: key });
    } catch (err) {
      setError(err);
    }
  }

  async function remove(id: string) {
    setError(null);
    try {
      await learn.deleteGroupRecord(groupId, id);
      await qc.invalidateQueries({ queryKey: key });
    } catch (err) {
      setError(err);
    }
  }

  return (
    <section className="fb-stack">
      <h2 className="fb-card__title">{t("therapist.skillRecords.title")}</h2>
      <p className="fb-setting__hint">{t("therapist.skillRecords.hint")}</p>
      <ErrorNotice error={error ?? records.error} />
      {(records.data?.records ?? []).length > 0 && (
        <List label={t("therapist.skillRecords.title")}>
          {(records.data?.records ?? []).map((r) => (
            <ListRow
              key={r.id}
              title={new Date(r.session_date).toLocaleDateString(i18n.language)}
              subtitle={r.skills.map((s) => s.name).join(" · ") + (r.note ? ` — ${r.note}` : "")}
              trailing={
                <button type="button" className="fb-btn fb-btn--secondary" onClick={() => void remove(r.id)}>
                  {t("therapist.skillRecords.remove")}
                </button>
              }
            />
          ))}
        </List>
      )}
      <form className="fb-card fb-form" onSubmit={(e) => void onSubmit(e)} noValidate>
        <TextField
          label={t("therapist.skillRecords.date")}
          type="date"
          value={date}
          onChange={(e) => setDate(e.target.value)}
        />
        <fieldset className="fb-fieldset">
          <legend>{t("therapist.skillRecords.skills")}</legend>
          {(skills.data?.modules ?? [])
            .filter((m) => m.id !== "orientation")
            .map((m) => (
              <details key={m.id}>
                <summary>{m.name}</summary>
                {m.skills.map((s) => (
                  <label key={s.id} className="fb-checkbox">
                    <input
                      type="checkbox"
                      checked={picked.includes(s.id)}
                      onChange={(e) =>
                        setPicked((p) => (e.target.checked ? [...p, s.id] : p.filter((x) => x !== s.id)))
                      }
                    />
                    {s.name}
                  </label>
                ))}
              </details>
            ))}
        </fieldset>
        <TextField
          label={t("therapist.skillRecords.note")}
          hint={t("therapist.skillRecords.noteHint")}
          maxLength={1000}
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
        <PrimaryButton type="submit" variant="secondary" disabled={picked.length === 0}>
          {t("therapist.skillRecords.add")}
        </PrimaryButton>
      </form>
    </section>
  );
}
