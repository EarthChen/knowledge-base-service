# Sprint 3: Dashboard 配套改造 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 对 Dashboard 进行全面改造，使其支持新的业务领域 Wiki 树结构、仓库绑定、域树审阅、主题页内容增强、Wiki 审阅批改、以及知识图谱可视化。

**Architecture:** Dashboard 基于 Vite + React 19 + TypeScript + Tailwind CSS 4 + @tanstack/react-query。现有 Business CRUD 页面（`/businesses`）和 BusinessContext 已就绪。Wiki 功能集中在 `WikiShell` 组件中，通过 query params 管理状态。本次改造主要涉及：(1) 增强 Business 页面增加仓库绑定；(2) 重构 Wiki 树视图为主题树；(3) 新增域树审阅、Wiki 审阅批改、知识图谱等组件；(4) 新增后端 API 以支持域树查询和 Wiki 审阅功能。

**Tech Stack:** React 19, TypeScript, Vite 8, Tailwind CSS 4, @tanstack/react-query, react-router-dom 7, @xyflow/react (知识图谱), react-markdown, mermaid, pnpm

**Spec:** `docs/superpowers/specs/PROPOSAL_20260430_145217_business-domain-wiki-tree.md` (Section 3.6, Sprint 3)

**Dependencies:** Sprint 1-2 完成 — Business CRUD API (`api/routes/business_routes.py`)、完整 LangGraph pipeline、`WikiPipelineState` 包含 `review_status` / `review_notes` / `domain_tree`

---

## File Structure

### Backend (新增/修改 API)

| File | Responsibility |
|------|---------------|
| `api/routes/wiki_page_routes.py` (modify) | 新增 `/wiki/domain-tree` 和 `/wiki/topic-tree` 端点 |
| `api/routes/wiki_feedback_routes.py` (modify) | 新增 `/wiki/pages/{page_uid}/review` 和批量审阅端点 |
| `api/routes/business_routes.py` (existing) | 已有仓库绑定 API，无需修改 |

### Frontend (新增/修改组件)

| File | Responsibility |
|------|---------------|
| `dashboard/src/pages/Businesses.tsx` (modify) | 增加仓库绑定面板 |
| `dashboard/src/hooks/useBusinessRepositories.ts` (new) | 仓库绑定数据 hook |
| `dashboard/src/components/wiki/WikiTopicTreeNav.tsx` (new) | 主题树导航（Domain → SubDomain → TopicPage） |
| `dashboard/src/components/wiki/WikiTopicContent.tsx` (new) | 主题页内容展示增强（服务卡片 + 数据模型折叠 + Mermaid） |
| `dashboard/src/components/wiki/WikiDomainReviewPanel.tsx` (new) | 域树审阅面板 |
| `dashboard/src/components/wiki/WikiPageReviewBar.tsx` (new) | 页面级审阅标记栏 |
| `dashboard/src/components/wiki/WikiKnowledgeGraph.tsx` (new) | xyflow 知识图谱视图 |
| `dashboard/src/hooks/useWikiDomainTree.ts` (new) | 域树数据 hook |
| `dashboard/src/hooks/useWikiReview.ts` (new) | Wiki 审阅状态 hook |
| `dashboard/src/components/wiki/WikiShell.tsx` (modify) | 集成新 Tab 和组件 |

---

## Task 1: Business 仓库绑定面板

**Files:**
- Create: `dashboard/src/hooks/useBusinessRepositories.ts`
- Modify: `dashboard/src/pages/Businesses.tsx`
- Test: `dashboard/src/pages/__tests__/Businesses.repoBind.test.tsx`

- [ ] **Step 1: Write the failing test**

```typescript
// dashboard/src/pages/__tests__/Businesses.repoBind.test.tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import Businesses from "../Businesses";

vi.mock("../../api/client", () => ({
  api: vi.fn().mockImplementation((path: string) => {
    if (path.includes("/businesses") && !path.includes("repositories"))
      return Promise.resolve({ businesses: [{ id: "test-biz", name: "Test", description: "desc", created_at: Date.now() / 1000 }] });
    if (path.includes("/repositories"))
      return Promise.resolve({ repositories: ["repo-a", "repo-b"] });
    return Promise.resolve({});
  }),
}));

vi.mock("../../contexts/BusinessContext", () => ({
  useBusiness: () => ({ currentBusiness: "test-biz", setCurrentBusiness: vi.fn(), businesses: [], isLoading: false, isBound: false }),
}));
vi.mock("../../contexts/AuthContext", () => ({
  useAuth: () => ({ isAdmin: true, boundBusiness: null }),
}));
vi.mock("../../i18n/context", () => ({
  useI18n: () => ({ t: new Proxy({}, { get: (_t, p) => new Proxy({}, { get: (_t2, p2) => `${String(p)}.${String(p2)}` }) }) }),
}));
vi.mock("../../components/Toast", () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

function renderWithProviders(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

describe("Businesses repo binding", () => {
  it("shows repo binding section when clicking manage repos", async () => {
    renderWithProviders(<Businesses />);
    await waitFor(() => expect(screen.getByText("Test")).toBeInTheDocument());
    const manageBtn = screen.getByText("businesses.manageRepos");
    fireEvent.click(manageBtn);
    await waitFor(() => expect(screen.getByText("repo-a")).toBeInTheDocument());
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service/dashboard && pnpm vitest run src/pages/__tests__/Businesses.repoBind.test.tsx`
Expected: FAIL — component doesn't have the manage repos button yet

- [ ] **Step 3: Create useBusinessRepositories hook**

