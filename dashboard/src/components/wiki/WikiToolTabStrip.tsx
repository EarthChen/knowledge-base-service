import { useCallback, type ReactNode } from "react";
import {
  Activity,
  FileOutput,
  GitBranch,
  LayoutGrid,
  Network,
  PieChart,
  BookMarked,
  Workflow,
} from "lucide-react";
import { useI18n } from "../../i18n/context";
import type { WikiToolTab } from "./WikiToolPanel";

type Props = {
  toolTab: WikiToolTab;
  onToolTabChange: (tab: WikiToolTab) => void;
};

export default function WikiToolTabStrip({ toolTab, onToolTabChange }: Props) {
  const { t } = useI18n();

  const tabBtn = useCallback(
    (id: WikiToolTab, label: string, icon: ReactNode) => (
      <button
        key={id}
        type="button"
        role="tab"
        id={`wiki-tab-${id}`}
        aria-selected={toolTab === id}
        aria-controls={`wiki-panel-${id}`}
        onClick={() => onToolTabChange(id)}
        className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-medium transition-colors ${
          toolTab === id
            ? "bg-sky-100 text-sky-800 ring-1 ring-sky-200 dark:bg-sky-950 dark:text-sky-200 dark:ring-sky-800"
            : "text-gray-600 hover:bg-gray-100 hover:text-gray-900 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-100"
        }`}
      >
        {icon}
        {label}
      </button>
    ),
    [onToolTabChange, toolTab],
  );

  return (
    <div className="flex flex-wrap gap-2" role="tablist" aria-label="Wiki tools">
      {tabBtn("page", t.wiki.tabPage, <LayoutGrid size={14} className="text-sky-600 dark:text-sky-400" aria-hidden />)}
      {tabBtn(
        "coverage",
        t.wiki.coverageTitle,
        <PieChart size={14} className="text-sky-600 dark:text-sky-400" aria-hidden />,
      )}
      {tabBtn(
        "health",
        t.wiki.tabHealth,
        <Activity size={14} className="text-emerald-600 dark:text-emerald-400" aria-hidden />,
      )}
      {tabBtn(
        "insights",
        t.wiki.tabInsights,
        <Network size={14} className="text-violet-600 dark:text-violet-400" aria-hidden />,
      )}
      {tabBtn(
        "refgraph",
        t.wiki.tabRefGraph,
        <GitBranch size={14} className="text-cyan-600 dark:text-cyan-400" aria-hidden />,
      )}
      {tabBtn(
        "research",
        t.wiki.tabResearch,
        <BookMarked size={14} className="text-indigo-600 dark:text-indigo-400" aria-hidden />,
      )}
      {tabBtn(
        "flows",
        t.wiki.tabFlows,
        <Workflow size={14} className="text-teal-600 dark:text-teal-400" aria-hidden />,
      )}
      {tabBtn(
        "export",
        t.wiki.tabExport,
        <FileOutput size={14} className="text-sky-600 dark:text-sky-400" aria-hidden />,
      )}
    </div>
  );
}
