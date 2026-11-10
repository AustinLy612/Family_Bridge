/** ListRow and the therapist-only CalendarGrid (Plan §5.13.2). */
import { Check, ChevronRight } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

export function List({ children, label }: { children: ReactNode; label?: string }) {
  return (
    <ul className="fb-list" aria-label={label}>
      {children}
    </ul>
  );
}

export function ListRow({
  icon,
  title,
  subtitle,
  to,
  onClick,
  trailing,
}: {
  icon?: ReactNode;
  title: string;
  subtitle?: string;
  to?: string;
  onClick?: () => void;
  trailing?: ReactNode;
}) {
  const interactive = !!to || !!onClick;
  const inner = (
    <>
      {icon && (
        <span className="fb-icon-tile" aria-hidden>
          {icon}
        </span>
      )}
      <span className="fb-row__text">
        <span className="fb-row__title">{title}</span>
        {subtitle && <span className="fb-row__subtitle">{subtitle}</span>}
      </span>
      {trailing}
      {interactive && <ChevronRight size={20} aria-hidden />}
    </>
  );
  return (
    <li>
      {!interactive ? (
        <div className="fb-row fb-row--static">{inner}</div>
      ) : to ? (
        <Link className="fb-row" to={to}>
          {inner}
        </Link>
      ) : (
        <button type="button" className="fb-row" onClick={onClick}>
          {inner}
        </button>
      )}
    </li>
  );
}

export interface CalendarDay {
  date: string; // ISO yyyy-mm-dd
  filled: boolean;
}

/**
 * THERAPIST VIEW ONLY (Plan §5.13.2): diary completion / practice coverage. Missing days are a
 * neutral empty cell, never red. Participant-facing activity calendars are excluded (§5.13.3).
 */
export function CalendarGrid({ label, days }: { label: string; days: CalendarDay[] }) {
  const { t, i18n } = useTranslation();
  const fmt = new Intl.DateTimeFormat(i18n.language, {
    month: "short",
    day: "numeric",
  });
  const filled = t("gallery.demo.calendarFilled");
  const empty = t("gallery.demo.calendarEmpty");
  return (
    <figure className="fb-calendar">
      <figcaption className="fb-calendar__caption">{label}</figcaption>
      <ul className="fb-calendar__grid">
        {days.map((d) => (
          <li
            key={d.date}
            className={`fb-calendar__cell${d.filled ? " fb-calendar__cell--filled" : ""}`}
            aria-label={`${fmt.format(new Date(`${d.date}T00:00:00`))}: ${d.filled ? filled : empty}`}
          >
            {d.filled && <Check size={14} strokeWidth={3} aria-hidden />}
          </li>
        ))}
      </ul>
      <div className="fb-calendar__legend" aria-hidden>
        <span>
          <span className="fb-calendar__swatch fb-calendar__cell--filled" />
          {filled}
        </span>
        <span>
          <span className="fb-calendar__swatch" />
          {empty}
        </span>
      </div>
    </figure>
  );
}
