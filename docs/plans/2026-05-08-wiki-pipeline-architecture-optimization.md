# Wiki Pipeline Architecture Optimization - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement 8 optimization items (P0.2, P0.1, P1.3, P1.4, P1.5, P2.6, P2.7, P2.8) for the Wiki generation pipeline to improve incremental generation granularity, domain classification stability, and code maintainability.

**Architecture:** Bottom-up recursive Wiki generation pipeline using LangGraph. Pipeline nodes classify entities → classify domains → decompose hierarchy → compose leaf modules → compose leaf pages → compose parent pages → heal → synthesize overviews. This plan adds intra-batch deduplication, oversized-leaf rebalancing, affected-domain filtering, agent context transfer, cross-page awareness, and structural refactoring.

**Tech Stack:** Python 3.12+, pytest + pytest-asyncio, FalkorDB (graph store), LangGraph, structlog

**Source Proposal:** `docs/proposals/PROPOSAL_20260508_090624_architecture_optimization.md`

---

## File Structure

### New Files
| File | Responsibility |
|------|---------------|
| `wiki/nodes/__init__.py` | Re-export all pipeline node functions |
| `wiki/nodes/classify.py` | Entity/domain classification + reorg detection nodes |
| `wiki/nodes/compose.py` | Leaf module/page composition + single-leaf-domain logic |
| `wiki/nodes/aggregate.py` | Parent page composition, leaf summarization, overview synthesis |
| `wiki/nodes/heal.py` | Quality healing node |
| `wiki/nodes/links.py` | Link creation node |
| `wiki/nodes/utils.py` | Shared helpers (_collect_leaf_domains, _normalize_domain_tree, etc.) |
| `tests/wiki/test_domain_stabilizer_batch_dedup.py` | Tests for P0.2 Sub-A |
| `tests/wiki/test_decompose_rebalance.py` | Tests for P0.2 Sub-B+C |
| `tests/wiki/test_incremental_affected_domains.py` | Tests for P0.1 |
| `tests/wiki/test_ccb_agent_context.py` | Tests for P1.3 |
| `tests/wiki/test_read_wiki_page_tool.py` | Tests for P1.4 |
| `tests/wiki/test_parent_cross_domain.py` | Tests for P1.5 |

### Modified Files
| File | Changes |
|------|---------|
| `wiki/domain_stabilizer.py` | Add Phase 2 batch-canonical dedup in `stabilize_sync()` |
| `wiki/pipeline_nodes.py` | Add `_detect_oversized_leaves` + rebalance in `decompose_hierarchy_node`; add `affected_domains` output in `classify_domains_node`; add filtering in `compose_leaf_pages_node`/`compose_parent_pages_node` |
| `wiki/cross_repo_domain_planner.py` | `classify_incremental()` returns `tuple[dict, set[str]]` |
| `wiki/content_context_builder.py` | Add `format_summary_for_agent()` to `EnrichedDomainContext` |
| `wiki/page_agent.py` | Add `known_context` param + implement `read_wiki_page` tool |

---

## Batch 1 (Parallel Tasks)

### Task 1: P0.2 Sub-A — Intra-Batch Deduplication in DomainStabilizer

**Files:**
- Modify: `wiki/domain_stabilizer.py:129-170`
- Create: `tests/wiki/test_domain_stabilizer_batch_dedup.py`

- [ ] **Step 1: Write failing tests for batch deduplication**

```python
# tests/wiki/test_domain_stabilizer_batch_dedup.py
"""Tests for intra-batch deduplication in DomainStabilizer.stabilize_sync()."""

from __future__ import annotations

import pytest

from wiki.domain_stabilizer import DomainStabilizer


class TestBatchDeduplication:
    """P0.2 Sub-A: When no existing domains match, near-duplicate proposed
    domains within the same batch should be merged to the first canonical."""

    def test_two_similar_proposed_merge_to_first(self):
        ds = DomainStabilizer(similarity_threshold=0.8)
        result = ds.stabilize_sync(
            proposed_domains=["订单处理", "订单管理"],
            existing_domains=[],
        )
        assert result["订单处理"] == "订单处理"
        assert result["订单管理"] == "订单处理"

    def test_three_similar_proposed_all_merge_to_first(self):
        ds = DomainStabilizer(similarity_threshold=0.8)
        result = ds.stabilize_sync(
            proposed_domains=["Payment Service", "Payment Module", "Payment System"],
            existing_domains=[],
        )
        assert result["Payment Service"] == "Payment Service"
        assert result["Payment Module"] == "Payment Service"
        assert result["Payment System"] == "Payment Service"

    def test_dissimilar_proposed_remain_independent(self):
        ds = DomainStabilizer(similarity_threshold=0.8)
        result = ds.stabilize_sync(
            proposed_domains=["Meeting", "Payment", "User Auth"],
            existing_domains=[],
        )
        assert result["Meeting"] == "Meeting"
        assert result["Payment"] == "Payment"
        assert result["User Auth"] == "User Auth"

    def test_existing_match_takes_priority_over_batch(self):
        ds = DomainStabilizer(similarity_threshold=0.8)
        result = ds.stabilize_sync(
            proposed_domains=["订单处理", "订单管理"],
            existing_domains=["订单"],
        )
        assert result["订单处理"] == "订单"
        assert result["订单管理"] == "订单"

    def test_batch_dedup_respects_tier_order(self):
        """First proposed domain becomes canonical (input order = priority)."""
        ds = DomainStabilizer(similarity_threshold=0.8)
        result = ds.stabilize_sync(
            proposed_domains=["Live Streaming", "Live Broadcasting"],
            existing_domains=[],
        )
        assert result["Live Streaming"] == "Live Streaming"
        assert result["Live Broadcasting"] == "Live Streaming"

    def test_empty_proposed_returns_empty(self):
        ds = DomainStabilizer(similarity_threshold=0.8)
        result = ds.stabilize_sync(proposed_domains=[], existing_domains=[])
        assert result == {}

    def test_mixed_existing_and_batch_dedup(self):
        """Some proposed match existing, others deduplicate within batch."""
        ds = DomainStabilizer(similarity_threshold=0.8)
        result = ds.stabilize_sync(
            proposed_domains=["Meeting Management", "支付服务", "支付模块"],
            existing_domains=["Meeting"],
        )
        assert result["Meeting Management"] == "Meeting"
        assert result["支付服务"] == "支付服务"
        assert result["支付模块"] == "支付服务"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_domain_stabilizer_batch_dedup.py -v --no-cov`
