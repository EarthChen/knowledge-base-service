# Wiki Frontend Phase 8-11: Editing, Version Diff, SSE, Extended Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add wiki content editing/annotation capabilities, version comparison UI, real-time SSE update notifications, and comprehensive test coverage for all new components.

**Architecture:** Phase 8 adds an annotation layer over wiki content (text selection → comment) plus "Edit on Git" link. Phase 9 adds version history timeline and diff viewer using react-diff-viewer-continued. Phase 10 adds SSE-based real-time wiki update notifications. Phase 11 extends the test suite to cover all Phase 8-10 components.

**Tech Stack:** React 19, TypeScript 5.9, @tanstack/react-query 5, react-diff-viewer-continued, EventSource API, Vitest, @testing-library/react, lucide-react, Tailwind CSS 4

**Depends on:** FE-Phase 1-7 (all infrastructure, components, and base tests)

**Backend Dependencies:** Phase 8 requires annotation API, Phase 9 requires version history API, Phase 10 requires SSE endpoint. These backend APIs are listed in the spec's "后端补充需求" section. Frontend work can proceed with MSW mocks while backend is developed in parallel.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `dashboard/src/components/wiki/WikiEditButton.tsx` | "Edit on Git" button |
| Create | `dashboard/src/components/wiki/WikiAnnotationLayer.tsx` | Text selection annotation overlay |
| Create | `dashboard/src/components/wiki/WikiAnnotationSidebar.tsx` | Annotation comments sidebar |
| Create | `dashboard/src/hooks/useWikiAnnotations.ts` | Annotation CRUD hook |
| Create | `dashboard/src/components/wiki/WikiVersionBadge.tsx` | Version number + timestamp badge |
| Create | `dashboard/src/components/wiki/WikiVersionHistory.tsx` | Version timeline |
| Create | `dashboard/src/components/wiki/WikiDiffViewer.tsx` | Side-by-side diff viewer |
| Create | `dashboard/src/hooks/useWikiVersions.ts` | Version history hook |
| Create | `dashboard/src/hooks/useWikiDiff.ts` | Version diff hook |
| Create | `dashboard/src/components/wiki/WikiUpdateNotification.tsx` | SSE update toast |
| Create | `dashboard/src/components/wiki/WikiGenerationProgress.tsx` | Generation progress bar |
| Create | `dashboard/src/hooks/useWikiEvents.ts` | SSE EventSource hook |
| Modify | `dashboard/src/components/wiki/WikiContent.tsx` | Integrate edit button, annotations, version badge |
| Modify | `dashboard/src/components/wiki/WikiShell.tsx` | Integrate SSE notifications |
| Create | `dashboard/src/components/wiki/__tests__/WikiEditButton.test.tsx` | Edit button test |
| Create | `dashboard/src/components/wiki/__tests__/WikiAnnotationLayer.test.tsx` | Annotation test |
| Create | `dashboard/src/components/wiki/__tests__/WikiVersionBadge.test.tsx` | Version badge test |
| Create | `dashboard/src/components/wiki/__tests__/WikiUpdateNotification.test.tsx` | Notification test |
| Create | `dashboard/src/hooks/__tests__/useWikiEvents.test.tsx` | SSE hook test |

---

### Task 1: Create useWikiAnnotations hook

**Files:**
- Create: `dashboard/src/hooks/useWikiAnnotations.ts`

- [ ] **Step 1: Create the hook**

```typescript
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { WikiAnnotation } from "./wikiTypes";

export function useWikiAnnotations(pageUid: string) {
  const queryClient = useQueryClient();
  const queryKey = ["wiki", "annotations", pageUid];

  const query = useQuery<WikiAnnotation[]>({
    queryKey,
    queryFn: () => api<WikiAnnotation[]>(`/wiki/pages/${encodeURIComponent(pageUid)}/annotations`),
    enabled: !!pageUid,
  });

  const create = useMutation({
    mutationFn: (body: {
      text_range_start: number;
      text_range_end: number;
      comment: string;
      author: string;
    }) =>
      api<WikiAnnotation>(`/wiki/pages/${encodeURIComponent(pageUid)}/annotations`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey }),
  });

  const remove = useMutation({
    mutationFn: (annotationId: string) =>
      api<void>(`/wiki/annotations/${encodeURIComponent(annotationId)}`, {
        method: "DELETE",
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey }),
  });

  return { ...query, create, remove };
}
```

