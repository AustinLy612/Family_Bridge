/** AppShell bound to the signed-in user, with server logout. */
import type { ReactNode } from "react";
import { useNavigate } from "react-router";
import { AppShell, type AppShellProps } from "../app/AppShell";
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
      onLogout={() => {
        void logout().finally(() => navigate("/", { replace: true }));
      }}
    />
  );
}
