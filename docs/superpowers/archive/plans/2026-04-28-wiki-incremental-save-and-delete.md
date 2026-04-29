# Wiki Incremental Save & Delete Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add incremental page persistence during wiki generation, single page soft-delete with version snapshots, and full-regeneration cleanup with hard-delete.

**Architecture:** Three features layered bottom-up: Store layer (Cypher queries) → Service layer (business logic) → API layer (HTTP endpoints) → Frontend (Dashboard UI). Each feature is independently deployable.

**Tech Stack:** Python 3.14, FastAPI, FalkorDB (Cypher), React + TypeScript (dashboard), lucide-react icons

**Spec:** `docs/superpowers/specs/2026-04-28-wiki-incremental-save-and-delete-design.md`

---

### Task 1: Add `incremental_persist` config fields to WikiConfig

**Files:**
- Modify: `config.py:173-252` (WikiConfig class)

- [ ] **Step 1: Add config fields**

In `config.py`, inside class `WikiConfig(BaseModel)` (around line 252, after existing fields), add:

```python
    # Incremental persist: save pages in batches during composition
    incremental_persist_enabled: bool = True
    incremental_persist_batch_size: int = 10
```

- [ ] **Step 2: Verify config loads**

Run: `cd knowledge-base-service && uv run python -c "from config import get_settings; s = get_settings(); print(s.wiki.incremental_persist_enabled, s.wiki.incremental_persist_batch_size)"`
Expected: `True 10`

- [ ] **Step 3: Commit**

```bash
git add config.py
git commit -m "feat(wiki): add incremental_persist config fields"
```

---

### Task 2: Add `on_page_composed` callback to `_compose_all_pages`

**Files:**
- Modify: `wiki/service.py:1375-1397` (`_compose_all_pages` signature and leaf/parent loops)

- [ ] **Step 1: Update `_compose_all_pages` signature**

In `wiki/service.py`, modify the `_compose_all_pages` method signature (line 1375):

```python
    async def _compose_all_pages(
        self,
        repository: str,
        structure: WikiStructure,
        config: WikiConfig,
        composer: WikiComposer,
        importance_tiers: dict[str, ImportanceTier] | None = None,
        llm_provider: str | None = None,
        *,
        community_markdown: str = "",
        token_budget_multiplier: float = 1.0,
        progress_callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        on_page_composed: Callable[[WikiPage], Awaitable[None]] | None = None,
    ) -> tuple[list[WikiPage], bool]:
```

- [ ] **Step 2: Call the callback after each leaf page is collected**

After the `leaf_results` loop (around line 1504-1513), add callback invocation:

Replace:
```python
        leaf_results = await asyncio.gather(*(compose_leaf(n) for n in leaves))
        for page in leaf_results:
            if page is not None:
                pages.append(page)
                uid = getattr(page, "_source_entity_uid", "")
                struct_path = getattr(page, "_structure_path", page.path)
                _sum = _extract_summary(page, entity_uid=uid)
                summary_index[struct_path] = _sum
                if page.path != struct_path:
                    summary_index[page.path] = _sum
```

With:
```python
        leaf_results = await asyncio.gather(*(compose_leaf(n) for n in leaves))
        for page in leaf_results:
            if page is not None:
                pages.append(page)
                uid = getattr(page, "_source_entity_uid", "")
                struct_path = getattr(page, "_structure_path", page.path)
                _sum = _extract_summary(page, entity_uid=uid)
                summary_index[struct_path] = _sum
                if page.path != struct_path:
                    summary_index[page.path] = _sum
                if on_page_composed is not None:
                    try:
                        await on_page_composed(page)
                    except Exception:
                        log.warning("on_page_composed_callback_failed", path=page.path, exc_info=True)
```

- [ ] **Step 3: Call the callback after each parent page**

Inside the parent loop (after `pages.append(page)` for each parent page, around the code block near line 1550-1600), add the same callback pattern after every `pages.append(page)`:

