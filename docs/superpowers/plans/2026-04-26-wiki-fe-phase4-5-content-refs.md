# Wiki Frontend Phase 4+5: Page Content Enhancement + References Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enhance page content rendering with wikilink hover preview, importance/enrichment badges, stale alerts, and build a references panel showing incoming/outgoing cross-references.

**Architecture:** MarkdownRenderer is extended to pre-process `[[wikilink]]` syntax into custom HTML elements, rendered as `WikiLinkPreview` components with hover cards. WikiReferencesPanel is a new component that consumes the `/pages/{uid}/references` API and renders in the right column of the three-column layout.

**Tech Stack:** React 19, TypeScript 5.9, @tanstack/react-query 5, react-markdown, rehype-raw, Tailwind CSS 4, lucide-react

**Depends on:** FE-Phase 1 (types + hooks), FE-Phase 2+3 (WikiShell, wikiRouteHelpers)

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `dashboard/src/components/wiki/WikiLinkPreview.tsx` | Hover preview card for wikilinks |
| Create | `dashboard/src/components/wiki/WikiStaleAlert.tsx` | Yellow warning bar for stale pages |
| Create | `dashboard/src/components/wiki/WikiReferencesPanel.tsx` | Right-side references panel |
| Modify | `dashboard/src/components/wiki/MarkdownRenderer.tsx` | Add wikilink pre-processing + custom component |
| Modify | `dashboard/src/components/wiki/WikiContent.tsx` | Add importance/enrichment badges, stale alert |
| Modify | `dashboard/src/components/wiki/WikiShell.tsx` | Integrate references panel in layout |

---

### Task 1: Create WikiStaleAlert component

**Files:**
- Create: `dashboard/src/components/wiki/WikiStaleAlert.tsx`

- [ ] **Step 1: Create the component**

```typescript
import { AlertTriangle } from "lucide-react";

interface WikiStaleAlertProps {
  generatedAt: string;
  isStale: boolean;
}

export default function WikiStaleAlert({ generatedAt, isStale }: WikiStaleAlertProps) {
  if (!isStale) return null;

  let formattedDate = generatedAt;
  try {
    formattedDate = new Date(generatedAt).toLocaleDateString();
  } catch {
    // keep raw string
  }

  return (
    <div className="flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-4 py-2.5 text-sm text-amber-800 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-300">
      <AlertTriangle size={16} className="shrink-0" />
      <span>
        Source code has been updated since this page was generated ({formattedDate}). Content may be outdated.
      </span>
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compilation**

Run: `cd dashboard && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/components/wiki/WikiStaleAlert.tsx
git commit -m "feat(dashboard): add WikiStaleAlert warning component"
```

---

### Task 2: Create WikiLinkPreview component

**Files:**
- Create: `dashboard/src/components/wiki/WikiLinkPreview.tsx`

- [ ] **Step 1: Create the component**

```typescript
import { useCallback, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { FileText, Loader2 } from "lucide-react";
import { useWikiPage } from "../../hooks/useWikiPage";
import { wikiHref } from "./wikiRouteHelpers";

interface WikiLinkPreviewProps {
  path: string;
  children: React.ReactNode;
}

export default function WikiLinkPreview({ path, children }: WikiLinkPreviewProps) {
  const navigate = useNavigate();
  const [show, setShow] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout>>();
  const { data, isLoading } = useWikiPage(undefined, path);

  const handleMouseEnter = useCallback(() => {
    timerRef.current = setTimeout(() => setShow(true), 300);
  }, []);

  const handleMouseLeave = useCallback(() => {
    clearTimeout(timerRef.current);
    setShow(false);
  }, []);

  const handleClick = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      navigate(wikiHref(path));
    },
    [navigate, path],
  );

  const snippet = data?.content?.slice(0, 200)?.replace(/^#+\s.+\n/, "") || "";

  return (
    <span
      className="relative inline"
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      <a
        href={wikiHref(path)}
        onClick={handleClick}
        className="font-medium text-sky-700 underline decoration-sky-300/50 decoration-1 underline-offset-2 transition-colors hover:text-sky-900 hover:decoration-sky-400 dark:text-sky-400 dark:decoration-sky-700 dark:hover:text-sky-300"
      >
        {children}
      </a>
      {show && (
        <span
          className="absolute bottom-full left-1/2 z-50 mb-2 w-72 -translate-x-1/2 rounded-xl border border-gray-200 bg-white p-4 shadow-lg dark:border-gray-700 dark:bg-gray-900"
          onMouseEnter={() => clearTimeout(timerRef.current)}
          onMouseLeave={handleMouseLeave}
        >
          {isLoading ? (
            <span className="flex items-center gap-2 text-sm text-gray-500">
              <Loader2 size={14} className="animate-spin" />
              Loading...
            </span>
          ) : data ? (
            <>
              <span className="flex items-center gap-2">
                <FileText size={14} className="shrink-0 text-sky-500" />
                <span className="truncate text-sm font-semibold text-gray-900 dark:text-gray-100">
                  {data.title}
                </span>
              </span>
              {snippet && (
                <span className="mt-2 block text-xs leading-relaxed text-gray-600 dark:text-gray-400">
                  {snippet}...
                </span>
              )}
              <span className="mt-2 block truncate font-mono text-[10px] text-gray-400">
                {path}
              </span>
            </>
          ) : (
            <span className="text-xs text-gray-500">Page not generated yet</span>
          )}
        </span>
      )}
    </span>
  );
}
```

- [ ] **Step 2: Verify TypeScript compilation**

Run: `cd dashboard && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/components/wiki/WikiLinkPreview.tsx
git commit -m "feat(dashboard): add WikiLinkPreview hover card component"
```

---

### Task 3: Enhance MarkdownRenderer with wikilink support

**Files:**
- Modify: `dashboard/src/components/wiki/MarkdownRenderer.tsx`

- [ ] **Step 1: Add wikilink pre-processing**

Import the wikilink parser and WikiLinkPreview at the top of `MarkdownRenderer.tsx`:

```typescript
import { replaceWikilinksWithHtml } from "./wikilinkParser";
import WikiLinkPreview from "./WikiLinkPreview";
```

- [ ] **Step 2: Add `wikilink` custom component handler**

In the `components` useMemo (around line 112), add a handler for the custom `wikilink` element. After the existing `h3: H3` entry, add:

```typescript
      // @ts-expect-error custom element not in standard Components
      wikilink: ({ "data-path": dataPath, children }: { "data-path"?: string; children?: React.ReactNode }) => {
        const path = dataPath ? decodeURIComponent(dataPath) : "";
        if (!path) return <span>{children}</span>;
        return <WikiLinkPreview path={path}>{children}</WikiLinkPreview>;
      },
