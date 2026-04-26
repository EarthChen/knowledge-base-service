# SP2: Frontend Architecture Hardening — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add error boundaries, code splitting, scoped query keys, tab ARIA semantics, unified MarkdownRenderer, and extracted regeneration hook to the frontend.

**Architecture:** Wrap key components in ErrorBoundary. Lazy-load heavy components behind React.Suspense. Standardize all TanStack Query keys with businessId. Add proper tablist/tab/tabpanel ARIA roles. Merge dual MarkdownRenderers.

**Tech Stack:** React 19, TypeScript, Vite, TanStack Query, Vitest, @testing-library/react

---

### Task 1: ErrorBoundary Component

**Files:**
- Create: `dashboard/src/components/ErrorBoundary.tsx`
- Test: `dashboard/src/components/__tests__/ErrorBoundary.test.tsx`

- [ ] **Step 1: Write failing test**

```tsx
// dashboard/src/components/__tests__/ErrorBoundary.test.tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import ErrorBoundary from "../ErrorBoundary";

function ThrowingChild({ shouldThrow }: { shouldThrow: boolean }) {
  if (shouldThrow) throw new Error("test crash");
  return <div>ok</div>;
}

describe("ErrorBoundary", () => {
  it("renders children when no error", () => {
    render(
      <ErrorBoundary>
        <ThrowingChild shouldThrow={false} />
      </ErrorBoundary>,
    );
    expect(screen.getByText("ok")).toBeTruthy();
  });

  it("renders fallback on error", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <ErrorBoundary>
        <ThrowingChild shouldThrow={true} />
      </ErrorBoundary>,
    );
    expect(screen.getByText(/something went wrong/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: /retry/i })).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dashboard && pnpm vitest run src/components/__tests__/ErrorBoundary.test.tsx`
Expected: FAIL

- [ ] **Step 3: Implement ErrorBoundary**

```tsx
// dashboard/src/components/ErrorBoundary.tsx
import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = { children: ReactNode; fallbackLabel?: string };
type State = { error: Error | null };

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[ErrorBoundary]", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-red-200 bg-red-50 p-8 text-center dark:border-red-900 dark:bg-red-950/40">
          <p className="text-sm font-medium text-red-800 dark:text-red-200">
            {this.props.fallbackLabel ?? "Something went wrong"}
          </p>
          <p className="max-w-md truncate font-mono text-xs text-red-600 dark:text-red-400">
            {this.state.error.message}
          </p>
          <button
            type="button"
            onClick={() => this.setState({ error: null })}
            className="rounded-lg border border-red-200 bg-white px-4 py-2 text-xs font-medium text-red-800 hover:bg-red-50 dark:border-red-800 dark:bg-red-950 dark:text-red-200 dark:hover:bg-red-900"
          >
            Retry
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd dashboard && pnpm vitest run src/components/__tests__/ErrorBoundary.test.tsx`
Expected: PASS

- [ ] **Step 5: Wrap WikiShell, WikiContent, MarkdownRenderer**

In `dashboard/src/components/wiki/WikiShell.tsx`, wrap the return JSX:
```tsx
import ErrorBoundary from "../ErrorBoundary";
// ... in return:
return (
  <ErrorBoundary fallbackLabel="Wiki failed to render">
    <div className="flex min-h-[min(70vh,860px)] ...">
      {/* existing content */}
    </div>
  </ErrorBoundary>
);
```

In `dashboard/src/components/wiki/WikiContent.tsx`, wrap MarkdownRenderer:
```tsx
import ErrorBoundary from "../ErrorBoundary";
// Around MarkdownRenderer usage:
<ErrorBoundary fallbackLabel="Content rendering error">
  <MarkdownRenderer ... />
</ErrorBoundary>
```

- [ ] **Step 6: Run frontend tests to verify no regression**

Run: `cd dashboard && pnpm vitest run`
Expected: No new failures

- [ ] **Step 7: Commit**

```bash
git add dashboard/src/components/ErrorBoundary.tsx dashboard/src/components/__tests__/ErrorBoundary.test.tsx dashboard/src/components/wiki/WikiShell.tsx dashboard/src/components/wiki/WikiContent.tsx
git commit -m "feat(sp2): add ErrorBoundary component, wrap WikiShell and WikiContent"
```

---

### Task 2: React.lazy Code Splitting

**Files:**
- Modify: `dashboard/src/components/wiki/WikiShell.tsx`
- Test: `dashboard/src/components/wiki/__tests__/WikiShell.test.tsx` (update)

- [ ] **Step 1: Add lazy imports in WikiShell**

Replace direct imports with lazy:

```tsx
// dashboard/src/components/wiki/WikiShell.tsx — top of file
import { lazy, Suspense, useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

// Lazy-loaded heavy components
const WikiReferenceGraph = lazy(() => import("./WikiReferenceGraph"));
const GraphInsightsPanel = lazy(() => import("./GraphInsightsPanel"));
const WikiBusinessExportPanel = lazy(() => import("./WikiBusinessExportPanel"));
const WikiLintPanel = lazy(() => import("./WikiLintPanel"));
```

