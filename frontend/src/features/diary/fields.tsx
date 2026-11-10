/**
 * Diary field inputs and read-only values (Plan §5.6). One component per template field type.
 * Every item can be left unanswered; nothing is required.
 */
import { useId } from "react";
import { useTranslation } from "react-i18next";
import type { DiaryField, DiaryTemplate, DiaryValue } from "../../api/diary";

const SCALE = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];

export function FieldInput({
  field,
  value,
  template,
  onChange,
}: {
  field: DiaryField;
  value: DiaryValue | undefined;
  template: DiaryTemplate;
  onChange: (v: DiaryValue | undefined) => void;
}) {
  const { t } = useTranslation();
  const labelId = useId();
  const hintId = useId();
  const head = (
    <>
      <span id={labelId} className="fb-diary-field__label">
        {field.label}
      </span>
      {field.hint && (
        <span id={hintId} className="fb-setting__hint">
          {field.hint}
        </span>
      )}
    </>
  );
  const clear =
    value !== undefined ? (
      <button type="button" className="fb-diary-clear" onClick={() => onChange(undefined)}>
        {t("diary.clear")}
      </button>
    ) : null;

  switch (field.type) {
    case "scale":
      return (
        <div className="fb-diary-field" data-field={field.id}>
          {head}
          <div
            className="fb-scale"
            role="radiogroup"
            aria-labelledby={labelId}
            aria-describedby={field.hint ? hintId : undefined}
          >
            {SCALE.map((n) => (
              <button
                key={n}
                type="button"
                role="radio"
                aria-checked={value === n}
                aria-label={String(n)}
                className={`fb-scale__option${value === n ? " fb-scale__option--on" : ""}`}
                onClick={() => onChange(n)}
              >
                {n}
              </button>
            ))}
          </div>
          {field.low && (
            <div className="fb-scale__anchors" aria-hidden>
              <span>1 · {field.low}</span>
              <span>10 · {field.high}</span>
            </div>
          )}
          {clear}
        </div>
      );
    case "boolean":
    case "frequency": {
      const options =
        field.type === "boolean"
          ? [
              { id: "yes", label: t("diary.yes"), v: true as DiaryValue },
              { id: "no", label: t("diary.no"), v: false as DiaryValue },
            ]
          : field.options.map((o) => ({ id: o.id, label: o.label, v: o.id as DiaryValue }));
      return (
        <div className="fb-diary-field" data-field={field.id}>
          {head}
          <div className="fb-choice" role="radiogroup" aria-labelledby={labelId}>
            {options.map((o) => (
              <button
                key={o.id}
                type="button"
                role="radio"
                aria-checked={value === o.v}
                className={`fb-choice__option${value === o.v ? " fb-choice__option--on" : ""}`}
                onClick={() => onChange(o.v)}
              >
                {o.label}
              </button>
            ))}
          </div>
          {clear}
        </div>
      );
    }
    case "skills": {
      const chosen = Array.isArray(value) ? value : [];
      const toggle = (id: string) => {
        const next = chosen.includes(id) ? chosen.filter((x) => x !== id) : [...chosen, id];
        onChange(next.length ? next : undefined);
      };
      return (
        <fieldset className="fb-diary-field" data-field={field.id}>
          <legend className="fb-diary-field__label">{field.label}</legend>
          {template.skills.map((m) => {
            const n = m.skills.filter((s) => chosen.includes(s.id)).length;
            return (
              <details key={m.id} open={n > 0}>
                <summary>
                  {m.name}
                  {n > 0 ? ` (${n})` : ""}
                </summary>
                <div className="fb-diary-skills">
                  {m.skills.map((s) => (
                    <label key={s.id} className="fb-checkbox">
                      <input type="checkbox" checked={chosen.includes(s.id)} onChange={() => toggle(s.id)} />
                      {s.name}
                    </label>
                  ))}
                </div>
              </details>
            );
          })}
        </fieldset>
      );
    }
    case "note":
      return null; // rendered by the form itself (it is not part of `values`)
  }
}