```

- [ ] **Step 3: Pre-process content before rendering**

In the `MarkdownRenderer` component (line 106), change the return statement to pre-process wikilinks:

Change:
```typescript
export default function MarkdownRenderer({ content }: Props) {
```

Keep the function signature, but add wikilink processing. After the `headingIds` useMemo, add:

```typescript
  const processedContent = useMemo(() => replaceWikilinksWithHtml(content), [content]);
```

Then in the JSX, replace `{content}` with `{processedContent}` inside `<ReactMarkdown>`.

- [ ] **Step 4: Verify TypeScript compilation**

Run: `cd dashboard && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/components/wiki/MarkdownRenderer.tsx
git commit -m "feat(dashboard): add wikilink parsing and hover preview to MarkdownRenderer"
```

---

### Task 4: Add importance/enrichment badges to WikiContent

**Files:**
- Modify: `dashboard/src/components/wiki/WikiContent.tsx`

- [ ] **Step 1: Add WikiStaleAlert import**

At the top of `WikiContent.tsx`, add:

```typescript
import WikiStaleAlert from "./WikiStaleAlert";
```

- [ ] **Step 2: Add badge rendering in the header**

After the `generatedAt` display (around line 282), add importance tier and enrichment badges. These values come from the `WikiPageDetail` type — note that `WikiPageDetail` in `wikiTypes.ts` may need extending. For now, use optional properties from `detail.context`:

After the generatedAt `<p>` tag, add:

```typescript
            {detail?.context?.importance_tier && (
              <span className={`mt-1 inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
                detail.context.importance_tier === "core"
                  ? "bg-sky-100 text-sky-800 dark:bg-sky-900/50 dark:text-sky-300"
                  : detail.context.importance_tier === "standard"
                    ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-300"
                    : "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400"
              }`}>
                {detail.context.importance_tier}
              </span>
            )}
```

- [ ] **Step 3: Add stale alert above content**

After the header `</header>` tag, before the main content flex container, add:

```typescript
      {detail?.generated_at && (
        <div className="px-5 pt-3">
          <WikiStaleAlert
            generatedAt={detail.generated_at}
            isStale={detail.context?.is_stale === "true"}
          />
        </div>
      )}
```

Note: The stale detection in FE-Phase 4 uses the `is_stale` field from `detail.context`. This is populated by the frontend matching the page path against coverage report stale pages (to be wired in a later step, or backend can populate it).

- [ ] **Step 4: Verify TypeScript compilation**

Run: `cd dashboard && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/components/wiki/WikiContent.tsx
git commit -m "feat(dashboard): add importance badges and stale alert to WikiContent"
```

---

### Task 5: Create WikiReferencesPanel component

**Files:**
- Create: `dashboard/src/components/wiki/WikiReferencesPanel.tsx`

- [ ] **Step 1: Create the component**

```typescript
import { useState } from "react";
import {
  ArrowUpRight,
  ArrowDownLeft,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  Loader2,
  X,
} from "lucide-react";
import type { WikiReference } from "../../hooks/wikiTypes";
import { useWikiReferences } from "../../hooks/useWikiReferences";
import { wikiHref } from "./wikiRouteHelpers";
import { useNavigate } from "react-router-dom";
import { useI18n } from "../../i18n/context";

function relationIcon(relType: string): string {
  const map: Record<string, string> = {
    calls: "fn",
    inherits: "ext",
    imports: "imp",
    cross_repo: "repo",
    semantic: "sem",
    business_flow: "flow",
  };
  return map[relType] || relType.slice(0, 3);
}

function ReferenceItem({ reference, onClick }: { reference: WikiReference; onClick: () => void }) {
  const r = reference;
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-start gap-2 rounded-lg px-3 py-2 text-left transition-colors hover:bg-gray-50 dark:hover:bg-gray-800"
    >
      <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded bg-gray-100 text-[9px] font-bold uppercase text-gray-600 dark:bg-gray-800 dark:text-gray-400">
        {relationIcon(r.relation_type)}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium text-gray-900 dark:text-gray-100">
          {r.target_title}
        </span>
        {r.repository && (
          <span className="mt-0.5 block truncate text-[11px] text-gray-500 dark:text-gray-400">
            {r.repository}
          </span>
        )}
        {r.context && (
          <span className="mt-0.5 block line-clamp-2 text-[11px] text-gray-400 dark:text-gray-500">
            {r.context}
          </span>
        )}
      </span>
    </button>
  );
}

