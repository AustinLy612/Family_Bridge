/**
 * Lets the header Pause control pause a joint room (Plan §5.13: in joint sessions the Pause button
 * is always on screen and pauses the room for both). Outside a room, Pause stays local.
 */
import { useSyncExternalStore } from "react";

type Handler = (() => void) | null;

let handler: Handler = null;
const listeners = new Set<() => void>();

export function setRoomPause(next: Handler): void {
  handler = next;
  for (const l of listeners) l();
}

export function useRoomPause(): Handler {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => handler,
  );
}
