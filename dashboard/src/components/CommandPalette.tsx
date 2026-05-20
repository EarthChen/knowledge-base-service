import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import {
  BookOpen,
  Box,
  Braces,
  FileText,
  FolderTree,
  Loader2,
  Search,
} from "lucide-react";
import type { SearchMatch } from "../api/types";
import { useHybridQuickSearch } from "../api/hooks";
import { useI18n } from "../i18n/context";
import FocusTrap from "./FocusTrap";

const TYPE_ICON: Record<string, ReactNode> = {
  function: <Braces className="size-4 text-emerald-600 dark:text-emerald-400" aria-hidden />,
  class: <Box className="size-4 text-sky-600 dark:text-sky-400" aria-hidden />,
  module: <FolderTree className="size-4 text-purple-600 dark:text-purple-400" aria-hidden />,
  document: <FileText className="size-4 text-amber-600 dark:text-amber-400" aria-hidden />,
};

function iconForType(t: string | undefined) {
  const key = t?.toLowerCase() ?? "";
  return TYPE_ICON[key] ?? <Search className="size-4 text-gray-400 dark:text-gray-500" aria-hidden />;
}

function isWikiMatch(match: SearchMatch): boolean {
  return match.type?.toLowerCase() === "document";
}

export default function CommandPalette() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [debounced, setDebounced] = useState("");
  const [selected, setSelected] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const isMac =
    typeof navigator !== "undefined" &&
    (/Mac|iPhone|iPad|iPod/i.test(navigator.platform) ||
      navigator.userAgent.includes("Mac OS"));
  const shortcutLabel = isMac ? "⌘K" : "Ctrl+K";

  useEffect(() => {
    const tmr = window.setTimeout(() => setDebounced(input.trim()), 300);
    return () => window.clearTimeout(tmr);
  }, [input]);

  const hybridQuick = useHybridQuickSearch(debounced, open);
  const matches = hybridQuick.data?.semantic_matches ?? [];
  const hybridPending = hybridQuick.isFetching;

  const safeSelected = useMemo(
    () => (matches.length === 0 ? 0 : Math.min(selected, matches.length - 1)),
    [matches.length, selected],
  );

  useEffect(() => {
    if (!open) return;
    const id = window.setTimeout(() => inputRef.current?.focus(), 0);
    return () => window.clearTimeout(id);
  }, [open]);

  // Ctrl/Cmd+K: bubble-phase listener. On wiki routes, WikiSearchBar registers the
  // same shortcut in capture phase and calls stopImmediatePropagation(), so wiki
  // search wins when both handlers are mounted.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((v) => !v);
      }
      if (e.key === "Escape") {
        setOpen(false);
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reset row highlight when the debounced query changes
    setSelected(0);
  }, [debounced]);

  const go = useCallback(
    (match: SearchMatch) => {
      const q = encodeURIComponent(debounced.trim() || match.name || "");
      if (isWikiMatch(match)) {
        const nameQ = encodeURIComponent(match.name || "");
        navigate(nameQ ? `/search?mode=wiki&q=${nameQ}` : "/search?mode=wiki");
      } else {
        navigate(q ? `/search?q=${q}` : "/search");
      }
      setOpen(false);
      setInput("");
      setDebounced("");
      setSelected(0);
    },
    [navigate, debounced],
  );

  const onBackdropClick = () => setOpen(false);

  const handleDialogKeyDownCapture = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelected((i) => (matches.length ? (i + 1) % matches.length : 0));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelected((i) =>
        matches.length ? (i - 1 + matches.length) % matches.length : 0,
      );
    } else if (e.key === "Enter") {
      const m = matches[safeSelected];
      if (m) {
        e.preventDefault();
        go(m);
      }
    }
  };

  const palette = (
    <div className="fixed inset-0 z-[200] flex items-start justify-center pt-[12vh] px-4">
      <button
        type="button"
        className="absolute inset-0 bg-black/50 backdrop-blur-[1px] dark:bg-black/70"
        aria-label={t.common.close}
        onClick={onBackdropClick}
      />
      <FocusTrap onEscape={() => setOpen(false)}>
        <div
          role="dialog"
          aria-modal="true"
          aria-label={t.app.commandPaletteShortcutOpen}
          className="relative w-full max-w-xl overflow-hidden rounded-xl border border-gray-200 bg-white shadow-2xl dark:border-gray-600 dark:bg-gray-900"
          tabIndex={-1}
          onKeyDownCapture={handleDialogKeyDownCapture}
        >
        <div className="flex items-center gap-2 border-b border-gray-100 px-3 dark:border-gray-700">
          <Search className="size-4 shrink-0 text-gray-400 dark:text-gray-500" aria-hidden />
          <input
            ref={inputRef}
            type="search"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={t.app.commandPalettePlaceholder}
            className="h-12 w-full border-0 bg-transparent text-sm text-gray-900 outline-none placeholder:text-gray-400 dark:text-gray-100 dark:placeholder:text-gray-500"
            autoComplete="off"
            autoCorrect="off"
            spellCheck={false}
          />
          {hybridPending && (
            <Loader2 className="size-4 shrink-0 animate-spin text-gray-400 dark:text-gray-500" aria-hidden />
          )}
        </div>

        <div className="max-h-[min(50vh,420px)] overflow-y-auto px-2 py-2">
          {debounced.length >= 2 && !hybridPending && matches.length === 0 && (
            <p className="px-3 py-8 text-center text-sm text-gray-500 dark:text-gray-400">
              {t.app.commandPaletteNoMatches}
            </p>
          )}
          <ul className="space-y-0.5">
            {matches.map((m, i) => (
              <li key={`${m.uid ?? m.name}-${i}`}>
                <button
                  type="button"
                  onClick={() => go(m)}
                  onMouseEnter={() => setSelected(i)}
                  className={`flex w-full items-start gap-3 rounded-lg px-3 py-2.5 text-left text-sm transition-colors ${
                    i === safeSelected
                      ? "bg-gray-100 dark:bg-gray-800"
                      : "hover:bg-gray-50 dark:hover:bg-gray-800/80"
                  }`}
                >
                  <span className="mt-0.5 shrink-0">{iconForType(m.type)}</span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium text-gray-900 dark:text-gray-100">
                      {m.name || "—"}
                    </span>
                    {m.file && (
                      <span className="mt-0.5 block truncate font-mono text-[11px] text-gray-500 dark:text-gray-400">
                        {m.file}
                        {m.line != null ? `:${m.line}` : ""}
                      </span>
                    )}
                    <span className="mt-1 block text-[10px] uppercase tracking-wide text-gray-400 dark:text-gray-500">
                      {m.type ?? "unknown"}
                    </span>
                  </span>
                  {isWikiMatch(m) ? (
                    <BookOpen className="mt-1 size-3.5 shrink-0 text-amber-500 dark:text-amber-400" aria-hidden />
                  ) : (
                    <Braces className="mt-1 size-3.5 shrink-0 text-emerald-500 opacity-60 dark:text-emerald-400" aria-hidden />
                  )}
                </button>
              </li>
            ))}
          </ul>
        </div>

        <div className="border-t border-gray-100 bg-gray-50 px-3 py-2 dark:border-gray-700 dark:bg-gray-800/80">
          <p className="text-[11px] leading-relaxed text-gray-500 dark:text-gray-400">
            {t.app.commandPaletteFooterHint}
          </p>
        </div>
        </div>
      </FocusTrap>
    </div>
  );

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="ml-auto inline-flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-xs text-gray-500 shadow-sm transition-colors hover:border-gray-300 hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300 dark:hover:border-gray-500 dark:hover:bg-gray-700"
        title={`${t.app.commandPaletteShortcutOpen} (${shortcutLabel})`}
      >
        <Search className="size-3.5" aria-hidden />
        <kbd className="hidden rounded border border-gray-200 bg-gray-100 px-1.5 py-0.5 font-mono text-[10px] text-gray-600 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-300 sm:inline-block">
          {shortcutLabel}
        </kbd>
      </button>

      {open && typeof document !== "undefined" ? createPortal(palette, document.body) : null}
    </>
  );
}
