# Wiki 智能过滤、主题聚合与并行优化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Wiki 从 "每个 module 一页 (~962)" 转变为 "按业务主题层次展开 (~40-80 页)"，同时修复过滤 bug 和提升并行度。

**Architecture:** 修复 importance_tiers 参数传递 bug → 跳过业务 wiki 中冗余的 per-repo 生成 → 集成已有的 TopicBasedStructurePlanner 到 LangGraph pipeline → 补全主题页的代码关联 → 提升并发参数。

**Tech Stack:** Python / FastAPI / LangGraph / FalkorDB / asyncio

**Spec:** `docs/superpowers/specs/2026-05-06-wiki-topic-filter-parallel-design.md`

---

## Phase 1: 快速见效 (U1 + U4 + U3a)

### Task 1: 连通 importance_tiers 到 WikiStructurePlanner (U1)

**Files:**
- Modify: `wiki/service.py:313-375` (`generate` method)
- Modify: `wiki/service.py:780-870` (`generate_stream_events` method)
- Test: `tests/wiki/test_service.py`

- [ ] **Step 1: Write failing test — importance_tiers 传入 planner**

```python
# tests/wiki/test_importance_tiers_planner.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

@pytest.mark.asyncio
async def test_generate_passes_importance_tiers_to_planner():
    """Verify that generate() computes importance_tiers BEFORE calling plan()
    and passes them as a keyword argument."""
    from wiki.service import WikiService

    mock_graph = AsyncMock()
    mock_graph.find_top_level_modules = AsyncMock(return_value=[])

    mock_planner = AsyncMock()
    mock_planner.plan = AsyncMock(return_value=MagicMock(root=MagicMock(children=[])))

    mock_wiki_cfg = MagicMock()
    mock_wiki_cfg.code_budget_enabled = True
    mock_wiki_cfg.importance_core_percentile = 80
    mock_wiki_cfg.importance_standard_percentile = 30

    mock_wiki_store = AsyncMock()
    mock_scorer = AsyncMock()
    mock_scorer.score_all = AsyncMock(return_value={"uid1": "core", "uid2": "skeleton"})

    service = WikiService.__new__(WikiService)
    service._graph = mock_graph
    service._planner = mock_planner
    service._wiki_cfg = mock_wiki_cfg
    service._wiki_store = mock_wiki_store
    service._community_service = None
    service._deferred_enrichment = None

    with patch("wiki.service.ImportanceScorer", return_value=mock_scorer):
        with patch.object(service, "_composer_for", return_value=MagicMock()):
            with patch.object(service, "_compose_all", new_callable=AsyncMock, return_value=[]):
                with patch.object(service, "_persist_pages_to_graph", new_callable=AsyncMock):
                    with patch.object(service, "_sync_graph_references_into_page_content", new_callable=AsyncMock):
                        with patch.object(service, "_run_compilation_snapshot", new_callable=AsyncMock):
                            with patch.object(service, "_ensure_repo", new_callable=AsyncMock):
                                with patch("wiki.service.parse_scope") as mock_parse:
                                    mock_parse.return_value = MagicMock(scope_type="repo", value=None)
                                    try:
                                        await service.generate("test-repo", "repo", "full", "json")
                                    except Exception:
                                        pass

    # Verify planner.plan was called with importance_tiers
    call_kwargs = mock_planner.plan.call_args
    assert call_kwargs is not None
    assert "importance_tiers" in (call_kwargs.kwargs or {}), \
        "planner.plan() must receive importance_tiers keyword argument"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_importance_tiers_planner.py -v`
Expected: FAIL — planner.plan() called without importance_tiers

- [ ] **Step 3: Fix generate() — move importance scoring before plan()**

In `wiki/service.py`, method `generate()` (~line 313):

