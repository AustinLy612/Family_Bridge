import { randomBytes } from "node:crypto";
import {
  COOPERATIVE_FRAGMENTS,
  EMOTIONS,
  INDIVIDUAL_RESPONSES,
  STATE_PROGRESS,
  SUPPORT_NEEDS,
  TRANSFER_RESPONSES,
  buildCooperativeFeedback,
} from "../shared/content";
import type {
  FeedbackSummary,
  GameState,
  PlayerRole,
  PublicRoomState,
  TherapistSessionSummary,
} from "../shared/types";

export const DEMO_THERAPIST_KEY = "lantern-demo";

interface Participant {
  role: PlayerRole;
  clientId: string;
  socketId: string;
  connected: boolean;
  confirmed: boolean;
  introReady: boolean;
  emotion?: string;
  supportNeed?: string;
  individualResponse?: string;
  fragments?: string[];
  feedbackAcknowledged: boolean;
  transferResponse?: string;
}

interface Room {
  code: string;
  state: GameState;
  pausedFrom?: GameState;
  participants: Partial<Record<PlayerRole, Participant>>;
  cooperativeFragments: string[];
  feedback?: FeedbackSummary;
  createdAt: number;
  updatedAt: number;
}

const roles: PlayerRole[] = ["adolescent", "caregiver"];

function isRole(value: unknown): value is PlayerRole {
  return value === "adolescent" || value === "caregiver";
}

function normalizeCode(code: string): string {
  return code.trim().toUpperCase();
}

export class GameRoomStore {
  private readonly rooms = new Map<string, Room>();

  createRoom(role: PlayerRole, clientId: string, socketId = "test-socket"): PublicRoomState {
    this.assertIdentity(role, clientId);
    const code = this.createCode();
    const now = Date.now();
    const room: Room = {
      code,
      state: "WELCOME",
      participants: {},
      cooperativeFragments: [],
      createdAt: now,
      updatedAt: now,
    };
    room.participants[role] = this.newParticipant(role, clientId, socketId);
    this.rooms.set(code, room);
    return this.publicFor(code, role, clientId);
  }

  joinRoom(codeInput: string, role: PlayerRole, clientId: string, socketId = "test-socket"): PublicRoomState {
    this.assertIdentity(role, clientId);
    const code = normalizeCode(codeInput);
    const room = this.requireRoom(code);
    if (room.state === "TERMINATED") throw new Error("This session has ended. Start a new demo room.");

    const existing = room.participants[role];
    if (existing && existing.clientId !== clientId) {
      throw new Error(`The ${role} role is already taken in this room.`);
    }
    if (existing) {
      existing.socketId = socketId;
      existing.connected = true;
    } else {
      room.participants[role] = this.newParticipant(role, clientId, socketId);
    }
    this.touch(room);
    return this.publicFor(code, role, clientId);
  }

  confirmParticipation(code: string, role: PlayerRole, clientId: string): PublicRoomState {
    const { room, participant } = this.authorizeParticipant(code, role, clientId);
    this.assertPlayable(room);
    participant.confirmed = true;
    if (this.both(room, (player) => player.confirmed)) room.state = "STORY_INTRO";
    this.touch(room);
    return this.publicFor(room.code, role, clientId);
  }

  beginStory(code: string, role: PlayerRole, clientId: string): PublicRoomState {
    const { room, participant } = this.authorizeParticipant(code, role, clientId);
    if (room.state !== "STORY_INTRO") throw new Error("The forest path is not ready for this step.");
    if (!this.both(room, (player) => player.confirmed)) throw new Error("Both participants must confirm first.");
    participant.introReady = true;
    if (this.both(room, (player) => player.introReady)) room.state = "EMOTION_RECOGNITION";
    this.touch(room);
    return this.publicFor(room.code, role, clientId);
  }

