/**
 * Re-export domain types for consumers using the types/ path.
 * The definitions live in lib/types.ts.
 */
export type {
  Unit,
  Direction,
  AnalysisStatus,
  QuestionStatus,
  FinancialMetric,
  DimensionValue,
  AnalysisResult,
  EvidenceItem,
  EvidencePackage,
  Interpretation,
  AnalysisPlan,
  ExplanationDraft,
  QuestionAnswer,
  DatasetSummary,
  Capabilities,
  HealthResponse,
  ApiError,
} from '../lib/types';