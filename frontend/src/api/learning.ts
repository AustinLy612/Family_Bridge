/** Phase 5 learning API (backend/app/api/learning.py): shapes and calls. */
import { del, get, post, put } from "./client";
import type { ContentSource, SafetyAction } from "./types";

export interface SkillRef {
  id: string;
  name: string;
  module: string;
}

export interface SkillsOut {
  modules: { id: string; name: string; skills: { id: string; name: string }[] }[];
}

// --- profile ------------------------------------------------------------------------------

export type Gender = "male" | "female" | "other" | "prefer_not_to_say";

export interface LearnerProfile {
  gender: Gender | null;
  age: number;
  grade: string;
  hobby_tags: string[];
  concern_tags: string[];
  other_hobby_text: string | null;
  other_concern_text: string | null;
}

export interface ProfileOptions {
  hobby_tags: string[];
  concern_tags: string[];
  grades: string[];
  genders: Gender[];
  max_tags: number;
  age_min: number;
  age_max: number;
}

export interface ProfileOut {
  profile: LearnerProfile | null;
  options: ProfileOptions;
}

// --- adolescent lessons ---------------------------------------------------------------------

export type TeachingPhase =
  | "pre_mood_recording"
  | "personal_inquiry"
  | "skill_selection"
  | "rag_retrieval_for_teaching"
  | "teaching"
  | "summary"
  | "done";

export type LessonStatus = "ongoing" | "completed" | "user_terminated" | "stopped_by_safety";
export type LessonSource = "recommended" | "alternative" | "chosen" | "group_review" | "explore";

export interface Turn {
  seq: number;
  role: "student" | "coach";
  content: string;
  question: string | null;
  source: ContentSource | null;
}

export interface TestSummary {
  id: string;
  session_id: string;
  attempt_no: number;
  status: "generating" | "ready" | "completed" | "unavailable" | "user_terminated" | "stopped_by_safety";
  source: ContentSource | null;
  outcome: "got_it" | "another_look" | null;
  mood_recorded: boolean;
  created_at: string;
}

export interface TestQuestion {
  position: number;
  scenario: string;
  question: string;
  options: string[];
  answer_index: number | null;
  is_correct: boolean | null;
  correct_index: number | null;
  explanation: string | null;
}

export interface SkillTest extends TestSummary {
  questions: TestQuestion[];
}

export interface Lesson {
  id: string;
  phase: TeachingPhase;
  status: LessonStatus;
  source: LessonSource | null;
  language: string;
  started_at: string;
  completed_at: string | null;
  checkin: {
    greeting: string;
    question: string;
    source: ContentSource | null;
    skipped: boolean | null;
  } | null;
  recommendation: {
    skill: SkillRef;
    reason: string;
    alternatives: SkillRef[];
    is_repeat: boolean;
    repeat_justification?: string;
    source: ContentSource | null;
  } | null;
  skill: SkillRef | null;
  plan: { title: string; minutes: number | null }[];
  plan_source: ContentSource | null;
  messages: Turn[];
  summary: {
    summary_text: string;
    key_points: string[];
    recommendations: string[];
    source: ContentSource | null;
  } | null;
  busy: boolean;
  tests: TestSummary[];
}

export interface LessonOut {
  lesson: Lesson;
  safety: SafetyAction;
}

// --- caregiver lessons ----------------------------------------------------------------------

export type CaregiverStep = "explain" | "practice" | "quiz" | "wrap_up" | "done";

export interface Feedback {
  what_worked: string;
  why: string;
  try_next: string;
}

export interface CaregiverLesson {
  id: string;
  kind: "caregiver";
  step: CaregiverStep;
  status: LessonStatus;
  source: LessonSource;
  language: string;
  skill: SkillRef;
  variant: "standard" | "simpler" | "another_example";
  explanation: {
    title: string;
    summary: string;
    key_points: string[];
    everyday_example: string;
    check_question: string;
    source: ContentSource;
    grounding: string;
    references: { module: string; handout: string; title: string }[];
  } | null;
  practice: {
    items: {
      scenario: string;
      prompt: string;
      answer_mode: "choice" | "short_text";
      options: string[];
      attempts: { attempt_no: number; answer: string; feedback: Feedback; source: ContentSource }[];
      can_retry: boolean;
    }[];
    source: ContentSource | null;
  } | null;
  quiz: {
    questions: {
      stem: string;
      options: string[];
      answer_index: number | null;
      is_correct: boolean | null;
      correct_index: number | null;
      explanation: string | null;
    }[];
    source: ContentSource | null;
  } | null;
  outcome: Outcome | null;
  reflection: string | null;
  started_at: string;
  completed_at: string | null;
}

export interface CaregiverOut {
  lesson: CaregiverLesson;
  safety: SafetyAction;
}

// --- both -------------------------------------------------------------------------------------

export type Outcome = "practised" | "understood" | "worth_revisiting";