```python
    async def generate(
        self,
        repository: str,
        scope_raw: str,
        mode: str,
        format: str,
        language: str = "en",
        llm_provider: str | None = None,
        token_budget_multiplier: float = 1.0,
        progress_callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        scope = parse_scope(scope_raw)
        config = self._config_for(mode, format, repository, language)
        await self._ensure_repo(repository)

        # --- Compute importance tiers BEFORE planning ---
        _importance_tiers: dict[str, ImportanceTier] = {}
        app_cfg = self._wiki_cfg
        if app_cfg.code_budget_enabled and self._wiki_store is not None:
            from wiki.importance_scorer import ImportanceScorer

            scorer = ImportanceScorer(
                self._wiki_store,
                core_percentile=app_cfg.importance_core_percentile,
                standard_percentile=app_cfg.importance_standard_percentile,
            )
            _importance_tiers = await scorer.score_all(repository)
            log.info(
                "importance_scoring_complete",
                repository=repository,
                entities=len(_importance_tiers),
            )

        # --- Plan with tiers so SKELETON modules are filtered ---
        structure = await self._planner.plan(
            repository, scope, importance_tiers=_importance_tiers or None
        )

        community_markdown = ""
        # ... rest of method unchanged ...
```

Key change: Move the `_importance_tiers` computation block **before** `self._planner.plan()`, and pass `importance_tiers=_importance_tiers or None` to `plan()`.

- [ ] **Step 4: Apply same fix to generate_stream_events()**

In `wiki/service.py`, method `generate_stream_events()` (~line 780): apply the identical reordering — compute `_importance_tiers` before `self._planner.plan()` and pass it.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_importance_tiers_planner.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add wiki/service.py tests/wiki/test_importance_tiers_planner.py
git commit -m "fix: pass importance_tiers to WikiStructurePlanner.plan() to enable SKELETON filtering"
```

---

### Task 2: 提升 compose_concurrency 默认值 (U4)

**Files:**
- Modify: `core/config.py:242` (`compose_concurrency` default)
- Test: Existing tests should pass

- [ ] **Step 1: Change default from 3 to 6**

In `core/config.py`, line 242:

```python
    #: Max concurrent wiki subtrees during compose (sibling ``walk`` tasks) and enrichment.
    compose_concurrency: int = Field(default=6, ge=1)
```

- [ ] **Step 2: Run existing tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/ -x -q --timeout=60 2>&1 | tail -20`
Expected: All tests pass (default change should not break any tests)

- [ ] **Step 3: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add core/config.py
git commit -m "perf: increase compose_concurrency default from 3 to 6"
```

---

### Task 3: 跳过业务 wiki 的 per-repo 生成 (U3a)

**Files:**
- Modify: `core/config.py` (add `business_wiki_skip_repo_pages` + `business_repo_concurrency`)
- Modify: `wiki/service.py:1179-1240` (per-repo loop in `generate_business_wiki`)
- Test: `tests/wiki/test_service_skip_repo.py`

- [ ] **Step 1: Add config flags**

In `core/config.py`, in `AppWikiFlags` class, after `compose_concurrency`:

```python
    #: Skip per-repo module-level page generation in business wiki.
    #: When True, only LangGraph pipeline topic pages are generated.
    business_wiki_skip_repo_pages: bool = Field(default=True)

    #: Max concurrent repo-level wiki generation (only used when skip_repo_pages=False).
    business_repo_concurrency: int = Field(default=3, ge=1)
```

- [ ] **Step 2: Write failing test**

```python
# tests/wiki/test_service_skip_repo.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

