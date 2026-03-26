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
  | "weight_optimization"
  | "macro_sentiment_refresh"
  | "industry_sentiment_refresh";

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

export type StrategyHorizon = "1d" | "1w" | "1m";

export interface Watchlist {
  id: number | null;
  name: string;
  description: string;
  region: string;
  exchange: string;
  timezone: string;
  default_horizon: StrategyHorizon;
  allow_shorts: boolean;
  optimize_evaluation_timing: boolean;
  tickers: string[];
}

export interface WatchlistEvaluationPolicy {
  watchlist_id: number | null;
  watchlist_name: string;
  default_horizon: StrategyHorizon;
  schedule_source: string;
  schedule_timezone: string;
  primary_cron: string | null;
  primary_window_label: string;
  secondary_window_label: string;
  shortlist_strategy: string;
  warnings: string[];
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
  app_plan_count: number;
  actionable_plan_count: number;
  long_plan_count: number;
  short_plan_count: number;
  no_action_plan_count: number;
  watchlist_plan_count: number;
  open_plan_count: number;
  win_plan_count: number;
  loss_plan_count: number;
  warning_plan_count: number;
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
  recommendation_plans: RecommendationPlan[];
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

export interface AppPreflightReport {
  status: string;
  checked_at: string;
  engine: string;
  checks: PreflightCheck[];
}

export interface DashboardResponse {
  watchlists: Watchlist[];
  jobs: Job[];
  latest_runs: Run[];
  recommendation_plans: RecommendationPlan[];
}

export interface SentimentSnapshot {
  id: number | null;
  scope: "macro" | "industry" | string;
  subject_key: string;
  subject_label: string;
  status: string;
  score: number;
  label: string;
  computed_at: string;
  expires_at: string | null;
  is_expired: boolean;
  coverage: Record<string, unknown>;
  source_breakdown: Record<string, unknown>;
  drivers: string[];
  signals: Record<string, unknown>;
  diagnostics: Record<string, unknown>;
  summary_text: string;
  job_id: number | null;
  run_id: number | null;
}

export interface SentimentSnapshotListResponse {
  snapshots: SentimentSnapshot[];
  scope: string | null;
  limit: number;
}

export interface MacroContextSnapshot {
  id: number | null;
  computed_at: string;
  status: string;
  summary_text: string;
  saliency_score: number;
  confidence_percent: number;
  active_themes: Array<Record<string, unknown>>;
  regime_tags: string[];
  warnings: string[];
  missing_inputs: string[];
  source_breakdown: Record<string, unknown>;
  metadata: Record<string, unknown>;
  run_id: number | null;
  job_id: number | null;
}

export interface IndustryContextSnapshot {
  id: number | null;
  industry_key: string;
  industry_label: string;
  computed_at: string;
  status: string;
  summary_text: string;
  direction: string;
  saliency_score: number;
  confidence_percent: number;
  active_drivers: Array<Record<string, unknown>>;
  linked_macro_themes: string[];
  linked_industry_themes: string[];
  warnings: string[];
  missing_inputs: string[];
  source_breakdown: Record<string, unknown>;
  metadata: Record<string, unknown>;
  run_id: number | null;
  job_id: number | null;
}

export interface TickerSignalSnapshot {
  id: number | null;
  ticker: string;
  horizon: StrategyHorizon;
  computed_at: string;
  status: string;
  direction: string;
  swing_probability_percent: number;
  confidence_percent: number;
  attention_score: number;
  macro_exposure_score: number;
  industry_alignment_score: number;
  ticker_sentiment_score: number;
  technical_setup_score: number;
  catalyst_score: number;
  expected_move_score: number;
  execution_quality_score: number;
  warnings: string[];
  missing_inputs: string[];
  source_breakdown: Record<string, unknown>;
  diagnostics: Record<string, unknown>;
  run_id: number | null;
  job_id: number | null;
}

export interface RecommendationPlanOutcome {
  id: number | null;
  recommendation_plan_id: number;
  ticker: string;
  action: string;
  outcome: string;
  status: string;
  evaluated_at: string;
  entry_touched: boolean | null;
  stop_loss_hit: boolean | null;
  take_profit_hit: boolean | null;
  horizon_return_1d: number | null;
  horizon_return_3d: number | null;
  horizon_return_5d: number | null;
  max_favorable_excursion: number | null;
  max_adverse_excursion: number | null;
  realized_holding_period_days: number | null;
  direction_correct: boolean | null;
  confidence_bucket: string;
  setup_family: string;
  horizon: string | null;
  transmission_bias: string | null;
  context_regime: string | null;
  notes: string;
  run_id: number | null;
}

export interface RecommendationPlan {
  id: number | null;
  ticker: string;
  horizon: StrategyHorizon;
  action: string;
  status: string;
  confidence_percent: number;
  entry_price_low: number | null;
  entry_price_high: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  holding_period_days: number | null;
  risk_reward_ratio: number | null;
  thesis_summary: string;
  rationale_summary: string;
  risks: string[];
  warnings: string[];
  missing_inputs: string[];
  evidence_summary: Record<string, unknown>;
  signal_breakdown: Record<string, unknown>;
  computed_at: string;
  run_id: number | null;
  job_id: number | null;
  watchlist_id: number | null;
  ticker_signal_snapshot_id: number | null;
  latest_outcome: RecommendationPlanOutcome | null;
}

export interface RecommendationCalibrationBucket {
  key: string;
  label: string;
  total_count: number;
  resolved_count: number;
  win_count: number;
  loss_count: number;
  open_count: number;
  no_action_count: number;
  watchlist_count: number;
  sample_status: string;
  min_required_resolved_count: number;
  win_rate_percent: number | null;
  average_return_1d: number | null;
  average_return_3d: number | null;
  average_return_5d: number | null;
  average_mfe: number | null;
  average_mae: number | null;
}

export interface RecommendationCalibrationSummary {
  total_outcomes: number;
  resolved_outcomes: number;
  open_outcomes: number;
  win_outcomes: number;
  loss_outcomes: number;
  no_action_outcomes: number;
  watchlist_outcomes: number;
  overall_win_rate_percent: number | null;
  by_confidence_bucket: RecommendationCalibrationBucket[];
  by_setup_family: RecommendationCalibrationBucket[];
  by_horizon: RecommendationCalibrationBucket[];
  by_transmission_bias: RecommendationCalibrationBucket[];
  by_context_regime: RecommendationCalibrationBucket[];
  by_horizon_setup_family: RecommendationCalibrationBucket[];
}

export interface RecommendationBaselineComparison {
  key: string;
  label: string;
  description: string;
  total_plan_count: number;
  trade_plan_count: number;
  resolved_trade_count: number;
  win_count: number;
  loss_count: number;
  open_trade_count: number;
  win_rate_percent: number | null;
  average_return_5d: number | null;
  average_confidence_percent: number | null;
}

export interface RecommendationBaselineSummary {
  total_plans_reviewed: number;
  total_trade_plans_reviewed: number;
  comparisons: RecommendationBaselineComparison[];
}

export interface RunDetailResponse {
  run: Run;
  outputs: RunOutput[];
  macro_context_snapshots: MacroContextSnapshot[];
  industry_context_snapshots: IndustryContextSnapshot[];
  ticker_signal_snapshots: TickerSignalSnapshot[];
  recommendation_plans: RecommendationPlan[];
}

export interface EvaluationRunResult {
  evaluated_recommendation_plans: number;
  synced_recommendation_plan_outcomes: number;
  pending_recommendation_plan_outcomes: number;
  win_recommendation_plan_outcomes: number;
  loss_recommendation_plan_outcomes: number;
  no_action_recommendation_plan_outcomes: number;
  watchlist_recommendation_plan_outcomes: number;
  output: string;
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
