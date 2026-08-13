"use client";

import Link from "next/link";
import { useSiteLanguage } from "./LanguageProvider";

export function Brand() {
  const { language } = useSiteLanguage();
  return (
    <span className="brand-lockup">
      <span className="brand-mark" aria-hidden="true">
        <span />
        <span />
        <span />
      </span>
      <span>
        <strong>MaryGenAI</strong>
        <small>{language === "pt-BR" ? "inteligência de fontes científicas" : "scientific source intelligence"}</small>
      </span>
    </span>
  );
}

export function SiteHeader() {
  const { language, setLanguage } = useSiteLanguage();
  const portuguese = language === "pt-BR";
  return (
    <header className="site-header">
      <div className="shell header-inner">
        <Link href="/" className="brand-link" aria-label={portuguese ? "Página inicial da MaryGenAI" : "MaryGenAI home"}>
          <Brand />
        </Link>
        <nav className="primary-nav" aria-label={portuguese ? "Navegação principal" : "Primary navigation"}>
          {/* Native anchors deliberately force reliable section navigation in the Worker runtime. */}
          {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
          <a href="/#how-it-works">{portuguese ? "Como funciona" : "How it works"}</a>
          {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
          <a href="/#current-state">{portuguese ? "Estado atual" : "Current state"}</a>
          {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
          <a href="/#collaborate">{portuguese ? "Colabore" : "Collaborate"}</a>
          <label className="language-select">
            <span className="sr-only">{portuguese ? "Idioma do website" : "Website language"}</span>
            <select
              aria-label={portuguese ? "Idioma do website" : "Website language"}
              value={language}
              onChange={(event) => setLanguage(event.target.value === "en" ? "en" : "pt-BR")}
            >
              <option value="pt-BR">PT</option>
              <option value="en">EN</option>
            </select>
          </label>
          <a href="/dataset" className="nav-cta">
            Dataset Viewer
          </a>
        </nav>
      </div>
    </header>
  );
}
