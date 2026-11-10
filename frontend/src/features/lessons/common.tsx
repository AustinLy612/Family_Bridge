/**
 * Shared pieces of the Phase 5 learning screens (Plan §5.5, §5.13).
 * Non-competitive by construction: no counts compared with anyone, no scores, no due dates.
 */
import { useQuery } from "@tanstack/react-query";
import { BookOpen, History } from "lucide-react";
import { useId, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";
import type { ContentSource } from "../../api/types";
import { learn, type HistoryItem, type Outcome } from "../../api/learning";
import { TextAreaField } from "../../components/Forms";
import { Chip, List, ListRow, PrimaryButton, ProvenanceChip, provenanceOf } from "../../design";
import "./lessons.css";

const MOODS = [1, 2, 3, 4, 5] as const;
const FACES: Record<number, string> = { 1: "😞", 2: "🙁", 3: "😐", 4: "🙂", 5: "😄" };

/** 1-5 mood with an optional note (Plan §5.5.1 step 1). */
export function MoodPicker({
  title,
  submitLabel,
  busy,
  onSubmit,
}: {
  title: string;
  submitLabel: string;
  busy?: boolean;
  onSubmit: (value: number, note: string) => void;
}) {
  const { t } = useTranslation();
  const [value, setValue] = useState<number | null>(null);
  const [note, setNote] = useState("");
  const labelId = useId();
  return (
    <form
      className="fb-card fb-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (value) onSubmit(value, note.trim());
      }}
    >
      <h2 id={labelId} className="fb-card__title">
        {title}
      </h2>
      <div className="fb-mood" role="radiogroup" aria-labelledby={labelId}>
        {MOODS.map((m) => (
          <button
            key={m}
            type="button"
            role="radio"
            aria-checked={value === m}
            className={`fb-mood__option${value === m ? " fb-mood__option--on" : ""}`}
            onClick={() => setValue(m)}
          >
            <span aria-hidden>{FACES[m]}</span>
            <span className="fb-mood__label">{t(`learn.mood.${m}`)}</span>
          </button>
        ))}
      </div>
      <TextAreaField
        label={t("learn.mood.note")}
        hint={t("learn.mood.noteHint")}
        value={note}
        maxLength={500}
        onChange={(e) => setNote(e.target.value)}
      />
      <PrimaryButton type="submit" disabled={!value || busy}>
        {submitLabel}
      </PrimaryButton>
    </form>
  );
}

export function SourceChip({ source }: { source: ContentSource | null | undefined }) {
  const kind = source ? provenanceOf(source) : null;
  return kind ? <ProvenanceChip kind={kind} /> : null;
}

export function OutcomeChip({ outcome }: { outcome: Outcome }) {
  const { t } = useTranslation();
  return <Chip tone={outcome === "understood" ? "blue" : "lavender"}>{t(`learn.outcome.${outcome}`)}</Chip>;
}

export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="fb-stack">
      <h2 className="fb-card__title">{title}</h2>
      {children}
    </section>
  );
}

/** Skills you've practised: what and when, never how much compared with anyone (§5.13). */
export function ProgressSection() {
  const { t, i18n } = useTranslation();
  const q = useQuery({ queryKey: ["learn", "progress"], queryFn: learn.progress });
  const date = (s: string) => new Date(s).toLocaleDateString(i18n.language);
  const items = q.data?.skills ?? [];
  return (
    <Section title={t("learn.progress.title")}>
      {items.length === 0 ? (
        <p className="fb-setting__hint">{t("learn.progress.empty")}</p>
      ) : (
        <List label={t("learn.progress.title")}>
          {items.map((p) => (
            <ListRow
              key={p.skill.id}
              icon={<BookOpen size={20} aria-hidden />}
              title={p.skill.name}
              subtitle={`${p.skill.module} · ${t("learn.progress.last", { date: date(p.last_practised_at) })}`}
              trailing={<OutcomeChip outcome={p.outcome} />}
            />
          ))}
        </List>
      )}
    </Section>
  );
}

/** The participant's own past lessons (D57). */
export function HistorySection({ hrefFor }: { hrefFor: (item: HistoryItem) => string }) {
  const { t, i18n } = useTranslation();
  const q = useQuery({ queryKey: ["learn", "history"], queryFn: learn.history });
  const items = q.data?.lessons ?? [];
  return (
    <Section title={t("learn.history.title")}>
      {items.length === 0 ? (
        <p className="fb-setting__hint">{t("learn.history.empty")}</p>
      ) : (
        <List label={t("learn.history.title")}>
          {items.slice(0, 20).map((h) => (
            <ListRow
              key={h.id}
              icon={<History size={20} aria-hidden />}
              title={h.skill.name}
              subtitle={`${new Date(h.started_at).toLocaleDateString(i18n.language)} · ${t(`learn.status.${h.status}`)}`}
              to={hrefFor(h)}
            />
          ))}
        </List>
      )}
    </Section>
  );
}

/** One open lesson at a time (D56): continue it or close it, no penalty either way. */
export function OpenLessonCard({
  skillName,
  href,
  onClose,
}: {
  skillName: string | null;
  href: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="fb-card fb-stack" data-testid="open-lesson">
      <h2 className="fb-card__title">{t("learn.open.title")}</h2>
      <p>{skillName ? t("learn.open.bodySkill", { skill: skillName }) : t("learn.open.body")}</p>
      <div className="fb-actions">
        <Link className="fb-btn fb-btn--primary" to={href}>
          {t("learn.open.continue")}
        </Link>
        <button type="button" className="fb-btn fb-btn--secondary" onClick={onClose}>
          {t("learn.open.close")}
        </button>
      </div>
      <p className="fb-setting__hint">{t("learn.open.hint")}</p>
    </div>
  );
}
