import {
  memo,
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent,
} from "react";
import { ChevronRight, ChevronDown, Check, FileText, FolderOpen, Pencil, Trash2, X } from "lucide-react";
import { ConfirmDialog } from "../ConfirmDialog";
import { useI18n } from "../../i18n/context";
import type { TopicTreeNode } from "../../hooks/useWikiDomainTree";

export interface DomainContextMenuPayload {
  uid: string;
  title: string;
  path: string;
  description?: string;
  depth: number;
}

interface Props {
  tree: TopicTreeNode[];
  selectedPath: string | null;
  onSelect: (path: string) => void;
  onRenameDomain?: (uid: string, newDisplayName: string) => void;
  onDeleteDomain?: (uid: string) => void;
  onDomainContextMenu?: (event: MouseEvent, payload: DomainContextMenuPayload) => void;
}

function initialExpanded(tree: TopicTreeNode[]): Set<string> {
  const out = new Set<string>();
  for (const n of tree) {
    if (n.children.length > 0) out.add(n.path);
  }
  return out;
}

function collectVisibleItems(
  nodes: TopicTreeNode[],
  expanded: Set<string>,
  out: TopicTreeNode[] = [],
): TopicTreeNode[] {
  for (const n of nodes) {
    out.push(n);
    if (n.children.length > 0 && expanded.has(n.path)) {
      collectVisibleItems(n.children, expanded, out);
    }
  }
  return out;
}

function findParentPath(
  nodes: TopicTreeNode[],
  path: string,
  parentPath: string | null = null,
): string | null {
  for (const n of nodes) {
    if (n.path === path) return parentPath;
    if (n.children.length) {
      const found = findParentPath(n.children, path, n.path);
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
  selectedPath,
  onSelect,
  onRenameDomain,
  onDeleteDomain,
  onDomainContextMenu,
  topicLabels,
  focusedPath,
  onFocusItem,
  onTreeKeyDown,
}: {
  nodes: TopicTreeNode[];
  depth: number;
  expanded: Set<string>;
  toggle: (path: string) => void;
  selectedPath: string | null;
  onSelect: (path: string) => void;
  onRenameDomain?: (uid: string, newDisplayName: string) => void;
  onDeleteDomain?: (uid: string) => void;
  onDomainContextMenu?: (event: MouseEvent, payload: DomainContextMenuPayload) => void;
  topicLabels: {
    expanded: string;
    collapsed: string;
    pending_review: string;
    edit: string;
    delete: string;
    delete_confirm: string;
    rename_input: string;
  };
  focusedPath: string | null;
  onFocusItem: (path: string) => void;
  onTreeKeyDown: (event: KeyboardEvent<HTMLUListElement>) => void;
}) {
  return (
    <ul
      role={depth === 0 ? "tree" : "group"}
      onKeyDown={depth === 0 ? onTreeKeyDown : undefined}
      className={depth === 0 ? "space-y-0.5" : "mt-0.5 space-y-0.5"}
    >
      {nodes.map((node) => (
        <TreeNodeRow
          key={node.path}
          node={node}
          depth={depth}
          expanded={expanded}
          toggle={toggle}
          selectedPath={selectedPath}
          onSelect={onSelect}
          onRenameDomain={onRenameDomain}
          onDeleteDomain={onDeleteDomain}
          onDomainContextMenu={onDomainContextMenu}
          topicLabels={topicLabels}
          focusedPath={focusedPath}
          onFocusItem={onFocusItem}
          onTreeKeyDown={onTreeKeyDown}
        />
      ))}
    </ul>
  );
});

