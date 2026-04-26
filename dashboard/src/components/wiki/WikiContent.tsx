import ErrorBoundary from "../ErrorBoundary";
import { BookOpen } from "lucide-react";
import type { WikiPageDetail } from "../../hooks/wikiTypes";
import { useWikiAnnotations } from "../../hooks/useWikiAnnotations";
import MarkdownRenderer from "./MarkdownRenderer";
import WikiAnnotationLayer from "./WikiAnnotationLayer";
import WikiAnnotationSidebar from "./WikiAnnotationSidebar";
import WikiEditButton from "./WikiEditButton";
import WikiStaleAlert from "./WikiStaleAlert";
import WikiSuggestedQuestions from "./WikiSuggestedQuestions";
import WikiPageFeedback from "./WikiPageFeedback";
import TableOfContents from "./TableOfContents";
import WikiBreadcrumbs from "./WikiBreadcrumbs";
import { parseMarkdownHeadings, type ParsedHeading } from "./headingUtils";
import { getErrorMessage } from "../../utils/errorUtils";
import WikiCallChainSection from "./WikiCallChainSection";
import MobileTocBar from "./MobileTocBar";
import WikiSourceLocRow from "./WikiSourceLocRow";
import { WikiVersionPicker } from "./WikiVersionPicker";
import { useI18n } from "../../i18n/context";
import { useToast } from "../Toast";

type Props = {
  repository: string;
  businessId: string;
  pagePath: string;
  detail: WikiPageDetail | undefined;
  isLoading: boolean;
  error: Error | null;
  wikiLinkParams?: Record<string, string>;
  onAskQuestion?: (question: string) => void;
};

function formatGeneratedAt(iso: string | null | undefined, locale: string): string | null {
  if (!iso || !String(iso).trim()) return null;
  try {
    return new Date(iso).toLocaleString(locale === "zh" ? "zh-CN" : undefined);
  } catch {
    return iso;
  }
}

