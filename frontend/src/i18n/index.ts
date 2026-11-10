/**
 * i18n setup (Plan §5.11; D3). All UI strings go through react-i18next.
 * Languages: Simplified Chinese (default) and English, switchable per user.
 * Phase 0 stores the choice locally; from Phase 1 it is saved on the user's account.
 */
import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import en from "./locales/en.json";
import zhCN from "./locales/zh-CN.json";

export const LANGUAGES = ["zh-CN", "en"] as const;
export type Language = (typeof LANGUAGES)[number];
export const DEFAULT_LANGUAGE: Language = "zh-CN";
const STORAGE_KEY = "fb.language";

export function isLanguage(v: unknown): v is Language {
  return typeof v === "string" && (LANGUAGES as readonly string[]).includes(v);
}

function initialLanguage(): Language {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (isLanguage(stored)) return stored;
  } catch {
    /* storage unavailable */
  }
  return DEFAULT_LANGUAGE;
}

export const resources = {
  en: { translation: en },
  "zh-CN": { translation: zhCN },
} as const;

void i18n.use(initReactI18next).init({
  resources,
  lng: initialLanguage(),
  fallbackLng: false, // a missing key must show up in tests, not silently fall back
  supportedLngs: LANGUAGES,
  interpolation: { escapeValue: false }, // React escapes
  returnNull: false,
});

function syncDocument(lng: string): void {
  document.documentElement.lang = lng;
}
syncDocument(i18n.language);
i18n.on("languageChanged", (lng) => {
  syncDocument(lng);
  try {
    localStorage.setItem(STORAGE_KEY, lng);
  } catch {
    /* ignore */
  }
});

export default i18n;
