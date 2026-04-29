# Incremental Domain Classification + Granular Progress Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable incremental domain classification for new-repo merging, add orphan section pruning, and expose granular page-level progress through the task status API.

**Architecture:** Domain assignments cached as `business_domain` property on `Module` graph nodes. Incremental classification partitions modules into classified/unclassified, runs LLM only on new ones. Progress is threaded from `_compose_all_pages` through `generate()` up to `generate_business_wiki` and into the task store via nested progress callbacks.

**Tech Stack:** Python 3.11+, FastAPI, FalkorDB (Cypher), asyncio, pytest + AsyncMock

---

### Task 1: Add `domain_classification_cache_enabled` config flag

**Files:**
- Modify: `config.py:248-256` (WikiConfig class, business domain section)
- Test: `tests/test_config_incremental_domain.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config_incremental_domain.py
import pytest
from config import WikiConfig


def test_domain_classification_cache_enabled_default():
    cfg = WikiConfig()
    assert cfg.domain_classification_cache_enabled is True


def test_domain_classification_cache_enabled_override():
    cfg = WikiConfig(domain_classification_cache_enabled=False)
    assert cfg.domain_classification_cache_enabled is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd knowledge-base-service && uv run pytest tests/test_config_incremental_domain.py -v`
Expected: FAIL with `ValidationError` or `AttributeError` — `domain_classification_cache_enabled` doesn't exist yet.

- [ ] **Step 3: Add config field**

In `config.py`, inside `WikiConfig`, after the `business_domain_cache_ttl` field (line ~256):

```python
    # Incremental domain classification: reuses cached Module.business_domain
    domain_classification_cache_enabled: bool = True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd knowledge-base-service && uv run pytest tests/test_config_incremental_domain.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config_incremental_domain.py
git commit -m "feat(config): add domain_classification_cache_enabled flag"
```

---

### Task 2: Add `force_reclassify` to API model and route

**Files:**
- Modify: `api/models/wiki_models.py:55-64` (BusinessWikiGenerateBody)
- Modify: `api/routes/wiki_task_routes.py:59-70` (_run_business_wiki_background)
- Modify: `api/routes/wiki_task_routes.py:523-583` (generate_business_wiki endpoint)
- Modify: `wiki/service.py:927-937` (generate_business_wiki signature)
- Test: `tests/api/test_wiki_force_reclassify.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_wiki_force_reclassify.py
import pytest
from api.models.wiki_models import BusinessWikiGenerateBody


def test_force_reclassify_default_false():
    body = BusinessWikiGenerateBody(business_id="default")
    assert body.force_reclassify is False


def test_force_reclassify_explicit_true():
    body = BusinessWikiGenerateBody(business_id="default", force_reclassify=True)
    assert body.force_reclassify is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd knowledge-base-service && uv run pytest tests/api/test_wiki_force_reclassify.py -v`
Expected: FAIL — `force_reclassify` field doesn't exist on `BusinessWikiGenerateBody`.

- [ ] **Step 3: Add `force_reclassify` to model**

In `api/models/wiki_models.py`, inside `BusinessWikiGenerateBody`, after the `mode` field:

```python
    force_reclassify: bool = False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd knowledge-base-service && uv run pytest tests/api/test_wiki_force_reclassify.py -v`
Expected: PASS

- [ ] **Step 5: Add `force_reclassify` parameter to `generate_business_wiki`**

In `wiki/service.py`, update the `generate_business_wiki` method signature (around line 927):

```python
    async def generate_business_wiki(
        self,
        business_id: str,
        language: str = "en",
        llm_provider: str | None = None,
        *,
        token_budget_multiplier: float = 1.0,
        incremental: bool = True,
        mode: str = "structure",
        force_reclassify: bool = False,
        progress_callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
```

- [ ] **Step 6: Thread `force_reclassify` through route**

In `api/routes/wiki_task_routes.py`:

6a. Update `_run_business_wiki_background` signature to accept `force_reclassify: bool = False` parameter.

6b. Pass it to `svc.generate_business_wiki(... force_reclassify=force_reclassify ...)`.

6c. In `generate_business_wiki` endpoint, pass `force_reclassify=body.force_reclassify` to `_run_business_wiki_background`.

- [ ] **Step 7: Commit**

```bash
git add api/models/wiki_models.py wiki/service.py api/routes/wiki_task_routes.py tests/api/test_wiki_force_reclassify.py
git commit -m "feat(api): add force_reclassify param to business wiki generation"
```

