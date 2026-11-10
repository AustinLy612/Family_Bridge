import { BookOpen, Eye, Library, Lock, Sparkles, UserRound, Users } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type { Provenance } from "../provenance";

type Tone = "lavender" | "outline" | "amber" | "blue";

export function Chip({
  children,
  icon,
  tone = "lavender",
}: {
  children: ReactNode;
  icon?: ReactNode;
  tone?: Tone;
}) {
  const cls = tone === "lavender" ? "fb-chip" : `fb-chip fb-chip--${tone}`;
  return (
    <span className={cls}>
      {icon}
      {children}
    </span>
  );
}

export type { Provenance };

/** Provenance label: AI-generated vs authored vs labelled general knowledge (§6.2, D6). */
const PROVENANCE_ICON: Record<Provenance, ReactNode> = {
  ai: <Sparkles size={14} aria-hidden />,
  authored: <BookOpen size={14} aria-hidden />,
  general: <Library size={14} aria-hidden />,
};
const PROVENANCE_TONE: Record<Provenance, Tone> = {
  ai: "blue",
  authored: "lavender",
  general: "amber",
};

export function ProvenanceChip({ kind }: { kind: Provenance }) {
  const { t } = useTranslation();
  return (
    <Chip tone={PROVENANCE_TONE[kind]} icon={PROVENANCE_ICON[kind]}>
      {t(`provenance.${kind}`)}
    </Chip>
  );
}

/** Privacy label: who can see this item (§5.3, §7.3). */
export type Visibility = { kind: "onlyYou" } | { kind: "therapist" } | { kind: "shared"; alias: string };

export function PrivacyChip({ visibility }: { visibility: Visibility }) {
  const { t } = useTranslation();
  switch (visibility.kind) {
    case "onlyYou":
      return (
        <Chip tone="outline" icon={<Lock size={14} aria-hidden />}>
          {t("privacy.onlyYou")}
        </Chip>
      );
    case "therapist":
      return (
        <Chip tone="outline" icon={<UserRound size={14} aria-hidden />}>
          {t("privacy.therapist")}
        </Chip>
      );
    case "shared":
      return (
        <Chip tone="outline" icon={<Users size={14} aria-hidden />}>
          {t("privacy.sharedWith", { alias: visibility.alias })}
        </Chip>
      );
  }
}

/** "Who can see this?" indicator shown in the header of every participant screen (§7.3). */
export function PrivacyIndicator({ visibility }: { visibility: Visibility }) {
  const { t } = useTranslation();
  return (
    <span className="fb-privacy-indicator" role="status" aria-label={t("shell.whoCanSee")}>
      <Eye size={16} aria-hidden />
      <PrivacyChip visibility={visibility} />
    </span>
  );
}
