/** Small building blocks shared by the Phase 7 therapist screens. */
import { useId } from "react";
import { useTranslation } from "react-i18next";
import type { GroupSummary } from "../../api/types";
import { SelectField } from "../../components/Forms";

export function GroupSelect({
  groups,
  value,
  onChange,
}: {
  groups: GroupSummary[];
  value: string | null;
  onChange: (id: string) => void;
}) {
  const { t } = useTranslation();
  if (groups.length < 2 || !value) return null;
  return (
    <SelectField
      label={t("therapist.dash.group")}
      value={value}
      onChange={onChange}
      options={groups.map((g) => ({ value: g.id, label: g.name }))}
    />
  );
}

/** A row of toggle buttons with radio semantics (ranges, days per week, filters). */
export function ChoiceGroup<T extends string | number>({
  label,
  options,
  value,
  onChange,
  format,
}: {
  label: string;
  options: readonly T[];
  value: T;
  onChange: (v: T) => void;
  format: (v: T) => string;
}) {
  const id = useId();
  return (
    <div className="fb-diary-field">
      <span id={id} className="fb-diary-field__label">
        {label}
      </span>
      <div className="fb-choice" role="radiogroup" aria-labelledby={id}>
        {options.map((o) => (
          <button
            key={String(o)}
            type="button"
            role="radio"
            aria-checked={value === o}
            className={`fb-choice__option${value === o ? " fb-choice__option--on" : ""}`}
            onClick={() => onChange(o)}
          >
            {format(o)}
          </button>
        ))}
      </div>
    </div>
  );
}
