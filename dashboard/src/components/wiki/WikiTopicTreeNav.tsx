import { useState, useCallback, useRef, useEffect, type MouseEvent } from "react";
import { ChevronRight, ChevronDown, Check, FileText, FolderOpen, Pencil, Trash2, X } from "lucide-react";
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
  if (tree.length === 0) {
    return (
      <div className="flex items-center justify-center p-4 text-sm text-gray-400 dark:text-gray-500">
        {tt.no_content}
      </div>
    );
  }

  return (
    <nav className="space-y-0.5 text-sm" aria-label={tt.nav_label}>
      {tree.map((node) => (
        <TreeNode
          key={node.path}
          node={node}
          depth={0}
          selectedPath={selectedPath}
          onSelect={onSelect}
          onRenameDomain={onRenameDomain}
          onDeleteDomain={onDeleteDomain}
          onDomainContextMenu={onDomainContextMenu}
          topicLabels={tt}
        />
      ))}
    </nav>
  );
}

function TreeNode({
  node,
  depth,
  selectedPath,
  onSelect,
  onRenameDomain,
  onDeleteDomain,
  onDomainContextMenu,
  topicLabels,
}: {
  node: TopicTreeNode;
  depth: number;
  selectedPath: string | null;
  onSelect: (path: string) => void;
  onRenameDomain?: (uid: string, newDisplayName: string) => void;
  onDeleteDomain?: (uid: string) => void;
  onDomainContextMenu?: (event: MouseEvent, payload: DomainContextMenuPayload) => void;
  topicLabels: {
    expanded: string;
    collapsed: string;
    pending_review: string;
  };
}) {
  const [expanded, setExpanded] = useState(depth === 0);
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState("");
  const [hovered, setHovered] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const hasChildren = node.children.length > 0;
  const isSelected = selectedPath === node.path;
  const isDomain = node.page_type === "domain_overview" || node.label === "WikiSection";
  const domainUid = node.uid?.trim() ?? "";
  const canEdit = isDomain && !!domainUid && !!onRenameDomain;

  useEffect(() => {
    if (editing && inputRef.current) inputRef.current.focus();
  }, [editing]);

  const handleClick = useCallback(() => {
    if (hasChildren) setExpanded((e) => !e);
    onSelect(node.path);
  }, [hasChildren, node.path, onSelect]);

  const startEdit = useCallback((e: MouseEvent) => {
    e.stopPropagation();
    setEditValue(node.name);
    setEditing(true);
  }, [node.name]);

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
      if (domainUid && onDeleteDomain && window.confirm(`Delete domain "${node.name}"?`)) {
        onDeleteDomain(domainUid);
      }
    },
    [domainUid, node.name, onDeleteDomain],
  );

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
      <div
        className="flex items-center gap-1 rounded-md bg-sky-50 px-1 py-1 dark:bg-sky-950/40"
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
      >
        <input
          ref={inputRef}
          type="text"
          value={editValue}
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
    );
  }

  return (
    <div>
      <div
        className="group relative"
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        onContextMenu={handleContextMenu}
      >
        <button
          type="button"
          onClick={handleClick}
          aria-expanded={hasChildren ? expanded : undefined}
          aria-label={
            hasChildren ? `${node.name}，${expanded ? topicLabels.expanded : topicLabels.collapsed}` : node.name
          }
          className={`flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-left transition-colors ${
            isSelected
              ? "bg-sky-50 text-sky-700 dark:bg-sky-950/40 dark:text-sky-400"
              : "text-gray-700 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800"
          }`}
          style={{ paddingLeft: `${depth * 16 + 8}px` }}
        >
          {hasChildren ? (
            expanded ? (
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
        {hovered && canEdit && (
          <div className="absolute right-1 top-1/2 flex -translate-y-1/2 gap-0.5">
            <button
              type="button"
              onClick={startEdit}
              className="rounded p-1 text-gray-400 hover:bg-gray-200 hover:text-gray-700 dark:text-gray-500 dark:hover:bg-gray-700 dark:hover:text-gray-200"
              title="Edit display name"
            >
              <Pencil size={11} />
            </button>
            {onDeleteDomain && (
              <button
                type="button"
                onClick={handleDelete}
                className="rounded p-1 text-gray-400 hover:bg-red-100 hover:text-red-600 dark:text-gray-500 dark:hover:bg-red-900/40 dark:hover:text-red-400"
                title="Delete domain"
              >
                <Trash2 size={11} />
              </button>
            )}
          </div>
        )}
      </div>
      {expanded && hasChildren && (
        <div>
          {node.children.map((child) => (
            <TreeNode
              key={child.path}
              node={child}
              depth={depth + 1}
              selectedPath={selectedPath}
              onSelect={onSelect}
              onRenameDomain={onRenameDomain}
              onDeleteDomain={onDeleteDomain}
              onDomainContextMenu={onDomainContextMenu}
              topicLabels={topicLabels}
            />
          ))}
        </div>
      )}
    </div>
  );
}
