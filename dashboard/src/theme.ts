export const KB_THEME_KEY = "kb_theme";

export type ThemePreference = "light" | "dark";

export function getStoredTheme(): ThemePreference | null {
  try {
    const v = localStorage.getItem(KB_THEME_KEY);
    if (v === "dark" || v === "light") return v;
  } catch {
    /* ignore */
  }
  return null;
}

export function applyTheme(theme: ThemePreference): void {
  const root = document.documentElement;
  if (theme === "dark") {
    root.classList.add("dark");
    root.style.colorScheme = "dark";
  } else {
    root.classList.remove("dark");
    root.style.colorScheme = "light";
  }
}

export function toggleStoredTheme(): ThemePreference {
  const next: ThemePreference = document.documentElement.classList.contains("dark")
    ? "light"
    : "dark";
  try {
    localStorage.setItem(KB_THEME_KEY, next);
  } catch {
    /* ignore */
  }
  applyTheme(next);
  return next;
}
