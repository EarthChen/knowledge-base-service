import { Fragment } from "react";

function escapeRegexChars(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

type Props = {
  text: string;
  query: string;
  className?: string;
};

/**
 * Highlights whitespace-separated terms from `query` inside `text` (case-insensitive).
 */
export default function HighlightText({ text, query, className }: Props) {
  const terms = query.trim().split(/\s+/).filter((t) => t.length > 0);

  if (!text || terms.length === 0) {
    return <span className={className}>{text}</span>;
  }

  const pattern = terms.map(escapeRegexChars).join("|");
  const re = new RegExp(`(${pattern})`, "gi");
  const parts = text.split(re);

  return (
    <span className={className}>
      {parts.map((part, i) => {
        if (!part) return null;
        const hit = terms.some((t) => t.toLowerCase() === part.toLowerCase());
        return (
          <Fragment key={`h-${i}`}>
            {hit ? (
              <mark className="rounded-sm bg-amber-200/90 px-0.5 text-inherit dark:bg-amber-500/40">
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