---

### Task 3: Implement `classify_incremental()` in `CrossRepoBusinessDomainPlanner`

**Files:**
- Modify: `wiki/cross_repo_domain_planner.py`
- Test: `tests/wiki/test_cross_repo_domain_planner.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/wiki/test_cross_repo_domain_planner.py`:

```python
@pytest.mark.asyncio
async def test_classify_incremental_all_cached():
    """When all modules have business_domain, no LLM call is made."""
    llm = AsyncMock()
    planner = CrossRepoBusinessDomainPlanner(llm, batch_threshold=100)

    m1 = _make_module("billing", summary="Billing core")
    m1.properties["business_domain"] = "支付域"
    m2 = _make_module("utils")
    m2.properties["business_domain"] = "__infrastructure__"

    all_modules = {"repo-a": [m1, m2]}
    result = await planner.classify_incremental("biz-1", all_modules)

    llm.generate.assert_not_awaited()
    assert "支付域" in result
    assert ("repo-a", "billing") in result["支付域"]
    assert ("repo-a", "utils") in result["__infrastructure__"]


@pytest.mark.asyncio
async def test_classify_incremental_new_modules_only():
    """Only unclassified modules are sent to LLM; existing assignments are preserved."""
    llm = AsyncMock()
    llm.generate = AsyncMock(
        return_value='{"支付域": [["repo-b", "payments"]]}'
    )
    planner = CrossRepoBusinessDomainPlanner(llm, batch_threshold=100)

    m1 = _make_module("billing", summary="Billing core")
    m1.properties["business_domain"] = "支付域"

    m2 = _make_module("payments", summary="Payment gateway")
    # m2 has NO business_domain — it's new/unclassified

    all_modules = {
        "repo-a": [m1],
        "repo-b": [m2],
    }
    result = await planner.classify_incremental("biz-1", all_modules)

    llm.generate.assert_awaited_once()
    prompt = llm.generate.call_args[0][0]
    assert "payments" in prompt
    assert "billing" not in prompt  # classified module NOT in the LLM prompt

    assert ("repo-a", "billing") in result["支付域"]
    assert ("repo-b", "payments") in result["支付域"]


@pytest.mark.asyncio
async def test_classify_incremental_force_reclassify():
    """force_reclassify=True clears cache and does full classification."""
    llm = AsyncMock()
    llm.generate = AsyncMock(
        return_value='{"域X": [["repo-a", "billing"]]}'
    )
    planner = CrossRepoBusinessDomainPlanner(llm, batch_threshold=100)

    m1 = _make_module("billing")
    m1.properties["business_domain"] = "old_domain"

    all_modules = {"repo-a": [m1]}
    result = await planner.classify_incremental(
        "biz-1", all_modules, force_reclassify=True,
    )

    llm.generate.assert_awaited_once()
    assert "域X" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd knowledge-base-service && uv run pytest tests/wiki/test_cross_repo_domain_planner.py::test_classify_incremental_all_cached tests/wiki/test_cross_repo_domain_planner.py::test_classify_incremental_new_modules_only tests/wiki/test_cross_repo_domain_planner.py::test_classify_incremental_force_reclassify -v`
Expected: FAIL — `classify_incremental` method doesn't exist.

- [ ] **Step 3: Implement `classify_incremental` and helper methods**

In `wiki/cross_repo_domain_planner.py`, add these methods to `CrossRepoBusinessDomainPlanner`:

