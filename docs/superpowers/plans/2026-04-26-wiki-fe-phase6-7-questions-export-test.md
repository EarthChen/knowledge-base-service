# Wiki Frontend Phase 6+7: Suggested Questions, Business Export + Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add suggested exploration questions to wiki pages, upgrade the export panel to support business-level multi-format export with Git push config, and set up frontend test infrastructure with comprehensive tests for FE-Phase 1-6 components.

**Architecture:** WikiSuggestedQuestions is a collapsible section at the page bottom. WikiBusinessExportPanel replaces the existing single-repo WikiExportPanel with format selection (markdown/zip/git/obsidian/mkdocs), Git config dialog, and tier filter. Test infrastructure uses Vitest + React Testing Library with MSW for API mocking.

**Tech Stack:** React 19, TypeScript 5.9, @tanstack/react-query 5, Vitest, @testing-library/react, msw (Mock Service Worker), lucide-react, Tailwind CSS 4

**Depends on:** FE-Phase 1-5

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `dashboard/src/components/wiki/WikiSuggestedQuestions.tsx` | Suggested exploration questions |
| Create | `dashboard/src/components/wiki/WikiBusinessExportPanel.tsx` | Business-level multi-format export |
| Create | `dashboard/src/components/wiki/GitPushConfigDialog.tsx` | Git remote config dialog |
| Modify | `dashboard/src/components/wiki/WikiContent.tsx` | Add WikiSuggestedQuestions section |
| Modify | `dashboard/src/components/wiki/WikiShell.tsx` | Wire business export tab |
| Create | `dashboard/vitest.config.ts` | Test runner configuration |
| Create | `dashboard/src/test/setup.ts` | Test global setup |
| Create | `dashboard/src/test/mocks/handlers.ts` | MSW API handlers |
| Create | `dashboard/src/test/mocks/server.ts` | MSW server setup |
| Create | `dashboard/src/components/wiki/__tests__/WikiCoverageCard.test.tsx` | Coverage card test |
| Create | `dashboard/src/components/wiki/__tests__/WikiStaleAlert.test.tsx` | Stale alert test |
| Create | `dashboard/src/components/wiki/__tests__/WikiSuggestedQuestions.test.tsx` | Questions test |
| Create | `dashboard/src/components/wiki/__tests__/wikilinkParser.test.ts` | Parser unit test |
| Create | `dashboard/src/components/wiki/__tests__/wikiRouteHelpers.test.ts` | Route helper test |
| Create | `dashboard/src/hooks/__tests__/useWikiTree.test.tsx` | Hook test |
| Modify | `dashboard/package.json` | Add test dependencies and script |

---

### Task 1: Create WikiSuggestedQuestions component

**Files:**
- Create: `dashboard/src/components/wiki/WikiSuggestedQuestions.tsx`

- [ ] **Step 1: Create the component**

```typescript
import { useState } from "react";
import { ChevronDown, ChevronUp, HelpCircle, MessageCircle } from "lucide-react";

interface WikiSuggestedQuestionsProps {
  questions: string[];
  onAskQuestion?: (question: string) => void;
}

export default function WikiSuggestedQuestions({
  questions,
  onAskQuestion,
}: WikiSuggestedQuestionsProps) {
  const [expanded, setExpanded] = useState(false);

  if (questions.length === 0) return null;

  return (
    <section className="mt-8 border-t border-gray-100 pt-6 dark:border-gray-800">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center justify-between gap-3 rounded-lg px-1 py-2 text-left hover:bg-gray-50/80 dark:hover:bg-gray-800/60"
      >
        <span className="flex items-center gap-2 text-sm font-semibold text-gray-900 dark:text-gray-100">
          <HelpCircle size={18} className="text-sky-600 dark:text-sky-400" aria-hidden />
          Explore further
        </span>
        {expanded ? (
          <ChevronUp size={18} className="text-gray-500 dark:text-gray-400" />
        ) : (
          <ChevronDown size={18} className="text-gray-500 dark:text-gray-400" />
        )}
      </button>

      {expanded && (
        <ul className="mt-3 space-y-2">
          {questions.map((q, i) => (
            <li key={i}>
              <button
                type="button"
                onClick={() => onAskQuestion?.(q)}
                className="flex w-full items-start gap-3 rounded-lg border border-gray-100 bg-gray-50/50 px-4 py-3 text-left transition-colors hover:border-sky-200 hover:bg-sky-50/40 dark:border-gray-800 dark:bg-gray-800/30 dark:hover:border-sky-900 dark:hover:bg-sky-950/20"
              >
                <MessageCircle size={16} className="mt-0.5 shrink-0 text-sky-500" />
                <span className="text-sm text-gray-800 dark:text-gray-200">{q}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
```

