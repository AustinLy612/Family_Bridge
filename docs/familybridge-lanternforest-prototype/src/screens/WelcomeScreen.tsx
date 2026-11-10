import { motion } from "framer-motion";
import type { PlayerRole } from "../../shared/types";
import { ForestScene } from "../components/ForestScene";

export function WelcomeScreen({
  reducedMotion,
  onSolo,
  onRole,
  onTherapist,
  onDiary,
}: {
  reducedMotion: boolean;
  onSolo: () => void;
  onRole: (role: PlayerRole) => void;
  onTherapist: () => void;
  onDiary: () => void;
}) {
  return (
    <main className="welcome-screen">
      <ForestScene lanternPower={42} keeperMood="hopeful" reducedMotion={reducedMotion}>
        <motion.section
          className="welcome-panel"
          initial={reducedMotion ? false : { opacity: 0, y: 22 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8 }}
        >
          <p className="brand-kicker"><span>✦</span> Enter Lantern Forest <span>✦</span></p>
          <h1><span>GenAI-DBT FamilyBridge</span> Lantern Forest</h1>
          <p className="welcome-subtitle">A fantasy-based cooperative DBT skills adventure</p>
          <p className="world-intro">A quiet woodland where lanterns glow brighter when feelings are understood.</p>

          <div className="role-paths" aria-label="Choose a path">
            <button className="path-card path-card--adolescent" onClick={() => onRole("adolescent")}>
              <span className="path-icon">☾</span>
              <span><small>Cooperative path</small><strong>Play as Adolescent</strong></span>
              <i>→</i>
            </button>
            <button className="path-card path-card--caregiver" onClick={() => onRole("caregiver")}>
              <span className="path-icon">⌂</span>
              <span><small>Cooperative path</small><strong>Play as Caregiver</strong></span>
              <i>→</i>
            </button>
          </div>

          <div className="welcome-secondary">
            <button className="primary-button" onClick={onSolo}>Start solo practice <span>Level 1</span></button>
            <button className="text-button" onClick={onTherapist}>Therapist demo dashboard</button>
            <button className="text-button" onClick={onDiary}>View demo Diary Cards</button>
          </div>
        </motion.section>
      </ForestScene>
    </main>
  );
}