Expected: FAIL — tests expecting batch dedup behavior that doesn't exist yet

- [ ] **Step 3: Implement batch deduplication in stabilize_sync**

Modify `wiki/domain_stabilizer.py` — replace the `stabilize_sync` method:

```python
    def stabilize_sync(
        self,
        proposed_domains: list[str],
        existing_domains: list[str],
    ) -> dict[str, str]:
        """Synchronous stabilization with Phase 1 (vs existing) + Phase 2 (vs batch).

        Pre-indexes existing domains by their first normalized token to reduce
        comparisons from O(proposed * existing) to roughly O(proposed * bucket).
        Phase 2 compares against already-confirmed batch canonicals when no
        existing domain matched.
        """
        if not proposed_domains:
            return {}

        if not existing_domains:
            # Phase 2 only — no existing to compare against
            result: dict[str, str] = {}
            batch_canonical: list[str] = []
            for proposed in proposed_domains:
                best_batch: tuple[float, str] = (-1.0, proposed)
                for canonical in batch_canonical:
                    sim = self.compute_similarity(proposed, canonical)
                    if sim > best_batch[0]:
                        best_batch = (sim, canonical)
                if best_batch[0] >= self._threshold:
                    result[proposed] = best_batch[1]
                else:
                    result[proposed] = proposed
                    batch_canonical.append(proposed)
            return result

        index: dict[str, list[str]] = {}
        for ed in existing_domains:
            norm = self.normalize_domain_name(ed)
            tokens = self._tokenize_for_jaccard(norm)
            bucket_keys = tokens if tokens else {""}
            for tk in bucket_keys:
                index.setdefault(tk, []).append(ed)

        result: dict[str, str] = {}
        batch_canonical: list[str] = []

        for proposed in proposed_domains:
            pnorm = self.normalize_domain_name(proposed)
            ptokens = self._tokenize_for_jaccard(pnorm)
            candidates: set[str] = set()
            bucket_keys = ptokens if ptokens else {""}
            for tk in bucket_keys:
                candidates.update(index.get(tk, []))
            if not candidates:
                candidates = set(existing_domains)

            # Phase 1: match against existing domains
            best: tuple[float, str] = (-1.0, proposed)
            for existing in candidates:
                sim = self.compute_similarity(proposed, existing)
                if sim > best[0]:
                    best = (sim, existing)

            if best[0] >= self._threshold:
                result[proposed] = best[1]
                continue

            # Phase 2: match against batch canonicals
            best_batch: tuple[float, str] = (-1.0, proposed)
            for canonical in batch_canonical:
                sim = self.compute_similarity(proposed, canonical)
                if sim > best_batch[0]:
                    best_batch = (sim, canonical)

            if best_batch[0] >= self._threshold:
                result[proposed] = best_batch[1]
            else:
                result[proposed] = proposed
                batch_canonical.append(proposed)

        return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_domain_stabilizer_batch_dedup.py tests/wiki/test_domain_stabilizer.py -v --no-cov`
Expected: ALL PASS (new tests + existing tests remain green)

- [ ] **Step 5: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add wiki/domain_stabilizer.py tests/wiki/test_domain_stabilizer_batch_dedup.py
git commit -m "feat(wiki): add intra-batch deduplication to DomainStabilizer.stabilize_sync

P0.2 Sub-A: When multiple proposed domains have no match in existing
domains, they are now compared against each other (Phase 2). The first
occurrence becomes canonical; subsequent near-duplicates map to it."
```

---

### Task 2: P1.3 — Agent-CCB Context Transfer (format_summary_for_agent)

**Files:**
- Modify: `wiki/content_context_builder.py:78-104`
- Create: `tests/wiki/test_ccb_agent_context.py`

- [ ] **Step 1: Write failing test for format_summary_for_agent**

```python
# tests/wiki/test_ccb_agent_context.py
"""Tests for EnrichedDomainContext.format_summary_for_agent() — P1.3."""

from __future__ import annotations

from wiki.content_context_builder import (
    CallChainStep,
    EnrichedDomainContext,
    EntityDetail,
    MethodDetail,
)


