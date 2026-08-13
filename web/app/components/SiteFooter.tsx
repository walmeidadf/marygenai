"use client";

import { Brand } from "./SiteHeader";
import { useSiteLanguage } from "./LanguageProvider";

const repository = "https://github.com/walmeidadf/marygenai";

export function SiteFooter() {
  const { language } = useSiteLanguage();
  const portuguese = language === "pt-BR";
  return (
    <footer className="site-footer">
      <div className="shell footer-grid">
        <div>
          <Brand />
          <p className="footer-note">
            {portuguese
              ? "Metadados científicos candidatos para descoberta e inspeção. Não constituem orientação médica."
              : "Candidate scientific metadata for discovery and inspection. Not medical advice."}
          </p>
        </div>
        <nav aria-label={portuguese ? "Navegação do rodapé" : "Footer navigation"}>
          <a href="/dataset">Dataset Viewer</a>
          <a href={`${repository}/tree/main/docs`}>{portuguese ? "Documentação" : "Documentation"}</a>
          <a href={repository}>{portuguese ? "Repositório" : "Repository"}</a>
        </nav>
        <p className="license-note">
          {portuguese
            ? "Nenhuma licença de software ou dados foi publicada. A visibilidade pública não concede direitos de redistribuição."
            : "No software or data license has been published. Public visibility does not grant redistribution rights."}
        </p>
      </div>
    </footer>
  );
}
