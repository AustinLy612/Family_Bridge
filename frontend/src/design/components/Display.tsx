/**
 * Display components (Plan §5.13.2): HeroBanner, StatTile, SelectCard, DetailBar,
 * ProgressBar, ProfileHeader.
 */
import { Check } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useAccessibility } from "../../app/accessibility";
import { PlaceholderArt } from "./PlaceholderArt";

export function HeroBanner({
  title,
  body,
  action,
  headingLevel = 2,
}: {
  title: string;
  body?: string;
  action?: ReactNode;
  headingLevel?: 1 | 2 | 3;
}) {
  const { illustrationsVisible } = useAccessibility();
  const H = `h${headingLevel}` as const;
  return (
    <section className="fb-hero">
      <div className="fb-hero__text">
        <H className="fb-hero__title">{title}</H>
        {body && <p>{body}</p>}
        {action && <div>{action}</div>}
      </div>
      {illustrationsVisible && <PlaceholderArt slot="hero" className="fb-hero__art" />}
    </section>
  );
}

/**
 * Neutral, non-decreasing counts only (lessons completed, skills explored, entries this week).
 * Deliberately has no target, goal, delta or streak props (Plan §5.13.2–3).
 */
export function StatTile({ icon, value, caption }: { icon: ReactNode; value: number; caption: string }) {
  return (
    <div className="fb-stat">
      <span className="fb-stat__icon" aria-hidden>
        {icon}
      </span>
      <span>
        <span className="fb-stat__value">{value}</span>
        <span className="fb-stat__caption">{caption}</span>
      </span>
    </div>
  );
}

export type CardTone = "pink" | "amber" | "blue" | "lavender";

/**
 * Tall coloured selection card. Selected = amber border + ink check badge + aria state, never
 * colour alone (Plan §5.13.2). `mode="radio"` inside a role="radiogroup"; `mode="toggle"` otherwise.
 */
export function SelectCard({
  title,
  caption,
  tone = "lavender",
  selected,
  onSelect,
  mode = "toggle",
}: {
  title: string;
  caption?: string;
  tone?: CardTone;
  selected: boolean;
  onSelect: () => void;
  mode?: "toggle" | "radio";
}) {
  const aria =
    mode === "radio" ? { role: "radio" as const, "aria-checked": selected } : { "aria-pressed": selected };
  return (
    <button type="button" className={`fb-select fb-select--${tone}`} onClick={onSelect} {...aria}>
      {selected && (
        <span className="fb-select__check" aria-hidden>
          <Check size={18} strokeWidth={3} />
        </span>
      )}
      <span className="fb-select__title">{title}</span>
      {caption && <span className="fb-select__caption">{caption}</span>}
    </button>
  );
}

export interface Detail {
  icon: ReactNode;
  label: string;
  value: string;
}

/** Icon + label/value pairs with an optional action area (lesson intro, invitation card). */
export function DetailBar({ items, children }: { items: Detail[]; children?: ReactNode }) {
  return (
    <div className="fb-detail">
      <dl className="fb-detail__items">
        {items.map((d) => (
          <div className="fb-detail__item" key={d.label}>
            <span className="fb-icon-tile" aria-hidden>
              {d.icon}
            </span>
            <span>
              <dt>{d.label}</dt>
              <dd>{d.value}</dd>
            </span>
          </div>
        ))}
      </dl>
      {children}
    </div>
  );
}

/**
 * Progress WITHIN one lesson or episode only ("Step 2 of 5"); never a cross-day or cross-person
 * comparison (Plan §5.13.2). Always labelled with text, so the bar colour is supplementary.
 */
export function ProgressBar({
  current,
  total,
  tone = "amber",
}: {
  current: number;
  total: number;
  tone?: "amber" | "lavender";
}) {
  const { t } = useTranslation();
  const safeTotal = Math.max(1, total);
  const clamped = Math.min(Math.max(0, current), safeTotal);
  const label = t("progress.stepOf", { current: clamped, total: safeTotal });
  return (
    <div className={`fb-progress${tone === "lavender" ? " fb-progress--alt" : ""}`}>
      <span className="fb-progress__label" aria-hidden>
        {label}
      </span>
      <div
        className="fb-progress__track"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={safeTotal}
        aria-valuenow={clamped}
        aria-valuetext={label}
        aria-label={label}
      >
        <div className="fb-progress__fill" style={{ width: `${(clamped / safeTotal) * 100}%` }} />
      </div>
    </div>
  );
}

/** Avatar + alias + info pills. No follower counts, no bio (Plan §5.13.2). */
export function ProfileHeader({ alias, pills }: { alias: string; pills: ReactNode }) {
  const { illustrationsVisible } = useAccessibility();
  return (
    <div className="fb-profile">
      <span className="fb-avatar fb-avatar--lg" aria-hidden>
        {illustrationsVisible && <PlaceholderArt slot="avatar" size={72} />}
      </span>
      <div className="fb-profile__text">
        <span className="fb-profile__alias">{alias}</span>
        <div className="fb-profile__pills">{pills}</div>
      </div>
    </div>
  );
}