- [ ] **Step 2: Verify TypeScript compilation**

Run: `cd dashboard && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/hooks/useWikiAnnotations.ts
git commit -m "feat(dashboard): add useWikiAnnotations CRUD hook"
```

---

### Task 2: Create WikiEditButton component

**Files:**
- Create: `dashboard/src/components/wiki/WikiEditButton.tsx`

- [ ] **Step 1: Create the component**

```typescript
import { ExternalLink } from "lucide-react";

interface WikiEditButtonProps {
  gitRemoteUrl?: string;
  branch?: string;
  exportPath?: string;
}

function buildEditUrl(remote: string, branch: string, filePath: string): string | null {
  try {
    let base = remote.replace(/\.git$/, "");
    if (base.startsWith("git@")) {
      base = base.replace("git@", "https://").replace(":", "/");
    }
    return `${base}/blob/${branch}/${filePath}`;
  } catch {
    return null;
  }
}

export default function WikiEditButton({ gitRemoteUrl, branch, exportPath }: WikiEditButtonProps) {
  if (!gitRemoteUrl || !exportPath) return null;

  const editUrl = buildEditUrl(gitRemoteUrl, branch || "main", exportPath);
  if (!editUrl) return null;

  return (
    <a
      href={editUrl}
      target="_blank"
      rel="noreferrer noopener"
      className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 transition-colors hover:bg-gray-50 hover:text-gray-900 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-300 dark:hover:bg-gray-800 dark:hover:text-gray-100"
    >
      <ExternalLink size={12} />
      Edit on Git
    </a>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add dashboard/src/components/wiki/WikiEditButton.tsx
git commit -m "feat(dashboard): add WikiEditButton for editing on Git"
```

---

### Task 3: Create WikiAnnotationLayer + WikiAnnotationSidebar

**Files:**
- Create: `dashboard/src/components/wiki/WikiAnnotationLayer.tsx`
- Create: `dashboard/src/components/wiki/WikiAnnotationSidebar.tsx`

- [ ] **Step 1: Create WikiAnnotationSidebar**

```typescript
import { Trash2 } from "lucide-react";
import type { WikiAnnotation } from "../../hooks/wikiTypes";

interface WikiAnnotationSidebarProps {
  annotations: WikiAnnotation[];
  onDelete: (id: string) => void;
  isDeleting: boolean;
}

export default function WikiAnnotationSidebar({
  annotations,
  onDelete,
  isDeleting,
}: WikiAnnotationSidebarProps) {
  if (annotations.length === 0) {
    return (
      <p className="px-4 py-6 text-center text-xs text-gray-500 dark:text-gray-400">
        No annotations yet. Select text to add one.
      </p>
    );
  }

  return (
    <div className="space-y-2 px-3 py-3">
      {annotations.map((a) => (
        <div
          key={a.annotation_id}
          className="rounded-lg border border-gray-100 bg-gray-50/50 p-3 dark:border-gray-800 dark:bg-gray-800/30"
        >
          <p className="text-sm text-gray-800 dark:text-gray-200">{a.comment}</p>
          <div className="mt-2 flex items-center justify-between text-[11px] text-gray-500 dark:text-gray-400">
            <span>{a.author} &middot; {new Date(a.created_at).toLocaleDateString()}</span>
            <button
              type="button"
              onClick={() => onDelete(a.annotation_id)}
              disabled={isDeleting}
              className="rounded p-1 text-gray-400 hover:bg-red-50 hover:text-red-600 disabled:opacity-50 dark:hover:bg-red-950 dark:hover:text-red-400"
            >
              <Trash2 size={12} />
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Create WikiAnnotationLayer**

```typescript
import { useCallback, useState } from "react";
import { MessageSquarePlus } from "lucide-react";

