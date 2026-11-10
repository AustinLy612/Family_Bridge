/** Phase 7 therapist dashboard API (backend/app/api/therapist.py): shapes and calls. */
import { api, get, post, put } from "./client";

export type ParticipantRole = "adolescent" | "caregiver";

export interface TaskOut {
  id: string;
  title: string;
  details: string | null;
  for_roles: ParticipantRole[];
  skill_ids: string[];
  starts_on: string;
  due_on: string;
  archived: boolean;
}

export interface Assignee {
  family_id: string;
  family: string;
  alias: string;
  role: ParticipantRole;
  done: boolean;
}

export interface Schedule {
  group: { id: string; name: string };
  diary_days_per_week: number;
  tasks: (TaskOut & { assignees: Assignee[] })[];
}

export interface TaskIn {
  title: string;
  details: string | null;
  for_roles: ParticipantRole[];
  skill_ids: string[];
  starts_on: string;
  due_on: string;
}

export interface SkillRef {
  id: string;
  name: string;
  module_id: string;
  module: string;
}

export interface TestRow {
  attempt_no: number;
  status: string;
  outcome: "got_it" | "another_look" | null;
  correct: number;
  total: number;
  mood_after: number | null;
}

export interface TeachingRow {
  id: string;
  kind: "teaching";
  skill: SkillRef | null;
  source: string | null;
  status: string;
  started_at: string;
  completed_at: string | null;
  recommendation_reason: string | null;
  summary: { summary_text: string; key_points: string[] } | null;
  understanding: string | null;
  checkin: "answered" | "skipped" | "not_reached";
  turns: number;
  mood_before: number | null;
  mood_after: number | null;
  tests: TestRow[];
}

export interface CaregiverRow {
  id: string;
  kind: "caregiver";
  skill: SkillRef | null;
  source: string;
  status: string;
  step: string;
  started_at: string;
  completed_at: string | null;
  variant: string;
  practice_categories: Record<string, number>;
  quiz: { correct: number; answered: number; outcome: string | null };
  reflection: "written" | "skipped" | "not_reached";
}

export interface MasteryRow {
  skill: SkillRef | null;
  lessons_completed: number;
  outcome: "practised" | "understood" | "worth_revisiting";
  practice_categories: Record<string, number>;
  last_practised_at: string;
}

export interface LearningPanel {
  user_id: string;
  alias: string;
  role: ParticipantRole;
  lessons: (TeachingRow | CaregiverRow)[];
  mastery: MasteryRow[];
}

export interface LessonDetail {
  kind: "teaching" | "caregiver";
  checkin?: { question: string; answer: string | null; skipped: boolean | null } | null;
  messages?: { role: string; content: string; at: string }[];
  mood_notes?: { kind: string; value: number; note: string }[];
  practice?: { item: number; attempt_no: number; answer: string; category: string }[];
  reflection?: string | null;
}

export interface Coverage {
  group: { id: string; name: string };
  modules: { id: string; name: string; skills: { id: string; name: string }[] }[];
  participants: {
    user_id: string;
    family_id: string;
    family: string;
    alias: string;
    role: ParticipantRole;
  }[];
  cells: Record<string, Record<string, { lessons: number; outcome: string }>>;
  group_session_skills: string[];
}

export type CacheReviewState = "unreviewed" | "reviewed" | "needs_change";

export interface CacheItem {
  id: string;
  function: string;
  skill: { id: string; name: string };
  role: string;
  language: string;
  variant: string;
  prompt_version: number;
  kb_version: number;
  source: string;
  review: CacheReviewState;
  reviewed_by: string | null;
  reviewed_at: string | null;
  hits: number;
  created_at: string;
  output: Record<string, unknown>;
}

export interface CacheList {
  items: CacheItem[];
  total: number;
  offset: number;
  page_size: number;
  counts: Record<CacheReviewState, number>;
}

interface RoleDiary {
  participants: number;
  expected_days: number;
  days_with_entries: number;
  entries: number;
  added_later: number;
  corrected: number;
}

export interface Metrics {
  group: { id: string; name: string };
  from: string;
  to: string;
  days: number;
  enrolment: {
    families: number;
    invitations_issued: number;
    invitations_redeemed: number;
    by_role: Record<ParticipantRole, { members: number; onboarded: number }>;
  };
  diary: { days_per_week: number; adolescent: RoleDiary; caregiver: RoleDiary };
  homework: { tasks: number; assigned: number; done: number };
  learning: {
    adolescent: {
      started: number;
      completed: number;
      stopped: number;
      stopped_by_safety: number;
      by_source: Record<string, number>;
      checkin_answered: number;
      checkin_skipped: number;
      test_attempts: number;
      tests_mastered: number;
      mood_before_mean: number | null;
      mood_after_mean: number | null;
    };
    caregiver: {
      started: number;
      completed: number;
      stopped: number;
      by_source: Record<string, number>;
      quiz_answers: number;
      quiz_correct: number;
    };
  };
  safety: {
    events: number;
    by_category: Record<string, number>;
    acknowledged: number;
    acknowledged_within_sla: number;
    open_now: number;
    sla_hours: number;
  };
  therapist_time: {
    families: { family_id: string; family: string; minutes: number }[];
    median_minutes: number | null;
  };
}

export const METRIC_DAYS = [7, 28, 90] as const;

export const therapist = {
  schedule: (groupId: string) => get<Schedule>(`/groups/${groupId}/schedule`),
  setDiaryDays: (groupId: string, days: number) =>
    put<{ diary_days_per_week: number }>(`/groups/${groupId}/diary-expectation`, { days_per_week: days }),
  createTask: (groupId: string, body: TaskIn) => post<{ task: TaskOut }>(`/groups/${groupId}/tasks`, body),
  updateTask: (taskId: string, body: TaskIn) => put<{ task: TaskOut }>(`/tasks/${taskId}`, body),
  archiveTask: (taskId: string) => api<void>("DELETE", `/tasks/${taskId}`),
  learning: (familyId: string) =>
    get<{ family: { id: string; label: string }; participants: LearningPanel[] }>(
      `/families/${familyId}/learning`,
    ),
  lesson: (familyId: string, lessonId: string) =>
    get<LessonDetail>(`/families/${familyId}/learning/lessons/${lessonId}`),
  coverage: (groupId: string) => get<Coverage>(`/groups/${groupId}/coverage`),
  cache: (params: { review?: string; offset?: number }) => {
    const q = new URLSearchParams();
    if (params.review) q.set("review", params.review);
    if (params.offset) q.set("offset", String(params.offset));
    return get<CacheList>(`/content/cache?${q.toString()}`);
  },
  reviewCache: (itemId: string, decision: "reviewed" | "needs_change") =>
    post<{ item: CacheItem }>(`/content/cache/${itemId}/review`, { decision }),
  metrics: (groupId: string, days: number) => get<Metrics>(`/groups/${groupId}/metrics?days=${days}`),
  reportTime: (familyId: string, seconds: number) => post<void>(`/families/${familyId}/time`, { seconds }),
};
