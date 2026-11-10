export const GAME_STATES = [
  "WELCOME",
  "STORY_INTRO",
  "EMOTION_RECOGNITION",
  "INDIVIDUAL_RESPONSE",
  "WAITING_FOR_PARTNER",
  "COOPERATIVE_TASK",
  "SKILL_FEEDBACK",
  "TRANSFER_REFLECTION",
  "COMPLETED",
  "PAUSED",
  "TERMINATED",
] as const;

export type GameState = (typeof GAME_STATES)[number];
export type PlayerRole = "adolescent" | "caregiver";

export interface ParticipantStatus {
  role: PlayerRole;
  connected: boolean;
  confirmed: boolean;
  hasSubmitted: boolean;
}

export interface RevealedPerspective {
  adolescent?: {
    emotion: string;
    supportNeed: string;
  };
  caregiver?: {
    observation: string;
    responseStyle: string;
  };
}

export interface FeedbackSummary {
  title: string;
  message: string;
  strengths: string[];
  nextStep: string;
}

export interface PublicRoomState {
  code: string;
  state: GameState;
  level: 2;
  pausedFrom?: GameState;
  participants: Partial<Record<PlayerRole, ParticipantStatus>>;
  currentRole?: PlayerRole;
  ownChoices?: {
    emotion?: string;
    supportNeed?: string;
    individualResponse?: string;
    fragments?: string[];
    transferResponse?: string;
  };
  revealedPerspective?: RevealedPerspective;
  cooperativeFragments: string[];
  feedback?: FeedbackSummary;
  lanternPower: number;
  updatedAt: number;
  simulatedAuthentication: true;
}

export interface SocketAck<T = unknown> {
  ok: boolean;
  data?: T;
  error?: string;
}

export interface TherapistSessionSummary {
  code: string;
  state: GameState;
  level: number;
  participants: Partial<Record<PlayerRole, ParticipantStatus>>;
  completion: number;
  skillSummary: string;
  updatedAt: number;
}
