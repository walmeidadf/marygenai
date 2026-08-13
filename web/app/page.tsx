"use client";

import Link from "next/link";
import { SiteFooter } from "./components/SiteFooter";
import { SiteHeader } from "./components/SiteHeader";
import { TrustBadge } from "./components/TrustBadge";
import { useSiteLanguage } from "./components/LanguageProvider";

const repository = "https://github.com/walmeidadf/marygenai";

const copy = {
  "pt-BR": {
    skip: "Ir para o conteúdo",
    heroEyebrow: "Infraestrutura de evidências para medicina canabinoide",
    heroTitle: ["Encontre o estudo.", "Inspecione a evidência."],
    heroEmphasis: "Conheça seus limites.",
    heroLede: "A MaryGenAI transforma literatura científica dispersa em registros candidatos vinculados às fontes, que médicos, pesquisadores e comunidades de aprendizagem podem descobrir e verificar.",
    explore: "Explorar o Dataset Viewer",
    documentation: "Ler a documentação",
    caveat: "As classificações por IA apoiam a busca. Elas não são verdade clínica revisada, diagnóstico ou recomendação de tratamento.",
    recordLabel: "REGISTRO CANDIDATO / 03437",
    readOnly: "somente leitura",
    map: ["fonte", "identidade", "rótulo candidato", "trecho de evidência", "revisão humana"],
    legend: [["Rastreável", "identidade da fonte e hashes"], ["Inspecionável", "evidências e incertezas"], ["Delimitado", "estado de confiança candidato"]],
    problemEyebrow: "O problema",
    problemTitle: "A descoberta científica não deveria começar em um labirinto de registros desconectados.",
    problemBody: "A literatura relevante está distribuída entre índices, repositórios, páginas de editoras e metadados inconsistentes. A MaryGenAI constrói a camada verificável de fontes entre esse cenário fragmentado e as ferramentas usadas para formular perguntas científicas.",
    howEyebrow: "Como funciona",
    howTitle: "Proveniência antes da escala.",
    howBody: "Cada transição preserva identidade, rota da fonte, evidência, incerteza e estado de confiança.",
    pipeline: [
      ["01", "Descobrir", "Encontrar publicações candidatas por rotas de fontes científicas explícitas e auditáveis."],
      ["02", "Adquirir", "Resolver a identidade e localizar texto-fonte utilizável por caminhos legais que preservam a proveniência."],
      ["03", "Classificar", "Criar rótulos estruturados de busca candidata com trechos de evidência, incerteza e versões."],
      ["04", "Recuperar", "Expor um snapshot imutável de candidatos pela CLI, pelo MCP e por este Viewer somente leitura."],
      ["05", "Revisar", "Futuros curadores treinados poderão aceitar, corrigir ou se abster antes da criação de qualquer snapshot revisado."],
    ],
    stateEyebrow: "Snapshot operacional verificado",
    stateTitle: "Útil hoje, explícito sobre o amanhã.",
    stateBody: "Os números abaixo refletem o estado documentado do projeto, verificado em 13 de agosto de 2026.",
    metrics: [
      ["3.437", "registros candidatos no snapshot ativo somente leitura"],
      ["3.149", "registros candidatos da campanha histórica estrita"],
      ["288", "candidatos PubMed qualificados adicionados ao snapshot"],
      ["100%", "dos registros ainda precisam de revisão humana"],
    ],
    cards: [
      ["Implementado", "Piloto de recuperação somente leitura", "Busca lexical e estruturada, detalhes do estudo, facetas, descoberta de capacidades, CLI, MCP stdio e HTTP sem estado sobre um snapshot DuckDB isolado."],
      ["Implementado aqui", "Dataset Viewer v1", "Busca, filtros, estado estável na URL, paginação, rótulos explícitos de confiança, inspeção de evidências, proveniência e acesso ao índice candidato."],
      ["Planejado", "Referência pública revisada", "Curadoria universitária, licenciamento explícito, snapshots revisados e redistribuição pública continuam sendo etapas futuras — não afirmações atuais."],
    ],
    mcpTitle: "Uma rota estruturada entre perguntas científicas e estudos candidatos inspecionáveis.",
    mcpBody: "O piloto MCP permite que assistentes compatíveis pesquisem o mesmo serviço somente leitura, inspecionem estudos selecionados e preservem linguagem segura e links preferenciais para as fontes.",
    mcpFine: "O aplicativo cliente deve distinguir correspondências diretas de tangenciais e inspecionar os detalhes antes de fazer afirmações específicas sobre evidências.",
    collaborateEyebrow: "Uma futura camada comunitária de revisão",
    collaborateTitle: "Universidades podem ajudar a transformar candidatos em conhecimento revisado.",
    collaborateBody: "Professores, estudantes e parceiros científicos poderão participar de tarefas de curadoria treinadas e versionadas, com identidade do revisor, dupla revisão, adjudicação e proveniência somente acréscimo.",
    collaborateSteps: [["Aprender", "com diretrizes congeladas e tarefas de calibração"], ["Revisar", "campos, trechos de evidência e identidade das fontes"], ["Adjudicar", "divergências sem apagar o histórico candidato"], ["Publicar depois", "somente após as etapas de licenciamento e revisão"]],
    safetyEyebrow: "Segurança e limitações",
    safetyTitle: "A publicação original continua sendo a autoridade científica.",
    safetyItems: ["Rótulos candidatos podem estar incompletos, incertos ou errados.", "Confiança e ordenação não medem a força da evidência clínica.", "Resultados vazios estão limitados ao snapshot e à consulta atuais.", "Dados que identifiquem pacientes não devem aparecer em consultas ou exemplos.", "O dataset candidato atual não está licenciado para redistribuição."],
  },
  en: {
    skip: "Skip to content",
    heroEyebrow: "Evidence infrastructure for cannabinoid medicine",
    heroTitle: ["Find the study.", "Inspect the evidence."],
    heroEmphasis: "Know its limits.",
    heroLede: "MaryGenAI turns scattered scientific literature into source-linked candidate records that physicians, researchers, and learning communities can discover and verify.",
    explore: "Explore the Dataset Viewer",
    documentation: "Read the documentation",
    caveat: "AI classifications support retrieval. They are not reviewed clinical truth, diagnosis, or treatment recommendations.",
    recordLabel: "CANDIDATE RECORD / 03437",
    readOnly: "read only",
    map: ["source", "identity", "candidate label", "evidence span", "human review"],
    legend: [["Traceable", "source identity and hashes"], ["Inspectable", "evidence and uncertainty"], ["Bounded", "candidate trust state"]],
    problemEyebrow: "The problem",
    problemTitle: "Scientific discovery should not begin with a maze of disconnected records.",
    problemBody: "Relevant literature is distributed across indexes, repositories, publisher pages, and inconsistent metadata. MaryGenAI builds the verifiable source layer between that fragmented landscape and the tools people use to ask scientific questions.",
    howEyebrow: "How it works",
    howTitle: "Provenance before scale.",
    howBody: "Every transition preserves identity, source route, evidence, uncertainty, and trust state.",
    pipeline: [
      ["01", "Discover", "Find candidate publications through explicit, auditable scientific source routes."],
      ["02", "Acquire", "Resolve identity and locate usable source text through lawful, provenance-preserving paths."],
      ["03", "Classify", "Create structured candidate retrieval labels with evidence spans, uncertainty, and versions."],
      ["04", "Retrieve", "Expose an immutable candidate snapshot through the CLI, MCP, and this read-only Viewer."],
      ["05", "Review", "Future trained curators accept, correct, or abstain before any reviewed snapshot is created."],
    ],
    stateEyebrow: "Verified operating snapshot",
    stateTitle: "Useful today, explicit about tomorrow.",
    stateBody: "Counts below reflect the documented project state verified on 13 August 2026.",
    metrics: [["3,437", "candidate records in the active read-only snapshot"], ["3,149", "candidate records from the strict historical campaign"], ["288", "qualified PubMed candidates added to the snapshot"], ["100%", "of records still require human review"]],
    cards: [
      ["Implemented", "Read-only retrieval pilot", "Lexical and structured search, study detail, facets, capability discovery, CLI, MCP stdio, and stateless HTTP over an isolated DuckDB snapshot."],
      ["Implemented here", "Dataset Viewer v1", "Search, filters, stable URL state, pagination, explicit trust labels, evidence inspection, provenance, and access to the candidate index."],
      ["Planned", "Reviewed public baseline", "University curation, explicit licensing, reviewed snapshots, and public redistribution remain future gates—not current claims."],
    ],
    mcpTitle: "A structured route from scientific questions to inspectable candidate studies.",
    mcpBody: "The MCP pilot lets compatible assistants search the same read-only retrieval service, inspect shortlisted studies, and preserve safe result language and preferred source links.",
    mcpFine: "The host must distinguish direct from tangential matches and inspect study detail before making detailed evidence claims.",
    collaborateEyebrow: "A future community review layer",
    collaborateTitle: "Universities can help turn candidates into reviewed knowledge.",
    collaborateBody: "Professors, students, and scientific partners will be able to participate through trained, versioned curation tasks with reviewer identity, double review, adjudication, and append-only provenance.",
    collaborateSteps: [["Learn", "with frozen guidelines and calibration tasks"], ["Review", "fields, evidence spans, and source identity"], ["Adjudicate", "disagreements without erasing candidate history"], ["Publish later", "only after licensing and review gates"]],
    safetyEyebrow: "Safety and limitations",
    safetyTitle: "The original publication remains the scientific authority.",
    safetyItems: ["Candidate labels may be incomplete, uncertain, or wrong.", "Confidence and ranking do not measure clinical evidence strength.", "Zero results are bounded to the current snapshot and query.", "No patient-identifying data belongs in queries or examples.", "The current candidate dataset is not licensed for redistribution."],
  },
} as const;