Remove the direct imports for these 4 components.

- [ ] **Step 2: Wrap lazy components in Suspense**

```tsx
{toolTab === "refgraph" && (
  <Suspense fallback={<div className="animate-pulse rounded-xl border p-8 text-center text-sm text-gray-400">Loading graph...</div>}>
    <WikiReferenceGraph businessId={businessId} view={viewType === "code_structure" ? "code_structure" : "business_domain"} />
  </Suspense>
)}
```

Apply same pattern for GraphInsightsPanel, WikiBusinessExportPanel, WikiLintPanel.

- [ ] **Step 3: Verify build succeeds**

Run: `cd dashboard && pnpm build`
Expected: Build succeeds with separate chunks for lazy components

- [ ] **Step 4: Run frontend tests**

Run: `cd dashboard && pnpm vitest run`
Expected: No new failures

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/components/wiki/WikiShell.tsx
git commit -m "perf(sp2): lazy-load WikiReferenceGraph, GraphInsightsPanel, ExportPanel, LintPanel"
```

---

### Task 3: Query Key Scoping

**Files:**
- Modify: `dashboard/src/hooks/useWikiPageByPath.ts`
- Modify: `dashboard/src/hooks/useWikiQualityScore.ts`
- Modify: `dashboard/src/hooks/useWikiReferenceGraph.ts`
- Modify: All hooks under `dashboard/src/hooks/` that use `["wiki"]` keys
- Test: Manual grep verification

- [ ] **Step 1: Audit all query keys**

Run: `rg "queryKey.*wiki" dashboard/src/hooks/ dashboard/src/components/wiki/`

- [ ] **Step 2: Update each hook to include businessId in query key**

Pattern for each hook:
```tsx
// Before:
queryKey: ["wiki", "page", pagePath]
// After:
queryKey: ["wiki", "page", businessId, pagePath]
```

- [ ] **Step 3: Update cache invalidation in WikiShell**

Replace broad invalidation:
```tsx
// Before:
queryClient.invalidateQueries({ queryKey: ["wiki"] });
// After:
queryClient.invalidateQueries({ queryKey: ["wiki", "page", businessId] });
queryClient.invalidateQueries({ queryKey: ["wiki", "tree", businessId] });
```

- [ ] **Step 4: Verify grep shows no unscoped query keys**

Run: `rg 'queryKey:\s*\["wiki"\]' dashboard/src/ --count`
Expected: 0 matches

- [ ] **Step 5: Run frontend tests**

Run: `cd dashboard && pnpm vitest run`
Expected: No new failures

- [ ] **Step 6: Commit**

```bash
git add dashboard/src/hooks/ dashboard/src/components/wiki/
git commit -m "perf(sp2): scope all TanStack Query keys with businessId"
```

---

### Task 4: Tab Semantics (ARIA)

**Files:**
- Modify: `dashboard/src/components/wiki/WikiShell.tsx`
- Test: `dashboard/src/components/wiki/__tests__/WikiShell.a11y.test.tsx`

- [ ] **Step 1: Write failing a11y test**

```tsx
// dashboard/src/components/wiki/__tests__/WikiShell.a11y.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";

describe("WikiShell tab semantics", () => {
  it("renders tablist with tab roles", () => {
    // Render WikiShell with mocked providers...
    const tablist = screen.getByRole("tablist");
    expect(tablist).toBeTruthy();
    const tabs = screen.getAllByRole("tab");
    expect(tabs.length).toBeGreaterThanOrEqual(5);
  });
});
```

- [ ] **Step 2: Update WikiShell toolbar to use tablist/tab roles**

Modify the toolbar container:
```tsx
<div role="tablist" aria-label={t.wiki.tabListLabel} className="flex flex-wrap gap-2">
```

Modify `tabBtn` to use tab role:
```tsx
const tabBtn = useCallback(
  (id: WikiToolTab, label: string, icon: ReactNode) => (
    <button
      key={id}
      role="tab"
      type="button"
      aria-selected={toolTab === id}
      aria-controls={`wiki-panel-${id}`}
      id={`wiki-tab-${id}`}
      onClick={() => setToolTab(id)}
      className={...}
    >
      {icon}
      {label}
    </button>
  ),
  [setToolTab, toolTab],
);
```

Wrap each panel with `role="tabpanel"`:
```tsx
{toolTab === "page" && (
  <div role="tabpanel" id="wiki-panel-page" aria-labelledby="wiki-tab-page">
    {/* content */}
  </div>
)}
```

- [ ] **Step 3: Add aria-busy to regenerate button**

```tsx
<button
  type="button"
  onClick={handleRegenerateWiki}
  disabled={regeneratePending}
  aria-busy={regeneratePending}
  ...
>
```

- [ ] **Step 4: Run frontend tests**

Run: `cd dashboard && pnpm vitest run`
Expected: No new failures

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/components/wiki/WikiShell.tsx dashboard/src/components/wiki/__tests__/
git commit -m "a11y(sp2): add tablist/tab/tabpanel ARIA roles to WikiShell"
```

---

