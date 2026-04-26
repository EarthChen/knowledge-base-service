# Wiki Frontend Phase 2+3: Tree Navigation + Landing Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the old repo-based wiki sidebar with a business-level tree navigator (dual-view), add full-text search (Cmd+K), build a hybrid landing page with coverage cards, and migrate all internal routes from `/wiki/:repository/*` to `/wiki?path=...`.

**Architecture:** WikiShell replaces WikiPage.tsx as the top-level shell, consuming URL search params. WikiTreeNav replaces WikiSidebar's tree section, fetching from the new `/wiki/tree` API. WikiLandingPage renders when no `path` param is present. All `wikiHref()` helpers across the codebase are updated to the new format.

**Tech Stack:** React 19, TypeScript 5.9, @tanstack/react-query 5, react-router-dom 7, chart.js + react-chartjs-2, lucide-react, Tailwind CSS 4

**Depends on:** FE-Phase 1 (types + hooks must be committed)

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `dashboard/src/components/wiki/WikiTreeNav.tsx` | Tree navigator with dual-view tabs |
| Create | `dashboard/src/components/wiki/WikiSearchBar.tsx` | Cmd+K search overlay |
| Create | `dashboard/src/components/wiki/WikiSearchResults.tsx` | Search results dropdown |
| Create | `dashboard/src/components/wiki/WikiLandingPage.tsx` | Hybrid entry: coverage + domain cards |
| Create | `dashboard/src/components/wiki/WikiCoverageCard.tsx` | Donut chart + coverage stats |
| Create | `dashboard/src/components/wiki/WikiShell.tsx` | Top-level wiki layout shell |
| Create | `dashboard/src/components/wiki/wikiRouteHelpers.ts` | Centralized `wikiHref()` for new URL format |
| Modify | `dashboard/src/pages/WikiPage.tsx` | Delegate to WikiShell |
| Modify | `dashboard/src/App.tsx` | Remove `:repository/*` route |
| Modify | `dashboard/src/components/wiki/WikiSidebar.tsx` | Keep IDE preferences section; tree logic replaced |
| Modify | `dashboard/src/components/wiki/WikiBreadcrumbs.tsx` | Update to new URL format |
| Modify | `dashboard/src/components/wiki/WikiContent.tsx` | Update wikiHref calls |
| Modify | `dashboard/src/components/wiki/WikiGlobalSearchBar.tsx` | Update wikiHref calls |
| Modify | `dashboard/src/components/wiki/AskPanel.tsx` | Update wikiHref calls |
| Modify | `dashboard/src/pages/FileExplorer.tsx` | Update wiki link |
| Modify | `dashboard/src/pages/ArchitecturePage.tsx` | Update wiki link |
| Modify | `dashboard/src/pages/PrImpactPage.tsx` | Update wikiHref + wikiEntitySearchHref |
| Modify | `dashboard/src/components/QuickStartBanner.tsx` | Update step links |

---

### Task 1: Create centralized wikiRouteHelpers.ts

**Files:**
- Create: `dashboard/src/components/wiki/wikiRouteHelpers.ts`

- [ ] **Step 1: Create the helper file**

```typescript
export function wikiHref(path?: string, params?: Record<string, string>): string {
  const sp = new URLSearchParams();
  if (path) sp.set("path", path);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v) sp.set(k, v);
    }
  }
  const qs = sp.toString();
  return qs ? `/wiki?${qs}` : "/wiki";
}

export function wikiSearchHref(query: string): string {
  return `/search?mode=wiki&q=${encodeURIComponent(query)}`;
}

export function parseWikiSearchParams(search: URLSearchParams) {
  return {
    path: search.get("path") || null,
    viewType: (search.get("view") as "business_domain" | "code_structure") || "business_domain",
    businessId: search.get("business_id") || null,
    toolTab: (search.get("tool") as "page" | "coverage" | "export" | "health" | "insights") || "page",
  };
}
```

- [ ] **Step 2: Verify TypeScript compilation**

Run: `cd dashboard && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/components/wiki/wikiRouteHelpers.ts
git commit -m "feat(dashboard): add centralized wiki route helper functions"
```

---

### Task 2: Create WikiTreeNav component

**Files:**
- Create: `dashboard/src/components/wiki/WikiTreeNav.tsx`

- [ ] **Step 1: Create the component**

