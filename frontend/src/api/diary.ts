/** Phase 6 Diary Cards API (backend/app/api/diary.py): shapes and calls. */
import { api, get, post, put } from "./client";
import type { SafetyAction } from "./types";

export type DiaryFieldType = "scale" | "boolean" | "skills" | "frequency" | "note";

export interface DiaryField {
  id: string;
  type: DiaryFieldType;
  label: string;
  hint: string | null;
  low: string | null;
  high: string | null;
  options: { id: string; label: string }[];
  show_if: string | null;
  urge: boolean;
}

export interface DiaryTemplate {
  role: "adolescent" | "caregiver";
  version: number;
  title: string;
  intro: string;
  groups: { id: string; label: string; fields: DiaryField[] }[];
  skills: { id: string; name: string; skills: { id: string; name: string }[] }[];
  note_max: number;
}

export type DiaryValue = number | boolean | string | string[];
export type DiaryValues = Record<string, DiaryValue>;

export interface OwnerShare {
  id: string;
  recipient: string;
  fields: string[];
  created_at: string;
  revoked_at: string | null;
}

export interface DiaryEntry {
  id: string;
  entry_date: string;
  recorded_at: string;
  updated_at: string;
  template_version: number;
  values: DiaryValues;
  note: string | null;
  revision_no: number;
  editable: boolean;
  shares: OwnerShare[];
  homework: HomeworkItem[];
}

/** Group homework set by the therapist (D69). Ticked only in the diary; Home lists it. */
export interface HomeworkItem {
  id: string;
  title: string;
  details: string | null;
  skill_ids: string[];
  due_on: string;
  done?: boolean;
}

export interface DiaryRevision {
  revision_no: number;
  saved_at: string;
  values: DiaryValues;
  note: string | null;
}

export interface DiaryWindow {
  today: string;
  editable_from: string;
}

export interface RenderedItem {
  field_id: string;
  label: string;
  type: DiaryFieldType;
  value: DiaryValue;
  display: string | null;
}

export interface SharedItem {
  id: string;
  from: string;
  entry_date: string;
  shared_at: string;
  items: RenderedItem[];
}

export interface SaveOut {
  entry: DiaryEntry;
  safety: SafetyAction;
}

export const diary = {
  template: () => get<{ template: DiaryTemplate; can_share: boolean } & DiaryWindow>("/diary/template"),
  templateVersion: (v: number) => get<{ template: DiaryTemplate }>(`/diary/templates/${v}`),
  entries: (days = 30) => get<{ entries: DiaryEntry[] } & DiaryWindow>(`/diary/entries?days=${days}`),
  entry: (id: string) => get<{ entry: DiaryEntry }>(`/diary/entries/${id}`),
  create: (entry_date: string, values: DiaryValues, note: string | null, homework: string[] = []) =>
    post<SaveOut>("/diary/entries", { entry_date, values, note, homework }),
  update: (id: string, values: DiaryValues, note: string | null, revision_no: number, homework?: string[]) =>
    put<SaveOut>(`/diary/entries/${id}`, { values, note, revision_no, homework }),
  homework: (date: string) => get<{ items: HomeworkItem[] }>(`/diary/homework?date=${date}`),
  myHomework: () => get<{ items: HomeworkItem[] }>("/homework"),
  revisions: (id: string) => get<{ revisions: DiaryRevision[] }>(`/diary/entries/${id}/revisions`),
  recipients: () => get<{ recipients: { id: string; alias: string }[] }>("/diary/share-recipients"),
  share: (id: string, recipient: string, fields: string[]) =>
    post<{ share: OwnerShare }>(`/diary/entries/${id}/shares`, { recipient, fields }),
  revoke: (shareId: string) => api<{ share: OwnerShare }>("DELETE", `/diary/shares/${shareId}`),
  sharedWithMe: () => get<{ items: SharedItem[] }>("/diary/shared-with-me"),
};

// --- therapist review ---------------------------------------------------------------------

export interface SeriesPoint {
  date: string;
  at: string;
  value: number;
}

export interface ReviewEntry extends Omit<DiaryEntry, "shares" | "homework"> {
  added_later: boolean;
  homework: string[]; // titles of homework ticked in this entry
  items: RenderedItem[];
  shares: OwnerShare[];
}

export interface ReviewPanel {
  user_id: string;
  alias: string;
  role: "adolescent" | "caregiver";
  series: { field_id: string; label: string; urge: boolean; points: SeriesPoint[] }[];
  skill_use: { entries_with_skill: number; skills: { skill_id: string; name: string; count: number }[] };
  completion: {
    days_with_entries: number;
    days: number;
    entries: number;
    days_per_week: number;
    expected_days: number;
  };
  entries: ReviewEntry[];
}

export interface FamilyReview {
  from: string;
  to: string;
  days: number;
  days_per_week: number;
  participants: ReviewPanel[];
}

export const REVIEW_DAYS = [7, 14, 30, 90] as const;

export const diaryReview = {
  family: (familyId: string, days: number) => get<FamilyReview>(`/families/${familyId}/diary?days=${days}`),
  revisions: (familyId: string, entryId: string) =>
    get<{ revisions: DiaryRevision[] }>(`/families/${familyId}/diary/entries/${entryId}/revisions`),
};

/** Values the template would actually show (hidden follow-ups dropped, as the server does). */
export function visibleValues(t: DiaryTemplate, values: DiaryValues): DiaryValues {
  const out: DiaryValues = {};
  for (const g of t.groups) {
    for (const f of g.fields) {
      if (f.type === "note") continue;
      const v = values[f.id];
      if (v === undefined) continue;
      if (f.show_if && values[f.show_if] !== true) continue;
      out[f.id] = v;
    }
  }
  return out;
}
