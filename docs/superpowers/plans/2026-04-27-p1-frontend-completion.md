# P1 — Frontend Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement 4 new frontend components (WikiEditor, ReasoningPathPanel, WikiTierSelector, OfflinePackDownloadButton) and raise test coverage to 70%.

**Architecture:** Each component is self-contained with its own hook, renders within existing wiki shell/tool infrastructure, and uses existing backend APIs.

**Tech Stack:** React 19, TypeScript, TanStack Query 5, CodeMirror 6, Vitest, RTL, Tailwind v4

---

### Task 4: WikiEditor — Markdown Editor with Live Preview

**Files:**
- Create: `dashboard/src/components/wiki/WikiEditor.tsx`
- Create: `dashboard/src/hooks/useWikiPageEdit.ts`
- Modify: `dashboard/src/components/wiki/WikiContent.tsx` (add edit mode toggle)
- Test: `dashboard/src/components/wiki/__tests__/WikiEditor.test.tsx`

- [ ] **Step 1: Install CodeMirror dependency**

Run: `cd dashboard && pnpm add @uiw/react-codemirror @codemirror/lang-markdown`

- [ ] **Step 2: Write failing test for useWikiPageEdit hook**

```typescript
// dashboard/src/hooks/__tests__/useWikiPageEdit.test.ts
import { describe, it, expect, vi } from 'vitest';

describe('useWikiPageEdit', () => {
  it('module exports usePatchWikiPage', async () => {
    const mod = await import('../useWikiPageEdit');
    expect(mod.usePatchWikiPage).toBeDefined();
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd dashboard && pnpm test --run -- useWikiPageEdit`
Expected: FAIL — module not found

- [ ] **Step 4: Implement useWikiPageEdit hook**

```typescript
// dashboard/src/hooks/useWikiPageEdit.ts
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { useI18n } from '../i18n/context';

interface PatchPayload {
  pageUid: string;
  content: string;
  editReason?: string;
  expectedVersion?: number;
}

export function usePatchWikiPage() {
  const queryClient = useQueryClient();
  const { t } = useI18n();
  return useMutation({
    mutationFn: async ({ pageUid, content, editReason, expectedVersion }: PatchPayload) => {
      const resp = await api<Record<string, unknown>>(
        `/wiki/pages/${encodeURIComponent(pageUid)}/content`,
        {
          method: 'PATCH',
          body: JSON.stringify({
            content,
            edit_reason: editReason ?? '',
            expected_version: expectedVersion ?? null,
          }),
        },
      );
      return resp;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['wiki'] });
    },
  });
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd dashboard && pnpm test --run -- useWikiPageEdit`
Expected: PASS

- [ ] **Step 6: Write WikiEditor component test**

```typescript
// dashboard/src/components/wiki/__tests__/WikiEditor.test.tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

describe('WikiEditor', () => {
  it('renders editor with save button', async () => {
    const { WikiEditor } = await import('../WikiEditor');
    const qc = new QueryClient();
    render(
      <QueryClientProvider client={qc}>
        <WikiEditor
          pageUid="test-page"
          initialContent="# Hello"
          currentVersion={1}
          onClose={() => {}}
        />
      </QueryClientProvider>,
    );
    expect(screen.getByRole('button', { name: /save/i })).toBeInTheDocument();
  });
});
```

- [ ] **Step 7: Implement WikiEditor.tsx**

Create `dashboard/src/components/wiki/WikiEditor.tsx`:
- Split view: left CodeMirror (Markdown lang), right MarkdownRenderer preview
- debounced preview (300ms)
- Save button calls `usePatchWikiPage` with `expectedVersion`
- Version mismatch warning from API response
- Close/cancel button

- [ ] **Step 8: Integrate edit mode into WikiContent.tsx**

Add "Edit" button (pencil icon) in WikiContent header (visible when `pageUid` exists).
Clicking toggles between view mode (existing) and edit mode (`<WikiEditor />`).