```typescript
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  Code,
  FileText,
  Folder,
  Globe,
  Loader2,
} from "lucide-react";
import type { WikiTreeNode } from "../../hooks/wikiTypes";
import { useWikiTree } from "../../hooks/useWikiTree";
import { wikiHref } from "./wikiRouteHelpers";
import { useI18n } from "../../i18n/context";

function TreeItem({
  node,
  depth,
  expanded,
  toggle,
  activePath,
}: {
  node: WikiTreeNode;
  depth: number;
  expanded: Set<string>;
  toggle: (key: string) => void;
  activePath: string | null;
}) {
  const hasChildren = (node.children?.length ?? 0) > 0;
  const isOpen = expanded.has(node.path);
  const isActive = activePath === node.path;
  const isPage = node.label === "WikiPage";

  return (
    <li>
      <div className="flex items-center gap-0.5">
        {hasChildren ? (
          <button
            type="button"
            aria-expanded={isOpen}
            onClick={() => toggle(node.path)}
            className="rounded p-0.5 text-gray-400 hover:bg-gray-100 hover:text-gray-700 dark:text-gray-500 dark:hover:bg-gray-800 dark:hover:text-gray-200"
          >
            {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </button>
        ) : (
          <span className="w-[22px]" />
        )}
        {isPage ? (
          <a
            href={wikiHref(node.path)}
            onClick={(e) => {
              e.preventDefault();
              window.history.pushState(null, "", wikiHref(node.path));
              window.dispatchEvent(new PopStateEvent("popstate"));
            }}
            className={`flex min-w-0 flex-1 items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors ${
              isActive
                ? "bg-sky-50 font-medium text-sky-900 dark:bg-sky-950/60 dark:text-sky-100"
                : "text-gray-700 hover:bg-gray-50 dark:text-gray-300 dark:hover:bg-gray-800/80"
            }`}
          >
            <FileText size={14} className="shrink-0 opacity-70" />
            <span className="truncate">{node.title}</span>
          </a>
        ) : (
          <button
            type="button"
            onClick={() => hasChildren && toggle(node.path)}
            className="flex min-w-0 flex-1 items-center gap-2 px-2 py-1.5 text-sm text-gray-600 dark:text-gray-400"
          >
            <Folder size={14} className="shrink-0 text-amber-600/90 dark:text-amber-400/90" />
            <span className="truncate">{node.title}</span>
          </button>
        )}
      </div>
      {hasChildren && isOpen && node.children && (
        <ul className="mt-0.5 space-y-0.5 border-l border-gray-100 pl-2 dark:border-gray-700">
          {node.children.map((child) => (
            <TreeItem
              key={child.uid}
              node={child}
              depth={depth + 1}
              expanded={expanded}
              toggle={toggle}
              activePath={activePath}
            />
          ))}
        </ul>
      )}
    </li>
  );
}

interface WikiTreeNavProps {
  businessId: string;
  viewType: "business_domain" | "code_structure";
  activePath: string | null;
  onSelectPage: (path: string) => void;
  onViewChange: (view: "business_domain" | "code_structure") => void;
}

export default function WikiTreeNav({
  businessId,
  viewType,
  activePath,
  onSelectPage,
  onViewChange,
}: WikiTreeNavProps) {
  const { t } = useI18n();
  const { data, isLoading, isError, error } = useWikiTree(businessId, viewType);
  const nodes = data?.nodes ?? [];

  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());

  const expandToActive = useCallback(() => {
    if (!activePath) return;
    const parts = activePath.split("/").filter(Boolean);
    const paths = new Set<string>();
    let acc = "";
    for (const p of parts) {
      acc = acc ? `${acc}/${p}` : p;
      paths.add(acc);
    }
    setExpanded((prev) => new Set([...prev, ...paths]));
  }, [activePath]);

  useEffect(() => {
    expandToActive();
  }, [expandToActive]);

  const toggle = (key: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const expandAll = () => {
    const keys = new Set<string>();
    const walk = (list: WikiTreeNode[]) => {
      for (const n of list) {
        if (n.children?.length) {
          keys.add(n.path);
          walk(n.children);
        }
      }
    };
    walk(nodes);
    setExpanded(keys);
  };

  return (
    <aside className="flex w-full shrink-0 flex-col rounded-xl border border-gray-200 bg-white shadow-sm dark:border-gray-700 dark:bg-gray-900 dark:shadow-gray-950/40 lg:w-72">
      <div className="flex items-center border-b border-gray-100 dark:border-gray-700">
        <button
          type="button"
          onClick={() => onViewChange("business_domain")}
          className={`flex flex-1 items-center justify-center gap-1.5 px-3 py-2.5 text-xs font-medium transition-colors ${
            viewType === "business_domain"
              ? "border-b-2 border-sky-500 text-sky-700 dark:text-sky-300"
              : "text-gray-500 hover:text-gray-800 dark:text-gray-400 dark:hover:text-gray-200"
          }`}
        >
          <Globe size={14} />
          {t.wiki.businessView ?? "Business"}
        </button>
        <button
          type="button"
          onClick={() => onViewChange("code_structure")}
          className={`flex flex-1 items-center justify-center gap-1.5 px-3 py-2.5 text-xs font-medium transition-colors ${
            viewType === "code_structure"
              ? "border-b-2 border-sky-500 text-sky-700 dark:text-sky-300"
              : "text-gray-500 hover:text-gray-800 dark:text-gray-400 dark:hover:text-gray-200"
          }`}
        >
          <Code size={14} />
          {t.wiki.codeView ?? "Code"}
        </button>
      </div>

      <div className="border-b border-gray-100 px-4 py-2 dark:border-gray-700">
        <button
          type="button"
          onClick={expandAll}
          className="text-xs font-medium text-sky-700 hover:underline dark:text-sky-400"
        >
          {t.wiki.expandAllFolders}
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-2 py-3">
        {isLoading && (
          <div className="flex items-center gap-2 px-2 text-sm text-gray-500 dark:text-gray-400">
            <Loader2 className="size-4 animate-spin" />
            {t.wiki.loadingPages}
          </div>
        )}
        {isError && (
          <p className="px-2 text-sm text-red-600 dark:text-red-400">
            {error instanceof Error ? error.message : String(error)}
          </p>
        )}
        {!isLoading && !isError && nodes.length === 0 && (
          <p className="px-2 text-sm text-gray-500 dark:text-gray-400">
            {t.wiki.noPagesFound}
          </p>
        )}
        {!isLoading && !isError && nodes.length > 0 && (
          <ul className="space-y-0.5">
            {nodes.map((node) => (
              <TreeItem
                key={node.uid}
                node={node}
                depth={0}
                expanded={expanded}
                toggle={toggle}
                activePath={activePath}
              />
            ))}
          </ul>
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
git add dashboard/src/components/wiki/WikiTreeNav.tsx
git commit -m "feat(dashboard): add WikiTreeNav with dual-view tabs"
```

