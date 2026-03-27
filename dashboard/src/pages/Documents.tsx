import { useCallback, useMemo, useState } from "react";
import { ChevronRight, FileText, Folder, FolderOpen, Loader2, Search, X } from "lucide-react";
import { useDocuments, useDocument, useRepositories } from "../api/hooks";
import type { DocumentItem } from "../api/types";
import { useI18n } from "../i18n/context";
import { SkeletonLine } from "../components/Skeleton";
import MarkdownRenderer from "../components/MarkdownRenderer";

interface TreeNode {
  dirs: Record<string, TreeNode>;
  files: DocumentItem[];
}

function emptyTree(): TreeNode {
  return { dirs: {}, files: [] };
}

function addDocument(root: TreeNode, doc: DocumentItem) {
  const normalized = doc.file.replace(/\\/g, "/");
  const parts = normalized.split("/").filter(Boolean);
  if (parts.length === 0) {
    root.files.push(doc);
    return;
  }
  parts.pop();
  let node = root;
  for (const part of parts) {
    if (!node.dirs[part]) node.dirs[part] = emptyTree();
    node = node.dirs[part];
  }
  node.files.push(doc);
}

function buildTree(docs: DocumentItem[]): TreeNode {
  const root = emptyTree();
  for (const doc of docs) {
    addDocument(root, doc);
  }
  return root;
}

function collectAllDirPaths(node: TreeNode, prefix: string): string[] {
  const paths: string[] = [];
  for (const dn of Object.keys(node.dirs)) {
    const dirPath = prefix ? `${prefix}/${dn}` : dn;
    paths.push(dirPath);
    paths.push(...collectAllDirPaths(node.dirs[dn], dirPath));
  }
  return paths;
}

function treeHasMatch(node: TreeNode, query: string): boolean {
  for (const doc of node.files) {
    if (doc.title.toLowerCase().includes(query) || doc.file.toLowerCase().includes(query)) {
      return true;
    }
  }
  for (const dn of Object.keys(node.dirs)) {
    if (dn.toLowerCase().includes(query) || treeHasMatch(node.dirs[dn], query)) {
      return true;
    }
  }
  return false;
}

function findReadme(node: TreeNode): DocumentItem | undefined {
  return node.files.find((f) => {
    const name = f.file.replace(/\\/g, "/").split("/").pop()?.toLowerCase() ?? "";
    return name === "readme.md" || name === "readme.rst";
  });
}

function TreeView({
  node,
  depth,
  selectedUid,
  onSelect,
  expanded,
  onToggle,
  pathPrefix,
  searchQuery,
}: {
  node: TreeNode;
  depth: number;
  selectedUid: string | null;
  onSelect: (uid: string) => void;
  expanded: Set<string>;
  onToggle: (path: string) => void;
  pathPrefix: string;
  searchQuery: string;
}) {
  const dirNames = Object.keys(node.dirs).sort();
  const sortedFiles = [...node.files].sort((a, b) => a.title.localeCompare(b.title));
  const pad = 8 + depth * 12;
  const lowerQuery = searchQuery.toLowerCase();

  const filteredFiles = lowerQuery
    ? sortedFiles.filter(
        (doc) =>
          doc.title.toLowerCase().includes(lowerQuery) ||
          doc.file.toLowerCase().includes(lowerQuery),
      )
    : sortedFiles;

  const filteredDirs = lowerQuery
    ? dirNames.filter(
        (dn) =>
          dn.toLowerCase().includes(lowerQuery) ||
          treeHasMatch(node.dirs[dn], lowerQuery),
      )
    : dirNames;

  return (
    <>
      {filteredDirs.map((dn) => {
        const dirPath = pathPrefix ? `${pathPrefix}/${dn}` : dn;
        const isOpen = expanded.has(dirPath);
        return (
          <div key={`${depth}-${dn}`} className="select-none">
            <button
              type="button"
              onClick={() => {
                const wasOpen = expanded.has(dirPath);
                onToggle(dirPath);
                if (!wasOpen) {
                  const readme = findReadme(node.dirs[dn]);
                  if (readme) onSelect(readme.uid);
                }
              }}
              className="flex w-full items-center gap-1.5 rounded-lg py-1.5 pr-2 text-sm text-slate-500 transition-colors hover:bg-slate-800/50 hover:text-slate-300"
              style={{ paddingLeft: pad }}
            >
              <ChevronRight
                size={14}
                className={`shrink-0 transition-transform duration-150 ${isOpen ? "rotate-90" : ""}`}
              />
              {isOpen ? (
                <FolderOpen size={16} className="shrink-0 text-amber-500/90" />
              ) : (
                <Folder size={16} className="shrink-0 text-amber-500/90" />
              )}
              <span className="truncate font-medium">{dn}</span>
            </button>
            {isOpen && (
              <TreeView
                node={node.dirs[dn]}
                depth={depth + 1}
                selectedUid={selectedUid}
                onSelect={onSelect}
                expanded={expanded}
                onToggle={onToggle}
                pathPrefix={dirPath}
                searchQuery={searchQuery}
              />
            )}
          </div>
        );
      })}
      {filteredFiles.map((doc) => (
        <button
          key={doc.uid}
          type="button"
          onClick={() => onSelect(doc.uid)}
          className={`flex w-full items-center gap-2 rounded-lg py-1.5 pr-2 text-left text-sm transition-colors ${
            selectedUid === doc.uid
              ? "bg-sky-500/15 text-sky-400"
              : "text-slate-400 hover:bg-slate-800/50 hover:text-slate-200"
          }`}
          style={{ paddingLeft: pad + 18 }}
        >
          <FileText size={16} className="shrink-0 text-slate-500" />
          <span className="truncate">{doc.title}</span>
        </button>
      ))}
    </>
  );
}

