# Wiki 增量保存与删除功能设计

> Created: 2026-04-28  
> Status: Draft

## 1. Background

当前 wiki 生成系统存在三个痛点：

1. **单仓库内页面全量保存**：`generate()` 方法先调用 `_compose_all_pages()` 生成所有页面，再统一调用 `_persist_pages_to_graph()` 保存。若生成中途崩溃，已生成的页面全部丢失。
2. **缺少删除页面功能**：Dashboard 没有删除 wiki 页面的入口，Store/API 层也不存在删除方法。
3. **全量重新生成不清除旧数据**：`generate_business_wiki(incremental=False)` 只是不跳过仓库，但使用 `MERGE`(upsert)，路径变更的旧页面成为孤儿节点，树结构持续膨胀。

## 2. Goals

- G1: 单仓库 wiki 生成过程中，每 N 页批量保存一次（persist callback 模式）
- G2: Dashboard 支持删除单个 wiki 页面（软删除 + 版本快照）
- G3: 全量重新生成（`incremental=False`）前硬删除所有 wiki 页面和树结构
- G4: 提供批量删除 API 端点，支持 Dashboard 中「删除所有页面」操作

## 3. Design

### 3.1 Feature 1: Incremental Save (Persist Callback)

**方案**: 给 `_compose_all_pages()` 添加 `persist_callback` 参数，在页面组装循环中每 N 页调用一次。

**修改文件**:
- `wiki/service.py`

**核心变更**:

```python
# In generate():
skip_claim = config.mode == "structure"

if self._wiki_cfg.incremental_persist_enabled:
    persist_batch: list[WikiPage] = []

    async def _incremental_persist(page: WikiPage) -> None:
        persist_batch.append(page)
        if len(persist_batch) >= self._wiki_cfg.incremental_persist_batch_size:
            await self._persist_pages_to_graph(
                repository, list(persist_batch),
                language=language, skip_claim_tracking=skip_claim,
            )
            persist_batch.clear()

    pages, degraded = await self._compose_all_pages(
        ..., on_page_composed=_incremental_persist,
    )
    # Flush remaining pages
    if persist_batch:
        await self._persist_pages_to_graph(
            repository, list(persist_batch),
            language=language, skip_claim_tracking=skip_claim,
        )
else:
    pages, degraded = await self._compose_all_pages(...)
    # IMPORTANT: Only do bulk persist when callback was NOT used
    await self._persist_pages_to_graph(
        repository, pages, language=language, skip_claim_tracking=skip_claim,
    )
```

> **CRITICAL**: 使用 callback 模式时不再调用最终的批量 `_persist_pages_to_graph`，避免重复写入。

**新增配置项** (WikiAppConfig):
- `incremental_persist_enabled: bool = True` — 功能开关，便于线上紧急关闭
- `incremental_persist_batch_size: int = 10` — 每批保存的页面数

**`_compose_all_pages()` 变更**:
- 新增 `on_page_composed: Callable[[WikiPage], Awaitable[None]] | None = None` 参数
- 在每个页面成功组装后调用 `await on_page_composed(page)`
- 仍然返回完整的 `pages` 列表（向后兼容）

**注意事项**:
- `_persist_pages_to_graph` 中的 supersession tracking 逻辑对重复调用幂等（使用 MERGE）
- SOURCE_ENTITY 边也在 `_persist_pages_to_graph` 中创建，分批调用安全
- tree linking (`_link_pages_to_tree`) 在所有页面保存完毕后执行，不受影响
- `skip_claim_tracking` 参数在 callback 闭包中正确传递

### 3.2 Feature 2: Delete Single Wiki Page (Soft Delete + Version Snapshot)

**流程**:
1. 创建 `WikiPageVersion` 快照（保存当前内容）
2. 设置 `wp.deprecated = true`, `wp.deleted_at = <timestamp>`
3. 从 HAS_CHILD 树中移除（删除 HAS_CHILD 边）
4. 保留节点和 SOURCE_ENTITY 边用于审计

**修改文件**:

#### Backend - Store Layer

**`store/wiki_page_store.py`** - 新增方法:

```python
async def soft_delete_wiki_page(self, page_uid: str) -> dict[str, Any]:
    """Soft-delete a wiki page: snapshot content, mark deprecated, detach from tree."""
```

Cypher 逻辑:
1. `MATCH (wp:WikiPage {uid: $uid})` 获取当前内容
2. `CREATE (wv:WikiPageVersion {...})` 保存快照
3. `SET wp.deprecated = true, wp.deleted_at = $ts, wp.content = ''`
4. `MATCH (parent)-[r:HAS_CHILD]->(wp) DELETE r` 移除树边

#### Backend - API Layer

**`api/routes/wiki_page_routes.py`** - 新增端点:

```
DELETE /api/v1/wiki/pages/{page_uid}
  - Requires: editor role
  - Query params: business_id (required)
  - Response: { ok: true, page_uid, snapshot_version }
```

#### Frontend - Dashboard

**`dashboard/src/hooks/wikiTypes.ts`** - 新增类型:

```typescript
export type WikiDeletePageResponse = {
  ok: boolean;
  page_uid: string;
  snapshot_version: number;
};
```

**`dashboard/src/components/wiki/WikiTreeNav.tsx`** - 新增:
- 在每个 WikiPage 节点旁添加垃圾桶图标（hover 显示）
- 点击后弹出确认对话框
- 确认后调用 DELETE API，刷新树

**`dashboard/src/components/wiki/WikiContent.tsx`** - 新增:
- 页面顶部工具栏添加「删除」按钮
- 同样带确认对话框

### 3.3 Feature 3: Full Regen Cleanup (Hard Delete)

**触发时机**: `generate_business_wiki(incremental=False)` 的开头。

**修改文件**:

#### Backend - Store Layer

**`store/wiki_tree_store.py`** - 新增方法:

```python
async def delete_all_wiki_content_for_business(self, business_id: str) -> dict[str, int]:
    """Hard-delete all WikiPages, WikiSections, and HAS_CHILD edges under a business WikiSpace."""
```

Cypher 逻辑（两步）:
```cypher
-- Step 1: Delete WikiPage nodes linked to business space
MATCH (ws:WikiSpace {business_id: $bid})-[:HAS_CHILD*1..10]->(wp:WikiPage)
DETACH DELETE wp
RETURN count(wp) AS pages_deleted

-- Step 2: Delete WikiSection nodes linked to business space
MATCH (ws:WikiSpace {business_id: $bid})-[:HAS_CHILD*1..10]->(ws2:WikiSection)
DETACH DELETE ws2
RETURN count(ws2) AS sections_deleted
```

另外，还需要删除属于该 business 所有 repo 的、但可能未链接到树的 WikiPage:
```cypher
-- Step 3: Cleanup orphan WikiPages from repos
MATCH (wp:WikiPage) WHERE wp.repository IN $repos
DETACH DELETE wp
RETURN count(wp) AS orphans_deleted
```

最后，清理因 WikiPage 删除而变成孤儿的 WikiPageVersion 节点:
```cypher
-- Step 4: Cleanup orphaned WikiPageVersion nodes
MATCH (wv:WikiPageVersion)
WHERE NOT EXISTS { MATCH (wp:WikiPage {uid: wv.wiki_page_uid}) }
DELETE wv
RETURN count(wv) AS versions_deleted
```

#### Backend - Service Layer

**`wiki/service.py`** - `generate_business_wiki()` 修改:

在域分类之前（约 line 986），当 `incremental=False` 时：
```python
if not incremental and self._wiki_store is not None:
    repo_names = [r["repository"] for r in repos]
    cleanup = await self._wiki_store.delete_all_wiki_content_for_business(business_id)
    log.info("full_regen_cleanup", business_id=business_id, **cleanup)
    if progress_callback:
        await progress_callback({
            "completed_repos": 0,
            "total_repos": total_repos,
            "phase": "cleanup_old_pages",
        })
```

#### Backend - API Layer (Bulk Delete)

**`api/routes/wiki_task_routes.py`** - 新增端点:

```
POST /api/v1/wiki/bulk-delete
  - Requires: editor role
  - Body: { business_id: "xxx" }
  - Response: { ok: true, pages_deleted, sections_deleted, versions_deleted }
```

> 注意: 使用 POST 而非 DELETE，避免与现有 `{page_uid:path}` 路由产生路径冲突。

#### Frontend

**`dashboard/src/components/wiki/WikiLandingPage.tsx`** - 新增:
- 在 wiki 管理区域添加「删除所有页面」按钮
- 需要二次确认（输入 business_id 确认）

## 4. Test Plan

- [ ] Unit test: `soft_delete_wiki_page` 创建版本快照并标记 deprecated
- [ ] Unit test: `delete_all_wiki_content_for_business` 清除所有节点和边
- [ ] Unit test: `_compose_all_pages` 的 `on_page_composed` callback 被正确调用
- [ ] Integration test: DELETE API 端点权限验证 + 功能验证
- [ ] Integration test: `generate_business_wiki(incremental=False)` 先清除后重新生成
- [ ] Frontend test: 删除确认对话框交互

## 5. Implementation Order

1. **Phase 1**: Store 层新增删除方法（`soft_delete_wiki_page`, `delete_all_wiki_content_for_business`）
2. **Phase 2**: Service 层：全量重新生成前清除 + 增量保存 callback
3. **Phase 3**: API 层：新增 DELETE 端点
4. **Phase 4**: Frontend：Dashboard 删除按钮 + 确认对话框