Find each occurrence of `pages.append(page)` in the parent loop and add after it:
```python
                if on_page_composed is not None:
                    try:
                        await on_page_composed(page)
                    except Exception:
                        log.warning("on_page_composed_callback_failed", path=page.path, exc_info=True)
```

There are multiple `pages.append(page)` in the parent loop (repo_overview, normal parent, delegated parent). Add callback after each.

- [ ] **Step 4: Commit**

```bash
git add wiki/service.py
git commit -m "feat(wiki): add on_page_composed callback to _compose_all_pages"
```

---

### Task 3: Use callback in `generate()` for incremental persist

**Files:**
- Modify: `wiki/service.py:396-461` (`generate` method)

- [ ] **Step 1: Modify `generate()` to use incremental persist**

Replace the current compose + persist block (lines 447-461):

```python
        pages, degraded = await self._compose_all_pages(
            repository,
            structure,
            config,
            composer,
            _importance_tiers,
            llm_provider,
            community_markdown=community_markdown,
            token_budget_multiplier=token_budget_multiplier,
            progress_callback=progress_callback,
        )
        await self._persist_pages_to_graph(
            repository, pages, language=language,
            skip_claim_tracking=(config.mode == "structure"),
        )
```

With:

```python
        skip_claim = config.mode == "structure"
        incremental_used = False

        if getattr(self._wiki_cfg, "incremental_persist_enabled", True):
            _persist_batch: list[WikiPage] = []
            _batch_size = int(getattr(self._wiki_cfg, "incremental_persist_batch_size", 10))

            async def _flush_persist_batch() -> None:
                if _persist_batch:
                    await self._persist_pages_to_graph(
                        repository, list(_persist_batch),
                        language=language, skip_claim_tracking=skip_claim,
                    )
                    _persist_batch.clear()

            async def _on_page(page: WikiPage) -> None:
                _persist_batch.append(page)
                if len(_persist_batch) >= _batch_size:
                    await _flush_persist_batch()

            pages, degraded = await self._compose_all_pages(
                repository, structure, config, composer,
                _importance_tiers, llm_provider,
                community_markdown=community_markdown,
                token_budget_multiplier=token_budget_multiplier,
                progress_callback=progress_callback,
                on_page_composed=_on_page,
            )
            await _flush_persist_batch()
            incremental_used = True
        else:
            pages, degraded = await self._compose_all_pages(
                repository, structure, config, composer,
                _importance_tiers, llm_provider,
                community_markdown=community_markdown,
                token_budget_multiplier=token_budget_multiplier,
                progress_callback=progress_callback,
            )

        if not incremental_used:
            await self._persist_pages_to_graph(
                repository, pages, language=language,
                skip_claim_tracking=skip_claim,
            )
```

- [ ] **Step 2: Run existing tests to verify no regression**

Run: `cd knowledge-base-service && uv run pytest tests/wiki/ -x -q --timeout=60 2>&1 | tail -20`
Expected: All existing tests pass.

- [ ] **Step 3: Commit**

```bash
git add wiki/service.py
git commit -m "feat(wiki): incremental persist during page composition"
```

---

### Task 4: Add `soft_delete_wiki_page` to WikiPageStoreMixin

**Files:**
- Modify: `store/wiki_page_store.py` (add method to WikiPageStoreMixin)

- [ ] **Step 1: Add the method**

At the end of `WikiPageStoreMixin` class in `store/wiki_page_store.py`, add:

