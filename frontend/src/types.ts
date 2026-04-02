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
}

export interface TickerAnalysisPage {
  ticker: string;
  performance: TickerPerformanceSummary;
  recommendation_plans: RecommendationPlan[];
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

export interface AppHealthResponse {
  status: string;
  app: string;
  env: string;
  preflight: {
    status: string;
    engine: string;
    checked_at: string;
  };
  workers: {
    status: string;
    count: number;
    details: string[];
  };
}

export interface WorkerHeartbeat {
  worker_id: string;
  hostname: string;
  pid: number;
  status: string;
  last_heartbeat_at: string;
  started_at: string;
  version: string | null;
  active_run_id: number | null;
  metadata_json: string | null;
  created_at: string;
  updated_at: string;
}

export interface ActiveWorkersResponse {
  status: string;
  count: number;
  stale_seconds: number;
  workers: WorkerHeartbeat[];
}

export interface WorkerLogsResponse {
  worker_id: string;
  log_path: string;
  tail: number;
  line_count: number;
  truncated: boolean;
  updated_at: string;
  lines: string[];
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

export interface SupportSnapshot {
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

export interface SupportSnapshotListResponse {
  snapshots: SupportSnapshot[];
  scope: string | null;
  limit: number;
}


export interface KeyLabelDetail {
  key: string;
  label: string;
}

export interface ContextEventRow {
  key?: string;
  label?: string;
  source_priority?: string;
  source_priority_detail?: KeyLabelDetail;
  persistence_state?: string;
  persistence_state_detail?: KeyLabelDetail;
  window_hint?: string;
  window_hint_detail?: KeyLabelDetail;
  recency_bucket?: string;
  recency_bucket_detail?: KeyLabelDetail;
  transmission_channels?: string[];
  transmission_channel_details?: KeyLabelDetail[];
  contradiction_reasons?: string[];
  contradiction_reason_details?: KeyLabelDetail[];
  [key: string]: unknown;
}

export interface MacroContextSnapshot {
  id: number | null;
  computed_at: string;
  expires_at: string | null;
  status: string;
  summary_text: string;
  saliency_score: number;
  confidence_percent: number;
  active_themes: ContextEventRow[];
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
  expires_at: string | null;
  status: string;
  summary_text: string;
  direction: string;
  saliency_score: number;
  confidence_percent: number;
  active_drivers: ContextEventRow[];
  linked_macro_themes: string[];
  linked_industry_themes: string[];
  warnings: string[];
  missing_inputs: string[];
  source_breakdown: Record<string, unknown>;
  metadata: Record<string, unknown>;
  run_id: number | null;
  job_id: number | null;
}

export interface RecommendationTransmissionSummary {
  alignment_percent?: number;
  context_bias?: string;
  transmission_bias?: string;
  transmission_bias_detail?: KeyLabelDetail;
  transmission_alignment_score?: number;
  catalyst_intensity_percent?: number;
  context_strength_percent?: number;
  context_event_relevance_percent?: number;
  contradiction_count?: number;
  transmission_tags?: string[];
  transmission_tag_details?: KeyLabelDetail[];
  primary_drivers?: string[];
  primary_driver_details?: KeyLabelDetail[];
  industry_exposure_channels?: string[];
  industry_exposure_channel_details?: KeyLabelDetail[];
  ticker_exposure_channels?: string[];
  ticker_exposure_channel_details?: KeyLabelDetail[];
  expected_transmission_window?: string;
  expected_transmission_window_detail?: KeyLabelDetail;
  conflict_flags?: string[];
  conflict_flag_details?: KeyLabelDetail[];
  decay_state?: string;
  transmission_confidence_adjustment?: number;
  lane_hint?: string;
  ticker_relationship_edges?: Array<Record<string, unknown>>;
  matched_ticker_relationships?: Array<Record<string, unknown>>;
  [key: string]: unknown;
}

export interface RecommendationCalibrationReview {
  enabled?: boolean;
  review_status?: string;
  review_status_label?: string;
  raw_confidence_percent?: number;
  calibrated_confidence_percent?: number;
  confidence_adjustment?: number;
  base_confidence_threshold?: number;
  effective_confidence_threshold?: number;
  threshold_adjustment?: number;
  overall_win_rate_percent?: number;
  setup_family?: RecommendationCalibrationBucket | Record<string, unknown>;
  confidence_bucket?: RecommendationCalibrationBucket | Record<string, unknown>;
  horizon?: RecommendationCalibrationBucket | Record<string, unknown>;
  transmission_bias?: RecommendationCalibrationBucket | Record<string, unknown>;
  context_regime?: RecommendationCalibrationBucket | Record<string, unknown>;
  horizon_setup_family?: RecommendationCalibrationBucket | Record<string, unknown>;
  reasons?: string[];
  reason_details?: KeyLabelDetail[];
  [key: string]: unknown;
}

export interface RecommendationPlanEvidenceSummary {
  summary?: string;
  setup_family?: string;
  action_reason?: string;
  action_reason_label?: string;
  action_reason_detail?: string;
  confidence_components?: Record<string, number>;
  raw_confidence_percent?: number;
  calibrated_confidence_percent?: number;
  confidence_adjustment?: number;
  calibration_review?: RecommendationCalibrationReview;
  transmission_summary?: RecommendationTransmissionSummary;
  entry_style?: string;
  stop_style?: string;
  target_style?: string;
  timing_expectation?: string;
  evaluation_focus?: string[];
  invalidation_summary?: string;
  [key: string]: unknown;
}

export interface RecommendationPlanSignalBreakdown {
  attention_score?: number;
  macro_exposure_score?: number;
  industry_alignment_score?: number;
  ticker_sentiment_score?: number;
  technical_setup_score?: number;
  catalyst_score?: number;
  expected_move_score?: number;
  execution_quality_score?: number;
  setup_family?: string;
  confidence_components?: Record<string, number>;
  raw_confidence_percent?: number;
  calibrated_confidence_percent?: number;
  confidence_bucket?: string;
  calibration_review?: RecommendationCalibrationReview;
  transmission_summary?: RecommendationTransmissionSummary;
  mode?: string;
  [key: string]: unknown;
}

export interface TickerSignalDiagnostics extends RecommendationTransmissionSummary {
  mode?: string;
  shortlisted?: boolean;
  shortlist_rank?: number;
  shortlist_reasons?: string[];
  shortlist_reason_details?: KeyLabelDetail[];
  shortlist_eligible?: boolean;
  selection_lane?: string;
  selection_lane_label?: string;
  cheap_scan_confidence_percent?: number;
  cheap_scan_directional_score?: number;
  catalyst_proxy_score?: number;
  cheap_scan_component_scores?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface TickerSignalSourceBreakdown extends RecommendationTransmissionSummary {
  cheap_scan_summary?: string;
  cheap_scan_model?: string | null;
  deep_analysis_available?: boolean;
  deep_analysis_model?: string | null;
  summary_method?: string | null;
  base_confidence_percent?: number;
  [key: string]: unknown;
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
  source_breakdown: TickerSignalSourceBreakdown;
  diagnostics: TickerSignalDiagnostics;
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
  transmission_bias_label: string | null;
  transmission_bias_detail: KeyLabelDetail | null;
  context_regime: string | null;
  context_regime_label: string | null;
  context_regime_detail: KeyLabelDetail | null;
  notes: string;
  run_id: number | null;
}

export interface RecommendationDecisionSample {
  id: number | null;
  recommendation_plan_id: number;
  ticker: string;
  horizon: string;
  action: string;
  decision_type: string;
  decision_reason: string;
  shortlisted: boolean;
  shortlist_rank: number | null;
  shortlist_decision: Record<string, unknown>;
  confidence_percent: number;
  calibrated_confidence_percent: number | null;
  effective_threshold_percent: number | null;
  confidence_gap_percent: number | null;
  setup_family: string;
  transmission_bias: string | null;
  context_regime: string | null;
  review_priority: string;
  review_label: string | null;
  review_notes: string;
  reviewed_at: string | null;
  decision_context: Record<string, unknown>;
  signal_breakdown: Record<string, unknown>;
  evidence_summary: Record<string, unknown>;
  run_id: number | null;
  job_id: number | null;
  watchlist_id: number | null;
  ticker_signal_snapshot_id: number | null;
  created_at: string;
  updated_at: string;
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
  evidence_summary: RecommendationPlanEvidenceSummary;
  signal_breakdown: RecommendationPlanSignalBreakdown;
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
  slice_name: string;
  slice_label: string;
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

export interface RecommendationPlanStats {
  total_plans: number;
  resolved_outcomes: number;
  open_outcomes: number;
  win_outcomes: number;
  loss_outcomes: number;
  no_action_outcomes: number;
  watchlist_outcomes: number;
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
  family_cohorts: RecommendationBaselineComparison[];
}

export interface RecommendationSetupFamilyReview {
  family: string;
  label: string;
  total_outcomes: number;
  resolved_outcomes: number;
  open_outcomes: number;
  win_outcomes: number;
  loss_outcomes: number;
  overall_win_rate_percent: number | null;
  average_return_1d: number | null;
  average_return_3d: number | null;
  average_return_5d: number | null;
  average_mfe: number | null;
  average_mae: number | null;
  by_horizon: RecommendationCalibrationBucket[];
  by_transmission_bias: RecommendationCalibrationBucket[];
  by_context_regime: RecommendationCalibrationBucket[];
}

export interface RecommendationSetupFamilyReviewSummary {
  total_outcomes_reviewed: number;
  families: RecommendationSetupFamilyReview[];
}

export interface RecommendationEvidenceConcentrationCohort {
  slice_name: string;
  slice_label: string;
  key: string;
  label: string;
  sample_status: string;
  resolved_count: number;
  min_required_resolved_count: number;
  win_rate_percent: number | null;
  average_return_5d: number | null;
  edge_vs_overall_win_rate_percent: number | null;
  edge_vs_overall_return_5d: number | null;
  concentration_score: number;
  interpretation: string;
}

export interface RecommendationEvidenceConcentrationSummary {
  total_outcomes_reviewed: number;
  resolved_outcomes_reviewed: number;
  overall_win_rate_percent: number | null;
  overall_average_return_5d: number | null;
  ready_for_expansion: boolean;
  focus_message: string;
  strongest_positive_cohorts: RecommendationEvidenceConcentrationCohort[];
  weakest_cohorts: RecommendationEvidenceConcentrationCohort[];
}

export interface RunDetailResponse {
  run: Run;
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

export interface SignalGatingTuningState {
  threshold_offset: number;
  confidence_adjustment: number;
  near_miss_gap_cutoff: number;
  shortlist_aggressiveness: number;
  degraded_penalty: number;
}

export interface SignalGatingTuningCandidateResult {
  threshold: number | null;
  score: number | null;
  selected_count: number;
  resolved_selected_count: number;
  resolved_sample_count: number;
  win_count: number;
  loss_count: number;
  skipped_win_count: number;
  skipped_loss_count: number;
  shortlisted_selected_count: number;
  near_miss_selected_count: number;
  degraded_selected_count: number;
  true_positive_count: number;
  false_positive_count: number;
  false_negative_count: number;
  true_negative_count: number;
  selection_rate_percent: number | null;
  precision_percent: number | null;
  recall_percent: number | null;
  win_rate_percent: number | null;
  threshold_offset: number;
  confidence_adjustment: number;
  near_miss_gap_cutoff: number;
  shortlist_aggressiveness: number;
  degraded_penalty: number;
  [key: string]: unknown;
}

export interface SignalGatingTuningRun {
  id: number | null;
  objective_name: string;
  status: string;
  applied: boolean;
  filters: Record<string, unknown>;
  sample_count: number;
  resolved_sample_count: number;
  candidate_count: number;
  baseline_threshold: number | null;
  baseline_score: number | null;
  best_threshold: number | null;
  best_score: number | null;
  winning_config: Record<string, unknown>;
  candidate_results: SignalGatingTuningCandidateResult[];
  summary: Record<string, unknown>;
  artifact: Record<string, unknown>;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface SignalGatingTuningResponse {
  objective_name: string;
  current_confidence_threshold: number;
  active_tuning: SignalGatingTuningState;
  latest_run: SignalGatingTuningRun | null;
}

export interface SignalGatingTuningRunsResponse {
  runs: SignalGatingTuningRun[];
  limit: number;
}

export interface SettingsResponse {
  settings: AppSetting[];
  providers: ProviderCredential[];
  optimization: OptimizationState;
  signal_gating_tuning: SignalGatingTuningState;
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
