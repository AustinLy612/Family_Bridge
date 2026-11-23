/**
 * Navigation hierarchy (D95). Everyone signs in to the shared Portal (`/portal`): account details
 * and settings, plus a way into each functional module. A module groups existing screens:
 *   - Family Bridge: family learning (group review, diary cards, joint activities; for therapists
 *     groups/families, schedule, diary review and joint sessions).
 *   - Personal Learning: individual DBT skills learning and practice (and its oversight for staff).
 *   - Administration (admin only).
 * Shared items (Help, safety queue, metrics) stay visible in every module; account items
 * (profile, settings) sit with the Portal. URLs did not change: every screen keeps its path
 * under the role home (`/teen`, `/caregiver`, `/therapist`, `/admin`).
 */
import {
  BookOpen,
  CalendarDays,
  ChartLine,
  ClipboardCheck,
  Database,
  FileDown,
  FileCheck2,
  GraduationCap,
  HeartHandshake,
  House,
  LifeBuoy,
  NotebookPen,
  ShieldAlert,
  SlidersHorizontal,
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

export type ModuleId = "family" | "learning" | "admin";

export interface NavModule {
  id: ModuleId; // i18n: portal.modules.<id>.*
  icon: LucideIcon;
  items: NavItem[];
  /** Extra screens (outside `items`) that belong to this module, relative to the role home. */
  extra?: RegExp;
}

export const PORTAL_PATH = "/portal";

const participantModules = (learnKey: "learn" | "exploreSkills"): NavModule[] => [
  {
    id: "family",
    icon: HeartHandshake,
    items: [
      { key: "familyHome", path: "", icon: House },
      { key: "groupReview", path: "group-review", icon: UsersRound },
      { key: "diary", path: "diary", icon: NotebookPen },
      { key: "joint", path: "joint", icon: HeartHandshake },
    ],
  },
  {
    id: "learning",
    icon: GraduationCap,
    items: [{ key: learnKey, path: "learn", icon: BookOpen }],
  },
];

export const MODULES: Record<Role, NavModule[]> = {
  adolescent: participantModules("learn"),
  caregiver: participantModules("exploreSkills"),
  therapist: [
    {
      id: "family",
      icon: HeartHandshake,
      items: [
        { key: "groups", path: "", icon: Users },
        { key: "schedule", path: "schedule", icon: CalendarDays },
        { key: "diaryReview", path: "diary-review", icon: NotebookPen },
        { key: "joint", path: "joint", icon: HeartHandshake },
      ],
      extra: /^(groups(\/|$)|families\/[^/]+(\/diary)?$)/,
    },
    {
      id: "learning",
      icon: GraduationCap,
      items: [
        { key: "progress", path: "progress", icon: ChartLine },
        { key: "contentReview", path: "content", icon: FileCheck2 },
      ],
      extra: /^families\/[^/]+\/learning(\/|$)/,
    },
  ],
  admin: [
    {
      id: "admin",
      icon: SlidersHorizontal,
      items: [
        { key: "therapists", path: "", icon: Users },
        { key: "siteSettings", path: "site", icon: Settings2 },
        { key: "export", path: "export", icon: FileDown },
      ],
    },
    {
      id: "learning",
      icon: GraduationCap,
      items: [
        { key: "knowledgeBase", path: "knowledge", icon: Database },
        { key: "aiLayer", path: "ai", icon: Sparkles },
      ],
    },
  ],
};

/** Always visible, whatever module is open. */
export const SHARED: Record<Role, NavItem[]> = {
  adolescent: [{ key: "help", path: "help", icon: LifeBuoy }],
  caregiver: [{ key: "help", path: "help", icon: LifeBuoy }],
  therapist: [
    { key: "safetyQueue", path: "safety", icon: ShieldAlert },
    { key: "metrics", path: "metrics", icon: ClipboardCheck },
  ],
  admin: [{ key: "safetyOversight", path: "safety", icon: ShieldAlert }],
};

/** Personal information that belongs with the Portal (Settings is added for every role). */
export const ACCOUNT: Record<Role, NavItem[]> = {
  adolescent: [{ key: "profile", path: "profile", icon: UserRound }],
  caregiver: [],
  therapist: [],
  admin: [],
};

/** Every routed nav item of a role (modules, shared, account), used to build the route table. */
export const NAV: Record<Role, NavItem[]> = Object.fromEntries(
  (Object.keys(MODULES) as Role[]).map((role) => [
    role,
    [...MODULES[role].flatMap((m) => m.items), ...SHARED[role], ...ACCOUNT[role]],
  ]),
) as Record<Role, NavItem[]>;

export function navHref(role: Role, item: NavItem): string {
  const home = ROLE_HOME[role];
  return item.path ? `${home}/${item.path}` : home;
}

/** Where a module opens: its first screen. */
export function moduleHref(role: Role, module: NavModule): string {
  const first = module.items[0];
  return first ? navHref(role, first) : ROLE_HOME[role];
}

const under = (rel: string, path: string) => rel === path || rel.startsWith(`${path}/`);

/** The module a pathname belongs to, or null for the Portal, account and shared screens. */
export function moduleFor(role: Role, pathname: string): ModuleId | null {
  const home = ROLE_HOME[role];
  if (pathname !== home && !pathname.startsWith(`${home}/`)) return null;
  const rel = pathname.slice(home.length).replace(/^\//, "").replace(/\/$/, "");
  for (const m of MODULES[role]) {
    if (m.items.some((i) => (i.path === "" ? rel === "" : under(rel, i.path)))) return m.id;
    if (m.extra?.test(rel)) return m.id;
  }
  return null;
}

export const isParticipant = (role: Role): boolean => role === "adolescent" || role === "caregiver";
