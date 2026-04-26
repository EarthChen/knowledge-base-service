import type { WikiSourceLocation } from "../../hooks/wikiTypes";
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

export default function SourceLocRow({ loc, repository }: { loc: WikiSourceLocation; repository: string }) {
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
