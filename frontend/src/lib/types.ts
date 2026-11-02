/**
 * FinSight API types — generated from the backend Pydantic schemas.
 *
 * All financial values are computed deterministically in Python/Pandas.
 * The LLM only interprets questions and explains validated evidence.
 */

export type Unit = 'currency' | 'percent' | 'count' | 'ratio';
export type Direction = 'increase' | 'decrease' | 'flat' | 'unknown';
export type AnalysisStatus = 'succeeded' | 'failed' | 'partial';
export type QuestionStatus = 'answered' | 'unsupported' | 'failed';

export interface FinancialMetric {
  id: string;
  label: string;
  value: number;
  unit: Unit;
  currency: string | null;
  period: string | null;
  comparison_period: string | null;
  comparison_value: number | null;
  change: number | null;
  percentage_change: number | null;
  source_dataset: string;
  calculation: string;
  formula_inputs: Record<string, number>;
}

export interface DimensionValue {
  dimension: string;
  key: string;
  label: string;
  metric: string | null;
  value: number;
  comparison_value: number | null;
  change: number | null;
  percentage_change: number | null;
  share_of_total_pct: number | null;
  transaction_count: number | null;
  contribution_to_change_pct: number | null;
}

export interface AnalysisResult {
  analysis_id: string;
  status: AnalysisStatus;
  analysis_type: string;
  metric: string;
  period: string | null;
  comparison_period: string | null;
  metrics: FinancialMetric[];
  breakdown: DimensionValue[];
  series: DimensionValue[];
  methodology: string[];
  warnings: string[];
  row_count: number;
  duration_ms: number;
  datasets_used: string[];
}

export interface EvidenceItem {
  id: string;
  metric: string;
  label: string;
  value: number;
  unit: Unit;
  currency: string | null;
  period: string | null;
  comparison_period: string | null;
  comparison_value: number | null;
  change: number | null;
  percentage_change: number | null;
  direction: Direction;
  share_of_total_pct: number | null;
  contribution_to_change_pct: number | null;
  source_dataset: string;
  source_fields: string[];
  calculation: string;
  is_derived: boolean;
}

export interface EvidencePackage {
  evidence: EvidenceItem[];
  datasets_used: string[];
  periods_covered: string[];
  notes: string[];
}

export interface Interpretation {
  restated_question: string;
  intent: string;
  analysis_type: string | null;
  metric: string | null;
  period: string | null;
  comparison_period: string | null;
  dimensions: string[];
  strategy: string;
  confidence: number;
  notes: string[];
}

export interface AnalysisPlan {
  analysis_type: string;
  metric: string;
  period: string | null;
  comparison_period: string | null;
  comparison_mode: string;
  dimensions: string[];
  filters: { field: string; values: string[] }[];
  limit: number;
}

export interface ExplanationDraft {
  summary: string;
  detail: string;
  findings: string[];
  grounded_on: string[];
  provider: string;
  model: string | null;
  generated_at: string;
}

export interface QuestionAnswer {
  answer_id: string;
  status: QuestionStatus;
  question: string;
  interpretation: Interpretation;
  plan: AnalysisPlan | null;
  analyses: AnalysisResult[];
  evidence: EvidencePackage;
  explanation: ExplanationDraft;
  caveats: string[];
  llm_enabled: boolean;
  duration_ms: number;
  created_at: string;
}

export interface DatasetSummary {
  id: string;
  label: string;
  description: string;
  row_count: number;
  column_count: number;
  period_start: string | null;
  period_end: string | null;
  metrics: string[];
  integrity_checks: { id: string; description: string; passed: boolean; observed: string }[];
}

export interface Capabilities {
  metrics: { id: string; label: string; unit: Unit; source_dataset: string; formula: string }[];
  analysis_types: { id: string; label: string; supported_metrics: string[] }[];
  periods: string[];
  currency: string;
}

export interface HealthResponse {
  status: 'ok' | 'degraded';
  service: string;
  version: string;
  environment: string;
  datasets_loaded: number;
  llm_enabled: boolean;
  checks: Record<string, string>;
}

export interface ApiError {
  error: { code: string; message: string; details: Record<string, unknown> };
}