import { useMemo, useState } from "react";
import { Download, FileOutput, GitBranch, Loader2 } from "lucide-react";
import { useBusinessWikiExport } from "../../hooks/useBusinessWikiExport";
import { useBusiness } from "../../contexts/BusinessContext";
import GitPushConfigDialog from "./GitPushConfigDialog";
import type { BusinessWikiExportBody } from "../../hooks/wikiTypes";
import { useI18n } from "../../i18n/context";

type ExportFormat = BusinessWikiExportBody["format"];
type ViewType = BusinessWikiExportBody["view_type"];
type MinTier = BusinessWikiExportBody["min_tier"];

export default function WikiBusinessExportPanel() {
  const { t } = useI18n();
  const formatOptions = useMemo(
    () =>
      [
        {
          value: "markdown" as const,
          label: t.wiki.exportFormatMarkdownLabel,
          desc: t.wiki.exportFormatMarkdownDesc,
        },
        {
          value: "zip" as const,
          label: t.wiki.exportFormatZipLabel,
          desc: t.wiki.exportFormatZipDesc,
        },
        {
          value: "obsidian" as const,
          label: t.wiki.exportFormatObsidianLabel,
          desc: t.wiki.exportFormatObsidianDesc,
        },
        {
          value: "mkdocs" as const,
          label: t.wiki.exportFormatMkdocsLabel,
          desc: t.wiki.exportFormatMkdocsDesc,
        },
        {
          value: "git" as const,
          label: t.wiki.exportFormatGitLabel,
          desc: t.wiki.exportFormatGitDesc,
        },
      ] satisfies { value: ExportFormat; label: string; desc: string }[],
    [t],
  );
  const { currentBusiness } = useBusiness();
  const exportMutation = useBusinessWikiExport();
  const [format, setFormat] = useState<ExportFormat>("markdown");
  const [viewType, setViewType] = useState<ViewType>("both");
  const [minTier, setMinTier] = useState<MinTier>("standard");
  const [gitDialogOpen, setGitDialogOpen] = useState(false);
  const [gitConfig, setGitConfig] = useState<BusinessWikiExportBody["git_config"]>();

  const handleExport = () => {
    if (format === "git" && !gitConfig) {
      setGitDialogOpen(true);
      return;
    }
    const body: BusinessWikiExportBody = {
      business_id: currentBusiness,
      format,
      view_type: viewType,
      min_tier: minTier,
    };
    if (format === "git" && gitConfig) body.git_config = gitConfig;
    exportMutation.mutate(body);
  };

  return (
    <section className="rounded-xl border border-gray-200 bg-white shadow-sm dark:border-gray-700 dark:bg-gray-900">
      <div className="flex items-center gap-2 border-b border-gray-100 px-4 py-3 dark:border-gray-700">
        <FileOutput size={18} className="text-sky-600 dark:text-sky-400" />
        <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">
          {t.wiki.exportBusinessPanelTitle}
        </span>
      </div>

      <div className="space-y-4 px-4 py-4">
        <div>
          <label className="block text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
            {t.wiki.exportFormatLabel}
          </label>
          <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
            {formatOptions.map((opt) => (
              <button
                key={opt.value}
                type="button"
                onClick={() => setFormat(opt.value)}
                className={`rounded-lg border px-3 py-2 text-left text-xs transition-colors ${
                  format === opt.value
                    ? "border-sky-300 bg-sky-50 text-sky-800 dark:border-sky-700 dark:bg-sky-950/50 dark:text-sky-200"
                    : "border-gray-200 bg-white text-gray-700 hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-300 dark:hover:bg-gray-800"
                }`}
              >
                <span className="block font-medium">{opt.label}</span>
                <span className="mt-0.5 block text-[11px] text-gray-500 dark:text-gray-400">{opt.desc}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-wrap gap-4">
          <label className="block">
            <span className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
              {t.wiki.exportViewLabel}
            </span>
            <select
              value={viewType}
              onChange={(e) => setViewType(e.target.value as ViewType)}
              className="mt-1 block rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:border-sky-400 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
            >
              <option value="both">{t.wiki.exportViewBoth}</option>
              <option value="business_domain">{t.wiki.exportViewBusinessDomain}</option>
              <option value="code_structure">{t.wiki.exportViewCodeStructure}</option>
            </select>
          </label>
          <label className="block">
            <span className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
              {t.wiki.exportMinTierLabel}
            </span>
            <select
              value={minTier}
              onChange={(e) => setMinTier(e.target.value as MinTier)}
              className="mt-1 block rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:border-sky-400 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
            >
              <option value="core">{t.wiki.exportMinTierCore}</option>
              <option value="standard">{t.wiki.exportMinTierStandard}</option>
              <option value="skeleton">{t.wiki.exportMinTierSkeleton}</option>
            </select>
          </label>
        </div>

        {format === "git" && (
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => setGitDialogOpen(true)}
              className="inline-flex items-center gap-2 rounded-lg border border-gray-200 px-3 py-2 text-xs font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-700 dark:text-gray-300 dark:hover:bg-gray-800"
            >
              <GitBranch size={14} />
              {gitConfig ? t.wiki.exportEditGitConfig : t.wiki.exportConfigureGit}
            </button>
            {gitConfig && (
              <span className="truncate font-mono text-xs text-gray-500">{gitConfig.remote_url}</span>
            )}
          </div>
        )}

        <button
          type="button"
          onClick={handleExport}
          disabled={exportMutation.isPending || (format === "git" && !gitConfig)}
          className="inline-flex items-center gap-2 rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-500 disabled:opacity-50"
        >
          {exportMutation.isPending ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <Download size={16} />
          )}
          {exportMutation.isPending ? t.wiki.exportExporting : t.wiki.exportButton}
        </button>

        {exportMutation.isError && (
          <p className="text-sm text-red-600 dark:text-red-400">
            {exportMutation.error instanceof Error ? exportMutation.error.message : t.wiki.exportFailed}
          </p>
        )}

        {exportMutation.data && (
          <div className="rounded-lg border border-emerald-200 bg-emerald-50/80 px-3 py-3 text-sm text-emerald-900 dark:border-emerald-900/50 dark:bg-emerald-950/40 dark:text-emerald-100">
            <p className="font-semibold">{t.wiki.exportComplete}</p>
            <p className="mt-1 text-xs">
              {t.wiki.exportSummaryLine
                .replace("{count}", String(exportMutation.data.file_count))
                .replace("{format}", exportMutation.data.format)}
              {exportMutation.data.download_url && /^https?:\/\//i.test(exportMutation.data.download_url) && (
                <a href={exportMutation.data.download_url} className="ml-2 text-sky-600 underline" rel="noopener noreferrer">
                  {t.wiki.exportDownload}
                </a>
              )}
            </p>
          </div>
        )}
      </div>

      <GitPushConfigDialog
        open={gitDialogOpen}
        onClose={() => setGitDialogOpen(false)}
        onConfirm={(config) => setGitConfig(config)}
      />
    </section>
  );
}
