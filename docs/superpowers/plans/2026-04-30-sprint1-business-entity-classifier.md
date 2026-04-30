# Sprint 1: Business Management + Entity Role Classifier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Business CRUD management, EntityRoleClassifier (two-phase entity classification), and integrate into the LangGraph pipeline skeleton to reduce wiki page count from ~967 to ~40-80 topic pages.

**Architecture:** New `EntityRoleClassifier` uses deterministic rules (Phase 1) + business logic density scoring (Phase 2) to classify entities into HAS_BUSINESS_LOGIC / SUPPORTING / DATA_MODEL / FRAMEWORK_NOISE. Business CRUD API forces users to manually create Business and bind repositories. Existing LangGraph pipeline stubs are filled with real logic.

**Tech Stack:** Python 3.11, FastAPI, FalkorDB (graph DB), LangGraph, pytest

**Spec:** `docs/superpowers/specs/PROPOSAL_20260430_145217_business-domain-wiki-tree.md` (Section 3.2, 3.5, Sprint 1)

---

## Task 1: WikiEntityRole Enum + EntityRoleClassifier

**Files:**
- Create: `wiki/entity_role_classifier.py`
- Test: `tests/wiki/test_entity_role_classifier.py`

- [ ] **Step 1: Write the failing tests for EntityRoleClassifier**

```python
# tests/wiki/test_entity_role_classifier.py
from __future__ import annotations

import pytest
from store.schema import GraphNode, NodeLabel
from wiki.entity_role_classifier import EntityRoleClassifier, WikiEntityRole


def _node(
    name: str,
    label: NodeLabel = NodeLabel.MODULE,
    *,
    annotations: list[str] | None = None,
    methods_count: int = 0,
    start_line: int = 0,
    end_line: int = 50,
    semantic_roles: list[str] | None = None,
    is_interface: bool = False,
    is_enum: bool = False,
) -> GraphNode:
    props: dict = {
        "name": name,
        "methods_count": methods_count,
        "start_line": start_line,
        "end_line": end_line,
        "is_interface": is_interface,
        "is_enum": is_enum,
    }
    if annotations:
        props["annotations"] = annotations
    if semantic_roles:
        props["semantic_roles"] = semantic_roles
    return GraphNode(label=label, properties=props, uid=f"Module::{name}:0")


class TestPhase1DeterministicRules:
    """Phase 1: deterministic fast-path rules."""

    def test_data_annotation_is_data_model(self):
        node = _node("UserDTO", annotations=["@Data"], methods_count=1)
        c = EntityRoleClassifier()
        assert c.classify(node, edge_count=0, children_count=0) == WikiEntityRole.DATA_MODEL

    def test_dto_suffix_is_data_model(self):
        node = _node("PaymentRequestDTO", methods_count=5)
        c = EntityRoleClassifier()
        assert c.classify(node, edge_count=3, children_count=2) == WikiEntityRole.DATA_MODEL

    def test_enum_is_data_model(self):
        node = _node("StatusEnum", is_enum=True, methods_count=0)
        c = EntityRoleClassifier()
        assert c.classify(node, edge_count=0, children_count=0) == WikiEntityRole.DATA_MODEL

    def test_empty_shell_is_noise(self):
        node = _node("EmptyConfig", methods_count=0, start_line=0, end_line=5)
        c = EntityRoleClassifier()
        assert c.classify(node, edge_count=0, children_count=0) == WikiEntityRole.FRAMEWORK_NOISE

    def test_pure_config_class_is_noise(self):
        node = _node("AppConfig", annotations=["@Configuration"], methods_count=0)
        c = EntityRoleClassifier()
        assert c.classify(node, edge_count=0, children_count=0) == WikiEntityRole.FRAMEWORK_NOISE


class TestPhase2ScoringModel:
    """Phase 2: business logic density scoring for entities not caught by Phase 1."""

    def test_controller_with_methods_is_business_logic(self):
        node = _node(
            "PaymentController",
            annotations=["@RestController"],
            methods_count=8,
            semantic_roles=["http_controller"],
            start_line=0,
            end_line=200,
        )
        c = EntityRoleClassifier()
        result = c.classify(node, edge_count=15, children_count=5)
        assert result == WikiEntityRole.HAS_BUSINESS_LOGIC

    def test_service_with_calls_is_business_logic(self):
        node = _node(
            "OrderService",
            annotations=["@Service"],
            methods_count=10,
            start_line=0,
            end_line=300,
        )
        c = EntityRoleClassifier()
        result = c.classify(node, edge_count=20, children_count=3)
        assert result == WikiEntityRole.HAS_BUSINESS_LOGIC

    def test_low_score_entity_is_supporting(self):
        node = _node(
            "HelperUtil",
            methods_count=3,
            start_line=0,
            end_line=40,
        )
        c = EntityRoleClassifier()
        result = c.classify(node, edge_count=2, children_count=0)
        assert result == WikiEntityRole.SUPPORTING

    def test_minimal_methods_no_role_is_data_model(self):
        node = _node(
            "SimpleWrapper",
            methods_count=1,
            start_line=0,
            end_line=15,
        )
        c = EntityRoleClassifier()
        result = c.classify(node, edge_count=0, children_count=0)
        assert result == WikiEntityRole.DATA_MODEL


class TestScoreComputation:
    """Verify the raw score computation."""

    def test_score_method(self):
        node = _node(
            "SomeService",
            annotations=["@Service"],
            methods_count=6,
            start_line=0,
            end_line=150,
        )
        c = EntityRoleClassifier()
        score = c.compute_score(node, edge_count=10, children_count=2)
        assert 0 <= score <= 100
        assert score >= 40  # should qualify as HAS_BUSINESS_LOGIC
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_entity_role_classifier.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'wiki.entity_role_classifier'`