@pytest.mark.asyncio
async def test_business_wiki_skips_per_repo_when_flag_true():
    """When business_wiki_skip_repo_pages=True, generate_business_wiki
    should NOT call self.generate() for each repo."""
    from wiki.service import WikiService

    service = WikiService.__new__(WikiService)
    mock_cfg = MagicMock()
    mock_cfg.code_budget_enabled = False
    mock_cfg.business_wiki_skip_repo_pages = True
    mock_cfg.compose_concurrency = 3
    service._wiki_cfg = mock_cfg

    mock_wiki_store = AsyncMock()
    mock_wiki_store.list_indexed_repositories = AsyncMock(
        return_value=[{"repository": "repo-a"}]
    )
    service._wiki_store = mock_wiki_store

    mock_graph = AsyncMock()
    mock_graph.list_repository_modules = AsyncMock(return_value=[
        MagicMock(uid="m1", label="Module", properties={"name": "Foo"})
    ])
    service._graph = mock_graph

    service.generate = AsyncMock()

    with patch("wiki.service.run_langgraph_pipeline", new_callable=AsyncMock) as mock_pipeline:
        mock_pipeline.return_value = MagicMock(
            domain_mapping={}, domain_tree=[], pages=[],
            resolved_links={},
        )
        with patch.object(service, "_persist_pages_to_graph", new_callable=AsyncMock):
            with patch.object(service, "_persist_resolved_pipeline_wikilinks", new_callable=AsyncMock):
                with patch.object(service, "_resolve_llm_port", return_value=MagicMock()):
                    with patch("wiki.service.ModuleDependencyGraph"):
                        with patch("wiki.service.WikiTreeBuilder"):
                            with patch.object(service, "_link_pages_to_tree", new_callable=AsyncMock):
                                with patch.object(service, "_run_compilation_snapshot", new_callable=AsyncMock):
                                    try:
                                        await service.generate_business_wiki("default")
                                    except Exception:
                                        pass

    service.generate.assert_not_called()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_service_skip_repo.py -v`
Expected: FAIL — generate() is still called

- [ ] **Step 4: Modify generate_business_wiki to skip per-repo**

In `wiki/service.py`, `generate_business_wiki()`, replace the per-repo loop (~line 1179-1240):

```python
        # --- Per-repo wiki (optional) ---
        partial_errors: list[dict[str, str]] = []
        total_repos = len(all_modules)
        completed_repos = 0

        if not app_cfg.business_wiki_skip_repo_pages:
            log.info("per_repo_generation_starting", business_id=business_id, repo_count=len(all_modules))

            if app_cfg.business_repo_concurrency > 1 and len(changed_repos) > 1:
                repo_sem = asyncio.Semaphore(app_cfg.business_repo_concurrency)

                async def _gen_one_repo(repo_name: str) -> None:
                    nonlocal completed_repos
                    async with repo_sem:
                        log.info("repo_wiki_generate_start", repository=repo_name, mode=mode)
                        await self.generate(
                            repo_name, "repo", mode, "json", language,
                            llm_provider, token_budget_multiplier=token_budget_multiplier,
                        )
                        completed_repos += 1
                        log.info("repo_wiki_generate_done", repository=repo_name)

                tasks = []
                for repo_name in all_modules:
                    if repo_name not in changed_repos:
                        completed_repos += 1
                        continue
                    tasks.append(_gen_one_repo(repo_name))

                results = await asyncio.gather(*tasks, return_exceptions=True)
                for i, r in enumerate(results):
                    if isinstance(r, Exception):
                        log.warning("repo_wiki_generate_failed", error=str(r)[:200])
                        partial_errors.append({"repository": "unknown", "error": str(r)[:200]})
            else:
                for repo_name in all_modules:
                    if repo_name not in changed_repos:
                        completed_repos += 1
                        if progress_callback:
                            await progress_callback({
                                "completed_repos": completed_repos,
                                "total_repos": total_repos,
                                "current_repo": repo_name,
                                "phase": "generating_pages",
                                "skipped": True,
                            })
                        continue
                    try:
                        log.info("repo_wiki_generate_start", repository=repo_name, mode=mode)
                        await self.generate(
                            repo_name, "repo", mode, "json", language,
                            llm_provider, token_budget_multiplier=token_budget_multiplier,
                        )
                        log.info("repo_wiki_generate_done", repository=repo_name)
                    except Exception as exc:
                        log.warning("repo_wiki_generate_failed", repository=repo_name, error=str(exc)[:200])
                        partial_errors.append({"repository": repo_name, "error": str(exc)[:200]})
                    completed_repos += 1
                    if progress_callback:
                        await progress_callback({
                            "completed_repos": completed_repos,
                            "total_repos": total_repos,
                            "current_repo": repo_name,
                            "phase": "generating_pages",
                        })
        else:
            log.info(
                "per_repo_generation_skipped",
                business_id=business_id,
                reason="business_wiki_skip_repo_pages=True",
            )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_service_skip_repo.py -v`
Expected: PASS

- [ ] **Step 6: Run full test suite**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/ -x -q --timeout=60 2>&1 | tail -20`
Expected: All tests pass

