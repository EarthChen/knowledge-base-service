import { useEffect, useRef, useCallback, type KeyboardEvent } from "react";
import FocusTrap from "../FocusTrap";
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
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([]);

  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        onClose();
      }
    };
    document.addEventListener("mousedown", handleClick);
    return () => {
      document.removeEventListener("mousedown", handleClick);
    };
  }, [onClose]);

  const getEnabledItems = useCallback(
    () => itemRefs.current.filter((el): el is HTMLButtonElement => el != null && !el.disabled),
    [],
  );

  const focusEnabledAt = useCallback(
    (index: number) => {
      const enabled = getEnabledItems();
      if (enabled.length === 0) return;
      const wrapped = ((index % enabled.length) + enabled.length) % enabled.length;
      enabled[wrapped]?.focus();
    },
    [getEnabledItems],
  );

  const handleMenuKeyDown = useCallback(
    (e: KeyboardEvent<HTMLDivElement>) => {
      const enabled = getEnabledItems();
      if (enabled.length === 0) return;
      const current = enabled.indexOf(document.activeElement as HTMLButtonElement);

      switch (e.key) {
        case "ArrowDown":
          e.preventDefault();
          focusEnabledAt(current < 0 ? 0 : current + 1);
          break;
        case "ArrowUp":
          e.preventDefault();
          focusEnabledAt(current < 0 ? enabled.length - 1 : current - 1);
          break;
        case "Home":
          e.preventDefault();
          enabled[0]?.focus();
          break;
        case "End":
          e.preventDefault();
          enabled[enabled.length - 1]?.focus();
          break;
      }
    },
    [focusEnabledAt, getEnabledItems],
  );

  const items = [
    { label: t.wiki.domain_management.rename, action: onRename, disabled: isRoot },
    { label: t.wiki.domain_management.createSubdomain, action: onCreateSubdomain, disabled: false },
    { label: t.wiki.domain_management.moveTo, action: onMove, disabled: isRoot },
    { label: t.wiki.domain_management.mergeTo, action: onMerge, disabled: isRoot },
    { label: t.wiki.domain_management.delete, action: onDelete, disabled: isRoot },
  ];

  return (
    <FocusTrap onEscape={onClose}>
      <div
        ref={ref}
        role="menu"
        onKeyDown={handleMenuKeyDown}
        className="fixed z-50 min-w-[160px] rounded-lg border border-gray-200 bg-white py-1 shadow-lg dark:border-gray-700 dark:bg-gray-800"
        style={{ left: x, top: y }}
      >
        {items.map((item, index) => (
          <button
            key={item.label}
            ref={(el) => {
              itemRefs.current[index] = el;
            }}
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
    </FocusTrap>
  );
}