interface WikiAnnotationLayerProps {
  onAddAnnotation: (range: { start: number; end: number; comment: string }) => void;
}

export default function WikiAnnotationLayer({ onAddAnnotation }: WikiAnnotationLayerProps) {
  const [showInput, setShowInput] = useState(false);
  const [comment, setComment] = useState("");
  const [selection, setSelection] = useState<{ start: number; end: number } | null>(null);

  const handleMouseUp = useCallback(() => {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || !sel.toString().trim()) {
      return;
    }
    const range = sel.getRangeAt(0);
    setSelection({
      start: range.startOffset,
      end: range.endOffset,
    });
    setShowInput(true);
  }, []);

  const handleSubmit = () => {
    if (!selection || !comment.trim()) return;
    onAddAnnotation({ start: selection.start, end: selection.end, comment: comment.trim() });
    setShowInput(false);
    setComment("");
    setSelection(null);
  };

  const handleCancel = () => {
    setShowInput(false);
    setComment("");
    setSelection(null);
  };

  return (
    <>
      <div onMouseUp={handleMouseUp} className="relative">
        {showInput && (
          <div className="absolute right-0 top-0 z-40 w-72 rounded-xl border border-gray-200 bg-white p-3 shadow-lg dark:border-gray-700 dark:bg-gray-900">
            <div className="flex items-center gap-2 text-xs font-semibold text-gray-700 dark:text-gray-300">
              <MessageSquarePlus size={14} />
              Add annotation
            </div>
            <textarea
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="Write a comment..."
              rows={3}
              className="mt-2 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:border-sky-400 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
            />
            <div className="mt-2 flex justify-end gap-2">
              <button
                type="button"
                onClick={handleCancel}
                className="rounded px-3 py-1.5 text-xs text-gray-600 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-800"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleSubmit}
                disabled={!comment.trim()}
                className="rounded bg-sky-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-sky-500 disabled:opacity-50"
              >
                Add
              </button>
            </div>
          </div>
        )}
      </div>
    </>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/components/wiki/WikiAnnotationLayer.tsx dashboard/src/components/wiki/WikiAnnotationSidebar.tsx
git commit -m "feat(dashboard): add WikiAnnotationLayer and WikiAnnotationSidebar"
```

---

### Task 4: Create version hooks and components

**Files:**
- Create: `dashboard/src/hooks/useWikiVersions.ts`
- Create: `dashboard/src/hooks/useWikiDiff.ts`
- Create: `dashboard/src/components/wiki/WikiVersionBadge.tsx`
- Create: `dashboard/src/components/wiki/WikiVersionHistory.tsx`
- Create: `dashboard/src/components/wiki/WikiDiffViewer.tsx`

- [ ] **Step 1: Create useWikiVersions hook**

```typescript
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { WikiVersion } from "./wikiTypes";

export function useWikiVersions(pageUid: string) {
  return useQuery<WikiVersion[]>({
    queryKey: ["wiki", "versions", pageUid],
    queryFn: () => api<WikiVersion[]>(`/wiki/pages/${encodeURIComponent(pageUid)}/versions`),
    enabled: !!pageUid,
  });
}
```

- [ ] **Step 2: Create useWikiDiff hook**

```typescript
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { WikiDiff } from "./wikiTypes";

export function useWikiDiff(pageUid: string, fromVersion: number, toVersion: number) {
  return useQuery<WikiDiff>({
    queryKey: ["wiki", "diff", pageUid, fromVersion, toVersion],
    queryFn: () =>
      api<WikiDiff>(
        `/wiki/pages/${encodeURIComponent(pageUid)}/diff?from=${fromVersion}&to=${toVersion}`,
      ),
    enabled: !!pageUid && fromVersion > 0 && toVersion > 0 && fromVersion !== toVersion,
  });
}
```

- [ ] **Step 3: Create WikiVersionBadge**

```typescript
import { Clock, History } from "lucide-react";

