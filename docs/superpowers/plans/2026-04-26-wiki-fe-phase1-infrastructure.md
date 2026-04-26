# Wiki Frontend Phase 1: 基础设施 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish all TypeScript types, React Query hooks, API client helpers, and utility functions required by FE-Phase 2–11.

**Architecture:** Extend existing `hooks/wikiTypes.ts` with new interfaces for tree/references/coverage/annotations/versions/events. Add 6 new hook files following existing patterns (useQuery / useMutation wrapping `api()` from `api/client.ts`). Add a wikilink parser utility.

**Tech Stack:** TypeScript 5.9, React 19, @tanstack/react-query 5, fetch-based `api()` helper

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `dashboard/src/hooks/wikiTypes.ts` | Add 12 new interfaces/types for tree, refs, coverage, export, search, annotations, versions, diff, events |
| Create | `dashboard/src/hooks/useWikiTree.ts` | `GET /wiki/tree` query hook |
| Create | `dashboard/src/hooks/useWikiReferences.ts` | `GET /wiki/pages/{uid}/references` query hook |
| Create | `dashboard/src/hooks/useWikiCoverage.ts` | `GET /wiki/coverage-report` query hook |
| Create | `dashboard/src/hooks/useBusinessWikiGenerate.ts` | `POST /wiki/business/generate` mutation hook |
| Create | `dashboard/src/hooks/useBusinessWikiExport.ts` | `POST /wiki/export` mutation hook |
| Create | `dashboard/src/components/wiki/wikilinkParser.ts` | Parse `[[path]]` and `[[path|label]]` in markdown text |
| Modify | `dashboard/src/api/client.ts` | Add `businessWikiGenerate` and `businessWikiExport` helper functions |

---

### Task 1: Extend wikiTypes.ts with new interfaces

**Files:**
- Modify: `dashboard/src/hooks/wikiTypes.ts`

- [ ] **Step 1: Add tree, reference, coverage, and export types**

Append the following types after the existing `WikiAskSource` type (line 66):

```typescript
export type WikiTreeNode = {
  uid: string;
  title: string;
  label: string;
  depth: number;
  sort_order: number;
  path: string;
  page_type: string;
  children?: WikiTreeNode[];
};

export type WikiTreeResponse = {
  nodes: WikiTreeNode[];
  business_id: string;
  view_type: string;
};

export type WikiReference = {
  target_uid: string;
  target_title: string;
  target_path: string;
  relation_type: string;
  context: string;
  repository: string;
};

export type WikiReferencesResponse = {
  page_uid: string;
  outgoing: WikiReference[];
  incoming: WikiReference[];
};

export type WikiStalePage = {
  page_path: string;
  page_title: string;
  entity_commit: string;
  page_generated_at: string;
};

export type WikiKnowledgeGap = {
  entity: string;
  in_degree: number;
  wiki_tier: string | null;
};

export type WikiCoverageResponse = {
  total_entities: number;
  covered_entities: number;
  coverage_percentage: number;
  core_coverage: number;
  standard_coverage: number;
  stale_pages: WikiStalePage[];
  stale_page_count: number;
  knowledge_gaps: WikiKnowledgeGap[];
  knowledge_gap_count: number;
};

export type BusinessWikiExportBody = {
  business_id: string;
  format: "markdown" | "zip" | "git" | "obsidian" | "mkdocs";
  view_type: "business_domain" | "code_structure" | "both";
  min_tier: "core" | "standard" | "skeleton";
  git_config?: {
    remote_url: string;
    branch: string;
    commit_message_prefix: string;
  };
};

export type BusinessWikiExportResponse = {
  status: string;
  format: string;
  file_count: number;
  output_path?: string;
  download_url?: string;
};

export type WikiAnnotation = {
  annotation_id: string;
  page_uid: string;
  text_range_start: number;
  text_range_end: number;
  comment: string;
  author: string;
  created_at: string;
};

export type WikiVersion = {
  version: number;
  content_hash: string;
  generated_at: string;
  change_summary: string;
};

export type WikiDiff = {
  from_version: number;
  to_version: number;
  hunks: Array<{
    old_start: number;
    old_lines: number;
    new_start: number;
    new_lines: number;
    content: string;
  }>;
};

export type WikiEventType =
  | "wiki:page_updated"
  | "wiki:generation_started"
  | "wiki:generation_completed"
  | "wiki:generation_failed";

export type WikiEvent = {
  type: WikiEventType;
  business_id: string;
  page_path?: string;
  timestamp: string;
  payload?: Record<string, unknown>;
};
```

- [ ] **Step 2: Verify TypeScript compilation**

Run: `cd dashboard && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/hooks/wikiTypes.ts
git commit -m "feat(dashboard): add wiki tree/refs/coverage/export/annotation/version/event types"
```

---

### Task 2: Add API client helper functions

**Files:**
- Modify: `dashboard/src/api/client.ts`

- [ ] **Step 1: Add business wiki generate and export functions**

Add these imports and functions at the end of `dashboard/src/api/client.ts` (after the `wikiTaskStatus` function at line 131):

```typescript
import type { BusinessWikiExportBody, BusinessWikiExportResponse } from "../hooks/wikiTypes";

export async function businessWikiGenerate(
  businessId: string,
  language: string,
): Promise<TaskInfo> {
  return api<TaskInfo>("/wiki/business/generate", {
    method: "POST",
    body: JSON.stringify({ business_id: businessId, language }),
  });
}

export async function businessWikiExport(
  body: BusinessWikiExportBody,
): Promise<BusinessWikiExportResponse> {
  return api<BusinessWikiExportResponse>("/wiki/export", {
    method: "POST",
    body: JSON.stringify(body),
  });
}
```

