import { useEffect, useRef, useState } from "react";
import { io, type Socket } from "socket.io-client";
import type { SocketAck, TherapistSessionSummary } from "../../shared/types";

const DEMO_KEY = "lantern-demo";

export function TherapistDashboard({ onExit }: { onExit: () => void }) {
  const socketRef = useRef<Socket | null>(null);
  const [sessions, setSessions] = useState<TherapistSessionSummary[]>([]);
  const [error, setError] = useState("");
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    const socket = io();
    socketRef.current = socket;
    socket.on("connect", () => {
      setConnected(true);
      socket.emit("therapist:subscribe", { key: DEMO_KEY }, (ack: SocketAck<TherapistSessionSummary[]>) => {
        if (ack.ok && ack.data) setSessions(ack.data);
        else setError(ack.error ?? "Could not open the demo dashboard.");
      });
    });
    socket.on("disconnect", () => setConnected(false));
    socket.on("therapist:sessions", setSessions);
    return () => {
      socket.disconnect();
    };
  }, []);

  const control = (code: string, action: "pause" | "resume" | "terminate" | "reset") => {
    socketRef.current?.emit("therapist:control", { code, action, key: DEMO_KEY }, (ack: SocketAck<TherapistSessionSummary[]>) => {
      if (ack.ok && ack.data) setSessions(ack.data);
      else setError(ack.error ?? "The control could not be applied.");
    });
  };

  const active = sessions.filter((session) => !["COMPLETED", "TERMINATED"].includes(session.state)).length;
  const complete = sessions.filter((session) => session.state === "COMPLETED").length;

  return (
    <main className="utility-screen dashboard-screen">
      <div className="utility-backdrop" />
      <section className="utility-shell dashboard-shell">
        <header className="utility-header dashboard-header">
          <div><p className="eyebrow">Lantern Forest · clinician view</p><h1>Therapist Demo Dashboard</h1><p>Session orchestration and learning summaries · no risk prediction</p></div>
          <div className="dashboard-head-actions"><span className={`connection-pill ${connected ? "is-online" : ""}`}>{connected ? "Live demo feed" : "Reconnecting"}</span><button className="ghost-button" onClick={onExit}>← Forest gate</button></div>
        </header>

        <div className="simulation-warning"><strong>Simulated clinical authentication</strong><span>This prototype key is intentionally visible. Do not use with real patient data.</span></div>
        <div className="dashboard-metrics">
          <article><span>Active rooms</span><strong>{active}</strong><small>Level 2 assigned</small></article>
          <article><span>Completed today</span><strong>{complete}</strong><small>Demo memory only</small></article>
          <article><span>Skill focus</span><strong className="metric-text">Validation</strong><small>Emotion recognition</small></article>
        </div>

        <section className="sessions-section">
          <div className="section-heading"><div><p className="eyebrow">Live session board</p><h2>Assigned Lantern Forest rooms</h2></div><span>{sessions.length} total</span></div>
          {error && <p className="error-banner">{error}</p>}
          {!sessions.length ? (
            <div className="empty-sessions"><span>✦</span><h3>No rooms have been created yet</h3><p>Create a cooperative room from the adolescent or caregiver path. It will appear here in real time.</p></div>
          ) : (
            <div className="session-table" role="table" aria-label="Demo sessions">
              <div className="session-row session-row--head" role="row"><span>Room</span><span>Participants</span><span>Progress</span><span>Skill summary</span><span>Controls</span></div>
              {sessions.map((session) => (
                <div className="session-row" role="row" key={session.code}>
                  <div><strong>{session.code}</strong><small>{session.state.replaceAll("_", " ")}</small></div>
                  <div className="dashboard-participants">{(["adolescent", "caregiver"] as const).map((role) => <span key={role} className={session.participants[role]?.connected ? "is-present" : ""}>{role === "adolescent" ? "☾" : "⌂"}<i>{session.participants[role]?.confirmed ? "ready" : session.participants[role] ? "joined" : "open"}</i></span>)}</div>
                  <div><div className="mini-progress"><span style={{ width: `${session.completion}%` }} /></div><small>{session.completion}%</small></div>
                  <p>{session.skillSummary}</p>
                  <div className="table-actions">
                    {session.state === "PAUSED" ? <button onClick={() => control(session.code, "resume")}>Resume</button> : !["COMPLETED", "TERMINATED"].includes(session.state) && <button onClick={() => control(session.code, "pause")}>Pause</button>}
                    <button onClick={() => control(session.code, "reset")}>Reset</button>
                    <button className="danger-text" onClick={() => control(session.code, "terminate")}>End</button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
        <p className="dashboard-footnote">Research prototype only. This dashboard does not monitor crisis risk, diagnose participants, or replace therapist review.</p>
      </section>
    </main>
  );
}
