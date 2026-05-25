export interface TreeViewNode {
  id: string;
  label: string;
  children?: TreeViewNode[];
}

interface TreeViewProps {
  nodes: TreeViewNode[];
  selectedId?: string | null;
  onSelect: (id: string) => void;
  isExpanded: (id: string) => boolean;
  onToggleExpand?: (id: string) => void;
  excludeIds?: Set<string>;
  className?: string;
}

function TreeViewBranch({
  nodes,
  selectedId,
  onSelect,
  isExpanded,
  onToggleExpand,
  excludeIds,
  depth = 0,
}: {
  nodes: TreeViewNode[];
  selectedId?: string | null;
  onSelect: (id: string) => void;
  isExpanded: (id: string) => boolean;
  onToggleExpand?: (id: string) => void;
  excludeIds?: Set<string>;
  depth?: number;
}) {
  return (
    <ul className={depth === 0 ? "space-y-0.5" : "mt-0.5 space-y-0.5"} role={depth === 0 ? "tree" : "group"}>
      {nodes
        .filter((node) => !excludeIds?.has(node.id))
        .map((node) => {
          const hasChildren = (node.children?.length ?? 0) > 0;
          const expanded = !hasChildren || isExpanded(node.id);
          const isSelected = selectedId === node.id;

          return (
            <li key={node.id} role="treeitem" aria-expanded={hasChildren ? expanded : undefined}>
              <button
                type="button"
                onClick={() => {
                  if (hasChildren && onToggleExpand) {
                    onToggleExpand(node.id);
                  }
                  onSelect(node.id);
                }}
                className={`w-full rounded px-2 py-1 text-left text-sm ${
                  isSelected
                    ? "bg-sky-100 text-sky-700 dark:bg-sky-950/40 dark:text-sky-400"
                    : "text-gray-700 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-700"
                }`}
                style={{ paddingLeft: `${depth * 16 + 8}px` }}
              >
                {node.label}
              </button>
              {hasChildren && expanded && node.children && (
                <TreeViewBranch
                  nodes={node.children}
                  selectedId={selectedId}
                  onSelect={onSelect}
                  isExpanded={isExpanded}
                  onToggleExpand={onToggleExpand}
                  excludeIds={excludeIds}
                  depth={depth + 1}
                />
              )}
            </li>
          );
        })}
    </ul>
  );
}

export function TreeView({
  nodes,
  selectedId,
  onSelect,
  isExpanded,
  onToggleExpand,
  excludeIds,
  className,
}: TreeViewProps) {
  return (
    <div className={className}>
      <TreeViewBranch
        nodes={nodes}
        selectedId={selectedId}
        onSelect={onSelect}
        isExpanded={isExpanded}
        onToggleExpand={onToggleExpand}
        excludeIds={excludeIds}
      />
    </div>
  );
}