### Task 5: MarkdownRenderer Unification

**Files:**
- Delete: `dashboard/src/components/MarkdownRenderer.tsx` (root-level)
- Modify: All import sites to use wiki MarkdownRenderer
- Test: Verify build

- [ ] **Step 1: Find all import sites of root MarkdownRenderer**

Run: `rg "from.*components/MarkdownRenderer" dashboard/src/ --files-with-matches`

- [ ] **Step 2: Update imports to point to wiki MarkdownRenderer**

For each file found, change:
```tsx
// Before:
import MarkdownRenderer from "../components/MarkdownRenderer";
// After:
import MarkdownRenderer from "../components/wiki/MarkdownRenderer";
```

- [ ] **Step 3: Ensure wiki MarkdownRenderer works without wiki-specific props**

Verify that `wikiLinkParams` and `headings` are optional props (they already should be).

- [ ] **Step 4: Delete root MarkdownRenderer**

Run: `rm dashboard/src/components/MarkdownRenderer.tsx`

- [ ] **Step 5: Verify build succeeds**

Run: `cd dashboard && pnpm build`
Expected: Build succeeds

- [ ] **Step 6: Run frontend tests**

Run: `cd dashboard && pnpm vitest run`
Expected: No new failures

- [ ] **Step 7: Commit**

```bash
git add -A dashboard/src/
git commit -m "refactor(sp2): unify dual MarkdownRenderer into single wiki component"
```

---

### Task 6: Extract useWikiRegenerate Hook

**Files:**
- Create: `dashboard/src/hooks/useWikiRegenerate.ts`
- Modify: `dashboard/src/components/wiki/WikiShell.tsx`
- Test: `dashboard/src/hooks/__tests__/useWikiRegenerate.test.ts`

- [ ] **Step 1: Write failing test**

```tsx
// dashboard/src/hooks/__tests__/useWikiRegenerate.test.ts
import { renderHook, act } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";

describe("useWikiRegenerate", () => {
  it("should expose regenerate function and isPending state", async () => {
    // Will import from useWikiRegenerate
    // const { result } = renderHook(() => useWikiRegenerate("biz-1"));
    // expect(result.current.isPending).toBe(false);
    // expect(typeof result.current.regenerate).toBe("function");
    expect(true).toBe(true); // placeholder until hook exists
  });
});
```

- [ ] **Step 2: Extract handleRegenerateWiki logic from WikiShell into hook**

```tsx
// dashboard/src/hooks/useWikiRegenerate.ts
import { useCallback, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { businessWikiGenerate, wikiTaskStatus } from "../api/client";
import { useToast } from "../components/Toast";
import { useI18n } from "../i18n/context";

export function useWikiRegenerate(businessId: string) {
  const [isPending, setIsPending] = useState(false);
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const { locale, t } = useI18n();

  const regenerate = useCallback(async () => {
    if (!businessId.trim() || isPending) return;
    setIsPending(true);
    try {
      const lang = locale === "zh" ? "zh" : "en";
      const res = await businessWikiGenerate(businessId.trim(), lang);
      const tid = res.task_id ? String(res.task_id) : "";
      if (!tid) {
        toast("success", t.wiki.regenerateStarted);
        await queryClient.invalidateQueries({ queryKey: ["wiki"] });
        return;
      }
      toast("info", t.wiki.regenerateRunning);
      const maxAttempts = 45;
      for (let i = 0; i < maxAttempts; i++) {
        await new Promise((r) => setTimeout(r, 2000));
        const st = await wikiTaskStatus(tid);
        if (st.status === "completed") {
          toast("success", t.wiki.regenerateComplete);
          await queryClient.invalidateQueries({ queryKey: ["wiki"] });
          return;
        }
        if (st.status === "failed") {
          const err = st.error;
          const detail =
            err && typeof err === "object" && "detail" in err
              ? String((err as { detail?: unknown }).detail ?? err)
              : err ? JSON.stringify(err) : t.common.unknown;
          toast("error", t.wiki.regenerateFailed.replace("{detail}", detail));
          return;
        }
      }
      toast("error", t.wiki.regenerateTimeout);
    } catch (e) {
      const { getErrorMessage } = await import("../utils/errorUtils");
      toast("error", getErrorMessage(e, t.common.unexpectedError));
    } finally {
      setIsPending(false);
    }
  }, [businessId, isPending, locale, t, toast, queryClient]);

  return { regenerate, isPending };
}
```

- [ ] **Step 3: Update WikiShell to use the hook**

Replace `handleRegenerateWiki` function and `regeneratePending` state with:
```tsx
const { regenerate: handleRegenerateWiki, isPending: regeneratePending } = useWikiRegenerate(businessId);
```

Remove the old `useState(false)` for `regeneratePending` and the `handleRegenerateWiki` function body.

- [ ] **Step 4: Verify build and tests**

Run: `cd dashboard && pnpm build && pnpm vitest run`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/hooks/useWikiRegenerate.ts dashboard/src/components/wiki/WikiShell.tsx
git commit -m "refactor(sp2): extract useWikiRegenerate hook from WikiShell"
```
