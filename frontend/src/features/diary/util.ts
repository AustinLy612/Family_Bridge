/** Diary helpers shared by the participant and therapist screens. */
import { useTranslation } from "react-i18next";
import type { DiaryField, DiaryTemplate, DiaryValue } from "../../api/diary";

export function useDateFormat() {
  const { i18n } = useTranslation();
  const day = (iso: string) =>
    new Date(`${iso}T00:00:00`).toLocaleDateString(i18n.language, {
      weekday: "short",
      month: "short",
      day: "numeric",
    });
  const time = (iso: string) =>
    new Date(iso).toLocaleTimeString(i18n.language, { hour: "2-digit", minute: "2-digit" });
  return { day, time };
}

/** A value as plain text, in the reader's language. */
export function useValueText(template: DiaryTemplate | undefined) {
  const { t } = useTranslation();
  const skillNames = new Map(
    template?.skills.flatMap((m) => m.skills.map((s) => [s.id, s.name] as const)) ?? [],
  );
  return (field: DiaryField, value: DiaryValue): string => {
    switch (field.type) {
      case "scale":
        return t("diary.scaleValue", { value });
      case "boolean":
        return value ? t("diary.yes") : t("diary.no");
      case "frequency":
        return field.options.find((o) => o.id === value)?.label ?? String(value);
      case "skills":
        return (Array.isArray(value) ? value : [])
          .map((s) => skillNames.get(s) ?? s)
          .join(t("diary.listSep"));
      case "note":
        return String(value);
    }
  };
}

export function allFields(t: DiaryTemplate): DiaryField[] {
  return t.groups.flatMap((g) => g.fields);
}
