import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useMemo, useState } from "react";
import {
  COOPERATIVE_FRAGMENTS,
  EMOTIONS,
  INDIVIDUAL_RESPONSES,
  STATE_PROGRESS,
  SUPPORT_NEEDS,
  TRANSFER_RESPONSES,
} from "../../shared/content";
import type { PlayerRole, PublicRoomState } from "../../shared/types";
import { ChoiceButton, Dialogue, SceneChrome } from "../components/SceneChrome";
import { ForestScene } from "../components/ForestScene";
import { useRoom } from "../hooks/useRoom";
import { useGentleChime } from "../hooks/useGentleChime";

export function CooperativeGame({
  initialRole,
  reducedMotion,
  soundEnabled,
  onExit,
}: {
  initialRole: PlayerRole;
  reducedMotion: boolean;
  soundEnabled: boolean;
  onExit: () => void;
}) {
  const roomApi = useRoom();
  const [role, setRole] = useState<PlayerRole>(initialRole);
  const [joinCode, setJoinCode] = useState("");
  const room = roomApi.room;

  const leave = () => {
    roomApi.leaveLocal();
    onExit();
  };

  if (!room || room.state === "WELCOME") {
    return (
      <RoomLobby
        room={room}
        reducedMotion={reducedMotion}
        role={role}
        setRole={setRole}
        joinCode={joinCode}
        setJoinCode={setJoinCode}
        connected={roomApi.connected}
        busy={roomApi.busy}
        error={roomApi.error}
        onCreate={() => void roomApi.createRoom(role)}
        onJoin={() => void roomApi.joinRoom(joinCode, role)}
        onConfirm={() => void roomApi.confirm()}
        onExit={leave}
      />
    );
  }

  return (
    <SharedLevel
      room={room}
      reducedMotion={reducedMotion}
      soundEnabled={soundEnabled}
      busy={roomApi.busy}
      error={roomApi.error}
      actions={roomApi}
      onExit={leave}
    />
  );
}

function RoomLobby({
  room,
  reducedMotion,
  role,
  setRole,
  joinCode,
  setJoinCode,
  connected,
  busy,
  error,
  onCreate,
  onJoin,
  onConfirm,
  onExit,
}: {
  room?: PublicRoomState;
  reducedMotion: boolean;
  role: PlayerRole;
  setRole: (role: PlayerRole) => void;
  joinCode: string;
  setJoinCode: (code: string) => void;
  connected: boolean;
  busy: boolean;
  error: string;
  onCreate: () => void;
  onJoin: () => void;
  onConfirm: () => void;
  onExit: () => void;
}) {
  const own = room?.participants[role];
  return (
    <main className="lobby-screen">
      <ForestScene lanternPower={25} keeperMood="quiet" compact reducedMotion={reducedMotion}>
        <section className="lobby-panel">
          <div className="lobby-topline">
            <button className="ghost-button" onClick={onExit}>← Forest gate</button>
            <span className={`connection-pill ${connected ? "is-online" : ""}`}>{connected ? "Connected" : "Reconnecting…"}</span>
          </div>
          <p className="eyebrow">Level 2 · Lighting the Forest Together</p>
          <h1>Meet at the lantern clearing</h1>
          <p className="lobby-intro">Each person joins on a separate browser. Private choices remain private until the cooperative reveal.</p>

          {!room ? (
            <>
              <div className="role-switch" aria-label="Your demo role">
                {(["adolescent", "caregiver"] as const).map((item) => (
                  <button key={item} className={role === item ? "is-active" : ""} aria-pressed={role === item} onClick={() => setRole(item)}>
                    <span>{item === "adolescent" ? "☾" : "⌂"}</span>{item}
                  </button>
                ))}
              </div>
              <div className="room-options">
                <section>
                  <span className="option-number">01</span>
                  <h2>Create a room</h2>
                  <p>Start a new clearing and share the four-letter code.</p>
                  <button className="primary-button" onClick={onCreate} disabled={busy}>Create room</button>
                </section>
                <div className="or-divider"><span>or</span></div>
                <section>
                  <span className="option-number">02</span>
                  <h2>Join a partner</h2>
                  <p>Enter the code shown on your partner’s screen.</p>
                  <input
                    className="room-code-input"
                    aria-label="Four-letter room code"
                    maxLength={4}
                    placeholder="CODE"
                    value={joinCode}
                    onChange={(event) => setJoinCode(event.target.value.toUpperCase().replace(/[^A-Z]/g, ""))}
                  />
                  <button className="primary-button" onClick={onJoin} disabled={busy || joinCode.length !== 4}>Join room</button>
                </section>
              </div>
            </>
          ) : (
            <section className="ready-room">
              <div className="room-code-display">
                <small>Lantern room</small>
                <strong>{room.code}</strong>
                <button onClick={() => void navigator.clipboard?.writeText(room.code)}>Copy code</button>
              </div>
              <div className="participants-grid">
                {(["adolescent", "caregiver"] as const).map((participantRole) => {
                  const participant = room.participants[participantRole];
                  return (
                    <div key={participantRole} className={`participant-orb ${participant?.connected ? "is-present" : ""} ${participant?.confirmed ? "is-ready" : ""}`}>
                      <span>{participantRole === "adolescent" ? "☾" : "⌂"}</span>
                      <strong>{participantRole}</strong>
                      <small>{!participant ? "Waiting to join" : participant.confirmed ? "Ready for the path" : "Present · confirming"}</small>
                    </div>
                  );
                })}
              </div>
              <div className="consent-note">
                <span>◌</span>
                <p><strong>Choice at every step</strong>This fictional activity can be paused or left at any time. No personal disclosure is requested.</p>
              </div>
              <button className="primary-button wide-button" onClick={onConfirm} disabled={busy || own?.confirmed}>
                {own?.confirmed ? "You are ready · waiting for partner" : "Confirm participation"}
              </button>
            </section>
          )}
          {error && <p className="error-banner" role="alert">{error}</p>}
          <p className="auth-note">Simulated authentication for research demonstration only</p>
        </section>
      </ForestScene>
    </main>
  );
}

