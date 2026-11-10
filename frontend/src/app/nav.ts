/** Per-role sidebar navigation (Plan §5.13.1). Routes are placeholders until each phase lands. */
import {
  BookOpen,
  CalendarDays,
  ChartLine,
  ClipboardCheck,
  Database,
  FileDown,
  FileCheck2,
  HeartHandshake,
  House,
  LifeBuoy,
  NotebookPen,
  ShieldAlert,
  ShieldCheck,
  UserRound,
  Users,
  UsersRound,
  Settings2,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import { ROLE_HOME, type Role } from "./session";

export interface NavItem {
  key: string; // i18n key under nav.*
  path: string; // relative to the role home
  icon: LucideIcon;
}

const participantCommon = (learnKey: "learn" | "exploreSkills"): NavItem[] => [
  { key: "home", path: "", icon: House },
  { key: learnKey, path: "learn", icon: BookOpen },
  { key: "groupReview", path: "group-review", icon: UsersRound },
  { key: "diary", path: "diary", icon: NotebookPen },
  { key: "joint", path: "joint", icon: HeartHandshake },
  { key: "help", path: "help", icon: LifeBuoy },
  { key: "privacy", path: "privacy", icon: ShieldCheck },
];

export const NAV: Record<Role, NavItem[]> = {
  adolescent: [...participantCommon("learn"), { key: "profile", path: "profile", icon: UserRound }],
  caregiver: participantCommon("exploreSkills"),
  therapist: [
    { key: "groups", path: "", icon: Users },
    { key: "schedule", path: "schedule", icon: CalendarDays },
    { key: "diaryReview", path: "diary-review", icon: NotebookPen },
    { key: "progress", path: "progress", icon: ChartLine },
    { key: "joint", path: "joint", icon: HeartHandshake },
    { key: "safetyQueue", path: "safety", icon: ShieldAlert },
    { key: "contentReview", path: "content", icon: FileCheck2 },
    { key: "metrics", path: "metrics", icon: ClipboardCheck },
  ],
  admin: [
    { key: "therapists", path: "", icon: Users },
    { key: "siteSettings", path: "site", icon: Settings2 },
    { key: "safetyOversight", path: "safety", icon: ShieldAlert },
    { key: "knowledgeBase", path: "knowledge", icon: Database },
    { key: "aiLayer", path: "ai", icon: Sparkles },
    { key: "export", path: "export", icon: FileDown },
  ],
};

export function navHref(role: Role, item: NavItem): string {
  const home = ROLE_HOME[role];
  return item.path ? `${home}/${item.path}` : home;
}

export const isParticipant = (role: Role): boolean => role === "adolescent" || role === "caregiver";