- [ ] **Step 3: Implement EntityRoleClassifier**

```python
# wiki/entity_role_classifier.py
"""Two-phase entity role classifier for Wiki generation.

Phase 1: Deterministic rules (fast path) — name patterns, annotations, trivial checks.
Phase 2: Business logic density scoring — weighted score across 4 dimensions.
"""
from __future__ import annotations

import re
from enum import StrEnum

from store.schema import GraphNode
from log import get_logger

log = get_logger(__name__)


class WikiEntityRole(StrEnum):
    HAS_BUSINESS_LOGIC = "has_business_logic"
    SUPPORTING = "supporting"
    DATA_MODEL = "data_model"
    FRAMEWORK_NOISE = "framework_noise"


_DATA_SUFFIXES = re.compile(
    r"(DTO|VO|PO|Bo|Param|Request|Response|Entity|Form|Query|Result)$",
    re.IGNORECASE,
)
_DATA_ANNOTATIONS = frozenset({
    "Data", "Value", "Builder", "Getter", "Setter", "AllArgsConstructor",
    "NoArgsConstructor", "ToString", "EqualsAndHashCode",
})
_NOISE_ONLY_ANNOTATIONS = frozenset({
    "Component", "Configuration", "EnableAutoConfiguration",
    "SpringBootApplication", "EnableDiscoveryClient",
})
_BIZ_ROLE_ANNOTATIONS = frozenset({
    "RestController", "Controller", "Service", "KafkaListener",
    "RabbitListener", "Scheduled",
})
_REPO_ANNOTATIONS = frozenset({"Repository", "Mapper"})
_CORE_SEMANTIC_ROLES = frozenset({
    "http_controller", "rpc_provider", "message_listener",
})


def _simplify_annotations(raw: list[str] | None) -> set[str]:
    if not raw:
        return set()
    return {a.lstrip("@").split("(")[0].rsplit(".", 1)[-1] for a in raw}


class EntityRoleClassifier:
    SCORE_THRESHOLD_BIZ = 40
    SCORE_THRESHOLD_SUPPORTING = 15

    def classify(
        self,
        node: GraphNode,
        *,
        edge_count: int = 0,
        children_count: int = 0,
    ) -> WikiEntityRole:
        phase1 = self._phase1_deterministic(node, edge_count)
        if phase1 is not None:
            return phase1
        score = self.compute_score(node, edge_count=edge_count, children_count=children_count)
        if score >= self.SCORE_THRESHOLD_BIZ:
            return WikiEntityRole.HAS_BUSINESS_LOGIC
        if score >= self.SCORE_THRESHOLD_SUPPORTING:
            return WikiEntityRole.SUPPORTING
        return WikiEntityRole.DATA_MODEL

    def compute_score(
        self,
        node: GraphNode,
        *,
        edge_count: int = 0,
        children_count: int = 0,
    ) -> float:
        props = node.properties
        methods_count = int(props.get("methods_count", 0) or 0)
        start = int(props.get("start_line", 0) or 0)
        end = int(props.get("end_line", 0) or 0)
        loc = max(end - start, 0)
        annotations = _simplify_annotations(props.get("annotations"))
        roles_raw = props.get("semantic_roles", [])
        roles = set(roles_raw) if isinstance(roles_raw, list) else set()

        effective_methods = max(methods_count - self._estimate_getters(node), 0)
        dim_methods = min(effective_methods / 5.0, 1.0) * 35
        dim_graph = min(edge_count / 20.0, 1.0) * 25
        dim_role = self._score_semantic_role(annotations, roles, methods_count)
        dim_loc = min(loc / 200.0, 1.0) * 15

        return dim_methods + dim_graph + dim_role + dim_loc

    def _phase1_deterministic(
        self, node: GraphNode, edge_count: int,
    ) -> WikiEntityRole | None:
        props = node.properties
        name = str(props.get("name", ""))
        methods_count = int(props.get("methods_count", 0) or 0)
        start = int(props.get("start_line", 0) or 0)
        end = int(props.get("end_line", 0) or 0)
        loc = max(end - start, 0)
        is_enum = bool(props.get("is_enum", False))
        annotations = _simplify_annotations(props.get("annotations"))

        if annotations & _DATA_ANNOTATIONS and methods_count <= 3:
            return WikiEntityRole.DATA_MODEL
        if _DATA_SUFFIXES.search(name):
            return WikiEntityRole.DATA_MODEL
        if is_enum or name.endswith("Enum") or name.endswith("Constants"):
            return WikiEntityRole.DATA_MODEL
        implements = props.get("implements", [])
        if isinstance(implements, list) and "Serializable" in implements and methods_count == 0:
            return WikiEntityRole.DATA_MODEL
        if loc < 10 and methods_count == 0 and edge_count == 0:
            return WikiEntityRole.FRAMEWORK_NOISE
        if annotations and annotations <= _NOISE_ONLY_ANNOTATIONS and methods_count == 0:
            return WikiEntityRole.FRAMEWORK_NOISE
        return None

    @staticmethod
    def _estimate_getters(node: GraphNode) -> int:
        annotations = _simplify_annotations(node.properties.get("annotations"))
        if annotations & {"Data", "Getter", "Setter"}:
            return int(node.properties.get("methods_count", 0) or 0) // 2
        return 0

    @staticmethod
    def _score_semantic_role(
        annotations: set[str], roles: set[str], methods_count: int,
    ) -> float:
        if roles & _CORE_SEMANTIC_ROLES:
            return 25.0
        if annotations & _BIZ_ROLE_ANNOTATIONS:
            return 20.0
        if annotations & _REPO_ANNOTATIONS:
            return 15.0
        if "Component" in annotations and methods_count > 3:
            return 10.0
        if methods_count > 0:
            return 5.0
        return 0.0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_entity_role_classifier.py -v`
