/** AppShell bound to the signed-in user, with server logout. */
import type { ReactNode } from "react";
import { useNavigate } from "react-router";
import { AppShell, type AppShellProps } from "../app/AppShell";
import { isParticipant } from "../app/nav";
import { useSessionControls } from "../app/session";

export function Page(
  props: Omit<AppShellProps, "role" | "alias" | "onLogout"> & {
    children: ReactNode;
  },
) {
  const { user, logout } = useSessionControls();
  const navigate = useNavigate();
  if (!user) return null;
  return (
    <AppShell
      {...props}
      role={user.role}
      alias={user.displayAlias}
      visibility={props.visibility ?? (isParticipant(user.role) ? { kind: "onlyYou" } : undefined)}
      onLogout={() => {
        void logout().finally(() => navigate("/", { replace: true }));
      }}
    />
  );
}
