/**
 * Component gallery (Plan Phase 0 task 5; §5.13.4). Development builds only.
 * Shows every base component inside the real app shell, switchable between zh-CN / en
 * (header language switch), default / calm palette, and participant / therapist density.
 * All content is demo text. Sign-off by the project lead is a Phase 0 acceptance criterion.
 */
import "./gallery.css";
import * as ToggleGroup from "@radix-ui/react-toggle-group";
import {
  BookOpen,
  Clock,
  Dumbbell,
  LayoutGrid,
  NotebookPen,
  Palette,
  Sparkles,
  UsersRound,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";
import { useAccessibility, type Density } from "../app/accessibility";
import { AppShell } from "../app/AppShell";
import { ROLES, type Role } from "../app/session";
import {
  CalendarGrid,
  Chip,
  DecisionButtons,
  DetailBar,
  HeroBanner,
  List,
  ListRow,
  PlaceholderArt,
  PrimaryButton,
  PrivacyChip,
  ProfileHeader,
  ProgressBar,
  ProvenanceChip,
  SelectCard,
  StatTile,
  type CalendarDay,
  type CardTone,
} from "../design";

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="gallery-section" aria-label={title}>
      <h2 className="gallery-section__title">{title}</h2>
      <div className="gallery-section__body">{children}</div>
    </section>
  );
}

function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
}) {
  return (
    <ToggleGroup.Root
      type="single"
      className="fb-segmented"
      aria-label={label}
      value={value}
      onValueChange={(v) => {
        if (v) onChange(v as T);
      }}
    >
      {options.map((o) => (
        <ToggleGroup.Item key={o.value} value={o.value}>
          {o.label}
        </ToggleGroup.Item>
      ))}
    </ToggleGroup.Root>
  );
}

const DEMO_DAYS: CalendarDay[] = Array.from({ length: 28 }, (_, i) => {
  const d = new Date(Date.UTC(2026, 9, 12 + i));
  return {
    date: d.toISOString().slice(0, 10),
    filled: [0, 1, 2, 4, 5, 8, 9, 11, 14, 15, 16, 19, 22, 23, 26].includes(i),
  };
});