```python
    async def soft_delete_wiki_page(self, page_uid: str) -> dict[str, Any]:
        """Soft-delete: snapshot current content to WikiPageVersion, mark deprecated, detach from tree."""
        ts = datetime.now(timezone.utc).isoformat()
        wv_uid = f"wpv:{page_uid}:{uuid.uuid4().hex[:16]}"

        cypher = (
            "MATCH (wp:WikiPage {uid: $uid}) "
            "WITH wp, coalesce(wp.version, 0) AS cur_v, coalesce(wp.content, '') AS old_c, "
            "coalesce(wp.content_source, '') AS old_src "
            "CREATE (wv:WikiPageVersion {"
            "uid: $wv_uid, wiki_page_uid: $uid, version: cur_v, content: old_c, "
            "edit_reason: 'soft_delete_snapshot', created_at: $ts, content_source: old_src}) "
            "SET wp.deprecated = true, wp.deleted_at = $ts, wp.content = '' "
            "WITH wp, cur_v "
            "OPTIONAL MATCH (parent)-[r:HAS_CHILD]->(wp) "
            "DELETE r "
            "RETURN cur_v AS snapshot_version"
        )
        result = await self._store.execute_query(
            cypher, {"uid": page_uid, "wv_uid": wv_uid, "ts": ts},
        )
        if not result.data:
            return {"ok": False, "error": "wiki_page_not_found", "page_uid": page_uid}
        row = result.data[0]
        return {
            "ok": True,
            "page_uid": page_uid,
            "snapshot_version": int(row.get("snapshot_version", 0)),
        }
```

- [ ] **Step 2: Commit**

```bash
git add store/wiki_page_store.py
git commit -m "feat(wiki): add soft_delete_wiki_page store method"
```

---

### Task 5: Add `delete_all_wiki_content_for_business` to WikiTreeStoreMixin

**Files:**
- Modify: `store/wiki_tree_store.py` (add method to WikiTreeStoreMixin)

- [ ] **Step 1: Add the method**

At the end of `WikiTreeStoreMixin` class in `store/wiki_tree_store.py`, add:

```python
    async def delete_all_wiki_content_for_business(
        self, business_id: str, repo_names: list[str] | None = None,
    ) -> dict[str, int]:
        """Hard-delete all WikiPages, WikiSections, and HAS_CHILD edges under a business WikiSpace.

        Also cleans up orphaned WikiPage nodes from given repos and stale WikiPageVersion nodes.
        """
        pages_deleted = 0
        sections_deleted = 0
        orphans_deleted = 0
        versions_deleted = 0

        q1 = (
            "MATCH (ws:WikiSpace {business_id: $bid})-[:HAS_CHILD*1..10]->(wp:WikiPage) "
            "DETACH DELETE wp "
            "RETURN count(wp) AS cnt"
        )
        r1 = await self._store.execute_query(q1, {"bid": business_id})
        if r1.data:
            pages_deleted = int(r1.data[0].get("cnt", 0))

        q2 = (
            "MATCH (ws:WikiSpace {business_id: $bid})-[:HAS_CHILD*1..10]->(sec:WikiSection) "
            "DETACH DELETE sec "
            "RETURN count(sec) AS cnt"
        )
        r2 = await self._store.execute_query(q2, {"bid": business_id})
        if r2.data:
            sections_deleted = int(r2.data[0].get("cnt", 0))

        if repo_names:
            q3 = (
                "MATCH (wp:WikiPage) WHERE wp.repository IN $repos "
                "DETACH DELETE wp "
                "RETURN count(wp) AS cnt"
            )
            r3 = await self._store.execute_query(q3, {"repos": repo_names})
            if r3.data:
                orphans_deleted = int(r3.data[0].get("cnt", 0))

        q4 = (
            "MATCH (wv:WikiPageVersion) "
            "WHERE NOT EXISTS { MATCH (wp:WikiPage {uid: wv.wiki_page_uid}) } "
            "DELETE wv "
            "RETURN count(wv) AS cnt"
        )
        r4 = await self._store.execute_query(q4)
        if r4.data:
            versions_deleted = int(r4.data[0].get("cnt", 0))

        return {
            "pages_deleted": pages_deleted,
            "sections_deleted": sections_deleted,
            "orphans_deleted": orphans_deleted,
            "versions_deleted": versions_deleted,
        }
```

- [ ] **Step 2: Commit**

