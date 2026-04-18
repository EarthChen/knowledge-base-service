import { ExternalLink } from "lucide-react";
import {
  buildIdeHref,
  getWikiLocalRoot,
  parseSourceProtocol,
  type EditorId,
} from "./editorLinks";

const EDITOR_PREF_KEY = "wiki-preferred-editor";

function readEditorPref(): EditorId {
  try {
    const v = localStorage.getItem(EDITOR_PREF_KEY);
    if (v === "cursor" || v === "idea" || v === "vscode") return v;
  } catch {
    /* ignore */
  }
  return "cursor";
}

type Props = {
  href: string;
  children?: React.ReactNode;
  className?: string;
};

export default function SourceLink({ href, children, className }: Props) {
  const parsed = parseSourceProtocol(href);
  if (!parsed) {
    return (
      <a href={href} className={className}>
        {children}
      </a>
    );
  }

  const editor = readEditorPref();
  const ideHref = buildIdeHref(editor, parsed.repository, parsed.filePath, parsed.line);

  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      <a
        href={ideHref}
        className={`font-medium text-sky-700 underline decoration-sky-300 underline-offset-2 hover:text-sky-900 ${className ?? ""}`}
        title={`Open in ${editor} (${parsed.filePath}:${parsed.line})`}
      >
        {children}
        <ExternalLink className="ml-0.5 inline size-3 opacity-70" aria-hidden />
      </a>
      {!getWikiLocalRoot(parsed.repository) && (
        <span
          className="text-[10px] text-amber-700"
          title="Set a local clone path in the wiki toolbar so IDE links resolve to absolute files."
        >
          set root
        </span>
      )}
    </span>
  );
}

export { EDITOR_PREF_KEY, readEditorPref };
