import { Fragment } from "react";
import { parseHighlightTerms, escapeRegexChars } from "../utils/highlightTerms";

type Props = {
  text: string;
  query: string;
  className?: string;
};

/**
 * Highlights whitespace-separated terms from `query` inside `text` (case-insensitive).
 * CJK: only splits the query on whitespace; unspaced phrases stay one term. Regex metacharacters
 * in the query are escaped. Longer terms match first (e.g. "foobar" before "foo").
 */
export default function HighlightText({ text, query, className }: Props) {
  const terms = parseHighlightTerms(query);

  if (!text || terms.length === 0) {
    return <span className={className}>{text}</span>;
  }

  const pattern = terms.map(escapeRegexChars).join("|");
  const re = new RegExp(`(${pattern})`, "giu");
  const parts = text.split(re);

  return (
    <span className={className}>
      {parts.map((part, i) => {
        if (!part) return null;
        const hit = terms.some((t) => t.toLowerCase() === part.toLowerCase());
        return (
          <Fragment key={`h-${i}`}>
            {hit ? (
              <mark className="rounded-sm bg-amber-200/90 px-0.5 font-semibold text-inherit underline decoration-amber-600/50 underline-offset-2 dark:bg-amber-500/40 dark:decoration-amber-300/40">
                {part}
              </mark>
            ) : (
              part
            )}
          </Fragment>
        );
      })}
    </span>
  );
}
