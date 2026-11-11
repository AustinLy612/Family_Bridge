/**
 * Keeps language and accessibility preferences on the user's account (Phase 1 task 7).
 * - On sign-in: the account's saved language and prefs are applied.
 * - While signed in: changes made anywhere (language switch, settings panel) are saved.
 */
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { patch } from "../api/client";
import type { UserOut } from "../api/types";
import { isLanguage } from "../i18n";
import { DEFAULT_A11Y, useAccessibility, type A11ySettings } from "./accessibility";
import { useSessionControls } from "./session";

const KEYS = Object.keys(DEFAULT_A11Y) as (keyof A11ySettings)[];

function fromServer(prefs: Record<string, unknown> | undefined): Partial<A11ySettings> {
  if (!prefs) return {};
  const out: Partial<A11ySettings> = {};
  for (const k of KEYS) if (k in prefs) (out as Record<string, unknown>)[k] = prefs[k];
  return out;
}

export function ServerPrefsSync() {
  const { user, setUser } = useSessionControls();
  const { i18n } = useTranslation();
  const qc = useQueryClient();
  const { settings, update } = useAccessibility();
  const appliedFor = useRef<string | null>(null);
  const lastSaved = useRef<string>("");

  // Apply the account's preferences once per signed-in user.
  useEffect(() => {
    if (!user?.id) {
      appliedFor.current = null;
      return;
    }
    if (appliedFor.current === user.id) return;
    appliedFor.current = user.id;
    const prefs = fromServer(user.a11yPrefs);
    if (Object.keys(prefs).length) update(prefs);
    if (user.language && user.language !== i18n.language) void i18n.changeLanguage(user.language);
    lastSaved.current = JSON.stringify({
      a11y: { ...settings, ...prefs },
      lang: user.language,
    });
  }, [user, update, i18n, settings]);

  // Save changes while signed in.
  useEffect(() => {
    if (!user?.id || appliedFor.current !== user.id) return;
    const lang = isLanguage(i18n.language) ? i18n.language : undefined;
    const snapshot = JSON.stringify({ a11y: settings, lang });
    if (snapshot === lastSaved.current) return;
    const handle = window.setTimeout(() => {
      const languageChanged = lang !== undefined && lang !== user.language;
      lastSaved.current = snapshot;
      patch<UserOut>("/me", { a11y_prefs: settings, language: lang })
        .then((u) => {
          setUser(u);
          // Lesson text, skill names and next AI steps follow the saved language.
          if (languageChanged) void qc.invalidateQueries({ queryKey: ["learn"] });
        })
        .catch(() => {
          lastSaved.current = "";
        });
    }, 400);
    return () => window.clearTimeout(handle);
  }, [settings, i18n.language, user?.id, user?.language, setUser, qc]);

  return null;
}
