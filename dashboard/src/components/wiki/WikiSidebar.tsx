import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  ChevronDown,
  ChevronRight,
  FileText,
  Folder,
  Loader2,
  Search,
} from "lucide-react";
import type { WikiPageSummary } from "../../hooks/wikiTypes";
import { useWikiSearch } from "../../hooks/useWikiSearch";
import {
  getWikiLocalRoot,
  wikiLocalRootKey,
  type EditorId,
} from "./editorLinks";
import { EDITOR_PREF_KEY } from "./SourceLink";

type TreeNode = {
  segment: string;
  fullPath: string;
  title?: string;
  children: TreeNode[];
};

type MutableNode = {
  segment: string;
  fullPath: string;
  title?: string;
  children: Map<string, MutableNode>;
};

function buildTree(pages: WikiPageSummary[]): TreeNode[] {
  const root = new Map<string, MutableNode>();

  for (const p of pages) {
    const segments = p.path.split("/").filter(Boolean);
    if (!segments.length) continue;
    let prefix = "";
    let map = root;
    for (let i = 0; i < segments.length; i++) {
      const seg = segments[i];
      prefix = prefix ? `${prefix}/${seg}` : seg;
      let node = map.get(seg);
      if (!node) {
        node = {
          segment: seg,
          fullPath: prefix,
          children: new Map(),
        };
        map.set(seg, node);
      }
      if (i === segments.length - 1) {
        node.title = p.title;
        node.fullPath = p.path;
      }
      map = node.children;
    }
  }

  function toForest(m: Map<string, MutableNode>): TreeNode[] {
    return [...m.values()]
      .sort((a, b) => a.segment.localeCompare(b.segment))
      .map((n) => ({
        segment: n.segment,
        fullPath: n.fullPath,
        title: n.title,
        children: toForest(n.children),
      }));
  }

  return toForest(root);
}

function wikiHref(repository: string, path: string): string {
  const er = encodeURIComponent(repository);
  const ep = path
    .split("/")
    .filter(Boolean)
    .map((s) => encodeURIComponent(s))
    .join("/");
  return `/wiki/${er}/${ep}`;
}

