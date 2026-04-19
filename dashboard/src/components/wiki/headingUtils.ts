/** GitHub-style slug for heading anchors (stable + duplicate suffixes). */

export function slugifyHeading(text: string): string {
  const s = text
    .trim()
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, "-")
    .replace(/^-+|-+$/gu, "");
  return s || "section";
}

export type ParsedHeading = {
  level: number;
  text: string;
  id: string;
};

/** Parse ATX headings (h1–h3) in document order; ids match rendered markdown headings. */
export function parseMarkdownHeadings(markdown: string): ParsedHeading[] {
  const lines = markdown.split(/\r?\n/);
  const counts = new Map<string, number>();
  const result: ParsedHeading[] = [];

  for (const line of lines) {
    const trimmed = line.trimStart();
    const m = /^(#{1,3})\s+(.+)$/.exec(trimmed);
    if (!m) continue;

    const level = m[1].length;
    const rawText = m[2].replace(/\s+#+\s*$/, "").trim();
    if (!rawText) continue;

    const base = slugifyHeading(rawText);
    const n = (counts.get(base) ?? 0) + 1;
    counts.set(base, n);
    const id = n === 1 ? base : `${base}-${n}`;

    result.push({ level, text: rawText, id });
  }

  return result;
}
