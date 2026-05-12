import { useMemo, useState } from "react";
import MarkdownRenderer from "./MarkdownRenderer";
import EntityCardsPanel from "./EntityCardsPanel";
import WikiSourceLocRow from "./WikiSourceLocRow";
import { useI18n } from "../../i18n/context";
import type { WikiSourceLocation } from "../../hooks/wikiTypes";

interface TopicPage {
  title: string;
  content: string;
  path: string;
  page_type: string;
  domain?: string;
  review_status?: string;
  source_locations?: WikiSourceLocation[];
}

interface Props {
  page: TopicPage | null | undefined;
  businessId?: string;
  repository?: string;
  wikiLinkParams?: Record<string, string>;
  onReviewAction: (action: "approve" | "needs_revision" | "regenerate", notes?: string) => void;
}

const REVIEW_CLASSNAMES: Record<string, string> = {
  pending_review: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-400",
  approved: "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-400",
  needs_revision: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400",
  revised: "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-400",
};

function reviewBadgeText(
  status: string | undefined,
  tc: {
    pending_review: string;
    approved: string;
    needs_revision: string;
    revised: string;
  },
): string | null {
  switch (status) {
    case "pending_review":
      return tc.pending_review;
    case "approved":
      return tc.approved;
    case "needs_revision":
      return tc.needs_revision;
    case "revised":
      return tc.revised;
    default:
      return null;
  }
}

export default function WikiTopicContent({
  page,
  businessId,
  repository,
  wikiLinkParams,
  onReviewAction,
}: Props) {
  const { t } = useI18n();
  const tc = t.wiki.topic_content;
  const [showNotesInput, setShowNotesInput] = useState(false);
  const [notes, setNotes] = useState("");

  const reviewBadge = useMemo(() => {
    if (!page) return null;
    const text = reviewBadgeText(page.review_status, tc);
    if (!text) return null;
    const className = REVIEW_CLASSNAMES[page.review_status ?? ""];
    if (!className) return null;
    return (
      <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${className}`}>
        {text}
      </span>
    );
  }, [page, tc]);

  if (!page) {
    return (
      <div className="flex h-48 items-center justify-center rounded-lg border border-dashed border-gray-300 text-sm text-gray-400 dark:border-gray-600 dark:text-gray-500">
        {tc.select_page}
      </div>
    );
  }

  return (
    <article className="space-y-6">
      <header className="flex items-center justify-between border-b border-gray-200 pb-4 dark:border-gray-700">
        <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100">{page.title}</h1>
        <div className="flex items-center gap-3">
          {reviewBadge}
          <div className="flex gap-1.5">
            <button
              type="button"
              onClick={() => onReviewAction("approve")}
              className="rounded-md bg-green-50 px-2.5 py-1 text-xs font-medium text-green-700 hover:bg-green-100 dark:bg-green-950/40 dark:text-green-400 dark:hover:bg-green-900/60"
            >
              {tc.approve}
            </button>
            {showNotesInput ? (
              <div className="flex items-center gap-1">
                <input
                  type="text"
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder={tc.revision_placeholder}
                  className="w-48 rounded-md border border-gray-300 px-2 py-1 text-xs dark:border-gray-600 dark:bg-gray-800"
                  autoFocus
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && notes.trim()) {
                      onReviewAction("needs_revision", notes.trim());
                      setNotes("");
                      setShowNotesInput(false);
                    }
                    if (e.key === "Escape") {
                      setShowNotesInput(false);
                      setNotes("");
                    }
                  }}
                />
                <button
                  type="button"
                  onClick={() => {
                    if (notes.trim()) {
                      onReviewAction("needs_revision", notes.trim());
                      setNotes("");
                      setShowNotesInput(false);
                    }
                  }}
                  className="rounded-md bg-amber-500 px-2 py-1 text-xs text-white hover:bg-amber-400"
                >
                  {tc.submit}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setShowNotesInput(false);
                    setNotes("");
                  }}
                  className="text-xs text-gray-400 hover:text-gray-600"
                >
                  {tc.cancel}
                </button>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => setShowNotesInput(true)}
                className="rounded-md bg-amber-50 px-2.5 py-1 text-xs font-medium text-amber-700 hover:bg-amber-100 dark:bg-amber-950/40 dark:text-amber-400 dark:hover:bg-amber-900/60"
              >
                {tc.mark_revision}
              </button>
            )}
            <button
              type="button"
              onClick={() => onReviewAction("regenerate")}
              className="rounded-md bg-sky-50 px-2.5 py-1 text-xs font-medium text-sky-700 hover:bg-sky-100 dark:bg-sky-950/40 dark:text-sky-400 dark:hover:bg-sky-900/60"
            >
              {tc.regenerate}
            </button>
          </div>
        </div>
      </header>
      <div className="prose prose-sm max-w-none dark:prose-invert">
        <MarkdownRenderer
          content={page.content}
          businessId={businessId}
          wikiLinkParams={wikiLinkParams}
        />
      </div>
      {businessId ? (
        <EntityCardsPanel pagePath={page.path} businessId={businessId} repository={repository} />
      ) : null}
      {repository && page.source_locations?.length ? (
        <WikiSourceLocRow repository={repository} sourceLocations={page.source_locations} />
      ) : null}
    </article>
  );
}
