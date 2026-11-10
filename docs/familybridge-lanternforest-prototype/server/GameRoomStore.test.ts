import { describe, expect, it } from "vitest";
import { DEMO_THERAPIST_KEY, GameRoomStore } from "./GameRoomStore";

const adolescentId = "adolescent-local-id";
const caregiverId = "caregiver-local-id";

function pairedRoom() {
  const store = new GameRoomStore();
  const created = store.createRoom("adolescent", adolescentId, "socket-a");
  store.joinRoom(created.code, "caregiver", caregiverId, "socket-c");
  return { store, code: created.code };
}

function reachEmotionStage(store: GameRoomStore, code: string) {
  store.confirmParticipation(code, "adolescent", adolescentId);
  store.confirmParticipation(code, "caregiver", caregiverId);
  store.beginStory(code, "adolescent", adolescentId);
  store.beginStory(code, "caregiver", caregiverId);
}

function reachCooperativeStage(store: GameRoomStore, code: string) {
  reachEmotionStage(store, code);
  store.submitEmotion(code, "adolescent", adolescentId, "disappointed", "heard");
  store.submitEmotion(code, "caregiver", caregiverId, "frustrated", "company");
  store.submitIndividual(code, "adolescent", adolescentId, "a-reflect");
  store.submitIndividual(code, "caregiver", caregiverId, "c-ask");
}

describe("authoritative game room store", () => {
  it("creates a short-code room and allows the other role to join", () => {
    const { store, code } = pairedRoom();
    const state = store.publicFor(code);
    expect(code).toMatch(/^[A-Z]{4}$/);
    expect(state.participants.adolescent?.connected).toBe(true);
    expect(state.participants.caregiver?.connected).toBe(true);
  });

  it("rejects duplicate role assignment", () => {
    const { store, code } = pairedRoom();
    expect(() => store.joinRoom(code, "caregiver", "different-caregiver", "other-socket")).toThrow(/already taken/i);
  });

  it("requires separate consent confirmation before story progression", () => {
    const { store, code } = pairedRoom();
    store.confirmParticipation(code, "adolescent", adolescentId);
    expect(store.publicFor(code).state).toBe("WELCOME");
    store.confirmParticipation(code, "caregiver", caregiverId);
    expect(store.publicFor(code).state).toBe("STORY_INTRO");
    store.beginStory(code, "adolescent", adolescentId);
    expect(store.publicFor(code).state).toBe("STORY_INTRO");
    store.beginStory(code, "caregiver", caregiverId);
    expect(store.publicFor(code).state).toBe("EMOTION_RECOGNITION");
  });

  it("keeps independent answers private until the permitted reveal stage", () => {
    const { store, code } = pairedRoom();
    reachEmotionStage(store, code);
    store.submitEmotion(code, "adolescent", adolescentId, "sad", "heard");
    const caregiverView = store.publicFor(code, "caregiver", caregiverId);
    expect(caregiverView.ownChoices?.emotion).toBeUndefined();
    expect(caregiverView.revealedPerspective).toBeUndefined();
  });

  it("blocks client attempts to skip server-controlled stages", () => {
    const { store, code } = pairedRoom();
    expect(() => store.submitCooperative(code, "adolescent", adolescentId, ["notice"])).toThrow(/not open/i);
    expect(() => store.submitTransfer(code, "caregiver", caregiverId, "fox-validate")).toThrow(/not open/i);
  });

  it("requires both participants to contribute to the cooperative task", () => {
    const { store, code } = pairedRoom();
    reachCooperativeStage(store, code);
    store.submitCooperative(code, "adolescent", adolescentId, ["notice", "name"]);
    expect(store.publicFor(code).state).toBe("COOPERATIVE_TASK");
    store.submitCooperative(code, "caregiver", caregiverId, ["ask", "choice"]);
    const feedback = store.publicFor(code);
    expect(feedback.state).toBe("SKILL_FEEDBACK");
    expect(feedback.cooperativeFragments).toEqual(["notice", "name", "ask", "choice"]);
    expect(feedback.feedback?.strengths.length).toBeGreaterThan(1);
  });

  it("completes feedback acknowledgement and transfer only when both contribute", () => {
    const { store, code } = pairedRoom();
    reachCooperativeStage(store, code);
    store.submitCooperative(code, "adolescent", adolescentId, ["notice"]);
    store.submitCooperative(code, "caregiver", caregiverId, ["name", "ask"]);
    store.acknowledgeFeedback(code, "adolescent", adolescentId);
    expect(store.publicFor(code).state).toBe("SKILL_FEEDBACK");
    store.acknowledgeFeedback(code, "caregiver", caregiverId);
    expect(store.publicFor(code).state).toBe("TRANSFER_REFLECTION");
    store.submitTransfer(code, "adolescent", adolescentId, "fox-validate");
    expect(store.publicFor(code).state).toBe("TRANSFER_REFLECTION");
    store.submitTransfer(code, "caregiver", caregiverId, "fox-fix");
    expect(store.publicFor(code).state).toBe("COMPLETED");
  });

  it("marks a disconnected participant without discarding recoverable room state", () => {
    const { store, code } = pairedRoom();
    reachEmotionStage(store, code);
    expect(store.disconnect("socket-c")).toBe(code);
    expect(store.publicFor(code).participants.caregiver?.connected).toBe(false);
    expect(store.publicFor(code).state).toBe("EMOTION_RECOGNITION");
    store.joinRoom(code, "caregiver", caregiverId, "socket-c2");
    expect(store.publicFor(code).participants.caregiver?.connected).toBe(true);
  });

  it("allows participant pause/termination while preserving a neutral state", () => {
    const { store, code } = pairedRoom();
    reachEmotionStage(store, code);
    store.pause(code, "adolescent", adolescentId);
    expect(store.publicFor(code).state).toBe("PAUSED");
    store.resume(code, "caregiver", caregiverId);
    expect(store.publicFor(code).state).toBe("EMOTION_RECOGNITION");
    store.terminate(code, "caregiver", caregiverId);
    expect(store.publicFor(code).state).toBe("TERMINATED");
  });

  it("protects therapist controls and can reset a demo room", () => {
    const { store, code } = pairedRoom();
    reachEmotionStage(store, code);
    expect(() => store.therapistControl(code, "pause", "wrong-key")).toThrow(/permission/i);
    store.therapistControl(code, "pause", DEMO_THERAPIST_KEY);
    expect(store.publicFor(code).state).toBe("PAUSED");
    store.therapistControl(code, "reset", DEMO_THERAPIST_KEY);
    const reset = store.publicFor(code);
    expect(reset.state).toBe("WELCOME");
    expect(reset.participants.adolescent?.confirmed).toBe(false);
  });
});
