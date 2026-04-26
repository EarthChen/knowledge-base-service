import type { WikiSearchResult } from "../../hooks/wikiTypes";

type Props = {
  results: WikiSearchResult[];
  onSelect: (path: string) => void;
};

export default function WikiSearchResults({ results, onSelect }: Props) {
  if (results.length === 0) return null;

  return (
    <ul className="max-h-72 overflow-y-auto py-1" role="listbox">
      {results.map((r) => (
        <li key={`${r.page_path}:${r.title}`} role="option">
          <button
            type="button"
            onClick={() => onSelect(r.page_path)}
            className="flex w-full flex-col gap-0.5 px-3 py-2 text-left text-sm transition-colors hover:bg-sky-50 dark:hover:bg-sky-950/50"
          >
            <span className="font-medium text-gray-900 dark:text-gray-100">{r.title}</span>
            <span className="truncate font-mono text-[11px] text-gray-500 dark:text-gray-400">
              {r.page_path}
            </span>
            {r.snippet ? (
              <span className="line-clamp-2 text-xs text-gray-600 dark:text-gray-400">
                {r.snippet}
              </span>
            ) : null}
          </button>
        </li>
      ))}
    </ul>
  );
}
