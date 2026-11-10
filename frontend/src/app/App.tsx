import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useMemo } from "react";
import { createBrowserRouter, RouterProvider } from "react-router";
import { AccessibilityProvider } from "./accessibility";
import { buildRoutes } from "./routes";
import { ServerPrefsSync } from "./ServerPrefsSync";
import { SessionProvider } from "./session";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

export function App() {
  const router = useMemo(() => createBrowserRouter(buildRoutes()), []);
  return (
    <QueryClientProvider client={queryClient}>
      <SessionProvider>
        <AccessibilityProvider>
          <ServerPrefsSync />
          <RouterProvider router={router} />
        </AccessibilityProvider>
      </SessionProvider>
    </QueryClientProvider>
  );
}