Expected: All 9 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add wiki/entity_role_classifier.py tests/wiki/test_entity_role_classifier.py
git commit -m "feat(wiki): add EntityRoleClassifier with two-phase classification

Phase 1: deterministic rules for DATA_MODEL and FRAMEWORK_NOISE
Phase 2: business logic density scoring (methods, graph, roles, loc)"
```

---

## Task 2: Extend WikiPipelineState

**Files:**
- Modify: `wiki/pipeline_state.py`
- Test: `tests/wiki/test_pipeline_state_extension.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/wiki/test_pipeline_state_extension.py
from __future__ import annotations

from wiki.pipeline_state import WikiPipelineState


def test_new_fields_exist_in_typeddict():
    """Verify WikiPipelineState has the new fields from the proposal."""
    hints = WikiPipelineState.__annotations__
    assert "entity_roles" in hints
    assert "role_stats" in hints
    assert "is_incremental" in hints
    assert "reorg_type" in hints
    assert "affected_domains" in hints
    assert "review_status" in hints
    assert "review_notes" in hints
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_pipeline_state_extension.py -v`
Expected: FAIL — `AssertionError` for missing fields

- [ ] **Step 3: Add new fields to WikiPipelineState**

Add the following fields to `wiki/pipeline_state.py` after the existing `errors` field:

```python
    # --- Entity classification (Phase 1) ---
    entity_roles: dict[str, str]
    role_stats: dict[str, int]

    # --- Incremental / reorg ---
    is_incremental: bool
    reorg_type: str
    affected_domains: list[str]

    # --- Review tracking ---
    review_status: dict[str, str]
    review_notes: dict[str, str]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_pipeline_state_extension.py -v`
Expected: PASS

- [ ] **Step 5: Verify existing tests still pass**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_checkpoint_config.py tests/wiki/test_quality_loop.py -v`
Expected: All PASS (new optional fields should not break existing usage)

