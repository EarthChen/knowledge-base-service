import { Eye, EyeOff } from "lucide-react";
import { useI18n } from "../../i18n/context";
import { CHIP_BASE, type NodeTypeKey } from "./graphLayout";

type GraphFilterBarProps = {
  typeVisible: Record<NodeTypeKey, boolean>;
  toggleType: (key: NodeTypeKey) => void;
  showEdgeLabels: boolean;
  setShowEdgeLabels: (v: boolean | ((prev: boolean) => boolean)) => void;
  legend: { type: NodeTypeKey; color: string }[];
};

export default function GraphFilterBar({
  typeVisible,
  toggleType,
  showEdgeLabels,
  setShowEdgeLabels,
  legend,
}: GraphFilterBarProps) {
  const { t } = useI18n();

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-[11px] font-medium text-gray-500 dark:text-gray-400">
        {t.explorer.filterHint}:
      </span>
      {(
        [
          ["Function", t.explorer.typeFunction, legend[0]!.color],
          ["Class", t.explorer.typeClass, legend[1]!.color],
          ["Module", t.explorer.typeModule, legend[2]!.color],
          ["Document", t.explorer.typeDocument, legend[3]!.color],
        ] as const
      ).map(([key, label, color]) => {
        const on = typeVisible[key];
        return (
          <button
            key={key}
            type="button"
            aria-pressed={on}
            onClick={() => toggleType(key)}
            className={`${CHIP_BASE} ${
              on
                ? "border-gray-200 bg-white text-gray-800 shadow-sm dark:border-gray-500 dark:bg-gray-800 dark:text-gray-100"
                : "border-gray-100 bg-gray-100 text-gray-400 line-through dark:border-gray-700 dark:bg-gray-900/80 dark:text-gray-500"
            }`}
          >
            <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: color }} />
            {label}
          </button>
        );
      })}
      <button
        type="button"
        onClick={() => setShowEdgeLabels((v) => !v)}
        className={`${CHIP_BASE} ml-auto border-gray-200 bg-white text-gray-700 shadow-sm dark:border-gray-500 dark:bg-gray-800 dark:text-gray-200`}
      >
        {showEdgeLabels ? <Eye size={14} /> : <EyeOff size={14} />}
        {t.explorer.edgeLabelToggle}: {showEdgeLabels ? t.explorer.edgeLabelsOn : t.explorer.edgeLabelsOff}
      </button>
    </div>
  );
}