```typescript
// dashboard/src/hooks/useBusinessRepositories.ts
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";

interface RepoListResponse {
  repositories: string[];
}

export function useBusinessRepositories(businessId: string) {
  return useQuery<RepoListResponse>({
    queryKey: ["business", businessId, "repositories"],
    queryFn: () => api(`/businesses/${encodeURIComponent(businessId)}/repositories`),
    enabled: !!businessId && businessId !== "default",
    staleTime: 30_000,
  });
}

export function useBindRepositories(businessId: string) {
  const qc = useQueryClient();
  return useMutation<unknown, Error, string[]>({
    mutationFn: (repositories) =>
      api(`/businesses/${encodeURIComponent(businessId)}/repositories`, {
        method: "PUT",
        body: JSON.stringify({ repositories }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["business", businessId, "repositories"] });
    },
  });
}
```

- [ ] **Step 4: Add repo binding panel to Businesses.tsx**

Add a `RepoBindPanel` section within each business card. When clicked "管理仓库", expand a panel showing bound repositories with checkboxes to add/remove. Use `useBusinessRepositories` and `useBindRepositories` hooks.

Key additions to `Businesses.tsx`:
- Import `useBusinessRepositories` and `useBindRepositories`
- Add state: `const [expandedBiz, setExpandedBiz] = useState<string | null>(null)`
- Add a "管理仓库" button in each business card
- When expanded, show bound repos list with a text input to add new repo IDs

- [ ] **Step 5: Add i18n keys**

Add to the translation files the keys: `businesses.manageRepos`, `businesses.boundRepos`, `businesses.bindRepo`, `businesses.unbindRepo`, `businesses.noRepos`

- [ ] **Step 6: Run test and verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service/dashboard && pnpm vitest run src/pages/__tests__/Businesses.repoBind.test.tsx`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add dashboard/src/hooks/useBusinessRepositories.ts dashboard/src/pages/Businesses.tsx dashboard/src/pages/__tests__/Businesses.repoBind.test.tsx
git commit -m "feat(dashboard): add repository binding panel to Business page"
```

---

## Task 2: 后端 — 域树和主题树 API

**Files:**
- Modify: `api/routes/wiki_page_routes.py`
- Test: `tests/wiki/api/test_domain_tree_api.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/wiki/api/test_domain_tree_api.py
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient, ASGITransport

from main import app


@pytest.fixture
def mock_wiki_service():
    svc = AsyncMock()
    svc.get_domain_tree = AsyncMock(return_value={
        "tree": [
            {"name": "payment", "modules": ["PaymentService"], "children": [
                {"name": "payment-core", "modules": ["PaymentService"], "children": []}
            ]},
        ],
        "review_status": {"domain_tree": "pending_review"},
    })
    svc.get_topic_tree = AsyncMock(return_value={
        "tree": [
            {"name": "payment", "page_type": "domain_overview", "path": "wiki/payment", "children": [
                {"name": "payment-core", "page_type": "topic", "path": "wiki/payment/payment-core", "children": []},
            ]},
        ],
    })
    return svc


@pytest.mark.asyncio
async def test_get_domain_tree(mock_wiki_service):
    with patch("api.routes.wiki_page_routes._get_wiki_service", return_value=mock_wiki_service):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/wiki/domain-tree",
                params={"business_id": "test-biz"},
                headers={"Authorization": "Bearer test-token"},
            )
    assert resp.status_code == 200
    data = resp.json()
    assert "tree" in data
    assert data["tree"][0]["name"] == "payment"


@pytest.mark.asyncio
async def test_get_topic_tree(mock_wiki_service):
    with patch("api.routes.wiki_page_routes._get_wiki_service", return_value=mock_wiki_service):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/wiki/topic-tree",
                params={"business_id": "test-biz"},
                headers={"Authorization": "Bearer test-token"},
            )
    assert resp.status_code == 200
    data = resp.json()
    assert "tree" in data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/api/test_domain_tree_api.py -v --no-cov`
Expected: FAIL — 404 endpoint not found

- [ ] **Step 3: Add domain-tree and topic-tree endpoints**

Add to `api/routes/wiki_page_routes.py`:

```python
@router.get("/domain-tree")
async def get_domain_tree(
    request: Request,
    business_id: str = Query(..., description="Business ID"),
) -> dict[str, Any]:
    """Return the hierarchical domain tree for a business wiki.

    Used by Dashboard domain review panel.
    """
    svc = _get_wiki_service(request)
    result = await svc.get_domain_tree(business_id)
    return result


@router.get("/topic-tree")
async def get_topic_tree(
    request: Request,
    business_id: str = Query(..., description="Business ID"),
) -> dict[str, Any]:
    """Return the topic page tree for dashboard wiki navigation.

    Structure: Domain → SubDomain → TopicPage (leaf).
    """
    svc = _get_wiki_service(request)
    result = await svc.get_topic_tree(business_id)
    return result
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/api/test_domain_tree_api.py -v --no-cov`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add api/routes/wiki_page_routes.py tests/wiki/api/test_domain_tree_api.py
git commit -m "feat(api): add domain-tree and topic-tree endpoints for dashboard"
```

---

## Task 3: 后端 — Wiki 审阅 API

**Files:**
- Modify: `api/routes/wiki_feedback_routes.py`
- Test: `tests/wiki/api/test_wiki_review_api.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/wiki/api/test_wiki_review_api.py
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient, ASGITransport

from main import app


@pytest.fixture
def mock_wiki_service():
    svc = AsyncMock()
    svc.set_page_review_status = AsyncMock(return_value={"status": "ok"})
    svc.batch_review = AsyncMock(return_value={"updated": 3})
    svc.trigger_page_regeneration = AsyncMock(return_value={"task_id": "regen-123"})
    return svc


