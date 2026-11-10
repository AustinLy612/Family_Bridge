/** Form building blocks for Phase 1 screens. Labels are always visible (Plan §5.11). */
import { Copy } from "lucide-react";
import {
  useEffect,
  useId,
  useRef,
  useState,
  type InputHTMLAttributes,
  type ReactNode,
  type TextareaHTMLAttributes,
} from "react";
import { useTranslation } from "react-i18next";
import { ApiError, errorKey } from "../api/client";

export function TextField({
  label,
  hint,
  error,
  ...input
}: {
  label: string;
  hint?: string;
  error?: string;
} & InputHTMLAttributes<HTMLInputElement>) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  const errId = error ? `${id}-err` : undefined;
  return (
    <div className="fb-field">
      <label htmlFor={id} className="fb-field__label">
        {label}
      </label>
      {hint && (
        <span id={hintId} className="fb-setting__hint">
          {hint}
        </span>
      )}
      <input
        id={id}
        className="fb-input"
        aria-invalid={error ? true : undefined}
        aria-describedby={[hintId, errId].filter(Boolean).join(" ") || undefined}
        {...input}
      />
      {error && (
        <span id={errId} className="fb-field__error">
          {error}
        </span>
      )}
    </div>
  );
}

export function TextAreaField({
  label,
  hint,
  ...input
}: {
  label: string;
  hint?: string;
} & TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  return (
    <div className="fb-field">
      <label htmlFor={id} className="fb-field__label">
        {label}
      </label>
      {hint && (
        <span id={hintId} className="fb-setting__hint">
          {hint}
        </span>
      )}
      <textarea id={id} className="fb-input fb-textarea" rows={4} aria-describedby={hintId} {...input} />
    </div>
  );
}

export function SelectField({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  const id = useId();
  return (
    <div className="fb-field">
      <label htmlFor={id} className="fb-field__label">
        {label}
      </label>
      <select id={id} className="fb-input" value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}

/** Translated API error. Password-policy errors list each problem. */
export function ErrorNotice({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  const problems =
    error instanceof ApiError && Array.isArray(error.detail.problems)
      ? (error.detail.problems as string[])
      : [];
  const retry =
    error instanceof ApiError && typeof error.detail.retry_after === "number"
      ? Math.ceil(error.detail.retry_after / 60)
      : null;
  return (
    <div role="alert" className="fb-notice fb-notice--error">
      <p>
        {t(errorKey(error), {
          minutes: retry ?? 1,
          defaultValue: t("apiErrors.unknown"),
        })}
      </p>
      {problems.length > 0 && (
        <ul>
          {problems.map((p) => (
            <li key={p}>{t(`apiErrors.${p}`)}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function Notice({ children, tone = "info" }: { children: ReactNode; tone?: "info" | "warn" }) {
  return <div className={`fb-notice fb-notice--${tone}`}>{children}</div>;
}

/**
 * A one-time code, shown exactly once (Plan §5.1). It is not stored by the browser; once this
 * panel is dismissed it cannot be shown again.
 */
export function CodeReveal({
  code,
  expiresAt,
  onDone,
}: {
  code: string;
  expiresAt: string;
  onDone: () => void;
}) {
  const { t, i18n } = useTranslation();
  const [copied, setCopied] = useState(false);
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    const h = headingRef.current;
    h?.scrollIntoView?.({ block: "center" });
    h?.focus();
  }, [code]);
  return (
    <section className="fb-card fb-code" aria-labelledby="code-title">
      <h3 id="code-title" ref={headingRef} tabIndex={-1}>
        {t("codes.shownOnce")}
      </h3>
      <p className="fb-code__value" lang="en">
        {code}
      </p>
      <p className="fb-setting__hint">
        {t("codes.expires", {
          date: new Date(expiresAt).toLocaleDateString(i18n.language),
        })}
      </p>
      <p className="fb-setting__hint">{t("codes.handOver")}</p>
      <div className="fb-actions">
        <button
          type="button"
          className="fb-btn fb-btn--secondary"
          onClick={() => {
            void navigator.clipboard?.writeText(code).then(() => setCopied(true));
          }}
        >
          <Copy size={18} aria-hidden /> {copied ? t("codes.copied") : t("codes.copy")}
        </button>
        <button type="button" className="fb-btn fb-btn--primary" onClick={onDone}>
          {t("codes.done")}
        </button>
      </div>
    </section>
  );
}