- [ ] **Step 7: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add core/config.py wiki/service.py tests/wiki/test_service_skip_repo.py
git commit -m "feat: add business_wiki_skip_repo_pages flag to skip per-repo generation in business wiki"
```

---

## Phase 2: 核心变更 (U2 + U3b + U3c)

### Task 4: 新增 plan_topic_structure pipeline 节点 (U2)

**Files:**
- Modify: `wiki/pipeline_nodes.py` (add `plan_topic_structure_node`)
- Modify: `wiki/pipeline_graph.py` (wire new node into graph)
- Modify: `wiki/pipeline_state.py` (ensure `topic_structure` is used)
- Test: `tests/wiki/test_pipeline_topic_planner.py`

- [ ] **Step 1: Write failing test for plan_topic_structure_node**

```python
# tests/wiki/test_pipeline_topic_planner.py
import pytest
from unittest.mock import AsyncMock, MagicMock

@pytest.mark.asyncio
async def test_plan_topic_structure_node_populates_state():
    """plan_topic_structure_node should populate topic_structure in state."""
    from wiki.pipeline_nodes import plan_topic_structure_node

    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value='[{"title": "User Mgmt", "description": "User management", "modules": [["repo1", "UserService"]], "sub_topics": []}]')

    state = {
        "domain_mapping": {"user_domain": [("repo1", "UserService")]},
        "modules": {
            "repo1": [
                {"uid": "Module::UserService:0", "properties": {"name": "UserService", "business_summary": "Handles users"}}
            ]
        },
        "entity_roles": {"Module::UserService:0": "has_business_logic"},
    }
    config = {"configurable": {"llm": mock_llm}}

    result = await plan_topic_structure_node(state, config)
    assert "topic_structure" in result
    assert isinstance(result["topic_structure"], list)
    assert len(result["topic_structure"]) > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_pipeline_topic_planner.py -v`
Expected: FAIL — plan_topic_structure_node not defined

- [ ] **Step 3: Implement plan_topic_structure_node**

In `wiki/pipeline_nodes.py`, add after the existing imports:

```python
from wiki.topic_structure_planner import TopicBasedStructurePlanner
```

Add the node function:

```python
async def plan_topic_structure_node(
    state: dict[str, Any], config: RunnableConfig | None = None
) -> dict[str, Any]:
    """Plan topic-based wiki structure using LLM."""
    llm = (config or {}).get("configurable", {}).get("llm")
    if not llm:
        log.info("plan_topic_structure_skip", reason="no_llm")
        return {"topic_structure": None}

    domain_mapping = state.get("domain_mapping", {})
    if not domain_mapping:
        return {"topic_structure": None}

    modules = state.get("modules", {})
    entity_roles = state.get("entity_roles", {})

    module_metadata: dict[tuple[str, str], dict[str, Any]] = {}
    importance_tiers: dict[str, str] = {}

    for repo_name, mod_list in modules.items():
        for mod_dict in mod_list:
            props = mod_dict.get("properties", {})
            name = props.get("name", "")
            uid = mod_dict.get("uid", "")
            if not name:
                continue
            module_metadata[(repo_name, name)] = {
                "summary": props.get("business_summary", "") or props.get("docstring", ""),
                "methods": props.get("methods", []),
                "calls": props.get("calls", []),
            }
            role = str(entity_roles.get(uid, "supporting"))
            if role == "framework_noise":
                importance_tiers[name] = "skeleton"
            elif role in ("has_business_logic", "entry_point"):
                importance_tiers[name] = "core"
            elif role == "supporting":
                importance_tiers[name] = "standard"
            else:
                importance_tiers[name] = "standard"

    planner = TopicBasedStructurePlanner(llm)
    topic_pages = await planner.plan(
        domain_mapping, module_metadata, importance_tiers
    )

    topic_dicts = [
        {
            "title": tp.title,
            "description": tp.description,
            "covered_modules": tp.covered_modules,
            "sub_topics": [
                {
                    "title": st.title,
                    "description": st.description,
                    "covered_modules": st.covered_modules,
                }
                for st in tp.sub_topics
            ],
        }
        for tp in topic_pages
    ]

    log.info("topic_structure_planned", topic_count=len(topic_dicts))
    return {"topic_structure": topic_dicts}
```

- [ ] **Step 4: Wire node into pipeline graph**

In `wiki/pipeline_graph.py`, add import:

```python
from wiki.pipeline_nodes import (
    ...,
    plan_topic_structure_node,
)
```

In `build_wiki_pipeline()`, add node and replace the edge from `set_review_status → compose_leaf_pages`:

```python
    graph.add_node("plan_topic_structure", plan_topic_structure_node)

    # Replace: graph.add_edge("set_review_status", "compose_leaf_pages")
    graph.add_edge("set_review_status", "plan_topic_structure")
    graph.add_edge("plan_topic_structure", "compose_leaf_pages")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_pipeline_topic_planner.py -v`
Expected: PASS

- [ ] **Step 6: Run full test suite**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/ -x -q --timeout=60 2>&1 | tail -20`
Expected: All tests pass