class TestFormatSummaryForAgent:
    def _make_context(self) -> EnrichedDomainContext:
        return EnrichedDomainContext(
            domain_name="Payment",
            parent_domain="Commerce",
            biz_entities=[
                EntityDetail(
                    uid="Module::PaymentService:0",
                    name="PaymentService",
                    repository="payment-repo",
                    file_path="src/service/PaymentService.java",
                    entity_type="Module",
                    business_summary="Handles payment processing",
                    methods=[
                        MethodDetail(
                            name="processPayment",
                            signature="public PaymentResult processPayment(PaymentRequest req)",
                            file_path="src/service/PaymentService.java",
                            start_line=45,
                            repository="payment-repo",
                        ),
                        MethodDetail(
                            name="refund",
                            signature="public void refund(String orderId)",
                            file_path="src/service/PaymentService.java",
                            start_line=120,
                            repository="payment-repo",
                        ),
                    ],
                ),
            ],
            cross_domain_calls=[
                CallChainStep(
                    caller="PaymentService",
                    callee="NotificationService",
                    caller_method="processPayment",
                    callee_method="sendReceipt",
                    relationship="CALLS",
                ),
            ],
            interface_impls=[
                {"interface": "PaymentGateway", "impl": "StripeGateway", "module": "PaymentService"}
            ],
            external_callers=[
                {"caller": "OrderService", "method": "checkout", "target": "PaymentService.processPayment"}
            ],
        )

    def test_returns_non_empty_string(self):
        ctx = self._make_context()
        summary = ctx.format_summary_for_agent()
        assert isinstance(summary, str)
        assert len(summary) > 0

    def test_contains_method_signatures(self):
        ctx = self._make_context()
        summary = ctx.format_summary_for_agent()
        assert "processPayment" in summary
        assert "refund" in summary

    def test_contains_cross_domain_calls(self):
        ctx = self._make_context()
        summary = ctx.format_summary_for_agent()
        assert "NotificationService" in summary

    def test_contains_interface_impls(self):
        ctx = self._make_context()
        summary = ctx.format_summary_for_agent()
        assert "PaymentGateway" in summary or "StripeGateway" in summary

    def test_contains_external_callers(self):
        ctx = self._make_context()
        summary = ctx.format_summary_for_agent()
        assert "OrderService" in summary

    def test_respects_max_length(self):
        ctx = self._make_context()
        summary = ctx.format_summary_for_agent(max_chars=200)
        assert len(summary) <= 200

    def test_empty_context_returns_minimal_summary(self):
        ctx = EnrichedDomainContext(domain_name="Empty", parent_domain="Root")
        summary = ctx.format_summary_for_agent()
        assert isinstance(summary, str)
        assert "Empty" in summary or summary == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_ccb_agent_context.py -v --no-cov`
Expected: FAIL — `AttributeError: 'EnrichedDomainContext' object has no attribute 'format_summary_for_agent'`

- [ ] **Step 3: Implement format_summary_for_agent**

Add method to `EnrichedDomainContext` in `wiki/content_context_builder.py` after line 103:

```python
    def format_summary_for_agent(self, max_chars: int = 2000) -> str:
        """Compress already-queried context into a structured summary for WikiPageAgent.

        This avoids redundant tool-calling by the agent for information CCB
        already retrieved from the graph.
        """
        sections: list[str] = []

        if self.biz_entities:
            method_lines: list[str] = []
            for ent in self.biz_entities:
                for m in ent.methods[:5]:
                    method_lines.append(f"  - {ent.name}.{m.name}: {m.signature}")
            if method_lines:
                sections.append("## Known Methods\n" + "\n".join(method_lines[:15]))

        if self.intra_domain_calls or self.cross_domain_calls:
            call_lines: list[str] = []
            for step in (self.intra_domain_calls + self.cross_domain_calls)[:10]:
                call_lines.append(
                    f"  - {step.caller}.{step.caller_method} → {step.callee}.{step.callee_method}"
                )
            if call_lines:
                sections.append("## Known Call Chains\n" + "\n".join(call_lines))

        if self.interface_impls:
            impl_lines = [
                f"  - {d.get('interface', '?')} ← {d.get('impl', '?')}"
                for d in self.interface_impls[:10]
            ]
            sections.append("## Known Implementations\n" + "\n".join(impl_lines))

        if self.external_callers:
            caller_lines = [
                f"  - {d.get('caller', '?')}.{d.get('method', '?')} → {d.get('target', '?')}"
                for d in self.external_callers[:10]
            ]
            sections.append("## Known External Callers\n" + "\n".join(caller_lines))

        if not sections:
            return ""

        full = f"# Already-queried context for domain: {self.domain_name}\n\n" + "\n\n".join(sections)
        if len(full) > max_chars:
            return full[:max_chars - 3] + "..."
        return full
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_ccb_agent_context.py -v --no-cov`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add wiki/content_context_builder.py tests/wiki/test_ccb_agent_context.py
git commit -m "feat(wiki): add format_summary_for_agent to EnrichedDomainContext

P1.3: Compresses CCB-queried information (methods, call chains,
interface implementations, external callers) into a structured summary
that WikiPageAgent can use as initial context, avoiding redundant
graph queries during CONTEXT_GAP enrichment."
```

---

## Batch 2 (Sequential — depends on Batch 1)

### Task 3: P0.2 Sub-B+C — Oversized Leaf Detection + Secondary Decomposition

**Files:**
- Modify: `wiki/pipeline_nodes.py:287-340`
- Create: `tests/wiki/test_decompose_rebalance.py`

- [ ] **Step 1: Write failing tests for oversized leaf detection and rebalance**

