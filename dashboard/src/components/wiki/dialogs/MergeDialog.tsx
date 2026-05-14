import { useState } from "react";
import { useI18n } from "../../../i18n/context";

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

function TreeSelector({
  nodes,
  excludeUid,
  selected,
  onSelect,
  depth = 0,
}: {
  nodes: TreeNode[];
  excludeUid: string;
  selected: string;
  onSelect: (uid: string) => void;
  depth?: number;
}) {
  return (
    <ul className="space-y-0.5">
      {nodes
        .filter((n) => n.uid !== excludeUid)
        .map((node) => (
          <li key={node.uid}>
            <button
              type="button"
              onClick={() => onSelect(node.uid)}
              className={`w-full rounded px-2 py-1 text-left text-sm ${
                selected === node.uid ? "bg-sky-100 text-sky-700 dark:bg-sky-950/40 dark:text-sky-400" : "text-gray-700 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-700"
              }`}
              style={{ paddingLeft: `${depth * 16 + 8}px` }}
            >
              {node.title || node.uid}
            </button>
            {node.children && node.children.length > 0 && (
              <TreeSelector nodes={node.children} excludeUid={excludeUid} selected={selected} onSelect={onSelect} depth={depth + 1} />
            )}
          </li>
        ))}
    </ul>
  );
}

export default function MergeDialog({ sourceUid, sourceTitle, treeData, onConfirm, onCancel }: MergeDialogProps) {
  const { t } = useI18n();
  const [selected, setSelected] = useState("");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onCancel}>
      <div
        className="w-full max-w-md rounded-xl border border-gray-200 bg-white p-6 shadow-xl dark:border-gray-700 dark:bg-gray-900"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="mb-2 text-lg font-semibold text-gray-900 dark:text-white">{t.wiki.domain_management.mergeTitle}</h3>
        <p className="mb-3 text-sm text-gray-600 dark:text-gray-400">{t.wiki.domain_management.mergeConfirm}</p>
        <p className="mb-3 text-sm font-medium text-gray-800 dark:text-gray-200">{sourceTitle}</p>
        <div className="mb-4 max-h-60 overflow-y-auto rounded-lg border border-gray-200 p-2 dark:border-gray-600">
          <TreeSelector nodes={treeData} excludeUid={sourceUid} selected={selected} onSelect={setSelected} />
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
    </div>
  );
}
