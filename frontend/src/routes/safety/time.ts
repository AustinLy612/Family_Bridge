/** Relative and absolute times in the UI language (safety queue). */
import { useCallback } from "react";
import { useTranslation } from "react-i18next";

const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["day", 86_400],
  ["hour", 3_600],
  ["minute", 60],
];

/** "3 hours ago" in the UI language. */
export function useAge() {
  const { i18n } = useTranslation();
  return useCallback(
    (iso: string, now: number = Date.now()) => {
      const seconds = Math.max(0, (now - new Date(iso).getTime()) / 1000);
      const fmt = new Intl.RelativeTimeFormat(i18n.language, { numeric: "auto" });
      for (const [unit, size] of UNITS) {
        if (seconds >= size) return fmt.format(-Math.floor(seconds / size), unit);
      }
      return fmt.format(0, "minute");
    },
    [i18n.language],
  );
}

export function useDateTime() {
  const { i18n } = useTranslation();
  return useCallback(
    (iso: string) =>
      new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium", timeStyle: "short" }).format(
        new Date(iso),
      ),
    [i18n.language],
  );
}
