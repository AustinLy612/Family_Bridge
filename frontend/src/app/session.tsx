/**
 * Session context (Plan §5.1). The server session lives in an HTTP-only cookie; this context
 * mirrors `GET /api/v1/auth/session` and keeps the CSRF token for the API client.
 * Authorisation is ALWAYS enforced server-side; this context only picks which UI tree to show.
 *
 * Tests may inject a fixed `user` (static mode, no network).
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { get, post, setCsrfToken } from "../api/client";
import type { SessionOut, UserOut } from "../api/types";

export const ROLES = ["adolescent", "caregiver", "therapist", "admin"] as const;
export type Role = (typeof ROLES)[number];

export interface SessionUser {
  pseudonymId: string;
  displayAlias: string;
  role: Role;
  id?: string;
  username?: string;
  language?: "zh-CN" | "en";
  a11yPrefs?: Record<string, unknown>;
  /** Participants must finish onboarding consent first (Plan §5.2). Defaults to true. */
  onboarded?: boolean;
  isDemo?: boolean;
}

export function toSessionUser(u: UserOut): SessionUser {
  return {
    id: u.id,
    pseudonymId: u.pseudonym,
    username: u.username,
    displayAlias: u.display_alias,
    role: u.role,
    language: u.language,
    a11yPrefs: u.a11y_prefs,
    onboarded: u.onboarded,
    isDemo: u.is_demo,
  };
}

interface SessionControls {
  user: SessionUser | null;
  loading: boolean;
  /** Apply a fresh session response (after login/redeem). */
  apply: (s: SessionOut) => void;
  /** Update the cached user after a profile change. */
  setUser: (u: UserOut) => void;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
}

const SessionContext = createContext<SessionControls | null>(null);

export function SessionProvider({
  user: injected,
  children,
}: {
  /** Static mode for tests. Omit to load the real server session. */
  user?: SessionUser | null;
  children: ReactNode;
}) {
  const isStatic = injected !== undefined;
  const [user, setUserState] = useState<SessionUser | null>(injected ?? null);
  const [loading, setLoading] = useState(!isStatic);

  const apply = useCallback((s: SessionOut) => {
    setCsrfToken(s.csrf_token);
    setUserState(s.user ? toSessionUser(s.user) : null);
  }, []);

  const refresh = useCallback(async () => {
    if (isStatic) return;
    try {
      apply(await get<SessionOut>("/auth/session"));
    } catch {
      apply({ user: null, csrf_token: null });
    } finally {
      setLoading(false);
    }
  }, [apply, isStatic]);

  useEffect(() => {
    if (isStatic) return;
    let cancelled = false;
    get<SessionOut>("/auth/session")
      .then(
        (s) => !cancelled && apply(s),
        () => !cancelled && apply({ user: null, csrf_token: null }),
      )
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [apply, isStatic]);

  const logout = useCallback(async () => {
    try {
      if (!isStatic) await post("/auth/logout");
    } finally {
      apply({ user: null, csrf_token: null });
    }
  }, [apply, isStatic]);

  const setUser = useCallback((u: UserOut) => setUserState(toSessionUser(u)), []);

  const value = useMemo(
    () => ({ user, loading, apply, setUser, refresh, logout }),
    [user, loading, apply, setUser, refresh, logout],
  );
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionUser | null {
  return useContext(SessionContext)?.user ?? null;
}

export function useSessionControls(): SessionControls {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSessionControls must be used inside SessionProvider");
  return ctx;
}

export const ROLE_HOME: Record<Role, string> = {
  adolescent: "/teen",
  caregiver: "/caregiver",
  therapist: "/therapist",
  admin: "/admin",
};

export const isParticipantRole = (role: Role): boolean => role === "adolescent" || role === "caregiver";

/** Where a signed-in user belongs right now: the shared Portal once onboarding is done (D95). */
export function landingFor(user: SessionUser): string {
  if (isParticipantRole(user.role) && user.onboarded === false) return "/onboarding";
  return "/portal";
}
