import { createServer } from "node:http";
import path from "node:path";
import express from "express";
import { Server } from "socket.io";
import type { PlayerRole, SocketAck } from "../shared/types";
import { DEMO_THERAPIST_KEY, GameRoomStore } from "./GameRoomStore";

const PORT = Number(process.env.PORT ?? 3001);
const app = express();
const httpServer = createServer(app);
const io = new Server(httpServer, { cors: { origin: true, credentials: true } });
const store = new GameRoomStore();
const therapistSockets = new Set<string>();

app.use(express.json());
app.get("/api/health", (_request, response) => {
  response.json({ ok: true, service: "FamilyBridge Lantern Forest", state: "ready" });
});
app.get("/api/therapist/sessions", (request, response) => {
  try {
    response.json(store.listTherapistSessions(String(request.query.key ?? "")));
  } catch (error) {
    response.status(403).json({ error: messageOf(error) });
  }
});

const distPath = path.resolve(process.cwd(), "dist");
app.use(express.static(distPath));
app.get("*", (request, response, next) => {
  if (request.path.startsWith("/api") || request.path.startsWith("/socket.io")) return next();
  response.sendFile(path.join(distPath, "index.html"), (error) => {
    if (error) next();
  });
});

io.on("connection", (socket) => {
  const updateAll = (code: string) => {
    emitRoom(code);
    emitTherapistSessions();
  };

  socket.on("room:create", safeAck((payload: { role: PlayerRole; clientId: string }) => {
    const state = store.createRoom(payload.role, payload.clientId, socket.id);
    socket.data.identity = { code: state.code, role: payload.role, clientId: payload.clientId };
    socket.join(state.code);
    updateAll(state.code);
    return state;
  }));

  socket.on("room:join", safeAck((payload: { code: string; role: PlayerRole; clientId: string }) => {
    const state = store.joinRoom(payload.code, payload.role, payload.clientId, socket.id);
    socket.data.identity = { code: state.code, role: payload.role, clientId: payload.clientId };
    socket.join(state.code);
    updateAll(state.code);
    return state;
  }));

  socket.on("participant:confirm", safeAck((payload: ParticipantPayload) => {
    const state = store.confirmParticipation(payload.code, payload.role, payload.clientId);
    updateAll(state.code);
    return state;
  }));
  socket.on("game:begin", safeAck((payload: ParticipantPayload) => {
    const state = store.beginStory(payload.code, payload.role, payload.clientId);
    updateAll(state.code);
    return state;
  }));
  socket.on("game:emotion", safeAck((payload: ParticipantPayload & { emotion: string; supportNeed: string }) => {
    const state = store.submitEmotion(payload.code, payload.role, payload.clientId, payload.emotion, payload.supportNeed);
    updateAll(state.code);
    return state;
  }));
  socket.on("game:individual", safeAck((payload: ParticipantPayload & { responseId: string }) => {
    const state = store.submitIndividual(payload.code, payload.role, payload.clientId, payload.responseId);
    updateAll(state.code);
    return state;
  }));
  socket.on("game:cooperative", safeAck((payload: ParticipantPayload & { fragmentIds: string[] }) => {
    const state = store.submitCooperative(payload.code, payload.role, payload.clientId, payload.fragmentIds);
    updateAll(state.code);
    return state;
  }));
  socket.on("game:feedback-ack", safeAck((payload: ParticipantPayload) => {
    const state = store.acknowledgeFeedback(payload.code, payload.role, payload.clientId);
    updateAll(state.code);
    return state;
  }));
  socket.on("game:transfer", safeAck((payload: ParticipantPayload & { responseId: string }) => {
    const state = store.submitTransfer(payload.code, payload.role, payload.clientId, payload.responseId);
    updateAll(state.code);
    return state;
  }));
  socket.on("room:pause", safeAck((payload: ParticipantPayload) => {
    const state = store.pause(payload.code, payload.role, payload.clientId);
    updateAll(state.code);
    return state;
  }));
  socket.on("room:resume", safeAck((payload: ParticipantPayload) => {
    const state = store.resume(payload.code, payload.role, payload.clientId);
    updateAll(state.code);
    return state;
  }));
  socket.on("room:terminate", safeAck((payload: ParticipantPayload) => {
    const state = store.terminate(payload.code, payload.role, payload.clientId);
    updateAll(state.code);
    return state;
  }));

  socket.on("therapist:subscribe", safeAck((payload: { key: string }) => {
    const sessions = store.listTherapistSessions(payload.key);
    therapistSockets.add(socket.id);
    return sessions;
  }));
  socket.on("therapist:control", safeAck((payload: { code: string; action: "pause" | "resume" | "terminate" | "reset"; key: string }) => {
    store.therapistControl(payload.code, payload.action, payload.key);
    updateAll(payload.code.trim().toUpperCase());
    return store.listTherapistSessions(payload.key);
  }));

  socket.on("disconnect", () => {
    therapistSockets.delete(socket.id);
    const code = store.disconnect(socket.id);
    if (code) updateAll(code);
  });
});

function emitRoom(code: string): void {
  const room = io.sockets.adapter.rooms.get(code);
  if (!room) return;
  for (const socketId of room) {
    const client = io.sockets.sockets.get(socketId);
    const identity = client?.data.identity as ParticipantPayload | undefined;
    if (client && identity) client.emit("room:state", store.publicFor(code, identity.role, identity.clientId));
  }
}

function emitTherapistSessions(): void {
  const sessions = store.listTherapistSessions(DEMO_THERAPIST_KEY);
  for (const socketId of therapistSockets) io.to(socketId).emit("therapist:sessions", sessions);
}

interface ParticipantPayload {
  code: string;
  role: PlayerRole;
  clientId: string;
}

function safeAck<TPayload, TResult>(handler: (payload: TPayload) => TResult) {
  return (payload: TPayload, acknowledge?: (ack: SocketAck<TResult>) => void) => {
    try {
      const result = handler(payload);
      acknowledge?.({ ok: true, data: result });
    } catch (error) {
      acknowledge?.({ ok: false, error: messageOf(error) });
    }
  };
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : "Something interrupted the forest path.";
}

httpServer.listen(PORT, "0.0.0.0", () => {
  console.log(`FamilyBridge server ready on http://localhost:${PORT}`);
  console.log("Therapist authentication is simulated for this research prototype.");
});

export { app, httpServer, io, store };
