import { useEffect, useState } from "react";
import type { PlayerRole } from "../shared/types";
import { SettingsMenu } from "./components/SettingsMenu";
import { CooperativeGame } from "./screens/CooperativeGame";
import { DiaryCardDemo } from "./screens/DiaryCardDemo";
import { SoloGame } from "./screens/SoloGame";
import { TherapistDashboard } from "./screens/TherapistDashboard";
import { WelcomeScreen } from "./screens/WelcomeScreen";

type Mode = "welcome" | "solo" | "cooperative" | "therapist" | "diary";

export default function App() {
  const [mode, setMode] = useState<Mode>(() => window.location.pathname === "/therapist" ? "therapist" : "welcome");
  const [role, setRole] = useState<PlayerRole>("adolescent");
  const [reducedMotion, setReducedMotion] = useState(() => localStorage.getItem("familybridge-reduced-motion") === "true" || window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  const [soundEnabled, setSoundEnabled] = useState(() => localStorage.getItem("familybridge-sound") === "true");
  const [enhancedContrast, setEnhancedContrast] = useState(() => localStorage.getItem("familybridge-enhanced-contrast") === "true");

  useEffect(() => {
    document.documentElement.classList.toggle("reduce-motion", reducedMotion);
    localStorage.setItem("familybridge-reduced-motion", String(reducedMotion));
  }, [reducedMotion]);
  useEffect(() => localStorage.setItem("familybridge-sound", String(soundEnabled)), [soundEnabled]);
  useEffect(() => {
    document.documentElement.classList.toggle("enhanced-contrast", enhancedContrast);
    localStorage.setItem("familybridge-enhanced-contrast", String(enhancedContrast));
  }, [enhancedContrast]);

  const go = (next: Mode) => {
    setMode(next);
    const path = next === "therapist" ? "/therapist" : "/";
    window.history.replaceState({}, "", path);
  };

  return (
    <div className="app-root">
      {mode === "welcome" && <WelcomeScreen reducedMotion={reducedMotion} onSolo={() => go("solo")} onRole={(nextRole) => { setRole(nextRole); go("cooperative"); }} onTherapist={() => go("therapist")} onDiary={() => go("diary")} />}
      {mode === "solo" && <SoloGame reducedMotion={reducedMotion} soundEnabled={soundEnabled} onExit={() => go("welcome")} />}
      {mode === "cooperative" && <CooperativeGame initialRole={role} reducedMotion={reducedMotion} soundEnabled={soundEnabled} onExit={() => go("welcome")} />}
      {mode === "therapist" && <TherapistDashboard onExit={() => go("welcome")} />}
      {mode === "diary" && <DiaryCardDemo onExit={() => go("welcome")} />}

      <SettingsMenu
        reducedMotion={reducedMotion}
        soundEnabled={soundEnabled}
        enhancedContrast={enhancedContrast}
        onMotionChange={setReducedMotion}
        onSoundChange={setSoundEnabled}
        onContrastChange={setEnhancedContrast}
      />
      <div className="prototype-ribbon">
        <strong>Research prototype</strong>
        <span>Not clinical treatment or a crisis-response system</span>
      </div>
    </div>
  );
}
