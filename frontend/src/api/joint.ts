/**
 * Joint sessions (Plan §5.9): invitations, the room WebSocket, the therapist board and the
 * episode registry. Room state is server-owned; the client sends typed actions only.
 */
import { del, get, api } from "./client";

export type Bi = { "zh-CN": string; en: string };
export type ParticipantRole = "adolescent" | "caregiver";

export interface EpisodeCard {
  id: string;
  version: number;
  title: Bi;
  objective: Bi;
  behavioral_criterion: Bi;
  estimated_minutes: number;
  skill_ids: string[];
  world: string;
  level: number;
  modes: string[];
}

export type ParticipantStatus =
  | "invited"
  | "accepted"
  | "ready"
  | "active"
  | "completed"
  | "ended"
  | "you_declined"
  | "wont_run"
  | "time_passed";

export interface MySession {
  id: string;
  mode: "joint" | "solo";
  episode: EpisodeCard | null;
  opens_at: string;
  closes_at: string;
  status: ParticipantStatus;
  can_respond: boolean;
  can_join: boolean;
}

// --- room projection (server: app/joint/engine.py project_for_role) ---

export interface Option {
  id: string;
  text: Bi;
}
export interface Piece extends Option {
  rubric_tag: string;
  by: ParticipantRole[];
}
export interface Feedback {
  title: Bi;
  text: Bi;
  notes: Bi[];
}
export interface StepView {
  id: string;
  type:
    | "narration"
    | "distress_check"
    | "private_choice"
    | "cooperative_compose"
    | "feedback"
    | "retry"
    | "transfer_probe"
    | "private_reflection";
  title: Bi | null;
  text: Bi;
  skippable: boolean;
  requires: "both" | "either";
  hints: Bi[];
  hints_left: number;
  my_act: "submitted" | "skipped" | null | undefined;
  partner_acted: boolean | null;
  phase?: "input" | "review";
  prompt?: Bi | null;
  options?: Option[];
  my_choice?: string | null;
  my_feedback?: Bi | null;
  revealed?: Partial<Record<ParticipantRole, { text?: Bi; rubric_tag?: string }>>;
  fragments?: Option[];
  rules?: { min_per_role: number; max_per_role: number };
  my_fragments?: string[] | null;
  partner_count?: number | null;
  composition?: Piece[];
  feedback?: Feedback;
  max_chars?: number;
}
export interface RoomView {
  phase: "lobby" | "running" | "paused" | "completed" | "ended";
  pause: "pause" | "hold" | null;
  me: ParticipantRole;
  solo: boolean;
  ready: { me: boolean; partner: boolean | null };
  partner_present: boolean | null;
  step_index: number;
  step_count: number;
  step: StepView | null;
  end_reason: "ended" | null;
}

export type RoomAction =
  | { type: "ready" | "pause" | "resume" | "leave" | "stop" }
  | { type: "submit" | "skip" | "hint" | "distress"; step_id: string; value?: unknown };

// --- therapist board ---

export interface BoardPerson {
  alias: string;
  response: "accepted" | "declined" | null;
  present: boolean;
}
export interface Board {
  phase: string;
  pause_by: string | null;
  ready: Record<string, boolean>;
  step_index: number;
  step_count: number;
  step_id: string | null;
  step_type: string | null;
  acted: Record<string, boolean>;
  end_reason: string | null;
}
export interface BoardSession {
  id: string;
  family_id: string;
  mode: string;
  episode: EpisodeCard | null;
  opens_at: string;
  closes_at: string;
  status: "invited" | "declined" | "cancelled" | "active" | "completed" | "ended";
  time_passed: boolean;
  adolescent: BoardPerson | null;
  caregiver: BoardPerson | null;
  board: Board | null;
}
export interface CatalogWorld {
  id: string;
  name: Bi;
  levels: { level: number; focus: Bi; skill_ids: string[]; target_minutes: [number, number] }[];
}
export interface GroupJoint {
  families: {
    id: string;
    label: string;
    is_demo: boolean;
    pairs: {
      caregiver_id: string;
      caregiver_alias: string;
      adolescent_alias: string | null;
      suitable: boolean;
    }[];
  }[];
  episodes: (EpisodeCard & { status: string; assignable_families: string[] })[];
  catalog: CatalogWorld[];
  sessions: BoardSession[];
}
export interface ScheduleIn {
  family_id: string;
  caregiver_id: string;
  episode_id: string;
  episode_version: number;
  opens_at: string;
  closes_at: string;
}
export type ControlAction = "pause" | "resume" | "safety_pause" | "terminate" | "reset";
export interface SessionSummary {
  id: string;
  status: string;
  episode: EpisodeCard | null;
  aliases: Partial<Record<ParticipantRole, string>>;
  record: {
    status: "completed" | "partial";
    completed_step_ids: string[];
    skipped_step_ids: string[];
    shared_rubric_tags: string[];
    started_at: string | null;
    ended_at: string;
  } | null;
  steps: { id: string; type: StepView["type"] }[];
  rubric: Partial<Record<ParticipantRole, Record<string, string[]>>>;
  responses: Partial<Record<ParticipantRole, { response: string; join_location: string | null }>>;
  distress: { role: ParticipantRole | null; step_id: string | null; value: number | null }[];
  reflections: { role: ParticipantRole | null; text: string; flagged: boolean }[];
  safety_event_ids: string[];
}
export interface EpisodeRow extends EpisodeCard {
  status: string;
  file_status: string;
}

export const joint = {
  mine: () => get<{ sessions: MySession[] }>("/joint/sessions"),
  one: (id: string) => get<MySession>(`/joint/sessions/${id}`),
  respond: (id: string, response: "accepted" | "declined") =>
    api<MySession>("POST", `/joint/sessions/${id}/respond`, { response }),
  solo: () => api<MySession>("POST", "/joint/solo", {}),
  group: (groupId: string) => get<GroupJoint>(`/groups/${groupId}/joint`),
  schedule: (groupId: string, body: ScheduleIn) =>
    api<{ id: string }>("POST", `/groups/${groupId}/joint-sessions`, body),
  cancel: (id: string) => del(`/joint-sessions/${id}`),
  control: (id: string, action: ControlAction) =>
    api<{ board: Board | null }>("POST", `/joint-sessions/${id}/control`, { action }),
  summary: (id: string) => get<SessionSummary>(`/joint-sessions/${id}/summary`),
  episodes: () => get<{ can_approve: boolean; episodes: EpisodeRow[] }>("/episodes"),
  decide: (id: string, version: number, status: "approved" | "retired") =>
    api<EpisodeRow>("POST", `/episodes/${id}/versions/${version}/decision`, { status }),
};

export function bi(text: Bi | null | undefined, lang: string): string {
  if (!text) return "";
  return lang.startsWith("zh") ? text["zh-CN"] : text.en;
}

export function roomUrl(sessionId: string): string {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}/api/v1/joint/sessions/${sessionId}/ws`;
}
