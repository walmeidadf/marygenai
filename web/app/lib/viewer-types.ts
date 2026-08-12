export type MatchKind = "direct" | "tangential" | "not_assessed";
export type ReviewState = "needs_review" | "human_reviewed";

export type EvidenceSpan = {
  field: string;
  value: string;
  quote: string;
  sourceSection: string;
  confidence: "high" | "medium" | "low";
};

export type StudySummary = {
  documentId: string;
  title: string;
  year: number;
  conditions: string[];
  cannabinoids: string[];
  studyDesign: string;
  population: string;
  outcomeDomains: string[];
  classificationConfidence: "high" | "medium" | "low";
  retrievalConfidenceBand: "high" | "medium" | "low";
  retrievalConfidenceScore: number;
  reviewState: ReviewState;
  trustLevel: "ai_classified_candidate" | "human_reviewed";
  hasUncertainty: boolean;
  matchKind: MatchKind;
  identifiers: { pmid?: string; pmcid?: string; doi?: string };
  preferredAccessUrl?: string;
  preferredAccessLabel?: string;
};

export type StudyDetail = StudySummary & {
  evidence: EvidenceSpan[];
  uncertainties: string[];
  warnings: string[];
  provenance: {
    sourceTrustLevel: string;
    sourceHash: string;
    model: string;
    promptVersion: string;
    schemaVersion: string;
    extractorVersion: string;
    indexBuildId: string;
  };
};

export type ViewerFacets = {
  conditions: string[];
  cannabinoids: string[];
  studyDesigns: string[];
  populations: string[];
  outcomeDomains: string[];
  classificationConfidences: string[];
  reviewStates: string[];
  years: number[];
};

export type ViewerMeta = {
  mode: "demo" | "index";
  snapshotId: string;
  snapshotLabel: string;
  documentCount: number;
  sortOptions: { value: string; label: string }[];
  facets: ViewerFacets;
  limitations: string[];
};

export type ViewerSearchResponse = {
  mode: "demo" | "index";
  snapshotId: string;
  total: number;
  page: number;
  pageSize: number;
  totalPages: number;
  sort: string;
  results: StudySummary[];
  zeroResultMessage: string;
};
