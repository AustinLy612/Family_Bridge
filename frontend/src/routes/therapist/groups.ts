/** The therapist's own groups, and which one a dashboard screen is showing. */
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router";
import { get } from "../../api/client";
import type { GroupSummary } from "../../api/types";

export function useGroupChoice() {
  const groups = useQuery({ queryKey: ["groups"], queryFn: () => get<GroupSummary[]>("/groups") });
  const [params, setParams] = useSearchParams();
  const list = groups.data ?? [];
  const wanted = params.get("group");
  const groupId = list.some((g) => g.id === wanted) ? wanted : (list[0]?.id ?? null);
  const setGroupId = (id: string) =>
    setParams(
      (p) => {
        p.set("group", id);
        return p;
      },
      { replace: true },
    );
  return { groups, list, groupId, setGroupId };
}
