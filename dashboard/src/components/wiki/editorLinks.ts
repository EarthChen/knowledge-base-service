/** IDE deep-link templates for opening source files at a line. */

export type EditorId = "vscode" | "cursor" | "idea";

export const editorTemplates: Record<
  EditorId,
  (path: string, line: number) => string
> = {
  vscode: (p, l) => `vscode://file/${p}:${l}`,
  cursor: (p, l) => `cursor://file/${p}:${l}`,
  idea: (p, l) => `idea://open?file=${encodeURIComponent(p)}&line=${l}`,
};

const SOURCE_RE =
  /^source:\/\/([^/]+)\/(.+?)#L(\d+)$/;

export function parseSourceProtocol(href: string): {
  repository: string;
  filePath: string;
  line: number;
} | null {
  const m = href.match(SOURCE_RE);
  if (!m) return null;
  return {
    repository: decodeURIComponent(m[1]),
    filePath: decodeURIComponent(m[2]),
    line: parseInt(m[3], 10),
  };
}

export function wikiLocalRootKey(repository: string): string {
  return `wiki-local-root:${repository}`;
}

export function getWikiLocalRoot(repository: string): string {
  try {
    return localStorage.getItem(wikiLocalRootKey(repository)) ?? "";
  } catch {
    return "";
  }
}

export function buildIdeHref(
  editor: EditorId,
  repository: string,
  filePath: string,
  line: number,
): string {
  const root = getWikiLocalRoot(repository).replace(/\/$/, "");
  const abs = root ? `${root}/${filePath}` : filePath;
  const fn = editorTemplates[editor];
  return fn ? fn(abs, line) : editorTemplates.vscode(abs, line);
}
