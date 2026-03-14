export type RunStatus =
  | "queued"
  | "running"
  | "completed"
  | "completed_with_warnings"
  | "failed"
  | "canceled";

export type JobType =
  | "proposal_generation"
  | "recommendation_evaluation"
  | "weight_optimization";

export type RecommendationDirection = "LONG" | "SHORT" | "NEUTRAL";
export type RecommendationState = "PENDING" | "WIN" | "LOSS";

export interface RunDiagnostics {
  warnings: string[];
  provider_errors: string[];
  problems: string[];
  news_feed_errors: string[];
  summary_error: string | null;
  llm_error: string | null;
  raw_output: string | null;
  analysis_json: string | null;
}

export interface Recommendation {
  id: number | null;
  run_id: number | null;
  ticker: string;
  direction: RecommendationDirection;
  confidence: number;
  entry_price: number;
  stop_loss: number;
  take_profit: number;
  indicator_summary: string;
  state: RecommendationState;
  created_at: string;
  evaluated_at: string | null;
}

export interface RunOutput {
  recommendation: Recommendation;
  diagnostics: RunDiagnostics;
}

export interface Watchlist {
  id: number | null;
  name: string;
  tickers: string[];
}

export interface Job {
  id: number | null;
  name: string;
  job_type: JobType;
  tickers: string[];
  watchlist_id: number | null;
  watchlist_name: string | null;
  enabled: boolean;
  cron: string | null;
  last_enqueued_at: string | null;
}

export interface Run {
  id: number | null;
  job_id: number;
  job_type: JobType;
  status: RunStatus;
  error_message: string | null;
  scheduled_for: string | null;
  summary_json: string | null;
  artifact_json: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
  duration_seconds: number | null;
  timing_json: string | null;
}

export interface RecommendationHistoryItem {
  recommendation_id: number;
  run_id: number;
  run_status: string;
  ticker: string;
  direction: RecommendationDirection;
  confidence: number;
  entry_price: number;
  stop_loss: number;
  take_profit: number;
  indicator_summary: string;
  state: RecommendationState;
  created_at: string;
  evaluated_at: string | null;
  warnings: string[];
  provider_errors: string[];
  summary_error: string | null;
  llm_error: string | null;
}

export interface PrototypeTradeLogEntry {
  id: number;
  timestamp: string;
  ticker: string;
  direction: string;
  entry_price: number;
  stop_loss: number;
  take_profit: number;
  confidence: number | null;
  status: string;
  close_timestamp: string | null;
  duration_days: number | null;
  analysis_json: string | null;
}

export interface TickerPerformanceSummary {
  ticker: string;
  app_recommendation_count: number;
  pending_recommendation_count: number;
  win_recommendation_count: number;
  loss_recommendation_count: number;
  warning_recommendation_count: number;
  long_recommendation_count: number;
  short_recommendation_count: number;
  neutral_recommendation_count: number;
  average_confidence: number | null;
  prototype_trade_log_path: string;
  prototype_trade_log_available: boolean;
  prototype_trade_count: number;
  resolved_trade_count: number;
  win_count: number;
  loss_count: number;
  pending_trade_count: number;
  win_rate_percent: number | null;
  average_resolved_duration_days: number | null;
}

export interface TickerAnalysisPage {
  ticker: string;
  performance: TickerPerformanceSummary;
  recommendation_history: RecommendationHistoryItem[];
  prototype_trades: PrototypeTradeLogEntry[];
}

export interface AppSetting {
  key: string;
  value: string;
}

export interface ProviderCredential {
  provider: string;
  api_key: string;
  api_secret: string;
}

export interface PreflightCheck {
  name: string;
  status: string;
  message: string;
  details: string[];
}

export interface PrototypePreflightReport {
  status: string;
  checked_at: string;
  prototype_repo_path: string;
  prototype_script_path: string;
  prototype_python_executable: string;
  checks: PreflightCheck[];
}

export interface DashboardResponse {
  watchlists: Watchlist[];
  jobs: Job[];
  latest_runs: Run[];
  recommendations: Recommendation[];
}

export interface RunDetailResponse {
  run: Run;
  outputs: RunOutput[];
}

export interface RecommendationDetailResponse {
  recommendation: Recommendation;
  run: Run;
  diagnostics: RunDiagnostics;
}

export interface EvaluationRunResult {
  evaluated_trade_log_entries: number;
  synced_recommendations: number;
  pending_recommendations: number;
  win_recommendations: number;
  loss_recommendations: number;
  output: string;
}

export interface HistoryFilters {
  ticker: string;
  direction: string;
  state: string;
  warnings: string;
  sort: string;
  order: string;
  per_page: number;
}

export interface HistoryPagination {
  page: number;
  per_page: number;
  total_results: number;
  total_pages: number;
  has_prev: boolean;
  has_next: boolean;
  prev_page: number;
  next_page: number;
}

export interface HistoryResponse {
  items: RecommendationHistoryItem[];
  filters: HistoryFilters;
  pagination: HistoryPagination;
}

export interface OptimizationFileFingerprint {
  exists: boolean;
  sha256: string | null;
  size_bytes: number | null;
  modified_at: string | null;
}

export interface OptimizationBackup {
  path: string;
  created_at: string;
  fingerprint: OptimizationFileFingerprint;
}

export interface OptimizationState {
  minimum_resolved_trades: number;
  weights_path: string;
  weights: OptimizationFileFingerprint;
  backup_dir: string;
  backup_count: number;
  latest_backup: OptimizationBackup | null;
  recent_backups: OptimizationBackup[];
}

export interface SettingsResponse {
  settings: AppSetting[];
  providers: ProviderCredential[];
  optimization: OptimizationState;
}

export interface DocSection {
  id: string;
  title: string;
  level: number;
}

export interface DocDocument {
  slug: string;
  title: string;
  path: string;
  content: string;
  sections: DocSection[];
}

export interface DocsResponse {
  documents: DocDocument[];
}
