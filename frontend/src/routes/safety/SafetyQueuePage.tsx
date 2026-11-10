/**
 * Clinician safety queue (Plan §5.7, §5.8; Phase 2 tasks 5, 6).
 * Therapists: events for their own groups' families, and a form to record an event by hand.
 * Admins: every event, read-only oversight (D39).
 * There is no SLA escalation (D38) and no SMS/email: the queue is the only channel (O12).
 */
import * as ToggleGroup from "@radix-ui/react-toggle-group";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ShieldAlert } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";
import { get, post } from "../../api/client";
import type {
  SafetyCategory,
  SafetyEventDetail,
  SafetyEventList,
  SafetySeverity,
  SafetySubject,
} from "../../api/types";
import { ROLE_HOME, useSession } from "../../app/session";
import { ErrorNotice, Notice, SelectField, TextAreaField } from "../../components/Forms";
import { List, ListRow, PrimaryButton } from "../../design";
import { Page } from "../Page";
import { SeverityChip, StatusChip } from "./format";
import { useAge } from "./time";

type Filter = "open" | "resolved" | "all";
const FILTERS: Filter[] = ["open", "resolved", "all"];

const MANUAL_CATEGORIES: SafetyCategory[] = [
  "risk_disclosure",
  "suspected_abuse",
  "parental_coercion",
  "privacy_breach",
  "discomfort_or_trauma_cue",
  "delayed_clinician_response",
];
const SEVERITIES: SafetySeverity[] = ["low", "medium", "high"];

function ManualEventForm({ onCreated }: { onCreated: (id: string) => void }) {
  const { t } = useTranslation();
  const subjects = useQuery({
    queryKey: ["safety", "subjects"],
    queryFn: () => get<SafetySubject[]>("/safety/subjects"),
  });
  const [subject, setSubject] = useState("");
  const [category, setCategory] = useState<SafetyCategory>("risk_disclosure");
  const [severity, setSeverity] = useState<SafetySeverity>("medium");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const chosen = subject || subjects.data?.[0]?.user.id || "";

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const d = await post<SafetyEventDetail>("/safety/events", {
        subject_user_id: chosen,
        category,
        severity,
        description: description.trim(),
      });
      setDescription("");
      onCreated(d.id);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="fb-card" aria-labelledby="manual-title">
      <h2 id="manual-title" className="fb-card__title">
        {t("safety.manualTitle")}
      </h2>
      <p className="fb-setting__hint">{t("safety.manualHint")}</p>
      <ErrorNotice error={subjects.error} />
      {subjects.data && subjects.data.length === 0 ? (
        <p>{t("safety.noSubjects")}</p>
      ) : (
        <form className="fb-form" onSubmit={onSubmit} noValidate>
          <SelectField
            label={t("safety.subject")}
            value={chosen}
            onChange={setSubject}
            options={(subjects.data ?? []).map((s) => ({
              value: s.user.id,
              label: `${s.user.alias} (${t(`role.${s.user.role}`)}) · ${s.family.label}`,
            }))}
          />
          <SelectField
            label={t("safety.categoryLabel")}
            value={category}
            onChange={(v) => setCategory(v as SafetyCategory)}
            options={MANUAL_CATEGORIES.map((c) => ({ value: c, label: t(`safety.category.${c}`) }))}
          />
          <SelectField
            label={t("safety.severityLabel")}
            value={severity}
            onChange={(v) => setSeverity(v as SafetySeverity)}
            options={SEVERITIES.map((s) => ({ value: s, label: t(`safety.severity.${s}`) }))}
          />
          <TextAreaField
            label={t("safety.description")}
            hint={t("safety.descriptionHint")}
            value={description}
            maxLength={2000}
            onChange={(e) => setDescription(e.target.value)}
          />
          <ErrorNotice error={error} />
          <div className="fb-actions">
            <PrimaryButton type="submit" disabled={busy || !chosen || !description.trim()}>
              {t("safety.record")}
            </PrimaryButton>
          </div>
        </form>
      )}
    </section>
  );
}

export function SafetyQueuePage() {
  const { t } = useTranslation();
  const user = useSession();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const age = useAge();
  const [filter, setFilter] = useState<Filter>("open");
  const q = useQuery({
    queryKey: ["safety", "events", filter],
    queryFn: () => get<SafetyEventList>(`/safety/events?status=${filter}`),
  });
  if (!user) return null;
  const isAdmin = user.role === "admin";
  const home = ROLE_HOME[user.role];

  return (
    <Page
      title={t(isAdmin ? "nav.safetyOversight" : "nav.safetyQueue")}
      subtitle={t(isAdmin ? "safety.oversightSubtitle" : "safety.queueSubtitle")}
      icon={<ShieldAlert size={22} />}
    >
      <div className="fb-stack">
        <Notice>{t(isAdmin ? "safety.oversightNotice" : "safety.queueNotice")}</Notice>
        <div className="fb-toolbar">
          <ToggleGroup.Root
            type="single"
            className="fb-segmented"
            aria-label={t("safety.filterLabel")}
            value={filter}
            onValueChange={(v) => {
              if (v) setFilter(v as Filter);
            }}
          >
            {FILTERS.map((f) => (
              <ToggleGroup.Item key={f} value={f}>
                {t(`safety.filter.${f}`)}
              </ToggleGroup.Item>
            ))}
          </ToggleGroup.Root>
          {q.data && (
            <span className="fb-setting__hint" aria-live="polite">
              {t("safety.counts", { new: q.data.counts.new, open: q.data.counts.open })}
            </span>
          )}
        </div>
        <ErrorNotice error={q.error} />
        {q.data &&
          (q.data.events.length === 0 ? (
            <p>{t(`safety.empty.${filter}`)}</p>
          ) : (
            <List label={t("safety.listLabel")}>
              {q.data.events.map((e) => (
                <ListRow
                  key={e.id}
                  title={`${t(`safety.category.${e.category}`)} · ${e.subject.alias}`}
                  subtitle={[
                    t(`role.${e.subject.role}`),
                    e.family?.label,
                    isAdmin ? e.family?.group_name : null,
                    t("safety.raised", { age: age(e.created_at) }),
                    e.occurrences > 1 ? t("safety.occurrences", { count: e.occurrences }) : null,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                  to={`${home}/safety/${e.id}`}
                  trailing={
                    <span className="fb-row__chips">
                      <SeverityChip severity={e.severity} />
                      <StatusChip status={e.status} />
                    </span>
                  }
                />
              ))}
            </List>
          ))}
        {!isAdmin && (
          <ManualEventForm
            onCreated={(id) => {
              void qc.invalidateQueries({ queryKey: ["safety"] });
              navigate(`${home}/safety/${id}`);
            }}
          />
        )}
      </div>
    </Page>
  );
}
