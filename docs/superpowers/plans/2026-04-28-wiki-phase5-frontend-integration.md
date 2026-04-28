# Wiki Phase 5: Frontend Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update the React dashboard to consume new backend data from Phases 1-4: enhanced navigation (NavigationContext), business flow view, quality score display, incremental update trigger, and multi-phase SSE progress reporting.

**Architecture:** The dashboard already has many relevant components:
- `WikiBreadcrumbs.tsx` — breadcrumbs (needs backend NavigationContext integration)
- `WikiActiveTasks.tsx` — active task display with cancel (already implemented)
- `WikiTreeNav` — tree navigation with code_structure/business_domain tabs
- `WikiBusinessFlowGraph.tsx` — business flow graph rendering
- `WikiReferencesPanel.tsx` — references panel
- `useWikiQualityScore.ts` — quality score hook
- `useBusinessFlows.ts` — business flows hook

Phase 5 focuses on **enhancing existing components** with new data, not building from scratch.

**Tech Stack:** React, TypeScript, TanStack Query, Tailwind CSS, Lucide icons

**Spec:** [`docs/superpowers/specs/2026-04-28-wiki-hierarchical-generation-design.md`](../specs/2026-04-28-wiki-hierarchical-generation-design.md)

**Depends on:** Phases 1-2 for navigation data, Phase 3 for incremental API, Phase 4 for quality API. Can be implemented in parallel with backend phases using mock data.

---

## File Structure

| File | Change | Backend Dependency |
|------|--------|--------------------|
| `dashboard/src/components/wiki/WikiBreadcrumbs.tsx` (modify) | Use NavigationContext from API | Phase 2 |
| `dashboard/src/components/wiki/WikiNavigationLinks.tsx` (create) | Parent/sibling/child navigation links | Phase 2 |
| `dashboard/src/components/wiki/WikiContent.tsx` (modify) | Render navigation + cross-view links | Phase 2 |
| `dashboard/src/components/wiki/WikiBusinessFlowGraph.tsx` (modify) | Render community-based business flow pages | Phase 2 |
| `dashboard/src/components/wiki/WikiQualityBadge.tsx` (create) | Quality score badge on wiki pages | Phase 4 |
| `dashboard/src/components/wiki/WikiQualitySummary.tsx` (create) | Repository-level quality summary card | Phase 4 |
| `dashboard/src/hooks/useWikiNavigation.ts` (create) | Fetch NavigationContext for a page | Phase 2 |
| `dashboard/src/hooks/useWikiQualityScore.ts` (modify) | Use new quality evaluation API | Phase 4 |
| `dashboard/src/components/wiki/WikiActiveTasks.tsx` (modify) | Show multi-phase progress | Phase 1 |
| `dashboard/src/components/wiki/WikiIncrementalTrigger.tsx` (create) | Button to trigger incremental update | Phase 3 |
| `dashboard/src/hooks/useWikiIncremental.ts` (create) | Mutation hook for incremental generation | Phase 3 |

---

### Task 1: Enhance WikiBreadcrumbs with NavigationContext

**Files:**
- Modify: `dashboard/src/components/wiki/WikiBreadcrumbs.tsx`
- Create: `dashboard/src/hooks/useWikiNavigation.ts`

Currently, `WikiBreadcrumbs` derives breadcrumbs from the URL path segments. After Phase 2,
the backend provides `NavigationContext.breadcrumbs` with proper titles and paths.

- [ ] **Step 1: Create useWikiNavigation hook**

```typescript
// dashboard/src/hooks/useWikiNavigation.ts
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

interface NavigationContext {
  parent_path: string | null;
  parent_title: string | null;
  sibling_paths: string[];
  child_paths: string[];
  related_flow_paths: string[];
  breadcrumbs: Array<[string, string]>; // [title, path]
}

export function useWikiNavigation(repository: string, pagePath: string) {
  return useQuery<NavigationContext>({
    queryKey: ["wiki", "navigation", repository, pagePath],
    queryFn: () =>
      api<NavigationContext>(
        `/wiki/navigation?repository=${encodeURIComponent(repository)}&path=${encodeURIComponent(pagePath)}`
      ),
    enabled: !!repository && !!pagePath,
    staleTime: 300_000, // 5 minutes
  });
}
```

- [ ] **Step 2: Update WikiBreadcrumbs to use NavigationContext when available**

