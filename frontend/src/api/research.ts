/** Research export (admin) and recruitment denominators (therapist). Plan §5.10. */
import { ApiError, csrf, get, post } from "./client";

export interface ExportFile {
  path: string;
  scope: "shared" | "adolescent" | "caregiver";
  description: string;
  rows: number;
}

export interface Recruitment {
  id: string;
  period_start: string;
  period_end: string;
  screened: number;
  eligible: number;
  approached: number;
  consented: number;
  recorded_at: string;
  recorded_by: string | null;
}

export type RecruitmentIn = Omit<Recruitment, "id" | "recorded_at" | "recorded_by">;

export const research = {
  preview: (includeDemo: boolean) =>
    get<{ include_demo: boolean; files: ExportFile[] }>(
      `/admin/research-export?include_demo=${includeDemo ? "true" : "false"}`,
    ),
  /** POST the export request and return the zip; the server audits every download. */
  async download(includeDemo: boolean): Promise<{ blob: Blob; filename: string }> {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    const token = csrf();
    if (token) headers["X-CSRF-Token"] = token;
    let res: Response;
    try {
      res = await fetch("/api/v1/admin/research-export", {
        method: "POST",
        headers,
        credentials: "same-origin",
        body: JSON.stringify({ include_demo: includeDemo }),
      });
    } catch {
      throw new ApiError(0, "network");
    }
    if (!res.ok) throw new ApiError(res.status, res.status === 403 ? "forbidden" : "unknown");
    const disposition = res.headers.get("Content-Disposition") ?? "";
    const filename = /filename="([^"]+)"/.exec(disposition)?.[1] ?? "familybridge-research.zip";
    return { blob: await res.blob(), filename };
  },
  recruitment: (groupId: string) => get<{ items: Recruitment[] }>(`/groups/${groupId}/recruitment`),
  addRecruitment: (groupId: string, body: RecruitmentIn) =>
    post<Recruitment>(`/groups/${groupId}/recruitment`, body),
};
