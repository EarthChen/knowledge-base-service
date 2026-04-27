# Agent notes (knowledge-base-service)

## Wiki compilation snapshot

After wiki pages are persisted, a compilation snapshot is written to the graph as `WikiPage` nodes:

- **Single (below layer threshold):** `wiki_snapshot.md` (`page_type`: `index`)
- **Layered (at/above threshold):** `wiki_snapshot.md` (index) plus `wiki_snapshot_modules/{module}.md` for each module slice

Read these paths from the graph (or exports that mirror them) for a full-map view of indexed wiki content. Tooling may also expose the same via snapshot APIs.

## Feedback regeneration token multipliers

`feedback_regen_token_multiplier` and `feedback_regen_batch_token_multiplier` (see `config.WikiConfig`) are **logged** when feedback triggers regeneration, but are **not yet applied** to `WikiService.generate()` or internal composer code/token budgets. Treat them as forward-looking / observability until that wiring exists.
