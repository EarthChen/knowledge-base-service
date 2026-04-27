/**
 * Search-query helpers for in-result highlighting.
 * CJK: terms are not split in the middle of text — only on Unicode/ASCII whitespace
 * (so e.g. "项目配置" or "漢字" stay single terms; "foo 项目" → two terms).
 */

/** EcmaScript RegExp metacharacters, escaped for use as literal segments in a RegExp. */
export function escapeRegexChars(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Splits a search query into highlight terms: trim, split on whitespace, dedupe (case-insensitive),
 * then longest-first for alternation (so "ab" wins over "a" in "xaby").
 */
export function parseHighlightTerms(query: string): string[] {
  const trimmed = query.trim();
  if (!trimmed) return [];
  // Unicode-aware whitespace; does not break unspaced CJK runs.
  const raw = trimmed.split(/\s+/u).filter((t) => t.length > 0);
  const seen = new Set<string>();
  const out: string[] = [];
  for (const t of raw) {
    const key = t.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(t);
  }
  out.sort((a, b) => b.length - a.length);
  return out;
}
