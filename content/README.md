# content/

Clinical and user-facing content lives here as versioned files, never in code
(DEVELOPMENT_PROMPT §5, Plan §3.2). The API loads and validates **every** file in this
tree at startup and refuses to start if any file is invalid or has no registered schema
(`backend/app/content/loader.py`).

Every content file carries an approval block:

```yaml
approval: { status: draft, approved_by: null, approved_at: null }  # demo | draft | approved | retired
```

`approved` requires `approved_by` and `approved_at`. Content that is not `approved` may
only be used for demo/test families.

| Folder | Holds | Schema added in |
|---|---|---|
| `skills/taxonomy.yaml` | Skill taxonomy (Plan Appendix B) | Phase 0 (IDs), Phase 3 (names, handout refs) |
| `prompts/` | Versioned LLM prompts `{function}/{role}/{lang}/vN.md` | Phase 4 |
| `fallbacks/` | Static reviewed fallback content | Phase 4 |
| `diary/` | Diary Card templates (D17) | Phase 6 |
| `episodes/` | Joint-session episodes: `catalog.yaml` (planned worlds and levels) and `{id}/vN.yaml` scripts. So far only the demo stub and a draft placeholder (O1) | Phase 8 |
| `help/` | Safety help-screen text (O4) | Phase 2 |
| `consent/` | Consent documents (O5) | Phase 1 |
| `safety/` | Risk keyword lists, output rules | Phase 2 |
| `eval/` | Retrieval, golden and adversarial AI evaluation sets | Phase 3–4 |

Never put text copied from the DBT manual in this tree (D7).
