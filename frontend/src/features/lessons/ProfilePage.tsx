/**
 * Adolescent profile questionnaire (Plan §5.5.1 step 0). Only age and grade are required.
 * Private: never shown to caregivers; the therapist can read it (D15).
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { UserRound } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { learn, type Gender, type LearnerProfile, type ProfileOptions } from "../../api/learning";
import { ErrorNotice, Notice, SelectField, TextField } from "../../components/Forms";
import { PrimaryButton, SelectCard } from "../../design";
import { Page } from "../../routes/Page";
import { Section } from "./common";

const EMPTY: LearnerProfile = {
  gender: null,
  age: 15,
  grade: "",
  hobby_tags: [],
  concern_tags: [],
  other_hobby_text: null,
  other_concern_text: null,
};

function Tags({
  title,
  hint,
  group,
  all,
  value,
  max,
  onChange,
}: {
  title: string;
  hint: string;
  group: "hobby" | "concern";
  all: string[];
  value: string[];
  max: number;
  onChange: (v: string[]) => void;
}) {
  const { t } = useTranslation();
  const toggle = (tag: string) => {
    if (value.includes(tag)) return onChange(value.filter((x) => x !== tag));
    if (tag === "prefer_not_to_say") return onChange([tag]);
    const rest = value.filter((x) => x !== "prefer_not_to_say");
    if (rest.length >= max) return;
    onChange([...rest, tag]);
  };
  return (
    <Section title={title}>
      <p className="fb-setting__hint">{hint}</p>
      <div className="fb-select-grid">
        {all.map((tag) => (
          <SelectCard
            key={tag}
            title={t(`learn.profile.${group}.${tag}`)}
            selected={value.includes(tag)}
            onSelect={() => toggle(tag)}
          />
        ))}
      </div>
    </Section>
  );
}

export function ProfilePage() {
  const { t } = useTranslation();
  const q = useQuery({ queryKey: ["learn", "profile"], queryFn: learn.profile });
  return (
    <Page title={t("nav.profile")} subtitle={t("learn.profile.subtitle")} icon={<UserRound size={22} />}>
      {q.data && <ProfileForm initial={q.data.profile ?? EMPTY} opts={q.data.options} />}
      <ErrorNotice error={q.error} />
    </Page>
  );
}

function ProfileForm({ initial, opts }: { initial: LearnerProfile; opts: ProfileOptions }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [form, setForm] = useState<LearnerProfile>(initial);
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  const update = (patch: Partial<LearnerProfile>) => {
    setSaved(false);
    setForm((f) => ({ ...f, ...patch }));
  };

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const out = await learn.saveProfile({
        ...form,
        other_hobby_text: form.other_hobby_text?.trim() || null,
        other_concern_text: form.other_concern_text?.trim() || null,
      });
      qc.setQueryData(["learn", "profile"], out);
      setSaved(true);
    } catch (err) {
      setError(err);
    }
  }

  return (
    <>
      {
        <form className="fb-stack" onSubmit={(e) => void onSubmit(e)} noValidate>
          <div className="fb-card fb-form">
            <TextField
              label={t("learn.profile.age")}
              type="number"
              min={opts.age_min}
              max={opts.age_max}
              value={String(form.age)}
              onChange={(e) => update({ age: Number(e.target.value) })}
            />
            <SelectField
              label={t("learn.profile.grade")}
              value={form.grade}
              onChange={(v) => update({ grade: v })}
              options={[
                { value: "", label: t("learn.profile.chooseGrade") },
                ...opts.grades.map((g) => ({ value: g, label: t(`learn.profile.grades.${g}`) })),
              ]}
            />
            <SelectField
              label={t("learn.profile.gender")}
              value={form.gender ?? ""}
              onChange={(v) => update({ gender: (v || null) as Gender | null })}
              options={[
                { value: "", label: t("learn.profile.optional") },
                ...opts.genders.map((g) => ({ value: g, label: t(`learn.profile.genders.${g}`) })),
              ]}
            />
          </div>
          <Tags
            title={t("learn.profile.hobbies")}
            hint={t("learn.profile.upTo", { n: opts.max_tags })}
            group="hobby"
            all={opts.hobby_tags}
            value={form.hobby_tags}
            max={opts.max_tags}
            onChange={(v) => update({ hobby_tags: v })}
          />
          <div className="fb-card fb-form">
            <TextField
              label={t("learn.profile.otherHobby")}
              hint={t("learn.profile.optional")}
              maxLength={100}
              value={form.other_hobby_text ?? ""}
              onChange={(e) => update({ other_hobby_text: e.target.value })}
            />
          </div>
          <Tags
            title={t("learn.profile.concerns")}
            hint={t("learn.profile.upTo", { n: opts.max_tags })}
            group="concern"
            all={opts.concern_tags}
            value={form.concern_tags}
            max={opts.max_tags}
            onChange={(v) => update({ concern_tags: v })}
          />
          <div className="fb-card fb-form">
            <TextField
              label={t("learn.profile.otherConcern")}
              hint={t("learn.profile.optional")}
              maxLength={100}
              value={form.other_concern_text ?? ""}
              onChange={(e) => update({ other_concern_text: e.target.value })}
            />
            <p className="fb-setting__hint">{t("learn.profile.privacy")}</p>
            <ErrorNotice error={error} />
            {saved && <Notice>{t("account.saved")}</Notice>}
            <PrimaryButton type="submit" disabled={!form.grade}>
              {t("account.save")}
            </PrimaryButton>
          </div>
        </form>
      }
    </>
  );
}
