/**
 * Accessibility & comfort settings (Plan §5.11, §6.2; Phase 0 task 4).
 * reduce motion (follows the OS until changed), high contrast, calm palette,
 * text scale up to 200 %, sound (OFF by default), show illustrations.
 * Phase 0 keeps these on the device; Phase 1 saves them on the user's account.
 */
import { MotionConfig } from "framer-motion";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export const TEXT_SCALES = [1, 1.25, 1.5, 2] as const;
export type TextScale = (typeof TEXT_SCALES)[number];
export type Density = "participant" | "therapist";

export interface A11ySettings {
  /** null = follow the operating-system preference */
  reduceMotion: boolean | null;
  highContrast: boolean;
  calmPalette: boolean;
  textScale: TextScale;
  sound: boolean;
  /** null = role default (on for participants, off for therapists/admins; Plan §5.13.5) */
  showIllustrations: boolean | null;
}

export const DEFAULT_A11Y: A11ySettings = {
  reduceMotion: null,
  highContrast: false,
  calmPalette: false,
  textScale: 1,
  sound: false,
  showIllustrations: null,
};

const STORAGE_KEY = "fb.a11y";

function load(): A11ySettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_A11Y;
    const parsed = JSON.parse(raw) as Partial<A11ySettings>;
    const merged = { ...DEFAULT_A11Y, ...parsed };
    if (!(TEXT_SCALES as readonly number[]).includes(merged.textScale)) merged.textScale = 1;
    return merged;
  } catch {
    return DEFAULT_A11Y;
  }
}

function systemPrefersReducedMotion(): boolean {
  return typeof window.matchMedia === "function"
    ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
    : false;
}

interface A11yContextValue {
  settings: A11ySettings;
  update: (patch: Partial<A11ySettings>) => void;
  /** Effective values after applying OS and role defaults. */
  reduceMotion: boolean;
  density: Density;
  setDensity: (d: Density) => void;
  illustrationsVisible: boolean;
}

const A11yContext = createContext<A11yContextValue | null>(null);

export function AccessibilityProvider({
  children,
  initial,
  density: initialDensity = "participant",
}: {
  children: ReactNode;
  initial?: Partial<A11ySettings>;
  density?: Density;
}) {
  const [settings, setSettings] = useState<A11ySettings>(() => ({
    ...load(),
    ...initial,
  }));
  const [density, setDensity] = useState<Density>(initialDensity);
  const [systemReduce, setSystemReduce] = useState(systemPrefersReducedMotion);

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const onChange = () => setSystemReduce(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const reduceMotion = settings.reduceMotion ?? systemReduce;
  const illustrationsVisible = settings.showIllustrations ?? density === "participant";

  useEffect(() => {
    const el = document.documentElement;
    el.dataset.reduceMotion = String(reduceMotion);
    el.dataset.contrast = settings.highContrast ? "high" : "normal";
    el.dataset.palette = settings.calmPalette ? "calm" : "default";
    el.dataset.density = density;
    el.style.setProperty("--text-scale", String(settings.textScale));
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
    } catch {
      /* ignore */
    }
  }, [settings, reduceMotion, density]);

  const update = useCallback((patch: Partial<A11ySettings>) => setSettings((s) => ({ ...s, ...patch })), []);

  const value = useMemo(
    () => ({
      settings,
      update,
      reduceMotion,
      density,
      setDensity,
      illustrationsVisible,
    }),
    [settings, update, reduceMotion, density, illustrationsVisible],
  );

  return (
    <A11yContext.Provider value={value}>
      <MotionConfig reducedMotion={reduceMotion ? "always" : "never"}>{children}</MotionConfig>
    </A11yContext.Provider>
  );
}

export function useAccessibility(): A11yContextValue {
  const ctx = useContext(A11yContext);
  if (!ctx) throw new Error("useAccessibility must be used inside AccessibilityProvider");
  return ctx;
}
