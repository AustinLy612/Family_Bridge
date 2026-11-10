import type { FeedbackSummary, PlayerRole } from "./types";

export const EMOTIONS = [
  { id: "disappointed", label: "Disappointed", hint: "Something mattered, and it did not work out." },
  { id: "frustrated", label: "Frustrated", hint: "Repeated effort has become tiring." },
  { id: "sad", label: "Sad", hint: "The keeper has gone quiet and withdrawn." },
  { id: "embarrassed", label: "Embarrassed", hint: "It may worry that others noticed the attempts." },
] as const;

export const SUPPORT_NEEDS = [
  { id: "heard", label: "To feel heard before solving" },
  { id: "company", label: "Quiet company and patience" },
  { id: "encouragement", label: "Gentle encouragement without pressure" },
] as const;

export const LEVEL_ONE_RESPONSES = [
  {
    id: "fix",
    text: "Don’t worry! Let’s fix it right away.",
    kind: "problem-solving",
    reaction: "The keeper glances at the lantern, but stays curled beneath the tree.",
  },
  {
    id: "minimize",
    text: "It’s not that difficult. Just try again.",
    kind: "minimizing",
    reaction: "The keeper’s ears dip. It seems less ready to talk.",
  },
  {
    id: "validate",
    text: "You seem really disappointed after trying so hard. Would you like to tell me what happened?",
    kind: "validating",
    reaction: "The keeper looks up. A small amber spark returns to the lantern.",
  },
] as const;

export const INDIVIDUAL_RESPONSES: Record<PlayerRole, ReadonlyArray<{ id: string; label: string; style: string }>> = {
  adolescent: [
    { id: "a-reflect", label: "Name the disappointment and stay curious", style: "validation" },
    { id: "a-cheer", label: "Cheer the keeper up immediately", style: "reassurance" },
    { id: "a-space", label: "Give quiet space, then check in", style: "attuned-space" },
  ],
  caregiver: [
    { id: "c-ask", label: "Acknowledge the effort, then ask what happened", style: "validation" },
    { id: "c-demo", label: "Show the keeper the correct lantern technique", style: "problem-solving" },
    { id: "c-push", label: "Remind the keeper that persistence is important", style: "encouragement" },
  ],
};

export const COOPERATIVE_FRAGMENTS = [
  { id: "notice", text: "You’ve tried again and again,", tag: "observation" },
  { id: "name", text: "and it makes sense that you feel disappointed.", tag: "validation" },
  { id: "ask", text: "Would you like to tell us what happened", tag: "curiosity" },
  { id: "choice", text: "or would quiet company feel better for now?", tag: "agency" },
  { id: "fix", text: "We can show you how to fix it.", tag: "problem-solving" },
  { id: "push", text: "You only need to try one more time.", tag: "pressure" },
] as const;

export const TRANSFER_RESPONSES = [
  {
    id: "fox-validate",
    text: "You were hoping they would wait. It makes sense that being left out hurt.",
    validating: true,
  },
  {
    id: "fox-fix",
    text: "Let’s find another task for you so it doesn’t matter anymore.",
    validating: false,
  },
  {
    id: "fox-minimize",
    text: "They probably didn’t mean it, so try not to be upset.",
    validating: false,
  },
] as const;

export function buildCooperativeFeedback(fragmentIds: string[]): FeedbackSummary {
  const tags = new Set(
    COOPERATIVE_FRAGMENTS.filter((fragment) => fragmentIds.includes(fragment.id)).map((fragment) => fragment.tag),
  );
  const strengths: string[] = [];
  if (tags.has("observation")) strengths.push("You noticed the effort without judging it.");
  if (tags.has("validation")) strengths.push("You named a feeling and showed that it made sense.");
  if (tags.has("curiosity")) strengths.push("You invited the keeper’s perspective instead of assuming it.");
  if (tags.has("agency")) strengths.push("You offered choice, which reduces pressure.");

  const strongValidation = tags.has("validation") && (tags.has("curiosity") || tags.has("agency"));
  return {
    title: strongValidation ? "The lantern hears both of you" : "A thoughtful first spark",
    message: strongValidation
      ? "Your shared reply pauses long enough for emotion before moving toward action. That is the heart of validation."
      : "You worked together and stayed engaged. Try placing one feeling-reflection before advice or encouragement.",
    strengths: strengths.length ? strengths : ["Both partners contributed to the shared response."],
    nextStep: tags.has("problem-solving") || tags.has("pressure")
      ? "Next time, ask whether support or problem-solving is wanted before offering a solution."
      : "Carry the same sequence forward: notice, name, invite, then ask what support would help.",
  };
}

export const STATE_PROGRESS: Record<string, number> = {
  WELCOME: 0,
  STORY_INTRO: 10,
  EMOTION_RECOGNITION: 25,
  INDIVIDUAL_RESPONSE: 40,
  WAITING_FOR_PARTNER: 50,
  COOPERATIVE_TASK: 65,
  SKILL_FEEDBACK: 82,
  TRANSFER_REFLECTION: 92,
  COMPLETED: 100,
  PAUSED: 50,
  TERMINATED: 0,
};