  submitEmotion(
    code: string,
    role: PlayerRole,
    clientId: string,
    emotion: string,
    supportNeed: string,
  ): PublicRoomState {
    const { room, participant } = this.authorizeParticipant(code, role, clientId);
    if (room.state !== "EMOTION_RECOGNITION") throw new Error("Emotion choices are not open right now.");
    if (!EMOTIONS.some((choice) => choice.id === emotion)) throw new Error("Choose a listed emotion.");
    if (!SUPPORT_NEEDS.some((choice) => choice.id === supportNeed)) throw new Error("Choose a listed support need.");
    participant.emotion = emotion;
    participant.supportNeed = supportNeed;
    if (this.both(room, (player) => Boolean(player.emotion && player.supportNeed))) room.state = "INDIVIDUAL_RESPONSE";
    this.touch(room);
    return this.publicFor(room.code, role, clientId);
  }

  submitIndividual(code: string, role: PlayerRole, clientId: string, responseId: string): PublicRoomState {
    const { room, participant } = this.authorizeParticipant(code, role, clientId);
    if (room.state !== "INDIVIDUAL_RESPONSE" && room.state !== "WAITING_FOR_PARTNER") {
      throw new Error("Individual responses are not open right now.");
    }
    if (!INDIVIDUAL_RESPONSES[role].some((response) => response.id === responseId)) {
      throw new Error("Choose a response written for your role.");
    }
    participant.individualResponse = responseId;
    room.state = this.both(room, (player) => Boolean(player.individualResponse))
      ? "COOPERATIVE_TASK"
      : "WAITING_FOR_PARTNER";
    this.touch(room);
    return this.publicFor(room.code, role, clientId);
  }

  submitCooperative(code: string, role: PlayerRole, clientId: string, fragmentIds: string[]): PublicRoomState {
    const { room, participant } = this.authorizeParticipant(code, role, clientId);
    if (room.state !== "COOPERATIVE_TASK") throw new Error("The shared reply is not open right now.");
    const unique = [...new Set(fragmentIds)];
    if (unique.length < 1 || unique.length > 3) throw new Error("Choose one to three response fragments.");
    if (unique.some((id) => !COOPERATIVE_FRAGMENTS.some((fragment) => fragment.id === id))) {
      throw new Error("One of those response fragments is not available.");
    }
    participant.fragments = unique;
    if (this.both(room, (player) => Boolean(player.fragments?.length))) {
      const allIds = new Set(roles.flatMap((playerRole) => room.participants[playerRole]?.fragments ?? []));
      room.cooperativeFragments = COOPERATIVE_FRAGMENTS.filter((fragment) => allIds.has(fragment.id)).map(
        (fragment) => fragment.id,
      );
      room.feedback = buildCooperativeFeedback(room.cooperativeFragments);
      room.state = "SKILL_FEEDBACK";
    }
    this.touch(room);
    return this.publicFor(room.code, role, clientId);
  }

  acknowledgeFeedback(code: string, role: PlayerRole, clientId: string): PublicRoomState {
    const { room, participant } = this.authorizeParticipant(code, role, clientId);
    if (room.state !== "SKILL_FEEDBACK") throw new Error("Feedback is not ready yet.");
    participant.feedbackAcknowledged = true;
    if (this.both(room, (player) => player.feedbackAcknowledged)) room.state = "TRANSFER_REFLECTION";
    this.touch(room);
    return this.publicFor(room.code, role, clientId);
  }

  submitTransfer(code: string, role: PlayerRole, clientId: string, responseId: string): PublicRoomState {
    const { room, participant } = this.authorizeParticipant(code, role, clientId);
    if (room.state !== "TRANSFER_REFLECTION") throw new Error("The transfer scene is not open right now.");
    if (!TRANSFER_RESPONSES.some((response) => response.id === responseId)) {
      throw new Error("Choose one of the available replies.");
    }
    participant.transferResponse = responseId;
    if (this.both(room, (player) => Boolean(player.transferResponse))) room.state = "COMPLETED";
    this.touch(room);
    return this.publicFor(room.code, role, clientId);
  }

