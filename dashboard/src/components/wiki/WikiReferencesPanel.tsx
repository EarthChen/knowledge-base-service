import { useCallback } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowDownLeft,
  ArrowUpRight,
  ChevronLeft,
  ChevronRight,
  Loader2,
} from "lucide-react";
import type { WikiReference } from "../../hooks/wikiTypes";
import { useWikiReferences } from "../../hooks/useWikiReferences";
import { wikiHref } from "./wikiRouteHelpers";
import { useI18n } from "../../i18n/context";

function relationIcon(relType: string): string {
  const map: Record<string, string> = {
    calls: "fn",
    inherits: "ext",
    imports: "imp",
    cross_repo: "repo",
    semantic: "sem",
    business_flow: "flow",
  };
  return map[relType] || relType.slice(0, 3);
}

function ReferenceItem({
  reference,
  onClick,
}: {
  reference: WikiReference;
  onClick: () => void;
}) {
  const r = reference;
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-start gap-2 rounded-lg px-3 py-2 text-left transition-colors hover:bg-gray-50 dark:hover:bg-gray-800"
    >
      <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded bg-gray-100 text-[9px] font-bold uppercase text-gray-600 dark:bg-gray-800 dark:text-gray-400">
        {relationIcon(r.relation_type)}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium text-gray-900 dark:text-gray-100">
          {r.title}
        </span>
        {r.repository && (
          <span className="mt-0.5 block truncate text-[11px] text-gray-500 dark:text-gray-400">
            {r.repository}
          </span>
        )}
        {r.context && (
          <span className="mt-0.5 block line-clamp-2 text-[11px] text-gray-400 dark:text-gray-500">
            {r.context}
          </span>
        )}
      </span>
    </button>
  );
}

function resolvePageUid(pageUid: string, pagePath: string, repository: string): string {
  const u = pageUid.trim();
  if (u) return u;
  const repo = repository.trim();
  const path = pagePath.trim();
  if (repo && path) return `WikiPage:${repo}:${path}`;
  return "";
}

interface WikiReferencesPanelProps {
  /** Graph WikiPage uid when API provides it (by-path context.uid). */
  pageUid: string;
  pagePath: string;
  repository: string;
  wikiLinkParams?: Record<string, string>;
  isOpen: boolean;
  onToggle: () => void;
}

export default function WikiReferencesPanel({
  pageUid,
  pagePath,
  repository,
  wikiLinkParams,
  isOpen,
  onToggle,
}: WikiReferencesPanelProps) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const uid = resolvePageUid(pageUid, pagePath, repository);
  const { data, isLoading, isError } = useWikiReferences(uid);

  const outgoing = data?.outgoing ?? [];
  const incoming = data?.incoming ?? [];

  const go = useCallback(
    (path: string) => {
      navigate(wikiHref(path, wikiLinkParams));
    },
    [navigate, wikiLinkParams],
  );

  if (!isOpen) {
    return (
      <button
        type="button"
        onClick={onToggle}
        className="hidden shrink-0 items-center justify-center rounded-xl border border-gray-200 bg-white p-2 shadow-sm hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-900 dark:hover:bg-gray-800 lg:flex"
        title={t.wiki.referencesShowPanel}
      >
        <ChevronLeft size={16} className="text-gray-500" />
      </button>
    );
  }

  return (
    <aside className="hidden w-64 shrink-0 flex-col rounded-xl border border-gray-200 bg-white shadow-sm dark:border-gray-700 dark:bg-gray-900 lg:flex">
      <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3 dark:border-gray-700">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
          {t.wiki.referencesHeading}
        </h3>
        <button
          type="button"
          onClick={onToggle}
          className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-700 dark:hover:bg-gray-800 dark:hover:text-gray-200"
          aria-label={t.common.close}
        >
          <ChevronRight size={14} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {!uid && (
          <p className="px-4 py-4 text-xs text-gray-500 dark:text-gray-400">{t.wiki.referencesNoPageId}</p>
        )}

        {uid && isLoading && (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="size-5 animate-spin text-gray-400" />
          </div>
        )}

        {uid && isError && (
          <p className="px-4 py-4 text-xs text-gray-500 dark:text-gray-400">{t.wiki.referencesLoadError}</p>
        )}

        {uid && !isLoading && !isError && outgoing.length === 0 && incoming.length === 0 && (
          <p className="px-4 py-6 text-center text-xs text-gray-500 dark:text-gray-400">
            {t.wiki.referencesEmpty}
          </p>
        )}

        {uid && !isLoading && !isError && outgoing.length > 0 && (
          <div className="border-b border-gray-50 px-3 py-3 dark:border-gray-800">
            <h4 className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
              <ArrowUpRight size={12} aria-hidden />
              {t.wiki.referencesOutgoing.replace("{count}", String(outgoing.length))}
            </h4>
            <div className="space-y-0.5">
              {outgoing.map((r) => (
                <ReferenceItem
                  key={r.target_uid ?? `${r.path}-${r.title}`}
                  reference={r}
                  onClick={() => go(r.path)}
                />
              ))}
            </div>
          </div>
        )}

        {uid && !isLoading && !isError && incoming.length > 0 && (
          <div className="px-3 py-3">
            <h4 className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
              <ArrowDownLeft size={12} aria-hidden />
              {t.wiki.referencesIncoming.replace("{count}", String(incoming.length))}
            </h4>
            <div className="space-y-0.5">
              {incoming.map((r) => (
                <ReferenceItem
                  key={r.source_uid ?? `${r.path}-${r.title}`}
                  reference={r}
                  onClick={() => go(r.path)}
                />
              ))}
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}
