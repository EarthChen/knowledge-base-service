export interface ParsedWikilink {
  raw: string;
  path: string;
  label: string;
}

const WIKILINK_RE = /\[\[([^\]|]+?)(?:\|([^\]]+?))?\]\]/g;

export function parseWikilinks(text: string): ParsedWikilink[] {
  const results: ParsedWikilink[] = [];
  let match: RegExpExecArray | null;
  while ((match = WIKILINK_RE.exec(text)) !== null) {
    const path = match[1].trim();
    const label = match[2]?.trim() || path.split("/").pop() || path;
    results.push({ raw: match[0], path, label });
  }
  return results;
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export function replaceWikilinksWithHtml(markdown: string): string {
  return markdown.replace(WIKILINK_RE, (_match, path: string, label?: string) => {
    const trimPath = path.trim();
    const trimLabel = label?.trim() || trimPath.split("/").pop() || trimPath;
    return `<wikilink data-path="${encodeURIComponent(trimPath)}">${escapeHtml(trimLabel)}</wikilink>`;
  });
}
