import type { ReactNode } from "react";

export function SceneChrome({
  title,
  eyebrow,
  progress,
  children,
  actions,
}: {
  title: string;
  eyebrow?: string;
  progress?: number;
  children: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="scene-chrome">
      <div className="scene-heading-row">
        <div>
          {eyebrow && <p className="eyebrow">{eyebrow}</p>}
          <h2>{title}</h2>
        </div>
        {actions && <div className="scene-actions">{actions}</div>}
      </div>
      {typeof progress === "number" && (
        <div className="story-progress" aria-label={`${progress}% complete`} role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}>
          <span style={{ width: `${progress}%` }} />
          <i aria-hidden="true" style={{ left: `${progress}%` }} />
        </div>
      )}
      {children}
    </div>
  );
}

export function Dialogue({ speaker, children, tone = "moss" }: { speaker: string; children: ReactNode; tone?: "moss" | "guide" | "shared" }) {
  return (
    <div className={`dialogue dialogue--${tone}`}>
      <span className="speaker"><i aria-hidden="true">{tone === "shared" ? "◇" : tone === "guide" ? "✦" : "❧"}</i>{speaker}</span>
      <div>{children}</div>
      <span className="dialogue-tail" aria-hidden="true" />
    </div>
  );
}

export function ChoiceButton({
  selected,
  title,
  detail,
  onClick,
  disabled,
  kind = "story",
  icon,
}: {
  selected?: boolean;
  title: string;
  detail?: string;
  onClick: () => void;
  disabled?: boolean;
  kind?: "story" | "emotion" | "support" | "fragment" | "transfer";
  icon?: string;
}) {
  return (
    <button className={`choice choice--${kind} ${selected ? "is-selected" : ""}`} onClick={onClick} disabled={disabled} type="button" aria-pressed={selected}>
      <span className="choice-marker" aria-hidden="true">{selected ? "✓" : icon ?? (kind === "fragment" ? "〰" : "✦")}</span>
      <span><strong>{title}</strong>{detail && <small>{detail}</small>}</span>
      <span className="choice-glimmer" aria-hidden="true" />
    </button>
  );
}
