/**
 * Client-side route gate per role. This only chooses which UI to render; every API call is
 * authorised server-side (Plan §4.2). No session → start page; wrong role → own home;
 * participant without completed onboarding → onboarding (Plan §5.2, cannot be skipped).
 */
import type { ReactNode } from "react";
import { Navigate } from "react-router";
import { landingFor, useSession, useSessionControls, type Role } from "./session";

export function RoleGate({ role, children }: { role: Role; children: ReactNode }) {
  const { loading } = useSessionControls();
  const user = useSession();
  if (loading) return null;
  if (!user) return <Navigate to="/" replace />;
  if (user.role !== role) return <Navigate to={landingFor(user)} replace />;
  if (landingFor(user) === "/onboarding") return <Navigate to="/onboarding" replace />;
  return <>{children}</>;
}