- [ ] **Step 2: Verify TypeScript compilation**

Run: `cd dashboard && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/components/wiki/WikiSuggestedQuestions.tsx
git commit -m "feat(dashboard): add WikiSuggestedQuestions collapsible section"
```

---

### Task 2: Create GitPushConfigDialog + WikiBusinessExportPanel

**Files:**
- Create: `dashboard/src/components/wiki/GitPushConfigDialog.tsx`
- Create: `dashboard/src/components/wiki/WikiBusinessExportPanel.tsx`

- [ ] **Step 1: Create GitPushConfigDialog**

```typescript
import { useState } from "react";
import { X } from "lucide-react";
import FocusTrap from "../FocusTrap";

interface GitConfig {
  remote_url: string;
  branch: string;
  commit_message_prefix: string;
}

interface GitPushConfigDialogProps {
  open: boolean;
  onClose: () => void;
  onConfirm: (config: GitConfig) => void;
}

export default function GitPushConfigDialog({ open, onClose, onConfirm }: GitPushConfigDialogProps) {
  const [remoteUrl, setRemoteUrl] = useState("");
  const [branch, setBranch] = useState("main");
  const [prefix, setPrefix] = useState("docs(wiki): ");

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 dark:bg-black/50">
      <FocusTrap>
        <div className="w-full max-w-md rounded-xl border border-gray-200 bg-white p-6 shadow-2xl dark:border-gray-700 dark:bg-gray-900">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
              Git Push Configuration
            </h3>
            <button type="button" onClick={onClose} className="rounded p-1 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200">
              <X size={16} />
            </button>
          </div>
          <div className="mt-4 space-y-3">
            <label className="block">
              <span className="text-xs font-medium text-gray-600 dark:text-gray-400">Remote URL</span>
              <input
                value={remoteUrl}
                onChange={(e) => setRemoteUrl(e.target.value)}
                placeholder="https://github.com/org/wiki-repo.git"
                className="mt-1 w-full rounded-lg border border-gray-200 px-3 py-2 font-mono text-sm outline-none focus:border-sky-400 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
              />
            </label>
            <label className="block">
              <span className="text-xs font-medium text-gray-600 dark:text-gray-400">Branch</span>
              <input
                value={branch}
                onChange={(e) => setBranch(e.target.value)}
                className="mt-1 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:border-sky-400 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
              />
            </label>
            <label className="block">
              <span className="text-xs font-medium text-gray-600 dark:text-gray-400">Commit Message Prefix</span>
              <input
                value={prefix}
                onChange={(e) => setPrefix(e.target.value)}
                className="mt-1 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:border-sky-400 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
              />
            </label>
          </div>
          <div className="mt-5 flex justify-end gap-3">
            <button type="button" onClick={onClose} className="rounded-lg px-4 py-2 text-sm text-gray-600 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-800">
              Cancel
            </button>
            <button
              type="button"
              onClick={() => {
                if (!remoteUrl.trim()) return;
                onConfirm({ remote_url: remoteUrl.trim(), branch: branch.trim() || "main", commit_message_prefix: prefix });
                onClose();
              }}
              disabled={!remoteUrl.trim()}
              className="rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-500 disabled:opacity-50"
            >
              Confirm
            </button>
          </div>
        </div>
      </FocusTrap>
    </div>
  );
}
```

- [ ] **Step 2: Create WikiBusinessExportPanel**

