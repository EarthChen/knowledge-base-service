import { useEffect, useRef } from "react";
import { useI18n } from "../../i18n/context";

interface DomainContextMenuProps {
  x: number;
  y: number;
  nodeUid: string;
  nodeTitle: string;
  isRoot: boolean;
  onClose: () => void;
  onRename: () => void;
  onDelete: () => void;
  onCreateSubdomain: () => void;
  onMove: () => void;
  onMerge: () => void;
}

export default function DomainContextMenu({
  x,
  y,
  nodeUid: _nodeUid,
  nodeTitle: _nodeTitle,
  isRoot,
  onClose,
  onRename,
  onDelete,
  onCreateSubdomain,
  onMove,
  onMerge,
}: DomainContextMenuProps) {
  const { t } = useI18n();
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        onClose();
      }
    };
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("mousedown", handleClick);
    document.addEventListener("keydown", handleEsc);
    return () => {
      document.removeEventListener("mousedown", handleClick);
      document.removeEventListener("keydown", handleEsc);
    };
  }, [onClose]);

  const items = [
    { label: t.wiki.domain_management.rename, action: onRename, disabled: isRoot },
    { label: t.wiki.domain_management.createSubdomain, action: onCreateSubdomain, disabled: false },
    { label: t.wiki.domain_management.moveTo, action: onMove, disabled: isRoot },
    { label: t.wiki.domain_management.mergeTo, action: onMerge, disabled: isRoot },
    { label: t.wiki.domain_management.delete, action: onDelete, disabled: isRoot },
  ];

  return (
    <div
      ref={ref}
      role="menu"
      className="fixed z-50 min-w-[160px] rounded-lg border border-gray-200 bg-white py-1 shadow-lg dark:border-gray-700 dark:bg-gray-800"
      style={{ left: x, top: y }}
    >
      {items.map((item) => (
        <button
          key={item.label}
          type="button"
          role="menuitem"
          disabled={item.disabled}
          onClick={() => {
            item.action();
            onClose();
          }}
          className="w-full px-3 py-1.5 text-left text-sm text-gray-700 hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-40 dark:text-gray-200 dark:hover:bg-gray-700"
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}
