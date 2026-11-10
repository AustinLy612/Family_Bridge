/**
 * Feasibility indicators for the therapist's own group (Plan §5.8 "Metrics", §5.10). Counts and
 * rates only, never a per-person ranking. Therapists also enter the enrolment-funnel
 * denominators here (Phase 9); the full research export is an admin screen.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ClipboardCheck } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { METRIC_DAYS, therapist, type Metrics } from "../../api/therapist";
import { research } from "../../api/research";
import { ErrorNotice, Notice, TextField } from "../../components/Forms";
import { PrimaryButton } from "../../design";
import { Section } from "../../features/lessons/common";
import { Page } from "../Page";
import { ChoiceGroup, GroupSelect } from "./common";
import { useGroupChoice } from "./groups";
import "./therapist.css";

type Days = (typeof METRIC_DAYS)[number];

export function MetricsPage() {
  const { t } = useTranslation();
  const { groups, list, groupId, setGroupId } = useGroupChoice();
  const [days, setDays] = useState<Days>(28);
  const q = useQuery({
    queryKey: ["metrics", groupId, days],
    queryFn: () => therapist.metrics(groupId ?? "", days),
    enabled: !!groupId,
  });
  return (
    <Page
      title={t("nav.metrics")}
      subtitle={t("therapist.metrics.subtitle")}
      icon={<ClipboardCheck size={22} />}
    >
      <div className="fb-stack">
        <ErrorNotice error={groups.error ?? q.error} />
        {groups.isSuccess && list.length === 0 && <p>{t("therapist.diary.noGroups")}</p>}
        <GroupSelect groups={list} value={groupId} onChange={setGroupId} />
        <ChoiceGroup
          label={t("therapist.diary.range")}
          options={METRIC_DAYS}
          value={days}
          onChange={setDays}
          format={(d) => t("therapist.diary.days", { n: d })}
        />
        {q.data && <Tables m={q.data} />}
        {groupId && <RecruitmentSection groupId={groupId} />}
      </div>
    </Page>
  );
}

function pct(n: number, d: number): string {
  return d > 0 ? `${Math.round((n / d) * 100)}%` : "—";
}

function Table({ caption, rows }: { caption: string; rows: [string, string | number][] }) {
  return (
    <Section title={caption}>
      <table className="fb-table" data-testid="metrics-table">
        <caption className="visually-hidden">{caption}</caption>
        <tbody>
          {rows.map(([k, v]) => (
            <tr key={k}>
              <th scope="row">{k}</th>
              <td>{v}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Section>
  );
}

function counts(c: Record<string, number>, label: (k: string) => string): string {
  const parts = Object.entries(c).map(([k, n]) => `${label(k)}: ${n}`);
  return parts.length ? parts.join(", ") : "—";
}

function Tables({ m }: { m: Metrics }) {
  const { t } = useTranslation();
  const k = (key: string, o: Record<string, unknown> = {}) => t(`therapist.metrics.${key}`, o);
  const e = m.enrolment;
  const a = m.learning.adolescent;
  const c = m.learning.caregiver;
  const src = (s: string) => t(`therapist.learning.source.${s}`, s);
  return (
    <>
      <p className="fb-setting__hint">{k("window", { from: m.from, to: m.to })}</p>
      <Table
        caption={k("enrolment")}
        rows={[
          [k("families"), e.families],
          [k("invitations"), `${e.invitations_redeemed} / ${e.invitations_issued}`],
          [k("onboardedTeens"), `${e.by_role.adolescent.onboarded} / ${e.by_role.adolescent.members}`],
          [k("onboardedCarers"), `${e.by_role.caregiver.onboarded} / ${e.by_role.caregiver.members}`],
        ]}
      />
      <Table
        caption={k("diary", { n: m.diary.days_per_week })}
        rows={(["adolescent", "caregiver"] as const).flatMap((r) => {
          const d = m.diary[r];
          const who = t(`role.${r}`);
          return [
            [
              k("diaryDays", { who }),
              `${d.days_with_entries} / ${d.expected_days} (${pct(d.days_with_entries, d.expected_days)})`,
            ],
            [k("diaryEntries", { who }), d.entries],
            [k("diaryLater", { who }), d.added_later],
            [k("diaryCorrected", { who }), d.corrected],
          ] as [string, string | number][];
        })}
      />
      <Table
        caption={k("homework")}
        rows={[
          [k("tasks"), m.homework.tasks],
          [
            k("homeworkDone"),
            `${m.homework.done} / ${m.homework.assigned} (${pct(m.homework.done, m.homework.assigned)})`,
          ],
        ]}
      />
      <Table
        caption={k("teenLearning")}
        rows={[
          [k("started"), a.started],
          [k("completed"), a.completed],
          [k("stopped"), a.stopped],
          [k("stoppedSafety"), a.stopped_by_safety],
          [k("bySource"), counts(a.by_source, src)],
          [k("checkin"), `${a.checkin_answered} / ${a.checkin_skipped}`],
          [k("tests"), `${a.tests_mastered} / ${a.test_attempts}`],
          [k("mood"), `${a.mood_before_mean ?? "—"} → ${a.mood_after_mean ?? "—"}`],
        ]}
      />
      <Table
        caption={k("carerLearning")}
        rows={[
          [k("started"), c.started],
          [k("completed"), c.completed],
          [k("stopped"), c.stopped],
          [k("bySource"), counts(c.by_source, src)],
          [k("quiz"), `${c.quiz_correct} / ${c.quiz_answers}`],
        ]}
      />
      <Table
        caption={k("safety")}
        rows={[
          [k("events"), m.safety.events],
          [k("byCategory"), counts(m.safety.by_category, (s) => t(`safety.category.${s}`, s))],
          [
            k("ackSla", { h: m.safety.sla_hours }),
            `${m.safety.acknowledged_within_sla} / ${m.safety.acknowledged}`,
          ],
          [k("openNow"), m.safety.open_now],
        ]}
      />
      <Table
        caption={k("time")}
        rows={[
          ...m.therapist_time.families.map(
            (f) => [f.family, k("minutes", { n: f.minutes })] as [string, string],
          ),
          [
            k("median"),
            m.therapist_time.median_minutes === null
              ? "—"
              : k("minutes", { n: m.therapist_time.median_minutes }),
          ],
        ]}
      />
    </>
  );
}

const FUNNEL = ["screened", "eligible", "approached", "consented"] as const;

/**
 * Enrolment-funnel denominators (Plan §5.10, §8.4): counts of families for a period, entered by
 * the group's therapists. Saving the same period again replaces the figures (history is kept).
 */
