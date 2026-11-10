/**
 * Therapist active time per family (§8.4; Plan §5.8). While a family's screen is visible, the
 * window has focus and the therapist has used mouse or keyboard in the last two minutes, seconds
 * are counted and reported about once a minute. Only the number of seconds is sent.
 */
import { useEffect } from "react";
import { therapist } from "../api/therapist";

const TICK = 5;
const FLUSH_AT = 60;
const IDLE_MS = 120_000;

export function useFocusTime(familyId: string | undefined): void {
  useEffect(() => {
    if (!familyId) return;
    let pending = 0;
    let lastInput = Date.now();
    const onInput = () => {
      lastInput = Date.now();
    };
    const events = ["pointerdown", "pointermove", "keydown", "scroll", "wheel"] as const;
    for (const e of events) window.addEventListener(e, onInput, { passive: true });
    const flush = () => {
      if (pending < 1) return;
      const seconds = Math.min(pending, 120);
      pending = 0;
      void therapist.reportTime(familyId, seconds).catch(() => undefined);
    };
    const timer = window.setInterval(() => {
      const active =
        document.visibilityState === "visible" && document.hasFocus() && Date.now() - lastInput < IDLE_MS;
      if (active) pending += TICK;
      if (pending >= FLUSH_AT) flush();
    }, TICK * 1000);
    const onHide = () => {
      if (document.visibilityState === "hidden") flush();
    };
    document.addEventListener("visibilitychange", onHide);
    return () => {
      window.clearInterval(timer);
      for (const e of events) window.removeEventListener(e, onInput);
      document.removeEventListener("visibilitychange", onHide);
      flush();
    };
  }, [familyId]);
}