---

### Task 3: Create WikiSearchBar + WikiSearchResults

**Files:**
- Create: `dashboard/src/components/wiki/WikiSearchBar.tsx`
- Create: `dashboard/src/components/wiki/WikiSearchResults.tsx`

- [ ] **Step 1: Create WikiSearchResults component**

```typescript
import { FileText } from "lucide-react";
import type { WikiSearchResult } from "../../hooks/wikiTypes";
import { wikiHref } from "./wikiRouteHelpers";

interface WikiSearchResultsProps {
  results: WikiSearchResult[];
  onSelect: (path: string) => void;
}

export default function WikiSearchResults({ results, onSelect }: WikiSearchResultsProps) {
  if (results.length === 0) {
    return (
      <p className="px-4 py-6 text-center text-sm text-gray-500 dark:text-gray-400">
        No results found.
      </p>
    );
  }

  return (
    <ul className="max-h-80 overflow-y-auto py-1">
      {results.map((r) => (
        <li key={r.page_path}>
          <button
            type="button"
            onClick={() => onSelect(r.page_path)}
            className="flex w-full items-start gap-3 px-4 py-2.5 text-left transition-colors hover:bg-gray-50 dark:hover:bg-gray-800"
          >
            <FileText size={16} className="mt-0.5 shrink-0 text-gray-400" />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-gray-900 dark:text-gray-100">
                {r.page_title ?? r.page_path.split("/").pop()}
              </p>
              {r.snippet && (
                <p className="mt-0.5 line-clamp-2 text-xs text-gray-500 dark:text-gray-400">
                  {r.snippet}
                </p>
              )}
              <p className="mt-0.5 truncate font-mono text-[11px] text-gray-400 dark:text-gray-500">
                {r.page_path}
              </p>
            </div>
          </button>
        </li>
      ))}
    </ul>
  );
}
```

- [ ] **Step 2: Create WikiSearchBar component**