function RecruitmentSection({ groupId }: { groupId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["recruitment", groupId],
    queryFn: () => research.recruitment(groupId),
  });
  const [form, setForm] = useState<Record<string, string>>({
    period_start: "",
    period_end: "",
    screened: "",
    eligible: "",
    approached: "",
    consented: "",
  });
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  const set = (k: string, v: string) => {
    setSaved(false);
    setForm((f) => ({ ...f, [k]: v }));
  };
  const complete = Object.values(form).every((v) => v !== "");

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await research.addRecruitment(groupId, {
        period_start: form.period_start ?? "",
        period_end: form.period_end ?? "",
        screened: Number(form.screened),
        eligible: Number(form.eligible),
        approached: Number(form.approached),
        consented: Number(form.consented),
      });
      setSaved(true);
      await qc.invalidateQueries({ queryKey: ["recruitment", groupId] });
    } catch (err) {
      setError(err);
    }
  }

  const items = q.data?.items ?? [];
  return (
    <Section title={t("therapist.recruitment.title")}>
      <p className="fb-setting__hint">{t("therapist.recruitment.hint")}</p>
      <form className="fb-stack" onSubmit={(e) => void submit(e)} noValidate>
        <div className="fb-recruit-grid">
          <TextField
            label={t("therapist.recruitment.periodStart")}
            type="date"
            value={form.period_start ?? ""}
            onChange={(e) => set("period_start", e.target.value)}
          />
          <TextField
            label={t("therapist.recruitment.periodEnd")}
            type="date"
            value={form.period_end ?? ""}
            onChange={(e) => set("period_end", e.target.value)}
          />
          {FUNNEL.map((k) => (
            <TextField
              key={k}
              label={t(`therapist.recruitment.${k}`)}
              type="number"
              min={0}
              inputMode="numeric"
              value={form[k] ?? ""}
              onChange={(e) => set(k, e.target.value)}
            />
          ))}
        </div>
        <ErrorNotice error={error ?? q.error} />
        {saved && <Notice>{t("therapist.recruitment.saved")}</Notice>}
        <div>
          <PrimaryButton type="submit" disabled={!complete}>
            {t("therapist.recruitment.save")}
          </PrimaryButton>
        </div>
      </form>
      {items.length > 0 && (
        <table
          className="fb-table"
          aria-label={t("therapist.recruitment.title")}
          data-testid="recruitment-table"
        >
          <thead>
            <tr>
              <th scope="col">{t("therapist.recruitment.period")}</th>
              {FUNNEL.map((k) => (
                <th key={k} scope="col">
                  {t(`therapist.recruitment.${k}`)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {items.map((r) => (
              <tr key={r.id}>
                <td>
                  {r.period_start} – {r.period_end}
                </td>
                {FUNNEL.map((k) => (
                  <td key={k}>{r[k]}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Section>
  );
}
