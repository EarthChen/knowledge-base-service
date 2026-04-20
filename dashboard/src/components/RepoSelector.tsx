import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { ChevronDown, X } from "lucide-react";

export type RepoSelectorLabels = {
  allRepos: string;
  addRepo: string;
  filterPlaceholder: string;
  /** Use {count} */
  selectedCount: string;
  removeRepo: string;
  noMatches: string;
};

type Props = {
  options: string[];
  /** Empty array = search all repositories. */
  selected: string[];
  onChange: (next: string[]) => void;
  labels: RepoSelectorLabels;
  /** Accessible label for the control group */
  groupLabel: string;
};

export default function RepoSelector({ options, selected, onChange, labels, groupLabel }: Props) {
  const listId = useId();
  const triggerId = useId();
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);

  const allMode = selected.length === 0;

  const filteredOptions = useMemo(() => {
    const q = filter.trim().toLowerCase();
    const selectedSet = new Set(selected);
    return options.filter((r) => {
      if (selectedSet.has(r)) return false;
      if (!q) return true;
      return r.toLowerCase().includes(q);
    });
  }, [options, selected, filter]);

  useEffect(() => {
    if (!open) return;
    function onDocMouseDown(e: MouseEvent) {
      const el = rootRef.current;
      if (!el || el.contains(e.target as Node)) return;
      setOpen(false);
      setFilter("");
    }
    document.addEventListener("mousedown", onDocMouseDown);
    return () => document.removeEventListener("mousedown", onDocMouseDown);
  }, [open]);

  const removeRepo = useCallback(
    (repo: string) => {
      onChange(selected.filter((r) => r !== repo));
    },
    [onChange, selected],
  );

  const addRepo = useCallback(
    (repo: string) => {
      if (selected.includes(repo)) return;
      onChange([...selected, repo]);
      setFilter("");
    },
    [onChange, selected],
  );

  const setAllRepos = useCallback(() => {
    onChange([]);
    setOpen(false);
    setFilter("");
  }, [onChange]);

  return (
    <div ref={rootRef} className="flex min-w-0 max-w-full flex-col gap-2">
      <span className="sr-only">{groupLabel}</span>
      <div className="flex min-w-0 flex-wrap items-center gap-1.5">
        <button
          type="button"
          onClick={setAllRepos}
          className={`shrink-0 rounded-full border px-2.5 py-1 text-[11px] font-medium transition-colors ${
            allMode
              ? "border-purple-300 bg-purple-100 text-purple-800 dark:border-purple-700 dark:bg-purple-950/70 dark:text-purple-200"
              : "border-gray-200 bg-gray-50 text-gray-600 hover:border-gray-300 hover:bg-gray-100 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300 dark:hover:border-gray-500 dark:hover:bg-gray-800"
          }`}
        >
          {labels.allRepos}
        </button>
        {selected.map((repo) => (
          <span
            key={repo}
            className="inline-flex max-w-full items-center gap-1 rounded-full border border-purple-200 bg-purple-50/90 pl-2.5 pr-1 py-0.5 text-[11px] font-medium text-purple-900 dark:border-purple-800 dark:bg-purple-950/50 dark:text-purple-100"
          >
            <span className="max-w-[200px] truncate" title={repo}>
              {repo}
            </span>
            <button
              type="button"
              onClick={() => removeRepo(repo)}
              className="rounded-full p-0.5 text-purple-600 transition-colors hover:bg-purple-200/60 hover:text-purple-900 dark:text-purple-300 dark:hover:bg-purple-900/60 dark:hover:text-purple-50"
              aria-label={`${labels.removeRepo}: ${repo}`}
            >
              <X size={12} strokeWidth={2.5} aria-hidden />
            </button>
          </span>
        ))}
        <div className="relative min-w-[8rem] shrink-0">
          <button
            id={triggerId}
            type="button"
            aria-haspopup="listbox"
            aria-expanded={open}
            aria-controls={listId}
            onClick={() => setOpen((v) => !v)}
            className="inline-flex w-full items-center justify-between gap-1 rounded-lg border border-gray-300 bg-white px-2.5 py-1.5 text-left text-[11px] font-medium text-gray-700 shadow-sm outline-none transition-colors hover:border-gray-400 focus:border-purple-400 focus:ring-1 focus:ring-purple-300 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-200 dark:hover:border-gray-500 dark:focus:border-purple-500 dark:focus:ring-purple-600"
          >
            <span className="truncate">{labels.addRepo}</span>
            <ChevronDown
              size={14}
              className={`shrink-0 text-gray-400 transition-transform ${open ? "rotate-180" : ""}`}
              aria-hidden
            />
          </button>
          {open && (
            <div
              id={listId}
              role="listbox"
              aria-labelledby={triggerId}
              className="absolute left-0 right-0 top-full z-30 mt-1 max-h-56 overflow-hidden rounded-lg border border-gray-200 bg-white shadow-lg dark:border-gray-600 dark:bg-gray-900 dark:shadow-gray-900/50"
            >
              <div className="border-b border-gray-100 p-2 dark:border-gray-700">
                <input
                  type="search"
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                  placeholder={labels.filterPlaceholder}
                  className="w-full rounded-md border border-gray-200 bg-gray-50 px-2 py-1.5 text-[11px] text-gray-900 outline-none focus:border-purple-400 focus:ring-1 focus:ring-purple-200 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:focus:border-purple-500 dark:focus:ring-purple-800"
                  autoFocus
                />
              </div>
              <ul className="max-h-40 overflow-y-auto py-1" role="presentation">
                {filteredOptions.length === 0 ? (
                  <li className="px-3 py-2 text-[11px] text-gray-500 dark:text-gray-400">
                    {labels.noMatches}
                  </li>
                ) : (
                  filteredOptions.map((repo) => (
                    <li key={repo} role="option">
                      <button
                        type="button"
                        className="w-full truncate px-3 py-2 text-left text-[11px] text-gray-800 hover:bg-purple-50 dark:text-gray-200 dark:hover:bg-purple-950/40"
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => {
                          addRepo(repo);
                          if (filteredOptions.length <= 1) setOpen(false);
                        }}
                      >
                        {repo}
                      </button>
                    </li>
                  ))
                )}
              </ul>
            </div>
          )}
        </div>
        {!allMode && (
          <span className="text-[10px] text-gray-400 dark:text-gray-500">
            {labels.selectedCount.replace("{count}", String(selected.length))}
          </span>
        )}
      </div>
    </div>
  );
}