- [ ] **Step 7: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add wiki/pipeline_nodes.py wiki/pipeline_graph.py tests/wiki/test_pipeline_topic_planner.py
git commit -m "feat: add plan_topic_structure node to LangGraph pipeline for topic-based wiki planning"
```

---

### Task 5: compose_leaf_pages_node 支持 topic_structure (U2 续)

**Files:**
- Modify: `wiki/pipeline_nodes.py:983-1028` (`compose_leaf_pages_node`)
- Test: `tests/wiki/test_pipeline_topic_compose.py`

- [ ] **Step 1: Write failing test**

```python
# tests/wiki/test_pipeline_topic_compose.py
import pytest
from unittest.mock import AsyncMock, MagicMock

@pytest.mark.asyncio
async def test_compose_leaf_pages_uses_topic_structure():
    """When topic_structure exists, compose_leaf_pages_node should
    generate pages based on topic structure, not raw leaf domains."""
    from wiki.pipeline_nodes import compose_leaf_pages_node

    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value='{"content": "# Test Page\\nContent here", "executive_summary": "Test summary"}')

    state = {
        "domain_tree": [{"name": "user_domain", "modules": ["UserService"], "children": []}],
        "topic_structure": [
            {
                "title": "User Management",
                "description": "Handles user registration and auth",
                "covered_modules": [("repo1", "UserService")],
                "sub_topics": [],
            }
        ],
        "entity_roles": {"Module::UserService:0": "has_business_logic"},
        "modules": {
            "repo1": [
                {
                    "uid": "Module::UserService:0",
                    "properties": {
                        "name": "UserService",
                        "business_summary": "Manages users",
                        "methods": ["register", "login"],
                        "calls": ["UserRepo.save"],
                    },
                }
            ]
        },
    }
    config = {"configurable": {"llm": mock_llm}}

    result = await compose_leaf_pages_node(state, config)
    pages = result.get("pages", [])
    assert len(pages) > 0
    assert any("User Management" in p.get("title", "") for p in pages)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_pipeline_topic_compose.py -v`
Expected: FAIL — compose_leaf_pages_node ignores topic_structure

- [ ] **Step 3: Modify compose_leaf_pages_node to use topic_structure**

In `wiki/pipeline_nodes.py`, at the start of `compose_leaf_pages_node`:

```python
async def compose_leaf_pages_node(
    state: dict[str, Any], config: RunnableConfig | None = None
) -> dict[str, Any]:
    """Phase 3: generate topic pages for each leaf domain.
    
    When topic_structure is available, uses TopicPage-based composition.
    Otherwise falls back to the original leaf domain logic.
    """
    llm = (config or {}).get("configurable", {}).get("llm")
    topic_structure = state.get("topic_structure")
    entity_roles = state.get("entity_roles", {})
    modules = state.get("modules", {})

    module_index: dict[str, dict] = {}
    for repo_name, mod_list in modules.items():
        for mod_dict in mod_list:
            name = mod_dict.get("properties", {}).get("name", "")
            if name:
                mod_dict["_repo"] = repo_name
                module_index[name] = mod_dict

    # --- Topic-based path (when TopicBasedStructurePlanner provided structure) ---
    if topic_structure:
        return await _compose_from_topic_structure(
            topic_structure, module_index, entity_roles, llm
        )

    # --- Original leaf-domain path (fallback) ---
    # ... existing code unchanged ...
