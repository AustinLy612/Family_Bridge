/**
 * Participant side of the safety flow (Plan §5.7). Features that send free text (lessons,
 * diary, joint sessions) pass the server's `safety` action here:
 * - "stop": the activity has been stopped; go to the help screen with the stop notice;
 * - "help": go to the help screen (e.g. urge threshold after a diary entry is saved);
 * - "care_card": stay, and show the gentle care-team card;
 * - "none": nothing.
 * The reason for a stop is never shown to anyone else (D10).
 */
import { useQuery } from "@tanstack/react-query";
import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";
import { get } from "../api/client";
import type { HelpPageOut, SafetyAction } from "../api/types";
import { ROLE_HOME, useSession } from "./session";

export interface HelpLocationState {
  safety?: "stop" | "help";
}

export function helpPath(role: keyof typeof ROLE_HOME): string {
  return `${ROLE_HOME[role]}/help`;
}

export function useSafetyOutcome() {
  const navigate = useNavigate();
  const user = useSession();
  const [careCard, setCareCard] = useState(false);
  const handle = useCallback(
    (action: SafetyAction): boolean => {
      if (!user) return false;
      if (action === "stop" || action === "help") {
        const state: HelpLocationState = { safety: action };
        navigate(helpPath(user.role), { state });
        return true;
      }
      if (action === "care_card") setCareCard(true);
      return false;
    },
    [navigate, user],
  );
  return { handle, careCard, dismissCareCard: () => setCareCard(false) };
}

/** Static help text + site contacts in the UI language (public endpoint). */
export function useHelpPage() {
  const { i18n } = useTranslation();
  return useQuery({
    queryKey: ["help", i18n.language],
    queryFn: () => get<HelpPageOut>(`/help?language=${encodeURIComponent(i18n.language)}`),
    staleTime: 5 * 60_000,
  });
}