Note: The import for `BusinessWikiExportBody` and `BusinessWikiExportResponse` must be added at the top of the file alongside the existing imports.

- [ ] **Step 2: Verify TypeScript compilation**

Run: `cd dashboard && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/api/client.ts
git commit -m "feat(dashboard): add business wiki generate and export API helpers"
```

---

### Task 3: Create useWikiTree hook

**Files:**
- Create: `dashboard/src/hooks/useWikiTree.ts`

- [ ] **Step 1: Create the hook file**

```typescript
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { WikiTreeResponse } from "./wikiTypes";

export function useWikiTree(businessId: string, viewType: string) {
  return useQuery<WikiTreeResponse>({
    queryKey: ["wiki", "tree", businessId, viewType],
    queryFn: () =>
      api<WikiTreeResponse>(
        `/wiki/tree?business_id=${encodeURIComponent(businessId)}&view=${encodeURIComponent(viewType)}`,
      ),
    enabled: !!businessId,
    staleTime: 30_000,
  });
}
```

- [ ] **Step 2: Verify TypeScript compilation**

Run: `cd dashboard && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/hooks/useWikiTree.ts
git commit -m "feat(dashboard): add useWikiTree hook for tree API"
```

---

### Task 4: Create useWikiReferences hook

**Files:**
- Create: `dashboard/src/hooks/useWikiReferences.ts`

- [ ] **Step 1: Create the hook file**

```typescript
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { WikiReferencesResponse } from "./wikiTypes";

export function useWikiReferences(pageUid: string) {
  return useQuery<WikiReferencesResponse>({
    queryKey: ["wiki", "references", pageUid],
    queryFn: () =>
      api<WikiReferencesResponse>(
        `/wiki/pages/${encodeURIComponent(pageUid)}/references`,
      ),
    enabled: !!pageUid,
    staleTime: 30_000,
  });
}
```

- [ ] **Step 2: Verify TypeScript compilation**

Run: `cd dashboard && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/hooks/useWikiReferences.ts
git commit -m "feat(dashboard): add useWikiReferences hook for page references API"
```

---

### Task 5: Create useWikiCoverage hook

**Files:**
- Create: `dashboard/src/hooks/useWikiCoverage.ts`

- [ ] **Step 1: Create the hook file**

```typescript
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { WikiCoverageResponse } from "./wikiTypes";

export function useWikiCoverage(businessId: string) {
  return useQuery<WikiCoverageResponse>({
    queryKey: ["wiki", "coverage", businessId],
    queryFn: () =>
      api<WikiCoverageResponse>(
        `/wiki/coverage-report?business_id=${encodeURIComponent(businessId)}`,
      ),
    enabled: !!businessId,
    staleTime: 60_000,
  });
}
```

- [ ] **Step 2: Verify TypeScript compilation**

Run: `cd dashboard && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/hooks/useWikiCoverage.ts
git commit -m "feat(dashboard): add useWikiCoverage hook for coverage report API"
```

---

### Task 6: Create useBusinessWikiGenerate and useBusinessWikiExport hooks

**Files:**
- Create: `dashboard/src/hooks/useBusinessWikiGenerate.ts`
- Create: `dashboard/src/hooks/useBusinessWikiExport.ts`

- [ ] **Step 1: Create useBusinessWikiGenerate hook**

```typescript
import { useMutation } from "@tanstack/react-query";
import { businessWikiGenerate } from "../api/client";

export function useBusinessWikiGenerate() {
  return useMutation({
    mutationFn: (vars: { businessId: string; language: string }) =>
      businessWikiGenerate(vars.businessId, vars.language),
  });
}
```

- [ ] **Step 2: Create useBusinessWikiExport hook**

```typescript
import { useMutation } from "@tanstack/react-query";
import { businessWikiExport } from "../api/client";
import type { BusinessWikiExportBody } from "./wikiTypes";

export function useBusinessWikiExport() {
  return useMutation({
    mutationFn: (body: BusinessWikiExportBody) => businessWikiExport(body),
  });
}
```

- [ ] **Step 3: Verify TypeScript compilation**

Run: `cd dashboard && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/hooks/useBusinessWikiGenerate.ts dashboard/src/hooks/useBusinessWikiExport.ts
git commit -m "feat(dashboard): add business wiki generate and export mutation hooks"
```

---

### Task 7: Create wikilink parser utility

**Files:**
- Create: `dashboard/src/components/wiki/wikilinkParser.ts`

- [ ] **Step 1: Create the parser file**

```typescript
export interface ParsedWikilink {
  raw: string;
  path: string;
  label: string;
}

const WIKILINK_RE = /\[\[([^\]|]+?)(?:\|([^\]]+?))?\]\]/g;

export function parseWikilinks(text: string): ParsedWikilink[] {
  const results: ParsedWikilink[] = [];
  let match: RegExpExecArray | null;
  while ((match = WIKILINK_RE.exec(text)) !== null) {
    const path = match[1].trim();
    const label = match[2]?.trim() || path.split("/").pop() || path;
    results.push({ raw: match[0], path, label });
  }
  return results;
}

export function replaceWikilinksWithHtml(markdown: string): string {
  return markdown.replace(WIKILINK_RE, (_match, path: string, label?: string) => {
    const trimPath = path.trim();
    const trimLabel = label?.trim() || trimPath.split("/").pop() || trimPath;
    return `<wikilink data-path="${encodeURIComponent(trimPath)}">${trimLabel}</wikilink>`;
  });
}
```

- [ ] **Step 2: Verify TypeScript compilation**

Run: `cd dashboard && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/components/wiki/wikilinkParser.ts
git commit -m "feat(dashboard): add wikilink parser utility for [[path]] and [[path|label]]"
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
