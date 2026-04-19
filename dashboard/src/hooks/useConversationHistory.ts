import { useCallback, useMemo, useState } from "react";
import type { WikiAskSource } from "./wikiTypes";

export type WikiConversationMessage = { role: string; content: string };

/** Persisted Ask conversation (optional sources for restoring the panel). */
export type WikiStoredConversation = {
  id: string;
  title: string;
  messages: WikiConversationMessage[];
  created_at: number;
  sources?: WikiAskSource[];
};

const MAX_CONVERSATIONS = 50;
const MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;

function storageKey(repository: string): string {
  return `kb_conversations_${repository}`;
}

function pruneAndCap(items: WikiStoredConversation[]): WikiStoredConversation[] {
  const now = Date.now();
  const fresh = items.filter((c) => now - c.created_at <= MAX_AGE_MS);
  fresh.sort((a, b) => b.created_at - a.created_at);
  return fresh.slice(0, MAX_CONVERSATIONS);
}

function readAll(repo: string): WikiStoredConversation[] {
  try {
    const raw = localStorage.getItem(storageKey(repo));
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return pruneAndCap(parsed as WikiStoredConversation[]);
  } catch {
    return [];
  }
}

function writeAll(repo: string, items: WikiStoredConversation[]): void {
  const next = pruneAndCap(items);
  try {
    localStorage.setItem(storageKey(repo), JSON.stringify(next));
  } catch {
    /* quota / private mode */
  }
}

/** Merge replace-by-id save and persist with retention rules. */
export function save(repo: string, conversation: WikiStoredConversation): void {
  const all = readAll(repo);
  const idx = all.findIndex((c) => c.id === conversation.id);
  if (idx >= 0) all[idx] = conversation;
  else all.push(conversation);
  writeAll(repo, all);
}

export function list(repo: string): WikiStoredConversation[] {
  return readAll(repo).sort((a, b) => b.created_at - a.created_at);
}

export function get(repo: string, id: string): WikiStoredConversation | undefined {
  return readAll(repo).find((c) => c.id === id);
}

export function remove(repo: string, id: string): void {
  const all = readAll(repo).filter((c) => c.id !== id);
  writeAll(repo, all);
}

export function clear(repo: string): void {
  try {
    localStorage.removeItem(storageKey(repo));
  } catch {
    /* ignore */
  }
}

/**
 * React wrapper around conversation storage; bumps a version when mutating so
 * list/get stay in sync with components.
 */
export function useConversationHistory() {
  const [version, setVersion] = useState(0);
  const bump = useCallback(() => setVersion((v) => v + 1), []);

  const saveCb = useCallback(
    (repo: string, conversation: WikiStoredConversation) => {
      save(repo, conversation);
      bump();
    },
    [bump],
  );

  const listCb = useCallback(
    (repo: string) => {
      void version;
      return list(repo);
    },
    [version],
  );

  const getCb = useCallback(
    (repo: string, id: string) => {
      void version;
      return get(repo, id);
    },
    [version],
  );

  const removeCb = useCallback(
    (repo: string, id: string) => {
      remove(repo, id);
      bump();
    },
    [bump],
  );

  const clearCb = useCallback(
    (repo: string) => {
      clear(repo);
      bump();
    },
    [bump],
  );

  return useMemo(
    () => ({
      save: saveCb,
      list: listCb,
      get: getCb,
      remove: removeCb,
      clear: clearCb,
    }),
    [saveCb, listCb, getCb, removeCb, clearCb],
  );
}