interface WikiReferencesPanelProps {
  pageUid: string;
  isOpen: boolean;
  onToggle: () => void;
}

export default function WikiReferencesPanel({ pageUid, isOpen, onToggle }: WikiReferencesPanelProps) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const { data, isLoading, isError } = useWikiReferences(pageUid);

  const outgoing = data?.outgoing ?? [];
  const incoming = data?.incoming ?? [];

  if (!isOpen) {
    return (
      <button
        type="button"
        onClick={onToggle}
        className="hidden shrink-0 items-center justify-center rounded-xl border border-gray-200 bg-white p-2 shadow-sm hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-900 dark:hover:bg-gray-800 lg:flex"
        title="Show references"
      >
        <ChevronLeft size={16} className="text-gray-500" />
      </button>
    );
  }

  return (
    <aside className="hidden w-64 shrink-0 flex-col rounded-xl border border-gray-200 bg-white shadow-sm dark:border-gray-700 dark:bg-gray-900 lg:flex">
      <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3 dark:border-gray-700">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
          {t.wiki.referencesHeading ?? "References"}
        </h3>
        <button
          type="button"
          onClick={onToggle}
          className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-700 dark:hover:bg-gray-800 dark:hover:text-gray-200"
        >
          <ChevronRight size={14} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {isLoading && (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="size-5 animate-spin text-gray-400" />
          </div>
        )}

        {isError && (
          <p className="px-4 py-4 text-xs text-gray-500 dark:text-gray-400">
            Unable to load references
          </p>
        )}

        {!isLoading && !isError && outgoing.length === 0 && incoming.length === 0 && (
          <p className="px-4 py-6 text-center text-xs text-gray-500 dark:text-gray-400">
            No references found
          </p>
        )}

        {outgoing.length > 0 && (
          <div className="border-b border-gray-50 px-3 py-3 dark:border-gray-800">
            <h4 className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
              <ArrowUpRight size={12} />
              Outgoing ({outgoing.length})
            </h4>
            <div className="space-y-0.5">
              {outgoing.map((r) => (
                <ReferenceItem
                  key={r.target_uid}
                  reference={r}
                  onClick={() => navigate(wikiHref(r.target_path))}
                />
              ))}
            </div>
          </div>
        )}

        {incoming.length > 0 && (
          <div className="px-3 py-3">
            <h4 className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
              <ArrowDownLeft size={12} />
              Incoming ({incoming.length})
            </h4>
            <div className="space-y-0.5">
              {incoming.map((r) => (
                <ReferenceItem
                  key={r.target_uid}
                  reference={r}
                  onClick={() => navigate(wikiHref(r.target_path))}
                />
              ))}
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}
```

- [ ] **Step 2: Verify TypeScript compilation**

Run: `cd dashboard && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/components/wiki/WikiReferencesPanel.tsx
git commit -m "feat(dashboard): add WikiReferencesPanel with outgoing/incoming references"
```

---

### Task 6: Integrate WikiReferencesPanel into WikiShell

**Files:**
- Modify: `dashboard/src/components/wiki/WikiShell.tsx`

- [ ] **Step 1: Import WikiReferencesPanel**

Add at the top of `WikiShell.tsx`:

```typescript
import WikiReferencesPanel from "./WikiReferencesPanel";
```

- [ ] **Step 2: Add references panel state**

In the WikiShell component, add state for the references panel. After the existing state declarations, add:

```typescript
  const [refsPanelOpen, setRefsPanelOpen] = useState(() => {
    try { return localStorage.getItem("kb_wiki_refs_panel") !== "closed"; } catch { return true; }
  });

  const toggleRefsPanel = useCallback(() => {
    setRefsPanelOpen((prev) => {
      const next = !prev;
      try { localStorage.setItem("kb_wiki_refs_panel", next ? "open" : "closed"); } catch { /* ignore */ }
      return next;
    });
  }, []);
```

- [ ] **Step 3: Add panel to layout**

In the return JSX, after the main content `</div>` and before the closing `</div>` of the flex container, add the references panel:

```typescript
        {path && pageQuery.data && (
          <WikiReferencesPanel
            pageUid={pageQuery.data.context?.uid ?? ""}
            isOpen={refsPanelOpen}
            onToggle={toggleRefsPanel}
          />
        )}
```

- [ ] **Step 4: Verify TypeScript compilation**

Run: `cd dashboard && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/components/wiki/WikiShell.tsx
git commit -m "feat(dashboard): integrate WikiReferencesPanel into WikiShell layout"
```

---

### Task 7: Add i18n keys for Phase 4+5

**Files:**
- Modify: `dashboard/src/i18n/en.ts`
- Modify: `dashboard/src/i18n/zh.ts`
- Modify: `dashboard/src/i18n/types.ts`

- [ ] **Step 1: Add new keys to English locale**

Add to the `wiki` section in `en.ts`:

```typescript
referencesHeading: "References",
staleWarning: "Source code has been updated since this page was generated. Content may be outdated.",
```

- [ ] **Step 2: Add new keys to Chinese locale**

Add to the `wiki` section in `zh.ts`:

```typescript
referencesHeading: "引用关系",
staleWarning: "源代码已更新，当前页面内容可能不是最新的。",
```

- [ ] **Step 3: Add keys to types**

Update `i18n/types.ts` accordingly.

- [ ] **Step 4: Verify TypeScript compilation**

Run: `cd dashboard && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/i18n/en.ts dashboard/src/i18n/zh.ts dashboard/src/i18n/types.ts
git commit -m "feat(dashboard): add i18n keys for references and stale alert"
```

---

### Task 8: Final verification

- [ ] **Step 1: Run full TypeScript check**

Run: `cd dashboard && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 2: Run lint**

Run: `cd dashboard && pnpm lint`
Expected: No new errors

- [ ] **Step 3: Verify build**

Run: `cd dashboard && pnpm build`
Expected: Build succeeds