```

Add the new helper function:

```python
async def _compose_from_topic_structure(
    topic_structure: list[dict[str, Any]],
    module_index: dict[str, dict],
    entity_roles: dict[str, Any],
    llm: Any,
) -> dict[str, Any]:
    """Compose pages from TopicBasedStructurePlanner output."""
    budget_resolver = TokenBudgetResolver()
    budget = budget_resolver.budget("topic_page_generate")
    sem = asyncio.Semaphore(_COMPOSE_CONCURRENCY)

    all_pages: list[dict[str, Any]] = []
    generated_uids: list[str] = []

    async def _compose_topic(topic: dict[str, Any]) -> list[dict[str, Any]]:
        async with sem:
            covered = topic.get("covered_modules", [])
            domain_dict = _topic_to_domain_dict(
                topic, module_index, entity_roles
            )
            return await _compose_single_leaf_domain(
                domain_dict, module_index, entity_roles, llm, budget
            )

    tasks = [_compose_topic(t) for t in topic_structure]
    for t in topic_structure:
        for sub in t.get("sub_topics", []):
            tasks.append(_compose_topic(sub))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    for item in results:
        if isinstance(item, BaseException):
            log.warning("compose_topic_failed", exc_info=item)
            continue
        pages, uids = item
        all_pages.extend(pages)
        generated_uids.extend(uids)

    log.info("compose_from_topics_done", total_pages=len(all_pages))
    return {"pages": all_pages, "generated_topic_pages": generated_uids}