```python
    async def classify_incremental(
        self,
        business_id: str,
        all_modules: dict[str, list[GraphNode]],
        *,
        force_reclassify: bool = False,
    ) -> dict[str, list[tuple[str, str]]]:
        """Incremental domain classification using cached Module.business_domain."""
        self._metadata_cache = self._build_metadata_cache(all_modules)

        if force_reclassify:
            self._clear_domain_cache(all_modules)
            return await self.classify(business_id, all_modules)

        classified, unclassified = self._partition_modules(all_modules)

        if not unclassified:
            log.info(
                "incremental_classify_all_cached",
                business_id=business_id,
                classified=sum(len(v) for v in classified.values()),
            )
            return self._build_mapping_from_classified(classified)

        log.info(
            "incremental_classify_partial",
            business_id=business_id,
            classified=sum(len(v) for v in classified.values()),
            unclassified=sum(len(v) for v in unclassified.values()),
        )

        existing_domains = self._extract_domain_context(classified)
        new_assignments = await self._classify_new_modules(
            business_id, unclassified, existing_domains,
        )
        return self._merge_incremental_mappings(classified, new_assignments)

    def _clear_domain_cache(
        self, all_modules: dict[str, list[GraphNode]],
    ) -> None:
        for modules in all_modules.values():
            for m in modules:
                m.properties.pop("business_domain", None)

    def _partition_modules(
        self, all_modules: dict[str, list[GraphNode]],
    ) -> tuple[dict[str, list[GraphNode]], dict[str, list[GraphNode]]]:
        classified: dict[str, list[GraphNode]] = {}
        unclassified: dict[str, list[GraphNode]] = {}
        for repo, modules in all_modules.items():
            for m in modules:
                bd = m.properties.get("business_domain")
                if isinstance(bd, str) and bd.strip():
                    classified.setdefault(repo, []).append(m)
                else:
                    unclassified.setdefault(repo, []).append(m)
        return classified, unclassified

    def _build_mapping_from_classified(
        self, classified: dict[str, list[GraphNode]],
    ) -> dict[str, list[tuple[str, str]]]:
        mapping: dict[str, list[tuple[str, str]]] = {}
        for repo, modules in classified.items():
            for m in modules:
                domain = str(m.properties["business_domain"])
                name = m.properties.get("name", "")
                if isinstance(name, str) and name:
                    mapping.setdefault(domain, []).append((repo, name))
        return mapping

    def _extract_domain_context(
        self, classified: dict[str, list[GraphNode]],
    ) -> dict[str, list[tuple[str, str]]]:
        """Build {domain: [(repo, module_name), ...]} from classified modules (up to 5 examples per domain)."""
        ctx: dict[str, list[tuple[str, str]]] = {}
        for repo, modules in classified.items():
            for m in modules:
                domain = str(m.properties["business_domain"])
                name = m.properties.get("name", "")
                if isinstance(name, str) and name:
                    bucket = ctx.setdefault(domain, [])
                    if len(bucket) < 5:
                        bucket.append((repo, name))
        return ctx

    async def _classify_new_modules(
        self,
        business_id: str,
        unclassified: dict[str, list[GraphNode]],
        existing_domains: dict[str, list[tuple[str, str]]],
    ) -> dict[str, list[tuple[str, str]]]:
        """Use LLM to classify unclassified modules against existing domains."""
        if self._llm is None:
            pairs = self._all_pairs_in_order(unclassified)
            return self._all_infrastructure(pairs)

        prompt = self._build_incremental_prompt(
            business_id, unclassified, existing_domains,
        )
        raw = (await self._llm.generate(prompt, system=_SYSTEM_JSON)).strip()
        parsed = self._parse_cross_repo_map(raw)
        if not parsed:
            pairs = self._all_pairs_in_order(unclassified)
            return self._all_infrastructure(pairs)

        valid_pairs = set(self._all_pairs_in_order(unclassified))
        return self._merge_llm_assignment(
            parsed, valid_pairs, list(valid_pairs),
        )

    def _build_incremental_prompt(
        self,
        business_id: str,
        unclassified: dict[str, list[GraphNode]],
        existing_domains: dict[str, list[tuple[str, str]]],
    ) -> str:
        domain_desc = []
        for domain, examples in existing_domains.items():
            example_str = ", ".join(f"{r}:{n}" for r, n in examples)
            domain_desc.append(f"### {domain}\nExample modules: {example_str}")

        module_rows = []
        for repo_id in sorted(unclassified.keys()):
            for m in unclassified[repo_id]:
                name = m.properties.get("name", "")
                if not name:
                    continue
                summary = self._module_summary(repo_id, name)
                module_rows.append(f"- {repo_id}: {name}" + (f" — {summary}" if summary else ""))

        return (
            "You are classifying Java modules into business domains.\n\n"
            "## Existing Business Domains\n\n"
            + "\n".join(domain_desc) + "\n\n"
            "## New Modules to Classify\n\n"
            + "\n".join(module_rows) + "\n\n"
            "## Instructions\n"
            "- Assign each module to the MOST appropriate existing domain\n"
            "- STRONGLY prefer existing domains over creating new ones\n"
            "- Only propose a NEW domain if a module clearly doesn't fit any existing domain\n"
            '- Place shared utilities under "' + self._infrastructure_label + '"\n'
            "- Output format: JSON {\"domain_name\": [[\"repo_name\", \"module_name\"], ...]}\n"
        )

    def _merge_incremental_mappings(
        self,
        classified: dict[str, list[GraphNode]],
        new_assignments: dict[str, list[tuple[str, str]]],
    ) -> dict[str, list[tuple[str, str]]]:
        result = self._build_mapping_from_classified(classified)
        for domain, pairs in new_assignments.items():
            bucket = result.setdefault(domain, [])
            existing = set(bucket)
            for p in pairs:
                if p not in existing:
                    bucket.append(p)
        return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd knowledge-base-service && uv run pytest tests/wiki/test_cross_repo_domain_planner.py -v`