- [ ] **Step 9: Run tests**

Run: `cd dashboard && pnpm test --run`
Expected: All pass

- [ ] **Step 10: Commit**

```bash
cd dashboard && git add -A
git commit -m "feat(dashboard): WikiEditor with CodeMirror + live preview + version control (P1 Task 4)"
```

---

### Task 5: ReasoningPathPanel

**Files:**
- Create: `dashboard/src/components/wiki/ReasoningPathPanel.tsx`
- Modify: `dashboard/src/components/wiki/AskPanel.tsx` (integrate panel)
- Test: `dashboard/src/components/wiki/__tests__/ReasoningPathPanel.test.tsx`

- [ ] **Step 1: Write failing test**

```typescript
// dashboard/src/components/wiki/__tests__/ReasoningPathPanel.test.tsx
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';

describe('ReasoningPathPanel', () => {
  it('renders stages', async () => {
    const { ReasoningPathPanel } = await import('../ReasoningPathPanel');
    const path = {
      stages: [
        { stage_name: 'search', retriever: 'vector', entity_hits: ['Foo', 'Bar'], score: 0.9, metadata: {} },
        { stage_name: 'graph', retriever: 'graph', entity_hits: ['Baz'], score: null, metadata: {} },
      ],
      answer_entities: ['Foo', 'Baz'],
    };
    render(<ReasoningPathPanel reasoningPath={path} />);
    expect(screen.getByText(/search/)).toBeInTheDocument();
    expect(screen.getByText(/vector/)).toBeInTheDocument();
    expect(screen.getByText(/Foo/)).toBeInTheDocument();
  });

  it('renders nothing when no path', async () => {
    const { ReasoningPathPanel } = await import('../ReasoningPathPanel');
    const { container } = render(<ReasoningPathPanel reasoningPath={null} />);
    expect(container.firstChild).toBeNull();
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd dashboard && pnpm test --run -- ReasoningPathPanel`
Expected: FAIL

- [ ] **Step 3: Implement ReasoningPathPanel.tsx**

Collapsible panel:
- Header: "Reasoning Path" with expand/collapse chevron
- Each stage: card with retriever badge (vector=blue, graph=green, fts=orange), entity chips, score bar
- answer_entities: highlighted chips at bottom
- Uses Tailwind for layout, no external diagram library

- [ ] **Step 4: Integrate into AskPanel.tsx**

After the answer content area in AskPanel, render `<ReasoningPathPanel reasoningPath={lastAnswer?.reasoning_path} />`.

- [ ] **Step 5: Run tests**

Run: `cd dashboard && pnpm test --run`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(dashboard): ReasoningPathPanel for Ask retrieval provenance (P1 Task 5)"
```

---

### Task 6: WikiTierSelector

**Files:**
- Create: `dashboard/src/components/wiki/WikiTierSelector.tsx`
- Modify: `dashboard/src/components/wiki/WikiTreeNav.tsx` (integrate selector)
- Modify: `dashboard/src/hooks/useWikiTree.ts` (pass wiki_tier param)
- Test: `dashboard/src/components/wiki/__tests__/WikiTierSelector.test.tsx`

- [ ] **Step 1: Write failing test**

```typescript
// dashboard/src/components/wiki/__tests__/WikiTierSelector.test.tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

