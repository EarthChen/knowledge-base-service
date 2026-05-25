import { Link } from "react-router-dom";
import { Search, BookOpen } from "lucide-react";
import type { UseMutationResult, UseQueryResult } from "@tanstack/react-query";
import type { GraphNode as ApiNode, GraphExpandResponse, GraphExpandRequest } from "../../api/types";
import type { ApiError } from "../../api/client";
import type { WikiPathForSourceEntityResponse } from "../../hooks/useWikiPathForSourceEntity";
import { wikiHref } from "../../components/wiki/wikiRouteHelpers";
import { useI18n } from "../../i18n/context";
import { normalizeGraphType, paletteForTheme, truncateDoc } from "./graphLayout";

type NodeDetailPanelProps = {
  node: ApiNode;
  isDark: boolean;
  businessId: string | null;
  wikiForEntity: UseQueryResult<WikiPathForSourceEntityResponse, Error>;
  expandMutation: UseMutationResult<GraphExpandResponse, ApiError, GraphExpandRequest, unknown>;
  onExpandNeighbors: (nodeUid: string, expandLimit: number) => void;
};

export default function NodeDetailPanel({
  node,
  isDark,
  businessId,
  wikiForEntity,
  expandMutation,
  onExpandNeighbors,
}: NodeDetailPanelProps) {
  const { t } = useI18n();
  const palette = paletteForTheme(isDark);
  const typeColors = palette[normalizeGraphType(node.type)];

  return (
    <aside className="w-full shrink-0 rounded-xl border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-700 dark:bg-gray-900 lg:w-80">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400 dark:text-gray-500">
        {t.explorer.panelTitle}
      </h3>
      <div className="mt-3 flex items-start justify-between gap-2">
        <p className="break-all text-sm font-semibold text-gray-900 dark:text-gray-100">{node.name}</p>
        <span
          className="shrink-0 rounded-md px-2 py-0.5 text-[10px] font-medium"
          style={{
            backgroundColor: typeColors?.bg ?? "#f1f5f9",
            color: typeColors?.text ?? "#334155",
            border: `1px solid ${typeColors?.border ?? "#64748b"}`,
          }}
        >
          {node.type}
        </span>
      </div>

      {node.file ? (
        <p className="mt-2 break-all text-xs text-gray-600 dark:text-gray-400">{node.file}</p>
      ) : null}

      <p className="mt-2 text-xs text-gray-700 dark:text-gray-300">
        <span className="font-medium text-gray-500 dark:text-gray-400">{t.explorer.panelLineRange}: </span>
        {node.line != null
          ? node.end_line != null && node.end_line !== node.line
            ? `${node.line}–${node.end_line}`
            : String(node.line)
          : "—"}
      </p>

      {node.signature ? (
        <div className="mt-3">
          <p className="text-[11px] font-medium text-gray-500 dark:text-gray-400">{t.explorer.panelSignature}</p>
          <pre className="mt-1 max-h-28 overflow-auto whitespace-pre-wrap break-all rounded-md bg-gray-50 p-2 text-[11px] text-gray-800 dark:bg-gray-800 dark:text-gray-200">
            {node.signature}
          </pre>
        </div>
      ) : null}

      {node.docstring ? (
        <div className="mt-3">
          <p className="text-[11px] font-medium text-gray-500 dark:text-gray-400">{t.explorer.panelDocstring}</p>
          <p className="mt-1 text-xs leading-relaxed text-gray-700 dark:text-gray-300">
            {truncateDoc(node.docstring)}
          </p>
        </div>
      ) : null}

      <div className="mt-4 flex flex-col gap-2">
        <button
          type="button"
          disabled={expandMutation.isPending}
          onClick={() => onExpandNeighbors(node.id, 100)}
          className="inline-flex items-center justify-center rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs font-medium text-emerald-900 transition-colors hover:bg-emerald-100 disabled:opacity-50 dark:border-emerald-900 dark:bg-emerald-950/80 dark:text-emerald-100 dark:hover:bg-emerald-900"
        >
          {t.explorer.expandAllNeighbors}
        </button>
        {wikiForEntity.data?.path && !wikiForEntity.isLoading && !wikiForEntity.isError ? (
          <Link
            to={wikiHref(wikiForEntity.data.path!, businessId ? { business_id: businessId } : undefined)}
            className="inline-flex items-center justify-center rounded-lg border border-violet-200 bg-violet-50 px-3 py-2 text-xs font-medium text-violet-900 hover:bg-violet-100 dark:border-violet-800 dark:bg-violet-950/80 dark:text-violet-100 dark:hover:bg-violet-900/80"
          >
            <BookOpen size={14} className="mr-1.5 inline shrink-0" aria-hidden />
            {t.graph.viewWiki}
          </Link>
        ) : null}
        <Link
          to={
            node.name
              ? `/search?mode=wiki&q=${encodeURIComponent(node.name)}`
              : "/search?mode=wiki"
          }
          className="inline-flex items-center justify-center rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-xs font-medium text-sky-900 hover:bg-sky-100 dark:border-sky-800 dark:bg-sky-950/80 dark:text-sky-100 dark:hover:bg-sky-900"
        >
          {t.explorer.openInWiki}
        </Link>
        <Link
          to={node.name ? `/search?q=${encodeURIComponent(node.name)}` : "/search"}
          className="inline-flex items-center justify-center rounded-lg border border-gray-200 bg-white px-3 py-2 text-xs font-medium text-gray-800 hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:hover:bg-gray-700"
        >
          <Search size={14} className="mr-1.5 inline" />
          {t.explorer.searchRelated}
        </Link>
      </div>

      <p className="mt-4 text-[10px] text-gray-400 dark:text-gray-500">{t.explorer.doubleClickHint}</p>
    </aside>
  );
}
