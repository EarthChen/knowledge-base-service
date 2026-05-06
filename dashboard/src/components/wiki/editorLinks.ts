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

const SOURCE_RE_HASH =
  /^source:\/\/([^/]+)\/(.+?)#L(\d+)$/;
const SOURCE_RE_COLON =
  /^source:\/\/([^/]+)\/(.+?):(\d+)$/;
const SOURCE_RE_NO_LINE =
  /^source:\/\/([^/]+)\/(.+)$/;

export function parseSourceProtocol(href: string): {
  repository: string;
  filePath: string;
  line: number;
} | null {
  const m1 = href.match(SOURCE_RE_HASH);
  if (m1) return { repository: decodeURIComponent(m1[1]), filePath: decodeURIComponent(m1[2]), line: parseInt(m1[3], 10) };
  const m2 = href.match(SOURCE_RE_COLON);
  if (m2) return { repository: decodeURIComponent(m2[1]), filePath: decodeURIComponent(m2[2]), line: parseInt(m2[3], 10) };
  const m3 = href.match(SOURCE_RE_NO_LINE);
  if (m3) return { repository: decodeURIComponent(m3[1]), filePath: decodeURIComponent(m3[2]), line: 1 };
  return null;
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