type RoomActions = ReturnType<typeof useRoom>;

function SharedLevel({
  room,
  reducedMotion,
  soundEnabled,
  busy,
  error,
  actions,
  onExit,
}: {
  room: PublicRoomState;
  reducedMotion: boolean;
  soundEnabled: boolean;
  busy: boolean;
  error: string;
  actions: RoomActions;
  onExit: () => void;
}) {
  const role = room.currentRole!;
  const [emotion, setEmotion] = useState("");
  const [support, setSupport] = useState("");
  const [individual, setIndividual] = useState("");
  const [fragments, setFragments] = useState<string[]>([]);
  const [transfer, setTransfer] = useState("");
  const playChime = useGentleChime(soundEnabled);
  const ownStatus = room.participants[role];
  const partnerRole: PlayerRole = role === "adolescent" ? "caregiver" : "adolescent";
  const partner = room.participants[partnerRole];

  useEffect(() => {
    if (room.state === "SKILL_FEEDBACK") playChime();
  }, [playChime, room.state]);

  const selectedSharedText = useMemo(() => COOPERATIVE_FRAGMENTS
    .filter((fragment) => fragments.includes(fragment.id))
    .map((fragment) => fragment.text)
    .join(" "), [fragments]);

  const keeperMood = room.state === "COMPLETED" || room.state === "SKILL_FEEDBACK"
    ? "bright"
    : room.state === "COOPERATIVE_TASK"
      ? "hopeful"
      : room.state === "STORY_INTRO"
        ? "hurt"
        : "quiet";

  return (
    <main className="game-screen">
      <ForestScene
        lanternPower={room.lanternPower}
        keeperMood={keeperMood}
        reducedMotion={reducedMotion}
        completed={room.state === "COMPLETED"}
      >
        <SceneChrome
          eyebrow={`Room ${room.code} · You are the ${role}`}
          title="Lighting the Forest Together"
          progress={STATE_PROGRESS[room.state] ?? 0}
          actions={
            <>
              <ParticipantMiniatures room={room} />
              {room.state === "PAUSED"
                ? <button className="ghost-button" onClick={() => void actions.resume()}>Resume</button>
                : !["COMPLETED", "TERMINATED"].includes(room.state) && <button className="ghost-button" onClick={() => void actions.pause()}>Pause</button>}
              <button className="ghost-button" onClick={() => {
                if (window.confirm("End this demo room for both participants?")) void actions.terminate();
              }}>End</button>
            </>
          }
        >
          {!partner?.connected && room.state !== "TERMINATED" && (
            <div className="partner-banner">The other lantern is offline. Their place is saved for reconnection.</div>
          )}
          {error && <p className="error-banner" role="alert">{error}</p>}
          <AnimatePresence mode="wait">
            <motion.div
              key={room.state}
              className={`stage-panel cooperative-stage cooperative-stage--${room.state.toLowerCase().replaceAll("_", "-")}`}
              aria-live="polite"
              initial={reducedMotion ? false : { opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              exit={reducedMotion ? undefined : { opacity: 0, y: -8 }}
            >
              {room.state === "STORY_INTRO" && (
                <>
                  <Dialogue speaker="Moss, the lantern keeper">“The lantern has two wicks. Perhaps it needs two ways of seeing.”</Dialogue>
                  <div className="private-clue">
                    <i aria-hidden="true">{role === "adolescent" ? "☾" : "⌂"}</i>
                    <div><span>Private clue · {role} view</span>
                    <p>{role === "adolescent"
                      ? "Moss is worried that another failed attempt will feel unbearable. Its ears lower whenever the lantern is mentioned."
                      : "Moss tried a spark stone, a firefly jar, and a careful wick adjustment. Each method failed before Moss withdrew."}</p></div>
                  </div>
                  <div className="stage-footer">
                    <span className="gentle-note">Both participants enter when ready.</span>
                    <button className="primary-button" disabled={busy || ownStatus?.hasSubmitted} onClick={() => void actions.begin()}>
                      {ownStatus?.hasSubmitted ? "Ready · waiting at the path" : "Walk into the clearing"}
                    </button>
                  </div>
                </>
              )}

              {room.state === "EMOTION_RECOGNITION" && (
                <>
                  <Dialogue speaker={role === "adolescent" ? "Your perspective" : "What you notice"} tone="guide">
                    {role === "adolescent"
                      ? "Choose one feeling that fits Moss’s words, and one kind of support that might help."
                      : "From the repeated attempts you observed, choose a possible feeling and a low-pressure kind of support."}
                  </Dialogue>
                  {ownStatus?.hasSubmitted ? <WaitingLeaf partner={partner} /> : (
                    <>
                      <div className="choice-columns" role="group" aria-label="Your private perspective">
                        <div className="choice-grove choice-grove--feeling"><h3><span aria-hidden="true">◒</span> Notice a feeling</h3>{EMOTIONS.map((item) => <ChoiceButton key={item.id} title={item.label} kind="emotion" icon="◌" selected={emotion === item.id} onClick={() => setEmotion(item.id)} />)}</div>
                        <div className="choice-grove choice-grove--support"><h3><span aria-hidden="true">❧</span> Offer support</h3>{SUPPORT_NEEDS.map((item) => <ChoiceButton key={item.id} title={item.label} kind="support" icon="◇" selected={support === item.id} onClick={() => setSupport(item.id)} />)}</div>
                      </div>
                      <div className="stage-footer"><span className="gentle-note">Your choices stay private for now.</span><button className="primary-button" disabled={busy || !emotion || !support} onClick={() => void actions.submitEmotion(emotion, support)}>Set down your lantern</button></div>
                    </>
                  )}
                </>
              )}

              {(room.state === "INDIVIDUAL_RESPONSE" || room.state === "WAITING_FOR_PARTNER") && (
                <>
                  <Dialogue speaker="A response of your own" tone="guide">
                    {role === "adolescent" ? "What might help Moss feel understood without taking away its choices?" : "How could you respond supportively after noticing how hard Moss tried?"}
                  </Dialogue>
                  {ownStatus?.hasSubmitted ? <WaitingLeaf partner={partner} /> : (
                    <>
                      <div className="response-list">
                        {INDIVIDUAL_RESPONSES[role].map((item) => <ChoiceButton key={item.id} title={item.label} icon={role === "adolescent" ? "☾" : "⌂"} selected={individual === item.id} onClick={() => setIndividual(item.id)} />)}
                      </div>
                      <div className="stage-footer"><span className="gentle-note">Only a safe summary is shared in the next step.</span><button className="primary-button" disabled={busy || !individual} onClick={() => void actions.submitIndividual(individual)}>Submit private choice</button></div>
                    </>
                  )}
                </>
              )}

              {room.state === "COOPERATIVE_TASK" && (
                <>
                  <Dialogue speaker="Two perspectives meet" tone="shared">You noticed different parts of the same moment. Build one response together.</Dialogue>
                  <SharedLanternRitual
                    role={role}
                    ownLit={Boolean(ownStatus?.hasSubmitted)}
                    partnerLit={Boolean(partner?.hasSubmitted)}
                  />
                  <div className="perspective-reveal">
                    <article><span>☾ Adolescent lens</span><p>Possible feeling: <strong>{friendly(room.revealedPerspective?.adolescent?.emotion)}</strong></p><p>Support need: {friendly(room.revealedPerspective?.adolescent?.supportNeed)}</p></article>
                    <article><span>⌂ Caregiver lens</span><p>{room.revealedPerspective?.caregiver?.observation}</p><p>Response tendency: <strong>{friendly(room.revealedPerspective?.caregiver?.responseStyle)}</strong></p></article>
                  </div>
                  {ownStatus?.hasSubmitted ? <WaitingLeaf partner={partner} message="Your fragments are set. The shared reply appears when both lanterns contribute." /> : (
                    <>
                      <p className="fragment-instruction">Choose one to three fragments. Both players must contribute; neither role leads automatically.</p>
                      <div className="fragment-grid">
                        {COOPERATIVE_FRAGMENTS.map((fragment) => (
                          <ChoiceButton
                            key={fragment.id}
                            title={fragment.text}
                            detail={fragment.tag}
                            kind="fragment"
                            selected={fragments.includes(fragment.id)}
                            onClick={() => setFragments((current) => current.includes(fragment.id)
                              ? current.filter((id) => id !== fragment.id)
                              : current.length < 3 ? [...current, fragment.id] : current)}
                          />
                        ))}
                      </div>
                      <div className={`shared-reply-preview ${fragments.length ? "has-fragments" : ""}`}>
                        <span>Your light ribbon</span>
                        <div className="reply-thread" aria-hidden="true"><i /><i /><i /></div>
                        <p>{selectedSharedText || "Choose a few words and watch them gather around your wick…"}</p>
                      </div>
                      <div className="stage-footer"><span className="gentle-note">Contribution matters more than agreement.</span><button className="primary-button" disabled={busy || !fragments.length} onClick={() => void actions.submitCooperative(fragments)}>Offer these fragments</button></div>
                    </>
                  )}
                </>
              )}

              {room.state === "SKILL_FEEDBACK" && room.feedback && (
                <>
                  <SharedLanternRitual role={role} ownLit partnerLit complete />
                  <Dialogue speaker="The shared reply" tone="shared">
                    {COOPERATIVE_FRAGMENTS.filter((fragment) => room.cooperativeFragments.includes(fragment.id)).map((fragment) => fragment.text).join(" ")}
                  </Dialogue>
                  <section className="feedback-sheet feedback-validation">
                    <p className="eyebrow">DBT skill reflection · no score</p>
                    <h3>{room.feedback.title}</h3>
                    <p>{room.feedback.message}</p>
                    <ul>{room.feedback.strengths.map((strength) => <li key={strength}>{strength}</li>)}</ul>
                    <div className="feedback-distinction"><span>Next gentle step</span><p>{room.feedback.nextStep}</p></div>
                  </section>
                  <div className="stage-footer"><span className="gentle-note">Both players continue when ready.</span><button className="primary-button" disabled={busy || ownStatus?.hasSubmitted} onClick={() => void actions.acknowledgeFeedback()}>{ownStatus?.hasSubmitted ? "Ready · waiting for partner" : "Carry the light forward"}</button></div>
                </>
              )}

              {room.state === "TRANSFER_REFLECTION" && (
                <>
                  <Dialogue speaker="A new woodland moment" tone="shared">A small fox is upset because its friends finished a workshop task without waiting.</Dialogue>
                  <p className="narration">Choose the response that first makes space for the fox’s feeling. This is fictional; no personal example is needed.</p>
                  {ownStatus?.hasSubmitted ? <WaitingLeaf partner={partner} message="Your transfer choice is set. The lantern glows fully when both have practiced." /> : (
                    <>
                      <div className="response-list compact-responses">
                        {TRANSFER_RESPONSES.map((item) => <ChoiceButton key={item.id} title={item.text} kind="transfer" icon="↝" selected={transfer === item.id} onClick={() => setTransfer(item.id)} />)}
                      </div>
                      <div className="stage-footer"><span className="gentle-note">Every attempt is part of learning.</span><button className="primary-button" disabled={busy || !transfer} onClick={() => void actions.submitTransfer(transfer)}>Complete transfer practice</button></div>
                    </>
                  )}
                </>
              )}

              {room.state === "COMPLETED" && (
                <section className="completion-message">
                  <SharedLanternRitual role={role} ownLit partnerLit complete />
                  <span className="completion-lantern">✦</span><p className="eyebrow">Two lanterns · one shared path</p>
                  <h3>The clearing is bright again</h3>
                  <p>You both contributed. The goal was not identical answers; it was listening across two perspectives and building a response together.</p>
                  <div className="skill-sequence"><span>Notice</span><i>→</i><span>Name</span><i>→</i><span>Invite</span><i>→</i><span>Ask</span></div>
                  <button className="primary-button" onClick={onExit}>Return to the forest gate</button>
                </section>
              )}

              {room.state === "PAUSED" && (
                <section className="pause-message"><span>◌</span><h3>The forest is resting</h3><p>Either participant or the therapist can pause. Nothing is lost, and no reason is required.</p><button className="primary-button" onClick={() => void actions.resume()}>Resume when ready</button></section>
              )}

              {room.state === "TERMINATED" && (
                <section className="pause-message"><span>☾</span><h3>This session has ended</h3><p>The forest gate remains open for a new demo whenever you choose.</p><button className="primary-button" onClick={onExit}>Return to welcome</button></section>
              )}
            </motion.div>
          </AnimatePresence>
        </SceneChrome>
      </ForestScene>
    </main>
  );
}

function SharedLanternRitual({
  role,
  ownLit,
  partnerLit,
  complete = false,
}: {
  role: PlayerRole;
  ownLit: boolean;
  partnerLit: boolean;
  complete?: boolean;
}) {
  const partnerRole: PlayerRole = role === "adolescent" ? "caregiver" : "adolescent";
  const bothLit = complete || (ownLit && partnerLit);
  const status = bothLit
    ? "Both perspectives are woven into the shared light."
    : ownLit
      ? "Your wick is glowing. Your partner can contribute when ready."
      : partnerLit
        ? "Your partner’s wick is glowing. Your contribution is still needed."
        : "Two equal wicks are waiting for one contribution each.";

  return (
    <section className={`shared-lantern-ritual ${bothLit ? "is-complete" : ""}`} aria-label="Cooperative contribution status">
      <div className={`ritual-player ritual-player--own ${ownLit || complete ? "is-lit" : ""}`}>
        <span aria-hidden="true">{role === "adolescent" ? "☾" : "⌂"}</span>
        <div><strong>You</strong><small>{role}</small></div>
      </div>
      <div className="ritual-light" aria-hidden="true">
        <i className={`ritual-wick ritual-wick--left ${ownLit || complete ? "is-lit" : ""}`} />
        <i className={`ritual-wick ritual-wick--right ${partnerLit || complete ? "is-lit" : ""}`} />
        <span className="ritual-lantern">◇</span>
        <b />
      </div>
      <div className={`ritual-player ritual-player--partner ${partnerLit || complete ? "is-lit" : ""}`}>
        <span aria-hidden="true">{partnerRole === "adolescent" ? "☾" : "⌂"}</span>
        <div><strong>Partner</strong><small>{partnerRole}</small></div>
      </div>
      <p role="status">{status}</p>
    </section>
  );
}

function ParticipantMiniatures({ room }: { room: PublicRoomState }) {
  return <div className="participant-miniatures" aria-label="Participant connection status">{(["adolescent", "caregiver"] as const).map((role) => <span key={role} title={`${role}: ${room.participants[role]?.connected ? "connected" : "offline"}`} aria-label={`${role}: ${room.participants[role]?.connected ? "connected" : "offline"}`} className={room.participants[role]?.connected ? "is-online" : ""}>{role === "adolescent" ? "☾" : "⌂"}</span>)}</div>;
}

function WaitingLeaf({ partner, message }: { partner?: { connected: boolean; hasSubmitted: boolean }; message?: string }) {
  return (
    <div className="waiting-leaf">
      <span aria-hidden="true">❧</span>
      <div className="waiting-wick" aria-hidden="true"><i /><i /></div>
      <h3>Your choice is safely held</h3>
      <p>{message ?? (partner?.hasSubmitted ? "Your partner has also responded. The forest is opening the next path…" : "Waiting for the other lantern. There is no time limit.")}</p>
    </div>
  );
}

function friendly(value?: string): string {
  if (!value) return "not shared";
  return value.replaceAll("-", " ");
}
