import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";

type Variant = "primary" | "secondary" | "danger";

export interface PrimaryButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /**
   * `danger` is reserved for therapist destructive actions (e.g. End session). Never use it
   * for participant errors, missed entries or answers (Plan §5.13.4).
   */
  variant?: Variant;
  block?: boolean;
  icon?: ReactNode;
  /** Shows a spinner, sets aria-busy and disables the button while work is in progress. */
  loading?: boolean;
}

export const PrimaryButton = forwardRef<HTMLButtonElement, PrimaryButtonProps>(function PrimaryButton(
  {
    variant = "primary",
    block = false,
    icon,
    loading = false,
    className,
    children,
    type = "button",
    disabled,
    ...rest
  },
  ref,
) {
  const cls = ["fb-btn", `fb-btn--${variant}`, block ? "fb-btn--block" : "", className ?? ""]
    .filter(Boolean)
    .join(" ");
  return (
    <button
      ref={ref}
      type={type}
      className={cls}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading ? <span className="fb-spinner" aria-hidden /> : icon}
      {children}
    </button>
  );
});

/**
 * Accept / decline pair. Both buttons are the same size, adjacent and equally easy to reach;
 * declining is never hidden or shamed (proposal §2, §9.1C; Plan §5.13.2).
 */
export function DecisionButtons({
  acceptLabel,
  declineLabel,
  onAccept,
  onDecline,
}: {
  acceptLabel: string;
  declineLabel: string;
  onAccept: () => void;
  onDecline: () => void;
}) {
  return (
    <div className="fb-decision">
      <PrimaryButton variant="primary" onClick={onAccept}>
        {acceptLabel}
      </PrimaryButton>
      <PrimaryButton variant="secondary" onClick={onDecline}>
        {declineLabel}
      </PrimaryButton>
    </div>
  );
}