  pause(code: string, role: PlayerRole, clientId: string): PublicRoomState {
    const { room } = this.authorizeParticipant(code, role, clientId);
    if (["COMPLETED", "TERMINATED", "PAUSED"].includes(room.state)) throw new Error("This session cannot be paused now.");
    room.pausedFrom = room.state;
    room.state = "PAUSED";
    this.touch(room);
    return this.publicFor(room.code, role, clientId);
  }

  resume(code: string, role: PlayerRole, clientId: string): PublicRoomState {
    const { room } = this.authorizeParticipant(code, role, clientId);
    if (room.state !== "PAUSED" || !room.pausedFrom) throw new Error("This session is not paused.");
    room.state = room.pausedFrom;
    room.pausedFrom = undefined;
    this.touch(room);
    return this.publicFor(room.code, role, clientId);
  }

  terminate(code: string, role: PlayerRole, clientId: string): PublicRoomState {
    const { room } = this.authorizeParticipant(code, role, clientId);
    room.state = "TERMINATED";
    room.pausedFrom = undefined;
    this.touch(room);
    return this.publicFor(room.code, role, clientId);
  }

  disconnect(socketId: string): string | undefined {
    for (const room of this.rooms.values()) {
      for (const role of roles) {
        const participant = room.participants[role];
        if (participant?.socketId === socketId) {
          participant.connected = false;
          this.touch(room);
          return room.code;
        }
      }
    }
    return undefined;
  }

  therapistControl(codeInput: string, action: "pause" | "resume" | "terminate" | "reset", key: string): void {
    if (key !== DEMO_THERAPIST_KEY) throw new Error("Therapist demo permission required.");
    const room = this.requireRoom(normalizeCode(codeInput));
    if (action === "pause") {
      if (!["COMPLETED", "TERMINATED", "PAUSED"].includes(room.state)) {
        room.pausedFrom = room.state;
        room.state = "PAUSED";
      }
    } else if (action === "resume") {
      if (room.state === "PAUSED" && room.pausedFrom) {
        room.state = room.pausedFrom;
        room.pausedFrom = undefined;
      }
    } else if (action === "terminate") {
      room.state = "TERMINATED";
      room.pausedFrom = undefined;
    } else {
      room.state = "WELCOME";
      room.pausedFrom = undefined;
      room.feedback = undefined;
      room.cooperativeFragments = [];
      for (const participant of Object.values(room.participants)) {
        if (!participant) continue;
        participant.confirmed = false;
        participant.introReady = false;
        participant.emotion = undefined;
        participant.supportNeed = undefined;
        participant.individualResponse = undefined;
        participant.fragments = undefined;
        participant.feedbackAcknowledged = false;
        participant.transferResponse = undefined;
      }
    }
    this.touch(room);
  }

  publicFor(codeInput: string, role?: PlayerRole, clientId?: string): PublicRoomState {
    const room = this.requireRoom(normalizeCode(codeInput));
    const own = role && clientId ? room.participants[role] : undefined;
    if (role && clientId && own?.clientId !== clientId) throw new Error("Participant identity does not match this room.");
    const reveal = ["COOPERATIVE_TASK", "SKILL_FEEDBACK", "TRANSFER_REFLECTION", "COMPLETED"].includes(room.state);
    const adolescent = room.participants.adolescent;
    const caregiver = room.participants.caregiver;
    const caregiverResponse = INDIVIDUAL_RESPONSES.caregiver.find((item) => item.id === caregiver?.individualResponse);

    return {
      code: room.code,
      state: room.state,
      level: 2,
      pausedFrom: room.pausedFrom,
      participants: Object.fromEntries(
        roles.flatMap((participantRole) => {
          const participant = room.participants[participantRole];
          return participant
            ? [[participantRole, {
                role: participantRole,
                connected: participant.connected,
                confirmed: participant.confirmed,
                hasSubmitted: this.hasSubmittedForState(participant, room.state),
              }]]
            : [];
        }),
      ),
      currentRole: role,
      ownChoices: own
        ? {
            emotion: own.emotion,
            supportNeed: own.supportNeed,
            individualResponse: own.individualResponse,
            fragments: own.fragments,
            transferResponse: own.transferResponse,
          }
        : undefined,
      revealedPerspective: reveal
        ? {
            adolescent: adolescent?.emotion && adolescent.supportNeed
              ? { emotion: adolescent.emotion, supportNeed: adolescent.supportNeed }
              : undefined,
            caregiver: caregiverResponse
              ? { observation: "The keeper attempted three careful lighting methods before withdrawing.", responseStyle: caregiverResponse.style }
              : undefined,
          }
        : undefined,
      cooperativeFragments: room.cooperativeFragments,
      feedback: reveal ? room.feedback : undefined,
      lanternPower: this.lanternPower(room.state),
      updatedAt: room.updatedAt,
      simulatedAuthentication: true,
    };
  }

