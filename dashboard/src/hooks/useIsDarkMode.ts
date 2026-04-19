import { useSyncExternalStore } from "react";

function subscribeDarkClass(onStoreChange: () => void): () => void {
  const obs = new MutationObserver(onStoreChange);
  obs.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
  return () => obs.disconnect();
}

function getIsDarkSnapshot(): boolean {
  return document.documentElement.classList.contains("dark");
}

/** Tracks `<html class="dark">` for theme-aware UI (e.g. Chart.js). */
export function useIsDarkMode(): boolean {
  return useSyncExternalStore(subscribeDarkClass, getIsDarkSnapshot, () => false);
}