```typescript
import { useState } from "react";
import { Download, FileOutput, GitBranch, Loader2 } from "lucide-react";
import { useBusinessWikiExport } from "../../hooks/useBusinessWikiExport";
import { useBusiness } from "../../contexts/BusinessContext";
import GitPushConfigDialog from "./GitPushConfigDialog";
import type { BusinessWikiExportBody } from "../../hooks/wikiTypes";

type ExportFormat = BusinessWikiExportBody["format"];
type ViewType = BusinessWikiExportBody["view_type"];
type MinTier = BusinessWikiExportBody["min_tier"];

const FORMAT_OPTIONS: { value: ExportFormat; label: string; desc: string }[] = [
  { value: "markdown", label: "Markdown", desc: "Flat markdown files" },
  { value: "zip", label: "ZIP", desc: "Compressed archive" },
  { value: "obsidian", label: "Obsidian", desc: "Obsidian vault with config" },
  { value: "mkdocs", label: "MkDocs", desc: "MkDocs site with mkdocs.yml" },
  { value: "git", label: "Git Push", desc: "Push to Git repository" },
];

export default function WikiBusinessExportPanel() {
  const { currentBusiness } = useBusiness();
  const exportMutation = useBusinessWikiExport();
  const [format, setFormat] = useState<ExportFormat>("markdown");
  const [viewType, setViewType] = useState<ViewType>("both");
  const [minTier, setMinTier] = useState<MinTier>("standard");
  const [gitDialogOpen, setGitDialogOpen] = useState(false);
  const [gitConfig, setGitConfig] = useState<BusinessWikiExportBody["git_config"]>();

  const handleExport = () => {
    if (format === "git" && !gitConfig) {
      setGitDialogOpen(true);
      return;
    }
    const body: BusinessWikiExportBody = {
      business_id: currentBusiness,
      format,
      view_type: viewType,
      min_tier: minTier,
    };
    if (format === "git" && gitConfig) body.git_config = gitConfig;
    exportMutation.mutate(body);
  };

  return (
    <section className="rounded-xl border border-gray-200 bg-white shadow-sm dark:border-gray-700 dark:bg-gray-900">
      <div className="flex items-center gap-2 border-b border-gray-100 px-4 py-3 dark:border-gray-700">
        <FileOutput size={18} className="text-sky-600 dark:text-sky-400" />
        <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">Business Wiki Export</span>
      </div>

      <div className="space-y-4 px-4 py-4">
        <div>
          <label className="block text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">Format</label>
          <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
            {FORMAT_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                onClick={() => setFormat(opt.value)}
                className={`rounded-lg border px-3 py-2 text-left text-xs transition-colors ${
                  format === opt.value
                    ? "border-sky-300 bg-sky-50 text-sky-800 dark:border-sky-700 dark:bg-sky-950/50 dark:text-sky-200"
                    : "border-gray-200 bg-white text-gray-700 hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-300 dark:hover:bg-gray-800"
                }`}
              >
                <span className="block font-medium">{opt.label}</span>
                <span className="mt-0.5 block text-[11px] text-gray-500 dark:text-gray-400">{opt.desc}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-wrap gap-4">
          <label className="block">
            <span className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">View</span>
            <select
              value={viewType}
              onChange={(e) => setViewType(e.target.value as ViewType)}
              className="mt-1 block rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:border-sky-400 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
            >
              <option value="both">Both views</option>
              <option value="business_domain">Business domain</option>
              <option value="code_structure">Code structure</option>
            </select>
          </label>
          <label className="block">
            <span className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">Min Tier</span>
            <select
              value={minTier}
              onChange={(e) => setMinTier(e.target.value as MinTier)}
              className="mt-1 block rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:border-sky-400 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
            >
              <option value="core">Core only</option>
              <option value="standard">Standard+</option>
              <option value="skeleton">All (incl. skeleton)</option>
            </select>
          </label>
        </div>

        {format === "git" && (
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => setGitDialogOpen(true)}
              className="inline-flex items-center gap-2 rounded-lg border border-gray-200 px-3 py-2 text-xs font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-700 dark:text-gray-300 dark:hover:bg-gray-800"
            >
              <GitBranch size={14} />
              {gitConfig ? "Edit Git Config" : "Configure Git Remote"}
            </button>
            {gitConfig && (
              <span className="truncate font-mono text-xs text-gray-500">{gitConfig.remote_url}</span>
            )}
          </div>
        )}

        <button
          type="button"
          onClick={handleExport}
          disabled={exportMutation.isPending || (format === "git" && !gitConfig)}
          className="inline-flex items-center gap-2 rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-500 disabled:opacity-50"
        >
          {exportMutation.isPending ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <Download size={16} />
          )}
          Export
        </button>

        {exportMutation.isError && (
          <p className="text-sm text-red-600 dark:text-red-400">
            {exportMutation.error instanceof Error ? exportMutation.error.message : "Export failed"}
          </p>
        )}

        {exportMutation.data && (
          <div className="rounded-lg border border-emerald-200 bg-emerald-50/80 px-3 py-3 text-sm text-emerald-900 dark:border-emerald-900/50 dark:bg-emerald-950/40 dark:text-emerald-100">
            <p className="font-semibold">Export complete</p>
            <p className="mt-1 text-xs">
              {exportMutation.data.file_count} files exported ({exportMutation.data.format})
              {exportMutation.data.download_url && (
                <a href={exportMutation.data.download_url} className="ml-2 text-sky-600 underline">Download</a>
              )}
            </p>
          </div>
        )}
      </div>

      <GitPushConfigDialog
        open={gitDialogOpen}
        onClose={() => setGitDialogOpen(false)}
        onConfirm={(config) => setGitConfig(config)}
      />
    </section>
  );
}
```