export default function Home() {
  const { language } = useSiteLanguage();
  const text = copy[language];

  return (
    <>
      <a className="skip-link" href="#main">{text.skip}</a>
      <SiteHeader />
      <main id="main">
        <section className="hero shell">
          <div className="hero-copy">
            <p className="eyebrow">{text.heroEyebrow}</p>
            <h1>{text.heroTitle[0]}<br />{text.heroTitle[1]}<br /><em>{text.heroEmphasis}</em></h1>
            <p className="hero-lede">{text.heroLede}</p>
            <div className="button-row">
              <Link className="button button-primary" href="/dataset">{text.explore}</Link>
              <a className="button button-secondary" href={`${repository}/tree/main/docs`}>{text.documentation}</a>
            </div>
            <p className="hero-caveat">{text.caveat}</p>
          </div>
          <div className="hero-evidence-card" aria-label={language === "pt-BR" ? "Prévia de registro de evidência candidato" : "Candidate evidence record preview"}>
            <div className="record-topline"><span className="mono-label">{text.recordLabel}</span><span className="live-dot">{text.readOnly}</span></div>
            <div className="record-map" aria-hidden="true">
              <span className="map-node node-source">{text.map[0]}</span><span className="map-node node-identity">{text.map[1]}</span>
              <span className="map-node node-label">{text.map[2]}</span><span className="map-node node-evidence">{text.map[3]}</span>
              <span className="map-node node-review">{text.map[4]}</span><i className="line line-a" /><i className="line line-b" /><i className="line line-c" /><i className="line line-d" />
            </div>
            <TrustBadge reviewState="needs_review" />
            <div className="record-legend">{text.legend.map(([title, body]) => <span key={title}><b>{title}</b>{body}</span>)}</div>
          </div>
        </section>

        <section className="problem-band" id="problem">
          <div className="shell problem-grid"><p className="eyebrow">{text.problemEyebrow}</p><h2>{text.problemTitle}</h2><p>{text.problemBody}</p></div>
        </section>

        <section className="section shell" id="how-it-works">
          <div className="section-heading split-heading"><div><p className="eyebrow">{text.howEyebrow}</p><h2>{text.howTitle}</h2></div><p>{text.howBody}</p></div>
          <ol className="pipeline-list">{text.pipeline.map(([number, title, description]) => <li key={number}><span>{number}</span><h3>{title}</h3><p>{description}</p></li>)}</ol>
        </section>

        <section className="section state-section" id="current-state">
          <div className="shell">
            <div className="section-heading split-heading"><div><p className="eyebrow">{text.stateEyebrow}</p><h2>{text.stateTitle}</h2></div><p>{text.stateBody}</p></div>
            <div className="metrics-grid">{text.metrics.map(([value, label]) => <article key={label}><strong>{value}</strong><span>{label}</span></article>)}</div>
            <div className="implemented-grid">{text.cards.map(([kicker, title, body], index) => <article className={`implemented-card ${index === 2 ? "planned-card" : ""}`} key={title}><p className="card-kicker">{kicker}</p><h3>{title}</h3><p>{body}</p></article>)}</div>
          </div>
        </section>

        <section className="section shell mcp-section" id="mcp">
          <div className="mcp-mark" aria-hidden="true">MCP</div><div><p className="eyebrow">Model Context Protocol</p><h2>{text.mcpTitle}</h2></div>
          <div><p>{text.mcpBody}</p><p className="fine-print">{text.mcpFine}</p></div>
        </section>

        <section className="section collaboration-section" id="collaborate">
          <div className="shell collaboration-grid">
            <div><p className="eyebrow">{text.collaborateEyebrow}</p><h2>{text.collaborateTitle}</h2><p>{text.collaborateBody}</p></div>
            <div className="collaboration-steps">{text.collaborateSteps.map(([title, body]) => <span key={title}><b>{title}</b>{body}</span>)}</div>
          </div>
        </section>

        <section className="section shell safety-section" id="limitations">
          <div><p className="eyebrow">{text.safetyEyebrow}</p><h2>{text.safetyTitle}</h2></div><ul>{text.safetyItems.map((item) => <li key={item}>{item}</li>)}</ul>
        </section>
      </main>
      <SiteFooter />
    </>
  );
}