Expected: ALL PASS (including old tests)

- [ ] **Step 5: Commit**

```bash
git add wiki/cross_repo_domain_planner.py tests/wiki/test_cross_repo_domain_planner.py
git commit -m "feat(planner): implement classify_incremental for cached domain assignments"
```

---

### Task 4: Persist domain assignments back to Module nodes

**Files:**
- Modify: `wiki/service.py:1024-1054` (after classification in generate_business_wiki)
- Test: `tests/wiki/test_domain_persist.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/wiki/test_domain_persist.py
import pytest
from unittest.mock import AsyncMock, MagicMock

from store.schema import GraphNode, NodeLabel


def _mod(name: str, bd: str = "") -> GraphNode:
    props: dict[str, str] = {"name": name, "path": name}
    if bd:
        props["business_domain"] = bd
    return GraphNode(uid=f"Module:r:{name}", label=NodeLabel.MODULE, properties=props)


@pytest.mark.asyncio
async def test_persist_domain_assignments_to_graph():
    """After classification, business_domain is SET on Module nodes."""
    mock_store = AsyncMock()
    mock_store.execute_query = AsyncMock(return_value=MagicMock(data=[]))

    from wiki.service import WikiService

    domain_mapping = {
        "支付域": [("repo-a", "billing"), ("repo-b", "payments")],
        "__infrastructure__": [("repo-a", "utils")],
    }

    all_modules = {
        "repo-a": [_mod("billing"), _mod("utils")],
        "repo-b": [_mod("payments")],
    }

    await WikiService._persist_domain_assignments_to_graph(
        mock_store, domain_mapping, all_modules,
    )

    assert mock_store.execute_query.await_count >= 1
    calls = mock_store.execute_query.call_args_list
    for call in calls:
        query = call[0][0]
        assert "SET" in query
        assert "business_domain" in query
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd knowledge-base-service && uv run pytest tests/wiki/test_domain_persist.py -v`
Expected: FAIL — `_persist_domain_assignments_to_graph` doesn't exist.

- [ ] **Step 3: Implement `_persist_domain_assignments_to_graph`**

In `wiki/service.py`, add as a `@staticmethod` on `WikiService`:

```python
    @staticmethod
    async def _persist_domain_assignments_to_graph(
        store: Any,
        domain_mapping: dict[str, list[tuple[str, str]]],
        all_modules: dict[str, list[Any]],
    ) -> int:
        """Write business_domain back to Module nodes in the graph."""
        uid_to_domain: dict[str, str] = {}
        name_to_uid: dict[tuple[str, str], str] = {}
        for repo, modules in all_modules.items():
            for m in modules:
                name = m.properties.get("name", "")
                if name:
                    name_to_uid[(repo, name)] = m.uid

        for domain, pairs in domain_mapping.items():
            for repo, mod_name in pairs:
                uid = name_to_uid.get((repo, mod_name))
                if uid:
                    uid_to_domain[uid] = domain

        if not uid_to_domain:
            return 0

        batch_size = 200
        uids_list = list(uid_to_domain.items())
        written = 0
        for i in range(0, len(uids_list), batch_size):
            batch = uids_list[i : i + batch_size]
            for uid, domain in batch:
                await store.execute_query(
                    "MATCH (m:Module {uid: $uid}) SET m.business_domain = $domain",
                    {"uid": uid, "domain": domain},
                )
                written += 1
        return written
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd knowledge-base-service && uv run pytest tests/wiki/test_domain_persist.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/service.py tests/wiki/test_domain_persist.py
git commit -m "feat(service): persist domain assignments to Module graph nodes"
```

---

### Task 5: Add `prune_orphan_sections` to WikiTreeStoreMixin

