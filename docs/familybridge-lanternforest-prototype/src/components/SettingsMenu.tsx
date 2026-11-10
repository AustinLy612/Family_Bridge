import { useState } from "react";

export function SettingsMenu({
  reducedMotion,
  soundEnabled,
  enhancedContrast,
  onMotionChange,
  onSoundChange,
  onContrastChange,
}: {
  reducedMotion: boolean;
  soundEnabled: boolean;
  enhancedContrast: boolean;
  onMotionChange: (value: boolean) => void;
  onSoundChange: (value: boolean) => void;
  onContrastChange: (value: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="settings-menu">
      <button className="round-button" onClick={() => setOpen((value) => !value)} aria-expanded={open} aria-label="Sensory settings">
        ⚙
      </button>
      {open && (
        <div className="settings-popover">
          <p className="eyebrow">Comfort settings</p>
          <label className="toggle-row">
            <span><strong>Reduce motion</strong><small>Stops parallax and drifting lights</small></span>
            <input type="checkbox" checked={reducedMotion} onChange={(event) => onMotionChange(event.target.checked)} />
          </label>
          <label className="toggle-row">
            <span><strong>Gentle sound effects</strong><small>Off by default · no music</small></span>
            <input type="checkbox" checked={soundEnabled} onChange={(event) => onSoundChange(event.target.checked)} />
          </label>
          <label className="toggle-row">
            <span><strong>Enhanced text contrast</strong><small>Stronger panels and brighter copy</small></span>
            <input type="checkbox" checked={enhancedContrast} onChange={(event) => onContrastChange(event.target.checked)} />
          </label>
        </div>
      )}
    </div>
  );
}
