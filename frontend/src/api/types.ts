/** Response shapes of the Phase 1 API (backend/app/api/schemas.py). */
import type { Role } from "../app/session";

export interface UserOut {
  id: string;
  pseudonym: string;
  username: string;
  role: Role;
  display_alias: string;
  language: "zh-CN" | "en";
  a11y_prefs: Record<string, unknown>;
  onboarded: boolean;
  is_demo: boolean;
}

export interface SessionOut {
  user: UserOut | null;
  csrf_token: string | null;
}

export interface CodeInfo {
  purpose: "invite" | "reset";
  role: Role;
  expires_at: string;
  username: string | null;
}

export interface ConsentCategory {
  id: string;
  required: boolean;
  default: boolean;
  grantee: string;
  title: string;
  summary: string;
}

export interface ConsentBlock {
  type: "paragraph" | "bullets";
  text: string | null;
  items: string[];
}

export interface HelpContact {
  label: Record<string, string>;
  phone: string;
  hours: Record<string, string>;
}

export interface SiteHelp {
  name: string;
  help_contacts: HelpContact[];
  service_hours: Record<string, string>;
  placeholder: boolean;
}

export interface OnboardingOut {
  completed: boolean;
  document: {
    document_id: string;
    version: number;
    language: string;
    approval: string;
    sections: { heading: string; blocks: ConsentBlock[] }[];
    categories: ConsentCategory[];
  };
  help: SiteHelp;
}

export interface ConsentState {
  category: string;
  required: boolean;
  granted: boolean;
  recorded_at: string | null;
}

export interface Viewer {
  kind: "self" | "assigned_therapist" | "family_member" | "admin" | "ai_provider" | "research";
  alias: string | null;
  role: Role | null;
  sees: string[];
}

export interface IssuedCode {
  invitation_id: string;
  code: string;
  expires_at: string;
}

export interface PendingInvite {
  id: string;
  role: Role;
  relationship_label: string | null;
  expires_at: string;
  created_at: string;
}

export interface TherapistOut {
  id: string;
  username: string;
  display_alias: string;
  status: "active" | "disabled";
  last_login_at: string | null;
  group_count: number;
  content_approver?: boolean;
}

export interface SiteOut {
  name: string;
  timezone: string;
  help_contacts: HelpContact[];
  service_hours: Record<string, string>;
  updated_at: string;
}

export interface GroupSummary {
  id: string;
  name: string;
  family_count: number;
  therapists: string[];
  is_demo: boolean;
}

export interface FamilySummary {
  id: string;
  label: string;
  member_count: number;
  pending_invites: number;
}

export interface GroupDetail extends GroupSummary {
  families: FamilySummary[];
}

export type Suitability = "suitable" | "not_suitable" | "not_assessed";

export interface MemberOut {
  user_id: string;
  pseudonym: string;
  display_alias: string;
  role: Role;
  relationship_label: string | null;
  onboarded: boolean;
  status: string;
}

export interface DyadOut {
  adolescent_id: string;
  caregiver_id: string;
  decision: Suitability;
  note: string | null;
  decided_at: string | null;
}

export interface FamilyDetail {
  id: string;
  group_id: string;
  label: string;
  members: MemberOut[];
  pending: PendingInvite[];
  dyads: DyadOut[];
}

// --- Phase 2: help screen and safety queue ----------------------------------------------------

export interface ContentSection {
  heading: string;
  blocks: ConsentBlock[];
}

export interface HelpNotice {
  title: string;
  body: string;
}

export interface HelpPageOut {
  document: {
    version: number;
    language: string;
    approval: string;
    stop_notice: HelpNotice;
    care_card: HelpNotice;
    sections: ContentSection[];
  };
  site: SiteHelp;
}

/** What a participant screen must do after the server screened their text (Plan §5.7). */
export type SafetyAction = "none" | "care_card" | "stop" | "help";

