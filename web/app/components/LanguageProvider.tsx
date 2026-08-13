"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { LANGUAGE_COOKIE, type SiteLanguage } from "../lib/language";

type LanguageContextValue = {
  language: SiteLanguage;
  setLanguage: (language: SiteLanguage) => void;
};

const LanguageContext = createContext<LanguageContextValue | null>(null);

export function LanguageProvider({ children, initialLanguage }: { children: React.ReactNode; initialLanguage: SiteLanguage }) {
  const [language, setLanguageState] = useState<SiteLanguage>(initialLanguage);

  useEffect(() => {
    document.documentElement.lang = language;
  }, [language]);

  const value = useMemo<LanguageContextValue>(() => ({
    language,
    setLanguage(nextLanguage) {
      document.cookie = `${LANGUAGE_COOKIE}=${nextLanguage}; Path=/; Max-Age=31536000; SameSite=Lax`;
      setLanguageState(nextLanguage);
    },
  }), [language]);

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}

export function useSiteLanguage() {
  const context = useContext(LanguageContext);
  if (!context) throw new Error("useSiteLanguage must be used within LanguageProvider");
  return context;
}