  listTherapistSessions(key: string): TherapistSessionSummary[] {
    if (key !== DEMO_THERAPIST_KEY) throw new Error("Therapist demo permission required.");
    return [...this.rooms.values()]
      .sort((a, b) => b.updatedAt - a.updatedAt)
      .map((room) => ({
        code: room.code,
        state: room.state,
        level: 2,
        participants: this.publicFor(room.code).participants,
        completion: STATE_PROGRESS[room.state] ?? 0,
        skillSummary: room.feedback?.message ?? "Emotion recognition and validation in progress",
        updatedAt: room.updatedAt,
      }));
  }

  private newParticipant(role: PlayerRole, clientId: string, socketId: string): Participant {
    return {
      role,
      clientId,
      socketId,
      connected: true,
      confirmed: false,
      introReady: false,
      feedbackAcknowledged: false,
    };
  }

  private authorizeParticipant(codeInput: string, role: PlayerRole, clientId: string): { room: Room; participant: Participant } {
    const room = this.requireRoom(normalizeCode(codeInput));
    const participant = room.participants[role];
    if (!participant || participant.clientId !== clientId) throw new Error("This role is not assigned to this participant.");
    return { room, participant };
  }

  private assertIdentity(role: PlayerRole, clientId: string): void {
    if (!isRole(role)) throw new Error("Choose adolescent or caregiver.");
    if (!clientId || clientId.length < 8 || clientId.length > 100) throw new Error("A valid local demo identity is required.");
  }

  private assertPlayable(room: Room): void {
    if (room.state === "TERMINATED") throw new Error("This session has ended.");
    if (room.state === "PAUSED") throw new Error("This session is paused.");
  }

  private requireRoom(code: string): Room {
    const room = this.rooms.get(code);
    if (!room) throw new Error("Room not found. Check the four-letter code.");
    return room;
  }

  private both(room: Room, predicate: (participant: Participant) => boolean): boolean {
    return roles.every((role) => {
      const participant = room.participants[role];
      return Boolean(participant && predicate(participant));
    });
  }

  private hasSubmittedForState(participant: Participant, state: GameState): boolean {
    if (state === "STORY_INTRO") return participant.introReady;
    if (state === "EMOTION_RECOGNITION") return Boolean(participant.emotion);
    if (state === "INDIVIDUAL_RESPONSE" || state === "WAITING_FOR_PARTNER") return Boolean(participant.individualResponse);
    if (state === "COOPERATIVE_TASK") return Boolean(participant.fragments?.length);
    if (state === "SKILL_FEEDBACK") return participant.feedbackAcknowledged;
    if (state === "TRANSFER_REFLECTION" || state === "COMPLETED") return Boolean(participant.transferResponse);
    return participant.confirmed;
  }

  private lanternPower(state: GameState): number {
    return Math.min(100, Math.max(8, (STATE_PROGRESS[state] ?? 0) + 8));
  }

  private createCode(): string {
    const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ";
    for (let attempt = 0; attempt < 100; attempt += 1) {
      const bytes = randomBytes(4);
      const code = [...bytes].map((byte) => alphabet[byte % alphabet.length]).join("");
      if (!this.rooms.has(code)) return code;
    }
    throw new Error("Could not create a unique room code.");
  }

  private touch(room: Room): void {
    room.updatedAt = Date.now();
  }
}
