import { useMutation } from "@tanstack/react-query";
import { Activity, Loader2, RefreshCw } from "lucide-react";
import { wikiLint } from "../../api/client";
import type { WikiLintIssue, WikiLintReport } from "../../api/types";
import { useI18n } from "../../i18n/context";

type Props = {
  repository: string;
};

function severityBadgeClass(sev: WikiLintIssue["severity"]): string {
  if (sev === "error") {
    return "bg-red-100 text-red-800 ring-red-200 dark:bg-red-950/60 dark:text-red-300 dark:ring-red-900";
  }
  if (sev === "warning") {
    return "bg-amber-100 text-amber-900 ring-amber-200 dark:bg-amber-950/50 dark:text-amber-200 dark:ring-amber-900";
  }
  return "bg-sky-100 text-sky-800 ring-sky-200 dark:bg-sky-950/50 dark:text-sky-300 dark:ring-sky-800";
}

function formatCategory(cat: string): string {
  return cat.replace(/_/g, " ");
}

export default function WikiLintPanel({ repository }: Props) {
  const { locale, t } = useI18n();
  const mutation = useMutation<WikiLintReport, Error, void>({
    mutationFn: () => wikiLint(repository, "all"),
  });

  const report = mutation.data;
  const stats = report?.stats;

  return (
    <section className="rounded-xl border border-gray-200 bg-white shadow-sm dark:border-gray-700 dark:bg-gray-900 dark:shadow-gray-950/40">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-100 px-4 py-3 dark:border-gray-700">
        <div className="flex items-center gap-2 text-sm font-semibold text-gray-900 dark:text-gray-100">
          <Activity size={18} className="text-emerald-600 dark:text-emerald-400" aria-hidden />
          {t.wiki.lintTitle}
        </div>
        <button
          type="button"
          onClick={() => mutation.mutate()}
          disabled={mutation.isPending}
          className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white shadow-sm hover:bg-emerald-500 disabled:opacity-50"
        >
          {mutation.isPending ? (
            <Loader2 className="size-3.5 animate-spin" aria-hidden />
          ) : (
            <RefreshCw className="size-3.5" aria-hidden />
          )}
          {t.wiki.lintRunCheck}
        </button>
      </div>

      <div className="space-y-4 px-4 py-4">
        <p className="text-xs text-gray-500 dark:text-gray-400">{t.wiki.lintHelp}</p>

        {mutation.isError && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-300">
            {mutation.error.message}
          </div>
        )}

        {stats && (
          <div className="flex flex-wrap gap-2">
            <span className="rounded-full bg-gray-100 px-3 py-1 text-xs font-medium text-gray-800 ring-1 ring-gray-200 dark:bg-gray-800 dark:text-gray-200 dark:ring-gray-600">
              {t.wiki.lintTotal} {stats.total}
            </span>
            <span className="rounded-full bg-red-100 px-3 py-1 text-xs font-medium text-red-800 ring-1 ring-red-200 dark:bg-red-950/50 dark:text-red-300 dark:ring-red-900">
              {t.wiki.lintErrors} {stats.errors}
            </span>
            <span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-medium text-amber-900 ring-1 ring-amber-200 dark:bg-amber-950/50 dark:text-amber-200 dark:ring-amber-900">
              {t.wiki.lintWarnings} {stats.warnings}
            </span>
            <span className="rounded-full bg-sky-100 px-3 py-1 text-xs font-medium text-sky-800 ring-1 ring-sky-200 dark:bg-sky-950/50 dark:text-sky-300 dark:ring-sky-800">
              {t.wiki.lintInfo} {stats.info}
            </span>
            {report?.checked_at && (
              <span className="text-xs text-gray-400 dark:text-gray-500">
                {t.wiki.lintCheckedPrefix}{" "}
                {new Date(report.checked_at).toLocaleString(
                  locale === "zh" ? "zh-CN" : undefined,
                )}
              </span>
            )}
          </div>
        )}

        {report && report.issues.length === 0 && (
          <p className="text-sm text-gray-600 dark:text-gray-400">{t.wiki.lintNoIssues}</p>
        )}

        {report && report.issues.length > 0 && (
          <ul className="max-h-[min(60vh,520px)] space-y-2 overflow-y-auto pr-1">
            {report.issues.map((issue, i) => (
              <li
                key={`${issue.category}-${issue.message}-${i}`}
                className="rounded-lg border border-gray-100 bg-gray-50/80 px-3 py-2.5 text-sm shadow-sm dark:border-gray-700 dark:bg-gray-800/60"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span
                    className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ring-1 ${severityBadgeClass(issue.severity)}`}
                  >
                    {issue.severity}
                  </span>
                  <span className="rounded-md bg-white px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-gray-600 ring-1 ring-gray-200 dark:bg-gray-900 dark:text-gray-400 dark:ring-gray-600">
                    {formatCategory(issue.category)}
                  </span>
                </div>
                <p className="mt-1.5 text-gray-900 dark:text-gray-100">{issue.message}</p>
                <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-gray-600 dark:text-gray-400">
                  {issue.page_path && (
                    <span>
                      <span className="text-gray-400 dark:text-gray-500">{t.wiki.lintPageLabel}</span>{" "}
                      <code className="font-mono text-gray-800 dark:text-gray-300">{issue.page_path}</code>
                    </span>
                  )}
                  {issue.entity_name && (
                    <span>
                      <span className="text-gray-400 dark:text-gray-500">{t.wiki.lintEntityLabel}</span>{" "}
                      <code className="font-mono text-gray-800 dark:text-gray-300">{issue.entity_name}</code>
                    </span>
                  )}
                </div>
                {issue.suggestion && (
                  <p className="mt-1.5 text-xs leading-relaxed text-gray-600 dark:text-gray-400">{issue.suggestion}</p>
                )}
              </li>
            ))}
          </ul>
        )}

        {!report && !mutation.isPending && !mutation.isError && (
          <p className="text-sm text-gray-500 dark:text-gray-400">{t.wiki.lintEmptyHint}</p>
        )}
      </div>
    </section>
  );
}
