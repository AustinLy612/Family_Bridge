import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactNode } from "react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { vi } from "vitest";
import { AccessibilityProvider, type A11ySettings } from "../app/accessibility";
import { buildRoutes } from "../app/routes";
import { ServerPrefsSync } from "../app/ServerPrefsSync";
import { SessionProvider, type SessionUser } from "../app/session";
import "../i18n";

function freshQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
}

/**
 * Render the app at `path`. `user` injects a static session (no network); pass `"server"` to
 * load the session from the (mocked) API like the real app does.
 */
export function renderApp(
  path: string | { pathname: string; state?: unknown },
  user: SessionUser | null | "server" = null,
  a11y?: Partial<A11ySettings>,
) {
  const router = createMemoryRouter(buildRoutes(), { initialEntries: [path] });
  const result = render(
    <QueryClientProvider client={freshQueryClient()}>
      <SessionProvider {...(user === "server" ? {} : { user })}>
        <AccessibilityProvider initial={a11y}>
          <ServerPrefsSync />
          <RouterProvider router={router} />
        </AccessibilityProvider>
      </SessionProvider>
    </QueryClientProvider>,
  );
  return { ...result, router };
}

export function Providers({ children }: { children: ReactNode }) {
  return <AccessibilityProvider>{children}</AccessibilityProvider>;
}

export const TEEN: SessionUser = {
  pseudonymId: "p-demo-1",
  displayAlias: "Demo Teen",
  role: "adolescent",
};
export const CAREGIVER: SessionUser = {
  pseudonymId: "p-demo-2",
  displayAlias: "Demo Carer",
  role: "caregiver",
};
export const THERAPIST: SessionUser = {
  pseudonymId: "p-demo-3",
  displayAlias: "Demo Therapist",
  role: "therapist",
};
export const ADMIN: SessionUser = {
  pseudonymId: "p-demo-4",
  displayAlias: "Demo Admin",
  role: "admin",
};

type Handler = (body: unknown, init: RequestInit) => { status?: number; body?: unknown };

/**
 * Minimal fetch mock: map "METHOD /path" (path after /api/v1, query string included) to a
 * handler. Unmatched requests fail the test loudly. Returns the list of calls made.
 */
export function mockApi(routes: Record<string, Handler | { status?: number; body?: unknown }>) {
  const calls: {
    key: string;
    body: unknown;
    headers: Record<string, string>;
  }[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = String(input).replace(/^\/api\/v1/, "");
    const key = `${(init.method ?? "GET").toUpperCase()} ${url}`;
    const body: unknown = init.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({
      key,
      body,
      headers: (init.headers ?? {}) as Record<string, string>,
    });
    const route = routes[key];
    if (!route) throw new Error(`unmocked API call: ${key}`);
    const out = typeof route === "function" ? route(body, init) : route;
    const status = out.status ?? 200;
    return new Response(status === 204 ? null : JSON.stringify(out.body ?? {}), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}
