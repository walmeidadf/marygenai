import type {
  StudyDetail,
  StudySummary,
  ViewerMeta,
  ViewerSearchResponse,
} from "./viewer-types";

export const ZERO_RESULT_MESSAGE =
  "No candidate records were retrieved from this demonstration snapshot for the current filters. This does not establish absence from the scientific literature.";

const scenarios = [
  ["DEMO-001", "Illustrative cannabidiol study for drug-resistant epilepsy", 2024, "Drug-resistant epilepsy", "Cannabidiol", "randomized controlled trial", "pediatric humans", "efficacy", "high", "high", "direct"],
  ["DEMO-002", "Illustrative safety follow-up for cannabinoid exposure", 2023, "Chronic pain", "THC and CBD", "prospective cohort", "adult humans", "safety", "medium", "medium", "direct"],
  ["DEMO-003", "Illustrative review of cannabinoids and sleep outcomes", 2022, "Sleep disorders", "Cannabinoids", "systematic review", "adult humans", "quality of life", "medium", "high", "direct"],
  ["DEMO-004", "Illustrative preclinical model of inflammatory signaling", 2021, "Inflammation", "Cannabigerol", "preclinical experiment", "animal model", "mechanism", "medium", "medium", "tangential"],
  ["DEMO-005", "Illustrative observational study of symptom reporting", 2020, "Multiple sclerosis", "THC", "cross-sectional study", "adult humans", "symptom control", "low", "low", "tangential"],
  ["DEMO-006", "Illustrative cannabinoid pharmacology evidence synthesis", 2024, "Neuropathic pain", "Cannabidiol", "scoping review", "mixed populations", "mechanism", "medium", "medium", "direct"],
  ["DEMO-007", "Illustrative feasibility study in supportive care", 2019, "Cancer supportive care", "THC and CBD", "single-arm trial", "adult humans", "feasibility", "low", "medium", "direct"],
  ["DEMO-008", "Illustrative evidence map for anxiety research", 2023, "Anxiety", "Cannabidiol", "evidence map", "mixed populations", "quality of life", "medium", "high", "direct"],
  ["DEMO-009", "Illustrative laboratory study of receptor activity", 2018, "Neuroinflammation", "Cannabigerol", "in vitro experiment", "cell model", "mechanism", "high", "medium", "tangential"],
  ["DEMO-010", "Illustrative case series for adverse-event monitoring", 2022, "Epilepsy", "Cannabidiol", "case series", "pediatric humans", "safety", "low", "low", "direct"],
  ["DEMO-011", "Illustrative cohort of patient-reported pain outcomes", 2024, "Chronic pain", "Cannabinoids", "retrospective cohort", "adult humans", "quality of life", "medium", "medium", "direct"],
  ["DEMO-012", "Illustrative umbrella review of neurological conditions", 2021, "Neurological conditions", "Cannabinoids", "umbrella review", "mixed populations", "efficacy", "medium", "high", "tangential"],
] as const;

export const demoStudies: StudyDetail[] = scenarios.map((scenario, index) => {
  const [documentId, title, year, condition, cannabinoid, design, population, outcome, classificationConfidence, retrievalConfidenceBand, matchKind] = scenario;
  const hasUncertainty = index % 3 !== 0;
  return {
    documentId,
    title,
    year,
    conditions: [condition],
    cannabinoids: [cannabinoid],
    studyDesign: design,
    population,
    outcomeDomains: [outcome],
    classificationConfidence,
    retrievalConfidenceBand,
    retrievalConfidenceScore: retrievalConfidenceBand === "high" ? 0.88 - index * 0.01 : retrievalConfidenceBand === "medium" ? 0.69 - index * 0.01 : 0.44 - index * 0.01,
    reviewState: "needs_review",
    trustLevel: "ai_classified_candidate",
    hasUncertainty,
    matchKind,
    identifiers: {},
    evidence: [
      {
        field: "medical_conditions",
        value: condition,
        quote: `Synthetic demonstration span supporting the candidate label “${condition}”.`,
        sourceSection: "Demonstration fixture",
        confidence: classificationConfidence,
      },
      {
        field: "cannabinoids_or_exposures",
        value: cannabinoid,
        quote: `Synthetic demonstration span supporting the candidate exposure “${cannabinoid}”.`,
        sourceSection: "Demonstration fixture",
        confidence: classificationConfidence,
      },
    ],
    uncertainties: hasUncertainty
      ? ["This synthetic record intentionally demonstrates a declared uncertain field."]
      : [],
    warnings: [
      "Synthetic fixture for interface development; not a scientific publication or clinical claim.",
    ],
    provenance: {
      sourceTrustLevel: "synthetic_demo",
      sourceHash: `demo-${String(index + 1).padStart(4, "0")}`,
      model: "not_applicable_synthetic_fixture",
      promptVersion: "not_applicable",
      schemaVersion: "viewer_demo.v1",
      extractorVersion: "not_applicable",
      indexBuildId: "public-demo-2026-08",
    },
  };
});