describe('WikiTierSelector', () => {
  it('renders three options', async () => {
    const { WikiTierSelector } = await import('../WikiTierSelector');
    const onChange = vi.fn();
    render(<WikiTierSelector value={null} onChange={onChange} />);
    const select = screen.getByRole('combobox');
    expect(select).toBeInTheDocument();
    fireEvent.change(select, { target: { value: 'standard' } });
    expect(onChange).toHaveBeenCalledWith('standard');
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd dashboard && pnpm test --run -- WikiTierSelector`
Expected: FAIL

- [ ] **Step 3: Implement WikiTierSelector.tsx**

Simple `<select>` dropdown with options: All (null), Standard, Essential.
`onChange` calls parent with the selected value.

- [ ] **Step 4: Integrate into WikiTreeNav.tsx**

- Add `wiki_tier` state from URL search params
- Pass to tree API call via `useWikiTree` hook
- Place selector next to view type toggle

- [ ] **Step 5: Update useWikiTree hook**

Add `wikiTier` to the query key and API call: `GET /wiki/tree?business_id=...&view=...&wiki_tier=standard`

- [ ] **Step 6: Run tests**

Run: `cd dashboard && pnpm test --run`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(dashboard): WikiTierSelector for importance-based tree filtering (P1 Task 6)"
```

---

### Task 7: OfflinePackDownloadButton

**Files:**
- Create: `dashboard/src/components/wiki/OfflinePackDownloadButton.tsx`
- Modify: `dashboard/src/components/wiki/WikiToolPanel.tsx` (add button to export area)
- Test: `dashboard/src/components/wiki/__tests__/OfflinePackDownloadButton.test.tsx`

- [ ] **Step 1: Write failing test**

```typescript
// dashboard/src/components/wiki/__tests__/OfflinePackDownloadButton.test.tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

describe('OfflinePackDownloadButton', () => {
  it('renders download button', async () => {
    const { OfflinePackDownloadButton } = await import('../OfflinePackDownloadButton');
    const qc = new QueryClient();
    render(
      <QueryClientProvider client={qc}>
        <OfflinePackDownloadButton repository="test-repo" businessId="b1" />
      </QueryClientProvider>,
    );
    expect(screen.getByRole('button')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd dashboard && pnpm test --run -- OfflinePackDownloadButton`
Expected: FAIL

- [ ] **Step 3: Implement OfflinePackDownloadButton.tsx**

Button that:
1. On click, fetches `GET /api/v1/wiki/{repository}/offline-pack?business_id=...`
2. Creates Blob from JSON response
3. Triggers browser download as `{repository}-wiki-offline.json`
4. Shows loading spinner during fetch
5. If response has `truncated: true`, shows toast: "Data truncated to 2000 pages"

- [ ] **Step 4: Integrate into WikiToolPanel export section**

Add the button to the export tab in WikiToolPanel, below existing export options.

- [ ] **Step 5: Run tests**

Run: `cd dashboard && pnpm test --run`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(dashboard): OfflinePackDownloadButton for wiki JSON export (P1 Task 7)"
```

---

### Task 8: Frontend Test Coverage → 70%

**Files:**
- Create/modify: various `__tests__/` files across `dashboard/src/`

- [ ] **Step 1: Check current coverage**

Run: `cd dashboard && pnpm test --run --coverage`
Note the current line coverage percentage.

- [ ] **Step 2: Identify coverage gaps**

Run: `cd dashboard && pnpm test --run --coverage 2>&1 | grep -E "^(All files|src/)" | head -20`
Focus on files below 50% coverage in `components/wiki/` and `hooks/`.

- [ ] **Step 3: Add tests for untested components**

Priority order:
1. New P1 components (already tested above)
2. `WikiContent.tsx` — edit mode branch
3. `WikiToolPanel.tsx` — tab switching
4. `WikiTreeNav.tsx` — tier parameter
5. `hooks/useWikiSearch.ts` — query key
6. Other low-coverage wiki hooks

- [ ] **Step 4: Verify coverage target**

Run: `cd dashboard && pnpm test --run --coverage`
Expected: ≥ 70% line coverage

- [ ] **Step 5: Update vitest.config.ts threshold**

Change `lines: 50` to `lines: 70` in coverage thresholds.

- [ ] **Step 6: Final run**

Run: `cd dashboard && pnpm test --run --coverage`
Expected: All pass, coverage meets threshold

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "test(dashboard): raise frontend test coverage to 70% (P1 Task 8)"
```
