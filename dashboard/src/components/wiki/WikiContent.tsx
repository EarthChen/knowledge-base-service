import { BookOpen, FolderOpen } from "lucide-react";
import type { WikiPageDetail, WikiSourceLocation } from "../../hooks/wikiTypes";
import MarkdownRenderer from "./MarkdownRenderer";
import WikiBreadcrumbs from "./WikiBreadcrumbs";
import { buildIdeHref, type EditorId } from "./editorLinks";
import { EDITOR_PREF_KEY } from "./SourceLink";

type Props = {
  repository: string;
  pagePath: string;
  detail: WikiPageDetail | undefined;
  isLoading: boolean;
  error: Error | null;
};

function readEditorPref(): EditorId {
  try {
    const v = localStorage.getItem(EDITOR_PREF_KEY);
    if (v === "cursor" || v === "idea" || v === "vscode") return v;
  } catch {
    /* ignore */
  }
  return "cursor";
}

function SourceLocRow({ loc, repository }: { loc: WikiSourceLocation; repository: string }) {
  const editor = readEditorPref();
  const href = buildIdeHref(editor, repository, loc.file_path, loc.start_line);
  return (
    <li className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-sm">
      <code className="rounded bg-gray-100 px-1.5 py-0.5 font-mono text-xs text-gray-800">
        {loc.fqn}
      </code>
      <a
        href={href}
        className="text-sky-700 underline decoration-sky-200 underline-offset-2 hover:text-sky-900"
      >
        {loc.file_path}:{loc.start_line}–{loc.end_line}
      </a>
    </li>
  );
}

export default function WikiContent({
  repository,
  pagePath,
  detail,
  isLoading,
  error,
}: Props) {
  const title =
    detail?.title ??
    (pagePath ? pagePath.split("/").pop() ?? pagePath : "Wiki overview");

  return (
    <div className="flex min-h-0 flex-1 flex-col rounded-xl border border-gray-200 bg-white shadow-sm">
      <header className="border-b border-gray-100 px-5 py-4">
        <WikiBreadcrumbs repository={repository} path={pagePath} />
        <div className="mt-3 flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-sky-50 text-sky-600">
            <BookOpen size={20} aria-hidden />
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-lg font-semibold tracking-tight text-gray-900">
              {title}
            </h2>
            <p className="mt-0.5 truncate font-mono text-xs text-gray-500">
              {pagePath || "Select a page"}
            </p>
          </div>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto px-5 py-6">
        {isLoading && (
          <div className="animate-pulse space-y-3">
            <div className="h-4 w-2/3 rounded bg-gray-100" />
            <div className="h-4 w-full rounded bg-gray-100" />
            <div className="h-4 w-5/6 rounded bg-gray-100" />
          </div>
        )}

        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
            {error.message}
          </div>
        )}

        {!isLoading && !error && detail && (
          <>
            <MarkdownRenderer content={detail.content} />

            {(detail.source_locations?.length ?? 0) > 0 && (
              <section className="mt-10 border-t border-gray-100 pt-8">
                <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-gray-900">
                  <FolderOpen size={16} aria-hidden />
                  Source locations
                </h3>
                <ul className="space-y-2 rounded-lg border border-gray-100 bg-gray-50/80 p-4">
                  {detail.source_locations.map((loc, i) => (
                    <SourceLocRow key={`${loc.file_path}-${loc.start_line}-${i}`} loc={loc} repository={repository} />
                  ))}
                </ul>
              </section>
            )}
          </>
        )}

        {!isLoading && !error && !pagePath && (
          <p className="text-sm text-gray-600">
            Choose a page from the tree, or type a query in wiki search. Expand folders with the
            chevron control.
          </p>
        )}

        {!isLoading && !error && !detail && pagePath && (
          <p className="text-sm text-gray-500">Select a page from the sidebar.</p>
        )}
      </div>
    </div>
  );
}
