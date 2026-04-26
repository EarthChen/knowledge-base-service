import { useCallback, useRef, useState, type ReactNode } from "react";
import { MessageSquarePlus } from "lucide-react";

export interface WikiAnnotationRangePayload {
  start: number;
  end: number;
  comment: string;
}

interface WikiAnnotationLayerProps {
  children: ReactNode;
  onAddAnnotation: (range: WikiAnnotationRangePayload) => void;
}

export default function WikiAnnotationLayer({ children, onAddAnnotation }: WikiAnnotationLayerProps) {
  const wrapperRef = useRef<HTMLDivElement>(null);
  const [showInput, setShowInput] = useState(false);
  const [comment, setComment] = useState("");
  const [selection, setSelection] = useState<{ start: number; end: number } | null>(null);

  const handleMouseUp = useCallback(() => {
    const root = wrapperRef.current;
    if (!root) return;

    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || !sel.toString().trim()) {
      return;
    }

    const range = sel.getRangeAt(0);
    if (!root.contains(range.commonAncestorContainer)) {
      return;
    }

    const pre = range.cloneRange();
    pre.selectNodeContents(root);
    pre.setEnd(range.startContainer, range.startOffset);
    const start = pre.toString().length;
    const end = start + range.toString().length;

    setSelection({ start, end });
    setShowInput(true);
  }, []);

  const handleSubmit = () => {
    if (!selection || !comment.trim()) return;
    onAddAnnotation({ start: selection.start, end: selection.end, comment: comment.trim() });
    setShowInput(false);
    setComment("");
    setSelection(null);
    window.getSelection()?.removeAllRanges();
  };

  const handleCancel = () => {
    setShowInput(false);
    setComment("");
    setSelection(null);
    window.getSelection()?.removeAllRanges();
  };

  return (
    <div ref={wrapperRef} onMouseUp={handleMouseUp} className="relative">
      {children}
      {showInput && (
        <div className="absolute right-0 top-0 z-40 w-72 rounded-xl border border-gray-200 bg-white p-3 shadow-lg dark:border-gray-700 dark:bg-gray-900">
          <div className="flex items-center gap-2 text-xs font-semibold text-gray-700 dark:text-gray-300">
            <MessageSquarePlus size={14} />
            Add annotation
          </div>
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="Write a comment..."
            rows={3}
            className="mt-2 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:border-sky-400 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
          />
          <div className="mt-2 flex justify-end gap-2">
            <button
              type="button"
              onClick={handleCancel}
              className="rounded px-3 py-1.5 text-xs text-gray-600 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-800"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSubmit}
              disabled={!comment.trim()}
              className="rounded bg-sky-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-sky-500 disabled:opacity-50"
            >
              Add
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