function TreeNodeRow({
  node,
  depth,
  expanded,
  toggle,
  selectedPath,
  onSelect,
  onRenameDomain,
  onDeleteDomain,
  onDomainContextMenu,
  topicLabels,
  focusedPath,
  onFocusItem,
  onTreeKeyDown,
}: {
  node: TopicTreeNode;
  depth: number;
  expanded: Set<string>;
  toggle: (path: string) => void;
  selectedPath: string | null;
  onSelect: (path: string) => void;
  onRenameDomain?: (uid: string, newDisplayName: string) => void;
  onDeleteDomain?: (uid: string) => void;
  onDomainContextMenu?: (event: MouseEvent, payload: DomainContextMenuPayload) => void;
  topicLabels: {
    expanded: string;
    collapsed: string;
    pending_review: string;
    edit: string;
    delete: string;
    delete_confirm: string;
    rename_input: string;
  };
  focusedPath: string | null;
  onFocusItem: (path: string) => void;
  onTreeKeyDown: (event: KeyboardEvent<HTMLUListElement>) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const hasChildren = node.children.length > 0;
  const isOpen = expanded.has(node.path);
  const isSelected = selectedPath === node.path;
  const isDomain = node.page_type === "domain_overview" || node.label === "WikiSection";
  const domainUid = node.uid?.trim() ?? "";
  const canEdit = isDomain && !!domainUid && !!onRenameDomain;
  const isFocused = focusedPath === node.path;

  useEffect(() => {
    if (editing && inputRef.current) inputRef.current.focus();
  }, [editing]);

  const handleClick = useCallback(() => {
    if (hasChildren) toggle(node.path);
    onSelect(node.path);
  }, [hasChildren, node.path, onSelect, toggle]);

  const startEdit = useCallback(
    (e: MouseEvent) => {
      e.stopPropagation();
      setEditValue(node.name);
      setEditing(true);
    },
    [node.name],
  );

  const cancelEdit = useCallback(() => {
    setEditing(false);
    setEditValue("");
  }, []);

  const saveEdit = useCallback(() => {
    const v = editValue.trim();
    if (v && v !== node.name && domainUid && onRenameDomain) {
      onRenameDomain(domainUid, v);
    }
    setEditing(false);
  }, [editValue, node.name, domainUid, onRenameDomain]);

  const handleDelete = useCallback(
    (e: MouseEvent) => {
      e.stopPropagation();
      if (domainUid && onDeleteDomain) {
        setConfirmDelete(true);
      }
    },
    [domainUid, onDeleteDomain],
  );

  const confirmDeleteDomain = useCallback(() => {
    if (domainUid && onDeleteDomain) {
      onDeleteDomain(domainUid);
    }
    setConfirmDelete(false);
  }, [domainUid, onDeleteDomain]);

  const handleContextMenu = useCallback(
    (e: MouseEvent) => {
      if (!isDomain || !domainUid || !onDomainContextMenu) return;
      e.preventDefault();
      e.stopPropagation();
      onDomainContextMenu(e, {
        uid: domainUid,
        title: node.name,
        path: node.path,
        description: node.description,
        depth,
      });
    },
    [isDomain, domainUid, onDomainContextMenu, node.name, node.path, node.description, depth],
  );

  if (editing) {
    return (
      <li className="list-none">
        <div
          className="flex items-center gap-1 rounded-md bg-sky-50 px-1 py-1 dark:bg-sky-950/40"
          style={{ paddingLeft: `${depth * 16 + 8}px` }}
        >
          <input
            ref={inputRef}
            type="text"
            value={editValue}
            aria-label={topicLabels.rename_input}
            onChange={(e) => setEditValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") saveEdit();
              if (e.key === "Escape") cancelEdit();
            }}
            className="min-w-0 flex-1 rounded border border-sky-300 bg-white px-1.5 py-0.5 text-xs text-gray-900 focus:outline-none focus:ring-1 focus:ring-sky-500 dark:border-sky-700 dark:bg-gray-900 dark:text-gray-100"
          />
          <button type="button" onClick={saveEdit} className="rounded p-0.5 text-green-600 hover:bg-green-100 dark:text-green-400 dark:hover:bg-green-900/40">
            <Check size={12} />
          </button>
          <button type="button" onClick={cancelEdit} className="rounded p-0.5 text-gray-500 hover:bg-gray-200 dark:text-gray-400 dark:hover:bg-gray-700">
            <X size={12} />
          </button>
        </div>
      </li>
    );
  }

  return (
    <li
      role="treeitem"
      aria-expanded={hasChildren ? isOpen : undefined}
      tabIndex={isFocused ? 0 : -1}
      data-tree-path={node.path}
      onFocus={() => onFocusItem(node.path)}
      className="list-none rounded-md outline-none focus-visible:ring-2 focus-visible:ring-sky-500/70"
    >
      <div className="group relative" onContextMenu={handleContextMenu}>
        <button
          type="button"
          tabIndex={-1}
          onClick={handleClick}
          aria-label={
            hasChildren ? `${node.name}，${isOpen ? topicLabels.expanded : topicLabels.collapsed}` : node.name
          }
          className={`flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-left transition-colors ${
            isSelected
              ? "bg-sky-50 text-sky-700 dark:bg-sky-950/40 dark:text-sky-400"
              : "text-gray-700 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800"
          }`}
          style={{ paddingLeft: `${depth * 16 + 8}px` }}
        >
          {hasChildren ? (
            isOpen ? (
              <ChevronDown size={14} />
            ) : (
              <ChevronRight size={14} />
            )
          ) : (
            <span className="w-3.5" />
          )}
          {isDomain ? <FolderOpen size={14} /> : <FileText size={14} />}
          <span className="truncate">{node.name}</span>
          {node.review_status === "pending_review" && (
            <span className="ml-auto rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] text-amber-700 dark:bg-amber-900/40 dark:text-amber-400">
              {topicLabels.pending_review}
            </span>
          )}
        </button>
        {canEdit && (
          <div className="absolute right-1 top-1/2 flex -translate-y-1/2 gap-0.5 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
            <button
              type="button"
              onClick={startEdit}
              aria-label={topicLabels.edit}
              className="rounded p-1 text-gray-400 hover:bg-gray-200 hover:text-gray-700 dark:text-gray-500 dark:hover:bg-gray-700 dark:hover:text-gray-200"
            >
              <Pencil size={11} />
            </button>
            {onDeleteDomain && (
              <button
                type="button"
                onClick={handleDelete}
                aria-label={topicLabels.delete}
                className="rounded p-1 text-gray-400 hover:bg-red-100 hover:text-red-600 dark:text-gray-500 dark:hover:bg-red-900/40 dark:hover:text-red-400"
              >
                <Trash2 size={11} />
              </button>
            )}
          </div>
        )}
      </div>
      {confirmDelete && (
        <ConfirmDialog
          title={topicLabels.delete}
          message={topicLabels.delete_confirm.replace("{name}", node.name)}
          confirmLabel={topicLabels.delete}
          variant="danger"
          onConfirm={confirmDeleteDomain}
          onCancel={() => setConfirmDelete(false)}
        />
      )}
      {hasChildren && isOpen && (
        <TreeBranch
          nodes={node.children}
          depth={depth + 1}
          expanded={expanded}
          toggle={toggle}
          selectedPath={selectedPath}
          onSelect={onSelect}
          onRenameDomain={onRenameDomain}
          onDeleteDomain={onDeleteDomain}
          onDomainContextMenu={onDomainContextMenu}
          topicLabels={topicLabels}
          focusedPath={focusedPath}
          onFocusItem={onFocusItem}
          onTreeKeyDown={onTreeKeyDown}
        />
      )}
    </li>
  );
}