- [ ] **Step 6: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add wiki/pipeline_state.py tests/wiki/test_pipeline_state_extension.py
git commit -m "feat(wiki): extend WikiPipelineState with entity classification and review fields"
```

---

## Task 3: Extend TokenBudgetResolver RATIOS

**Files:**
- Modify: `wiki/token_budget.py`
- Modify: `tests/wiki/test_token_budget.py`

- [ ] **Step 1: Write the failing test**

Add to existing `tests/wiki/test_token_budget.py`:

```python
def test_pipeline_component_ratios():
    """New pipeline components should have budget ratios."""
    r = TokenBudgetResolver(base=30_000)
    assert r.budget("domain_classify") == 15_000
    assert r.budget("domain_merge") == 6_000
    assert r.budget("domain_tree_plan") == 4_500
    assert r.budget("topic_page_generate") == 18_000
    assert r.budget("domain_overview") == 9_000
    assert r.budget("system_overview") == 7_500
    assert r.budget("entity_group") == 6_000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_token_budget.py::test_pipeline_component_ratios -v`
Expected: FAIL — budget values don't match (fallback to default 0.27 ratio)

- [ ] **Step 3: Add pipeline component ratios to TokenBudgetResolver**

Add to `wiki/token_budget.py` `RATIOS` dict:

```python
    RATIOS: dict[str, float] = {
        "decomposition": 1.0,
        "ask_concept": 0.33,
        "ask_flow": 0.40,
        "ask_relation": 0.27,
        "ask_impact": 0.33,
        "ask_general": 0.27,
        "compact": 0.13,
        "assembly": 0.27,
        "domain_classify": 0.50,
        "domain_merge": 0.20,
        "domain_tree_plan": 0.15,
        "topic_page_generate": 0.60,
        "domain_overview": 0.30,
        "system_overview": 0.25,
        "entity_group": 0.20,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_token_budget.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add wiki/token_budget.py tests/wiki/test_token_budget.py
git commit -m "feat(wiki): add pipeline component ratios to TokenBudgetResolver"
```

---

## Task 4: Business CRUD API

**Files:**
- Create: `api/routes/business_routes.py`
- Test: `tests/api/test_business_routes.py`
- Modify: `api/app.py` (register new router)
- Modify: `store/schema.py` (add Business NodeLabel if missing)

- [ ] **Step 1: Check if Business NodeLabel exists**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && rg "BUSINESS" store/schema.py`

If not present, add `BUSINESS = "Business"` to `NodeLabel` in `store/schema.py`.

- [ ] **Step 2: Write the failing tests**

```python
# tests/api/test_business_routes.py
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from api.routes.business_routes import router


@pytest.fixture
def mock_graph():
    g = AsyncMock()
    g.query = AsyncMock(return_value=MagicMock(result_set=[]))
    return g


class TestBusinessCRUD:
    def test_router_has_list_endpoint(self):
        paths = [r.path for r in router.routes]
        assert "/businesses" in paths or any("/businesses" in str(r.path) for r in router.routes)

    def test_router_has_create_endpoint(self):
        methods = []
        for r in router.routes:
            if hasattr(r, "methods"):
                methods.extend(r.methods)
        assert "POST" in methods
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/api/test_business_routes.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 4: Implement Business CRUD routes**

```python
# api/routes/business_routes.py
"""Business management CRUD API routes."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from log import get_logger

log = get_logger(__name__)
router = APIRouter(prefix="/api/v1", tags=["business"])


class BusinessCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(..., min_length=1, max_length=500)


class BusinessUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class RepositoryBind(BaseModel):
    repositories: list[str]


@router.get("/businesses")
async def list_businesses(request: Request) -> dict[str, Any]:
    graph = request.app.state.graph
    q = "MATCH (b:Business) RETURN b.uid AS id, b.name AS name, b.description AS description, b.created_at AS created_at ORDER BY b.created_at DESC"
    result = await graph.query(q)
    businesses = []
    for row in result.result_set:
        businesses.append({
            "id": row[0],
            "name": row[1],
            "description": row[2],
            "created_at": row[3],
        })
    return {"businesses": businesses}


@router.post("/businesses", status_code=201)
async def create_business(request: Request, body: BusinessCreate) -> dict[str, Any]:
    graph = request.app.state.graph
    uid = f"business:{uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()
    q = (
        "CREATE (b:Business {uid: $uid, name: $name, description: $desc, created_at: $now}) "
        "RETURN b.uid AS id"
    )
    result = await graph.query(q, params={"uid": uid, "name": body.name, "desc": body.description, "now": now})
    return {"id": uid, "name": body.name, "description": body.description}


@router.put("/businesses/{business_id}")
async def update_business(request: Request, business_id: str, body: BusinessUpdate) -> dict[str, Any]:
    graph = request.app.state.graph
    sets = []
    params: dict[str, Any] = {"bid": business_id}
    if body.name is not None:
        sets.append("b.name = $name")
        params["name"] = body.name
    if body.description is not None:
        sets.append("b.description = $desc")
        params["desc"] = body.description
    if not sets:
        raise HTTPException(400, "No fields to update")
    q = f"MATCH (b:Business {{uid: $bid}}) SET {', '.join(sets)} RETURN b.uid AS id, b.name AS name, b.description AS description"
    result = await graph.query(q, params=params)
    if not result.result_set:
        raise HTTPException(404, f"Business {business_id} not found")
    row = result.result_set[0]
    return {"id": row[0], "name": row[1], "description": row[2]}


@router.delete("/businesses/{business_id}")
async def delete_business(request: Request, business_id: str) -> dict[str, str]:
    graph = request.app.state.graph
    q = "MATCH (b:Business {uid: $bid}) DETACH DELETE b RETURN count(b) AS deleted"
    result = await graph.query(q, params={"bid": business_id})
    deleted = result.result_set[0][0] if result.result_set else 0
    if deleted == 0:
        raise HTTPException(404, f"Business {business_id} not found")
    return {"status": "deleted"}


@router.put("/businesses/{business_id}/repositories")
async def bind_repositories(request: Request, business_id: str, body: RepositoryBind) -> dict[str, Any]:
    graph = request.app.state.graph
    check = "MATCH (b:Business {uid: $bid}) RETURN b.uid"
    result = await graph.query(check, params={"bid": business_id})
    if not result.result_set:
        raise HTTPException(404, f"Business {business_id} not found")
    await graph.query(
        "MATCH (b:Business {uid: $bid})-[r:CONTAINS_REPO]->() DELETE r",
        params={"bid": business_id},
    )
    for repo in body.repositories:
        await graph.query(
            "MATCH (b:Business {uid: $bid}) "
            "MERGE (r:Repository {name: $repo}) "
            "MERGE (b)-[:CONTAINS_REPO]->(r)",
            params={"bid": business_id, "repo": repo},
        )
    return {"business_id": business_id, "repositories": body.repositories}


@router.get("/businesses/{business_id}/repositories")
async def get_repositories(request: Request, business_id: str) -> dict[str, Any]:
    graph = request.app.state.graph
    q = (
        "MATCH (b:Business {uid: $bid})-[:CONTAINS_REPO]->(r) "
        "RETURN r.name AS repo ORDER BY repo"
    )
    result = await graph.query(q, params={"bid": business_id})
    repos = [row[0] for row in result.result_set]
    return {"business_id": business_id, "repositories": repos}
```

- [ ] **Step 5: Register router in app.py**

Find the router registration section in `api/app.py` and add:

```python
from api.routes.business_routes import router as business_router
app.include_router(business_router)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/api/test_business_routes.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add api/routes/business_routes.py tests/api/test_business_routes.py api/app.py
git commit -m "feat(api): add Business CRUD API with repository binding"
```

---

## Task 5: Enhance Domain Classification Prompt + Repo Path Cleanup

**Files:**
- Modify: `wiki/cross_repo_domain_planner.py`
- Modify: `wiki/prompts.py`
- Test: `tests/wiki/test_repo_path_cleanup.py`

- [ ] **Step 1: Write the failing test for repo path cleanup**

```python
# tests/wiki/test_repo_path_cleanup.py
from __future__ import annotations

from wiki.cross_repo_domain_planner import clean_repo_path


def test_strips_gitlab_group_prefix():
    assert clean_repo_path("ultron/ultron-basic-user") == "ultron-basic-user"


def test_strips_deep_prefix():
    assert clean_repo_path("org/team/my-service") == "my-service"


def test_no_prefix_unchanged():
    assert clean_repo_path("my-service") == "my-service"


def test_empty_string():
    assert clean_repo_path("") == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_repo_path_cleanup.py -v`
Expected: FAIL — `ImportError: cannot import name 'clean_repo_path'`

- [ ] **Step 3: Add clean_repo_path to cross_repo_domain_planner.py**

Add at the module level in `wiki/cross_repo_domain_planner.py`:

```python
def clean_repo_path(path: str) -> str:
    """Remove GitLab group prefix from repository path.

    'ultron/ultron-basic-user' → 'ultron-basic-user'
    """
    if "/" in path:
        return path.rsplit("/", 1)[-1]
    return path
```

- [ ] **Step 4: Apply clean_repo_path in _build_single_batch_prompt**

Find the `_build_single_batch_prompt` method in `wiki/cross_repo_domain_planner.py` and wrap `repository` values with `clean_repo_path()`.

- [ ] **Step 5: Enhance DOMAIN_CLASSIFY_PROMPT in prompts.py**

Update the domain classify prompt rules to add:

```
- Do NOT create domains named after technical concepts: enums, data_structures, utilities, infrastructure, configuration, constants
- Domain names must represent business capabilities (e.g., payment, messaging, user-management)
- These modules belong to a unified microservice system; group by business function, not by repository
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_repo_path_cleanup.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add wiki/cross_repo_domain_planner.py wiki/prompts.py tests/wiki/test_repo_path_cleanup.py
git commit -m "fix(wiki): clean repo path prefix and enhance domain classify prompt

- Strip GitLab group prefix (ultron/xxx → xxx)
- Forbid non-business domain names in LLM prompt
- Tell LLM these are modules from a unified microservice system"
```

---

## Task 6: Fill collect_modules Pipeline Stub with EntityRoleClassifier

**Files:**
- Modify: `wiki/pipeline_graph.py`
- Create: `wiki/pipeline_nodes.py`
- Test: `tests/wiki/test_pipeline_classify_node.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/wiki/test_pipeline_classify_node.py
from __future__ import annotations

import pytest
from wiki.pipeline_nodes import classify_entities_node
from wiki.entity_role_classifier import WikiEntityRole


@pytest.mark.asyncio
async def test_classify_entities_returns_roles():
    """classify_entities_node should populate entity_roles in state."""
    state = {
        "business_id": "test",
        "repositories": ["test-repo"],
        "config": {},
        "modules": {
            "test-repo": [
                {
                    "uid": "Module::PaymentService:0",
                    "label": "Module",
                    "properties": {
                        "name": "PaymentService",
                        "annotations": ["@Service"],
                        "methods_count": 10,
                        "start_line": 0,
                        "end_line": 300,
                        "semantic_roles": ["http_controller"],
                    },
                },
                {
                    "uid": "Module::UserDTO:0",
                    "label": "Module",
                    "properties": {
                        "name": "UserDTO",
                        "annotations": ["@Data"],
                        "methods_count": 0,
                        "start_line": 0,
                        "end_line": 20,
                    },
                },
            ]
        },
        "entity_roles": {},
        "role_stats": {},
    }
    result = await classify_entities_node(state)
    assert "Module::PaymentService:0" in result["entity_roles"]
    assert result["entity_roles"]["Module::PaymentService:0"] == WikiEntityRole.HAS_BUSINESS_LOGIC
    assert result["entity_roles"]["Module::UserDTO:0"] == WikiEntityRole.DATA_MODEL
    assert result["role_stats"]["has_business_logic"] >= 1
    assert result["role_stats"]["data_model"] >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_pipeline_classify_node.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'wiki.pipeline_nodes'`

- [ ] **Step 3: Implement classify_entities_node**

```python
# wiki/pipeline_nodes.py
"""LangGraph pipeline node implementations for Wiki generation."""
from __future__ import annotations

from collections import Counter
from typing import Any

from store.schema import GraphNode, NodeLabel
from wiki.entity_role_classifier import EntityRoleClassifier, WikiEntityRole
from log import get_logger

log = get_logger(__name__)


async def classify_entities_node(state: dict[str, Any]) -> dict[str, Any]:
    """Phase 1: classify all entities using EntityRoleClassifier."""
    classifier = EntityRoleClassifier()
    entity_roles: dict[str, str] = {}
    role_counter: Counter[str] = Counter()

    for repo, modules in state.get("modules", {}).items():
        for mod_dict in modules:
            uid = mod_dict.get("uid", "")
            props = mod_dict.get("properties", {})
            label_str = mod_dict.get("label", "Module")
            try:
                label = NodeLabel(label_str)
            except ValueError:
                label = NodeLabel.MODULE
            node = GraphNode(label=label, properties=props, uid=uid)
            role = classifier.classify(node, edge_count=0, children_count=0)
            entity_roles[uid] = role
            role_counter[role] += 1

    log.info(
        "classify_entities_done",
        total=len(entity_roles),
        **{r: c for r, c in role_counter.items()},
    )
    return {
        "entity_roles": entity_roles,
        "role_stats": dict(role_counter),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_pipeline_classify_node.py -v`
Expected: PASS

- [ ] **Step 5: Wire classify_entities_node into pipeline_graph.py**

In `wiki/pipeline_graph.py`, replace the `collect_modules_node` stub:

```python
from wiki.pipeline_nodes import classify_entities_node

# Replace the stub:
# async def collect_modules_node(...) -> ...
#     log.info("pipeline_node_stub", node="collect_modules")
#     return {}
```

Update `build_wiki_pipeline` to use `classify_entities_node`:

```python
graph.add_node("collect_modules", classify_entities_node)
```

- [ ] **Step 6: Run pipeline tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_quality_loop.py tests/wiki/test_pipeline_classify_node.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add wiki/pipeline_nodes.py wiki/pipeline_graph.py tests/wiki/test_pipeline_classify_node.py
git commit -m "feat(wiki): wire EntityRoleClassifier into LangGraph pipeline

Replace collect_modules stub with classify_entities_node that runs
two-phase entity classification on all modules."
```

---

## Self-Review Checklist

**1. Spec coverage:**
- [x] Task 1: EntityRoleClassifier (Spec 3.2) ✓
- [x] Task 2: WikiPipelineState extension (Spec 3.1) ✓
- [x] Task 3: TokenBudgetResolver ratios (Spec Section 8) ✓
- [x] Task 4: Business CRUD API (Spec 3.5) ✓
- [x] Task 5: Domain prompt enhancement + repo path cleanup (Spec 3.3, Sprint 1.7) ✓
- [x] Task 6: Pipeline integration (Sprint 1.5-1.6) ✓
- [ ] Sprint 1.2 (remove business_id defaults from wiki routes) — deferred to Sprint 2 to avoid breaking existing API clients before Dashboard is ready
- [ ] Sprint 1.9 (打包机验证) — manual verification, not codifiable

**2. Placeholder scan:** No TBDs, TODOs, or vague instructions found.

**3. Type consistency:** WikiEntityRole used consistently across entity_role_classifier.py, pipeline_nodes.py, and tests.
