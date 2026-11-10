/** Shared labels for the safety queue: severity and status chips (text, never colour alone). */
import { useTranslation } from "react-i18next";
import type { SafetySeverity, SafetyStatus } from "../../api/types";
import { Chip } from "../../design";

export function SeverityChip({ severity }: { severity: SafetySeverity }) {
  const { t } = useTranslation();
  const tone = severity === "high" ? "amber" : severity === "medium" ? "blue" : "outline";
  return <Chip tone={tone}>{t("safety.severityChip", { level: t(`safety.severity.${severity}`) })}</Chip>;
}

export function StatusChip({ status }: { status: SafetyStatus }) {
  const { t } = useTranslation();
  return <Chip tone={status === "new" ? "lavender" : "outline"}>{t(`safety.status.${status}`)}</Chip>;
}