```typescript
// Use NavigationContext breadcrumbs if available, fallback to path-based
const { data: navCtx } = useWikiNavigation(repository, path);
const breadcrumbs = navCtx?.breadcrumbs
  ? navCtx.breadcrumbs.map(([title, p]) => ({ label: title, path: p }))
  : segments.map((seg, i) => ({
      label: decodeURIComponent(seg),
      path: segments.slice(0, i + 1).join("/"),
    }));
```

- [ ] **Step 3: Test and commit**

---

### Task 2: Create WikiNavigationLinks component

**Files:**
- Create: `dashboard/src/components/wiki/WikiNavigationLinks.tsx`

- [ ] **Step 1: Implement navigation links section**

```tsx
// dashboard/src/components/wiki/WikiNavigationLinks.tsx
import { ArrowUp, ArrowRight, ArrowDown, GitBranch } from "lucide-react";
import { Link } from "react-router-dom";
import { wikiHref } from "./wikiRouteHelpers";
import { useWikiNavigation } from "../../hooks/useWikiNavigation";
import { useI18n } from "../../i18n/context";

type Props = {
  repository: string;
  pagePath: string;
};

export default function WikiNavigationLinks({ repository, pagePath }: Props) {
  const { data: nav, isLoading } = useWikiNavigation(repository, pagePath);
  const { t } = useI18n();

  if (isLoading || !nav) return null;

  return (
    <div className="mt-6 space-y-3 border-t border-gray-200 pt-4 dark:border-gray-700">
      {nav.parent_path && (
        <div className="flex items-center gap-2 text-sm">
          <ArrowUp size={14} className="text-gray-500" />
          <span className="text-gray-500">Parent:</span>
          <Link
            to={wikiHref(nav.parent_path)}
            className="text-blue-600 hover:underline dark:text-blue-400"
          >
            {nav.parent_title || nav.parent_path}
          </Link>
        </div>
      )}
      {nav.sibling_paths.length > 0 && (
        <div className="text-sm">
          <div className="flex items-center gap-2 text-gray-500">
            <ArrowRight size={14} />
            <span>Siblings:</span>
          </div>
          <ul className="ml-6 mt-1 space-y-0.5">
            {nav.sibling_paths.map((p) => (
              <li key={p}>
                <Link to={wikiHref(p)} className="text-blue-600 hover:underline dark:text-blue-400">
                  {p.split("/").pop()}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
      {nav.child_paths.length > 0 && (
        <div className="text-sm">
          <div className="flex items-center gap-2 text-gray-500">
            <ArrowDown size={14} />
            <span>Children:</span>
          </div>
          <ul className="ml-6 mt-1 space-y-0.5">
            {nav.child_paths.map((p) => (
              <li key={p}>
                <Link to={wikiHref(p)} className="text-blue-600 hover:underline dark:text-blue-400">
                  {p.split("/").pop()}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
      {nav.related_flow_paths.length > 0 && (
        <div className="text-sm">
          <div className="flex items-center gap-2 text-gray-500">
            <GitBranch size={14} />
            <span>Business Flows:</span>
          </div>
          <ul className="ml-6 mt-1 space-y-0.5">
            {nav.related_flow_paths.map((p) => (
              <li key={p}>
                <Link to={wikiHref(p)} className="text-blue-600 hover:underline dark:text-blue-400">
                  {p.split("/").pop()?.replace(".md", "")}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Integrate into WikiContent.tsx**
- [ ] **Step 3: Test and commit**

---

### Task 3: Create WikiQualityBadge and WikiQualitySummary

**Files:**
- Create: `dashboard/src/components/wiki/WikiQualityBadge.tsx`
- Create: `dashboard/src/components/wiki/WikiQualitySummary.tsx`
- Modify: `dashboard/src/hooks/useWikiQualityScore.ts`

- [ ] **Step 1: Update quality score hook to use new API**

```typescript
// Extend to support new quality evaluation API
export function useWikiQualitySummary(repository: string) {
  return useQuery<QualitySummary>({
    queryKey: ["wiki", "quality", "summary", repository],
    queryFn: () =>
      api<QualitySummary>(`/wiki/quality/summary?repository=${encodeURIComponent(repository)}`),
    enabled: !!repository,
    staleTime: 120_000,
  });
}