```python
# tests/wiki/test_decompose_rebalance.py
"""Tests for P0.2 Sub-B+C: oversized leaf detection and secondary decomposition."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wiki.pipeline_nodes import decompose_hierarchy_node


def _make_state_with_large_leaf(module_count: int = 20) -> dict:
    """Create state that will produce a single flat leaf domain with many modules."""
    modules_list = []
    domain_pairs = []
    for i in range(module_count):
        name = f"Module{i}"
        modules_list.append({
            "uid": f"Module::{name}:0",
            "label": "Module",
            "properties": {"name": name, "path": f"src/{name}.java", "business_summary": f"Module {i}"},
        })
        domain_pairs.append(("repo1", name))

    return {
        "domain_mapping": {"BigDomain": domain_pairs},
        "modules": {"repo1": modules_list},
    }


def _make_config_with_llm(decompose_result=None):
    """Create config with a mock LLM."""
    llm = AsyncMock()
    return {"configurable": {"llm": llm}}


class TestDetectOversizedLeaves:
    @pytest.mark.asyncio
    async def test_small_leaf_not_rebalanced(self):
        """Leaf with <= MAX_LEAF_MODULES (15) modules should not be rebalanced."""
        state = _make_state_with_large_leaf(module_count=10)

        mock_decomposer = MagicMock()
        mock_decomposer.decompose = AsyncMock()

        with patch("wiki.pipeline_nodes.HierarchicalDecomposer") as MockHD:
            MockHD.return_value = mock_decomposer
            # First call for main decomposition
            from wiki.dependency_graph import DomainNode
            mock_decomposer.decompose.return_value = [
                DomainNode(name="BigDomain", description="big", modules=[], children=[])
            ]

            config = _make_config_with_llm()
            result = await decompose_hierarchy_node(state, config)

        tree = result.get("domain_tree", [])
        assert len(tree) >= 1
        big = next((d for d in tree if d["name"] == "BigDomain"), None)
        assert big is not None
        assert big.get("children") == [] or not big.get("children")

    @pytest.mark.asyncio
    async def test_large_leaf_triggers_rebalance(self):
        """Leaf with > MAX_LEAF_MODULES (15) modules should trigger rebalance."""
        state = _make_state_with_large_leaf(module_count=20)

        from wiki.dependency_graph import DomainNode, ModuleInfo

        all_modules = [
            ModuleInfo(name=f"Module{i}", path=f"src/Module{i}.java", uid=f"Module::Module{i}:0")
            for i in range(20)
        ]

        # Main decomposition returns a single big leaf with all modules
        main_result = [
            DomainNode(
                name="BigDomain", description="big",
                modules=all_modules, children=[],
            )
        ]
        # Rebalance decomposition splits into 2 sub-domains
        sub_result = [
            DomainNode(name="SubA", description="sub a", modules=all_modules[:10], children=[]),
            DomainNode(name="SubB", description="sub b", modules=all_modules[10:], children=[]),
        ]

        call_count = {"n": 0}

        async def fake_decompose(mods, graph):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return main_result
            return sub_result

        with patch("wiki.pipeline_nodes.HierarchicalDecomposer") as MockHD:
            mock_instance = MagicMock()
            mock_instance.decompose = AsyncMock(side_effect=fake_decompose)
            MockHD.return_value = mock_instance

            config = _make_config_with_llm()
            result = await decompose_hierarchy_node(state, config)

        tree = result.get("domain_tree", [])
        big = next((d for d in tree if d["name"] == "BigDomain"), None)
        assert big is not None
        assert len(big.get("children", [])) == 2

    @pytest.mark.asyncio
    async def test_rebalance_failure_preserves_original(self):
        """If rebalance fails, keep the original oversized leaf unchanged."""
        state = _make_state_with_large_leaf(module_count=20)

        from wiki.dependency_graph import DomainNode, ModuleInfo

        all_modules = [
            ModuleInfo(name=f"Module{i}", path=f"src/Module{i}.java", uid=f"Module::Module{i}:0")
            for i in range(20)
        ]
        main_result = [
            DomainNode(name="BigDomain", description="big", modules=all_modules, children=[])
        ]

        call_count = {"n": 0}

        async def fake_decompose(mods, graph):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return main_result
            raise RuntimeError("LLM failure")

        with patch("wiki.pipeline_nodes.HierarchicalDecomposer") as MockHD:
            mock_instance = MagicMock()
            mock_instance.decompose = AsyncMock(side_effect=fake_decompose)
            MockHD.return_value = mock_instance

            config = _make_config_with_llm()
            result = await decompose_hierarchy_node(state, config)

        tree = result.get("domain_tree", [])
        big = next((d for d in tree if d["name"] == "BigDomain"), None)
        assert big is not None
        # Original structure preserved (no children added)
        assert big.get("children") == [] or not big.get("children")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_decompose_rebalance.py -v --no-cov`
Expected: FAIL — rebalance logic doesn't exist yet; `test_large_leaf_triggers_rebalance` will fail

- [ ] **Step 3: Implement oversized leaf detection and rebalance in decompose_hierarchy_node**

Modify `wiki/pipeline_nodes.py` — add helper before `decompose_hierarchy_node` and add post-processing inside it:

```python
# Add constant near the top of the file (after other constants)
_MAX_LEAF_MODULES = 15


def _collect_leaf_domains(domain_tree: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # ... existing function (already defined, keep as-is) ...


def _detect_oversized_leaves(domain_tree: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return leaf domains whose module count exceeds _MAX_LEAF_MODULES."""
    oversized: list[dict[str, Any]] = []
    for leaf in _collect_leaf_domains(domain_tree):
        modules = leaf.get("modules", [])
        if len(modules) > _MAX_LEAF_MODULES:
            oversized.append(leaf)
    return oversized
```

Inside `decompose_hierarchy_node`, after `domain_tree = _normalize_domain_tree(raw_tree)` (around line 331), add:

```python
    # P0.2 Sub-B+C: detect oversized leaves and rebalance
    oversized = _detect_oversized_leaves(domain_tree)
    if oversized and llm:
        rebalance_decomposer = HierarchicalDecomposer(llm, max_depth=1, min_modules_for_nesting=3)
        for leaf in oversized:
            leaf_module_names = set(leaf.get("modules", []))
            leaf_modules = [m for m in all_module_infos if m.name in leaf_module_names]
            if not leaf_modules:
                continue
            rebal_graph = ModuleGraph(modules=leaf_modules, edges=[], entry_points=[])
            try:
                sub_tree = await rebalance_decomposer.decompose(leaf_modules, rebal_graph)
                if sub_tree and len(sub_tree) > 1:
                    leaf["children"] = _normalize_domain_tree(sub_tree)
                    leaf["modules"] = []
                    log.info("leaf_rebalanced", domain=leaf.get("name"), sub_domains=len(sub_tree))
            except Exception:
                log.warning("leaf_rebalance_failed", domain=leaf.get("name"), exc_info=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_decompose_rebalance.py tests/wiki/test_pipeline_graph.py -v --no-cov`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add wiki/pipeline_nodes.py tests/wiki/test_decompose_rebalance.py
git commit -m "feat(wiki): add oversized leaf detection and secondary decomposition

