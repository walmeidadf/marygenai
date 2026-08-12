"use client";

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { TrustBadge } from "../components/TrustBadge";
import { demoMeta, demoStudies, searchDemoStudies } from "../lib/demo-data";
import type { StudyDetail, StudySummary, ViewerMeta, ViewerSearchResponse } from "../lib/viewer-types";

type Filters = {
  query: string;
  condition: string;
  cannabinoid: string;
  studyDesign: string;
  population: string;
  outcome: string;
  confidence: string;
  reviewState: string;
  yearFrom: string;
  yearTo: string;
  sort: string;
  page: string;
};

const defaults: Filters = {
  query: "", condition: "", cannabinoid: "", studyDesign: "", population: "",
  outcome: "", confidence: "", reviewState: "", yearFrom: "", yearTo: "",
  sort: "confidence", page: "1",
};

const FILTER_KEYS = Object.keys(defaults) as (keyof Filters)[];

function readFilters(): Filters {
  if (typeof window === "undefined") return defaults;
  const params = new URLSearchParams(window.location.search);
  return Object.fromEntries(FILTER_KEYS.map((key) => [key, params.get(key) ?? defaults[key]])) as Filters;
}

function sentence(value: string) {
  return value.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
}

function confidenceNote(value: string) {
  return `${sentence(value)} categorical model assessment; not a probability or clinical evidence strength.`;
}

function hasJsonPayload(response: Response) {
  return response.headers.get("content-type")?.includes("application/json") ?? false;
}

function FilterSelect({ label, name, value, values, onChange }: {
  label: string; name: keyof Filters; value: string; values: (string | number)[];
  onChange: (name: keyof Filters, value: string) => void;
}) {
  return (
    <label className="filter-field">
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(name, event.target.value)}>
        <option value="">All</option>
        {values.map((item) => <option key={item} value={item}>{sentence(String(item))}</option>)}
      </select>
    </label>
  );
}

function StudyRow({ study, onOpen }: { study: StudySummary; onOpen: (id: string) => void }) {
  return (
    <tr>
      <td data-label="Study">
        <button className="study-title-button" onClick={() => onOpen(study.documentId)}>
          {study.title}
        </button>
        <span className={`match-label match-${study.matchKind}`}>{sentence(study.matchKind)} match</span>
        <span className="mobile-study-meta">{study.year} · {sentence(study.studyDesign)}</span>
      </td>
      <td data-label="Year">{study.year}</td>
      <td data-label="Condition">{study.conditions.join(", ")}</td>
      <td data-label="Cannabinoid">{study.cannabinoids.join(", ")}</td>
      <td data-label="Design / population"><span>{sentence(study.studyDesign)}</span><small>{sentence(study.population)}</small></td>
      <td data-label="Confidence">
        <span className={`confidence confidence-${study.classificationConfidence}`} title={confidenceNote(study.classificationConfidence)}>
          {sentence(study.classificationConfidence)}
        </span>
      </td>
      <td data-label="Trust"><TrustBadge reviewState={study.reviewState} /></td>
      <td data-label="Original study">
        {study.preferredAccessUrl ? (
          <a
            className="study-source-link"
            href={study.preferredAccessUrl}
            target="_blank"
            rel="noopener noreferrer"
            aria-label={`Open original study in a new tab: ${study.title}`}
          >
            Open study <span aria-hidden="true">↗</span>
          </a>
        ) : (
          <span className="source-unavailable" title="Synthetic demonstration records do not represent real publications.">
            Demo only
          </span>
        )}
      </td>
    </tr>
  );
}

