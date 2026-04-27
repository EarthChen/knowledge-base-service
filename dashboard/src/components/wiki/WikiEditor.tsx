import { useCallback, useMemo, useState } from "react";
import CodeMirror from "@uiw/react-codemirror";
import { markdown } from "@codemirror/lang-markdown";
import { usePatchWikiPage } from "../../hooks/useWikiPageEdit";
import MarkdownRenderer from "./MarkdownRenderer";
import { parseMarkdownHeadings } from "./headingUtils";
import { getErrorMessage } from "../../utils/errorUtils";
import { useI18n } from "../../i18n/context";

export interface WikiEditorProps {
  pageUid: string;
  initialContent: string;
  currentVersion: number;
  businessId?: string;
  wikiLinkParams?: Record<string, string>;
  onClose: () => void;
}

export function WikiEditor({
  pageUid,
  initialContent,
  currentVersion,
  businessId = "",
  wikiLinkParams,
  onClose,
}: WikiEditorProps) {
  const { t } = useI18n();
  const [content, setContent] = useState(initialContent);
  const [editReason, setEditReason] = useState("");
  const [versionMismatchWarning, setVersionMismatchWarning] = useState<string | null>(null);
  const mutation = usePatchWikiPage();

  const previewHeadings = useMemo(() => parseMarkdownHeadings(content), [content]);

  const handleSave = useCallback(() => {
    mutation.mutate(
      { pageUid, content, editReason, expectedVersion: currentVersion },
      {
        onSuccess: (data) => {
          if (data.version_mismatch_warning) {
            setVersionMismatchWarning(data.version_mismatch_warning);
            return;
          }
          onClose();
        },
      },
    );
  }, [pageUid, content, editReason, currentVersion, mutation, onClose]);

  const extensions = useMemo(() => [markdown()], []);

  const errorText = mutation.isError
    ? getErrorMessage(mutation.error, t.common.unexpectedError)
    : null;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex min-h-[min(70vh,800px)] flex-1 gap-2">
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded border border-gray-200 dark:border-gray-700">
          <CodeMirror
            value={content}
            height="100%"
            className="min-h-0 flex-1 overflow-auto text-sm [&_.cm-editor]:min-h-[min(70vh,800px)] [&_.cm-editor]:h-full [&_.cm-scroller]:min-h-[min(70vh,800px)]"
            extensions={extensions}
            onChange={setContent}
          />
        </div>
        <div className="flex min-h-0 flex-1 flex-col overflow-auto rounded border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-950">
          <MarkdownRenderer
            content={content}
            businessId={businessId}
            wikiLinkParams={wikiLinkParams}
            headings={previewHeadings}
          />
        </div>
      </div>

      {versionMismatchWarning ? (
        <div className="mt-2 space-y-2 border-t border-gray-200 pt-2 dark:border-gray-700">
          <p
            className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/60 dark:text-amber-100"
            role="status"
          >
            {versionMismatchWarning}
          </p>
          <div className="flex justify-end">
            <button
              type="button"
              onClick={onClose}
              className="rounded bg-amber-600 px-3 py-1.5 text-sm text-white hover:bg-amber-700"
            >
              {t.wiki.wikiEditorDismiss}
            </button>
          </div>
        </div>
      ) : (
        <div className="mt-2 flex flex-wrap items-center gap-2 border-t border-gray-200 pt-2 dark:border-gray-700">
          <input
            type="text"
            placeholder={t.wiki.wikiEditReasonPlaceholder}
            value={editReason}
            onChange={(e) => setEditReason(e.target.value)}
            className="min-w-0 flex-1 rounded border border-gray-200 bg-white px-2 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-900"
          />
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-gray-200 px-3 py-1.5 text-sm hover:bg-gray-100 dark:border-gray-600 dark:hover:bg-gray-800"
          >
            {t.wiki.wikiEditorCancel}
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={mutation.isPending || content === initialContent}
            className="rounded bg-sky-600 px-3 py-1.5 text-sm text-white hover:bg-sky-700 disabled:opacity-50"
            role="button"
          >
            {mutation.isPending ? t.wiki.wikiEditorSaving : t.wiki.wikiEditorSave}
          </button>
        </div>
      )}

      {errorText ? (
        <p className="mt-1 text-sm text-red-600 dark:text-red-400" role="alert">
          {errorText}
        </p>
      ) : null}
    </div>
  );
}