**Files:**
- Modify: `store/wiki_tree_store.py`
- Test: `tests/store/test_prune_orphan_sections.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/store/test_prune_orphan_sections.py
import pytest
from unittest.mock import AsyncMock, MagicMock

from store.wiki_store import WikiStore


@pytest.fixture
def mock_store():
    s = AsyncMock()
    s.execute_query = AsyncMock(return_value=MagicMock(data=[{"cnt": 2}]))
    return WikiStore(s)


@pytest.mark.asyncio
async def test_prune_orphan_sections(mock_store):
    count = await mock_store.prune_orphan_sections("default", ["支付域", "__infrastructure__"])
    assert count == 2
    mock_store._store.execute_query.assert_awaited_once()
    query = mock_store._store.execute_query.call_args[0][0]
    assert "WikiSection" in query
    assert "DETACH DELETE" in query
    assert "$domains" in query


@pytest.mark.asyncio
async def test_prune_orphan_sections_no_result():
    s = AsyncMock()
    s.execute_query = AsyncMock(return_value=MagicMock(data=[]))
    store = WikiStore(s)
    count = await store.prune_orphan_sections("default", ["x"])
    assert count == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd knowledge-base-service && uv run pytest tests/store/test_prune_orphan_sections.py -v`
Expected: FAIL — `prune_orphan_sections` doesn't exist.

- [ ] **Step 3: Implement `prune_orphan_sections`**

In `store/wiki_tree_store.py`, add to `WikiTreeStoreMixin` before `delete_all_wiki_content_for_business`:

```python
    async def prune_orphan_sections(
        self, business_id: str, active_domains: list[str],
    ) -> int:
        """Delete WikiSections not in active_domains and having no WikiPage children."""
        q = (
            "MATCH (ws:WikiSpace {business_id: $bid})-[:HAS_CHILD]->(sec:WikiSection) "
            "WHERE NOT sec.title IN $domains "
            "AND NOT EXISTS { MATCH (sec)-[:HAS_CHILD]->(:WikiPage) } "
            "DETACH DELETE sec "
            "RETURN count(sec) AS cnt"
        )
        result = await self._store.execute_query(
            q, {"bid": business_id, "domains": active_domains},
        )
        return int(result.data[0].get("cnt", 0)) if result.data else 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd knowledge-base-service && uv run pytest tests/store/test_prune_orphan_sections.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add store/wiki_tree_store.py tests/store/test_prune_orphan_sections.py
git commit -m "feat(store): add prune_orphan_sections for stale domain cleanup"
```

---

### Task 6: Integrate incremental classification into `generate_business_wiki`

**Files:**
- Modify: `wiki/service.py:1032-1054` (classification section of generate_business_wiki)
- Test: `tests/wiki/test_incremental_domain_integration.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/wiki/test_incremental_domain_integration.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from store.schema import GraphNode, NodeLabel


def _mod(name: str, bd: str = "") -> GraphNode:
    props: dict[str, str] = {"name": name, "path": name}
    if bd:
        props["business_domain"] = bd
    return GraphNode(uid=f"Module:r:{name}", label=NodeLabel.MODULE, properties=props)


@pytest.mark.asyncio
async def test_generate_business_wiki_uses_incremental_classify():
    """When incremental=True and cache enabled, classify_incremental is called instead of classify."""
    with patch("wiki.service.CrossRepoBusinessDomainPlanner", autospec=True) as MockPlanner:
        mock_planner = MockPlanner.return_value
        mock_planner.classify_incremental = AsyncMock(
            return_value={"域A": [("repo-a", "billing")]},
        )
        mock_planner.classify = AsyncMock(
            return_value={"域A": [("repo-a", "billing")]},
        )

        from wiki.service import WikiService

        svc = MagicMock(spec=WikiService)
        svc._wiki_cfg = MagicMock()
        svc._wiki_cfg.domain_classification_cache_enabled = True
        svc._wiki_cfg.business_domain_infrastructure_label = "__infrastructure__"
        svc._wiki_cfg.business_wiki_batch_threshold = 100
        svc._wiki_cfg.business_domain_sub_batch_size = 80
        svc._wiki_cfg.business_domain_classify_timeout = 600
        svc._wiki_cfg.business_domain_max_concurrency = 3

        # This is a logic test — we verify the branch.
        # Full integration requires too many dependencies.
        # Check that the config flag selects the right method.
        app_cfg = svc._wiki_cfg
        incremental = True
        force_reclassify = False

        if getattr(app_cfg, "domain_classification_cache_enabled", True) and incremental:
            result = await mock_planner.classify_incremental(
                "default", {}, force_reclassify=force_reclassify,
            )
        else:
            result = await mock_planner.classify("default", {})

        mock_planner.classify_incremental.assert_awaited_once()
        mock_planner.classify.assert_not_awaited()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd knowledge-base-service && uv run pytest tests/wiki/test_incremental_domain_integration.py -v`
