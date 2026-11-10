/**
 * Usability instrumentation (Plan §5.10, §8.4): the browser reports client errors and the
 * outcome of scripted tasks to `POST /research/client-events`. Closed vocabulary only: an error
 * kind (js / api_5xx / network) and a screen key such as "adolescent:diary". Never a message,
 * URL, stack or anything the person typed. Reports are best effort; failures are ignored.
 */
import { useEffect, useRef } from "react";
import { ROLE_HOME } from "./session";
import { csrf, setTroubleReporter } from "../api/client";

export type ErrorKind = "js" | "api_5xx" | "network";
export type TaskId = "diary_entry" | "onboarding";

const ENDPOINT = "/api/v1/research/client-events";
const MAX_ERRORS_PER_PAGE = 20;
const DEDUPE_MS = 10_000;

let sentErrors = 0;
const lastSent = new Map<string, number>();

function send(body: Record<string, string>): void {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = csrf();
  if (!token) return; // signed out: the endpoint needs a session
  headers["X-CSRF-Token"] = token;
  void fetch(ENDPOINT, {
    method: "POST",
    headers,
    credentials: "same-origin",
    keepalive: true,
    body: JSON.stringify(body),
  }).catch(() => undefined);
}

/** "/teen/diary/abc" -> "adolescent:diary"; anything unknown -> "other". */
export function areaOf(pathname: string): string {
  const [, first = "", second = ""] = pathname.split("/");
  const role = Object.entries(ROLE_HOME).find(([, home]) => home === `/${first}`)?.[0];
  if (!role) return first === "onboarding" ? "onboarding" : "other";
  const screen = /^[a-z0-9-]{1,24}$/.test(second) ? second : "";
  return `${role}:${screen}`;
}

export function reportError(kind: ErrorKind): void {
  const area = areaOf(window.location.pathname);
  const key = `${kind}|${area}`;
  const now = Date.now();
  if (sentErrors >= MAX_ERRORS_PER_PAGE || now - (lastSent.get(key) ?? 0) < DEDUPE_MS) return;
  sentErrors += 1;
  lastSent.set(key, now);
  send({ type: "client.error", kind, area });
}

export function reportTask(task: TaskId, outcome: "success" | "abandoned"): void {
  send({ type: "task.outcome", task, outcome });
}

/** Install once at start-up: uncaught errors and failed API calls become `client.error`. */
export function installResearchReporting(): void {
  window.addEventListener("error", () => reportError("js"));
  window.addEventListener("unhandledrejection", () => reportError("js"));
  setTroubleReporter((status) => {
    if (status === 0) reportError("network");
    else if (status >= 500) reportError("api_5xx");
  });
}

// React StrictMode mounts, unmounts and remounts in development; a remount within the same tick
// cancels the pending "abandoned" report.
const pending = new Map<TaskId, ReturnType<typeof setTimeout>>();

/**
 * A scripted task on screen: reports "abandoned" if the person leaves (navigates away or closes
 * the tab) before `succeed()` is called. Returns `succeed`.
 */
export function useTaskOutcome(task: TaskId, active = true): () => void {
  const done = useRef(false);
  useEffect(() => {
    if (!active) return;
    clearTimeout(pending.get(task));
    pending.delete(task);
    done.current = false;
    const onHide = () => {
      if (!done.current) {
        done.current = true;
        reportTask(task, "abandoned");
      }
    };
    window.addEventListener("pagehide", onHide);
    return () => {
      window.removeEventListener("pagehide", onHide);
      if (done.current) return;
      pending.set(
        task,
        setTimeout(() => {
          pending.delete(task);
          if (!done.current) {
            done.current = true;
            reportTask(task, "abandoned");
          }
        }, 0),
      );
    };
  }, [task, active]);
  return () => {
    if (done.current) return;
    done.current = true;
    reportTask(task, "success");
  };
}
