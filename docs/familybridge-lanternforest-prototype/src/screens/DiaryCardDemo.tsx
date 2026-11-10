import { useState } from "react";
import type { PlayerRole } from "../../shared/types";

type DiaryEntry = {
  emotion: string;
  intensity: number;
  skill: string;
  reflection: string;
  complete: boolean;
};

const examples: Record<PlayerRole, DiaryEntry> = {
  adolescent: {
    emotion: "Uneasy",
    intensity: 4,
    skill: "Observe and describe",
    reflection: "Fictional example: I noticed the feeling before deciding what to do.",
    complete: true,
  },
  caregiver: {
    emotion: "Concerned",
    intensity: 5,
    skill: "Validation",
    reflection: "Fictional example: I paused before offering a solution.",
    complete: false,
  },
};

export function DiaryCardDemo({ onExit }: { onExit: () => void }) {
  const [role, setRole] = useState<PlayerRole>("adolescent");
  const [entries, setEntries] = useState(examples);
  const entry = entries[role];
  const update = <K extends keyof DiaryEntry>(key: K, value: DiaryEntry[K]) => {
    setEntries((current) => ({ ...current, [role]: { ...current[role], [key]: value } }));
  };

  return (
    <main className="utility-screen diary-screen">
      <div className="utility-backdrop" />
      <section className="utility-shell">
        <header className="utility-header">
          <div><p className="eyebrow">Private practice record</p><h1>Demo Diary Card</h1><p>Fictional example data only · saved nowhere</p></div>
          <button className="ghost-button" onClick={onExit}>← Forest gate</button>
        </header>
        <div className="privacy-band"><span>◉</span><p><strong>Separate by design</strong>The adolescent and caregiver cards are independent. Switching this research demo view does not represent shared access.</p></div>
        <div className="diary-layout">
          <nav className="diary-tabs" aria-label="Demo card role">
            {(["adolescent", "caregiver"] as const).map((item) => (
              <button key={item} className={role === item ? "is-active" : ""} onClick={() => setRole(item)}>
                <span>{item === "adolescent" ? "☾" : "⌂"}</span><strong>{item} card</strong><small>Private fictional entry</small>
              </button>
            ))}
          </nav>
          <form className="diary-form" onSubmit={(event) => event.preventDefault()}>
            <div className="form-row">
              <label><span>Current emotion</span><select value={entry.emotion} onChange={(event) => update("emotion", event.target.value)}><option>Calm</option><option>Uneasy</option><option>Concerned</option><option>Frustrated</option><option>Hopeful</option></select></label>
              <label><span>DBT skill practiced</span><select value={entry.skill} onChange={(event) => update("skill", event.target.value)}><option>Observe and describe</option><option>Validation</option><option>Check the facts</option><option>Wise Mind</option></select></label>
            </div>
            <label className="intensity-field"><span>Emotional intensity <strong>{entry.intensity} / 10</strong></span><input type="range" min="0" max="10" value={entry.intensity} onChange={(event) => update("intensity", Number(event.target.value))} /><div><small>Low</small><small>High</small></div></label>
            <label><span>Brief reflection</span><textarea rows={4} value={entry.reflection} onChange={(event) => update("reflection", event.target.value)} /></label>
            <label className="completion-check"><input type="checkbox" checked={entry.complete} onChange={(event) => update("complete", event.target.checked)} /><span><strong>Mark practice complete</strong><small>Missed entries are not treated as noncompliance.</small></span></label>
            <div className="diary-footer"><span>Not automatically shared with the other participant</span><button className="primary-button" onClick={onExit}>Done</button></div>
          </form>
        </div>
      </section>
    </main>
  );
}
