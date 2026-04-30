import { useMemo } from "react";
import MarkdownRenderer from "./MarkdownRenderer";

interface TopicPage {
  title: string;
  content: string;
  path: string;
  page_type: string;
  domain?: string;
  review_status?: string;
}

interface Props {
  page: TopicPage;
  onReviewAction: (action: "approve" | "needs_revision" | "regenerate", notes?: string) => void;
}

const REVIEW_LABELS: Record<string, { text: string; className: string }> = {
  pending_review: {
    text: "待审阅",
    className: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-400",
  },
  approved: {
    text: "已通过",
    className: "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-400",
  },
  needs_revision: {
    text: "需修改",
    className: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400",
  },
  revised: {
    text: "已修订",
    className: "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-400",
  },
};

export default function WikiTopicContent({ page, onReviewAction }: Props) {
  const reviewBadge = useMemo(() => {
    const entry = REVIEW_LABELS[page.review_status ?? ""];
    if (!entry) return null;
    return (
      <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${entry.className}`}>
        {entry.text}
      </span>
    );
  }, [page.review_status]);

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
              通过
            </button>
            <button
              type="button"
              onClick={() => {
                const notes = window.prompt("请输入修改意见:");
                if (notes) onReviewAction("needs_revision", notes);
              }}
              className="rounded-md bg-amber-50 px-2.5 py-1 text-xs font-medium text-amber-700 hover:bg-amber-100 dark:bg-amber-950/40 dark:text-amber-400 dark:hover:bg-amber-900/60"
            >
              标记修改
            </button>
            <button
              type="button"
              onClick={() => onReviewAction("regenerate")}
              className="rounded-md bg-sky-50 px-2.5 py-1 text-xs font-medium text-sky-700 hover:bg-sky-100 dark:bg-sky-950/40 dark:text-sky-400 dark:hover:bg-sky-900/60"
            >
              重新生成
            </button>
          </div>
        </div>
      </header>
      <div className="prose prose-sm max-w-none dark:prose-invert">
        <MarkdownRenderer content={page.content} />
      </div>
    </article>
  );
}
