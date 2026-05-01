import { useState, useCallback } from "react";
import { ChevronRight, ChevronDown, FileText, FolderOpen } from "lucide-react";
import { useI18n } from "../../i18n/context";
import type { TopicTreeNode } from "../../hooks/useWikiDomainTree";

interface Props {
  tree: TopicTreeNode[];
  selectedPath: string | null;
  onSelect: (path: string) => void;
}

export default function WikiTopicTreeNav({ tree, selectedPath, onSelect }: Props) {
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
  topicLabels,
}: {
  node: TopicTreeNode;
  depth: number;
  selectedPath: string | null;
  onSelect: (path: string) => void;
  topicLabels: {
    expanded: string;
    collapsed: string;
    pending_review: string;
  };
}) {
  const [expanded, setExpanded] = useState(depth === 0);
  const hasChildren = node.children.length > 0;
  const isSelected = selectedPath === node.path;
  const isDomain = node.page_type === "domain_overview";

  const handleClick = useCallback(() => {
    if (hasChildren) setExpanded((e) => !e);
    onSelect(node.path);
  }, [hasChildren, node.path, onSelect]);

  return (
    <div>
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
      {expanded && hasChildren && (
        <div>
          {node.children.map((child) => (
            <TreeNode
              key={child.path}
              node={child}
              depth={depth + 1}
              selectedPath={selectedPath}
              onSelect={onSelect}
              topicLabels={topicLabels}
            />
          ))}
        </div>
      )}
    </div>
  );
}
