import { memo, useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { Link } from "react-router-dom";
import {
  ChevronDown,
  ChevronRight,
  FileText,
  Folder,
  Layers,
  Loader2,
  UnfoldVertical,
} from "lucide-react";
import type { WikiTreeNode } from "../../hooks/wikiTypes";
import { useWikiTree } from "../../hooks/useWikiTree";
import { useI18n } from "../../i18n/context";
import { wikiHref } from "./wikiRouteHelpers";
import { getErrorMessage } from "../../utils/errorUtils";
import { WikiTierSelector } from "./WikiTierSelector";

type ViewType = "business_domain" | "code_structure";

const EMPTY_TREE: WikiTreeNode[] = [];

type WikiTier = "standard" | "essential" | "comprehensive" | null;

type Props = {
  businessId: string;
  viewType: ViewType;
  activePath: string;
  onViewChange: (view: ViewType) => void;
  wikiTier: WikiTier;
  onWikiTierChange: (tier: string | null) => void;
};

function collectAncestorKeys(
  nodes: WikiTreeNode[],
  targetPath: string,
  trail: string[] = [],
): string[] | null {
  for (const n of nodes) {
    const key = n.uid;
    const nextTrail = [...trail, key];
    if (n.path === targetPath) return nextTrail;
    if (n.children?.length) {
      const found = collectAncestorKeys(n.children, targetPath, nextTrail);
      if (found) return found;
    }
  }
  return null;
}

function collectAllKeys(nodes: WikiTreeNode[]): string[] {
  const out: string[] = [];
  const walk = (list: WikiTreeNode[]) => {
    for (const n of list) {
      if (n.children?.length) {
        out.push(n.uid);
        walk(n.children);
      }
    }
  };
  walk(nodes);
  return out;
}

function collectVisibleItems(nodes: WikiTreeNode[], expanded: Set<string>, out: WikiTreeNode[] = []): WikiTreeNode[] {
  for (const n of nodes) {
    out.push(n);
    if (n.children?.length && expanded.has(n.uid)) {
      collectVisibleItems(n.children, expanded, out);
    }
  }
  return out;
}

function findParentUid(nodes: WikiTreeNode[], uid: string, parentUid: string | null = null): string | null {
  for (const n of nodes) {
    if (n.uid === uid) return parentUid;
    if (n.children?.length) {
      const found = findParentUid(n.children, uid, n.uid);
      if (found !== null) return found;
    }
  }
  return null;
}

const TreeBranch = memo(function TreeBranch({
  nodes,
  depth,
  expanded,
  toggle,
  activePath,
  linkParams,
  focusedUid,
  onFocusItem,
  onTreeKeyDown,
}: {
  nodes: WikiTreeNode[];
  depth: number;
  expanded: Set<string>;
  toggle: (uid: string) => void;
  activePath: string;
  linkParams: Record<string, string>;
  focusedUid: string | null;
  onFocusItem: (uid: string) => void;
  onTreeKeyDown: (event: KeyboardEvent<HTMLUListElement>) => void;
}) {
  const { t } = useI18n();
  return (
    <ul
      role={depth === 0 ? "tree" : "group"}
      onKeyDown={depth === 0 ? onTreeKeyDown : undefined}
      className={
        depth === 0
          ? "space-y-0.5"
          : "mt-0.5 space-y-0.5 border-l border-gray-100 pl-2 dark:border-gray-700"
      }
    >
      {nodes.map((node) => {
        const hasKids = Boolean(node.children?.length);
        const isOpen = expanded.has(node.uid);
        const isActive = Boolean(activePath && node.path === activePath);
        const pageLink = node.path ? wikiHref(node.path, linkParams) : null;
        const isFocused = focusedUid === node.uid;

        return (
          <li
            key={node.uid}
            role="treeitem"
            aria-expanded={hasKids ? isOpen : undefined}
            tabIndex={isFocused ? 0 : -1}
            data-tree-uid={node.uid}
            onFocus={() => onFocusItem(node.uid)}
            className="rounded-md outline-none focus-visible:ring-2 focus-visible:ring-sky-500/70"
          >
            <div className="flex items-center gap-0.5">
              {hasKids ? (
                <button
                  type="button"
                  onClick={() => toggle(node.uid)}
                  aria-label={isOpen ? t.wiki.treeNavCollapse : t.wiki.treeNavExpand}
                  className="rounded p-0.5 text-gray-400 hover:bg-gray-100 hover:text-gray-700 dark:text-gray-500 dark:hover:bg-gray-800 dark:hover:text-gray-200"
                >
                  {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                </button>
              ) : (
                <span className="w-[22px]" />
              )}
              {pageLink && !hasKids ? (
                <Link
                  to={pageLink}
                  className={`flex min-w-0 flex-1 items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors ${
                    isActive
                      ? "bg-sky-50 font-medium text-sky-900 dark:bg-sky-950/60 dark:text-sky-100"
                      : "text-gray-700 hover:bg-gray-50 dark:text-gray-300 dark:hover:bg-gray-800/80"
                  }`}
                >
                  <FileText size={14} className="shrink-0 opacity-70" />
                  <span className="truncate">{node.title || node.label}</span>
                </Link>
              ) : hasKids ? (
                <div className="flex min-w-0 flex-1 items-center gap-2 px-2 py-1.5 text-sm">
                  <Folder size={14} className="shrink-0 text-amber-600/90 dark:text-amber-400/90" />
                  {pageLink ? (
                    <Link
                      to={pageLink}
                      className={`min-w-0 truncate font-medium hover:underline ${
                        isActive
                          ? "text-sky-800 dark:text-sky-200"
                          : "text-gray-800 dark:text-gray-200"
                      }`}
                    >
                      {node.title || node.label}
                    </Link>
                  ) : (
                    <span className="truncate text-gray-600 dark:text-gray-400">
                      {node.title || node.label}
                    </span>
                  )}
                </div>
              ) : pageLink ? (
                <Link
                  to={pageLink}
                  className={`flex min-w-0 flex-1 items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors ${
                    isActive
                      ? "bg-sky-50 font-medium text-sky-900 dark:bg-sky-950/60 dark:text-sky-100"
                      : "text-gray-700 hover:bg-gray-50 dark:text-gray-300 dark:hover:bg-gray-800/80"
                  }`}
                >
                  <FileText size={14} className="shrink-0 opacity-70" />
                  <span className="truncate">{node.title || node.label}</span>
                </Link>
              ) : (
                <span className="flex min-w-0 flex-1 items-center gap-2 px-2 py-1.5 text-sm text-gray-500 dark:text-gray-400">
                  <FileText size={14} className="shrink-0 opacity-50" />
                  <span className="truncate">{node.title || node.label}</span>
                </span>
              )}
            </div>
            {hasKids && isOpen && node.children && (
              <TreeBranch
                nodes={node.children}
                depth={depth + 1}
                expanded={expanded}
                toggle={toggle}
                activePath={activePath}
                linkParams={linkParams}
                focusedUid={focusedUid}
                onFocusItem={onFocusItem}
                onTreeKeyDown={onTreeKeyDown}
              />
            )}
          </li>
        );
      })}
    </ul>
  );
});

export default function WikiTreeNav({
  businessId,
  viewType,
  activePath,
  onViewChange,
  wikiTier,
  onWikiTierChange,
}: Props) {
  const { t } = useI18n();
  const treeQuery = useWikiTree(businessId, viewType, wikiTier);
  const treeRef = useRef<HTMLDivElement>(null);
  const nodes = useMemo(
    () => treeQuery.data?.tree ?? EMPTY_TREE,
    [treeQuery.data?.tree],
  );

  const linkParams = useMemo(
    () =>
      ({
        business_id: businessId,
        view: viewType,
        ...(wikiTier ? { wiki_tier: wikiTier } : {}),
      }) as Record<string, string>,
    [businessId, viewType, wikiTier],
  );

  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const [focusedUid, setFocusedUid] = useState<string | null>(null);

  useEffect(() => {
    if (!activePath || !nodes.length) return;
    const chain = collectAncestorKeys(nodes, activePath);
    if (!chain) return;
    setExpanded((prev) => {
      const next = new Set(prev);
      for (const uid of chain) {
        const n = findNodeByUid(nodes, uid);
        if (n?.children?.length) next.add(uid);
      }
      return next;
    });
  }, [activePath, nodes]);

  useEffect(() => {
    if (!nodes.length) {
      setFocusedUid(null);
      return;
    }
    const visible = collectVisibleItems(nodes, expanded);
    if (!visible.length) return;
    setFocusedUid((prev) => (prev && visible.some((n) => n.uid === prev) ? prev : visible[0].uid));
  }, [nodes, expanded]);

  useEffect(() => {
    if (!focusedUid) return;
    const el = treeRef.current?.querySelector<HTMLElement>(`[data-tree-uid="${focusedUid}"]`);
    if (el && document.activeElement !== el) {
      el.focus();
    }
  }, [focusedUid]);

  const toggle = useCallback((uid: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(uid)) next.delete(uid);
      else next.add(uid);
      return next;
    });
  }, []);

  const expandAll = useCallback(() => {
    setExpanded(new Set(collectAllKeys(nodes)));
  }, [nodes]);

  const selectFocusedItem = useCallback(
    (node: WikiTreeNode) => {
      const hasKids = Boolean(node.children?.length);
      const pageLink = node.path ? wikiHref(node.path, linkParams) : null;
      if (pageLink) {
        const link = treeRef.current?.querySelector<HTMLAnchorElement>(
          `[data-tree-uid="${node.uid}"] a[href]`,
        );
        link?.click();
      } else if (hasKids) {
        toggle(node.uid);
      }
    },
    [linkParams, toggle],
  );

  const handleTreeKeyDown = useCallback(
    (event: KeyboardEvent<HTMLUListElement>) => {
      if (!focusedUid || !nodes.length) return;

      const visible = collectVisibleItems(nodes, expanded);
      const idx = visible.findIndex((n) => n.uid === focusedUid);
      if (idx < 0) return;

      const current = visible[idx];
      const hasKids = Boolean(current.children?.length);
      const isOpen = expanded.has(current.uid);

      switch (event.key) {
        case "ArrowDown":
          event.preventDefault();
          if (idx < visible.length - 1) setFocusedUid(visible[idx + 1].uid);
          break;
        case "ArrowUp":
          event.preventDefault();
          if (idx > 0) setFocusedUid(visible[idx - 1].uid);
          break;
        case "ArrowRight":
          event.preventDefault();
          if (hasKids && !isOpen) {
            setExpanded((prev) => new Set(prev).add(current.uid));
          } else if (hasKids && isOpen && current.children?.length) {
            setFocusedUid(current.children[0].uid);
          }
          break;
        case "ArrowLeft":
          event.preventDefault();
          if (hasKids && isOpen) {
            setExpanded((prev) => {
              const next = new Set(prev);
              next.delete(current.uid);
              return next;
            });
          } else {
            const parent = findParentUid(nodes, focusedUid);
            if (parent) setFocusedUid(parent);
          }
          break;
        case "Home":
          event.preventDefault();
          if (visible.length) setFocusedUid(visible[0].uid);
          break;
        case "End":
          event.preventDefault();
          if (visible.length) setFocusedUid(visible[visible.length - 1].uid);
          break;
        case "Enter":
        case " ":
          event.preventDefault();
          selectFocusedItem(current);
          break;
        default:
          break;
      }
    },
    [expanded, focusedUid, nodes, selectFocusedItem],
  );

  return (
    <aside className="flex w-full shrink-0 flex-col rounded-xl border border-gray-200 bg-white shadow-sm dark:border-gray-700 dark:bg-gray-900">
      <div
        className="flex border-b border-gray-100 dark:border-gray-700"
        role="tablist"
        aria-label={t.wiki.businessView + " / " + t.wiki.codeView}
      >
        <button
          type="button"
          role="tab"
          aria-selected={viewType === "business_domain"}
          onClick={() => onViewChange("business_domain")}
          className={`flex-1 px-3 py-2.5 text-xs font-medium transition-colors ${
            viewType === "business_domain"
              ? "border-b-2 border-sky-600 text-sky-800 dark:border-sky-400 dark:text-sky-200"
              : "text-gray-500 hover:text-gray-800 dark:text-gray-400 dark:hover:text-gray-200"
          }`}
        >
          <span className="flex items-center justify-center gap-1.5">
            <Layers size={14} aria-hidden />
            {t.wiki.businessView}
          </span>
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={viewType === "code_structure"}
          onClick={() => onViewChange("code_structure")}
          className={`flex-1 px-3 py-2.5 text-xs font-medium transition-colors ${
            viewType === "code_structure"
              ? "border-b-2 border-sky-600 text-sky-800 dark:border-sky-400 dark:text-sky-200"
              : "text-gray-500 hover:text-gray-800 dark:text-gray-400 dark:hover:text-gray-200"
          }`}
        >
          <span className="flex items-center justify-center gap-1.5">
            <Folder size={14} aria-hidden />
            {t.wiki.codeView}
          </span>
        </button>
      </div>

      <div className="flex items-center justify-between gap-2 border-b border-gray-50 px-2 py-1.5 dark:border-gray-800">
        <WikiTierSelector
          value={wikiTier === "standard" || wikiTier === "essential" ? wikiTier : null}
          onChange={onWikiTierChange}
        />
        <button
          type="button"
          onClick={expandAll}
          disabled={!nodes.length}
          className="inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium text-gray-600 hover:bg-gray-100 disabled:opacity-40 dark:text-gray-400 dark:hover:bg-gray-800"
        >
          <UnfoldVertical size={12} aria-hidden />
          {t.documents.expandAll}
        </button>
      </div>

      <div ref={treeRef} className="max-h-[min(70vh,560px)] overflow-y-auto p-2">
        {treeQuery.isLoading && (
          <p className="flex items-center gap-2 px-2 py-4 text-sm text-gray-500 dark:text-gray-400">
            <Loader2 className="size-4 animate-spin" aria-hidden />
            {t.wiki.loadingPages}
          </p>
        )}
        {treeQuery.isError && (
          <p className="px-2 py-3 text-sm text-red-600 dark:text-red-400">
            {getErrorMessage(treeQuery.error, t.common.unexpectedError)}
          </p>
        )}
        {!treeQuery.isLoading && !treeQuery.isError && nodes.length === 0 && (
          <p className="px-2 py-4 text-sm text-gray-500 dark:text-gray-400">{t.wiki.noPagesFound}</p>
        )}
        {nodes.length > 0 && (
          <TreeBranch
            nodes={nodes}
            depth={0}
            expanded={expanded}
            toggle={toggle}
            activePath={activePath}
            linkParams={linkParams}
            focusedUid={focusedUid}
            onFocusItem={setFocusedUid}
            onTreeKeyDown={handleTreeKeyDown}
          />
        )}
      </div>
    </aside>
  );
}

function findNodeByUid(list: WikiTreeNode[], uid: string): WikiTreeNode | null {
  for (const n of list) {
    if (n.uid === uid) return n;
    if (n.children?.length) {
      const f = findNodeByUid(n.children, uid);
      if (f) return f;
    }
  }
  return null;
}