```bash
git add store/wiki_tree_store.py
git commit -m "feat(wiki): add delete_all_wiki_content_for_business store method"
```

---

### Task 6: Add full-regen cleanup to `generate_business_wiki`

**Files:**
- Modify: `wiki/service.py:919-993` (`generate_business_wiki` method)

- [ ] **Step 1: Add cleanup step after repo listing**

In `wiki/service.py`, inside `generate_business_wiki`, after `all_modules` is populated and before the incremental freshness check (around line 963), add:

```python
        # Full regen: clean up all existing wiki content before regenerating
        if not incremental and self._wiki_store is not None:
            repo_names_for_cleanup = list(all_modules.keys())
            try:
                cleanup_result = await self._wiki_store.delete_all_wiki_content_for_business(
                    business_id, repo_names=repo_names_for_cleanup,
                )
                log.info(
                    "full_regen_cleanup_done",
                    business_id=business_id,
                    **cleanup_result,
                )
            except Exception:
                log.warning("full_regen_cleanup_failed", business_id=business_id, exc_info=True)
            if progress_callback:
                await progress_callback({
                    "completed_repos": 0,
                    "total_repos": len(all_modules),
                    "current_repo": "",
                    "phase": "cleanup_old_pages",
                })
```

Insert this block right before line 963 (`changed_repos: set[str] = set(all_modules.keys())`).

- [ ] **Step 2: Run existing tests**