export default function WikiTopicTreeNav({
  tree,
  selectedPath,
  onSelect,
  onRenameDomain,
  onDeleteDomain,
  onDomainContextMenu,
}: Props) {
  const { t } = useI18n();
  const tt = t.wiki.topic_tree;
  const treeRef = useRef<HTMLDivElement>(null);

  const [expanded, setExpanded] = useState(() => initialExpanded(tree));
  const [focusedPath, setFocusedPath] = useState<string | null>(null);

  useEffect(() => {
    setExpanded(initialExpanded(tree));
  }, [tree]);

  useEffect(() => {
    if (!tree.length) {
      setFocusedPath(null);
      return;
    }
    const visible = collectVisibleItems(tree, expanded);
    if (!visible.length) return;
    setFocusedPath((prev) => (prev && visible.some((n) => n.path === prev) ? prev : visible[0].path));
  }, [tree, expanded]);

  useEffect(() => {
    if (!focusedPath) return;
    const el = treeRef.current?.querySelector<HTMLElement>(`[data-tree-path="${CSS.escape(focusedPath)}"]`);
    if (el && document.activeElement !== el) {
      el.focus();
    }
  }, [focusedPath]);

  const toggle = useCallback((path: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }, []);

  const selectFocusedItem = useCallback(
    (node: TopicTreeNode) => {
      onSelect(node.path);
    },
    [onSelect],
  );

  const handleTreeKeyDown = useCallback(
    (event: KeyboardEvent<HTMLUListElement>) => {
      if (!focusedPath || !tree.length) return;

      const visible = collectVisibleItems(tree, expanded);
      const idx = visible.findIndex((n) => n.path === focusedPath);
      if (idx < 0) return;

      const current = visible[idx];
      const hasKids = current.children.length > 0;
      const isOpen = expanded.has(current.path);

      switch (event.key) {
        case "ArrowDown":
          event.preventDefault();
          if (idx < visible.length - 1) setFocusedPath(visible[idx + 1].path);
          break;
        case "ArrowUp":
          event.preventDefault();
          if (idx > 0) setFocusedPath(visible[idx - 1].path);
          break;
        case "ArrowRight":
          event.preventDefault();
          if (hasKids && !isOpen) {
            setExpanded((prev) => new Set(prev).add(current.path));
          } else if (hasKids && isOpen && current.children.length) {
            setFocusedPath(current.children[0].path);
          }
          break;
        case "ArrowLeft":
          event.preventDefault();
          if (hasKids && isOpen) {
            setExpanded((prev) => {
              const next = new Set(prev);
              next.delete(current.path);
              return next;
            });
          } else {
            const parent = findParentPath(tree, focusedPath);
            if (parent) setFocusedPath(parent);
          }
          break;
        case "Home":
          event.preventDefault();
          if (visible.length) setFocusedPath(visible[0].path);
          break;
        case "End":
          event.preventDefault();
          if (visible.length) setFocusedPath(visible[visible.length - 1].path);
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
    [expanded, focusedPath, tree, selectFocusedItem],
  );

  if (tree.length === 0) {
    return (
      <div className="flex items-center justify-center p-4 text-sm text-gray-400 dark:text-gray-500">
        {tt.no_content}
      </div>
    );
  }

  return (
    <nav ref={treeRef} className="text-sm" aria-label={tt.nav_label}>
      <TreeBranch
        nodes={tree}
        depth={0}
        expanded={expanded}
        toggle={toggle}
        selectedPath={selectedPath}
        onSelect={onSelect}
        onRenameDomain={onRenameDomain}
        onDeleteDomain={onDeleteDomain}
        onDomainContextMenu={onDomainContextMenu}
        topicLabels={tt}
        focusedPath={focusedPath}
        onFocusItem={setFocusedPath}
        onTreeKeyDown={handleTreeKeyDown}
      />
    </nav>
  );
}
