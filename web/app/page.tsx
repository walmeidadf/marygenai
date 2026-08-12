import Link from "next/link";
import { SiteFooter } from "./components/SiteFooter";
import { SiteHeader } from "./components/SiteHeader";
import { TrustBadge } from "./components/TrustBadge";

const repository = "https://github.com/walmeidadf/marygenai";

const pipeline = [
  ["01", "Discover", "Find candidate publications through explicit, auditable scientific source routes."],
  ["02", "Acquire", "Resolve identity and locate usable source text through lawful, provenance-preserving paths."],
  ["03", "Classify", "Create structured candidate retrieval labels with evidence spans, uncertainty, and versions."],
  ["04", "Retrieve", "Expose an immutable candidate snapshot through the CLI, MCP, and this read-only Viewer."],
  ["05", "Review", "Future trained curators accept, correct, or abstain before any reviewed snapshot is created."],
] as const;

export default function Home() {
  return (
    <>
      <a className="skip-link" href="#main">Skip to content</a>
      <SiteHeader />
      <main id="main">
        <section className="hero shell">
          <div className="hero-copy">
            <p className="eyebrow">Evidence infrastructure for cannabinoid medicine</p>
            <h1>Find the study.<br />Inspect the evidence.<br /><em>Know its limits.</em></h1>
            <p className="hero-lede">
              MaryGenAI turns scattered scientific literature into source-linked candidate records
              that physicians, researchers, and learning communities can discover and verify.
            </p>
            <div className="button-row">
              <Link className="button button-primary" href="/dataset">Explore the Dataset Viewer</Link>
              <a className="button button-secondary" href={`${repository}/tree/main/docs`}>Read the documentation</a>
            </div>
            <p className="hero-caveat">
              AI classifications support retrieval. They are not reviewed clinical truth,
              diagnosis, or treatment recommendations.
            </p>
          </div>
          <div className="hero-evidence-card" aria-label="Candidate evidence record preview">
            <div className="record-topline">
              <span className="mono-label">CANDIDATE RECORD / 03149</span>
              <span className="live-dot">read only</span>
            </div>
            <div className="record-map" aria-hidden="true">
              <span className="map-node node-source">source</span>
              <span className="map-node node-identity">identity</span>
              <span className="map-node node-label">candidate label</span>
              <span className="map-node node-evidence">evidence span</span>
              <span className="map-node node-review">human review</span>
              <i className="line line-a" /><i className="line line-b" />
              <i className="line line-c" /><i className="line line-d" />
            </div>
            <TrustBadge reviewState="needs_review" />
            <div className="record-legend">
              <span><b>Traceable</b> source identity and hashes</span>
              <span><b>Inspectable</b> evidence and uncertainty</span>
              <span><b>Bounded</b> candidate trust state</span>
            </div>
          </div>
        </section>

        <section className="problem-band">
          <div className="shell problem-grid">
            <p className="eyebrow">The problem</p>
            <h2>Scientific discovery should not begin with a maze of disconnected records.</h2>
            <p>
              Relevant literature is distributed across indexes, repositories, publisher pages,
              and inconsistent metadata. MaryGenAI builds the verifiable source layer between
              that fragmented landscape and the tools people use to ask scientific questions.
            </p>
          </div>
        </section>

        <section className="section shell" id="how-it-works">
          <div className="section-heading split-heading">
            <div><p className="eyebrow">How it works</p><h2>Provenance before scale.</h2></div>
            <p>Every transition preserves identity, source route, evidence, uncertainty, and trust state.</p>
          </div>
          <ol className="pipeline-list">
            {pipeline.map(([number, title, description]) => (
              <li key={number}>
                <span>{number}</span><h3>{title}</h3><p>{description}</p>
              </li>
            ))}
          </ol>
        </section>

        <section className="section state-section" id="current-state">
          <div className="shell">
            <div className="section-heading split-heading">
              <div><p className="eyebrow">Verified operating snapshot</p><h2>Useful today, explicit about tomorrow.</h2></div>
              <p>Counts below reflect the documented project state verified on 12 August 2026.</p>
            </div>
            <div className="metrics-grid">
              <article><strong>3,149</strong><span>strict-valid AI-classified candidate records</span></article>
              <article><strong>3,374</strong><span>source-ready records in the maintainer-local funnel</span></article>
              <article><strong>6,490</strong><span>deduplicated records in the classification corpus</span></article>
              <article><strong>1,361</strong><span>post-legacy PubMed publication candidates</span></article>
            </div>
            <div className="implemented-grid">
              <article className="implemented-card">
                <p className="card-kicker">Implemented</p>
                <h3>Read-only retrieval pilot</h3>
                <p>Lexical and structured search, study detail, facets, capability discovery, CLI, MCP stdio, and stateless HTTP over an isolated DuckDB snapshot.</p>
              </article>
              <article className="implemented-card">
                <p className="card-kicker">Implemented here</p>
                <h3>Dataset Viewer v1</h3>
                <p>Search, filters, stable URL state, pagination, explicit trust labels, evidence inspection, provenance, and a synthetic public demo mode.</p>
              </article>
              <article className="implemented-card planned-card">
                <p className="card-kicker">Planned</p>
                <h3>Reviewed public baseline</h3>
                <p>University curation, explicit licensing, reviewed snapshots, and public redistribution remain future gates—not current claims.</p>
              </article>
            </div>
          </div>
        </section>

        <section className="section shell mcp-section">
          <div className="mcp-mark" aria-hidden="true">MCP</div>
          <div>
            <p className="eyebrow">Model Context Protocol</p>
            <h2>A structured route from scientific questions to inspectable candidate studies.</h2>
          </div>
          <div>
            <p>
              The MCP pilot lets compatible assistants search the same read-only retrieval service,
              inspect shortlisted studies, and preserve safe result language and preferred source links.
            </p>
            <p className="fine-print">The host must distinguish direct from tangential matches and inspect study detail before making detailed evidence claims.</p>
          </div>
        </section>

        <section className="section collaboration-section" id="collaborate">
          <div className="shell collaboration-grid">
            <div>
              <p className="eyebrow">A future community review layer</p>
              <h2>Universities can help turn candidates into reviewed knowledge.</h2>
              <p>
                Professors, students, and scientific partners will be able to participate through
                trained, versioned curation tasks with reviewer identity, double review,
                adjudication, and append-only provenance.
              </p>
            </div>
            <div className="collaboration-steps">
              <span><b>Learn</b> with frozen guidelines and calibration tasks</span>
              <span><b>Review</b> fields, evidence spans, and source identity</span>
              <span><b>Adjudicate</b> disagreements without erasing candidate history</span>
              <span><b>Publish later</b> only after licensing and review gates</span>
            </div>
          </div>
        </section>

        <section className="section shell safety-section">
          <div><p className="eyebrow">Safety and limitations</p><h2>The original publication remains the scientific authority.</h2></div>
          <ul>
            <li>Candidate labels may be incomplete, uncertain, or wrong.</li>
            <li>Confidence and ranking do not measure clinical evidence strength.</li>
            <li>Zero results are bounded to the current snapshot and query.</li>
            <li>No patient-identifying data belongs in queries or examples.</li>
            <li>The current candidate dataset is not licensed for redistribution.</li>
          </ul>
        </section>
      </main>
      <SiteFooter />
    </>
  );
}
