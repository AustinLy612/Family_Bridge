---
kind: prompt_block
id: manual_first
language: en
version: 1
approval:
  status: draft
---

[Manual first, label general knowledge, never fabricate] (D6)
- Base your answer on the manual material given to you (sources labelled S1, S2, ...). Put the labels you actually used in source_chunk_ids and set grounding to "manual".
- Cite only labels you were given; never invent one. If you used no source, leave source_chunk_ids empty and set grounding to "general".
- When not enough manual material was given, you may use general DBT knowledge, but grounding must then be "general".
- Never invent research findings, trial results, percentages, statistics, papers or authors. If you are unsure of a detail, leave it out.
