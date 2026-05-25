import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Highlight, themes } from "prism-react-renderer";
import {
  BookOpen,
  ChevronRight,
  FileCode,
  Folder,
  FolderOpen,
  Loader2,
  Network,
  Search,
} from "lucide-react";
import { useFileContent, useFileEntities, useFileTree, useRepositories } from "../api/hooks";
import type { FileEntityItem, FileTreeNode } from "../api/types";
import { useI18n } from "../i18n/context";
import { getErrorMessage } from "../utils/errorUtils";

const EXT_TO_LANG: Record<string, string> = {
  py: "python",
  java: "java",
  go: "go",
  js: "javascript",
  jsx: "jsx",
  ts: "typescript",
  tsx: "tsx",
  md: "markdown",
  json: "json",
  yaml: "yaml",
  yml: "yaml",
  rs: "rust",
  kt: "kotlin",
};

function detectLanguage(filePath: string): string {
  const ext = filePath.split(".").pop()?.toLowerCase() ?? "";
  return EXT_TO_LANG[ext] ?? "typescript";
}

function fileIconClass(fileName: string): string {
  const ext = fileName.split(".").pop()?.toLowerCase() ?? "";
  const map: Record<string, string> = {
    py: "text-emerald-600 dark:text-emerald-400",
    java: "text-amber-600 dark:text-amber-400",
    go: "text-cyan-600 dark:text-cyan-400",
    js: "text-yellow-600 dark:text-yellow-400",
    ts: "text-blue-600 dark:text-blue-400",
    tsx: "text-sky-600 dark:text-sky-400",
    jsx: "text-yellow-600 dark:text-yellow-400",
  };
  return map[ext] ?? "text-gray-500 dark:text-gray-400";
}

function filterTree(node: FileTreeNode, q: string): FileTreeNode | null {
  const query = q.trim().toLowerCase();
  if (!query) return node;
  if (node.type === "file") {
    const hit =
      node.name.toLowerCase().includes(query) || node.path.toLowerCase().includes(query);
    return hit ? node : null;
  }
  const kids = (node.children || [])
    .map((c) => filterTree(c, q))
    .filter(Boolean) as FileTreeNode[];
  if (kids.length === 0) return null;
  return { ...node, children: kids };
}

function dirPrefixesForPath(filePath: string): string[] {
  const parts = filePath.split("/").filter(Boolean);
  const out: string[] = [];
  for (let i = 0; i < parts.length - 1; i++) {
    out.push(parts.slice(0, i + 1).join("/"));
  }
  return out;
}

function useHtmlClassDark(): boolean {
  const [dark, setDark] = useState(
    () => typeof document !== "undefined" && document.documentElement.classList.contains("dark"),
  );
  useEffect(() => {
    const el = document.documentElement;
    const sync = () => setDark(el.classList.contains("dark"));
    sync();
    const mo = new MutationObserver(sync);
    mo.observe(el, { attributes: true, attributeFilter: ["class"] });
    return () => mo.disconnect();
  }, []);
  return dark;
}

function TreeRows({
  node,
  depth,
  expanded,
  onToggle,
  selectedPath,
  onSelectFile,
  filterActive,
  isRoot = false,
}: {
  node: FileTreeNode;
  depth: number;
  expanded: Set<string>;
  onToggle: (path: string | string[]) => void;
  selectedPath: string | null;
  onSelectFile: (path: string, repo?: string) => void;
  filterActive: boolean;
  isRoot?: boolean;
}) {
  const children = node.children || [];
  const rows = children.map((child) => (
    <TreeRow
      key={`${child.type}:${child.path}:${child.name}`}
      node={child}
      depth={depth}
      expanded={expanded}
      onToggle={onToggle}
      selectedPath={selectedPath}
      onSelectFile={onSelectFile}
      filterActive={filterActive}
    />
  ));
  if (isRoot) {
    return <ul role="tree" className="space-y-0.5">{rows}</ul>;
  }
  return <ul role="group" className="space-y-0.5">{rows}</ul>;
}

