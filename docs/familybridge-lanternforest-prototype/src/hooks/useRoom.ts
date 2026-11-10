import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { io, type Socket } from "socket.io-client";
import type { PlayerRole, PublicRoomState, SocketAck } from "../../shared/types";

const ACTIVE_KEY = "familybridge-active-room";
const CLIENT_KEY = "familybridge-tab-id";

function getClientId(): string {
  const existing = sessionStorage.getItem(CLIENT_KEY);
  if (existing) return existing;
  const id = crypto.randomUUID();
  sessionStorage.setItem(CLIENT_KEY, id);
  return id;
}

type Identity = { code: string; role: PlayerRole; clientId: string };

export function useRoom() {
  const socketRef = useRef<Socket | null>(null);
  const [room, setRoom] = useState<PublicRoomState>();
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const clientId = useMemo(getClientId, []);

  useEffect(() => {
    const socket = io();
    socketRef.current = socket;
    const restore = () => {
      setConnected(true);
      const raw = sessionStorage.getItem(ACTIVE_KEY);
      if (!raw) return;
      const identity = JSON.parse(raw) as Identity;
      socket.emit("room:join", identity, (ack: SocketAck<PublicRoomState>) => {
        if (ack.ok && ack.data) setRoom(ack.data);
        else if (ack.error) setError(ack.error);
      });
    };
    socket.on("connect", restore);
    socket.on("disconnect", () => setConnected(false));
    socket.on("room:state", (state: PublicRoomState) => setRoom(state));
    return () => {
      socket.disconnect();
      socketRef.current = null;
    };
  }, []);

  const request = useCallback(async <T,>(event: string, payload: unknown): Promise<T | undefined> => {
    const socket = socketRef.current;
    if (!socket) return undefined;
    setBusy(true);
    setError("");
    return new Promise<T | undefined>((resolve) => {
      socket.emit(event, payload, (ack: SocketAck<T>) => {
        setBusy(false);
        if (!ack.ok) {
          setError(ack.error ?? "The forest path was interrupted.");
          resolve(undefined);
          return;
        }
        resolve(ack.data);
      });
    });
  }, []);

  const persist = (state: PublicRoomState, role: PlayerRole) => {
    const identity: Identity = { code: state.code, role, clientId };
    sessionStorage.setItem(ACTIVE_KEY, JSON.stringify(identity));
    setRoom(state);
  };

  const identity = room?.currentRole
    ? { code: room.code, role: room.currentRole, clientId }
    : undefined;

  return {
    room,
    connected,
    error,
    busy,
    clearError: () => setError(""),
    createRoom: async (role: PlayerRole) => {
      const state = await request<PublicRoomState>("room:create", { role, clientId });
      if (state) persist(state, role);
    },
    joinRoom: async (code: string, role: PlayerRole) => {
      const state = await request<PublicRoomState>("room:join", { code, role, clientId });
      if (state) persist(state, role);
    },
    confirm: () => identity && request("participant:confirm", identity),
    begin: () => identity && request("game:begin", identity),
    submitEmotion: (emotion: string, supportNeed: string) => identity && request("game:emotion", { ...identity, emotion, supportNeed }),
    submitIndividual: (responseId: string) => identity && request("game:individual", { ...identity, responseId }),
    submitCooperative: (fragmentIds: string[]) => identity && request("game:cooperative", { ...identity, fragmentIds }),
    acknowledgeFeedback: () => identity && request("game:feedback-ack", identity),
    submitTransfer: (responseId: string) => identity && request("game:transfer", { ...identity, responseId }),
    pause: () => identity && request("room:pause", identity),
    resume: () => identity && request("room:resume", identity),
    terminate: () => identity && request("room:terminate", identity),
    leaveLocal: () => {
      sessionStorage.removeItem(ACTIVE_KEY);
      setRoom(undefined);
      setError("");
    },
  };
}
