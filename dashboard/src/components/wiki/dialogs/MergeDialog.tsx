import { useMemo, useState } from "react";
import { useId } from "react";
import FocusTrap from "../../FocusTrap";
import { useI18n } from "../../../i18n/context";
import { TreeView, type TreeViewNode } from "../../shared/TreeView";

interface TreeNode {
  uid: string;
  title: string;
  children?: TreeNode[];
}

interface MergeDialogProps {
  sourceUid: string;
  sourceTitle: string;
  treeData: TreeNode[];
  onConfirm: (targetUid: string) => void;
  onCancel: () => void;
}

function toTreeViewNodes(nodes: TreeNode[]): TreeViewNode[] {
  return nodes.map((node) => ({
    id: node.uid,
    label: node.title || node.uid,
    children: node.children?.length ? toTreeViewNodes(node.children) : undefined,
  }));
}

export default function MergeDialog({ sourceUid, sourceTitle, treeData, onConfirm, onCancel }: MergeDialogProps) {
  const { t } = useI18n();
  const titleId = useId();
  const [selected, setSelected] = useState("");

  const nodes = useMemo(() => toTreeViewNodes(treeData), [treeData]);
  const excludeIds = useMemo(() => new Set([sourceUid]), [sourceUid]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      onClick={onCancel}
    >
      <FocusTrap onEscape={onCancel}>
        <div
          className="w-full max-w-md rounded-xl border border-gray-200 bg-white p-6 shadow-xl dark:border-gray-700 dark:bg-gray-900"
          onClick={(e) => e.stopPropagation()}
        >
          <h3 id={titleId} className="mb-2 text-lg font-semibold text-gray-900 dark:text-white">
            {t.wiki.domain_management.mergeTitle}
          </h3>
        <p className="mb-3 text-sm text-gray-600 dark:text-gray-400">{t.wiki.domain_management.mergeConfirm}</p>
        <p className="mb-3 text-sm font-medium text-gray-800 dark:text-gray-200">{sourceTitle}</p>
        <div className="mb-4 max-h-60 overflow-y-auto rounded-lg border border-gray-200 p-2 dark:border-gray-600">
          <TreeView
            nodes={nodes}
            selectedId={selected}
            onSelect={setSelected}
            isExpanded={() => true}
            excludeIds={excludeIds}
          />
        </div>
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-800"
          >
            {t.wiki.domain_management.cancel}
          </button>
          <button
            type="button"
            onClick={() => onConfirm(selected)}
            disabled={!selected}
            className="rounded-lg bg-amber-600 px-4 py-2 text-sm text-white hover:bg-amber-700 disabled:opacity-50"
          >
            {t.wiki.domain_management.confirm}
          </button>
        </div>
        </div>
      </FocusTrap>
    </div>
  );
}
