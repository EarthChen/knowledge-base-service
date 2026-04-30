import { useState } from "react";

interface Props {
  pagePath: string;
  currentStatus: string;
  onStatusChange: (pagePath: string, status: string, notes: string) => void;
  onRegenerate: (pagePath: string) => void;
}

const STATUS_STYLES: Record<string, string> = {
  pending_review: "border-amber-300 bg-amber-50 dark:border-amber-700 dark:bg-amber-950/30",
  approved: "border-green-300 bg-green-50 dark:border-green-700 dark:bg-green-950/30",
  needs_revision: "border-red-300 bg-red-50 dark:border-red-700 dark:bg-red-950/30",
  revised: "border-blue-300 bg-blue-50 dark:border-blue-700 dark:bg-blue-950/30",
};

export default function WikiPageReviewBar({
  pagePath,
  currentStatus,
  onStatusChange,
  onRegenerate,
}: Props) {
  const [showNotes, setShowNotes] = useState(false);
  const [notesText, setNotesText] = useState("");

  return (
    <div
      className={`flex items-center gap-2 rounded-lg border p-2 text-xs ${STATUS_STYLES[currentStatus] ?? "border-gray-200"}`}
    >
      <button
        type="button"
        onClick={() => onStatusChange(pagePath, "approved", "")}
        className="rounded-md bg-green-600 px-2 py-0.5 text-white hover:bg-green-500"
        title="通过"
      >
        ✓
      </button>
      <button
        type="button"
        onClick={() => onStatusChange(pagePath, "needs_revision", "")}
        className="rounded-md bg-red-500 px-2 py-0.5 text-white hover:bg-red-400"
        title="需修改"
      >
        ✗
      </button>
      {showNotes ? (
        <div className="flex items-center gap-1">
          <input
            type="text"
            value={notesText}
            onChange={(e) => setNotesText(e.target.value)}
            placeholder="审阅意见..."
            className="w-36 rounded-md border border-gray-300 px-1.5 py-0.5 text-xs dark:border-gray-600 dark:bg-gray-800"
            autoFocus
            onKeyDown={(e) => {
              if (e.key === "Enter" && notesText.trim()) {
                const text = notesText.trim();
                setNotesText("");
                setShowNotes(false);
                onStatusChange(pagePath, "needs_revision", text);
              }
              if (e.key === "Escape") {
                setShowNotes(false);
                setNotesText("");
              }
            }}
          />
          <button
            type="button"
            onClick={() => {
              if (notesText.trim()) {
                const text = notesText.trim();
                setNotesText("");
                setShowNotes(false);
                onStatusChange(pagePath, "needs_revision", text);
              }
            }}
            className="rounded-md bg-amber-500 px-1.5 py-0.5 text-xs text-white"
          >
            确定
          </button>
          <button
            type="button"
            onClick={() => {
              setShowNotes(false);
              setNotesText("");
            }}
            className="text-xs text-gray-400"
          >
            ✕
          </button>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setShowNotes(true)}
          className="rounded-md bg-amber-500 px-2 py-0.5 text-white hover:bg-amber-400"
          title="添加意见"
        >
          📝
        </button>
      )}
      <button
        type="button"
        onClick={() => onRegenerate(pagePath)}
        className="ml-auto rounded-md bg-sky-600 px-2 py-0.5 text-white hover:bg-sky-500"
      >
        重新生成
      </button>
    </div>
  );
}
