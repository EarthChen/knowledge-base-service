# Wiki Generation Architecture Improvement

**Status:** Implemented (2026-04-27)  
**Created:** 2026-04-27  
**Scope:** Backend task architecture + incremental generation + progress reporting

**Implementation notes:** Delivered as Phases A–C — `wiki/task_store.py` (`WikiTaskStore`), `WikiTaskRegistry` + `bootstrap` wiring, async `POST /api/v1/wiki/business/generate` (202 + `task_id`), `GET /api/v1/wiki/business/tasks/{task_id}`, repo-level `get_repo_wiki_freshness` + `generate_business_wiki(incremental=..., progress_callback=...)`, dashboard polling and `WikiShell` progress UI. Tests: `tests/wiki/test_task_store.py`, `test_business_wiki_background.py`, `test_repo_freshness.py`, `test_business_wiki_incremental.py`.

## Background

This spec addressed synchronous business-wiki generation, full-regeneration by default, and in-memory-only task tracking. Those issues were:

1. Long blocking HTTP requests (multi-repo generation can take minutes)
2. Wasted LLM tokens when only one repo changed
3. Task state lost on service restart
4. No progress visibility in dashboard

*Resolved in implementation (2026-04-27):* `POST /api/v1/wiki/business/generate` is asynchronous (**202** + `task_id`), progress is available via **`GET /api/v1/wiki/business/tasks/{task_id}`** (and persisted in **Redis** when configured), `incremental` enables repository-level skip, and the dashboard polls and shows progress. See the opening **Implementation notes** for module pointers.

## Design

### Module 1: Background Task + Redis Persistence

#### WikiTaskStore (`wiki/task_store.py`)

Redis Hash-backed task storage replacing in-memory `WikiTaskRegistry`.

```python
class WikiTaskStore:
    KEY_PREFIX = "kb:wiki_tasks:"
    DEFAULT_TTL = 1800  # 30 minutes

    def __init__(self, conn: redis.Redis) -> None: ...

    def put_task(self, task_id: str, record: dict) -> None:
        # HSET kb:wiki_tasks:{task_id} + EXPIRE
    
    def get_task(self, task_id: str) -> dict | None:
        # HGETALL kb:wiki_tasks:{task_id}
    
    def update_status(self, task_id: str, status: str, **extra) -> None:
        # HSET partial update
    
    def list_active(self) -> list[dict]:
        # SCAN kb:wiki_tasks:* for active tasks
```

#### API Change: `POST /api/v1/wiki/business/generate`

- Returns `202 Accepted` with `{task_id, status: "pending"}` immediately
- Background execution via `asyncio.create_task`
- Each completed repo updates task progress in Redis

#### WikiTaskRegistry Migration

`WikiTaskRegistry` delegates to `WikiTaskStore` instead of internal dict. Backward compatible for single-repo tasks.

### Module 2: Two-Level Incremental Generation

#### Level 1: Repository-level skip

```
for repo in all_repos:
    repo_last_indexed = MAX(indexed_at) from code nodes WHERE repository = repo
    wiki_last_generated = MAX(generated_at) from WikiPages WHERE repository = repo
    if repo_last_indexed > wiki_last_generated:
        changed_repos.append(repo)
    else:
        skipped_repos.append(repo)
```

New store method: `get_repo_wiki_freshness(business_id) -> dict[repo, {last_indexed, last_generated}]`

#### Level 2: Page-level incremental (for changed repos)

Reuse existing `generate_incremental(repo, AffectedPageSet)`:
- Build `AffectedPageSet` by comparing code node `indexed_at` vs WikiPage `generated_at`
- Falls back to full generation if incremental fails

#### Cross-repo references

- Only regenerate references for changed repos
- Domain overview pages only regenerated when new repos are added

#### New parameter

`generate_business_wiki(..., *, incremental: bool = True)` — when `False`, forces full regeneration.

### Module 3: Progress Reporting + Dashboard

#### Task progress structure

```json
{
  "task_id": "biz-wiki-abc123",
  "status": "running",
  "business_id": "my-project",
  "total_repos": 5,
  "completed_repos": 3,
  "skipped_repos": 1,
  "current_repo": "user-service",
  "progress_pct": 60,
  "started_at": "2026-04-27T05:30:00Z",
  "incremental": true,
  "partial_errors": []
}
```

#### Dashboard changes

- `useWikiRegenerate`: poll returns progress, display progress bar
- Show current repo name + completion percentage
- Show skipped repos count (no changes)
- Support incremental/full toggle

## File Changes

| File | Change |
|------|--------|
| `wiki/task_store.py` | NEW: Redis-backed task storage |
| `wiki/task_registry.py` | MODIFY: delegate to WikiTaskStore |
| `wiki/service.py` | MODIFY: incremental logic + progress callback |
| `api/routes/wiki_task_routes.py` | MODIFY: background task for business generate |
| `store/wiki_page_store.py` | ADD: `get_repo_wiki_freshness()` query |
| `dashboard/src/hooks/useWikiRegenerate.ts` | MODIFY: progress display |
| `dashboard/src/i18n/{en,zh,types}.ts` | ADD: progress i18n keys |

## Testing

- WikiTaskStore: unit tests with mocked Redis connection
- Incremental detection: test with varied `indexed_at` / `generated_at` timestamps
- Background task: test task_id returned, status polling
- Frontend: test progress bar rendering with mock task data

## Risks

- Redis SCAN for `list_active()` may be slow with many concurrent tasks — mitigated by TTL (tasks expire)
- Incremental may miss edge cases (e.g., deleted modules) — fallback to full regen on error
- Background tasks need proper error handling to avoid zombie tasks