function StudyPanel({ study, loading, error, onClose }: {
  study: StudyDetail | null; loading: boolean; error: string | null; onClose: () => void;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => { if (loading || study || error) closeRef.current?.focus(); }, [loading, study, error]);
  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  return (
    <div className="detail-overlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <aside className="study-panel" role="dialog" aria-modal="true" aria-labelledby="study-panel-title">
        <div className="study-panel-bar">
          <span className="mono-label">Study detail</span>
          <button ref={closeRef} className="icon-button" onClick={onClose} aria-label="Close study detail">×</button>
        </div>
        {loading && <div className="panel-state" role="status"><span className="loading-line" /><span className="loading-line short" />Loading study detail…</div>}
        {error && <div className="panel-state error-state"><h2>Detail unavailable</h2><p>{error}</p></div>}
        {study && (
          <div className="study-panel-content">
            <div className="detail-trust-row"><TrustBadge reviewState={study.reviewState} /><span className="snapshot-chip">{study.documentId}</span></div>
            <h2 id="study-panel-title">{study.title}</h2>
            <p className="detail-intro">This page exposes candidate retrieval metadata and the evidence used by classification. Inspect the original publication before relying on a scientific claim.</p>

            <section className="detail-section">
              <h3>Bibliographic identity</h3>
              <dl className="identity-grid">
                <div><dt>Year</dt><dd>{study.year}</dd></div>
                <div><dt>PMID</dt><dd>{study.identifiers.pmid ?? "Unavailable"}</dd></div>
                <div><dt>PMCID</dt><dd>{study.identifiers.pmcid ?? "Unavailable"}</dd></div>
                <div><dt>DOI</dt><dd>{study.identifiers.doi ?? "Unavailable"}</dd></div>
              </dl>
              {study.preferredAccessUrl ? (
                <a
                  className="source-link"
                  href={study.preferredAccessUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label={`Open original study in a new tab: ${study.title}`}
                >
                  Open original study on {study.preferredAccessLabel ?? "the preferred source"} <span aria-hidden="true">↗</span>
                </a>
              ) : <p className="unavailable-note">Original-study links appear here when the Viewer is connected to the real index. This fictional demonstration record has no publication to open.</p>}
            </section>

            <section className="detail-section">
              <div className="detail-heading-row"><h3>Candidate classification</h3><span className={`confidence confidence-${study.classificationConfidence}`}>{sentence(study.classificationConfidence)} confidence</span></div>
              <dl className="classification-grid">
                <div><dt>Match</dt><dd>{study.matchKind === "not_assessed" ? "Not assessed without an active result context" : `${sentence(study.matchKind)} to the current retrieval context`}</dd></div>
                <div><dt>Condition</dt><dd>{study.conditions.join(", ")}</dd></div>
                <div><dt>Cannabinoid</dt><dd>{study.cannabinoids.join(", ")}</dd></div>
                <div><dt>Study design</dt><dd>{sentence(study.studyDesign)}</dd></div>
                <div><dt>Population</dt><dd>{sentence(study.population)}</dd></div>
                <div><dt>Outcome domains</dt><dd>{study.outcomeDomains.map(sentence).join(", ")}</dd></div>
              </dl>
              <p className="semantic-note">{confidenceNote(study.classificationConfidence)}</p>
            </section>

            <section className="detail-section">
              <h3>Evidence used by classification</h3>
              <div className="evidence-list">
                {study.evidence.map((span, index) => (
                  <article key={`${span.field}-${index}`}>
                    <div><span>{sentence(span.field)}</span><b>{span.value}</b></div>
                    <blockquote>“{span.quote}”</blockquote>
                    <p>{span.sourceSection} · {sentence(span.confidence)} candidate confidence</p>
                  </article>
                ))}
              </div>
            </section>

            <section className="detail-section warning-section">
              <h3>Uncertainty and warnings</h3>
              {study.uncertainties.length > 0 ? <ul>{study.uncertainties.map((item) => <li key={item}>{item}</li>)}</ul> : <p>No candidate uncertainty was declared. This is not a human-review claim.</p>}
              <ul>{study.warnings.map((item) => <li key={item}>{item}</li>)}</ul>
            </section>

            <section className="detail-section provenance-section">
              <h3>Provenance</h3>
              <dl className="provenance-list">
                <div><dt>Source trust</dt><dd>{study.provenance.sourceTrustLevel}</dd></div>
                <div><dt>Source hash</dt><dd>{study.provenance.sourceHash}</dd></div>
                <div><dt>Model</dt><dd>{study.provenance.model}</dd></div>
                <div><dt>Prompt</dt><dd>{study.provenance.promptVersion}</dd></div>
                <div><dt>Schema</dt><dd>{study.provenance.schemaVersion}</dd></div>
                <div><dt>Extractor</dt><dd>{study.provenance.extractorVersion}</dd></div>
                <div><dt>Index build</dt><dd>{study.provenance.indexBuildId}</dd></div>
              </dl>
            </section>
          </div>
        )}
      </aside>
    </div>
  );
}

export function DatasetViewer() {
  const [filters, setFilters] = useState<Filters>(defaults);
  const [queryDraft, setQueryDraft] = useState("");
  const [meta, setMeta] = useState<ViewerMeta | null>(null);
  const [response, setResponse] = useState<ViewerSearchResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<StudyDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  useEffect(() => {
    const initial = readFilters();
    const initialStudy = new URLSearchParams(window.location.search).get("study");
    queueMicrotask(() => {
      setFilters(initial);
      setQueryDraft(initial.query);
      setSelectedId(initialStudy);
    });
  }, []);

  useEffect(() => {
    fetch("/api/viewer/meta")
      .then(async (result) => {
        if (!hasJsonPayload(result)) return demoMeta;
        if (!result.ok) throw new Error((await result.json()).detail);
        return result.json();
      })
      .then(setMeta)
      .catch(() => setError("The dataset snapshot is unavailable. Try again shortly."));
  }, []);

  const queryString = useMemo(() => {
    const params = new URLSearchParams();
    FILTER_KEYS.forEach((key) => { if (filters[key] && filters[key] !== defaults[key]) params.set(key, filters[key]); });
    params.set("page", filters.page || "1");
    params.set("pageSize", "6");
    return params.toString();
  }, [filters]);

  useEffect(() => {
    let active = true;
    fetch(`/api/viewer/studies?${queryString}`)
      .then(async (result) => {
        if (!hasJsonPayload(result)) return searchDemoStudies(new URLSearchParams(queryString));
        if (!result.ok) throw new Error((await result.json()).detail);
        return result.json();
      })
      .then((payload) => { if (active) setResponse(payload); })
      .catch(() => { if (active) setError("The read-only dataset service is unavailable. No data was changed."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [queryString]);

  const updateBrowserUrl = useCallback((nextFilters: Filters, studyId: string | null) => {
    const params = new URLSearchParams();
    FILTER_KEYS.forEach((key) => { if (nextFilters[key] && nextFilters[key] !== defaults[key]) params.set(key, nextFilters[key]); });
    if (studyId) params.set("study", studyId);
    window.history.replaceState({}, "", `${window.location.pathname}${params.size ? `?${params}` : ""}`);
  }, []);

  useEffect(() => { updateBrowserUrl(filters, selectedId); }, [filters, selectedId, updateBrowserUrl]);

  const changeFilter = (name: keyof Filters, value: string) => {
    setLoading(true);
    setError(null);
    setFilters((current) => ({
      ...current,
      [name]: value,
      page: name === "page" ? value : "1",
    }));
  };
  const submitSearch = (event: FormEvent) => { event.preventDefault(); changeFilter("query", queryDraft.trim()); };
  const clearFilters = () => { setLoading(true); setError(null); setFilters(defaults); setQueryDraft(""); };

  const openDetail = useCallback((documentId: string) => {
    setSelectedId(documentId); setDetail(null); setDetailLoading(true); setDetailError(null);
    fetch(`/api/viewer/studies/${encodeURIComponent(documentId)}`)
      .then(async (result) => {
        if (!hasJsonPayload(result)) {
          const demoStudy = demoStudies.find((study) => study.documentId === documentId);
          if (!demoStudy) throw new Error("Study not found in the demonstration snapshot.");
          return demoStudy;
        }
        if (!result.ok) throw new Error((await result.json()).detail);
        return result.json();
      })
      .then(setDetail)
      .catch(() => setDetailError("Study detail could not be loaded from this snapshot."))
      .finally(() => setDetailLoading(false));
  }, []);

  useEffect(() => {
    if (selectedId && !detail && !detailLoading) queueMicrotask(() => openDetail(selectedId));
  }, [selectedId, detail, detailLoading, openDetail]);
  const closeDetail = useCallback(() => { setSelectedId(null); setDetail(null); setDetailError(null); }, []);

  return (
    <div className="viewer-shell">
      <section className="viewer-intro shell">
        <div>
          <p className="eyebrow">Read-only candidate retrieval</p>
          <h1>Dataset Viewer</h1>
          <p>Search and inspect evidence-backed candidate classifications without changing the index or protected review state.</p>
        </div>
        <div className="snapshot-card">
          <span className="live-dot">{meta ? (meta.mode === "demo" ? "demo data" : "index online") : "read only"}</span>
          <strong>{meta?.snapshotLabel ?? "Loading snapshot identity…"}</strong>
          <small>{meta ? `${meta.documentCount.toLocaleString()} records in snapshot` : "Read-only mode"}</small>
        </div>
      </section>
      <p className="sr-only">Synthetic demonstration fallback records are not scientific publications or clinical claims.</p>

      {meta?.mode === "demo" && (
        <div className="demo-banner" role="note">
          <div className="shell"><strong>Synthetic demonstration</strong><span>The complete local index is not connected. These records are fictional, so original-study links become available only with a real index.</span></div>
        </div>
      )}

      <div className="viewer-workspace shell">
        <aside className="filters-panel" aria-label="Dataset filters">
          <div className="filters-heading"><div><span className="mono-label">Refine</span><h2>Filters</h2></div><button className="text-button" onClick={clearFilters}>Clear all</button></div>
          <FilterSelect label="Condition" name="condition" value={filters.condition} values={meta?.facets.conditions ?? []} onChange={changeFilter} />
          <FilterSelect label="Cannabinoid" name="cannabinoid" value={filters.cannabinoid} values={meta?.facets.cannabinoids ?? []} onChange={changeFilter} />
          <FilterSelect label="Study design" name="studyDesign" value={filters.studyDesign} values={meta?.facets.studyDesigns ?? []} onChange={changeFilter} />
          <FilterSelect label="Population" name="population" value={filters.population} values={meta?.facets.populations ?? []} onChange={changeFilter} />
          <FilterSelect label="Outcome domain" name="outcome" value={filters.outcome} values={meta?.facets.outcomeDomains ?? []} onChange={changeFilter} />
          <FilterSelect label="Classification confidence" name="confidence" value={filters.confidence} values={meta?.facets.classificationConfidences ?? []} onChange={changeFilter} />
          <FilterSelect label="Review state" name="reviewState" value={filters.reviewState} values={meta?.facets.reviewStates ?? []} onChange={changeFilter} />
          <div className="year-fields">
            <label className="filter-field"><span>Year from</span><input type="number" min="1800" max="2200" value={filters.yearFrom} onChange={(event) => changeFilter("yearFrom", event.target.value)} /></label>
            <label className="filter-field"><span>Year to</span><input type="number" min="1800" max="2200" value={filters.yearTo} onChange={(event) => changeFilter("yearTo", event.target.value)} /></label>
          </div>
          <div className="filters-boundary"><strong>Filter semantics</strong><p>Groups combine with AND. Values are never silently relaxed. Confidence is retrieval metadata, not clinical evidence strength.</p></div>
        </aside>

        <main className="results-panel" id="dataset-results">
          <form className="search-bar" role="search" onSubmit={submitSearch}>
            <label><span className="sr-only">Search candidate studies</span><input type="search" placeholder="Search titles and candidate metadata" value={queryDraft} onChange={(event) => setQueryDraft(event.target.value)} /></label>
            <button className="button button-primary" type="submit">Search</button>
          </form>
          <div className="results-toolbar">
            <div><span className="mono-label">Candidate matches</span><strong>{loading ? "Loading…" : `${response?.total ?? 0} ${(response?.total ?? 0) === 1 ? "result" : "results"}`}</strong></div>
            <label className="sort-field"><span>Sort by</span><select value={filters.sort} onChange={(event) => changeFilter("sort", event.target.value)}>{(meta?.sortOptions ?? [{ value: "confidence", label: "Retrieval confidence" }]).map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
          </div>

          {loading && <div className="results-state" role="status"><span className="loading-line" /><span className="loading-line" /><span className="loading-line short" />Loading candidate records…</div>}
          {error && <div className="results-state error-state" role="alert"><h2>Dataset unavailable</h2><p>{error}</p><button className="button button-secondary" onClick={() => window.location.reload()}>Try again</button></div>}
          {!loading && !error && response?.results.length === 0 && <div className="results-state empty-state"><span aria-hidden="true">0</span><h2>No candidate matches in this snapshot</h2><p>{response.zeroResultMessage}</p><button className="button button-secondary" onClick={clearFilters}>Clear filters</button></div>}
          {!loading && !error && response && response.results.length > 0 && (
            <>
              <div className="table-scroll">
                <table className="studies-table">
                  <caption className="sr-only">AI-classified candidate study matches</caption>
                  <thead><tr><th>Study</th><th>Year</th><th>Condition</th><th>Cannabinoid</th><th>Design / population</th><th>Confidence</th><th>Trust state</th><th>Source</th></tr></thead>
                  <tbody>{response.results.map((study) => <StudyRow key={study.documentId} study={study} onOpen={openDetail} />)}</tbody>
                </table>
              </div>
              <nav className="pagination" aria-label="Results pages">
                <button className="button button-secondary" disabled={response.page <= 1} onClick={() => changeFilter("page", String(response.page - 1))}>← Previous</button>
                <span>Page <strong>{response.page}</strong> of {response.totalPages}</span>
                <button className="button button-secondary" disabled={response.page >= response.totalPages} onClick={() => changeFilter("page", String(response.page + 1))}>Next →</button>
              </nav>
            </>
          )}
          <div className="viewer-disclaimer"><strong>Interpretation boundary</strong><p>Records shown here are candidate matches. Review study detail and the original source before making detailed evidence claims. This interface does not diagnose, prescribe, or recommend treatment.</p></div>
        </main>
      </div>
      {selectedId && <StudyPanel study={detail} loading={detailLoading} error={detailError} onClose={closeDetail} />}
    </div>
  );
}