```typescript
import { useCallback, useEffect, useRef, useState } from "react";
import { Search, X } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useWikiSearch } from "../../hooks/useWikiSearch";
import WikiSearchResults from "./WikiSearchResults";
import { wikiHref } from "./wikiRouteHelpers";
import { useBusiness } from "../../contexts/BusinessContext";
import FocusTrap from "../FocusTrap";

export default function WikiSearchBar() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const { currentBusiness } = useBusiness();
  const search = useWikiSearch();

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setOpen(true);
      }
      if (e.key === "Escape") {
        setOpen(false);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  const handleSearch = useCallback(() => {
    const q = query.trim();
    if (q.length < 2) return;
    search.mutate({ query: q, repository: currentBusiness });
  }, [query, currentBusiness, search]);

  const handleSelect = useCallback(
    (path: string) => {
      setOpen(false);
      setQuery("");
      navigate(wikiHref(path));
    },
    [navigate],
  );

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/30 pt-[10vh] dark:bg-black/50">
      <FocusTrap>
        <div className="w-full max-w-xl overflow-hidden rounded-xl border border-gray-200 bg-white shadow-2xl dark:border-gray-700 dark:bg-gray-900">
          <div className="flex items-center gap-3 border-b border-gray-100 px-4 py-3 dark:border-gray-700">
            <Search size={18} className="text-gray-400" />
            <input
              ref={inputRef}
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleSearch();
              }}
              placeholder="Search wiki pages..."
              className="min-w-0 flex-1 bg-transparent text-sm text-gray-900 outline-none placeholder:text-gray-400 dark:text-gray-100"
            />
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-700 dark:hover:bg-gray-800 dark:hover:text-gray-200"
            >
              <X size={16} />
            </button>
          </div>
          {search.data && (
            <WikiSearchResults
              results={search.data.results}
              onSelect={handleSelect}
            />
          )}
          {search.isPending && (
            <p className="px-4 py-6 text-center text-sm text-gray-500">Searching...</p>
          )}
          {search.isError && (
            <p className="px-4 py-4 text-center text-sm text-red-600 dark:text-red-400">
              Search unavailable
            </p>
          )}
        </div>
      </FocusTrap>
    </div>
  );
}
```

Note: This component uses the existing `useWikiSearch` mutation hook (from `hooks/useWikiSearch.ts`), which calls `POST /wiki/search`. The `FocusTrap` component already exists at `components/FocusTrap.tsx`.

- [ ] **Step 3: Verify TypeScript compilation**

Run: `cd dashboard && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/components/wiki/WikiSearchBar.tsx dashboard/src/components/wiki/WikiSearchResults.tsx
git commit -m "feat(dashboard): add WikiSearchBar (Cmd+K) and WikiSearchResults"
```

---

### Task 4: Create WikiCoverageCard component

**Files:**
- Create: `dashboard/src/components/wiki/WikiCoverageCard.tsx`

- [ ] **Step 1: Create the component**

