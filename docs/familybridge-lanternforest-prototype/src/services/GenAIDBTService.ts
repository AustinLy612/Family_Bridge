export type SkillResponseEvaluation = {
  category: "validation" | "problem-solving" | "minimizing";
  heading: string;
  feedback: string;
  distinction: string;
  invitation: string;
};

export interface GenAIDBTService {
  explainSkill(skillId: string): Promise<string>;
  generateHint(context: string): Promise<string>;
  evaluateSkillResponse(responseId: string): Promise<SkillResponseEvaluation>;
  generateTransferScenario(skillId: string): Promise<{ title: string; prompt: string }>;
}

/**
 * Clinically reviewable local fallback. A production adapter may call the existing
 * RAG service, but must return typed, reviewed content and must never drive game state.
 */
export class LocalMockGenAIDBTService implements GenAIDBTService {
  async explainSkill(): Promise<string> {
    return "Validation communicates that a feeling is understandable in context. It does not require agreement, and it can come before advice.";
  }

  async generateHint(): Promise<string> {
    return "Try the lantern sequence: notice the effort, name a possible feeling, then invite the other person’s perspective.";
  }

  async evaluateSkillResponse(responseId: string): Promise<SkillResponseEvaluation> {
    if (responseId === "validate") {
      return {
        category: "validation",
        heading: "The keeper feels understood",
        feedback: "You noticed both the feeling and the effort, then made room for the keeper to speak.",
        distinction: "Validation pauses with the emotion before deciding whether a solution is needed.",
        invitation: "Notice how the reply stays curious rather than claiming to know everything.",
      };
    }
    if (responseId === "fix") {
      return {
        category: "problem-solving",
        heading: "Helpful intent, one step early",
        feedback: "Offering help can be caring. Here, the solution arrives before the keeper knows its disappointment has been heard.",
        distinction: "Problem-solving changes the situation; validation first acknowledges the emotional experience.",
        invitation: "Try again and add one sentence that names the feeling before offering help.",
      };
    }
    return {
      category: "minimizing",
      heading: "A chance to slow down",
      feedback: "This reply may make the task sound simple when it has felt difficult to the keeper.",
      distinction: "Minimizing reduces or corrects a feeling; validation shows why the feeling could make sense.",
      invitation: "Try again with words that recognize the effort and disappointment.",
    };
  }

  async generateTransferScenario(): Promise<{ title: string; prompt: string }> {
    return {
      title: "The fox at the mossy workshop",
      prompt: "A small fox is upset because its friends completed a task without waiting for it. What response makes room for the fox’s feeling?",
    };
  }
}

export const genAIDBTService: GenAIDBTService = new LocalMockGenAIDBTService();
