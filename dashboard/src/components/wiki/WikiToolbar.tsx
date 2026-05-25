import { Loader2, PanelLeftClose, PanelLeftOpen, RefreshCw, Trash2 } from "lucide-react";
import { useI18n } from "../../i18n/context";
import type { WikiRegenProgress } from "../../hooks/useWikiRegenerate";
import WikiToolTabStrip from "./WikiToolTabStrip";
import WikiSearchBar from "./WikiSearchBar";
import type { WikiToolTab } from "./WikiToolPanel";

export interface WikiToolbarProps {
  sidebarCollapsed: boolean;
  toggleSidebar: () => void;
  toolTab: WikiToolTab;
  setToolTab: (tab: WikiToolTab) => void;
  wikiLinkParams: Record<string, string>;
  repoForIncremental: string;
  isEditor: boolean;
  isAdmin: boolean;
  wikiRegenIncremental: boolean;
  setWikiRegenIncremental: (value: boolean) => void;
  regeneratePending: boolean;
  handleRegenerateWiki: (incremental: boolean) => Promise<void>;
  regenerateProgress: WikiRegenProgress | null;
  onClearWikiClick: () => void;
  clearWikiPending: boolean;
}

export default function WikiToolbar({
  sidebarCollapsed,
  toggleSidebar,
  toolTab,
  setToolTab,
  wikiLinkParams,
  repoForIncremental,
  isEditor,
  isAdmin,
  wikiRegenIncremental,
  setWikiRegenIncremental,
  regeneratePending,
  handleRegenerateWiki,
  regenerateProgress,
  onClearWikiClick,
  clearWikiPending,
}: WikiToolbarProps) {
  const { t } = useI18n();

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-gray-200 bg-white px-3 py-2 shadow-sm dark:border-gray-700 dark:bg-gray-900">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={toggleSidebar}
            className="hidden items-center justify-center rounded-md border border-gray-200 bg-white p-1.5 text-gray-500 hover:bg-gray-50 hover:text-gray-700 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-200 lg:flex"
            aria-label={sidebarCollapsed ? t.wiki.sidebarExpand : t.wiki.sidebarCollapse}
            title={sidebarCollapsed ? t.wiki.sidebarExpand : t.wiki.sidebarCollapse}
          >
            {sidebarCollapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
          </button>
          <WikiToolTabStrip toolTab={toolTab} onToolTabChange={setToolTab} />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <WikiSearchBar linkParams={wikiLinkParams} repository={repoForIncremental} />
          {isEditor && (
            <>
              <div
                className="inline-flex shrink-0 overflow-hidden rounded-lg border border-gray-200 text-xs font-medium dark:border-gray-600"
                role="group"
                aria-label={t.wiki.regenerate}
              >
                <button
                  type="button"
                  onClick={() => setWikiRegenIncremental(true)}
                  disabled={regeneratePending}
                  className={`px-2.5 py-2 transition-colors ${
                    wikiRegenIncremental
                      ? "bg-amber-100 text-amber-950 dark:bg-amber-950/60 dark:text-amber-100"
                      : "bg-white text-gray-600 hover:bg-gray-50 dark:bg-gray-900 dark:text-gray-300 dark:hover:bg-gray-800"
                  }`}
                >
                  {t.wiki.regenerateIncremental}
                </button>
                <button
                  type="button"
                  onClick={() => setWikiRegenIncremental(false)}
                  disabled={regeneratePending}
                  className={`border-l border-gray-200 px-2.5 py-2 transition-colors dark:border-gray-600 ${
                    !wikiRegenIncremental
                      ? "bg-amber-100 text-amber-950 dark:bg-amber-950/60 dark:text-amber-100"
                      : "bg-white text-gray-600 hover:bg-gray-50 dark:bg-gray-900 dark:text-gray-300 dark:hover:bg-gray-800"
                  }`}
                >
                  {t.wiki.regenerateFull}
                </button>
              </div>
              <button
                type="button"
                onClick={() => void handleRegenerateWiki(wikiRegenIncremental)}
                disabled={regeneratePending}
                aria-busy={regeneratePending}
                className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-medium text-amber-900 hover:bg-amber-100 disabled:opacity-50 dark:border-amber-900 dark:bg-amber-950/50 dark:text-amber-200 dark:hover:bg-amber-950"
              >
                {regeneratePending ? (
                  <Loader2 size={14} className="animate-spin" aria-hidden />
                ) : (
                  <RefreshCw size={14} aria-hidden />
                )}
                {t.wiki.regenerate}
              </button>
            </>
          )}
          {isAdmin && (
            <button
              type="button"
              onClick={onClearWikiClick}
              disabled={clearWikiPending}
              className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs font-medium text-red-700 hover:bg-red-100 disabled:opacity-50 dark:border-red-900 dark:bg-red-950/50 dark:text-red-300 dark:hover:bg-red-950"
            >
              <Trash2 size={14} aria-hidden />
              {t.wiki.clearAllWiki}
            </button>
          )}
        </div>
      </div>

      {regenerateProgress && (
        <div className="space-y-1.5 rounded-lg border border-amber-200/80 bg-amber-50/50 px-3 py-2 dark:border-amber-900/50 dark:bg-amber-950/20">
          <p className="text-xs text-amber-950 dark:text-amber-100">
            {t.wiki.regenerateProgress
              .replace("{current}", regenerateProgress.currentRepo || "—")
              .replace("{pct}", String(Math.round(regenerateProgress.progressPct)))}
          </p>
          {regenerateProgress.skippedRepos > 0 && (
            <p className="text-xs text-gray-600 dark:text-gray-400">
              {t.wiki.regenerateSkipped.replace("{count}", String(regenerateProgress.skippedRepos))}
            </p>
          )}
          <div
            className="h-2 w-full overflow-hidden rounded-full bg-gray-200 dark:bg-gray-700"
            role="progressbar"
            aria-valuenow={Math.round(regenerateProgress.progressPct)}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label={t.wiki.regenerateProgress
              .replace("{current}", regenerateProgress.currentRepo || "—")
              .replace("{pct}", String(Math.round(regenerateProgress.progressPct)))}
          >
            <div
              className="h-full rounded-full bg-amber-500 transition-[width] dark:bg-amber-600"
              style={{ width: `${Math.min(100, Math.max(0, regenerateProgress.progressPct))}%` }}
            />
          </div>
        </div>
      )}
    </>
  );
}