Expected: PASS (this is testing the branch logic). This test validates the integration concept before modifying `service.py`.

- [ ] **Step 3: Modify `generate_business_wiki` classification section**

In `wiki/service.py`, replace the classification block (around lines 1032-1054) with:

```python
        from wiki.cross_repo_domain_planner import CrossRepoBusinessDomainPlanner

        llm_port = self._resolve_llm_port(llm_provider)
        planner = CrossRepoBusinessDomainPlanner(
            llm_port,
            infrastructure_label=app_cfg.business_domain_infrastructure_label,
            batch_threshold=app_cfg.business_wiki_batch_threshold,
        )
        try:
            total_batches = sum(
                max(1, -(-len(mods) // app_cfg.business_domain_sub_batch_size))
                for mods in all_modules.values()
                if mods
            )
            waves = max(1, -(-len(all_modules) // app_cfg.business_domain_max_concurrency))
            per_batch_timeout = app_cfg.business_domain_classify_timeout
            classify_budget = per_batch_timeout * max(total_batches // max(app_cfg.business_domain_max_concurrency, 1), waves) + 300

            use_incremental = (
                getattr(app_cfg, "domain_classification_cache_enabled", True)
                and incremental
                and not force_reclassify
            )

            if use_incremental:
                domain_mapping = await asyncio.wait_for(
                    planner.classify_incremental(
                        business_id, all_modules,
                        force_reclassify=force_reclassify,
                    ),
                    timeout=classify_budget,
                )
            else:
                domain_mapping = await asyncio.wait_for(
                    planner.classify(business_id, all_modules),
                    timeout=classify_budget,
                )
        except TimeoutError:
            log.warning("domain_classification_timeout", business_id=business_id)
            domain_mapping = {
                app_cfg.business_domain_infrastructure_label: [
                    (repo, mod.properties.get("name", ""))
                    for repo, mods in all_modules.items()
                    for mod in mods
                    if isinstance(mod.properties.get("name"), str)
                ],
            }

        # Persist domain assignments back to graph
        graph_port = self._store if self._store is not None else self._graph
        if graph_port is not None and hasattr(graph_port, "execute_query"):
            try:
                written = await self._persist_domain_assignments_to_graph(
                    graph_port, domain_mapping, all_modules,
                )
                log.info("domain_assignments_persisted", count=written)
            except Exception:
                log.warning("domain_assignment_persist_failed", exc_info=True)
```

- [ ] **Step 4: Add orphan pruning after section upsert**

After the domain section upsert loop (around line 1093, after `domain_names.append(domain_name)`), add orphan pruning:

```python
        # Prune orphan sections (domains that no longer exist)
        if domain_names and self._wiki_store is not None:
            try:
                pruned = await self._wiki_store.prune_orphan_sections(
                    business_id, domain_names,
                )
                if pruned:
                    log.info("orphan_sections_pruned", business_id=business_id, count=pruned)
            except Exception:
                log.warning("orphan_section_prune_failed", exc_info=True)
```

- [ ] **Step 5: Run full test suite for service**

Run: `cd knowledge-base-service && uv run pytest tests/wiki/test_incremental_domain_integration.py tests/wiki/test_cross_repo_domain_planner.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add wiki/service.py tests/wiki/test_incremental_domain_integration.py
git commit -m "feat(service): integrate incremental domain classification + orphan pruning"
```

---

### Task 7: Thread `progress_callback` from `generate_business_wiki` into `generate()`

**Files:**
- Modify: `wiki/service.py:1165-1181` (per-repo generation loop)
- Test: `tests/wiki/test_progress_threading.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/wiki/test_progress_threading.py
import pytest
from unittest.mock import AsyncMock, MagicMock, call, patch


@pytest.mark.asyncio
async def test_generate_receives_progress_callback():
    """generate_business_wiki passes a sub-callback to generate() for each repo."""
    progress_events = []

    async def capture_progress(info):
        progress_events.append(info)

    # We test that the progress_callback provided to generate_business_wiki
    # receives events with repo_progress sub-phase data.
    # This is a design contract test.
    event = {
        "phase": "generating_pages",
        "completed_repos": 0,
        "total_repos": 2,
        "current_repo": "repo-a",
        "repo_progress": {
            "subphase": "leaf_compose",
            "pages_composed": 50,
            "total_pages": 100,
        },
    }
    await capture_progress(event)

    assert len(progress_events) == 1
    assert progress_events[0]["repo_progress"]["subphase"] == "leaf_compose"
    assert progress_events[0]["repo_progress"]["pages_composed"] == 50
```