export interface ProgressItem {
  skill: SkillRef;
  module_id: string;
  lessons_completed: number;
  outcome: Outcome;
  first_practised_at: string;
  last_practised_at: string;
}

export interface HistoryItem {
  kind: "teaching" | "caregiver";
  id: string;
  skill: SkillRef;
  status: LessonStatus;
  source: LessonSource | null;
  started_at: string;
}

export interface GroupRecord {
  id: string;
  session_date: string;
  skills: SkillRef[];
  note?: string | null;
}

export const learn = {
  skills: () => get<SkillsOut>("/learn/skills"),
  profile: () => get<ProfileOut>("/learn/profile"),
  saveProfile: (p: Omit<LearnerProfile, never>) => put<ProfileOut>("/learn/profile", p),
  current: () => get<{ lesson: Lesson | null }>("/learn/sessions/current"),
  start: (body: { group_record_id?: string; skill_id?: string } = {}) =>
    post<LessonOut>("/learn/sessions", body),
  lesson: (id: string) => get<LessonOut>(`/learn/sessions/${id}`),
  mood: (id: string, value: number, note?: string) =>
    post<LessonOut>(`/learn/sessions/${id}/mood`, { value, note: note || null }),
  checkin: (id: string, answer: string | null) =>
    post<LessonOut>(`/learn/sessions/${id}/checkin`, answer ? { answer } : { skip: true }),
  choose: (id: string, skill_id: string, choice: "recommended" | "alternative" | "chosen") =>
    post<LessonOut>(`/learn/sessions/${id}/choose`, { skill_id, choice }),
  end: (id: string) => post<LessonOut>(`/learn/sessions/${id}/end`),
  postMood: (id: string, value: number, note?: string) =>
    post<LessonOut>(`/learn/sessions/${id}/post-mood`, { value, note: note || null }),
  stop: (id: string) => post<LessonOut>(`/learn/sessions/${id}/stop`),
  startTest: (id: string) => post<{ test: SkillTest }>(`/learn/sessions/${id}/tests`),
  test: (id: string) => get<{ test: SkillTest }>(`/learn/tests/${id}`),
  answer: (id: string, position: number, answer_index: number) =>
    post<{ question: TestQuestion; test: SkillTest }>(`/learn/tests/${id}/answers`, {
      position,
      answer_index,
    }),
  testMood: (id: string, value: number, note?: string) =>
    post<{ test: SkillTest; safety: SafetyAction }>(`/learn/tests/${id}/mood`, {
      value,
      note: note || null,
    }),
  stopTest: (id: string) => post<{ test: SkillTest }>(`/learn/tests/${id}/stop`),
  caregiverCurrent: () => get<{ lesson: CaregiverLesson | null }>("/learn/caregiver/current"),
  caregiverStart: (skill_id: string, group_record_id?: string) =>
    post<CaregiverOut>("/learn/caregiver/lessons", { skill_id, group_record_id }),
  caregiverLesson: (id: string) => get<CaregiverOut>(`/learn/caregiver/lessons/${id}`),
  adapt: (id: string, variant: "standard" | "simpler" | "another_example") =>
    post<CaregiverOut>(`/learn/caregiver/lessons/${id}/adapt`, { variant }),
  next: (id: string, from_step: "explain" | "practice" | "quiz") =>
    post<CaregiverOut>(`/learn/caregiver/lessons/${id}/next`, { from_step }),
  practise: (id: string, item_index: number, answer: { option_index?: number; text?: string }) =>
    post<
      CaregiverOut & {
        feedback: (Feedback & { attempt_no: number; can_retry: boolean; source: ContentSource }) | null;
      }
    >(`/learn/caregiver/lessons/${id}/practice`, { item_index, ...answer }),
  quiz: (id: string, question_index: number, answer_index: number) =>
    post<CaregiverOut>(`/learn/caregiver/lessons/${id}/quiz`, { question_index, answer_index }),
  finish: (id: string, reflection: string | null) =>
    post<CaregiverOut>(`/learn/caregiver/lessons/${id}/finish`, { reflection }),
  caregiverStop: (id: string) => post<CaregiverOut>(`/learn/caregiver/lessons/${id}/stop`),
  groupReview: () => get<{ records: GroupRecord[] }>("/learn/group-review"),
  progress: () => get<{ skills: ProgressItem[] }>("/learn/progress"),
  history: () => get<{ lessons: HistoryItem[] }>("/learn/history"),
  groupRecords: (groupId: string) => get<{ records: GroupRecord[] }>(`/groups/${groupId}/skill-records`),
  createGroupRecord: (
    groupId: string,
    body: { session_date: string; skill_ids: string[]; note?: string | null },
  ) => post<{ record: GroupRecord }>(`/groups/${groupId}/skill-records`, body),
  deleteGroupRecord: (groupId: string, recordId: string) =>
    del(`/groups/${groupId}/skill-records/${recordId}`),
};
