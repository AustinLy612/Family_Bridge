/** Provenance kinds and the mapping from the backend `ContentSource` (§6.2, D6). */
export type Provenance = "ai" | "authored" | "general";

/** Backend `ContentSource` -> label; internal outputs ("none") get no label. */
export function provenanceOf(source: string): Provenance | null {
  switch (source) {
    case "ai_manual":
      return "ai";
    case "ai_general":
      return "general";
    case "authored":
      return "authored";
    default:
      return null;
  }
}
