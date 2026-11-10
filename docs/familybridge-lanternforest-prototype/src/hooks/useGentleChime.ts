import { useCallback } from "react";

export function useGentleChime(enabled: boolean) {
  return useCallback(() => {
    if (!enabled) return;
    const AudioContextClass = window.AudioContext ?? (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AudioContextClass) return;
    const context = new AudioContextClass();
    const gain = context.createGain();
    const oscillator = context.createOscillator();
    oscillator.type = "sine";
    oscillator.frequency.setValueAtTime(523.25, context.currentTime);
    oscillator.frequency.exponentialRampToValueAtTime(659.25, context.currentTime + 0.35);
    gain.gain.setValueAtTime(0.0001, context.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.08, context.currentTime + 0.03);
    gain.gain.exponentialRampToValueAtTime(0.0001, context.currentTime + 0.7);
    oscillator.connect(gain).connect(context.destination);
    oscillator.start();
    oscillator.stop(context.currentTime + 0.72);
    oscillator.addEventListener("ended", () => void context.close());
  }, [enabled]);
}