export default function Gallery() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { settings, update, density, setDensity, illustrationsVisible } = useAccessibility();
  const [role, setRole] = useState<Role>("adolescent");
  const [selected, setSelected] = useState<string>("mindfulness");
  const [lastDecision, setLastDecision] = useState<string | null>(null);

  const modules: { id: string; key: string; tone: CardTone }[] = [
    { id: "mindfulness", key: "moduleMindfulness", tone: "lavender" },
    { id: "distress", key: "moduleDistress", tone: "pink" },
    { id: "emotion", key: "moduleEmotion", tone: "amber" },
    { id: "middle", key: "moduleMiddlePath", tone: "blue" },
  ];

  const rail = (
    <>
      <StatTile icon={<BookOpen size={20} />} value={3} caption={t("gallery.demo.statLessons")} />
      <StatTile icon={<Sparkles size={20} />} value={5} caption={t("gallery.demo.statSkills")} />
      <StatTile icon={<NotebookPen size={20} />} value={4} caption={t("gallery.demo.statDiary")} />
    </>
  );

  return (
    <AppShell
      role={role}
      alias={t("gallery.demo.profileAlias")}
      title={t("gallery.title")}
      subtitle={t("gallery.subtitle")}
      icon={<LayoutGrid size={20} />}
      tag={t("gallery.sampleText")}
      showBack
      headerPills={
        <Chip tone="outline" icon={<Clock size={14} aria-hidden />}>
          {t("time.minutes", { count: 10 })}
        </Chip>
      }
      visibility={{ kind: "onlyYou" }}
      rail={rail}
      onLogout={() => navigate("/")}
    >
      <div className="gallery-controls fb-card">
        <label className="gallery-control">
          <span>{t("gallery.shellRole")}</span>
          <Segmented
            label={t("gallery.shellRole")}
            value={role}
            options={ROLES.map((r) => ({ value: r, label: t(`role.${r}`) }))}
            onChange={setRole}
          />
        </label>
        <div className="gallery-control">
          <span>{t("gallery.palette")}</span>
          <Segmented
            label={t("gallery.palette")}
            value={settings.calmPalette ? "calm" : "default"}
            options={[
              { value: "default", label: t("gallery.paletteDefault") },
              { value: "calm", label: t("gallery.paletteCalm") },
            ]}
            onChange={(v) => update({ calmPalette: v === "calm" })}
          />
        </div>
        <div className="gallery-control">
          <span>{t("gallery.density")}</span>
          <Segmented<Density>
            label={t("gallery.density")}
            value={density}
            options={[
              { value: "participant", label: t("gallery.densityParticipant") },
              { value: "therapist", label: t("gallery.densityTherapist") },
            ]}
            onChange={setDensity}
          />
        </div>
      </div>

      <Section title={t("gallery.sections.hero")}>
        <HeroBanner
          title={t("gallery.demo.heroTitle")}
          body={t("gallery.demo.heroBody")}
          action={<PrimaryButton>{t("gallery.demo.heroAction")}</PrimaryButton>}
          headingLevel={3}
        />
      </Section>

      <Section title={t("gallery.sections.stat")}>
        <div className="gallery-row">{rail}</div>
      </Section>

      <Section title={t("gallery.sections.select")}>
        <div className="fb-select-grid" role="radiogroup" aria-label={t("gallery.sections.select")}>
          {modules.map((m) => (
            <SelectCard
              key={m.id}
              mode="radio"
              tone={m.tone}
              title={t(`gallery.demo.${m.key}`)}
              caption={t("gallery.demo.moduleCaption")}
              selected={selected === m.id}
              onSelect={() => setSelected(m.id)}
            />
          ))}
        </div>
      </Section>

      <Section title={t("gallery.sections.detail")}>
        <DetailBar
          items={[
            {
              icon: <Clock size={18} />,
              label: t("gallery.demo.detailTime"),
              value: t("time.minutes", { count: 10 }),
            },
            {
              icon: <Sparkles size={18} />,
              label: t("gallery.demo.detailSkill"),
              value: t("gallery.demo.moduleMindfulness"),
            },
            {
              icon: <Dumbbell size={18} />,
              label: t("gallery.demo.detailPractice"),
              value: t("gallery.demo.detailPracticeValue"),
            },
          ]}
        >
          <PrimaryButton>{t("gallery.demo.heroAction")}</PrimaryButton>
        </DetailBar>
        <div className="fb-card gallery-invite">
          <h3>{t("gallery.demo.inviteTitle")}</h3>
          <DecisionButtons
            acceptLabel={t("gallery.demo.accept")}
            declineLabel={t("gallery.demo.decline")}
            onAccept={() => setLastDecision("accept")}
            onDecline={() => setLastDecision("decline")}
          />
          <span className="visually-hidden" role="status">
            {lastDecision ?? ""}
          </span>
        </div>
        <div className="gallery-row">
          <PrimaryButton variant="secondary">{t("shell.back")}</PrimaryButton>
          {role === "therapist" && (
            <PrimaryButton variant="danger">{t("gallery.demo.endSession")}</PrimaryButton>
          )}
        </div>
      </Section>

      <Section title={t("gallery.sections.chip")}>
        <div className="gallery-row">
          <Chip>{t("gallery.demo.moduleEmotion")}</Chip>
          <ProvenanceChip kind="ai" />
          <ProvenanceChip kind="authored" />
          <ProvenanceChip kind="general" />
          <PrivacyChip visibility={{ kind: "onlyYou" }} />
          <PrivacyChip visibility={{ kind: "therapist" }} />
          <PrivacyChip visibility={{ kind: "shared", alias: "Sam" }} />
        </div>
      </Section>

      <Section title={t("gallery.sections.list")}>
        <List label={t("gallery.sections.list")}>
          <ListRow
            icon={<UsersRound size={18} />}
            title={t("gallery.demo.listTitle")}
            subtitle={t("gallery.demo.listSubtitle")}
            onClick={() => undefined}
          />
          <ListRow
            icon={<BookOpen size={18} />}
            title={t("gallery.demo.listTitle2")}
            subtitle={t("gallery.demo.listSubtitle2")}
            onClick={() => undefined}
          />
        </List>
      </Section>

      <Section title={t("gallery.sections.progress")}>
        <ProgressBar current={2} total={5} />
        <ProgressBar current={4} total={5} tone="lavender" />
      </Section>

      {(role === "therapist" || role === "admin") && (
        <Section title={t("gallery.sections.calendar")}>
          <CalendarGrid label={t("gallery.demo.calendarLabel")} days={DEMO_DAYS} />
        </Section>
      )}

      <Section title={t("gallery.sections.profile")}>
        <ProfileHeader
          alias={t("gallery.demo.profileAlias")}
          pills={
            <>
              <Chip>{t(`role.${role}`)}</Chip>
              <Chip tone="outline" icon={<Palette size={14} aria-hidden />}>
                {settings.calmPalette ? t("gallery.paletteCalm") : t("gallery.paletteDefault")}
              </Chip>
            </>
          }
        />
      </Section>

      <Section title={t("gallery.sections.art")}>
        {illustrationsVisible ? (
          <div className="gallery-row">
            <figure className="gallery-art">
              <PlaceholderArt slot="hero" />
              <figcaption>{t("gallery.demo.artHero")}</figcaption>
            </figure>
            <figure className="gallery-art">
              <span className="fb-avatar">
                <PlaceholderArt slot="avatar" />
              </span>
              <figcaption>{t("gallery.demo.artAvatar")}</figcaption>
            </figure>
            <figure className="gallery-art">
              <PlaceholderArt slot="empty" />
              <figcaption>{t("gallery.demo.artEmpty")}</figcaption>
            </figure>
          </div>
        ) : (
          <p className="fb-setting__hint">{t("settings.illustrationsHint")}</p>
        )}
      </Section>
    </AppShell>
  );
}