P0.2 Sub-B+C: After initial hierarchy decomposition, detect leaf
domains with >15 modules and re-decompose them using
HierarchicalDecomposer(max_depth=1). Failure preserves original
structure. Only executes once (no recursive rebalancing)."
```

---

### Task 4: P0.1 — Incremental Generation Granularity (affected_domains)

**Files:**
- Modify: `wiki/cross_repo_domain_planner.py:174-295`
- Modify: `wiki/pipeline_nodes.py:87-228` (classify_domains_node)
- Modify: `wiki/pipeline_nodes.py:1650-1723` (compose_leaf_pages_node)
- Modify: `wiki/pipeline_nodes.py:669-730` (compose_parent_pages_node)
- Create: `tests/wiki/test_incremental_affected_domains.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/wiki/test_incremental_affected_domains.py
"""Tests for P0.1: incremental generation uses affected_domains to filter compose."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wiki.cross_repo_domain_planner import CrossRepoBusinessDomainPlanner


class TestClassifyIncrementalReturnsAffected:
    @pytest.mark.asyncio
    async def test_returns_tuple_with_affected_set(self):
        """classify_incremental should return (mapping, affected_domains)."""
        llm = AsyncMock()
        planner = CrossRepoBusinessDomainPlanner(llm)

        from store.schema import GraphNode, NodeLabel

        # Existing module with domain
        existing_mod = GraphNode(
            label=NodeLabel.MODULE,
            properties={"name": "OldService", "business_domain": "Payment"},
            uid="Module::OldService:0",
        )
        # New module without domain
        new_mod = GraphNode(
            label=NodeLabel.MODULE,
            properties={"name": "NewService"},
            uid="Module::NewService:0",
        )

        all_modules = {"repo1": [existing_mod, new_mod]}

        # Mock triage to assign new module to existing domain
        with patch.object(planner, "_triage_new_modules") as mock_triage:
            from wiki.cross_repo_domain_planner import _TriageResult
            mock_triage.return_value = _TriageResult(
                assignments={("repo1", "NewService"): "Payment"},
                new_domains={},
                reclassify_domains=[],
            )

            result = await planner.classify_incremental("biz1", all_modules)

        assert isinstance(result, tuple)
        assert len(result) == 2
        mapping, affected = result
        assert isinstance(mapping, dict)
        assert isinstance(affected, set)
        assert "Payment" in affected

    @pytest.mark.asyncio
    async def test_no_new_modules_returns_empty_affected(self):
        """When no new modules, affected_domains should be empty."""
        llm = AsyncMock()
        planner = CrossRepoBusinessDomainPlanner(llm)

        from store.schema import GraphNode, NodeLabel

        existing_mod = GraphNode(
            label=NodeLabel.MODULE,
            properties={"name": "OldService", "business_domain": "Payment"},
            uid="Module::OldService:0",
        )

        result = await planner.classify_incremental("biz1", {"repo1": [existing_mod]})

        assert isinstance(result, tuple)
        mapping, affected = result
        assert affected == set()

    @pytest.mark.asyncio
    async def test_new_domain_in_affected(self):
        """New domains created during triage should be in affected set."""
        llm = AsyncMock()
        planner = CrossRepoBusinessDomainPlanner(llm)

        from store.schema import GraphNode, NodeLabel

        new_mod = GraphNode(
            label=NodeLabel.MODULE,
            properties={"name": "BrandNew"},
            uid="Module::BrandNew:0",
        )

        with patch.object(planner, "_triage_new_modules") as mock_triage:
            from wiki.cross_repo_domain_planner import _TriageResult
            mock_triage.return_value = _TriageResult(
                assignments={},
                new_domains={"NewDomain": [("repo1", "BrandNew")]},
                reclassify_domains=[],
            )

            result = await planner.classify_incremental("biz1", {"repo1": [new_mod]})

        mapping, affected = result
        assert "NewDomain" in affected


class TestComposeLeafPagesFiltering:
    """compose_leaf_pages_node should skip unaffected domains in light reorg."""

    @pytest.mark.asyncio
    async def test_light_reorg_filters_by_affected(self):
        from wiki.pipeline_nodes import compose_leaf_pages_node

        state = {
            "domain_tree": [
                {"name": "Payment", "modules": ["PaySvc"], "children": []},
                {"name": "Meeting", "modules": ["MeetSvc"], "children": []},
            ],
            "domain_mapping": {
                "Payment": [("r", "PaySvc")],
                "Meeting": [("r", "MeetSvc")],
            },
            "modules": {"r": [
                {"uid": "m1", "label": "Module", "properties": {"name": "PaySvc", "path": "a.java"}},
                {"uid": "m2", "label": "Module", "properties": {"name": "MeetSvc", "path": "b.java"}},
            ]},
            "entity_roles": {},
            "module_summaries": {},
            "reorg_type": "light",
            "affected_domains": ["Payment"],
        }

        config = {"configurable": {"llm": AsyncMock(), "graph_store": None, "wiki_store": None}}

        with patch("wiki.pipeline_nodes._compose_single_leaf_domain") as mock_compose:
            mock_compose.return_value = ([], [])
            result = await compose_leaf_pages_node(state, config)

        # Only Payment domain should have been composed
        composed_domains = [call.args[0]["name"] for call in mock_compose.call_args_list]
        assert "Payment" in composed_domains
        assert "Meeting" not in composed_domains
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_incremental_affected_domains.py -v --no-cov`
Expected: FAIL — `classify_incremental` returns dict not tuple; compose doesn't filter

- [ ] **Step 3: Modify classify_incremental to return tuple**

In `wiki/cross_repo_domain_planner.py`, change the return type and early returns:

Change the method signature (line 174):
```python
    async def classify_incremental(
        self,
        business_id: str,
        all_modules: dict[str, list[GraphNode]],
    ) -> tuple[dict[str, list[tuple[str, str]]], set[str]]:
```

Change the early return when no new modules (line ~214):
```python
            return existing, set()
```

Change the fallback return when llm is None (line ~226):
```python
            existing.setdefault(self._infrastructure_label, []).extend(new_pairs)
            return existing, {self._infrastructure_label}
```

Change the fallback return after triage failure (line ~249):
```python
            existing.setdefault(self._infrastructure_label, []).extend(new_pairs)
            return existing, {self._infrastructure_label}
```

After triage assignments are applied (~line 253-264), compute affected set:
```python
        affected: set[str] = set()
        for pair, domain in triage.assignments.items():
            existing.setdefault(domain, []).append(pair)
            affected.add(domain)

        for domain_name, pairs in triage.new_domains.items():
            existing.setdefault(domain_name, []).extend(pairs)
            affected.add(domain_name)

        if not triage.reclassify_domains:
            return existing, affected
```

After reclassification completes (~line 289-295):
```python
        if reclassified is not None:
            for domain_name in triage.reclassify_domains:
                existing.pop(domain_name, None)
                affected.add(domain_name)
            for domain_name, pairs in reclassified.items():
                existing.setdefault(domain_name, []).extend(pairs)
                affected.add(domain_name)
        else:
            affected.update(triage.reclassify_domains)

        return existing, affected
```

- [ ] **Step 4: Update classify_domains_node to consume new return type**

In `wiki/pipeline_nodes.py`, modify `classify_domains_node` (around line 199-228):

```python
    if is_incremental:
        domain_mapping, affected_domains = await planner.classify_incremental(business_id, biz_modules)
    else:
        domain_mapping = await planner.classify(business_id, biz_modules)
        affected_domains = set(domain_mapping.keys())
```

And update the return statement (around line 228):
```python
    return {"domain_mapping": domain_mapping, "affected_domains": list(affected_domains)}
```

- [ ] **Step 5: Update compose_leaf_pages_node to filter by affected_domains**

In `wiki/pipeline_nodes.py`, inside `compose_leaf_pages_node` (after `leaf_domains = _collect_leaf_domains(domain_tree)` around line 1692):

```python
    # P0.1: Filter leaf domains based on incremental affected_domains
    reorg_type = state.get("reorg_type", "full")
    affected_domains = set(state.get("affected_domains", []))

    if reorg_type == "light" and affected_domains:
        leaf_domains = [d for d in leaf_domains if d.get("name") in affected_domains]
    elif reorg_type == "none":
        log.info("compose_leaf_pages_skip_none_reorg")
        return {"pages": [], "generated_topic_pages": []}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_incremental_affected_domains.py tests/wiki/test_classify_domains_node.py tests/wiki/test_compose_pages_node.py -v --no-cov`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add wiki/cross_repo_domain_planner.py wiki/pipeline_nodes.py tests/wiki/test_incremental_affected_domains.py
git commit -m "feat(wiki): implement affected_domains for incremental generation granularity

P0.1: classify_incremental now returns (mapping, affected_domains).
classify_domains_node writes affected_domains to state.
compose_leaf_pages_node filters by affected_domains when reorg_type
is 'light', skipping unchanged domains to avoid wasteful LLM calls."
```

---

## Batch 3 (Sequential — depends on Batch 1)

### Task 5: P1.4 — Cross-Page Awareness (read_wiki_page tool)

**Files:**
- Modify: `wiki/page_agent.py`
- Create: `tests/wiki/test_read_wiki_page_tool.py`

- [ ] **Step 1: Write failing tests for read_wiki_page**

```python
# tests/wiki/test_read_wiki_page_tool.py
"""Tests for P1.4: read_wiki_page tool implementation in WikiPageAgent."""

from __future__ import annotations

import pytest

from wiki.page_agent import WikiPageAgent


class TestReadWikiPageTool:
    def _make_agent(self, existing_pages=None):
        from unittest.mock import AsyncMock
        llm = AsyncMock()
        graph_store = AsyncMock()
        agent = WikiPageAgent(llm, graph_store)
        return agent

    def test_search_existing_pages_by_keyword(self):
        """read_wiki_page should find pages from existing_pages list by title keyword."""
        from wiki.page_agent import WikiPageAgent

        existing_pages = [
            {"path": "/wiki/payment/overview", "title": "Payment Overview", "content": "Payment handles..."},
            {"path": "/wiki/meeting/overview", "title": "Meeting Overview", "content": "Meeting handles..."},
        ]

        agent = self._make_agent()
        result = agent._read_wiki_page("payment", existing_pages=existing_pages)
        assert result is not None
        assert "Payment" in result

    def test_returns_none_for_no_match(self):
        """read_wiki_page returns None when no page matches."""
        existing_pages = [
            {"path": "/wiki/payment/overview", "title": "Payment Overview", "content": "..."},
        ]

        agent = self._make_agent()
        result = agent._read_wiki_page("nonexistent", existing_pages=existing_pages)
        assert result is None

    def test_truncates_long_content(self):
        """read_wiki_page truncates content exceeding SINGLE_RESULT_LIMIT."""
        long_content = "x" * 5000
        existing_pages = [
            {"path": "/wiki/big", "title": "Big Page", "content": long_content},
        ]

        agent = self._make_agent()
        result = agent._read_wiki_page("big", existing_pages=existing_pages)
        assert result is not None
        assert len(result) <= 4200  # SINGLE_RESULT_LIMIT + some header
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_read_wiki_page_tool.py -v --no-cov`
Expected: FAIL — `_read_wiki_page` method doesn't exist

- [ ] **Step 3: Implement _read_wiki_page in WikiPageAgent**

Add to `wiki/page_agent.py`:

```python
    _SINGLE_RESULT_LIMIT = 4000

    def _read_wiki_page(
        self,
        query: str,
        *,
        existing_pages: list[dict] | None = None,
    ) -> str | None:
        """Search existing pages by title/path keyword. Returns content or None."""
        if not existing_pages:
            return None

        query_lower = query.lower().strip()
        if not query_lower:
            return None

        for page in existing_pages:
            title = str(page.get("title", "")).lower()
            path = str(page.get("path", "")).lower()
            if query_lower in title or query_lower in path:
                content = str(page.get("content", ""))
                header = f"# {page.get('title', 'Untitled')}\nPath: {page.get('path', '')}\n\n"
                full = header + content
                if len(full) > self._SINGLE_RESULT_LIMIT:
                    return full[: self._SINGLE_RESULT_LIMIT - 3] + "..."
                return full

        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_read_wiki_page_tool.py tests/wiki/test_page_agent.py -v --no-cov`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add wiki/page_agent.py tests/wiki/test_read_wiki_page_tool.py
git commit -m "feat(wiki): implement read_wiki_page tool for cross-page awareness

P1.4: WikiPageAgent._read_wiki_page searches existing_pages by title/
path keyword. Returns truncated content (max 4000 chars) or None.
Prioritizes in-memory pipeline pages over graph queries."
```

---

### Task 6: P1.5 — Parent Domain Cross-Domain Call Information

**Files:**
- Modify: `wiki/pipeline_nodes.py` (compose_parent_pages_node, ~line 669-730)
- Modify: `wiki/pipeline_nodes.py` (_compose_single_leaf_domain, ~line 981)
- Create: `tests/wiki/test_parent_cross_domain.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/wiki/test_parent_cross_domain.py
"""Tests for P1.5: parent domain aggregation includes cross-domain call info."""

from __future__ import annotations

import pytest


class TestCrossDomainMetadataInPages:
    def test_page_dict_contains_cross_domain_metadata(self):
        """After compose, page_dict metadata should contain cross_domain_calls."""
        page_dict = {
            "path": "/wiki/payment/overview",
            "title": "Payment",
            "content": "...",
            "metadata": {
                "cross_domain_calls": [
                    {"from": "PaymentService", "to": "NotificationService", "to_domain": "Notification"},
                ]
            },
        }
        calls = page_dict["metadata"]["cross_domain_calls"]
        assert len(calls) == 1
        assert calls[0]["to_domain"] == "Notification"

    def test_build_subdomain_interaction_text(self):
        """Helper should build structured interaction text from child pages."""
        from wiki.pipeline_nodes import _build_subdomain_interactions

        child_pages = [
            {
                "title": "Payment",
                "metadata": {
                    "domain_name": "Payment",
                    "cross_domain_calls": [
                        {"from": "PaySvc", "to": "NotifySvc", "to_domain": "Notification"},
                        {"from": "PaySvc", "to": "OrderSvc", "to_domain": "Order"},
                    ],
                },
            },
            {
                "title": "Order",
                "metadata": {
                    "domain_name": "Order",
                    "cross_domain_calls": [
                        {"from": "OrderSvc", "to": "PaySvc", "to_domain": "Payment"},
                    ],
                },
            },
        ]

        result = _build_subdomain_interactions(child_pages)
        assert isinstance(result, str)
        assert "Payment" in result
        assert "Notification" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_parent_cross_domain.py -v --no-cov`
Expected: FAIL — `_build_subdomain_interactions` doesn't exist

- [ ] **Step 3: Implement _build_subdomain_interactions helper**

Add to `wiki/pipeline_nodes.py` (near other helper functions):

```python
def _build_subdomain_interactions(child_pages: list[dict[str, Any]]) -> str:
    """Build a text description of interactions between child sub-domains.

    Aggregates cross_domain_calls metadata from child page dicts into a
    structured summary for parent domain overview generation.
    """
    interactions: list[str] = []
    for page in child_pages:
        meta = page.get("metadata", {})
        if not isinstance(meta, dict):
            continue
        domain_name = meta.get("domain_name", page.get("title", ""))
        calls = meta.get("cross_domain_calls", [])
        if not calls:
            continue
        targets: dict[str, list[str]] = {}
        for call in calls:
            to_domain = call.get("to_domain", "")
            method = f"{call.get('from', '?')}.{call.get('from_method', '?')}"
            if to_domain:
                targets.setdefault(to_domain, []).append(call.get("to", ""))
        for target_domain, callees in targets.items():
            unique_callees = list(dict.fromkeys(callees))[:3]
            interactions.append(f"- {domain_name} → {target_domain}: {', '.join(unique_callees)}")

    if not interactions:
        return ""
    return "## Sub-domain Interactions\n" + "\n".join(interactions[:20])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_parent_cross_domain.py -v --no-cov`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add wiki/pipeline_nodes.py tests/wiki/test_parent_cross_domain.py
git commit -m "feat(wiki): add cross-domain call info to parent domain aggregation

P1.5: _build_subdomain_interactions extracts cross_domain_calls from
child page metadata and builds a structured interaction description
for parent domain overview generation prompts."
```

---

## Batch 4 (Refactoring — after functional changes are stable)

### Task 7: P2.6 — Split pipeline_nodes.py into wiki/nodes/ directory

**Files:**
- Create: `wiki/nodes/__init__.py`
- Create: `wiki/nodes/classify.py`
- Create: `wiki/nodes/compose.py`
- Create: `wiki/nodes/aggregate.py`
- Create: `wiki/nodes/heal.py`
- Create: `wiki/nodes/links.py`
- Create: `wiki/nodes/utils.py`
- Modify: `wiki/pipeline_nodes.py` (replace with re-export stub)

- [ ] **Step 1: Run all existing tests to establish baseline**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/ -x --timeout=120 --no-cov -q 2>&1 | tail -20`
Expected: Record pass/fail count as baseline

- [ ] **Step 2: Create wiki/nodes/ directory structure**

```bash
mkdir -p /Users/earthchen/ai-work/agent-work/knowledge-base-service/wiki/nodes
```

- [ ] **Step 3: Extract utils.py (shared helpers)**

Move all helper functions (`_normalize_domain_tree`, `_collect_leaf_domains`, `_collect_parent_domains_by_level`, `_collect_module_names_in_subtree`, `_module_dicts_for_names`, `_call_target_module`, `_build_page_data_for_semantic_diagrams`, `_detect_oversized_leaves`, `_build_subdomain_interactions`, etc.) from `wiki/pipeline_nodes.py` to `wiki/nodes/utils.py`.

Keep imports consistent — `utils.py` should import from `wiki.*` modules the same way the original file does.

- [ ] **Step 4: Extract classify.py (classification nodes)**

Move `classify_entities_node`, `classify_domains_node`, `decompose_hierarchy_node`, `detect_reorg_node`, `set_review_status_node` to `wiki/nodes/classify.py`.

Import helpers from `wiki.nodes.utils`.

- [ ] **Step 5: Extract compose.py (composition nodes)**

Move `compose_leaf_modules_node`, `compose_leaf_pages_node`, `_compose_single_leaf_domain`, `_compose_from_topic_structure` to `wiki/nodes/compose.py`.

- [ ] **Step 6: Extract aggregate.py (aggregation nodes)**

Move `compose_parent_pages_node`, `summarize_leaves_node`, `synthesize_overviews_node` to `wiki/nodes/aggregate.py`.

- [ ] **Step 7: Extract heal.py and links.py**

Move `heal_pages_node` to `wiki/nodes/heal.py`.
Move `create_links_node` to `wiki/nodes/links.py`.

- [ ] **Step 8: Create wiki/nodes/__init__.py with re-exports**

```python
"""Wiki pipeline nodes — split by responsibility for maintainability."""

from wiki.nodes.classify import (
    classify_domains_node,
    classify_entities_node,
    decompose_hierarchy_node,
    detect_reorg_node,
    set_review_status_node,
)
from wiki.nodes.compose import (
    compose_leaf_modules_node,
    compose_leaf_pages_node,
)
from wiki.nodes.aggregate import (
    compose_parent_pages_node,
    summarize_leaves_node,
    synthesize_overviews_node,
)
from wiki.nodes.heal import heal_pages_node
from wiki.nodes.links import create_links_node
from wiki.nodes.utils import (
    _build_subdomain_interactions,
    _collect_leaf_domains,
    _detect_oversized_leaves,
    _normalize_domain_tree,
    has_parent_domains,
)

__all__ = [
    "classify_domains_node",
    "classify_entities_node",
    "compose_leaf_modules_node",
    "compose_leaf_pages_node",
    "compose_parent_pages_node",
    "create_links_node",
    "decompose_hierarchy_node",
    "detect_reorg_node",
    "heal_pages_node",
    "set_review_status_node",
    "summarize_leaves_node",
    "synthesize_overviews_node",
]
```

- [ ] **Step 9: Replace wiki/pipeline_nodes.py with re-export stub**

```python
"""Pipeline nodes (backward-compatible re-export).