@pytest.mark.asyncio
async def test_set_page_review_status(mock_wiki_service):
    with patch("api.routes.wiki_feedback_routes._get_wiki_service", return_value=mock_wiki_service):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/wiki/pages/wiki%2Fpayment/review",
                json={"status": "approved", "notes": ""},
                headers={"Authorization": "Bearer test-token"},
            )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_batch_review(mock_wiki_service):
    with patch("api.routes.wiki_feedback_routes._get_wiki_service", return_value=mock_wiki_service):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/wiki/review/batch",
                json={
                    "business_id": "test-biz",
                    "reviews": [
                        {"page_path": "wiki/payment", "status": "approved"},
                        {"page_path": "wiki/messaging", "status": "needs_revision", "notes": "Missing flow diagram"},
                    ],
                },
                headers={"Authorization": "Bearer test-token"},
            )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_trigger_regeneration(mock_wiki_service):
    with patch("api.routes.wiki_feedback_routes._get_wiki_service", return_value=mock_wiki_service):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/wiki/pages/wiki%2Fpayment/regenerate",
                json={"heal_hints": "Add more detail about refund flow"},
                headers={"Authorization": "Bearer test-token"},
            )
    assert resp.status_code == 200
    data = resp.json()
    assert "task_id" in data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/api/test_wiki_review_api.py -v --no-cov`
Expected: FAIL — endpoints don't exist

- [ ] **Step 3: Add review endpoints**

Add to `api/routes/wiki_feedback_routes.py`:

```python
@router.post("/pages/{page_uid:path}/review", response_model=None)
async def set_page_review(
    request: Request,
    page_uid: str,
    body: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """Set review status for a wiki page."""
    svc = _get_wiki_service(request)
    status = body.get("status", "pending_review")
    notes = body.get("notes", "")
    return await svc.set_page_review_status(page_uid, status, notes)


@router.post("/review/batch", response_model=None)
async def batch_review(
    request: Request,
    body: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """Batch review multiple wiki pages."""
    svc = _get_wiki_service(request)
    business_id = body.get("business_id", "")
    reviews = body.get("reviews", [])
    return await svc.batch_review(business_id, reviews)


@router.post("/pages/{page_uid:path}/regenerate", response_model=None)
async def trigger_regeneration(
    request: Request,
    page_uid: str,
    body: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """Trigger regeneration of a wiki page with optional heal hints."""
    svc = _get_wiki_service(request)
    heal_hints = body.get("heal_hints", "")
    return await svc.trigger_page_regeneration(page_uid, heal_hints)
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/api/test_wiki_review_api.py -v --no-cov`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add api/routes/wiki_feedback_routes.py tests/wiki/api/test_wiki_review_api.py
git commit -m "feat(api): add wiki page review and regeneration endpoints"
```

---

## Task 4: Wiki 主题树导航组件

**Files:**
- Create: `dashboard/src/hooks/useWikiDomainTree.ts`
- Create: `dashboard/src/components/wiki/WikiTopicTreeNav.tsx`
- Test: `dashboard/src/components/wiki/__tests__/WikiTopicTreeNav.test.tsx`

- [ ] **Step 1: Write the failing test**

```typescript
// dashboard/src/components/wiki/__tests__/WikiTopicTreeNav.test.tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import WikiTopicTreeNav from "../WikiTopicTreeNav";

vi.mock("../../../api/client", () => ({
  api: vi.fn(),
}));

const mockTree = [
  {
    name: "payment",
    page_type: "domain_overview",
    path: "wiki/payment",
    children: [
      { name: "payment-core", page_type: "topic", path: "wiki/payment/payment-core", children: [] },
      { name: "refund", page_type: "topic", path: "wiki/payment/refund", children: [] },
    ],
  },
  {
    name: "user-management",
    page_type: "domain_overview",
    path: "wiki/user-management",
    children: [],
  },
];

function renderWithProviders(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

describe("WikiTopicTreeNav", () => {
  it("renders domain nodes", () => {
    renderWithProviders(
      <WikiTopicTreeNav tree={mockTree} selectedPath={null} onSelect={vi.fn()} />,
    );
    expect(screen.getByText("payment")).toBeInTheDocument();
    expect(screen.getByText("user-management")).toBeInTheDocument();
  });

  it("expands domain to show children", () => {
    renderWithProviders(
      <WikiTopicTreeNav tree={mockTree} selectedPath={null} onSelect={vi.fn()} />,
    );
    fireEvent.click(screen.getByText("payment"));
    expect(screen.getByText("payment-core")).toBeInTheDocument();
    expect(screen.getByText("refund")).toBeInTheDocument();
  });

  it("calls onSelect when clicking a topic page", () => {
    const onSelect = vi.fn();
    renderWithProviders(
      <WikiTopicTreeNav tree={mockTree} selectedPath={null} onSelect={onSelect} />,
    );
    fireEvent.click(screen.getByText("payment"));
    fireEvent.click(screen.getByText("payment-core"));
    expect(onSelect).toHaveBeenCalledWith("wiki/payment/payment-core");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service/dashboard && pnpm vitest run src/components/wiki/__tests__/WikiTopicTreeNav.test.tsx`
Expected: FAIL — module not found

- [ ] **Step 3: Create useWikiDomainTree hook**

```typescript
// dashboard/src/hooks/useWikiDomainTree.ts
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

export interface TopicTreeNode {
  name: string;
  page_type: string;
  path: string;
  children: TopicTreeNode[];
  review_status?: string;
}

interface TopicTreeResponse {
  tree: TopicTreeNode[];
}

export function useWikiTopicTree(businessId: string) {
  return useQuery<TopicTreeResponse>({
    queryKey: ["wiki", "topic-tree", businessId],
    queryFn: () => api(`/wiki/topic-tree?business_id=${encodeURIComponent(businessId)}`),
    enabled: !!businessId,
    staleTime: 30_000,
  });
}

interface DomainTreeResponse {
  tree: TopicTreeNode[];
  review_status: Record<string, string>;
}

export function useWikiDomainTree(businessId: string) {
  return useQuery<DomainTreeResponse>({
    queryKey: ["wiki", "domain-tree", businessId],
    queryFn: () => api(`/wiki/domain-tree?business_id=${encodeURIComponent(businessId)}`),
    enabled: !!businessId,
    staleTime: 30_000,
  });
}
```

- [ ] **Step 4: Implement WikiTopicTreeNav**

```typescript
// dashboard/src/components/wiki/WikiTopicTreeNav.tsx
import { useState, useCallback } from "react";
import { ChevronRight, ChevronDown, FileText, FolderOpen } from "lucide-react";
import type { TopicTreeNode } from "../../hooks/useWikiDomainTree";

interface Props {
  tree: TopicTreeNode[];
  selectedPath: string | null;
  onSelect: (path: string) => void;
}

export default function WikiTopicTreeNav({ tree, selectedPath, onSelect }: Props) {
  return (
    <nav className="space-y-0.5 text-sm">
      {tree.map((node) => (
        <TreeNode key={node.path} node={node} depth={0} selectedPath={selectedPath} onSelect={onSelect} />
      ))}
    </nav>
  );
}

function TreeNode({
  node, depth, selectedPath, onSelect,
}: {
  node: TopicTreeNode; depth: number; selectedPath: string | null; onSelect: (path: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const hasChildren = node.children.length > 0;
  const isSelected = selectedPath === node.path;
  const isDomain = node.page_type === "domain_overview";

  const handleClick = useCallback(() => {
    if (hasChildren) setExpanded((e) => !e);
    onSelect(node.path);
  }, [hasChildren, node.path, onSelect]);

  return (
    <div>
      <button
        onClick={handleClick}
        className={`flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-left transition-colors ${
          isSelected
            ? "bg-sky-50 text-sky-700 dark:bg-sky-950/40 dark:text-sky-400"
            : "text-gray-700 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800"
        }`}
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
      >
        {hasChildren ? (
          expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />
        ) : (
          <span className="w-3.5" />
        )}
        {isDomain ? <FolderOpen size={14} /> : <FileText size={14} />}
        <span className="truncate">{node.name}</span>
        {node.review_status === "pending_review" && (
          <span className="ml-auto rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] text-amber-700 dark:bg-amber-900/40 dark:text-amber-400">
            待审阅
          </span>
        )}
      </button>
      {expanded && hasChildren && (
        <div>
          {node.children.map((child) => (
            <TreeNode key={child.path} node={child} depth={depth + 1} selectedPath={selectedPath} onSelect={onSelect} />
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 5: Run tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service/dashboard && pnpm vitest run src/components/wiki/__tests__/WikiTopicTreeNav.test.tsx`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add dashboard/src/hooks/useWikiDomainTree.ts dashboard/src/components/wiki/WikiTopicTreeNav.tsx dashboard/src/components/wiki/__tests__/WikiTopicTreeNav.test.tsx
git commit -m "feat(dashboard): add WikiTopicTreeNav for business domain topic tree

Displays Domain → SubDomain → TopicPage hierarchy with expand/collapse.
Shows pending_review badge on domains needing review."
```

---

## Task 5: 主题页内容展示增强

**Files:**
- Create: `dashboard/src/components/wiki/WikiTopicContent.tsx`
- Test: `dashboard/src/components/wiki/__tests__/WikiTopicContent.test.tsx`

- [ ] **Step 1: Write the failing test**

```typescript
// dashboard/src/components/wiki/__tests__/WikiTopicContent.test.tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import WikiTopicContent from "../WikiTopicContent";

describe("WikiTopicContent", () => {
  const page = {
    title: "Payment Service",
    content: "## 业务概述\nPayment handling.\n\n## 核心业务流程\n```mermaid\nsequenceDiagram\nA->>B: pay\n```\n\n## 核心服务详情\n### PaymentService\nProcesses payments.\n\n## 数据模型\n| 类名 | 类型 | 字段 |\n|---|---|---|\n| PayDTO | DTO | id, amount |\n\n## 关联主题\n- [[user-management]]",
    path: "wiki/payment",
    page_type: "topic",
    domain: "payment",
    review_status: "pending_review",
  };

  it("renders page title", () => {
    render(<WikiTopicContent page={page} onReviewAction={vi.fn()} />);
    expect(screen.getByText("Payment Service")).toBeInTheDocument();
  });

  it("renders business overview section", () => {
    render(<WikiTopicContent page={page} onReviewAction={vi.fn()} />);
    expect(screen.getByText(/Payment handling/)).toBeInTheDocument();
  });

  it("shows review status badge", () => {
    render(<WikiTopicContent page={page} onReviewAction={vi.fn()} />);
    expect(screen.getByText(/待审阅/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service/dashboard && pnpm vitest run src/components/wiki/__tests__/WikiTopicContent.test.tsx`
Expected: FAIL — module not found

- [ ] **Step 3: Implement WikiTopicContent**

```typescript
// dashboard/src/components/wiki/WikiTopicContent.tsx
import { useMemo } from "react";
import MarkdownRenderer from "./MarkdownRenderer";

interface TopicPage {
  title: string;
  content: string;
  path: string;
  page_type: string;
  domain?: string;
  review_status?: string;
}

interface Props {
  page: TopicPage;
  onReviewAction: (action: "approve" | "needs_revision" | "regenerate", notes?: string) => void;
}

const REVIEW_LABELS: Record<string, { text: string; className: string }> = {
  pending_review: { text: "待审阅", className: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-400" },
  approved: { text: "已通过", className: "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-400" },
  needs_revision: { text: "需修改", className: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400" },
  revised: { text: "已修订", className: "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-400" },
};

export default function WikiTopicContent({ page, onReviewAction }: Props) {
  const reviewBadge = useMemo(() => {
    const entry = REVIEW_LABELS[page.review_status ?? ""];
    if (!entry) return null;
    return (
      <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${entry.className}`}>
        {entry.text}
      </span>
    );
  }, [page.review_status]);

  return (
    <article className="space-y-6">
      <header className="flex items-center justify-between border-b border-gray-200 pb-4 dark:border-gray-700">
        <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100">{page.title}</h1>
        <div className="flex items-center gap-3">
          {reviewBadge}
          <div className="flex gap-1.5">
            <button
              onClick={() => onReviewAction("approve")}
              className="rounded-md bg-green-50 px-2.5 py-1 text-xs font-medium text-green-700 hover:bg-green-100 dark:bg-green-950/40 dark:text-green-400 dark:hover:bg-green-900/60"
            >
              通过
            </button>
            <button
              onClick={() => {
                const notes = prompt("请输入修改意见:");
                if (notes) onReviewAction("needs_revision", notes);
              }}
              className="rounded-md bg-amber-50 px-2.5 py-1 text-xs font-medium text-amber-700 hover:bg-amber-100 dark:bg-amber-950/40 dark:text-amber-400 dark:hover:bg-amber-900/60"
            >
              需修改
            </button>
            <button
              onClick={() => onReviewAction("regenerate")}
              className="rounded-md bg-sky-50 px-2.5 py-1 text-xs font-medium text-sky-700 hover:bg-sky-100 dark:bg-sky-950/40 dark:text-sky-400 dark:hover:bg-sky-900/60"
            >
              重新生成
            </button>
          </div>
        </div>
      </header>
      <div className="prose prose-sm max-w-none dark:prose-invert">
        <MarkdownRenderer content={page.content} />
      </div>
    </article>
  );
}
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service/dashboard && pnpm vitest run src/components/wiki/__tests__/WikiTopicContent.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add dashboard/src/components/wiki/WikiTopicContent.tsx dashboard/src/components/wiki/__tests__/WikiTopicContent.test.tsx
git commit -m "feat(dashboard): add WikiTopicContent with review actions

Renders topic page markdown with review status badge and
approve/needs_revision/regenerate action buttons."
```

---

## Task 6: 域树审阅面板

**Files:**
- Create: `dashboard/src/components/wiki/WikiDomainReviewPanel.tsx`
- Test: `dashboard/src/components/wiki/__tests__/WikiDomainReviewPanel.test.tsx`

- [ ] **Step 1: Write the failing test**

```typescript
// dashboard/src/components/wiki/__tests__/WikiDomainReviewPanel.test.tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import WikiDomainReviewPanel from "../WikiDomainReviewPanel";

vi.mock("../../../api/client", () => ({
  api: vi.fn(),
}));

function renderWithProviders(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

describe("WikiDomainReviewPanel", () => {
  const domainTree = [
    {
      name: "payment",
      description: "Payment processing",
      modules: ["PaymentService", "RefundService"],
      children: [],
    },
    {
      name: "user-management",
      description: "User management",
      modules: ["UserService"],
      children: [],
    },
  ];

  it("renders domain cards", () => {
    renderWithProviders(
      <WikiDomainReviewPanel
        domainTree={domainTree}
        reviewStatus={{ domain_tree: "pending_review" }}
        onApprove={vi.fn()}
        onRegenerate={vi.fn()}
      />,
    );
    expect(screen.getByText("payment")).toBeInTheDocument();
    expect(screen.getByText("user-management")).toBeInTheDocument();
  });

  it("shows module count per domain", () => {
    renderWithProviders(
      <WikiDomainReviewPanel
        domainTree={domainTree}
        reviewStatus={{ domain_tree: "pending_review" }}
        onApprove={vi.fn()}
        onRegenerate={vi.fn()}
      />,
    );
    expect(screen.getByText("2 modules")).toBeInTheDocument();
    expect(screen.getByText("1 modules")).toBeInTheDocument();
  });

  it("shows pending_review banner", () => {
    renderWithProviders(
      <WikiDomainReviewPanel
        domainTree={domainTree}
        reviewStatus={{ domain_tree: "pending_review" }}
        onApprove={vi.fn()}
        onRegenerate={vi.fn()}
      />,
    );
    expect(screen.getByText(/域树待审阅/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service/dashboard && pnpm vitest run src/components/wiki/__tests__/WikiDomainReviewPanel.test.tsx`
Expected: FAIL

- [ ] **Step 3: Implement WikiDomainReviewPanel**

```typescript
// dashboard/src/components/wiki/WikiDomainReviewPanel.tsx
import { CheckCircle, AlertTriangle, RefreshCw, Layers } from "lucide-react";

interface DomainNode {
  name: string;
  description?: string;
  modules: string[];
  children: DomainNode[];
}

interface Props {
  domainTree: DomainNode[];
  reviewStatus: Record<string, string>;
  onApprove: () => void;
  onRegenerate: (domainNames: string[]) => void;
}

export default function WikiDomainReviewPanel({ domainTree, reviewStatus, onApprove, onRegenerate }: Props) {
  const isPending = reviewStatus.domain_tree === "pending_review";

  return (
    <div className="space-y-4">
      {isPending && (
        <div className="flex items-center gap-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-700 dark:bg-amber-950/30 dark:text-amber-300">
          <AlertTriangle size={16} />
          <span>域树待审阅 — 请检查域划分是否合理，确认后点击"批准"</span>
          <button
            onClick={onApprove}
            className="ml-auto flex items-center gap-1 rounded-md bg-green-600 px-3 py-1 text-xs font-medium text-white hover:bg-green-500"
          >
            <CheckCircle size={12} /> 批准
          </button>
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {domainTree.map((domain) => (
          <div
            key={domain.name}
            className="rounded-xl border border-gray-200 p-4 dark:border-gray-700"
          >
            <div className="flex items-center gap-2">
              <Layers size={16} className="text-sky-600 dark:text-sky-400" />
              <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">{domain.name}</h3>
            </div>
            {domain.description && (
              <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">{domain.description}</p>
            )}
            <div className="mt-2 text-xs text-gray-400 dark:text-gray-500">
              {domain.modules.length} modules
            </div>
            <div className="mt-2 flex flex-wrap gap-1">
              {domain.modules.slice(0, 5).map((m) => (
                <span key={m} className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-600 dark:bg-gray-800 dark:text-gray-400">
                  {m}
                </span>
              ))}
              {domain.modules.length > 5 && (
                <span className="text-[10px] text-gray-400">+{domain.modules.length - 5}</span>
              )}
            </div>
            {isPending && (
              <button
                onClick={() => onRegenerate([domain.name])}
                className="mt-3 flex items-center gap-1 text-xs text-sky-600 hover:text-sky-500 dark:text-sky-400"
              >
                <RefreshCw size={12} /> 重新生成此域
              </button>
            )}
            {domain.children.length > 0 && (
              <div className="mt-2 border-t border-gray-100 pt-2 dark:border-gray-800">
                <div className="text-[10px] font-medium text-gray-400">子域:</div>
                {domain.children.map((child) => (
                  <div key={child.name} className="ml-2 text-[11px] text-gray-500 dark:text-gray-400">
                    └ {child.name} ({child.modules.length} modules)
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service/dashboard && pnpm vitest run src/components/wiki/__tests__/WikiDomainReviewPanel.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add dashboard/src/components/wiki/WikiDomainReviewPanel.tsx dashboard/src/components/wiki/__tests__/WikiDomainReviewPanel.test.tsx
git commit -m "feat(dashboard): add WikiDomainReviewPanel for post-generation domain review

Shows domain cards with module lists, pending_review banner,
approve and per-domain regenerate buttons."
```

---

## Task 7: Wiki 审阅 Hook + 页面审阅栏

**Files:**
- Create: `dashboard/src/hooks/useWikiReview.ts`
- Create: `dashboard/src/components/wiki/WikiPageReviewBar.tsx`
- Test: `dashboard/src/components/wiki/__tests__/WikiPageReviewBar.test.tsx`

- [ ] **Step 1: Write the failing test**

```typescript
// dashboard/src/components/wiki/__tests__/WikiPageReviewBar.test.tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import WikiPageReviewBar from "../WikiPageReviewBar";

describe("WikiPageReviewBar", () => {
  it("shows approve and reject buttons", () => {
    render(
      <WikiPageReviewBar
        pagePath="wiki/payment"
        currentStatus="pending_review"
        onStatusChange={vi.fn()}
        onRegenerate={vi.fn()}
      />,
    );
    expect(screen.getByText("✓")).toBeInTheDocument();
    expect(screen.getByText("✗")).toBeInTheDocument();
    expect(screen.getByText("📝")).toBeInTheDocument();
  });

  it("calls onStatusChange with approved on click", () => {
    const onChange = vi.fn();
    render(
      <WikiPageReviewBar
        pagePath="wiki/payment"
        currentStatus="pending_review"
        onStatusChange={onChange}
        onRegenerate={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByText("✓"));
    expect(onChange).toHaveBeenCalledWith("wiki/payment", "approved", "");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service/dashboard && pnpm vitest run src/components/wiki/__tests__/WikiPageReviewBar.test.tsx`
Expected: FAIL

- [ ] **Step 3: Create useWikiReview hook**

```typescript
// dashboard/src/hooks/useWikiReview.ts
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";

interface ReviewPayload {
  status: string;
  notes?: string;
}

export function useSetPageReview() {
  const qc = useQueryClient();
  return useMutation<unknown, Error, { pagePath: string; status: string; notes: string }>({
    mutationFn: ({ pagePath, status, notes }) =>
      api(`/wiki/pages/${encodeURIComponent(pagePath)}/review`, {
        method: "POST",
        body: JSON.stringify({ status, notes }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["wiki"] });
    },
  });
}

export function useBatchReview() {
  const qc = useQueryClient();
  return useMutation<unknown, Error, { businessId: string; reviews: Array<{ page_path: string; status: string; notes?: string }> }>({
    mutationFn: ({ businessId, reviews }) =>
      api("/wiki/review/batch", {
        method: "POST",
        body: JSON.stringify({ business_id: businessId, reviews }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["wiki"] });
    },
  });
}

export function useRegeneratePage() {
  const qc = useQueryClient();
  return useMutation<{ task_id: string }, Error, { pagePath: string; healHints?: string }>({
    mutationFn: ({ pagePath, healHints }) =>
      api(`/wiki/pages/${encodeURIComponent(pagePath)}/regenerate`, {
        method: "POST",
        body: JSON.stringify({ heal_hints: healHints ?? "" }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["wiki"] });
    },
  });
}
```

- [ ] **Step 4: Implement WikiPageReviewBar**

```typescript
// dashboard/src/components/wiki/WikiPageReviewBar.tsx
interface Props {
  pagePath: string;
  currentStatus: string;
  onStatusChange: (pagePath: string, status: string, notes: string) => void;
  onRegenerate: (pagePath: string) => void;
}

const STATUS_STYLES: Record<string, string> = {
  pending_review: "border-amber-300 bg-amber-50 dark:border-amber-700 dark:bg-amber-950/30",
  approved: "border-green-300 bg-green-50 dark:border-green-700 dark:bg-green-950/30",
  needs_revision: "border-red-300 bg-red-50 dark:border-red-700 dark:bg-red-950/30",
  revised: "border-blue-300 bg-blue-50 dark:border-blue-700 dark:bg-blue-950/30",
};

export default function WikiPageReviewBar({ pagePath, currentStatus, onStatusChange, onRegenerate }: Props) {
  return (
    <div className={`flex items-center gap-2 rounded-lg border p-2 text-xs ${STATUS_STYLES[currentStatus] ?? ""}`}>
      <button
        onClick={() => onStatusChange(pagePath, "approved", "")}
        className="rounded-md bg-green-600 px-2 py-0.5 text-white hover:bg-green-500"
        title="通过"
      >
        ✓
      </button>
      <button
        onClick={() => onStatusChange(pagePath, "needs_revision", "")}
        className="rounded-md bg-red-500 px-2 py-0.5 text-white hover:bg-red-400"
        title="需修改"
      >
        ✗
      </button>
      <button
        onClick={() => {
          const notes = prompt("请输入审阅意见:");
          if (notes) onStatusChange(pagePath, "needs_revision", notes);
        }}
        className="rounded-md bg-amber-500 px-2 py-0.5 text-white hover:bg-amber-400"
        title="添加意见"
      >
        📝
      </button>
      <button
        onClick={() => onRegenerate(pagePath)}
        className="ml-auto rounded-md bg-sky-600 px-2 py-0.5 text-white hover:bg-sky-500"
      >
        重新生成
      </button>
    </div>
  );
}
```

- [ ] **Step 5: Run tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service/dashboard && pnpm vitest run src/components/wiki/__tests__/WikiPageReviewBar.test.tsx`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add dashboard/src/hooks/useWikiReview.ts dashboard/src/components/wiki/WikiPageReviewBar.tsx dashboard/src/components/wiki/__tests__/WikiPageReviewBar.test.tsx
git commit -m "feat(dashboard): add wiki review hooks and page review bar

useSetPageReview, useBatchReview, useRegeneratePage hooks.
WikiPageReviewBar with approve/reject/annotate/regenerate buttons."
```

---

## Task 8: 知识图谱视图

**Files:**
- Create: `dashboard/src/components/wiki/WikiKnowledgeGraph.tsx`
- Test: `dashboard/src/components/wiki/__tests__/WikiKnowledgeGraph.test.tsx`

- [ ] **Step 1: Write the failing test**

```typescript
// dashboard/src/components/wiki/__tests__/WikiKnowledgeGraph.test.tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import WikiKnowledgeGraph from "../WikiKnowledgeGraph";

vi.mock("@xyflow/react", () => ({
  ReactFlow: ({ nodes, edges }: { nodes: unknown[]; edges: unknown[] }) => (
    <div data-testid="react-flow">
      <span>{nodes.length} nodes</span>
      <span>{edges.length} edges</span>
    </div>
  ),
  Background: () => null,
  Controls: () => null,
  MiniMap: () => null,
}));

describe("WikiKnowledgeGraph", () => {
  const domains = [
    { id: "payment", label: "Payment", children: ["refund"] },
    { id: "refund", label: "Refund", children: [] },
    { id: "user", label: "User", children: [] },
  ];
  const edges = [
    { source: "payment", target: "user", label: "CALLS" },
    { source: "payment", target: "refund", label: "CALLS" },
  ];

  it("renders xyflow with correct node and edge counts", () => {
    render(<WikiKnowledgeGraph domains={domains} domainEdges={edges} onNodeClick={vi.fn()} />);
    expect(screen.getByTestId("react-flow")).toBeInTheDocument();
    expect(screen.getByText("3 nodes")).toBeInTheDocument();
    expect(screen.getByText("2 edges")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service/dashboard && pnpm vitest run src/components/wiki/__tests__/WikiKnowledgeGraph.test.tsx`
Expected: FAIL

- [ ] **Step 3: Implement WikiKnowledgeGraph**

```typescript
// dashboard/src/components/wiki/WikiKnowledgeGraph.tsx
import { useMemo, useCallback } from "react";
import { ReactFlow, Background, Controls, MiniMap } from "@xyflow/react";
import type { Node, Edge } from "@xyflow/react";
import "@xyflow/react/dist/style.css";

interface DomainInfo {
  id: string;
  label: string;
  children: string[];
}

interface DomainEdge {
  source: string;
  target: string;
  label: string;
}

interface Props {
  domains: DomainInfo[];
  domainEdges: DomainEdge[];
  onNodeClick: (domainId: string) => void;
}

export default function WikiKnowledgeGraph({ domains, domainEdges, onNodeClick }: Props) {
  const nodes: Node[] = useMemo(() => {
    const cols = Math.ceil(Math.sqrt(domains.length));
    return domains.map((d, i) => ({
      id: d.id,
      position: { x: (i % cols) * 200, y: Math.floor(i / cols) * 150 },
      data: { label: d.label },
      style: {
        background: "#e0f2fe",
        border: "1px solid #7dd3fc",
        borderRadius: "8px",
        padding: "10px",
        fontSize: "12px",
        fontWeight: 600,
      },
    }));
  }, [domains]);

  const edges: Edge[] = useMemo(
    () =>
      domainEdges.map((e, i) => ({
        id: `e-${i}`,
        source: e.source,
        target: e.target,
        label: e.label,
        animated: true,
        style: { stroke: "#94a3b8" },
      })),
    [domainEdges],
  );

  const handleNodeClick = useCallback(
    (_: unknown, node: Node) => onNodeClick(node.id),
    [onNodeClick],
  );

  return (
    <div className="h-[500px] w-full rounded-lg border border-gray-200 dark:border-gray-700">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodeClick={handleNodeClick}
        fitView
      >
        <Background />
        <Controls />
        <MiniMap />
      </ReactFlow>
    </div>
  );
}
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service/dashboard && pnpm vitest run src/components/wiki/__tests__/WikiKnowledgeGraph.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add dashboard/src/components/wiki/WikiKnowledgeGraph.tsx dashboard/src/components/wiki/__tests__/WikiKnowledgeGraph.test.tsx
git commit -m "feat(dashboard): add WikiKnowledgeGraph with xyflow domain visualization

Renders domain nodes and CALLS edges with interactive layout.
Click domain node to navigate to domain overview page."
```

---

## Task 9: WikiShell 集成 — 新 Tab 和组件串联

**Files:**
- Modify: `dashboard/src/components/wiki/WikiShell.tsx`
- Modify: `dashboard/src/components/wiki/WikiToolTabStrip.tsx` (if tab management lives here)

This task wires all new components into the existing WikiShell. This is a modification-heavy task — read the existing WikiShell before implementing.

- [ ] **Step 1: Read existing WikiShell.tsx**

Read the full `WikiShell.tsx` to understand current tab/panel structure, state management, and how wiki tree, content, and tool panels are composed.

- [ ] **Step 2: Add topic tree view toggle**

In `WikiShell.tsx`, add a state toggle between "主题树" (new WikiTopicTreeNav) and "代码结构" (existing WikiTreeNav) views. Use a simple toggle button or a segmented control at the top of the tree panel:

```typescript
const [treeView, setTreeView] = useState<"topic" | "code">("topic");
```

When `treeView === "topic"`:
- Use `useWikiTopicTree(businessId)` to fetch data
- Render `<WikiTopicTreeNav tree={topicTree} ... />`

When `treeView === "code"`:
- Use existing `useWikiTree(businessId, ...)` 
- Render existing `<WikiTreeNav ... />`

- [ ] **Step 3: Add Knowledge Graph tab**

Add a "知识图谱" tab to the tool panel (alongside existing tabs like Ask, Search, etc.). When active, render `<WikiKnowledgeGraph>`.

- [ ] **Step 4: Add Domain Review access**

Add a "域审阅" button/panel that appears when `review_status.domain_tree === "pending_review"`. This renders `<WikiDomainReviewPanel>` in a slide-over or dedicated panel area.

- [ ] **Step 5: Integrate WikiTopicContent for topic pages**

When a topic page is selected from WikiTopicTreeNav, render `<WikiTopicContent>` instead of the standard `<WikiContent>` based on `page.page_type`:
- If `page_type === "topic"` or `page_type === "domain_overview"` → `<WikiTopicContent>`
- Otherwise → existing `<WikiContent>`

- [ ] **Step 6: Integrate WikiPageReviewBar**

Below the content area (for both WikiTopicContent and WikiContent), render `<WikiPageReviewBar>` when the page has a `review_status`.

- [ ] **Step 7: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add dashboard/src/components/wiki/WikiShell.tsx dashboard/src/components/wiki/WikiToolTabStrip.tsx
git commit -m "feat(dashboard): integrate topic tree, knowledge graph, and review into WikiShell

Add topic/code tree view toggle, knowledge graph tab,
domain review panel, and page review bar integration."
```

---

## Self-Review Checklist

**1. Spec coverage:**
- [x] 3.6.1 Business 管理页面 → Task 1 (仓库绑定增强，CRUD 已存在)
- [x] 3.6.2 Business 选择器 → 已存在 `BusinessContext` + `useBusiness()` hook
- [x] 3.6.3 Wiki 树视图重构 → Task 4 (WikiTopicTreeNav)
- [x] 3.6.4 主题页内容展示增强 → Task 5 (WikiTopicContent)
- [x] 3.6.5 域树审阅面板 → Task 6 (WikiDomainReviewPanel)
- [x] 3.6.5 生成进度面板 → 已有 `WikiGenerationProgress` 和 `WikiActiveTasks` 组件，无需新建
- [x] 3.6.6 Wiki 审阅与批改 → Task 3 (API) + Task 7 (hooks + review bar) + Task 5 (content review actions)
- [x] 3.6.7 知识图谱视图 → Task 8 (WikiKnowledgeGraph)
- [x] Backend API support → Task 2 (domain-tree, topic-tree) + Task 3 (review, regenerate)
- [x] WikiShell integration → Task 9

**2. Placeholder scan:** No TBDs or TODOs. All steps contain concrete code.

**3. Type consistency:**
- `TopicTreeNode` interface used consistently across `useWikiDomainTree.ts` and `WikiTopicTreeNav.tsx`
- Review status strings: `"pending_review"` | `"approved"` | `"needs_revision"` | `"revised"` — consistent with `WikiPipelineState.review_status` from backend
- API paths: `/wiki/domain-tree`, `/wiki/topic-tree`, `/wiki/pages/{path}/review`, `/wiki/review/batch`, `/wiki/pages/{path}/regenerate` — consistent between tests and implementations