function compactDirChain(node: FileTreeNode): { label: string; leaf: FileTreeNode; intermediates: string[] } {
  const parts: string[] = [node.name];
  const midPaths: string[] = [];
  let cur = node;
  while (
    cur.type === "directory" &&
    cur.children?.length === 1 &&
    cur.children[0].type === "directory"
  ) {
    midPaths.push(cur.path);
    cur = cur.children[0];
    parts.push(cur.name);
  }
  return { label: parts.join("/"), leaf: cur, intermediates: midPaths };
}

function TreeRow({
  node,
  depth,
  expanded,
  onToggle,
  selectedPath,
  onSelectFile,
  filterActive,
}: {
  node: FileTreeNode;
  depth: number;
  expanded: Set<string>;
  onToggle: (path: string | string[]) => void;
  selectedPath: string | null;
  onSelectFile: (path: string, repo?: string) => void;
  filterActive: boolean;
}) {
  const pad = 8 + depth * 12;
  const isDir = node.type === "directory";
  const selected = node.type === "file" && selectedPath === node.path;

  if (isDir) {
    const { label, leaf, intermediates } = compactDirChain(node);
    const isOpen = expanded.has(leaf.path) || intermediates.some((p) => expanded.has(p));

    const handleToggle = () => {
      onToggle([leaf.path, ...intermediates]);
    };

    return (
      <li role="treeitem" aria-expanded={isOpen} className="list-none">
        <button
          type="button"
          style={{ paddingLeft: pad }}
          onClick={handleToggle}
          aria-expanded={isOpen}
          className="flex w-full items-center gap-1 rounded-md py-1 text-left text-sm text-gray-800 hover:bg-gray-100 dark:text-gray-100 dark:hover:bg-gray-800"
        >
          <ChevronRight
            size={14}
            className={`shrink-0 text-gray-500 transition-transform ${isOpen ? "rotate-90" : ""}`}
          />
          {isOpen ? (
            <FolderOpen size={15} className="shrink-0 text-amber-500 dark:text-amber-400" />
          ) : (
            <Folder size={15} className="shrink-0 text-amber-600/90 dark:text-amber-400/90" />
          )}
          <span className="min-w-0 truncate font-medium">{label}</span>
        </button>
        {isOpen && (
          <TreeRows
            node={leaf}
            depth={depth + 1}
            expanded={expanded}
            onToggle={onToggle}
            selectedPath={selectedPath}
            onSelectFile={onSelectFile}
            filterActive={filterActive}
          />
        )}
      </li>
    );
  }

  return (
    <li role="treeitem" className="list-none">
      <button
        type="button"
        style={{ paddingLeft: pad }}
        onClick={() => onSelectFile(node.path, node.repository)}
        className={`flex w-full items-center gap-1 rounded-md py-1 text-left text-sm hover:bg-gray-100 dark:hover:bg-gray-800 ${
          selected
            ? "bg-sky-50 text-sky-900 dark:bg-sky-950/50 dark:text-sky-100"
            : "text-gray-800 dark:text-gray-100"
        }`}
      >
        <span className="w-3 shrink-0" aria-hidden />
        <FileCode size={15} className={`shrink-0 ${fileIconClass(node.name)}`} />
        <span className="min-w-0 truncate">{node.name}</span>
      </button>
    </li>
  );
}

