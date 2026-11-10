/**
 * Room connection (Plan §5.9 "WebSocket protocol"). The server owns the state; this hook sends
 * typed actions with idempotency ids, keeps unacknowledged actions and re-sends them after a
 * reconnect (the server drops duplicates), sends heartbeats, and reports round-trip time.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { roomUrl, type RoomAction, type RoomView } from "../../api/joint";

export type SafetyMessage = "stop" | "help" | "care_card";
export type Conn = "connecting" | "open" | "reconnecting" | "closed";

interface Pending {
  msg: Record<string, unknown>;
  resolve: (r: { ok: boolean; code?: string }) => void;
}

const PING_MS = 15_000;
const MAX_BACKOFF_MS = 10_000;

function newId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

export function useRoom(
  sessionId: string,
  { onSafety, location }: { onSafety: (a: SafetyMessage) => void; location: string | null },
) {
  const [view, setView] = useState<RoomView | null>(null);
  const [conn, setConn] = useState<Conn>("connecting");
  const [error, setError] = useState<string | null>(null);
  const ws = useRef<WebSocket | null>(null);
  const seq = useRef(0);
  const pending = useRef(new Map<string, Pending>());
  const safety = useRef(onSafety);
  const loc = useRef(location);
  useEffect(() => {
    safety.current = onSafety;
    loc.current = location;
  }, [onSafety, location]);

  useEffect(() => {
    let stopped = false;
    let attempt = 0;
    let ping: ReturnType<typeof setInterval> | undefined;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let pings = 0;

    const open = () => {
      const sock = new WebSocket(roomUrl(sessionId));
      ws.current = sock;
      sock.onopen = () => {
        attempt = 0;
        setConn("open");
        sock.send(JSON.stringify({ type: "join", location: loc.current }));
        for (const p of pending.current.values()) sock.send(JSON.stringify(p.msg));
        ping = setInterval(() => {
          pings += 1;
          sock.send(JSON.stringify({ type: "ping", t: performance.now(), n: pings }));
        }, PING_MS);
      };
      sock.onmessage = (ev) => {
        const m = JSON.parse(String(ev.data)) as Record<string, unknown>;
        switch (m.type) {
          case "state":
            if (typeof m.seq === "number" && m.seq >= seq.current) {
              seq.current = m.seq;
              setView(m.state as RoomView);
            }
            break;
          case "ack":
          case "error": {
            const p = typeof m.id === "string" ? pending.current.get(m.id) : undefined;
            if (p) {
              pending.current.delete(m.id as string);
              p.resolve(m.type === "ack" ? { ok: true } : { ok: false, code: String(m.code) });
            } else if (m.type === "error") {
              setError(String(m.code));
            }
            break;
          }
          case "safety":
            safety.current(m.action as SafetyMessage);
            break;
          case "pong":
            if (typeof m.t === "number" && pings % 4 === 0) {
              sock.send(JSON.stringify({ type: "rtt", ms: Math.round(performance.now() - m.t) }));
            }
            break;
        }
      };
      sock.onclose = (ev) => {
        clearInterval(ping);
        if (stopped) return;
        // 4401/4403: signed out, not allowed or not open; do not retry
        if (ev.code === 4401 || ev.code === 4403) {
          setConn("closed");
          return;
        }
        setConn("reconnecting");
        attempt += 1;
        retry = setTimeout(open, Math.min(MAX_BACKOFF_MS, 500 * 2 ** attempt));
      };
    };
    open();
    return () => {
      stopped = true;
      clearInterval(ping);
      clearTimeout(retry);
      ws.current?.close(1000);
    };
  }, [sessionId]);

  const send = useCallback((action: RoomAction) => {
    const id = newId();
    const msg = { ...action, id };
    return new Promise<{ ok: boolean; code?: string }>((resolve) => {
      pending.current.set(id, { msg, resolve });
      if (ws.current?.readyState === WebSocket.OPEN) ws.current.send(JSON.stringify(msg));
    });
  }, []);

  const join = useCallback((location: string) => {
    if (ws.current?.readyState === WebSocket.OPEN) {
      ws.current.send(JSON.stringify({ type: "join", location }));
    }
  }, []);

  return { view, conn, error, send, join };
}