function parseSuggestedQuestions(raw: string | undefined): string[] {
  if (!raw?.trim()) return [];
  try {
    const v = JSON.parse(raw) as unknown;
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}

export default function WikiContent({
  repository,
  businessId,
  pagePath,
  detail,
  isLoading,
  error,
  wikiLinkParams,
  onAskQuestion,
}: Props) {
  const { locale, t } = useI18n();
  const { toast } = useToast();
  const title =
    detail?.title ??
    (pagePath ? pagePath.split("/").pop() ?? pagePath : t.wiki.overviewTitle);
  const generatedLabel = t.wiki.generated;
  const generatedAt = formatGeneratedAt(detail?.generated_at, locale);

  const tocItems: ParsedHeading[] = detail?.content ? parseMarkdownHeadings(detail.content) : [];
  const showToc = tocItems.length >= 3;
  const pageUid = detail?.context?.uid?.trim() ?? "";
  const annotationsQuery = useWikiAnnotations(businessId, pageUid);

  return (
    <div className="flex min-h-0 flex-1 flex-col rounded-xl border border-gray-200 bg-white shadow-sm dark:border-gray-700 dark:bg-gray-900">
      <header className="border-b border-gray-100 px-5 py-4 dark:border-gray-700">
        <WikiBreadcrumbs repository={repository} path={pagePath} linkParams={wikiLinkParams} />
        <div className="mt-3 flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-sky-50 text-sky-600 dark:bg-sky-950 dark:text-sky-400">
            <BookOpen size={20} aria-hidden />
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-lg font-semibold tracking-tight text-gray-900 dark:text-gray-100">
              {title}
            </h2>
            <p className="mt-0.5 truncate font-mono text-xs text-gray-500 dark:text-gray-400">
              {pagePath || t.wiki.selectPage}
            </p>
            {generatedAt && (
              <p className="mt-1 text-xs text-gray-400 dark:text-gray-500">
                {generatedLabel}:{" "}
                <span className="font-mono text-gray-600 dark:text-gray-400">{generatedAt}</span>
              </p>
            )}
            {detail?.context?.importance_tier && (
              <span
                className={`mt-1 inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
                  detail.context.importance_tier === "core"
                    ? "bg-sky-100 text-sky-800 dark:bg-sky-900/50 dark:text-sky-300"
                    : detail.context.importance_tier === "standard"
                      ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-300"
                      : "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400"
                }`}
              >
                {detail.context.importance_tier}
              </span>
            )}
            <div className="mt-2 flex flex-wrap items-center gap-2">
              {detail?.context?.version ? (
                <WikiVersionPicker
                  key={`${pagePath}:${pageUid}`}
                  businessId={businessId}
                  pageUid={pageUid}
                  version={detail.context.version}
                  generatedAt={detail?.generated_at || ""}
                />
              ) : null}
              <WikiEditButton
                gitRemoteUrl={detail?.context?.git_remote_url}
                branch={detail?.context?.git_branch}
                exportPath={detail?.context?.export_path}
              />
            </div>
          </div>
        </div>
      </header>

      {detail?.generated_at && generatedAt && detail.context?.is_stale === "true" && (
        <div className="px-5 pt-3">
          <WikiStaleAlert generatedAtLabel={generatedAt} isStale />
        </div>
      )}

      <div className="flex min-h-0 flex-1 flex-col lg:flex-row lg:items-start">
        {showToc && detail?.content ? (
          <MobileTocBar
            key={`${pagePath}\0${repository}`}
            content={detail.content}
            parsedHeadings={tocItems}
            heading={t.wiki.tocHeading}
          />
        ) : null}
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-6">
        {isLoading && (
          <div className="animate-pulse space-y-3">
            <div className="h-4 w-2/3 rounded bg-gray-100 dark:bg-gray-800" />
            <div className="h-4 w-full rounded bg-gray-100 dark:bg-gray-800" />
            <div className="h-4 w-5/6 rounded bg-gray-100 dark:bg-gray-800" />
          </div>
        )}

        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/60 dark:text-red-200">
            {error.message}
          </div>
        )}

        {!isLoading && !error && detail && (
          <>
            <div className="flex flex-col gap-4 lg:flex-row lg:items-start">
              <div className="min-w-0 flex-1">
                {pageUid ? (
                  <WikiAnnotationLayer
                    annotations={annotationsQuery.data ?? []}
                    highlightSourceKey={detail.content}
                    onAddAnnotation={({ start, end, comment, selected_text }) => {
                      annotationsQuery.create.mutate(
                        {
                          text_range_start: start,
                          text_range_end: end,
                          selected_text,
                          comment,
                          author: "viewer",
                        },
                        {
                          onError: (e) => {
                            toast(
                              "error",
                              getErrorMessage(e, t.common.unexpectedError) || t.wiki.annotationSaveFailed,
                            );
                          },
                        },
                      );
                    }}
                  >
                    <ErrorBoundary fallbackLabel="Content rendering error">
                      <MarkdownRenderer
                        content={detail.content}
                        businessId={businessId}
                        wikiLinkParams={wikiLinkParams}
                        headings={tocItems}
                      />
                    </ErrorBoundary>
                  </WikiAnnotationLayer>
                ) : (
                  <ErrorBoundary fallbackLabel="Content rendering error">
                    <MarkdownRenderer
                      content={detail.content}
                      businessId={businessId}
                      wikiLinkParams={wikiLinkParams}
                      headings={tocItems}
                    />
                  </ErrorBoundary>
                )}
              </div>
              {pageUid ? (
                <aside className="shrink-0 rounded-xl border border-gray-100 bg-gray-50/50 dark:border-gray-800 dark:bg-gray-900/40 lg:w-72">
                  <h4 className="border-b border-gray-100 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-gray-600 dark:border-gray-800 dark:text-gray-400">
                    {t.wiki.annotationsTitle}
                  </h4>
                  <WikiAnnotationSidebar
                    annotations={annotationsQuery.data ?? []}
                    onDelete={(id) =>
                      annotationsQuery.remove.mutate(id, {
                        onError: (e) => {
                          toast(
                            "error",
                            getErrorMessage(e, t.common.unexpectedError) || t.wiki.annotationDeleteFailed,
                          );
                        },
                      })
                    }
                    isDeleting={annotationsQuery.remove.isPending}
                  />
                </aside>
              ) : null}
            </div>

            <WikiSourceLocRow repository={repository} sourceLocations={detail.source_locations ?? []} />

            {detail && (
              <WikiCallChainSection repository={repository} detail={detail} wikiLinkParams={wikiLinkParams} />
            )}

            <WikiSuggestedQuestions
              questions={parseSuggestedQuestions(detail.context?.suggested_questions)}
              onAskQuestion={onAskQuestion}
            />
            {pageUid ? (
              <div className="mt-6">
                <WikiPageFeedback pageUid={pageUid} businessId={businessId} />
              </div>
            ) : null}
          </>
        )}

        {!isLoading && !error && !pagePath && (
          <p className="text-sm text-gray-600 dark:text-gray-400">{t.wiki.choosePageHint}</p>
        )}

        {!isLoading && !error && !detail && pagePath && (
          <p className="text-sm text-gray-500 dark:text-gray-400">{t.wiki.selectPageFromSidebar}</p>
        )}
        </div>

        {showToc && detail?.content && (
          <aside className="hidden shrink-0 border-t border-gray-100 px-5 py-6 dark:border-gray-700 lg:block lg:w-56 lg:border-l lg:border-t-0 xl:w-60">
            <TableOfContents content={detail.content} parsedHeadings={tocItems} />
          </aside>
        )}
      </div>
    </div>
  );
}