export default function FileExplorer() {
  const { t } = useI18n();
  const isDark = useHtmlClassDark();
  const prismTheme = isDark ? themes.oneDark : themes.oneLight;

  const { data: reposData } = useRepositories();
  const repos = reposData?.repositories ?? [];

  const [repository, setRepository] = useState("");
  const [treeFilter, setTreeFilter] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [selectedRepo, setSelectedRepo] = useState<string>("");
  const [focusedEntity, setFocusedEntity] = useState<FileEntityItem | null>(null);

  useEffect(() => {
    if (!repository && repos.length > 0) {
      setRepository(repos[0].repository);
    }
  }, [repository, repos]);

  const { data: treeData, isLoading: treeLoading, error: treeError } = useFileTree(repository);

  const filteredTree = useMemo(() => {
    if (!treeData) return null;
    const q = treeFilter.trim();
    if (!q) return treeData;
    return filterTree(treeData, q);
  }, [treeData, treeFilter]);

  const repoForContent = (selectedRepo || repository).trim();
  const contentQueryEnabled = !!(selectedPath && repoForContent);
  const {
    data: content,
    isPending: contentPending,
    isFetching: contentFetching,
    error: contentError,
  } = useFileContent(repoForContent, selectedPath ?? "", contentQueryEnabled);
  const contentLoading =
    contentQueryEnabled &&
    !contentError &&
    (contentFetching || (contentPending && content === undefined));

  const { data: entitiesData, isLoading: entitiesLoading } = useFileEntities(selectedPath ?? "", !!selectedPath);

  const linesStart = content?.start_line ?? 1;

  const entityByLine = useMemo(() => {
    const map = new Map<number, FileEntityItem>();
    const list = entitiesData?.entities ?? [];
    const sorted = [...list].sort((a, b) => (a.start_line ?? 0) - (b.start_line ?? 0));
    for (const e of sorted) {
      const ln = e.start_line;
      if (typeof ln === "number" && !map.has(ln)) map.set(ln, e);
    }
    return map;
  }, [entitiesData]);

  const toggle = useCallback((pathOrPaths: string | string[]) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      const paths = Array.isArray(pathOrPaths) ? pathOrPaths : [pathOrPaths];
      const primary = paths[0];
      const shouldOpen = !next.has(primary);
      for (const p of paths) {
        if (shouldOpen) next.add(p);
        else next.delete(p);
      }
      return next;
    });
  }, []);

  const onSelectFile = useCallback(
    (path: string, fileRepo?: string) => {
      setSelectedPath(path);
      setSelectedRepo(fileRepo || repository);
      setFocusedEntity(null);
      setExpanded((prev) => {
        const next = new Set(prev);
        for (const p of dirPrefixesForPath(path)) next.add(p);
        return next;
      });
    },
    [repository],
  );

  useEffect(() => {
    if (!treeFilter.trim() || !filteredTree) return;
    const toOpen = new Set<string>();
    function walk(n: FileTreeNode) {
      if (n.type === "directory" && n.children?.length) {
        toOpen.add(n.path);
        for (const c of n.children) walk(c);
      }
    }
    walk(filteredTree);
    setExpanded(toOpen);
  }, [treeFilter, filteredTree]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="flex items-center gap-2 text-lg font-semibold text-gray-900 dark:text-gray-100">
          <FolderOpen size={20} className="text-amber-600 dark:text-amber-400" />
          {t.fileExplorer.title}
        </h1>
      </div>

      <div className="flex min-h-[calc(100vh-10rem)] flex-col gap-4 lg:flex-row">
        <aside className="flex min-h-0 w-full shrink-0 flex-col overflow-hidden rounded-xl border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-900 lg:w-80">
          <div className="border-b border-gray-200 p-3 dark:border-gray-700">
            <label className="mb-1 block text-xs font-medium text-gray-500 dark:text-gray-400">
              {t.repos.repository}
            </label>
            <select
              value={repository}
              onChange={(e) => {
                setRepository(e.target.value);
                setSelectedPath(null);
                setSelectedRepo("");
                setExpanded(new Set());
              }}
              className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-700 outline-none ring-sky-300 focus:ring-2 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200"
            >
              <option value="">{t.documents.allRepos}</option>
              {repos.map((r) => (
                <option key={r.repository} value={r.repository}>
                  {r.repository}
                </option>
              ))}
            </select>
          </div>
          <div className="border-b border-gray-200 px-3 py-2 dark:border-gray-700">
            <div className="relative">
              <Search
                size={14}
                className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-500 dark:text-gray-400"
              />
              <input
                type="search"
                value={treeFilter}
                onChange={(e) => setTreeFilter(e.target.value)}
                placeholder={t.fileExplorer.searchPlaceholder}
                className="w-full rounded-lg border border-gray-300 bg-white py-1.5 pl-8 pr-3 text-sm text-gray-700 outline-none ring-sky-300 placeholder:text-gray-400 focus:ring-2 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200"
              />
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-2">
            {treeLoading ? (
              <div className="flex items-center gap-2 p-4 text-sm text-gray-500 dark:text-gray-400">
                <Loader2 className="animate-spin" size={18} />
                {t.fileExplorer.loadingTree}
              </div>
            ) : treeError ? (
              <p className="p-3 text-sm text-red-600 dark:text-red-400">{getErrorMessage(treeError, t.common.unexpectedError)}</p>
            ) : filteredTree ? (
              <TreeRows
                node={filteredTree}
                depth={0}
                expanded={expanded}
                onToggle={toggle}
                selectedPath={selectedPath}
                onSelectFile={onSelectFile}
                filterActive={!!treeFilter.trim()}
                isRoot
              />
            ) : (
              <p className="p-3 text-sm text-gray-500 dark:text-gray-400">{t.search.noResults}</p>
            )}
          </div>
        </aside>

        <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-xl border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-900">
          {!selectedPath ? (
            <div className="flex flex-1 flex-col items-center justify-center gap-3 p-8 text-center text-gray-500 dark:text-gray-400">
              <FileCode size={40} className="opacity-60" />
              <p className="text-sm">{t.fileExplorer.selectFile}</p>
            </div>
          ) : contentLoading ? (
            <div className="flex flex-1 items-center justify-center gap-2 text-gray-500 dark:text-gray-400">
              <Loader2 size={20} className="animate-spin" />
              <span className="text-sm">{t.fileExplorer.loadingContent}</span>
            </div>
          ) : contentError ? (
            <div className="p-6 text-sm text-red-600 dark:text-red-400">
              {getErrorMessage(contentError, t.common.unexpectedError)}
            </div>
          ) : content ? (
            <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
              <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden border-b border-gray-200 lg:border-b-0 lg:border-r lg:border-gray-200 dark:border-gray-700">
                <div className="shrink-0 border-b border-gray-200 px-4 py-3 dark:border-gray-700">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="break-all font-mono text-xs text-gray-700 dark:text-gray-300">{content.file_path}</p>
                    <span className="text-xs text-gray-500 dark:text-gray-400">
                      {t.fileExplorer.linesCount.replace("{count}", String(content.total_lines))}
                    </span>
                  </div>
                  {content.truncated && (
                    <p className="mt-2 text-xs text-amber-700 dark:text-amber-400">{t.fileExplorer.truncatedWarning}</p>
                  )}
                </div>
                <div className="min-h-0 flex-1 overflow-auto bg-gray-50 dark:bg-black/40">
                  <Highlight
                    theme={prismTheme}
                    code={content.content.replace(/\n$/, "")}
                    language={detectLanguage(content.file_path)}
                  >
                    {({ tokens, getLineProps, getTokenProps }) => (
                      <pre className="m-0 min-w-max p-3 text-xs leading-relaxed">
                        {tokens.map((line, i) => {
                          const lineNo = i + linesStart;
                          const ent = entityByLine.get(lineNo);
                          const lineProps = getLineProps({ line });
                          return (
                            <div
                              key={i}
                              {...lineProps}
                              className={`${lineProps.className ?? ""} table-row`.trim()}
                            >
                              <span className="table-cell w-10 select-none border-r border-gray-200/80 pr-2 text-right font-mono text-[11px] text-gray-400 dark:border-gray-700">
                                {lineNo}
                              </span>
                              <span className="table-cell w-24 max-w-24 shrink-0 border-r border-gray-200/80 px-1 align-top dark:border-gray-700">
                                {ent ? (
                                  <button
                                    type="button"
                                    onClick={() => setFocusedEntity(ent)}
                                    title={ent.name}
                                    className="inline-flex max-w-full rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-medium text-emerald-900 hover:bg-emerald-200 dark:bg-emerald-900/50 dark:text-emerald-100 dark:hover:bg-emerald-800"
                                  >
                                    <span className="truncate">{ent.type === "Function" ? "fn" : "cls"}</span>
                                  </button>
                                ) : null}
                              </span>
                              <span className="table-cell px-2">
                                {line.map((token, key) => (
                                  <span key={key} {...getTokenProps({ token })} />
                                ))}
                              </span>
                            </div>
                          );
                        })}
                      </pre>
                    )}
                  </Highlight>
                </div>
              </div>

              <aside className="flex w-full shrink-0 flex-col gap-3 overflow-y-auto border-gray-200 p-4 dark:border-gray-700 lg:w-72 lg:border-l">
                <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">{t.fileExplorer.entities}</h3>
                {entitiesLoading ? (
                  <Loader2 className="animate-spin text-gray-400" size={18} />
                ) : !entitiesData?.entities.length ? (
                  <p className="text-xs text-gray-500 dark:text-gray-400">{t.fileExplorer.noEntities}</p>
                ) : (
                  <ul className="space-y-2">
                    {entitiesData.entities.map((ent) => {
                      const isFocused = focusedEntity?.name === ent.name && focusedEntity?.start_line === ent.start_line;
                      return (
                        <li key={`${ent.name}:${ent.start_line}:${ent.type}`}>
                          <button
                            type="button"
                            onClick={() => setFocusedEntity(ent)}
                            className={`w-full rounded-lg border px-3 py-2 text-left text-sm transition-colors dark:border-gray-600 ${
                              isFocused
                                ? "border-sky-500 bg-sky-50 dark:border-sky-500 dark:bg-sky-950/40"
                                : "border-gray-200 bg-white hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-800 dark:hover:bg-gray-700/40"
                            }`}
                          >
                            <span className="font-medium text-gray-900 dark:text-gray-100">{ent.name}</span>
                            <span className="ml-2 text-xs text-gray-500 dark:text-gray-400">
                              L{ent.start_line}
                              {ent.end_line != null ? `–${ent.end_line}` : ""}
                            </span>
                            <div className="truncate text-xs text-gray-500 dark:text-gray-500">{ent.type}</div>
                          </button>
                          {isFocused && (
                            <div className="mt-1 rounded-lg border border-gray-200 bg-gray-50 p-3 text-xs dark:border-gray-700 dark:bg-gray-800/80">
                              {ent.signature ? (
                                <pre className="mb-2 max-h-24 overflow-auto whitespace-pre-wrap break-all font-mono text-[11px] text-gray-700 dark:text-gray-300">
                                  {ent.signature}
                                </pre>
                              ) : null}
                              <div className="flex flex-col gap-1.5">
                                <Link
                                  to={`/explorer?q=${encodeURIComponent(ent.name)}`}
                                  className="inline-flex items-center justify-center gap-2 rounded-lg bg-gray-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-gray-800 dark:bg-gray-100 dark:text-gray-900 dark:hover:bg-white"
                                >
                                  <Network size={14} />
                                  {t.fileExplorer.viewInGraph}
                                </Link>
                                <Link
                                  to={`/search?q=${encodeURIComponent(ent.name)}`}
                                  className="inline-flex items-center justify-center gap-2 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-800 hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100 dark:hover:bg-gray-800"
                                >
                                  <Search size={14} />
                                  {t.fileExplorer.searchRelated}
                                </Link>
                                {repoForContent ? (
                                  <Link
                                    to="/wiki"
                                    className="inline-flex items-center justify-center gap-2 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-800 hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100 dark:hover:bg-gray-800"
                                  >
                                    <BookOpen size={14} />
                                    {t.fileExplorer.viewWiki}
                                  </Link>
                                ) : null}
                              </div>
                            </div>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                )}
              </aside>
            </div>
          ) : (
            <div className="flex flex-1 flex-col items-center justify-center gap-2 p-8 text-center text-sm text-gray-500 dark:text-gray-400">
              <p>{repoForContent ? t.fileExplorer.contentUnavailable : t.fileExplorer.noRepository}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