export type SafetyCategory =
  | "discomfort_or_trauma_cue"
  | "risk_disclosure"
  | "urge_threshold"
  | "suspected_abuse"
  | "parental_coercion"
  | "privacy_breach"
  | "delayed_clinician_response";
export type SafetySeverity = "low" | "medium" | "high";
export type SafetyStatus = "new" | "acknowledged" | "in_review" | "resolved";

export interface PersonRef {
  id: string;
  alias: string;
  role: Role;
}

export interface FamilyRef {
  id: string;
  label: string;
  group_id: string;
  group_name: string;
}

export interface SafetyEventSummary {
  id: string;
  category: SafetyCategory;
  severity: SafetySeverity;
  status: SafetyStatus;
  source: "lesson" | "diary" | "joint" | "manual";
  channel: "keyword" | "llm" | "threshold" | "manual" | "participant";
  subject: PersonRef;
  family: FamilyRef | null;
  assignee: PersonRef | null;
  occurrences: number;
  activity_stopped: boolean;
  created_at: string;
  updated_at: string;
}

export interface SafetyEventList {
  events: SafetyEventSummary[];
  counts: { new: number; open: number };
}

export interface SafetyEventDetail extends SafetyEventSummary {
  excerpt: string | null;
  matched_terms: string[];
  created_by: PersonRef | null;
  follow_up: string | null;
  resolved_by: PersonRef | null;
  notes: { id: string; author: PersonRef; body: string; created_at: string }[];
  timeline: { status: SafetyStatus; at: string }[];
  next_statuses: SafetyStatus[];
}

export interface SafetySubject {
  user: PersonRef;
  family: FamilyRef;
}

// --- knowledge base (Phase 3; admin status only, never manual text) -------------------------

export type KbStatusValue = "building" | "active" | "superseded" | "failed";

export interface KbEvalBucket {
  queries: number;
  recall: number;
  mrr: number;
}

export interface KbVersion {
  version: number;
  status: KbStatusValue;
  created_at: string;
  activated_at: string | null;
  chunk_count: number;
  embedding_model: string;
  source_pages: number;
  handout_index_version: number;
  handouts: number;
  chunks_by_module: Record<string, number>;
  chunks_by_source_quality: Record<string, number>;
  transcribed_pages: number[];
  header_mismatches: { page: number; found: string; expected: string }[];
  eval: {
    passed: boolean;
    k: number;
    target_recall: number;
    eval_set_version: number | null;
    overall: KbEvalBucket;
    by_language: Record<string, KbEvalBucket>;
    misses: number;
  } | null;
}

export interface KbStatus {
  active: KbVersion | null;
  history: { version: number; status: KbStatusValue; chunk_count: number; created_at: string }[];
  retrieval: { days: number; searches: number; insufficient: number; median_latency_ms: number | null };
  min_score: Record<string, number>;
}

// --- AI layer (Phase 4; admin status: counts and codes only) -------------------------------------

/** Where participant-facing content came from (backend ContentSource). */
export type ContentSource = "ai_manual" | "ai_general" | "authored" | "none";

export interface AiFunctionStats {
  function: string;
  calls: number;
  fallbacks: number;
  repaired: number;
  retried: number;
  general: number;
  median_latency_ms: number | null;
}

export interface AiEvalRun {
  kind: string;
  created_at: string;
  provider: string;
  model: string;
  passed: boolean;
  headline: Record<string, unknown>;
}

export interface AiStatus {
  provider: string;
  model: string;
  breaker: "closed" | "open" | "half_open";
  days: number;
  calls: number;
  fallbacks: number;
  functions: AiFunctionStats[];
  failure_codes: Record<string, number>;
  prompts: { function: string; role: string; language: string; version: number; approval: string }[];
  fallback_files: number;
  cache_items: number;
  cache_by_review: Record<string, number>;
  eval_runs: AiEvalRun[];
}
