/**
 * Shared controls: language switch (D3), accessibility settings (§5.11, §6.2),
 * and the Pause control that is reachable on every participant screen (§6.2, §7.3).
 */
import * as Switch from "@radix-ui/react-switch";
import * as ToggleGroup from "@radix-ui/react-toggle-group";
import { Pause } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { TEXT_SCALES, useAccessibility, type TextScale } from "../app/accessibility";
import { PrimaryButton } from "../design";
import { LANGUAGES, isLanguage } from "../i18n";
import { useRoomPause } from "../app/roomPause";

export function LanguageSwitch() {
  const { t, i18n } = useTranslation();
  return (
    <ToggleGroup.Root
      type="single"
      className="fb-segmented"
      aria-label={t("language.label")}
      value={i18n.language}
      onValueChange={(v) => {
        if (isLanguage(v)) void i18n.changeLanguage(v);
      }}
    >
      {LANGUAGES.map((lng) => (
        <ToggleGroup.Item key={lng} value={lng} lang={lng}>
          {t(`language.${lng}`)}
        </ToggleGroup.Item>
      ))}
    </ToggleGroup.Root>
  );
}

function SettingSwitch({
  label,
  hint,
  checked,
  onChange,
}: {
  label: string;
  hint?: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  const id = useId();
  return (
    <div className="fb-setting">
      <label className="fb-setting__label" htmlFor={id}>
        {label}
        {hint && <span className="fb-setting__hint">{hint}</span>}
      </label>
      <Switch.Root id={id} className="fb-switch" checked={checked} onCheckedChange={onChange}>
        <Switch.Thumb className="fb-switch__thumb" />
      </Switch.Root>
    </div>
  );
}

export function AccessibilityPanel() {
  const { t } = useTranslation();
  const { settings, update, reduceMotion, illustrationsVisible } = useAccessibility();
  const textSizeId = useId();
  return (
    <section className="fb-card" aria-labelledby={`${textSizeId}-title`}>
      <h2 id={`${textSizeId}-title`} style={{ fontSize: "var(--fs-lg)" }}>
        {t("settings.title")}
      </h2>
      <p className="fb-setting__hint" style={{ marginBottom: "var(--space-3)" }}>
        {t("settings.subtitle")}
      </p>
      <SettingSwitch
        label={t("settings.reduceMotion")}
        hint={t("settings.reduceMotionHint")}
        checked={reduceMotion}
        onChange={(v) => update({ reduceMotion: v })}
      />
      <SettingSwitch
        label={t("settings.highContrast")}
        checked={settings.highContrast}
        onChange={(v) => update({ highContrast: v })}
      />
      <SettingSwitch
        label={t("settings.calmPalette")}
        hint={t("settings.calmPaletteHint")}
        checked={settings.calmPalette}
        onChange={(v) => update({ calmPalette: v })}
      />
      <div className="fb-setting">
        <span className="fb-setting__label" id={textSizeId}>
          {t("settings.textSize")}
        </span>
        <ToggleGroup.Root
          type="single"
          className="fb-segmented"
          aria-labelledby={textSizeId}
          value={String(settings.textScale)}
          onValueChange={(v) => {
            const n = Number(v);
            if ((TEXT_SCALES as readonly number[]).includes(n)) update({ textScale: n as TextScale });
          }}
        >
          {TEXT_SCALES.map((s) => (
            <ToggleGroup.Item key={s} value={String(s)}>
              {Math.round(s * 100)}%
            </ToggleGroup.Item>
          ))}
        </ToggleGroup.Root>
      </div>
      <SettingSwitch
        label={t("settings.sound")}
        hint={t("settings.soundHint")}
        checked={settings.sound}
        onChange={(v) => update({ sound: v })}
      />
      <SettingSwitch
        label={t("settings.illustrations")}
        hint={t("settings.illustrationsHint")}
        checked={illustrationsVisible}
        onChange={(v) => update({ showIllustrations: v })}
      />
    </section>
  );
}

/**
 * Pause control. Opens a calm full-screen pause layer that hides the screen behind it.
 * No timer, nothing lost, no reason asked (§6.2). Escape or the button resumes.
 * In a joint room it pauses the room for both people instead (the room shows the pause).
 */
export function PauseControl() {
  const { t } = useTranslation();
  const roomPause = useRoomPause();
  const [paused, setPaused] = useState(false);
  const resumeRef = useRef<HTMLButtonElement>(null);
  const openerRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();

  useEffect(() => {
    if (!paused) return;
    const opener = openerRef.current;
    resumeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setPaused(false);
      if (e.key === "Tab") {
        // Single focusable control: keep focus inside the dialog.
        e.preventDefault();
        resumeRef.current?.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      opener?.focus();
    };
  }, [paused]);

  return (
    <>
      <PrimaryButton
        ref={openerRef}
        variant="secondary"
        icon={<Pause size={18} aria-hidden />}
        onClick={() => (roomPause ? roomPause() : setPaused(true))}
      >
        {t("shell.pause")}
      </PrimaryButton>
      {paused && (
        <div className="fb-pause" role="dialog" aria-modal="true" aria-labelledby={titleId}>
          <div className="fb-pause__card">
            <h2 id={titleId} className="fb-hero__title">
              {t("shell.pausedTitle")}
            </h2>
            <p>{t("shell.pausedBody")}</p>
            <PrimaryButton ref={resumeRef} onClick={() => setPaused(false)}>
              {t("shell.resume")}
            </PrimaryButton>
          </div>
        </div>
      )}
    </>
  );
}