Run: `cd knowledge-base-service && uv run pytest tests/wiki/test_business_wiki_incremental.py -x -q --timeout=60 2>&1 | tail -20`
Expected: Tests pass (or skip gracefully if mock store doesn't have the new method).

- [ ] **Step 3: Commit**

```bash
git add wiki/service.py
git commit -m "feat(wiki): cleanup old pages before full regeneration"
```

---

### Task 7: Add DELETE API endpoint for single page

**Files:**
- Modify: `api/routes/wiki_page_routes.py` (add DELETE endpoint using editor_router)

- [ ] **Step 1: Add the endpoint**

In `api/routes/wiki_page_routes.py`, after the existing `wiki_edit_page_content` endpoint (around line 949), add:

```python
@editor_router.delete("/wiki/pages/{page_uid:path}", response_model=None)
async def wiki_delete_page(
    request: Request,
    page_uid: str,
    business_id: str = Depends(get_effective_business_id),
) -> dict[str, Any]:
    """Soft-delete a wiki page: snapshot content, mark deprecated, detach from tree."""
    raw_store: Any = getattr(request.app.state, "wiki_store", None)
    if raw_store is None:
        raise KbServiceUnavailable("Wiki store unavailable")
    store = WikiStore(raw_store)
    decoded = unquote(page_uid)
    if not await store.assert_wiki_page_in_business(business_id, decoded):
        raise KbNotFound(f"Wiki page not found: {decoded}")
    result = await store.soft_delete_wiki_page(decoded)
    if not result.get("ok"):
        raise KbNotFound(result.get("error", "delete_failed"))
    return result
```

- [ ] **Step 2: Commit**

```bash
git add api/routes/wiki_page_routes.py
git commit -m "feat(wiki): add DELETE endpoint for single page soft-delete"
```

---

### Task 8: Add POST bulk-delete API endpoint

**Files:**
- Modify: `api/routes/wiki_task_routes.py` (add bulk-delete endpoint)
- Modify: `api/models/wiki_models.py` (add request body model)

- [ ] **Step 1: Add request body model**

In `api/models/wiki_models.py`, add:

```python
class WikiBulkDeleteBody(BaseModel):
    business_id: str = Field(..., min_length=1)
```

- [ ] **Step 2: Add the endpoint in wiki_task_routes.py**

In `api/routes/wiki_task_routes.py`, add import and endpoint:

Add to imports:
```python
from api.models.wiki_models import WikiBulkDeleteBody
from store.wiki_store import WikiStore
```

Add endpoint at the end of the file:
```python
@router.post(
    "/bulk-delete",
    response_model=None,
    dependencies=[Depends(require_role(Role.EDITOR))],
)
async def wiki_bulk_delete(
    body: WikiBulkDeleteBody,
    request: Request,
) -> dict[str, Any]:
    """Hard-delete all wiki pages, sections, and orphaned versions for a business."""
    raw_store: Any = getattr(request.app.state, "wiki_store", None)
    if raw_store is None:
        raise KbServiceUnavailable("Wiki store unavailable")
    store = WikiStore(raw_store)
    result = await store.delete_all_wiki_content_for_business(body.business_id)
    return {"ok": True, **result}
```

- [ ] **Step 3: Commit**

```bash
git add api/routes/wiki_task_routes.py api/models/wiki_models.py
git commit -m "feat(wiki): add POST /bulk-delete endpoint for business wiki cleanup"
```

---

### Task 9: Add delete button to WikiTreeNav (Frontend)

**Files:**
- Modify: `dashboard/src/components/wiki/WikiTreeNav.tsx`
- Modify: `dashboard/src/hooks/wikiTypes.ts`

- [ ] **Step 1: Add delete response type**

In `dashboard/src/hooks/wikiTypes.ts`, add at the end:

```typescript
export type WikiDeletePageResponse = {
  ok: boolean;
  page_uid: string;
  snapshot_version: number;
};
```

- [ ] **Step 2: Add delete icon and handler to WikiTreeNav**

In `dashboard/src/components/wiki/WikiTreeNav.tsx`:

1. Add `Trash2` to the lucide-react import
2. Add a delete icon button next to each WikiPage node (visible on hover)
3. Add confirmation dialog using `window.confirm`
4. On confirm, call `DELETE /api/v1/wiki/pages/{page_uid}?business_id={bid}`
5. On success, invalidate the wiki tree query to refresh

The tree node render function needs to include a small trash icon:

```tsx
{node.label === "WikiPage" && (
  <button
    className="ml-auto opacity-0 group-hover:opacity-100 p-0.5 rounded hover:bg-red-100 dark:hover:bg-red-900/30 text-muted-foreground hover:text-red-600 transition-opacity"
    title={t("wiki.deletePage")}
    onClick={(e) => {
      e.preventDefault();
      e.stopPropagation();
      handleDeletePage(node.uid, node.title);
    }}
  >
    <Trash2 className="h-3.5 w-3.5" />
  </button>
)}
```

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/components/wiki/WikiTreeNav.tsx dashboard/src/hooks/wikiTypes.ts
git commit -m "feat(wiki): add delete page button to wiki tree navigation"
```

---

### Task 10: Add "Delete All Pages" button to WikiLandingPage (Frontend)

**Files:**
- Modify: `dashboard/src/components/wiki/WikiLandingPage.tsx`

- [ ] **Step 1: Add bulk delete button and confirmation**

In `dashboard/src/components/wiki/WikiLandingPage.tsx`, add a danger zone section with a "Delete All Wiki Pages" button.

The button should:
1. Show a confirmation dialog that requires typing the business_id to confirm
2. Call `POST /api/v1/wiki/bulk-delete` with the business_id
3. On success, invalidate the wiki tree and show a success toast
4. On error, show error toast

- [ ] **Step 2: Commit**

```bash
git add dashboard/src/components/wiki/WikiLandingPage.tsx
git commit -m "feat(wiki): add 'Delete All Pages' button to wiki landing page"
```

---

### Task 11: Final integration test

- [ ] **Step 1: Run all wiki-related tests**

Run: `cd knowledge-base-service && uv run pytest tests/wiki/ tests/api/test_wiki_* -x -q --timeout=120 2>&1 | tail -30`
Expected: All tests pass.

- [ ] **Step 2: Verify frontend builds**

Run: `cd knowledge-base-service/dashboard && pnpm build 2>&1 | tail -20`
Expected: Build succeeds with no errors.

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "test: verify wiki incremental-save and delete integration"
```
