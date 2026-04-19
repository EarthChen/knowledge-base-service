import { useCallback, useSyncExternalStore } from "react";

const STORAGE_KEY = "kb_search_history";
const MAX_ITEMS = 20;

let listeners: Array<() => void> = [];

function emitChange() {
  for (const l of listeners) l();
}

function getSnapshot(): string[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as string[]) : [];
  } catch {
    return [];
  }
}

function subscribe(listener: () => void) {
  listeners = [...listeners, listener];
  return () => {
    listeners = listeners.filter((l) => l !== listener);
  };
}

export function useSearchHistory() {
  const history = useSyncExternalStore(subscribe, getSnapshot, () => []);

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
