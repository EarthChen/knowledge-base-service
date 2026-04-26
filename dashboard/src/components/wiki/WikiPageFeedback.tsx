import { useState } from "react";
import { ThumbsUp, ThumbsDown } from "lucide-react";
import { api } from "../../api/client";

type Props = { pageUid: string; businessId: string };

export default function WikiPageFeedback({ pageUid, businessId }: Props) {
  const [sent, setSent] = useState<"up" | "down" | null>(null);
  const [sending, setSending] = useState(false);

  const sendFeedback = async (rating: "up" | "down") => {
    if (sending) return;
    setSending(true);
    try {
      await api(`/wiki/pages/${encodeURIComponent(pageUid)}/feedback`, {
        method: "POST",
        body: JSON.stringify({ rating, business_id: businessId }),
      });
      setSent(rating);
    } catch {
      // Silently fail — feedback is non-critical
    } finally {
      setSending(false);
    }
  };

  if (sent) {
    return (
      <div className="flex items-center gap-2 text-xs text-gray-400">
        {sent === "up" ? (
          <ThumbsUp className="h-3.5 w-3.5 text-green-500" />
        ) : (
          <ThumbsDown className="h-3.5 w-3.5 text-red-500" />
        )}
        <span>Thanks for your feedback!</span>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-3 text-xs text-gray-500">
      <span>Was this helpful?</span>
      <button
        type="button"
        disabled={sending}
        onClick={() => void sendFeedback("up")}
        title="Helpful"
        aria-label="thumbs up"
        className="rounded p-1 hover:bg-green-50 disabled:opacity-50 dark:hover:bg-green-950/40"
      >
        <ThumbsUp className="h-3.5 w-3.5" />
      </button>
      <button
        type="button"
        disabled={sending}
        onClick={() => void sendFeedback("down")}
        title="Not helpful"
        aria-label="thumbs down"
        className="rounded p-1 hover:bg-red-50 disabled:opacity-50 dark:hover:bg-red-950/40"
      >
        <ThumbsDown className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