- [ ] **Step 3: Verify TypeScript compilation**

Run: `cd dashboard && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/components/wiki/GitPushConfigDialog.tsx dashboard/src/components/wiki/WikiBusinessExportPanel.tsx
git commit -m "feat(dashboard): add WikiBusinessExportPanel with multi-format export and Git push config"
```

---

### Task 3: Wire new components into WikiContent and WikiShell

**Files:**
- Modify: `dashboard/src/components/wiki/WikiContent.tsx`
- Modify: `dashboard/src/components/wiki/WikiShell.tsx`

- [ ] **Step 1: Add WikiSuggestedQuestions to WikiContent**

In `WikiContent.tsx`, import WikiSuggestedQuestions:

```typescript
import WikiSuggestedQuestions from "./WikiSuggestedQuestions";
```

After the `CallChainSection` rendering (around line 349), add:

```typescript
            <WikiSuggestedQuestions
              questions={detail.context?.suggested_questions
                ? JSON.parse(detail.context.suggested_questions)
                : []}
            />
```

- [ ] **Step 2: Wire WikiBusinessExportPanel in WikiShell**

In `WikiShell.tsx`, import:

```typescript
import WikiBusinessExportPanel from "./WikiBusinessExportPanel";
```

Replace the existing export tab rendering:
```typescript
          {toolTab === "export" && <WikiExportPanel repository="" />}
```
With:
```typescript
          {toolTab === "export" && <WikiBusinessExportPanel />}
```

- [ ] **Step 3: Verify TypeScript compilation**

Run: `cd dashboard && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/components/wiki/WikiContent.tsx dashboard/src/components/wiki/WikiShell.tsx
git commit -m "feat(dashboard): wire WikiSuggestedQuestions and WikiBusinessExportPanel"
```

---

### Task 4: Setup test infrastructure

**Files:**
- Modify: `dashboard/package.json`
- Create: `dashboard/vitest.config.ts`
- Create: `dashboard/src/test/setup.ts`

- [ ] **Step 1: Install test dependencies**

Run:
```bash
cd dashboard && pnpm add -D vitest @testing-library/react @testing-library/jest-dom @testing-library/user-event jsdom msw
```

- [ ] **Step 2: Add test script to package.json**

In `dashboard/package.json`, add to `"scripts"`:

```json
"test": "vitest run",
"test:watch": "vitest"
```

- [ ] **Step 3: Create vitest.config.ts**

```typescript
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
```

- [ ] **Step 4: Create test setup file**

```typescript
import "@testing-library/jest-dom/vitest";
```

- [ ] **Step 5: Verify test setup**

Run: `cd dashboard && pnpm test`
Expected: "No test files found" (no tests yet, but setup works)

- [ ] **Step 6: Commit**

```bash
git add dashboard/package.json dashboard/vitest.config.ts dashboard/src/test/setup.ts dashboard/pnpm-lock.yaml
git commit -m "chore(dashboard): setup Vitest + React Testing Library + MSW test infrastructure"
```

---

### Task 5: Write unit tests for utility functions

**Files:**
- Create: `dashboard/src/components/wiki/__tests__/wikilinkParser.test.ts`
- Create: `dashboard/src/components/wiki/__tests__/wikiRouteHelpers.test.ts`

- [ ] **Step 1: Create wikilinkParser tests**

```typescript
import { describe, it, expect } from "vitest";
import { parseWikilinks, replaceWikilinksWithHtml } from "../wikilinkParser";

describe("parseWikilinks", () => {
  it("parses simple wikilink", () => {
    const result = parseWikilinks("See [[user/auth]]");
    expect(result).toEqual([
      { raw: "[[user/auth]]", path: "user/auth", label: "auth" },
    ]);
  });

  it("parses wikilink with label", () => {
    const result = parseWikilinks("[[user/auth|Authentication]]");
    expect(result).toEqual([
      { raw: "[[user/auth|Authentication]]", path: "user/auth", label: "Authentication" },
    ]);
  });

  it("parses multiple wikilinks", () => {
    const result = parseWikilinks("[[a/b]] and [[c/d|D]]");
    expect(result).toHaveLength(2);
  });

  it("returns empty for no wikilinks", () => {
    expect(parseWikilinks("plain text")).toEqual([]);
  });
});

describe("replaceWikilinksWithHtml", () => {
  it("replaces wikilink with HTML element", () => {
    const result = replaceWikilinksWithHtml("See [[user/auth]]");
    expect(result).toContain("<wikilink");
    expect(result).toContain('data-path="user%2Fauth"');
    expect(result).toContain("auth</wikilink>");
  });

  it("uses custom label", () => {
    const result = replaceWikilinksWithHtml("[[path|Label]]");
    expect(result).toContain("Label</wikilink>");
  });
});
```

