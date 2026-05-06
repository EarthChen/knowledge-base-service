import { ChevronDown, ChevronRight, Loader2 } from "lucide-react";
import { useState } from "react";
import { useI18n } from "../../i18n/context";
import type { WikiRelatedEntityRow } from "../../hooks/wikiTypes";
import { useWikiEntities } from "../../hooks/useWikiEntities";

function typeBadgeClass(entityType: string): string {
  const t = entityType.toLowerCase();
  if (t.includes("function")) {
    return "bg-violet-100 text-violet-800 dark:bg-violet-950/50 dark:text-violet-300";
  }
  if (t.includes("class")) {
    return "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-300";
  }
  if (t.includes("module")) {
    return "bg-sky-100 text-sky-800 dark:bg-sky-950/50 dark:text-sky-300";
  }
  return "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300";
}

function EntityCard({ entity }: { entity: WikiRelatedEntityRow }) {
  const line =
    entity.start_line != null && entity.start_line > 0 ? `:${entity.start_line}` : "";
  const loc = `${entity.file_path}${line}`;

  return (
    <div className="rounded-lg border border-gray-200 bg-gray-50/80 p-3 dark:border-gray-700 dark:bg-gray-900/40">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium text-gray-900 dark:text-gray-100">{entity.name}</span>
        <span
          className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${typeBadgeClass(entity.entity_type)}`}
        >
          {entity.entity_type}
        </span>
        <span className="rounded-md border border-gray-200 bg-white px-2 py-0.5 font-mono text-[10px] text-gray-600 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-400">
          {entity.repository}
        </span>
      </div>
      <p className="mt-1 font-mono text-[11px] text-gray-600 dark:text-gray-400">{loc}</p>
      {entity.signature ? (
        <pre className="mt-2 max-h-24 overflow-auto whitespace-pre-wrap break-all rounded border border-gray-200 bg-white p-2 font-mono text-[11px] text-gray-800 dark:border-gray-700 dark:bg-gray-950 dark:text-gray-200">
          {entity.signature}
        </pre>
      ) : null}
      {entity.business_summary ? (
        <p className="mt-2 text-xs text-gray-600 dark:text-gray-400">{entity.business_summary}</p>
      ) : null}
    </div>
  );
}

type Props = {
  pagePath: string;
  businessId: string;
  repository?: string;
};

export default function EntityCardsPanel({ pagePath, businessId, repository }: Props) {
  const { t } = useI18n();
  const tc = t.wiki.topic_content;
  const [expanded, setExpanded] = useState(false);
  const q = useWikiEntities(pagePath, businessId, repository);

  if (!q.data?.entities?.length && !q.isLoading && !q.isError) {
    return null;
  }

  return (
    <section className="mt-8 rounded-xl border border-gray-200 bg-white shadow-sm dark:border-gray-700 dark:bg-gray-900/50">
      <button
        type="button"
        onClick={() => setExpanded((e) => !e)}
        className="flex w-full items-center gap-2 px-4 py-3 text-left text-sm font-medium text-gray-800 transition-colors hover:bg-gray-50 dark:text-gray-100 dark:hover:bg-gray-800/50"
        aria-expanded={expanded}
      >
        {expanded ? (
          <ChevronDown className="size-4 shrink-0 text-gray-500" aria-hidden />
        ) : (
          <ChevronRight className="size-4 shrink-0 text-gray-500" aria-hidden />
        )}
        <span>{tc.related_entities_heading}</span>
        {q.isLoading ? <Loader2 className="size-4 animate-spin text-gray-400" aria-hidden /> : null}
        {q.isError && !q.isLoading ? (
          <span className="ml-auto text-xs font-normal text-red-500 dark:text-red-400">!</span>
        ) : null}
        {!q.isLoading && !q.isError && q.data?.entities.length ? (
          <span className="ml-auto text-xs font-normal text-gray-500 dark:text-gray-400">
            {q.data.entities.length}
          </span>
        ) : null}
        <span className="sr-only">{expanded ? tc.related_entities_collapse : tc.related_entities_expand}</span>
      </button>
      {expanded && (
        <div className="border-t border-gray-100 px-4 py-3 dark:border-gray-700">
          {q.isLoading && (
            <p className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
              <Loader2 className="size-3.5 animate-spin" aria-hidden />
              {tc.related_entities_loading}
            </p>
          )}
          {q.isError && (
            <p className="text-xs text-red-600 dark:text-red-400">{String(q.error)}</p>
          )}
          {!q.isLoading && !q.isError && q.data && q.data.entities.length === 0 ? (
            <p className="text-xs text-gray-500 dark:text-gray-400">{tc.related_entities_empty}</p>
          ) : null}
          {q.data?.entities.length ? (
            <div className="flex max-h-[min(50vh,420px)] flex-col gap-3 overflow-y-auto pr-1">
              {q.data.entities.map((e) => (
                <EntityCard key={e.uid} entity={e} />
              ))}
            </div>
          ) : null}
        </div>
      )}
    </section>
  );
}
