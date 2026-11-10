/**
 * Therapist schedule (Plan §5.8 "Tasks & scheduling"; D69, D70): the group's diary expectation
 * (days per week) and group homework per role, with each assignee's status. Participants tick
 * homework in their diary; there is no overdue state anywhere. Lessons are never tasks (D24).
 * Joint-session scheduling arrives with Phase 8.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarDays, Check, ClipboardList } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { learn } from "../../api/learning";
import { therapist, type ParticipantRole, type Schedule, type TaskIn } from "../../api/therapist";
import { ErrorNotice, Notice, TextAreaField, TextField } from "../../components/Forms";
import { Chip, PrimaryButton } from "../../design";
import { useDateFormat } from "../../features/diary/util";
import { Section } from "../../features/lessons/common";
import { Page } from "../Page";
import { ChoiceGroup, GroupSelect } from "./common";
import { useGroupChoice } from "./groups";
import "../../features/diary/diary.css";
import "./therapist.css";

const DAYS = [1, 2, 3, 4, 5, 6, 7] as const;
const ROLES: ParticipantRole[] = ["adolescent", "caregiver"];

export function SchedulePage() {
  const { t } = useTranslation();
  const { groups, list, groupId, setGroupId } = useGroupChoice();
  const q = useQuery({
    queryKey: ["schedule", groupId],
    queryFn: () => therapist.schedule(groupId ?? ""),
    enabled: !!groupId,
  });
  return (
    <Page
      title={t("nav.schedule")}
      subtitle={t("therapist.schedule.subtitle")}
      icon={<CalendarDays size={22} />}
    >
      <div className="fb-stack">
        <ErrorNotice error={groups.error ?? q.error} />
        {groups.isSuccess && list.length === 0 && <p>{t("therapist.diary.noGroups")}</p>}
        <GroupSelect groups={list} value={groupId} onChange={setGroupId} />
        {q.data && groupId && (
          <>
            <Expectation groupId={groupId} value={q.data.diary_days_per_week} />
            <TaskForm groupId={groupId} />
            <TaskList groupId={groupId} schedule={q.data} />
          </>
        )}
      </div>
    </Page>
  );
}

function Expectation({ groupId, value }: { groupId: string; value: number }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  async function change(days: number) {
    setError(null);
    setSaved(false);
    try {
      await therapist.setDiaryDays(groupId, days);
      await qc.invalidateQueries({ queryKey: ["schedule", groupId] });
      setSaved(true);
    } catch (err) {
      setError(err);
    }
  }
  return (
    <section className="fb-card fb-stack" aria-labelledby="diary-expectation">
      <h2 id="diary-expectation" className="fb-card__title">
        {t("therapist.schedule.diaryTitle")}
      </h2>
      <p className="fb-setting__hint">{t("therapist.schedule.diaryHint")}</p>
      <ChoiceGroup
        label={t("therapist.schedule.daysPerWeek")}
        options={DAYS}
        value={value}
        onChange={(d) => void change(d)}
        format={(d) => (d === 7 ? t("therapist.schedule.daily") : String(d))}
      />
      <ErrorNotice error={error} />
      {saved && <Notice>{t("account.saved")}</Notice>}
    </section>
  );
}

function plusDays(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toLocaleDateString("sv-SE"); // YYYY-MM-DD in local time
}

function TaskForm({
  groupId,
  initial,
  taskId,
  onDone,
}: {
  groupId: string;
  initial?: TaskIn;
  taskId?: string;
  onDone?: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const skills = useQuery({ queryKey: ["learn", "skills"], queryFn: learn.skills });
  const [form, setForm] = useState<TaskIn>(
    initial ?? {
      title: "",
      details: null,
      for_roles: ["adolescent", "caregiver"],
      skill_ids: [],
      starts_on: plusDays(0),
      due_on: plusDays(6),
    },
  );
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  const update = (patch: Partial<TaskIn>) => {
    setSaved(false);
    setForm((f) => ({ ...f, ...patch }));
  };

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const body = { ...form, title: form.title.trim(), details: form.details?.trim() || null };
      if (taskId) await therapist.updateTask(taskId, body);
      else await therapist.createTask(groupId, body);
      await qc.invalidateQueries({ queryKey: ["schedule", groupId] });
      if (!taskId) setForm((f) => ({ ...f, title: "", details: null, skill_ids: [] }));
      setSaved(true);
      onDone?.();
    } catch (err) {
      setError(err);
    }
  }

  return (
    <form
      className="fb-card fb-form"
      onSubmit={(e) => void onSubmit(e)}
      noValidate
      aria-label={t(taskId ? "therapist.schedule.editTask" : "therapist.schedule.newTask")}
    >
      {!taskId && <h2 className="fb-card__title">{t("therapist.schedule.newTask")}</h2>}
      <TextField
        label={t("therapist.schedule.taskTitle")}
        value={form.title}
        maxLength={200}
        onChange={(e) => update({ title: e.target.value })}
      />
      <TextAreaField
        label={t("therapist.schedule.taskDetails")}
        hint={t("therapist.schedule.taskDetailsHint")}
        value={form.details ?? ""}
        maxLength={1000}
        onChange={(e) => update({ details: e.target.value })}
      />
      <fieldset className="fb-fieldset">
        <legend>{t("therapist.schedule.forRoles")}</legend>
        {ROLES.map((r) => (
          <label key={r} className="fb-checkbox">
            <input
              type="checkbox"
              checked={form.for_roles.includes(r)}
              onChange={(e) =>
                update({
                  for_roles: e.target.checked
                    ? ROLES.filter((x) => x === r || form.for_roles.includes(x))
                    : form.for_roles.filter((x) => x !== r),
                })
              }
            />
            {t(`role.${r}`)}
          </label>
        ))}
      </fieldset>
      <div className="fb-form--inline">
        <TextField
          label={t("therapist.schedule.startsOn")}
          type="date"
          value={form.starts_on}
          onChange={(e) => update({ starts_on: e.target.value })}
        />
        <TextField
          label={t("therapist.schedule.dueOn")}
          type="date"
          value={form.due_on}
          onChange={(e) => update({ due_on: e.target.value })}
        />
      </div>
      <details>
        <summary>{t("therapist.schedule.linkSkills", { n: form.skill_ids.length })}</summary>
        {(skills.data?.modules ?? []).map((m) => (
          <fieldset key={m.id} className="fb-fieldset">
            <legend>{m.name}</legend>
            {m.skills.map((s) => (
              <label key={s.id} className="fb-checkbox">
                <input
                  type="checkbox"
                  checked={form.skill_ids.includes(s.id)}
                  onChange={(e) =>
                    update({
                      skill_ids: e.target.checked
                        ? [...form.skill_ids, s.id]
                        : form.skill_ids.filter((x) => x !== s.id),
                    })
                  }
                />
                {s.name}
              </label>
            ))}
          </fieldset>
        ))}
      </details>
      <ErrorNotice error={error} />
      {saved && <Notice>{t("account.saved")}</Notice>}
      <PrimaryButton type="submit" disabled={!form.title.trim() || form.for_roles.length === 0}>
        {t(taskId ? "account.save" : "therapist.schedule.addTask")}
      </PrimaryButton>
    </form>
  );
}

function TaskList({ groupId, schedule }: { groupId: string; schedule: Schedule }) {
  const { t } = useTranslation();
  const { day } = useDateFormat();
  const qc = useQueryClient();
  const [editing, setEditing] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  async function archive(id: string) {
    setError(null);
    try {
      await therapist.archiveTask(id);
      await qc.invalidateQueries({ queryKey: ["schedule", groupId] });
    } catch (err) {
      setError(err);
    }
  }
  return (
    <Section title={t("therapist.schedule.homework")}>
      <ErrorNotice error={error} />
      {schedule.tasks.length === 0 && <p>{t("therapist.schedule.noTasks")}</p>}
      {schedule.tasks.map((task) => (
        <article key={task.id} className="fb-card fb-stack" data-testid="task">
          <h3 className="fb-card__title">
            <ClipboardList size={18} aria-hidden /> {task.title}
          </h3>
          <p className="fb-setting__hint">
            {t("therapist.schedule.window", { from: day(task.starts_on), to: day(task.due_on) })} ·{" "}
            {task.for_roles.map((r) => t(`role.${r}`)).join(", ")}
          </p>
          {task.details && <p>{task.details}</p>}
          <table className="fb-table">
            <caption className="visually-hidden">
              {t("therapist.schedule.statusCaption", { title: task.title })}
            </caption>
            <thead>
              <tr>
                <th scope="col">{t("therapist.families")}</th>
                <th scope="col">{t("therapist.schedule.person")}</th>
                <th scope="col">{t("therapist.schedule.status")}</th>
              </tr>
            </thead>
            <tbody>
              {task.assignees.map((a) => (
                <tr key={`${a.family_id}:${a.alias}`}>
                  <td>{a.family}</td>
                  <td>
                    {a.alias} <span className="fb-setting__hint">({t(`role.${a.role}`)})</span>
                  </td>
                  <td>
                    {a.done ? (
                      <Chip tone="outline" icon={<Check size={14} aria-hidden />}>
                        {t("homework.done")}
                      </Chip>
                    ) : (
                      <span className="fb-setting__hint">{t("therapist.schedule.notYet")}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {editing === task.id ? (
            <TaskForm
              groupId={groupId}
              taskId={task.id}
              initial={{
                title: task.title,
                details: task.details,
                for_roles: task.for_roles,
                skill_ids: task.skill_ids,
                starts_on: task.starts_on,
                due_on: task.due_on,
              }}
              onDone={() => setEditing(null)}
            />
          ) : (
            <div className="fb-actions">
              <button type="button" className="fb-btn fb-btn--secondary" onClick={() => setEditing(task.id)}>
                {t("therapist.schedule.edit")}
              </button>
              <button
                type="button"
                className="fb-btn fb-btn--secondary"
                onClick={() => void archive(task.id)}
              >
                {t("therapist.schedule.archive")}
              </button>
            </div>
          )}
        </article>
      ))}
    </Section>
  );
}
