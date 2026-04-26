import {
  useCallback,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { MessageSquarePlus } from "lucide-react";
import { useI18n } from "../../i18n/context";
import type { WikiAnnotation } from "../../hooks/wikiTypes";

export interface WikiAnnotationRangePayload {
  start: number;
  end: number;
  /** Selected plain text; used to re-locate the span after markdown render. */
  selected_text: string;
  comment: string;
}

interface WikiAnnotationLayerProps {
  children: ReactNode;
  onAddAnnotation: (range: WikiAnnotationRangePayload) => void;
  /** Saved annotations to highlight in the rendered markdown body. */
  annotations?: WikiAnnotation[];
  /** When this changes (e.g. page markdown), highlights are recomputed. */
  highlightSourceKey?: string;
}

function domPlainText(root: HTMLElement): string {
  let s = "";
  const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let n: Node | null;
  while ((n = w.nextNode())) {
    s += (n as Text).data;
  }
  return s;
}

function resolveAnnotationSpan(
  plain: string,
  ann: Pick<WikiAnnotation, "text_range_start" | "text_range_end" | "selected_text">,
): { start: number; end: number } | null {
  const needle = ann.selected_text?.trim();
  if (needle) {
    const at = ann.text_range_start;
    if (
      at >= 0 &&
      at + needle.length <= plain.length &&
      plain.slice(at, at + needle.length) === needle
    ) {
      return { start: at, end: at + needle.length };
    }
    let bestIdx = -1;
    let bestDist = Infinity;
    let idx = plain.indexOf(needle);
    while (idx !== -1) {
      const dist = Math.abs(idx - ann.text_range_start);
      if (dist < bestDist) {
        bestDist = dist;
        bestIdx = idx;
      }
      idx = plain.indexOf(needle, idx + 1);
    }
    if (bestIdx !== -1) {
      return { start: bestIdx, end: bestIdx + needle.length };
    }
    return null;
  }
  const start = ann.text_range_start;
  const end = ann.text_range_end;
  if (start >= 0 && end <= plain.length && start < end) {
    return { start, end };
  }
  return null;
}

function unwrapWikiAnnotationMarks(root: HTMLElement) {
  const marks = Array.from(root.querySelectorAll("mark[data-wiki-ann]"));
  for (const mark of marks) {
    const parent = mark.parentNode;
    if (!parent) continue;
    while (mark.firstChild) {
      parent.insertBefore(mark.firstChild, mark);
    }
    parent.removeChild(mark);
  }
  root.normalize();
}

function wrapPlainTextRange(root: HTMLElement, start: number, end: number) {
  if (start >= end) return;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let acc = 0;
  let startNode: Text | null = null;
  let startOff = 0;
  let endNode: Text | null = null;
  let endOff = 0;
  let n: Text | null;
  while ((n = walker.nextNode() as Text | null)) {
    const len = n.length;
    if (!startNode && acc + len > start) {
      startNode = n;
      startOff = start - acc;
    }
    if (startNode && acc + len >= end) {
      endNode = n;
      endOff = end - acc;
      break;
    }
    acc += len;
  }
  if (!startNode || !endNode) return;
  const r = document.createRange();
  r.setStart(startNode, startOff);
  r.setEnd(endNode, endOff);
  const mark = document.createElement("mark");
  mark.setAttribute("data-wiki-ann", "1");
  mark.className =
    "rounded-sm bg-amber-100/90 px-0.5 text-inherit dark:bg-amber-900/40";
  r.surroundContents(mark);
}

export default function WikiAnnotationLayer({
  children,
  onAddAnnotation,
  annotations,
  highlightSourceKey,
}: WikiAnnotationLayerProps) {
  const { t } = useI18n();
  const wrapperRef = useRef<HTMLDivElement>(null);
  const [showInput, setShowInput] = useState(false);
  const [comment, setComment] = useState("");
  const [selection, setSelection] = useState<{
    start: number;
    end: number;
    selectedText: string;
  } | null>(null);

  useLayoutEffect(() => {
    const root = wrapperRef.current;
    if (!root) return;
    unwrapWikiAnnotationMarks(root);
    if (!annotations?.length) return;
    const plain = domPlainText(root);
    const resolved: { start: number; end: number }[] = [];
    for (const ann of annotations) {
      const span = resolveAnnotationSpan(plain, ann);
      if (span) resolved.push(span);
    }
    resolved.sort((a, b) => b.start - a.start);
    for (const { start, end } of resolved) {
      try {
        wrapPlainTextRange(root, start, end);
      } catch {
        /* surroundContents fails when range splits non-text structure */
      }
    }
  }, [annotations, highlightSourceKey]);

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
    const selectedText = range.toString();
    const end = start + selectedText.length;

    setSelection({ start, end, selectedText });
    setShowInput(true);
  }, []);

  const handleSubmit = () => {
    if (!selection || !comment.trim()) return;
    onAddAnnotation({
      start: selection.start,
      end: selection.end,
      selected_text: selection.selectedText,
      comment: comment.trim(),
    });
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
            {t.wiki.annotationAdd}
          </div>
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder={t.wiki.annotationCommentPlaceholder}
            rows={3}
            className="mt-2 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:border-sky-400 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
          />
          <div className="mt-2 flex justify-end gap-2">
            <button
              type="button"
              onClick={handleCancel}
              className="rounded px-3 py-1.5 text-xs text-gray-600 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-800"
            >
              {t.wiki.annotationCancel}
            </button>
            <button
              type="button"
              onClick={handleSubmit}
              disabled={!comment.trim()}
              className="rounded bg-sky-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-sky-500 disabled:opacity-50"
            >
              {t.wiki.annotationSubmit}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