- [ ] **Step 2: Create wikiRouteHelpers tests**

```typescript
import { describe, it, expect } from "vitest";
import { wikiHref, wikiSearchHref, parseWikiSearchParams } from "../wikiRouteHelpers";

describe("wikiHref", () => {
  it("returns /wiki with no args", () => {
    expect(wikiHref()).toBe("/wiki");
  });

  it("returns path param", () => {
    expect(wikiHref("user/auth")).toBe("/wiki?path=user%2Fauth");
  });

  it("includes extra params", () => {
    const href = wikiHref("a/b", { view: "code_structure" });
    expect(href).toContain("path=a%2Fb");
    expect(href).toContain("view=code_structure");
  });
});

describe("wikiSearchHref", () => {
  it("encodes query", () => {
    expect(wikiSearchHref("test query")).toBe("/search?mode=wiki&q=test%20query");
  });
});

describe("parseWikiSearchParams", () => {
  it("parses defaults", () => {
    const result = parseWikiSearchParams(new URLSearchParams());
    expect(result.path).toBeNull();
    expect(result.viewType).toBe("business_domain");
    expect(result.toolTab).toBe("page");
  });

  it("parses all params", () => {
    const sp = new URLSearchParams("path=a/b&view=code_structure&tool=export");
    const result = parseWikiSearchParams(sp);
    expect(result.path).toBe("a/b");
    expect(result.viewType).toBe("code_structure");
    expect(result.toolTab).toBe("export");
  });
});
```

- [ ] **Step 3: Run tests**

Run: `cd dashboard && pnpm test`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/components/wiki/__tests__/
git commit -m "test(dashboard): add unit tests for wikilinkParser and wikiRouteHelpers"
```

---

### Task 6: Write component tests

**Files:**
- Create: `dashboard/src/components/wiki/__tests__/WikiStaleAlert.test.tsx`
- Create: `dashboard/src/components/wiki/__tests__/WikiSuggestedQuestions.test.tsx`

- [ ] **Step 1: Create WikiStaleAlert test**

```typescript
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import WikiStaleAlert from "../WikiStaleAlert";

describe("WikiStaleAlert", () => {
  it("renders nothing when not stale", () => {
    const { container } = render(
      <WikiStaleAlert generatedAt="2026-01-01" isStale={false} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders warning when stale", () => {
    render(<WikiStaleAlert generatedAt="2026-01-01" isStale={true} />);
    expect(screen.getByText(/outdated/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Create WikiSuggestedQuestions test**

```typescript
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import WikiSuggestedQuestions from "../WikiSuggestedQuestions";

describe("WikiSuggestedQuestions", () => {
  it("renders nothing with empty questions", () => {
    const { container } = render(<WikiSuggestedQuestions questions={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("shows questions after expanding", () => {
    render(<WikiSuggestedQuestions questions={["Q1?", "Q2?"]} />);
    fireEvent.click(screen.getByText(/explore further/i));
    expect(screen.getByText("Q1?")).toBeInTheDocument();
    expect(screen.getByText("Q2?")).toBeInTheDocument();
  });

  it("calls onAskQuestion when clicked", () => {
    const handler = vi.fn();
    render(<WikiSuggestedQuestions questions={["Q1?"]} onAskQuestion={handler} />);
    fireEvent.click(screen.getByText(/explore further/i));
    fireEvent.click(screen.getByText("Q1?"));
    expect(handler).toHaveBeenCalledWith("Q1?");
  });
});
```

- [ ] **Step 3: Run tests**

Run: `cd dashboard && pnpm test`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/components/wiki/__tests__/
git commit -m "test(dashboard): add component tests for WikiStaleAlert and WikiSuggestedQuestions"
```

---

### Task 7: Final verification

- [ ] **Step 1: Run full TypeScript check**

Run: `cd dashboard && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 2: Run all tests**

Run: `cd dashboard && pnpm test`
Expected: All tests pass

- [ ] **Step 3: Verify build**

Run: `cd dashboard && pnpm build`
Expected: Build succeeds