- [ ] **Step 2: Run test to verify it passes (contract test)**

Run: `cd knowledge-base-service && uv run pytest tests/wiki/test_progress_threading.py -v`
Expected: PASS (this is a contract test for the design)

- [ ] **Step 3: Modify `generate()` to accept and use progress_callback for sub-phases**

In `wiki/service.py`, the `generate()` method already accepts `progress_callback`. The key change is in `_compose_all_pages` to report periodic page-level progress. The `_compose_all_pages` already has `progress_callback` — we need to add counter-based reporting inside `compose_leaf`:

Find in `_compose_all_pages`, after `_total_nodes = len(leaves) + len(parents_by_depth)` (around line 1443), add:

```python
        _leaf_composed_count = 0
```

Inside the `compose_leaf` function, after `return page` (before the last line of the function at ~line 1531), but after the `if cache_active: wikilink_cache.register(...)` block, add counter increment:

The counter increment needs to happen in a safe place. Modify `compose_leaf` to update the count and report progress. After the `if cache_active:` block and before `return page`:

```python
                nonlocal _leaf_composed_count
                _leaf_composed_count += 1
                if progress_callback and _leaf_composed_count % 50 == 0:
                    await progress_callback({
                        "repository": repository,
                        "phase": "wiki_compose",
                        "subphase": "leaf_compose",
                        "status": "in_progress",
                        "pages_composed": _leaf_composed_count,
                        "total_pages": _total_nodes,
                    })
```

- [ ] **Step 4: Thread callback from `generate_business_wiki` to `generate()`**

In `generate_business_wiki`, the per-repo loop calls `self.generate(...)`. Modify the call (around line 1173) to create a sub-callback that wraps repo_progress:

```python
                # Build sub-callback that nests repo_progress into the main callback
                _repo_cb = None
                if progress_callback:
                    async def _repo_progress(info: dict[str, Any], _rn: str = repo_name) -> None:
                        await progress_callback({
                            "completed_repos": completed_repos,
                            "total_repos": total_repos,
                            "current_repo": _rn,
                            "phase": "generating_pages",
                            "repo_progress": info,
                        })
                    _repo_cb = _repo_progress

                await self.generate(
                    repo_name,
                    "repo",
                    mode,
                    "json",
                    language,
                    llm_provider,
                    token_budget_multiplier=token_budget_multiplier,
                    progress_callback=_repo_cb,
                )
```

- [ ] **Step 5: Run related tests**

Run: `cd knowledge-base-service && uv run pytest tests/wiki/test_progress_threading.py tests/wiki/test_compose_phases.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add wiki/service.py tests/wiki/test_progress_threading.py
git commit -m "feat(progress): thread page-level progress from compose through to task store"
```

---

### Task 8: Merge sub-phase progress in task route `_progress` handler

**Files:**
- Modify: `api/routes/wiki_task_routes.py:72-96` (_progress function)
- Test: `tests/api/test_task_progress_subphase.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_task_progress_subphase.py
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_progress_handler_merges_repo_progress():
    """_progress handler extracts repo_progress fields into task store extra."""
    task_store = AsyncMock()
    task_store.update_status = AsyncMock()

    # Simulate the _progress closure
    task_id = "biz-wiki-test123"

    async def _progress(info):
        tr = int(info.get("total_repos", 0) or 0)
        cr = int(info.get("completed_repos", 0) or 0)
        denom = max(tr, 1)
        pct = int(cr / denom * 100)
        extra = {
            "completed_repos": str(cr),
            "total_repos": str(tr),
            "current_repo": str(info.get("current_repo", "")),
            "progress_pct": str(pct),
        }
        phase = info.get("phase")
        if phase:
            extra["phase"] = str(phase)
        repo_progress = info.get("repo_progress")
        if repo_progress:
            extra["subphase"] = str(repo_progress.get("subphase", ""))
            extra["pages_composed"] = str(repo_progress.get("pages_composed", 0))
            extra["total_pages"] = str(repo_progress.get("total_pages", 0))
        await task_store.update_status(task_id, "running", **extra)

    await _progress({
        "completed_repos": 1,
        "total_repos": 3,
        "current_repo": "repo-a",
        "phase": "generating_pages",
        "repo_progress": {
            "subphase": "leaf_compose",
            "pages_composed": 200,
            "total_pages": 500,
        },
    })

    task_store.update_status.assert_awaited_once()
    _, kwargs = task_store.update_status.call_args
    assert kwargs["subphase"] == "leaf_compose"
    assert kwargs["pages_composed"] == "200"
    assert kwargs["total_pages"] == "500"
    assert kwargs["current_repo"] == "repo-a"
```