function TreeSection({
  nodes,
  repository,
  depth,
  expanded,
  toggle,
  activePath,
}: {
  nodes: TreeNode[];
  repository: string;
  depth: number;
  expanded: Set<string>;
  toggle: (key: string) => void;
  activePath: string;
}) {
  return (
    <ul className={depth === 0 ? "space-y-0.5" : "mt-0.5 space-y-0.5 border-l border-gray-100 pl-2"}>
      {nodes.map((node) => {
        const hasKids = node.children.length > 0;
        const isLeaf = !hasKids;
        const key = node.fullPath || `${depth}:${node.segment}`;
        const isOpen = expanded.has(key);
        const isActive = activePath === node.fullPath;

        return (
          <li key={key}>
            <div className="flex items-center gap-0.5">
              {hasKids ? (
                <button
                  type="button"
                  aria-expanded={isOpen}
                  onClick={() => toggle(key)}
                  className="rounded p-0.5 text-gray-400 hover:bg-gray-100 hover:text-gray-700"
                >
                  {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                </button>
              ) : (
                <span className="w-[22px]" />
              )}
              {isLeaf ? (
                <Link
                  to={wikiHref(repository, node.fullPath)}
                  className={`flex min-w-0 flex-1 items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors ${
                    isActive
                      ? "bg-sky-50 font-medium text-sky-900"
                      : "text-gray-700 hover:bg-gray-50"
                  }`}
                >
                  <FileText size={14} className="shrink-0 opacity-70" />
                  <span className="truncate">{node.title ?? node.segment}</span>
                </Link>
              ) : (
                <span className="flex min-w-0 flex-1 items-center gap-2 px-2 py-1.5 text-sm text-gray-600">
                  <Folder size={14} className="shrink-0 text-amber-600/90" />
                  <span className="truncate">{node.segment}</span>
                </span>
              )}
            </div>
            {hasKids && isOpen && (
              <TreeSection
                nodes={node.children}
                repository={repository}
                depth={depth + 1}
                expanded={expanded}
                toggle={toggle}
                activePath={activePath}
              />
            )}
          </li>
        );
      })}
    </ul>
  );
}

type Props = {
  repository: string;
  pages: WikiPageSummary[];
  activePath: string;
  pagesLoading: boolean;
  pagesError: Error | null;
};

export default function WikiSidebar({
  repository,
  pages,
  activePath,
  pagesLoading,
  pagesError,
}: Props) {
  const tree = useMemo(() => buildTree(pages), [pages]);
  const search = useWikiSearch();
  const [searchParams, setSearchParams] = useSearchParams();
  const urlQuery = searchParams.get("q") ?? "";
  const [q, setQ] = useState(urlQuery);
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());

  useEffect(() => {
    if (urlQuery && !search.data && !search.isPending) {
      setQ(urlQuery);
      search.mutate({ repository, query: urlQuery });
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        next.delete("q");
        return next;
      }, { replace: true });
    }
  }, [urlQuery]);

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
    const walk = (nodes: TreeNode[]) => {
      for (const n of nodes) {
        if (n.children.length) keys.add(n.fullPath || n.segment);
        walk(n.children);
      }
    };
    walk(tree);
    setExpanded(keys);
  };

  const [localRoot, setLocalRoot] = useState(() =>
    getWikiLocalRoot(repository),
  );

  useEffect(() => {
    setLocalRoot(getWikiLocalRoot(repository));
  }, [repository]);
  const [editor, setEditor] = useState<EditorId>(() => {
    try {
      const v = localStorage.getItem(EDITOR_PREF_KEY);
      if (v === "vscode" || v === "cursor" || v === "idea") return v;
    } catch {
      /* ignore */
    }
    return "cursor";
  });

  return (
    <aside className="flex w-full shrink-0 flex-col rounded-xl border border-gray-200 bg-white shadow-sm lg:w-80">
      <div className="border-b border-gray-100 px-4 py-3">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500">
          Wiki pages
        </h3>
        <button
          type="button"
          onClick={expandAll}
          className="mt-2 text-xs font-medium text-sky-700 hover:underline"
        >
          Expand all folders
        </button>
      </div>

      <div className="border-b border-gray-100 px-4 py-3">
        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            const query = q.trim();
            if (!query) return;
            search.mutate({ repository, query });
          }}
        >
          <label className="sr-only" htmlFor="wiki-search">
            Search wiki
          </label>
          <div className="flex gap-2">
            <input
              id="wiki-search"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search wiki…"
              className="min-w-0 flex-1 rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none ring-sky-500/30 focus:border-sky-400 focus:ring-2"
            />
            <button
              type="submit"
              disabled={search.isPending}
              className="inline-flex items-center justify-center rounded-lg bg-sky-600 px-3 py-2 text-white hover:bg-sky-500 disabled:opacity-50"
            >
              {search.isPending ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Search className="size-4" />
              )}
            </button>
          </div>
        </form>
        {search.data && search.data.results.length > 0 && (
          <ul className="mt-3 max-h-48 space-y-1 overflow-y-auto rounded-lg border border-gray-100 bg-gray-50 p-2 text-sm">
            {search.data.results.map((r) => (
              <li key={r.page_path}>
                <Link
                  to={wikiHref(repository, r.page_path)}
                  className="block rounded-md px-2 py-1.5 hover:bg-white"
                >
                  <span className="font-medium text-gray-900">{r.title}</span>
                  <span className="mt-0.5 block truncate font-mono text-[11px] text-gray-500">
                    {r.page_path}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
        {search.isError && (
          <p className="mt-2 text-xs text-red-600">
            {(search.error as Error).message}
          </p>
        )}
      </div>

      <div className="flex-1 overflow-y-auto px-2 py-3">
        {pagesLoading && (
          <div className="flex items-center gap-2 px-2 text-sm text-gray-500">
            <Loader2 className="size-4 animate-spin" />
            Loading pages…
          </div>
        )}
        {pagesError && (
          <p className="px-2 text-sm text-red-600">{pagesError.message}</p>
        )}
        {!pagesLoading && !pagesError && tree.length === 0 && (
          <p className="px-2 text-sm text-gray-500">No wiki pages found.</p>
        )}
        {!pagesLoading && !pagesError && tree.length > 0 && (
          <TreeSection
            nodes={tree}
            repository={repository}
            depth={0}
            expanded={expanded}
            toggle={toggle}
            activePath={activePath}
          />
        )}
      </div>

      <div className="border-t border-gray-100 px-4 py-3 text-xs text-gray-600">
        <p className="font-semibold uppercase tracking-wide text-gray-500">
          IDE links
        </p>
        <label className="mt-2 block">
          <span className="text-[11px] text-gray-500">Local repo root</span>
          <input
            value={localRoot}
            onChange={(e) => setLocalRoot(e.target.value)}
            onBlur={() => {
              try {
                localStorage.setItem(
                  wikiLocalRootKey(repository),
                  localRoot.trim(),
                );
              } catch {
                /* ignore */
              }
            }}
            placeholder="/path/to/local/clone"
            className="mt-1 w-full rounded-md border border-gray-200 px-2 py-1.5 font-mono text-[11px] outline-none focus:border-sky-400"
          />
        </label>
        <label className="mt-2 block">
          <span className="text-[11px] text-gray-500">Preferred editor</span>
          <select
            value={editor}
            onChange={(e) => {
              const v = e.target.value as EditorId;
              setEditor(v);
              try {
                localStorage.setItem(EDITOR_PREF_KEY, v);
              } catch {
                /* ignore */
              }
            }}
            className="mt-1 w-full rounded-md border border-gray-200 px-2 py-1.5 text-xs outline-none focus:border-sky-400"
          >
            <option value="cursor">Cursor</option>
            <option value="vscode">VS Code</option>
            <option value="idea">IntelliJ IDEA</option>
          </select>
        </label>
      </div>
    </aside>
  );
}
