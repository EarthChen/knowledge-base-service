import { createContext, useContext, useState, useCallback, useEffect } from "react";
import type { Locale, Translations } from "./types";
import en from "./en";
import zh from "./zh";

const MESSAGES: Record<Locale, Translations> = { en, zh };
const STORAGE_KEY = "kb_locale";

function detectLocale(): Locale {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved === "en" || saved === "zh") return saved;
  const lang = navigator.language.toLowerCase();
  return lang.startsWith("en") ? "en" : "zh";
}

interface I18nContextType {
  locale: Locale;
  t: Translations;
  setLocale: (l: Locale) => void;
}

const I18nContext = createContext<I18nContextType>({
  locale: "zh",
  t: zh,
  setLocale: () => {},
});

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(detectLocale);

  const setLocale = useCallback((l: Locale) => {
    localStorage.setItem(STORAGE_KEY, l);
    setLocaleState(l);
  }, []);

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  return (
    <I18nContext.Provider value={{ locale, t: MESSAGES[locale], setLocale }}>
      {children}
    </I18nContext.Provider>
  );
}

export function useI18n() {
  return useContext(I18nContext);
}