function SectionNav({
  sections,
  onScrollTo,
  label,
}: {
  sections: { uid: string; title: string; level?: number }[];
  onScrollTo: (uid: string) => void;
  label: string;
}) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  const minLevel = Math.min(...sections.map((s) => s.level ?? 2));

  const toggleCollapse = (uid: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(uid)) {
        next.delete(uid);
      } else {
        next.add(uid);
      }
      return next;
    });
  };

  const visibleSections: typeof sections = [];
  let skipBelow: number | null = null;
  for (const s of sections) {
    const lvl = s.level ?? 2;
    if (skipBelow !== null && lvl > skipBelow) {
      continue;
    }
    skipBelow = null;
    visibleSections.push(s);
    if (collapsed.has(s.uid)) {
      skipBelow = lvl;
    }
  }

  const hasChildren = (idx: number): boolean => {
    const current = visibleSections[idx];
    const currentLvl = current.level ?? 2;
    const next = sections[sections.indexOf(current) + 1];
    return next !== undefined && (next.level ?? 2) > currentLvl;
  };

  return (
    <nav className="w-full shrink-0 border-t border-slate-800 p-3 lg:w-56 lg:border-l lg:border-t-0">
      <p className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">
        {label}
      </p>
      <ul className="max-h-48 space-y-0.5 overflow-y-auto lg:max-h-none">
        {visibleSections.map((s, i) => {
          const lvl = (s.level ?? 2) - minLevel;
          const pad = lvl * 12;
          const isCollapsed = collapsed.has(s.uid);
          const expandable = hasChildren(i);

          return (
            <li key={s.uid}>
              <div className="flex items-center" style={{ paddingLeft: pad }}>
                {expandable ? (
                  <button
                    type="button"
                    onClick={() => toggleCollapse(s.uid)}
                    className="mr-0.5 shrink-0 rounded p-0.5 text-slate-600 hover:text-slate-400"
                  >
                    <ChevronRight
                      size={12}
                      className={`transition-transform duration-150 ${isCollapsed ? "" : "rotate-90"}`}
                    />
                  </button>
                ) : (
                  <span className="mr-0.5 inline-block w-[16px] shrink-0" />
                )}
                <button
                  type="button"
                  onClick={() => onScrollTo(s.uid)}
                  className={`w-full rounded-lg px-1.5 py-1 text-left text-xs transition-colors hover:bg-slate-800/80 hover:text-sky-400 ${
                    lvl === 0 ? "font-medium text-slate-300" : "text-slate-500"
                  }`}
                >
                  {s.title}
                </button>
              </div>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

export default function Documents() {
  const { t } = useI18n();
  const [repository, setRepository] = useState<string>("");
  const [selectedUid, setSelectedUid] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [expandedInit, setExpandedInit] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");

  const { data: reposData } = useRepositories();
  const {
    data: listData,
    isLoading: listLoading,
    error: listError,
  } = useDocuments(repository || undefined);
  const {
    data: detail,
    isLoading: detailLoading,
    error: detailError,
  } = useDocument(selectedUid);

  const tree = useMemo(
    () => buildTree(listData?.documents ?? []),
    [listData?.documents],
  );

  useMemo(() => {
    if (!expandedInit && listData?.documents && listData.documents.length > 0) {
      setExpanded(new Set());
      setExpandedInit(true);
      const rootReadme = findReadme(tree);
      if (rootReadme) {
        setSelectedUid(rootReadme.uid);
      }
    }
  }, [tree, expandedInit, listData?.documents]);

  const handleToggle = useCallback((path: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(path)) {
        next.delete(path);
      } else {
        next.add(path);
      }
      return next;
    });
  }, []);

  const handleExpandAll = useCallback(() => {
    const allPaths = collectAllDirPaths(tree, "");
    setExpanded(new Set(allPaths));
  }, [tree]);

  const handleCollapseAll = useCallback(() => {
    setExpanded(new Set());
  }, []);

  const allDocs = listData?.documents ?? [];
  const repos = reposData?.repositories ?? [];

  const handleDocLink = useCallback(
    (href: string) => {
      const normalizedHref = href.replace(/\\/g, "/").replace(/^\.\//, "");
      const match = allDocs.find((doc) => {
        const normalizedFile = doc.file.replace(/\\/g, "/");
        return (
          normalizedFile.endsWith(normalizedHref) ||
          normalizedFile.endsWith(`/${normalizedHref}`)
        );
      });
      if (match) {
        setSelectedUid(match.uid);
      }
    },
    [allDocs],
  );

  function scrollToSection(uid: string) {
    const el = document.getElementById(`doc-section-${uid}`);
    el?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-lg font-semibold text-white">
          <FileText size={20} /> {t.documents.title}
        </h2>
      </div>

      <div className="flex min-h-[calc(100vh-10rem)] flex-col gap-4 lg:flex-row">
        <aside className="flex min-h-0 w-full shrink-0 flex-col overflow-hidden rounded-xl border border-slate-800 bg-slate-800/50 lg:w-72">
        <div className="border-b border-slate-800 p-3">
          <label className="mb-1 block text-xs font-medium text-slate-500">
            {t.repos.repository}
          </label>
          <select
            value={repository}
            onChange={(e) => {
              setRepository(e.target.value);
              setSelectedUid(null);
              setExpandedInit(false);
            }}
            className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-300 outline-none ring-sky-500/30 focus:ring-2"
          >
            <option value="">{t.documents.allRepos}</option>
            {repos.map((r) => (
              <option key={r.repository} value={r.repository}>
                {r.repository}
              </option>
            ))}
          </select>
        </div>
        <div className="border-b border-slate-800 px-3 py-2">
          <div className="relative">
            <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder={t.search.placeholder}
              className="w-full rounded-lg border border-slate-700 bg-slate-900 py-1.5 pl-8 pr-8 text-sm text-slate-300 outline-none ring-sky-500/30 placeholder:text-slate-600 focus:ring-2"
            />
            {searchQuery && (
              <button
                type="button"
                onClick={() => setSearchQuery("")}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
              >
                <X size={14} />
              </button>
            )}
          </div>
          <div className="mt-1.5 flex gap-1">
            <button
              type="button"
              onClick={handleExpandAll}
              className="rounded px-2 py-0.5 text-xs text-slate-500 transition-colors hover:bg-slate-800 hover:text-slate-300"
            >
              {t.documents.expandAll ?? "Expand All"}
            </button>
            <button
              type="button"
              onClick={handleCollapseAll}
              className="rounded px-2 py-0.5 text-xs text-slate-500 transition-colors hover:bg-slate-800 hover:text-slate-300"
            >
              {t.documents.collapseAll ?? "Collapse All"}
            </button>
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          {listLoading ? (
            <div className="space-y-2 p-2">
              {Array.from({ length: 6 }).map((_, i) => (
                <SkeletonLine key={i} className="h-4 w-full" />
              ))}
            </div>
          ) : listError ? (
            <div className="p-3 text-sm text-red-400">
              {(listError as Error).message}
            </div>
          ) : (listData?.documents.length ?? 0) === 0 ? (
            <div className="p-3 text-sm text-slate-500">{t.search.noResults}</div>
          ) : (
            <TreeView
              node={tree}
              depth={0}
              selectedUid={selectedUid}
              onSelect={setSelectedUid}
              expanded={expanded}
              onToggle={handleToggle}
              pathPrefix=""
              searchQuery={searchQuery}
            />
          )}
        </div>
        </aside>

        <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-xl border border-slate-800 bg-slate-800/50">
        {!selectedUid ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 p-8 text-center text-slate-500">
            <FileText size={40} className="text-slate-600" />
            <p className="text-sm">{t.documents.selectDoc}</p>
          </div>
        ) : detailLoading ? (
          <div className="flex flex-1 items-center justify-center gap-2 text-slate-500">
            <Loader2 size={20} className="animate-spin" />
            <span className="text-sm">{t.search.searching}</span>
          </div>
        ) : detailError ? (
          <div className="p-6 text-sm text-red-400">
            {(detailError as Error).message}
          </div>
        ) : detail ? (
          <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
            <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden border-b border-slate-800 lg:border-b-0 lg:border-r">
              <div className="shrink-0 border-b border-slate-800 p-4">
                <h2 className="text-lg font-semibold text-white">{detail.title}</h2>
                <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                  <span className="font-mono text-slate-400">{detail.file}</span>
                  <span className="rounded-md border border-slate-700 bg-slate-900/80 px-2 py-0.5 text-sky-400">
                    {detail.repository}
                  </span>
                </div>
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto p-4">
                {detail.sections.map((section) => (
                  <div
                    key={section.uid}
                    id={`doc-section-${section.uid}`}
                    className="scroll-mt-4 border-b border-slate-800/80 pb-6 last:border-0 last:pb-0"
                  >
                    <h3 className="mb-3 text-sm font-semibold text-slate-200">
                      {section.title}
                    </h3>
                    <MarkdownRenderer content={section.content} onDocLink={handleDocLink} />
                  </div>
                ))}
              </div>
            </div>
            {detail.sections.length > 0 && (
              <SectionNav sections={detail.sections} onScrollTo={scrollToSection} label={t.documents.sections} />
            )}
          </div>
        ) : null}
        </div>
      </div>
    </div>
  );
}