```typescript
import { Doughnut } from "react-chartjs-2";
import {
  Chart as ChartJS,
  ArcElement,
  Tooltip,
  Legend,
} from "chart.js";
import { useWikiCoverage } from "../../hooks/useWikiCoverage";
import { AlertTriangle, Loader2 } from "lucide-react";
import { useI18n } from "../../i18n/context";

ChartJS.register(ArcElement, Tooltip, Legend);

interface WikiCoverageCardProps {
  businessId: string;
}

export default function WikiCoverageCard({ businessId }: WikiCoverageCardProps) {
  const { data, isLoading, isError } = useWikiCoverage(businessId);
  const { t } = useI18n();

  if (isLoading) {
    return (
      <div className="flex items-center justify-center rounded-xl border border-gray-200 bg-white p-6 dark:border-gray-700 dark:bg-gray-900">
        <Loader2 className="size-5 animate-spin text-gray-400" />
      </div>
    );
  }

  if (isError || !data) return null;

  const pct = Math.round(data.coverage_percentage * 100);
  const remaining = 100 - pct;

  const chartData = {
    labels: ["Covered", "Uncovered"],
    datasets: [
      {
        data: [pct, remaining],
        backgroundColor: ["#0ea5e9", "#e2e8f0"],
        borderWidth: 0,
      },
    ],
  };

  const chartOptions = {
    cutout: "70%",
    plugins: {
      legend: { display: false },
      tooltip: { enabled: true },
    },
    responsive: true,
    maintainAspectRatio: false,
  };

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm dark:border-gray-700 dark:bg-gray-900">
      <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300">
        {t.wiki.coverageTitle ?? "Wiki Coverage"}
      </h3>
      <div className="mt-4 flex items-center gap-6">
        <div className="relative h-24 w-24 shrink-0">
          <Doughnut data={chartData} options={chartOptions} />
          <span className="absolute inset-0 flex items-center justify-center text-lg font-bold text-gray-900 dark:text-gray-100">
            {pct}%
          </span>
        </div>
        <div className="grid flex-1 grid-cols-2 gap-3">
          <div>
            <p className="text-[11px] font-medium uppercase text-gray-500 dark:text-gray-400">Core</p>
            <p className="text-lg font-bold text-gray-900 dark:text-gray-100">
              {Math.round(data.core_coverage * 100)}%
            </p>
          </div>
          <div>
            <p className="text-[11px] font-medium uppercase text-gray-500 dark:text-gray-400">Standard</p>
            <p className="text-lg font-bold text-gray-900 dark:text-gray-100">
              {Math.round(data.standard_coverage * 100)}%
            </p>
          </div>
          <div>
            <p className="text-[11px] font-medium uppercase text-gray-500 dark:text-gray-400">Stale</p>
            <p className="text-lg font-bold text-amber-600 dark:text-amber-400">
              {data.stale_page_count}
            </p>
          </div>
          <div>
            <p className="text-[11px] font-medium uppercase text-gray-500 dark:text-gray-400">Gaps</p>
            <p className="text-lg font-bold text-red-600 dark:text-red-400">
              {data.knowledge_gap_count}
            </p>
          </div>
        </div>
      </div>
      {data.stale_page_count > 0 && (
        <div className="mt-3 flex items-center gap-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:bg-amber-950/30 dark:text-amber-300">
          <AlertTriangle size={14} />
          {data.stale_page_count} pages may be outdated
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compilation**

Run: `cd dashboard && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/components/wiki/WikiCoverageCard.tsx
git commit -m "feat(dashboard): add WikiCoverageCard with donut chart"
```

---

### Task 5: Create WikiLandingPage component

**Files:**
- Create: `dashboard/src/components/wiki/WikiLandingPage.tsx`

- [ ] **Step 1: Create the component**

```typescript
import {
  ArrowRight,
  BookOpen,
  ChevronRight,
  Loader2,
} from "lucide-react";
import { useWikiTree } from "../../hooks/useWikiTree";
import WikiCoverageCard from "./WikiCoverageCard";
import { wikiHref } from "./wikiRouteHelpers";
import { useI18n } from "../../i18n/context";

interface WikiLandingPageProps {
  businessId: string;
  onNavigate: (path: string) => void;
}

