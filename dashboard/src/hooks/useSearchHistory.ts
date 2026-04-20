import { useCallback, useSyncExternalStore } from "react";

const STORAGE_KEY = "kb_search_history";
const MAX_ITEMS = 20;

/** Stable empty snapshot — useSyncExternalStore requires referential stability when data is unchanged. */
const EMPTY_HISTORY: string[] = [];

let listeners: Array<() => void> = [];

/** Last raw string from localStorage; `undefined` means cache is cold. */
let cachedStorageKey: string | null | undefined = undefined;
let cachedHistory: string[] = EMPTY_HISTORY;

function emitChange() {
  for (const l of listeners) l();
}

function readRaw(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function getSnapshot(): string[] {
  const raw = readRaw();
  if (raw === cachedStorageKey) return cachedHistory;
  cachedStorageKey = raw;

  if (!raw) {
    cachedHistory = EMPTY_HISTORY;
    return cachedHistory;
  }
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) {
      cachedHistory = EMPTY_HISTORY;
      return cachedHistory;
    }
    const list = parsed.filter((item): item is string => typeof item === "string");
    cachedHistory = list;
    return cachedHistory;
  } catch {
    cachedHistory = EMPTY_HISTORY;
    return cachedHistory;
  }
}

function subscribe(listener: () => void) {
  listeners = [...listeners, listener];
  return () => {
    listeners = listeners.filter((l) => l !== listener);
  };
}

export function useSearchHistory() {
  const history = useSyncExternalStore(subscribe, getSnapshot, () => EMPTY_HISTORY);

  const addEntry = useCallback((query: string) => {
    const trimmed = query.trim();
    if (!trimmed) return;
    const current = getSnapshot();
    const filtered = current.filter((q) => q !== trimmed);
    const updated = [trimmed, ...filtered].slice(0, MAX_ITEMS);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(updated));
    emitChange();
  }, []);

  const removeEntry = useCallback((query: string) => {
    const current = getSnapshot();
    const updated = current.filter((q) => q !== query);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(updated));
    emitChange();
  }, []);

  const clearHistory = useCallback(() => {
    localStorage.removeItem(STORAGE_KEY);
    emitChange();
  }, []);

  return { history, addEntry, removeEntry, clearHistory };
}