def _topic_to_domain_dict(
    topic: dict[str, Any],
    module_index: dict[str, dict],
    entity_roles: dict[str, Any],
) -> dict[str, Any]:
    """Convert a TopicPage dict into the domain dict format expected by
    _compose_single_leaf_domain."""
    covered = topic.get("covered_modules", [])
    module_names = [name for _repo, name in covered]
    return {
        "name": topic["title"],
        "modules": module_names,
        "children": [],
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_pipeline_topic_compose.py -v`
Expected: PASS

- [ ] **Step 5: Verify summarize_leaves compatibility**

Ensure that pages generated via topic_structure still have the `"domain"` field set to match domain_tree leaf names. In `_compose_from_topic_structure`, after `_compose_single_leaf_domain` returns pages, verify each page dict has `"domain"` key.

- [ ] **Step 6: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add wiki/pipeline_nodes.py tests/wiki/test_pipeline_topic_compose.py
git commit -m "feat: compose_leaf_pages_node uses topic_structure when available"
```

---

### Task 6: 主题页代码关联 (U3b)

**Files:**
- Modify: `wiki/pipeline_nodes.py` (`_compose_single_leaf_domain` — add `covered_entity_uids`)
- Modify: `wiki/persistence.py` (`persist_pages_to_graph` — support multi-entity edges)
- Test: `tests/wiki/test_persistence_multi_entity.py`

- [ ] **Step 1: Write failing test for multi-entity persistence**

```python
# tests/wiki/test_persistence_multi_entity.py
import pytest
from unittest.mock import AsyncMock, MagicMock

@pytest.mark.asyncio
async def test_persist_creates_source_entity_edges_for_covered_uids():
    """persist_pages_to_graph should create SOURCE_ENTITY edges for
    each uid in covered_entity_uids."""
    from wiki.persistence import WikiPagePersistence
    from wiki.models import WikiPage, WikiPageMetadata

    page = WikiPage(
        title="User Management",
        content="# User Management\nContent",
        path="wiki/User Management",
        repository="default",
        page_type="topic",
        metadata=WikiPageMetadata(),
    )
    page._covered_entity_uids = ["Module::UserService:0", "Module::AuthService:0"]

    mock_store = AsyncMock()
    mock_store.execute_query = AsyncMock()

    persistence = WikiPagePersistence.__new__(WikiPagePersistence)
    persistence._store = mock_store
    persistence._wiki_cfg = MagicMock()
    persistence._wiki_cfg.claim_tracking_concurrency = 1

    await persistence.persist_pages_to_graph("default", [page])

    # Check that execute_query was called with pairs containing both UIDs
    calls = mock_store.execute_query.call_args_list
    edge_calls = [c for c in calls if "SOURCE_ENTITY" in str(c)]
    assert len(edge_calls) > 0, "Should create SOURCE_ENTITY edges"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_persistence_multi_entity.py -v`
Expected: FAIL

- [ ] **Step 3: Add covered_entity_uids to _compose_single_leaf_domain output**

In `wiki/pipeline_nodes.py`, `_compose_single_leaf_domain()`, before the return statement, collect UIDs:

```python
    covered_entity_uids = [e["uid"] for e in biz_entities] + [d["uid"] for d in data_models]
```

Add to each page dict returned:

```python
    # In the page dict construction:
    page_dict["covered_entity_uids"] = covered_entity_uids
```

- [ ] **Step 4: Extend persistence to handle covered_entity_uids**

In `wiki/persistence.py`, in `persist_pages_to_graph()`, after the existing `entity_uid` pairs construction, add:

```python
        # Multi-entity edges (topic pages covering multiple modules)
        for pd in page_dicts:
            covered = getattr(pd.get("_page_obj"), "_covered_entity_uids", None) or pd.get("covered_entity_uids", [])
            if covered:
                wiki_uid = f"WikiPage:{repository}:{pd['path']}"
                for eu in covered:
                    if eu and {"wiki_uid": wiki_uid, "entity_uid": eu} not in pairs:
                        pairs.append({"wiki_uid": wiki_uid, "entity_uid": eu})
```

- [ ] **Step 5: Add repo and file_path to biz_entities in prompt**

In `wiki/pipeline_nodes.py`, `_compose_single_leaf_domain()`, when building `biz_entities`:

```python
        if str(role) in ("has_business_logic", "entry_point"):
            biz_entities.append({
                "uid": uid,
                "name": mod_name,
                "repository": mod_dict.get("_repo", ""),
                "file_path": str(props.get("file", "") or props.get("file_path", "")),
                "summary": str(props.get("business_summary", "") or props.get("docstring", "") or ""),
                "methods": [str(m) for m in (props.get("methods", []) or [])[:10]],
                "calls": [str(c) for c in (props.get("calls", []) or [])[:15]],
            })
```

- [ ] **Step 6: Run tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_persistence_multi_entity.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add wiki/pipeline_nodes.py wiki/persistence.py tests/wiki/test_persistence_multi_entity.py
git commit -m "feat: topic pages retain SOURCE_ENTITY edges for code navigation"
```

---

### Task 7: 跨仓库主题增强 (U3c)

**Files:**
- Modify: `wiki/pipeline_nodes.py` (module_index retains repo info)
- Modify: `wiki/topic_page_composer.py` (prompt includes repo context)
- Test: existing tests + manual verification

- [ ] **Step 1: Verify module_index already has _repo field**

Check that Task 5's change to inject `mod_dict["_repo"] = repo_name` is in place. This was already done in `compose_leaf_pages_node` modification.

- [ ] **Step 2: Update TopicPageComposer prompt to include repo info**

In `wiki/topic_page_composer.py`, `_build_single_page_prompt()`:

```python
        entities_desc = "\n".join(
            f"- **{e['name']}** [{e.get('repository', '')}]: {e.get('summary', '')} "
            f"(file: {e.get('file_path', 'unknown')}; methods: {', '.join(e.get('methods', [])[:10])}; "
            f"calls: {', '.join(e.get('calls', [])[:5])})"
            for e in domain.get("biz_entities", [])
        )
```

Add to the prompt instructions:

```python
            "- Source code references using `source://repo/file:line` notation\n"
            "- When describing cross-repo interactions, annotate which repository each service belongs to\n"
```

- [ ] **Step 3: Run existing tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/ -x -q --timeout=60 2>&1 | tail -20`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add wiki/pipeline_nodes.py wiki/topic_page_composer.py
git commit -m "feat: topic pages include cross-repo context and source references"
```

---

## Phase 3: 进阶优化 (U3d) — 延迟实施

> Phase 3 (U3d 增量更新策略) 涉及 compose_leaf_pages_node 读取图数据库加载已有页面，是较大的架构变更。建议在 Phase 1+2 验证稳定后单独设计和实施。此处仅记录方向，不包含实施步骤。

### Task 8: 部署验证

**Files:**
- `deploy-dev.sh`

- [ ] **Step 1: 部署到打包机**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && bash deploy-dev.sh`

- [ ] **Step 2: 触发 ultron-composite 业务 wiki 生成**

通过 API 触发业务级 wiki 生成，验证：
- 页面数量 ≤ 80
- 生成时间 < 1h
- 主题页有 SOURCE_ENTITY 关联
- Wiki 树结构按业务域层次展开

- [ ] **Step 3: E2E 验证**

使用浏览器访问 wiki dashboard，确认：
- 主题页内容丰富（非骨架）
- 可从 wiki 页面导航到代码引用
- 搜索功能正常
- 跨仓库主题聚合正确