export default function WikiLandingPage({ businessId, onNavigate }: WikiLandingPageProps) {
  const { t } = useI18n();
  const { data, isLoading } = useWikiTree(businessId, "business_domain");
  const domains = data?.nodes ?? [];

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div className="flex items-start gap-4 rounded-xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-900">
        <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-sky-50 text-sky-600 dark:bg-sky-950 dark:text-sky-400">
          <BookOpen size={24} aria-hidden />
        </div>
        <div>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
            {t.wiki.title}
          </h2>
          <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">
            {t.wiki.browseDescription}
          </p>
        </div>
      </div>

      <WikiCoverageCard businessId={businessId} />

      <div>
        <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
          {t.wiki.domainsHeading ?? "Business Domains"}
        </h3>
        {isLoading && (
          <div className="flex items-center gap-2 text-sm text-gray-500">
            <Loader2 className="size-4 animate-spin" />
            {t.wiki.loadingPages}
          </div>
        )}
        {!isLoading && domains.length === 0 && (
          <p className="text-sm text-gray-500 dark:text-gray-400">
            {t.wiki.noPagesFound}
          </p>
        )}
        {!isLoading && domains.length > 0 && (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {domains.map((domain) => (
              <button
                key={domain.uid}
                type="button"
                onClick={() => onNavigate(domain.path)}
                className="group flex items-center justify-between rounded-xl border border-gray-200 bg-white px-4 py-3 text-left shadow-sm transition-colors hover:border-sky-200 hover:bg-sky-50/40 dark:border-gray-700 dark:bg-gray-900 dark:hover:border-sky-800 dark:hover:bg-sky-950/30"
              >
                <div className="min-w-0 flex-1">
                  <p className="font-medium text-gray-900 dark:text-gray-100">
                    {domain.title}
                  </p>
                  {domain.children && (
                    <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
                      {domain.children.length} sub-sections
                    </p>
                  )}
                </div>
                <ChevronRight
                  size={18}
                  className="shrink-0 text-gray-400 transition-transform group-hover:translate-x-0.5 dark:text-gray-500"
                />
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compilation**

Run: `cd dashboard && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/components/wiki/WikiLandingPage.tsx
git commit -m "feat(dashboard): add WikiLandingPage with coverage + domain cards"
```

---

### Task 6: Create WikiShell and refactor WikiPage.tsx

**Files:**
- Create: `dashboard/src/components/wiki/WikiShell.tsx`
- Modify: `dashboard/src/pages/WikiPage.tsx`

- [ ] **Step 1: Create WikiShell component**

WikiShell is the new top-level shell managing three-column layout and URL params.

```typescript
import { useCallback, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  Activity,
  FileOutput,
  LayoutGrid,
  Loader2,
  Network,
  RefreshCw,
} from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";

import WikiTreeNav from "./WikiTreeNav";
import WikiLandingPage from "./WikiLandingPage";
import WikiContent from "./WikiContent";
import WikiSearchBar from "./WikiSearchBar";
import AskPanel from "./AskPanel";
import WikiLintPanel from "./WikiLintPanel";
import WikiExportPanel from "./WikiExportPanel";
import GraphInsightsPanel from "./GraphInsightsPanel";
import { parseWikiSearchParams, wikiHref } from "./wikiRouteHelpers";
import { useBusiness } from "../../contexts/BusinessContext";
import { useWikiPage } from "../../hooks/useWikiPage";
import { useToast } from "../Toast";
import { useI18n } from "../../i18n/context";
import { wikiGenerate, wikiTaskStatus } from "../../api/client";
import type { ReactNode } from "react";

type WikiToolTab = "page" | "coverage" | "export" | "health" | "insights";

export default function WikiShell() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const { currentBusiness } = useBusiness();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const { locale, t } = useI18n();

  const { path, viewType, businessId: urlBiz, toolTab: urlTool } =
    parseWikiSearchParams(searchParams);
  const businessId = urlBiz || currentBusiness;
  const [currentView, setCurrentView] = useState<"business_domain" | "code_structure">(viewType);
  const [toolTab, setToolTab] = useState<WikiToolTab>(urlTool);
  const [regeneratePending, setRegeneratePending] = useState(false);

  const pageQuery = useWikiPage(undefined, path ?? undefined);

  const handleNavigate = useCallback(
    (newPath: string) => {
      navigate(wikiHref(newPath, { view: currentView, business_id: businessId }));
    },
    [navigate, currentView, businessId],
  );

  const handleViewChange = useCallback(
    (view: "business_domain" | "code_structure") => {
      setCurrentView(view);
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        next.set("view", view);
        return next;
      }, { replace: true });
    },
    [setSearchParams],
  );

  const handleToolTab = (tab: WikiToolTab) => {
    setToolTab(tab);
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      if (tab === "page") next.delete("tool");
      else next.set("tool", tab);
      return next;
    }, { replace: true });
  };

  async function handleRegenerateWiki() {
    if (regeneratePending) return;
    setRegeneratePending(true);
    try {
      const res = await wikiGenerate("", "repo", "structure", locale === "zh" ? "zh" : "en");
      const tid = res.task_id ? String(res.task_id) : "";
      if (!tid) {
        toast("success", t.wiki.regenerateStarted);
        await queryClient.invalidateQueries({ queryKey: ["wiki"] });
        return;
      }
      toast("info", t.wiki.regenerateRunning);
      for (let i = 0; i < 45; i++) {
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
              : err ? JSON.stringify(err) : "unknown";
          toast("error", t.wiki.regenerateFailed.replace("{detail}", detail));
          return;
        }
      }
      toast("error", t.wiki.regenerateTimeout);
    } catch (e) {
      toast("error", e instanceof Error ? e.message : String(e));
    } finally {
      setRegeneratePending(false);
    }
  }

  const tabBtn = (id: WikiToolTab, label: string, icon: ReactNode) => (
    <button
      key={id}
      type="button"
      onClick={() => handleToolTab(id)}
      className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-medium transition-colors ${
        toolTab === id
          ? "bg-sky-100 text-sky-800 ring-1 ring-sky-200 dark:bg-sky-950 dark:text-sky-200 dark:ring-sky-800"
          : "text-gray-600 hover:bg-gray-100 hover:text-gray-900 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-100"
      }`}
    >
      {icon}
      {label}
    </button>
  );

  return (
    <>
      <WikiSearchBar />
      <div className="flex min-h-[min(70vh,860px)] flex-col gap-4 lg:flex-row lg:items-stretch">
        <WikiTreeNav
          businessId={businessId}
          viewType={currentView}
          activePath={path}
          onSelectPage={handleNavigate}
          onViewChange={handleViewChange}
        />

        <div className="flex min-w-0 flex-1 flex-col gap-4">
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-gray-200 bg-white px-3 py-2 shadow-sm dark:border-gray-700 dark:bg-gray-900">
            <div className="flex flex-wrap gap-2">
              {tabBtn("page", t.wiki.tabPage, <LayoutGrid size={14} className="text-sky-600 dark:text-sky-400" aria-hidden />)}
              {tabBtn("health", t.wiki.tabHealth, <Activity size={14} className="text-emerald-600 dark:text-emerald-400" aria-hidden />)}
              {tabBtn("insights", t.wiki.tabInsights, <Network size={14} className="text-violet-600 dark:text-violet-400" aria-hidden />)}
              {tabBtn("export", t.wiki.tabExport, <FileOutput size={14} className="text-sky-600 dark:text-sky-400" aria-hidden />)}
            </div>
            <button
              type="button"
              onClick={handleRegenerateWiki}
              disabled={regeneratePending}
              className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-medium text-amber-900 hover:bg-amber-100 disabled:opacity-50 dark:border-amber-900 dark:bg-amber-950/50 dark:text-amber-200 dark:hover:bg-amber-950"
            >
              {regeneratePending ? (
                <Loader2 size={14} className="animate-spin" aria-hidden />
              ) : (
                <RefreshCw size={14} aria-hidden />
              )}
              {t.wiki.regenerate}
            </button>
          </div>

          {toolTab === "page" && !path && (
            <WikiLandingPage
              businessId={businessId}
              onNavigate={handleNavigate}
            />
          )}

          {toolTab === "page" && path && (
            <>
              <WikiContent
                repository=""
                pagePath={path}
                detail={pageQuery.data}
                isLoading={pageQuery.isLoading}
                error={
                  pageQuery.isError
                    ? pageQuery.error instanceof Error
                      ? pageQuery.error
                      : new Error(String(pageQuery.error))
                    : null
                }
              />
              <AskPanel repository="" />
            </>
          )}

          {toolTab === "health" && <WikiLintPanel repository="" />}
          {toolTab === "insights" && <GraphInsightsPanel repository="" />}
          {toolTab === "export" && <WikiExportPanel repository="" />}
        </div>
      </div>
    </>
  );
}
```

- [ ] **Step 2: Replace WikiPage.tsx content**

Replace the entire content of `dashboard/src/pages/WikiPage.tsx` with:

```typescript
import WikiShell from "../components/wiki/WikiShell";

export default function WikiPage() {
  return <WikiShell />;
}
```

- [ ] **Step 3: Verify TypeScript compilation**

Run: `cd dashboard && npx tsc --noEmit`
Expected: May have errors related to WikiContent, AskPanel, WikiLintPanel etc. expecting `repository` prop — address these in Task 7.

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/components/wiki/WikiShell.tsx dashboard/src/pages/WikiPage.tsx
git commit -m "feat(dashboard): add WikiShell as top-level wiki layout, simplify WikiPage"
```

---

### Task 7: Update App.tsx routes

**Files:**
- Modify: `dashboard/src/App.tsx`

- [ ] **Step 1: Remove the `:repository/*` route**

In `dashboard/src/App.tsx`, change the wiki route block (lines 32-35) from:

```typescript
          <Route path="wiki">
            <Route index element={<WikiPage />} />
            <Route path=":repository/*" element={<WikiPage />} />
          </Route>
```

To:

```typescript
          <Route path="wiki" element={<WikiPage />} />
```

- [ ] **Step 2: Verify TypeScript compilation**

Run: `cd dashboard && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/App.tsx
git commit -m "refactor(dashboard): remove old /wiki/:repository/* route"
```

---

### Task 8: Update all internal wiki links

**Files:**
- Modify: `dashboard/src/components/wiki/WikiBreadcrumbs.tsx`
- Modify: `dashboard/src/components/wiki/WikiContent.tsx`
- Modify: `dashboard/src/components/wiki/WikiGlobalSearchBar.tsx`
- Modify: `dashboard/src/components/wiki/AskPanel.tsx`
- Modify: `dashboard/src/pages/FileExplorer.tsx`
- Modify: `dashboard/src/pages/ArchitecturePage.tsx`
- Modify: `dashboard/src/pages/PrImpactPage.tsx`

- [ ] **Step 1: Update WikiBreadcrumbs.tsx**

Replace the local `wikiLink` function and update `to` attributes to use the new format. Import `wikiHref` from `wikiRouteHelpers`:

```typescript
import { wikiHref } from "./wikiRouteHelpers";
```

Replace the breadcrumb link logic:
- Home link: `to={wikiHref()}` (was `/wiki/${encRepo}`)
- Segment links: `to={wikiHref(accumulatedPath)}` (was `/wiki/${encRepo}/${encPath}`)

- [ ] **Step 2: Update WikiContent.tsx**

Replace the local `wikiHref` function (line 42-50). Import from `wikiRouteHelpers`:

```typescript
import { wikiHref } from "./wikiRouteHelpers";
```

Remove the old `wikiHref` function definition and update all calls from `wikiHref(repository, path)` to `wikiHref(path)`.

- [ ] **Step 3: Update WikiGlobalSearchBar.tsx**

Replace the local `wikiHref` function (line 14-18). Import from `wikiRouteHelpers`:

```typescript
import { wikiHref } from "./wikiRouteHelpers";
```

Update calls from `wikiHref(repository, r.page_path)` to `wikiHref(r.page_path)`.

- [ ] **Step 4: Update AskPanel.tsx**

Replace the local `wikiHref` function (line 43-47). Import from `wikiRouteHelpers`:

```typescript
import { wikiHref } from "./wikiRouteHelpers";
```

Update calls from `wikiHref(repository, s.wiki_page)` to `wikiHref(s.wiki_page)`.

- [ ] **Step 5: Update FileExplorer.tsx**

Find the link to wiki (around line 524):

```typescript
to={`/wiki/${encodeURIComponent(repoForContent)}`}
```

Replace with:

```typescript
to="/wiki"
```

- [ ] **Step 6: Update ArchitecturePage.tsx**

Find the link (around line 112):

```typescript
return `/wiki/${encodeURIComponent(r)}?tool=insights`;
```

Replace with:

```typescript
return `/wiki?tool=insights`;
```

- [ ] **Step 7: Update PrImpactPage.tsx**

Replace the local `wikiHref` and `wikiEntitySearchHref` functions. Import from `wikiRouteHelpers`:

```typescript
import { wikiHref, wikiSearchHref } from "./wikiRouteHelpers";
```

Update calls:
- `wikiHref(repository.trim(), page.wiki_page_path)` → `wikiHref(page.wiki_page_path)`
- `wikiEntitySearchHref(repository.trim(), entity)` → `wikiSearchHref(entity)`

- [ ] **Step 8: Verify TypeScript compilation**

Run: `cd dashboard && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 9: Commit**

```bash
git add dashboard/src/components/wiki/WikiBreadcrumbs.tsx \
       dashboard/src/components/wiki/WikiContent.tsx \
       dashboard/src/components/wiki/WikiGlobalSearchBar.tsx \
       dashboard/src/components/wiki/AskPanel.tsx \
       dashboard/src/pages/FileExplorer.tsx \
       dashboard/src/pages/ArchitecturePage.tsx \
       dashboard/src/pages/PrImpactPage.tsx
git commit -m "refactor(dashboard): migrate all internal wiki links to new URL format"
```

---

### Task 9: Add i18n keys for new components

**Files:**
- Modify: `dashboard/src/i18n/en.ts`
- Modify: `dashboard/src/i18n/zh.ts`
- Modify: `dashboard/src/i18n/types.ts`

- [ ] **Step 1: Add new keys to English locale**

Add to the `wiki` section in `en.ts`:

```typescript
businessView: "Business",
codeView: "Code",
coverageTitle: "Wiki Coverage",
domainsHeading: "Business Domains",
```

- [ ] **Step 2: Add new keys to Chinese locale**

Add to the `wiki` section in `zh.ts`:

```typescript
businessView: "业务视角",
codeView: "代码视角",
coverageTitle: "Wiki 覆盖率",
domainsHeading: "业务领域",
```

- [ ] **Step 3: Add new keys to the i18n type definition**

Add the new keys to the `wiki` section in `i18n/types.ts`.

- [ ] **Step 4: Verify TypeScript compilation**

Run: `cd dashboard && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/i18n/en.ts dashboard/src/i18n/zh.ts dashboard/src/i18n/types.ts
git commit -m "feat(dashboard): add i18n keys for wiki tree nav and landing page"
```

---

### Task 10: Final verification

- [ ] **Step 1: Run full TypeScript check**

Run: `cd dashboard && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 2: Run lint**

Run: `cd dashboard && pnpm lint`
Expected: No new errors

- [ ] **Step 3: Verify build**

Run: `cd dashboard && pnpm build`
Expected: Build succeeds