const unique = <T,>(values: T[]) => [...new Set(values)].sort();

export const demoMeta: ViewerMeta = {
  mode: "demo",
  snapshotId: "public-demo-2026-08",
  snapshotLabel: "Synthetic public demonstration · August 2026",
  documentCount: demoStudies.length,
  sortOptions: [
    { value: "confidence", label: "Retrieval confidence" },
    { value: "year-desc", label: "Newest year" },
    { value: "year-asc", label: "Oldest year" },
    { value: "title", label: "Title A–Z" },
  ],
  facets: {
    conditions: unique(demoStudies.flatMap((study) => study.conditions)),
    cannabinoids: unique(demoStudies.flatMap((study) => study.cannabinoids)),
    studyDesigns: unique(demoStudies.map((study) => study.studyDesign)),
    populations: unique(demoStudies.map((study) => study.population)),
    outcomeDomains: unique(demoStudies.flatMap((study) => study.outcomeDomains)),
    classificationConfidences: ["high", "medium", "low"],
    reviewStates: ["needs_review"],
    years: unique(demoStudies.map((study) => study.year)).sort((a, b) => b - a),
  },
  limitations: [
    "Records are synthetic and demonstrate the interface only.",
    "Search is deterministic lexical matching, not semantic retrieval.",
    "Classification and retrieval confidence are not clinical evidence strength.",
  ],
};

export function searchDemoStudies(params: URLSearchParams): ViewerSearchResponse {
  const query = (params.get("query") ?? "").trim().toLocaleLowerCase();
  const value = (name: string) => (params.get(name) ?? "").trim().toLocaleLowerCase();
  const yearFrom = Number(params.get("yearFrom") || 0);
  const yearTo = Number(params.get("yearTo") || 9999);
  const page = Math.max(1, Number(params.get("page") || 1));
  const pageSize = Math.min(12, Math.max(1, Number(params.get("pageSize") || 6)));
  const sort = params.get("sort") || "confidence";

  const contains = (items: string[], filter: string) =>
    !filter || items.some((item) => item.toLocaleLowerCase() === filter);
  const filtered = demoStudies.filter((study) => {
    const haystack = [study.title, ...study.conditions, ...study.cannabinoids, study.studyDesign, study.population, ...study.outcomeDomains].join(" ").toLocaleLowerCase();
    return (
      (!query || query.split(/\s+/).every((term) => haystack.includes(term))) &&
      contains(study.conditions, value("condition")) &&
      contains(study.cannabinoids, value("cannabinoid")) &&
      (!value("studyDesign") || study.studyDesign.toLocaleLowerCase() === value("studyDesign")) &&
      (!value("population") || study.population.toLocaleLowerCase() === value("population")) &&
      contains(study.outcomeDomains, value("outcome")) &&
      (!value("confidence") || study.classificationConfidence === value("confidence")) &&
      (!value("reviewState") || study.reviewState === value("reviewState")) &&
      study.year >= yearFrom &&
      study.year <= yearTo
    );
  });

  const sorted = [...filtered].sort((a, b) => {
    if (sort === "year-desc") return b.year - a.year || a.documentId.localeCompare(b.documentId);
    if (sort === "year-asc") return a.year - b.year || a.documentId.localeCompare(b.documentId);
    if (sort === "title") return a.title.localeCompare(b.title) || a.documentId.localeCompare(b.documentId);
    return b.retrievalConfidenceScore - a.retrievalConfidenceScore || b.year - a.year || a.documentId.localeCompare(b.documentId);
  });
  const totalPages = Math.max(1, Math.ceil(sorted.length / pageSize));
  const safePage = Math.min(page, totalPages);
  const start = (safePage - 1) * pageSize;
  const results: StudySummary[] = sorted.slice(start, start + pageSize);
  return {
    mode: "demo",
    snapshotId: demoMeta.snapshotId,
    total: sorted.length,
    page: safePage,
    pageSize,
    totalPages,
    sort,
    results,
    zeroResultMessage: ZERO_RESULT_MESSAGE,
  };
}