All node implementations now live in wiki/nodes/.
This file exists purely for import compatibility.
"""

from wiki.nodes import *  # noqa: F401, F403
from wiki.nodes.utils import *  # noqa: F401, F403
```

- [ ] **Step 10: Run all tests to verify refactor is behavior-preserving**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/ -x --timeout=120 --no-cov -q 2>&1 | tail -20`
Expected: Same pass/fail count as baseline from Step 1

- [ ] **Step 11: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add wiki/nodes/ wiki/pipeline_nodes.py
git commit -m "refactor(wiki): split pipeline_nodes.py into wiki/nodes/ directory

P2.6: Extract ~2000 line monolith into focused modules:
- classify.py: entity/domain classification + reorg detection
- compose.py: leaf module/page composition
- aggregate.py: parent pages, summaries, overviews
- heal.py: quality healing
- links.py: link creation
- utils.py: shared helpers

Original pipeline_nodes.py preserved as re-export for compatibility."
```

---

### Task 8: P2.7+2.8 — Simplify Legacy Path + Extract Diagram Logic

**Files:**
- Modify: `wiki/nodes/compose.py` (after Task 7)

- [ ] **Step 1: Run compose-related tests as baseline**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_compose_pages_node.py tests/wiki/test_compose_pages_diagrams.py tests/wiki/test_compose_pages_calls.py -v --no-cov`
Expected: Record baseline

- [ ] **Step 2: Extract _post_process_pages helper function**

In `wiki/nodes/compose.py`, extract the common post-processing logic (diagram generation, sanitize, agent enrichment) from `_compose_single_leaf_domain` into a new function:

```python
async def _post_process_pages(
    pages: list[dict[str, Any]],
    llm: Any,
    graph_store: Any | None,
    domain_name: str,
    module_names: list[str],
    module_index: dict[str, list[dict]],
    known_entities: set[str],
    context: Any | None = None,
) -> list[dict[str, Any]]:
    """Common post-processing: diagrams → sanitize → agent enrichment."""
    # Diagram generation
    pages = await _generate_diagrams_for_pages(pages, llm, domain_name, module_names, module_index)
    # Sanitize
    pages = _sanitize_pages(pages, known_entities)
    # Agent enrichment (if graph_store available)
    if graph_store and context:
        pages = await _enrich_pages_with_agent(pages, llm, graph_store, domain_name, context)
    return pages
```

- [ ] **Step 3: Simplify legacy fallback path**

In `_compose_single_leaf_domain`, reduce the legacy path to minimal generation:

```python
    if pages is None:
        pages = await _compose_legacy_fallback(leaf, module_index, entity_roles, llm, budget)
        # Legacy path: only basic sanitize, no diagrams or agent enrichment
        pages = _sanitize_pages(pages, known_entities)
        return pages, generated_uids
```

- [ ] **Step 4: Run tests to verify refactor is behavior-preserving**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_compose_pages_node.py tests/wiki/test_compose_pages_diagrams.py tests/wiki/test_compose_pages_calls.py -v --no-cov`
Expected: Same results as baseline

- [ ] **Step 5: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add wiki/nodes/compose.py
git commit -m "refactor(wiki): extract _post_process_pages and simplify legacy fallback

P2.7+2.8: Common post-processing (diagrams, sanitize, agent enrichment)
now lives in _post_process_pages(). Legacy path does minimal generation
without diagrams or agent enrichment — reducing maintenance surface."
```

---

## Code Review Checkpoints

After each batch, dispatch a code-reviewer subagent to review:

1. **After Batch 1:** Review P0.2 Sub-A and P1.3 for correctness, edge cases, and test quality
2. **After Batch 2:** Review P0.2 Sub-B+C and P0.1 for integration correctness and state propagation
3. **After Batch 3:** Review P1.4 and P1.5 for API consistency with existing page_agent
4. **After Batch 4:** Review P2.6 and P2.7+2.8 for import correctness and backward compatibility

---

## Verification Strategy

After all tasks complete:

```bash
# Full test suite
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
uv run pytest tests/wiki/ --timeout=120 -q

# Ruff lint check
uv run ruff check wiki/ tests/wiki/

# Verify no import breaks
uv run python -c "from wiki.pipeline_nodes import classify_domains_node, compose_leaf_pages_node, compose_parent_pages_node"
```

---

## Notes for Subagent Workers

1. **Test framework:** pytest + pytest-asyncio with `asyncio_mode = "auto"`. No need for explicit `@pytest.mark.asyncio` on most tests.
2. **Run command:** Always use `uv run pytest` (not `pytest` directly).
3. **Coverage:** Skip coverage for individual tasks with `--no-cov` flag. Full coverage check at the end.
4. **Mocking:** Use `unittest.mock.AsyncMock` for LLM and graph_store dependencies.
5. **Import style:** The project uses relative imports within `wiki/` package. Follow existing patterns.
6. **Logging:** Use `from core.log import get_logger; log = get_logger(__name__)`.