interface QualitySummary {
  avg_score: number;
  evaluated_count: number;
  low_quality_count: number;
}
```

- [ ] **Step 2: Create WikiQualityBadge**

```tsx
// Small badge showing quality score on individual wiki pages
type Props = { score: number };

export default function WikiQualityBadge({ score }: Props) {
  const color = score >= 0.8 ? "green" : score >= 0.6 ? "yellow" : "red";
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium
      ${color === "green" ? "bg-green-100 text-green-800" : ""}
      ${color === "yellow" ? "bg-yellow-100 text-yellow-800" : ""}
      ${color === "red" ? "bg-red-100 text-red-800" : ""}
    `}>
      Quality: {(score * 100).toFixed(0)}%
    </span>
  );
}
```

- [ ] **Step 3: Create WikiQualitySummary card for repository overview**
- [ ] **Step 4: Test and commit**

---

### Task 4: Multi-phase SSE progress in WikiActiveTasks

**Files:**
- Modify: `dashboard/src/components/wiki/WikiActiveTasks.tsx`

- [ ] **Step 1: Extend task progress display to show phases**

The backend now sends phase-level progress events. Update the task list to display:
- Current phase (leaf_compose / parent_aggregate / business_flow / quality_eval)
- Phase-specific progress (e.g., "Leaf compose: 120/500 pages")
- Overall progress bar

```typescript
interface PhaseProgress {
  phase: string;
  status: "started" | "completed";
  count?: number;
  pages_composed?: number;
}

// In the task card render:
{task.current_phase && (
  <div className="mt-1 text-xs text-gray-500">
    Phase: {phaseLabel(task.current_phase)}
    {task.phase_progress && ` (${task.phase_progress}%)`}
  </div>
)}
```

- [ ] **Step 2: Test and commit**

---

### Task 5: Create WikiIncrementalTrigger

**Files:**
- Create: `dashboard/src/components/wiki/WikiIncrementalTrigger.tsx`
- Create: `dashboard/src/hooks/useWikiIncremental.ts`

- [ ] **Step 1: Create mutation hook**

```typescript
// dashboard/src/hooks/useWikiIncremental.ts
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";

export function useWikiIncremental(repository: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      api("/wiki/generate-incremental", {
        method: "POST",
        body: JSON.stringify({ repository }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["wiki"] });
    },
  });
}
```

- [ ] **Step 2: Create trigger button component**

```tsx
// Dashboard button to trigger incremental wiki update
export default function WikiIncrementalTrigger({ repository }: { repository: string }) {
  const { mutate, isPending, data } = useWikiIncremental(repository);

  return (
    <button
      onClick={() => mutate()}
      disabled={isPending}
      className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
    >
      {isPending ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
      Incremental Update
    </button>
  );
}
```

- [ ] **Step 3: Test and commit**

---

### Task 6: Backend API endpoints for frontend

**Files:**
- Modify: `api/routes/wiki_routes.py` — add `/wiki/navigation` endpoint

The frontend hooks expect certain API endpoints. Ensure these exist:

- [ ] **Step 1: `/wiki/navigation` endpoint (for Task 1)**

```python
@router.get("/navigation")
async def get_wiki_navigation(
    repository: str = Query(...),
    path: str = Query(...),
    wiki_service: WikiService = Depends(get_wiki_service),
):
    """Get NavigationContext for a specific wiki page."""
    # Load from stored wiki page metadata
    wiki_store = WikiStore(wiki_service._store)
    page = await wiki_store.get_wiki_page(repository, path)
    if not page or not page.navigation:
        return NavigationContext()
    return page.navigation
```

- [ ] **Step 2: Verify `/wiki/quality/summary` exists (Task 3)**
- [ ] **Step 3: Verify `/wiki/generate-incremental` exists (Task 5)**
- [ ] **Step 4: Test and commit**

---

## Self-Review Checklist

- [x] Enhanced breadcrumbs with NavigationContext: Task 1
- [x] Parent/sibling/child/flow navigation links: Task 2
- [x] Quality score display (page + repo level): Task 3
- [x] Multi-phase SSE progress: Task 4
- [x] Incremental update trigger: Task 5
- [x] Backend API endpoints: Task 6
- [x] Uses existing components where possible (WikiBreadcrumbs, WikiActiveTasks, etc.)
- [x] Hooks follow existing patterns (TanStack Query, api helper)
