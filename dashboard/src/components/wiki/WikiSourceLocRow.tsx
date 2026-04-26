import { FolderOpen } from "lucide-react";
import type { WikiSourceLocation } from "../../hooks/wikiTypes";
import { useI18n } from "../../i18n/context";
import { buildIdeHref, type EditorId } from "./editorLinks";
import { EDITOR_PREF_KEY } from "./SourceLink";

function readEditorPref(): EditorId {
  try {
    const v = localStorage.getItem(EDITOR_PREF_KEY);
    if (v === "cursor" || v === "idea" || v === "vscode") return v;
  } catch {
    /* ignore */
  }
  return "cursor";
}

function SourceLocationItem({ loc, repository }: { loc: WikiSourceLocation; repository: string }) {
  const editor = readEditorPref();
  const href = buildIdeHref(editor, repository, loc.file_path, loc.start_line);
  return (
    <li className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-sm">
      <code className="rounded bg-gray-100 px-1.5 py-0.5 font-mono text-xs text-gray-800 dark:bg-gray-800 dark:text-gray-200">
        {loc.fqn}
      </code>
      <a
        href={href}
        className="text-sky-700 underline decoration-sky-200 underline-offset-2 hover:text-sky-900 dark:text-sky-400 dark:decoration-sky-800 dark:hover:text-sky-300"
      >
        {loc.file_path}:{loc.start_line}–{loc.end_line}
      </a>
    </li>
  );
}

type Props = {
  repository: string;
  sourceLocations: WikiSourceLocation[];
};

export default function WikiSourceLocRow({ repository, sourceLocations }: Props) {
  const { t } = useI18n();
  if (!sourceLocations?.length) return null;

  return (
    <section className="mt-10 border-t border-gray-100 pt-8">
      <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-gray-900 dark:text-gray-100">
        <FolderOpen size={16} aria-hidden />
        {t.wiki.sourceLocations}
      </h3>
      <ul className="space-y-2 rounded-lg border border-gray-100 bg-gray-50/80 p-4 dark:border-gray-700 dark:bg-gray-800/80">
        {sourceLocations.map((loc, i) => (
          <SourceLocationItem key={`${loc.file_path}-${loc.start_line}-${i}`} loc={loc} repository={repository} />
        ))}
      </ul>
    </section>
  );
}
