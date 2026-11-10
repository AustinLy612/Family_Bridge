import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useState } from "react";
import { EMOTIONS, LEVEL_ONE_RESPONSES, TRANSFER_RESPONSES } from "../../shared/content";
import { ChoiceButton, Dialogue, SceneChrome } from "../components/SceneChrome";
import { ForestScene } from "../components/ForestScene";
import { genAIDBTService, type SkillResponseEvaluation } from "../services/GenAIDBTService";
import { useGentleChime } from "../hooks/useGentleChime";

type SoloStage = "intro" | "emotion" | "response" | "feedback" | "transfer" | "complete";

const progress: Record<SoloStage, number> = { intro: 8, emotion: 28, response: 48, feedback: 68, transfer: 86, complete: 100 };
const emotionIcons: Record<string, string> = { disappointed: "◒", frustrated: "≈", sad: "☂", embarrassed: "◌" };
const responseGestures: Record<string, { icon: string; action: string }> = {
  fix: { icon: "✧", action: "Reach for the lantern" },
  minimize: { icon: "↟", action: "Urge Moss onward" },
  validate: { icon: "❧", action: "Sit beside Moss" },
};

export function SoloGame({
  reducedMotion,
  soundEnabled,
  onExit,
}: {
  reducedMotion: boolean;
  soundEnabled: boolean;
  onExit: () => void;
}) {
  const [stage, setStage] = useState<SoloStage>("intro");
  const [emotions, setEmotions] = useState<string[]>([]);
  const [response, setResponse] = useState("");
  const [feedback, setFeedback] = useState<SkillResponseEvaluation>();
  const [transfer, setTransfer] = useState("");
  const [hint, setHint] = useState("");
  const playChime = useGentleChime(soundEnabled);

  useEffect(() => {
    if (stage === "feedback" && feedback?.category === "validation") playChime();
  }, [feedback, playChime, stage]);

  const chooseResponse = async (id: string) => {
    setResponse(id);
    setFeedback(await genAIDBTService.evaluateSkillResponse(id));
    setStage("feedback");
  };

  const keeperMood = stage === "intro" || feedback?.category === "minimizing"
    ? "hurt"
    : stage === "complete" || feedback?.category === "validation"
      ? "bright"
      : feedback?.category === "problem-solving"
        ? "hopeful"
        : "quiet";
  const lanternPower = stage === "complete" ? 100 : progress[stage] * 0.78;

  return (
    <main className="game-screen">
      <ForestScene lanternPower={lanternPower} keeperMood={keeperMood} reducedMotion={reducedMotion} completed={stage === "complete"}>
        <SceneChrome
          eyebrow="Level 1 · Emotion recognition and validation"
          title="Understanding the Little Lantern Keeper"
          progress={progress[stage]}
          actions={<button className="ghost-button" onClick={onExit}>Leave gently</button>}
        >
          <AnimatePresence mode="wait">
            <motion.div
              key={stage}
              className={`stage-panel story-stage story-stage--${stage}`}
              aria-live="polite"
              initial={reducedMotion ? false : { opacity: 0, y: 14 }}
              animate={{ opacity: 1, y: 0 }}
              exit={reducedMotion ? undefined : { opacity: 0, y: -8 }}
            >
              {stage === "intro" && (
                <>
                  <Dialogue speaker="Moss, the lantern keeper">
                    “I tried so many times, but the lantern still won’t light. I don’t think I want to try again.”
                  </Dialogue>
                  <p className="narration">Moss settles beneath the old tree. The lantern gives one small, uncertain flicker.</p>
                  <button className="primary-button story-continue" onClick={() => setStage("emotion")}><span aria-hidden="true">❧</span> Approach slowly</button>
                </>
              )}

              {stage === "emotion" && (
                <>
                  <Dialogue speaker="Forest guide" tone="guide">What might Moss be feeling? More than one feeling can fit.</Dialogue>
                  <div className="choice-grid emotion-grid" role="group" aria-label="Possible emotions Moss may be feeling">
                    {EMOTIONS.map((emotion) => (
                      <ChoiceButton
                        key={emotion.id}
                        title={emotion.label}
                        detail={emotion.hint}
                        kind="emotion"
                        icon={emotionIcons[emotion.id]}
                        selected={emotions.includes(emotion.id)}
                        onClick={() => setEmotions((current) => current.includes(emotion.id)
                          ? current.filter((item) => item !== emotion.id)
                          : current.length < 2 ? [...current, emotion.id] : [current[1], emotion.id])}
                      />
                    ))}
                  </div>
                  <div className="stage-footer">
                    <span className="gentle-note">Choose one or two possibilities. There is no penalty.</span>
                    <button className="primary-button" disabled={!emotions.length} onClick={() => setStage("response")}>Follow the lantern glow</button>
                  </div>
                </>
              )}

              {stage === "response" && (
                <>
                  <Dialogue speaker="Forest guide" tone="guide">Which response makes space for the feeling before changing the situation?</Dialogue>
                  <div className="response-list">
                    {LEVEL_ONE_RESPONSES.map((option) => (
                      <button className="story-response story-action" key={option.id} onClick={() => void chooseResponse(option.id)}>
                        <span className="story-action-icon" aria-hidden="true">{responseGestures[option.id]?.icon}</span>
                        <span className="story-action-copy"><small>{responseGestures[option.id]?.action}</small><strong>{option.text}</strong></span>
                        <i aria-hidden="true">→</i>
                      </button>
                    ))}
                  </div>
                  <button className="hint-button" onClick={async () => setHint(await genAIDBTService.generateHint("level-one"))}>
                    ✦ Ask the fireflies for a hint
                  </button>
                  {hint && <p className="hint-text">{hint}</p>}
                </>
              )}

              {stage === "feedback" && feedback && (
                <>
                  <Dialogue speaker="Moss’s reaction">
                    {LEVEL_ONE_RESPONSES.find((option) => option.id === response)?.reaction}
                  </Dialogue>
                  <section className={`feedback-sheet feedback-${feedback.category}`}>
                    <p className="eyebrow">A skill, not a score</p>
                    <h3>{feedback.heading}</h3>
                    <p>{feedback.feedback}</p>
                    <div className="feedback-distinction">
                      <span>What is the difference?</span>
                      <p>{feedback.distinction}</p>
                    </div>
                    <p className="gentle-note">{feedback.invitation}</p>
                  </section>
                  <div className="stage-footer">
                    <button className="secondary-button" onClick={() => { setStage("response"); setHint(""); }}>Try another response</button>
                    <button className="primary-button" onClick={() => setStage("transfer")}>Visit the next clearing</button>
                  </div>
                </>
              )}

              {stage === "transfer" && (
                <>
                  <Dialogue speaker="A new path" tone="shared">
                    A small fox is upset because its friends completed a task without waiting for it.
                  </Dialogue>
                  <p className="narration">Which reply carries the same validation skill into this new, low-intensity situation?</p>
                  <div className="response-list compact-responses">
                    {TRANSFER_RESPONSES.map((option) => (
                        <ChoiceButton key={option.id} title={option.text} kind="transfer" icon="↝" selected={transfer === option.id} onClick={() => setTransfer(option.id)} />
                    ))}
                  </div>
                  {transfer && (
                    <p className={`transfer-note ${TRANSFER_RESPONSES.find((item) => item.id === transfer)?.validating ? "is-warm" : ""}`}>
                      {TRANSFER_RESPONSES.find((item) => item.id === transfer)?.validating
                        ? "This response identifies what mattered and why the feeling makes sense. The skill transfers."
                        : "This moves toward fixing or explaining. Try adding a sentence that first recognizes what the fox hoped for."}
                    </p>
                  )}
                  <div className="stage-footer">
                    <span className="gentle-note">No personal disclosure is needed.</span>
                    <button className="primary-button" disabled={!transfer} onClick={() => setStage("complete")}>Complete the practice</button>
                  </div>
                </>
              )}

              {stage === "complete" && (
                <section className="completion-message">
                  <span className="completion-lantern">✦</span>
                  <p className="eyebrow">Lantern restored</p>
                  <h3>The forest path is brighter</h3>
                  <p>Validation can begin with a simple sequence: notice, name, invite, then ask what support would help.</p>
                  <div className="completion-actions">
                    <button className="secondary-button" onClick={() => { setStage("intro"); setEmotions([]); setResponse(""); setFeedback(undefined); setTransfer(""); }}>Practice again</button>
                    <button className="primary-button" onClick={onExit}>Return to the forest gate</button>
                  </div>
                </section>
              )}
            </motion.div>
          </AnimatePresence>
        </SceneChrome>
      </ForestScene>
    </main>
  );
}
