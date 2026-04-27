import type { WikiSearchResult } from "../../hooks/wikiTypes";
import HighlightText from "../HighlightText";

type Props = {
  results: WikiSearchResult[];
  onSelect: (path: string) => void;
  listboxId?: string;
  activeIndex: number;
  /** Whitespace / phrase segments from the active search, used to mark matches. */
  highlightQuery?: string;
};

export function wikiSearchOptionId(listboxId: string | undefined, index: number): string {
  const base = listboxId ?? "wiki-search-listbox";
  return `${base}-opt-${index}`;
}

export default function WikiSearchResults({
  results,
  onSelect,
  listboxId,
  activeIndex,
  highlightQuery = "",
}: Props) {
  if (results.length === 0) return null;

  const hq = highlightQuery.trim();
  const showMark = Boolean(hq);

  return (
    <ul
      id={listboxId}
      className="max-h-72 overflow-y-auto py-1"
      role="listbox"
    >
      {results.map((r, index) => (
        <li
          key={`${r.page_path}:${r.title}`}
          id={wikiSearchOptionId(listboxId, index)}
          role="option"
          aria-selected={activeIndex === index}
        >
          <button
            type="button"
            tabIndex={-1}
            onClick={() => onSelect(r.page_path)}
            className="flex w-full flex-col gap-0.5 px-3 py-2 text-left text-sm transition-colors hover:bg-sky-50 dark:hover:bg-sky-950/50"
          >
            <span className="font-medium text-gray-900 dark:text-gray-100">
              {showMark ? <HighlightText text={r.title} query={hq} /> : r.title}
            </span>
            <span className="truncate font-mono text-[11px] text-gray-500 dark:text-gray-400">
              {showMark ? <HighlightText text={r.page_path} query={hq} /> : r.page_path}
            </span>
            {r.snippet ? (
              <span className="line-clamp-2 text-xs text-gray-600 dark:text-gray-400">
                {showMark ? <HighlightText text={r.snippet} query={hq} /> : r.snippet}
              </span>
            ) : null}
          </button>
        </li>
      ))}
    </ul>
  );
}