interface WikiVersionBadgeProps {
  version: number;
  generatedAt: string;
  onClick?: () => void;
}

export default function WikiVersionBadge({ version, generatedAt, onClick }: WikiVersionBadgeProps) {
  let formatted = generatedAt;
  try { formatted = new Date(generatedAt).toLocaleDateString(); } catch { /* keep raw */ }

  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center gap-1.5 rounded-full border border-gray-200 bg-gray-50 px-2.5 py-1 text-[11px] text-gray-600 transition-colors hover:bg-gray-100 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-400 dark:hover:bg-gray-700"
    >
      <History size={11} />
      v{version}
      <span className="text-gray-400 dark:text-gray-500">&middot;</span>
      <Clock size={11} />
      {formatted}
    </button>
  );
}
```

- [ ] **Step 4: Create WikiVersionHistory**

```typescript
import { Loader2 } from "lucide-react";
import type { WikiVersion } from "../../hooks/wikiTypes";
import { useWikiVersions } from "../../hooks/useWikiVersions";

interface WikiVersionHistoryProps {
  pageUid: string;
  onSelectVersions: (from: number, to: number) => void;
}

export default function WikiVersionHistory({ pageUid, onSelectVersions }: WikiVersionHistoryProps) {
  const { data: versions, isLoading } = useWikiVersions(pageUid);

  if (isLoading) {
    return <div className="flex justify-center py-4"><Loader2 className="size-5 animate-spin text-gray-400" /></div>;
  }

  if (!versions?.length) {
    return <p className="py-4 text-center text-xs text-gray-500">No version history available</p>;
  }

  return (
    <div className="space-y-2 py-2">
      {versions.map((v, i) => {
        const prev = versions[i + 1];
        return (
          <div key={v.version} className="flex items-center gap-3 rounded-lg px-3 py-2 hover:bg-gray-50 dark:hover:bg-gray-800">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-sky-50 text-xs font-bold text-sky-700 dark:bg-sky-950 dark:text-sky-300">
              v{v.version}
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-sm text-gray-900 dark:text-gray-100">{v.change_summary || "Updated"}</p>
              <p className="text-[11px] text-gray-500">{new Date(v.generated_at).toLocaleString()}</p>
            </div>
            {prev && (
              <button
                type="button"
                onClick={() => onSelectVersions(prev.version, v.version)}
                className="rounded px-2 py-1 text-[11px] font-medium text-sky-600 hover:bg-sky-50 dark:text-sky-400 dark:hover:bg-sky-950"
              >
                Diff
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 5: Create WikiDiffViewer**

First install react-diff-viewer-continued:
```bash
cd dashboard && pnpm add react-diff-viewer-continued
```

```typescript
import { Loader2 } from "lucide-react";
import { useWikiDiff } from "../../hooks/useWikiDiff";
import ReactDiffViewer from "react-diff-viewer-continued";

interface WikiDiffViewerProps {
  pageUid: string;
  fromVersion: number;
  toVersion: number;
}

export default function WikiDiffViewer({ pageUid, fromVersion, toVersion }: WikiDiffViewerProps) {
  const { data, isLoading, isError } = useWikiDiff(pageUid, fromVersion, toVersion);

  if (isLoading) {
    return <div className="flex justify-center py-8"><Loader2 className="size-5 animate-spin text-gray-400" /></div>;
  }

  if (isError || !data) {
    return <p className="py-4 text-center text-sm text-gray-500">Unable to load diff</p>;
  }

  const oldContent = data.hunks.map((h) => h.content.split("\n").filter((l) => l.startsWith("-") || l.startsWith(" ")).map((l) => l.slice(1)).join("\n")).join("\n");
  const newContent = data.hunks.map((h) => h.content.split("\n").filter((l) => l.startsWith("+") || l.startsWith(" ")).map((l) => l.slice(1)).join("\n")).join("\n");

  return (
    <div className="overflow-x-auto rounded-xl border border-gray-200 dark:border-gray-700">
      <ReactDiffViewer
        oldValue={oldContent}
        newValue={newContent}
        splitView
        leftTitle={`v${fromVersion}`}
        rightTitle={`v${toVersion}`}
      />
    </div>
  );
}
```

- [ ] **Step 6: Commit**

```bash
git add dashboard/src/hooks/useWikiVersions.ts \
       dashboard/src/hooks/useWikiDiff.ts \
       dashboard/src/components/wiki/WikiVersionBadge.tsx \
       dashboard/src/components/wiki/WikiVersionHistory.tsx \
       dashboard/src/components/wiki/WikiDiffViewer.tsx \
       dashboard/package.json dashboard/pnpm-lock.yaml
git commit -m "feat(dashboard): add version history, diff hooks and viewer components"
```

---

### Task 5: Create SSE hook and notification components

**Files:**
- Create: `dashboard/src/hooks/useWikiEvents.ts`
- Create: `dashboard/src/components/wiki/WikiUpdateNotification.tsx`
- Create: `dashboard/src/components/wiki/WikiGenerationProgress.tsx`

- [ ] **Step 1: Create useWikiEvents hook**

```typescript
import { useCallback, useEffect, useRef } from "react";
import { API_BASE } from "../api/client";
import type { WikiEvent } from "./wikiTypes";

export function useWikiEvents(
  businessId: string,
  onEvent: (event: WikiEvent) => void,
) {
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  const sourceRef = useRef<EventSource | null>(null);

  const connect = useCallback(() => {
    if (!businessId) return;
    const url = `${API_BASE}/wiki/events?business_id=${encodeURIComponent(businessId)}`;
    const source = new EventSource(url);

    source.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data) as WikiEvent;
        onEventRef.current(event);
      } catch {
        // ignore malformed events
      }
    };

    let retryDelay = 1000;
    source.onerror = () => {
      source.close();
      setTimeout(() => connect(), retryDelay);
      retryDelay = Math.min(retryDelay * 2, 30000);
    };

    sourceRef.current = source;
  }, [businessId]);

  useEffect(() => {
    connect();
    return () => sourceRef.current?.close();
  }, [connect]);
}
```

- [ ] **Step 2: Create WikiUpdateNotification**

```typescript
import { RefreshCw, X } from "lucide-react";

interface WikiUpdateNotificationProps {
  pagePath: string;
  onRefresh: () => void;
  onDismiss: () => void;
}

export default function WikiUpdateNotification({
  pagePath,
  onRefresh,
  onDismiss,
}: WikiUpdateNotificationProps) {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-sky-200 bg-sky-50 px-4 py-2.5 text-sm text-sky-800 dark:border-sky-800 dark:bg-sky-950/30 dark:text-sky-300">
      <RefreshCw size={16} className="shrink-0" />
      <span className="flex-1">
        Page <span className="font-medium">{pagePath.split("/").pop()}</span> has been updated.
      </span>
      <button
        type="button"
        onClick={onRefresh}
        className="rounded px-2 py-1 text-xs font-medium text-sky-700 hover:bg-sky-100 dark:text-sky-300 dark:hover:bg-sky-900"
      >
        Refresh
      </button>
      <button type="button" onClick={onDismiss} className="rounded p-1 text-sky-400 hover:text-sky-700 dark:hover:text-sky-200">
        <X size={14} />
      </button>
    </div>
  );
}
```

- [ ] **Step 3: Create WikiGenerationProgress**

```typescript
import { Loader2, CheckCircle, XCircle } from "lucide-react";
import type { WikiEventType } from "../../hooks/wikiTypes";

interface WikiGenerationProgressProps {
  status: WikiEventType | null;
}

export default function WikiGenerationProgress({ status }: WikiGenerationProgressProps) {
  if (!status) return null;

  const isRunning = status === "wiki:generation_started";
  const isDone = status === "wiki:generation_completed";
  const isFailed = status === "wiki:generation_failed";

  return (
    <div
      className={`flex items-center gap-2 rounded-lg border px-4 py-2.5 text-sm ${
        isFailed
          ? "border-red-200 bg-red-50 text-red-800 dark:border-red-800 dark:bg-red-950/30 dark:text-red-300"
          : isDone
            ? "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950/30 dark:text-emerald-300"
            : "border-sky-200 bg-sky-50 text-sky-800 dark:border-sky-800 dark:bg-sky-950/30 dark:text-sky-300"
      }`}
    >
      {isRunning && <Loader2 size={16} className="animate-spin" />}
      {isDone && <CheckCircle size={16} />}
      {isFailed && <XCircle size={16} />}
      <span>
        {isRunning && "Wiki generation in progress..."}
        {isDone && "Wiki generation completed"}
        {isFailed && "Wiki generation failed"}
      </span>
    </div>
  );
}
```

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/hooks/useWikiEvents.ts \
       dashboard/src/components/wiki/WikiUpdateNotification.tsx \
       dashboard/src/components/wiki/WikiGenerationProgress.tsx
git commit -m "feat(dashboard): add SSE hook and wiki update notification components"
```

---

### Task 6: Integrate Phase 8-10 into WikiContent and WikiShell

**Files:**
- Modify: `dashboard/src/components/wiki/WikiContent.tsx`
- Modify: `dashboard/src/components/wiki/WikiShell.tsx`

- [ ] **Step 1: Add WikiEditButton and WikiVersionBadge to WikiContent header**

Import at the top of `WikiContent.tsx`:

```typescript
import WikiEditButton from "./WikiEditButton";
import WikiVersionBadge from "./WikiVersionBadge";
```

In the header section, after the generatedAt display, add:

```typescript
            <div className="mt-2 flex flex-wrap items-center gap-2">
              {detail?.context?.version && (
                <WikiVersionBadge
                  version={Number(detail.context.version)}
                  generatedAt={detail.generated_at || ""}
                />
              )}
              <WikiEditButton
                gitRemoteUrl={detail?.context?.git_remote_url}
                branch={detail?.context?.git_branch}
                exportPath={detail?.context?.export_path}
              />
            </div>
```

- [ ] **Step 2: Add SSE notifications to WikiShell**

Import at the top of `WikiShell.tsx`:

```typescript
import { useWikiEvents } from "../../hooks/useWikiEvents";
import WikiUpdateNotification from "./WikiUpdateNotification";
import WikiGenerationProgress from "./WikiGenerationProgress";
import type { WikiEvent, WikiEventType } from "../../hooks/wikiTypes";
```

Add state and event handler:

```typescript
  const [updateNotification, setUpdateNotification] = useState<string | null>(null);
  const [generationStatus, setGenerationStatus] = useState<WikiEventType | null>(null);

  const handleWikiEvent = useCallback((event: WikiEvent) => {
    if (event.type === "wiki:page_updated" && event.page_path) {
      setUpdateNotification(event.page_path);
    } else if (event.type === "wiki:generation_started" || event.type === "wiki:generation_completed" || event.type === "wiki:generation_failed") {
      setGenerationStatus(event.type);
      if (event.type === "wiki:generation_completed") {
        queryClient.invalidateQueries({ queryKey: ["wiki"] });
      }
    }
  }, [queryClient]);

  useWikiEvents(businessId, handleWikiEvent);
```

In the JSX, after `<WikiSearchBar />` and before the main flex container, add:

```typescript
      {updateNotification && (
        <WikiUpdateNotification
          pagePath={updateNotification}
          onRefresh={() => {
            queryClient.invalidateQueries({ queryKey: ["wiki"] });
            setUpdateNotification(null);
          }}
          onDismiss={() => setUpdateNotification(null)}
        />
      )}
      <WikiGenerationProgress status={generationStatus} />
```

- [ ] **Step 3: Verify TypeScript compilation**

Run: `cd dashboard && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/components/wiki/WikiContent.tsx dashboard/src/components/wiki/WikiShell.tsx
git commit -m "feat(dashboard): integrate edit button, version badge, SSE notifications"
```

---

### Task 7: Write extended tests for Phase 8-10

**Files:**
- Create: `dashboard/src/components/wiki/__tests__/WikiEditButton.test.tsx`
- Create: `dashboard/src/components/wiki/__tests__/WikiVersionBadge.test.tsx`
- Create: `dashboard/src/components/wiki/__tests__/WikiUpdateNotification.test.tsx`

- [ ] **Step 1: WikiEditButton test**

```typescript
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import WikiEditButton from "../WikiEditButton";

describe("WikiEditButton", () => {
  it("renders nothing without gitRemoteUrl", () => {
    const { container } = render(<WikiEditButton />);
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing without exportPath", () => {
    const { container } = render(<WikiEditButton gitRemoteUrl="https://github.com/org/repo.git" />);
    expect(container.firstChild).toBeNull();
  });

  it("renders link with correct URL", () => {
    render(
      <WikiEditButton
        gitRemoteUrl="https://github.com/org/repo.git"
        branch="main"
        exportPath="docs/wiki/auth.md"
      />,
    );
    const link = screen.getByText(/edit on git/i).closest("a");
    expect(link).toHaveAttribute("href", "https://github.com/org/repo/blob/main/docs/wiki/auth.md");
  });

  it("handles git@ URLs", () => {
    render(
      <WikiEditButton
        gitRemoteUrl="git@github.com:org/repo.git"
        branch="dev"
        exportPath="auth.md"
      />,
    );
    const link = screen.getByText(/edit on git/i).closest("a");
    expect(link).toHaveAttribute("href", "https://github.com/org/repo/blob/dev/auth.md");
  });
});
```

- [ ] **Step 2: WikiVersionBadge test**

```typescript
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import WikiVersionBadge from "../WikiVersionBadge";

describe("WikiVersionBadge", () => {
  it("displays version and date", () => {
    render(<WikiVersionBadge version={3} generatedAt="2026-04-20T10:00:00Z" />);
    expect(screen.getByText(/v3/)).toBeInTheDocument();
  });

  it("calls onClick", () => {
    const handler = vi.fn();
    render(<WikiVersionBadge version={1} generatedAt="2026-01-01" onClick={handler} />);
    fireEvent.click(screen.getByRole("button"));
    expect(handler).toHaveBeenCalled();
  });
});
```

- [ ] **Step 3: WikiUpdateNotification test**

```typescript
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import WikiUpdateNotification from "../WikiUpdateNotification";

describe("WikiUpdateNotification", () => {
  it("shows page name", () => {
    render(
      <WikiUpdateNotification pagePath="user/auth" onRefresh={vi.fn()} onDismiss={vi.fn()} />,
    );
    expect(screen.getByText("auth")).toBeInTheDocument();
  });

  it("calls onRefresh", () => {
    const onRefresh = vi.fn();
    render(
      <WikiUpdateNotification pagePath="a/b" onRefresh={onRefresh} onDismiss={vi.fn()} />,
    );
    fireEvent.click(screen.getByText(/refresh/i));
    expect(onRefresh).toHaveBeenCalled();
  });

  it("calls onDismiss", () => {
    const onDismiss = vi.fn();
    render(
      <WikiUpdateNotification pagePath="a/b" onRefresh={vi.fn()} onDismiss={onDismiss} />,
    );
    const buttons = screen.getAllByRole("button");
    fireEvent.click(buttons[buttons.length - 1]);
    expect(onDismiss).toHaveBeenCalled();
  });
});
```

- [ ] **Step 4: Run tests**

Run: `cd dashboard && pnpm test`
Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/components/wiki/__tests__/
git commit -m "test(dashboard): add tests for WikiEditButton, WikiVersionBadge, WikiUpdateNotification"
```

---

### Task 8: Final verification

- [ ] **Step 1: Run full TypeScript check**

Run: `cd dashboard && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 2: Run all tests**

Run: `cd dashboard && pnpm test`
Expected: All tests pass

- [ ] **Step 3: Run lint**

Run: `cd dashboard && pnpm lint`
Expected: No new errors

- [ ] **Step 4: Verify build**

Run: `cd dashboard && pnpm build`
Expected: Build succeeds