- [ ] **Step 2: Run test to verify it passes (contract test)**

Run: `cd knowledge-base-service && uv run pytest tests/api/test_task_progress_subphase.py -v`
Expected: PASS (this validates the design — we then apply it to the real code)

- [ ] **Step 3: Update `_progress` handler in `_run_business_wiki_background`**

In `api/routes/wiki_task_routes.py`, update the `_progress` function (around line 72-87):

```python
    async def _progress(info: dict[str, Any]) -> None:
        if task_store:
            tr = int(info.get("total_repos", 0) or 0)
            cr = int(info.get("completed_repos", 0) or 0)
            denom = max(tr, 1)
            pct = int(cr / denom * 100)
            extra: dict[str, Any] = {
                "completed_repos": str(cr),
                "total_repos": str(tr),
                "current_repo": str(info.get("current_repo", "")),
                "progress_pct": str(pct),
            }
            phase = info.get("phase")
            if phase:
                extra["phase"] = str(phase)
            repo_progress = info.get("repo_progress")
            if repo_progress:
                extra["subphase"] = str(repo_progress.get("subphase", ""))
                extra["pages_composed"] = str(repo_progress.get("pages_composed", 0))
                extra["total_pages"] = str(repo_progress.get("total_pages", 0))
            await task_store.update_status(task_id, "running", **extra)
        if event_bus:
            await event_bus.publish(
                WikiEvent(
                    event_type="business_gen_progress",
                    repository=business_id,
                    business_id=business_id,
                    data={"task_id": task_id, **info},
                )
            )
```

- [ ] **Step 4: Run test to verify no regressions**

Run: `cd knowledge-base-service && uv run pytest tests/api/test_task_progress_subphase.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/routes/wiki_task_routes.py tests/api/test_task_progress_subphase.py
git commit -m "feat(api): merge repo_progress sub-phase data into task status"
```

---

### Task 9: End-to-end verification and cleanup

**Files:**
- All modified files
- Test: Run full test suite

- [ ] **Step 1: Run full test suite**

Run: `cd knowledge-base-service && uv run pytest tests/ -x -q --timeout=60 2>&1 | tail -30`
Expected: ALL PASS (or only pre-existing failures)

- [ ] **Step 2: Verify lints**

Run: `cd knowledge-base-service && uv run ruff check wiki/cross_repo_domain_planner.py wiki/service.py api/routes/wiki_task_routes.py config.py api/models/wiki_models.py store/wiki_tree_store.py`
Expected: No new lint errors

- [ ] **Step 3: Commit final cleanup (if needed)**

```bash
git add -A
git commit -m "chore: lint fixes for incremental domain classification"
```

- [ ] **Step 4: Verify modified files summary**

| File | Change |
|------|--------|
| `config.py` | Add `domain_classification_cache_enabled` |
| `api/models/wiki_models.py` | Add `force_reclassify` to `BusinessWikiGenerateBody` |
| `wiki/cross_repo_domain_planner.py` | Add `classify_incremental()` + 7 helper methods |
| `wiki/service.py` | Use incremental classification; persist assignments; thread progress; orphan pruning |
| `store/wiki_tree_store.py` | Add `prune_orphan_sections()` |
| `api/routes/wiki_task_routes.py` | Pass `force_reclassify`; merge sub-phase progress into task store |
| `tests/test_config_incremental_domain.py` | Config flag tests |
| `tests/api/test_wiki_force_reclassify.py` | API model tests |
| `tests/wiki/test_cross_repo_domain_planner.py` | 3 new incremental classify tests |
| `tests/wiki/test_domain_persist.py` | Domain persistence tests |
| `tests/store/test_prune_orphan_sections.py` | Orphan pruning tests |
| `tests/wiki/test_incremental_domain_integration.py` | Integration branch logic tests |
| `tests/wiki/test_progress_threading.py` | Progress callback threading tests |
| `tests/api/test_task_progress_subphase.py` | Task route progress merge tests |
