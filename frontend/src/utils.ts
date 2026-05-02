import type {
  AppSetting,
  JobType,
  RecommendationDirection,
  RecommendationPlan,
  RecommendationState,
  RunDetailResponse,
  RunDiagnostics,
  RunStatus,
} from "./types";

export interface KeyLabelDetail {
  key: string;
  label: string;
}

export function formatDate(value: string | null): string {
  if (!value) {
    return "—";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString();
}

export function formatDuration(value: number | string | null | undefined): string {
  if (value === null || value === undefined) {
    return "—";
  }
  const numericValue = typeof value === "number" ? value : Number.parseFloat(value);
  if (!Number.isFinite(numericValue)) {
    return "—";
  }
  return `${numericValue.toFixed(2)}s`;
}

export function runTone(status: RunStatus | string): "ok" | "warning" | "danger" | "neutral" {
  if (status === "completed") {
    return "ok";
  }
  if (status === "completed_with_warnings") {
    return "warning";
  }
  if (status === "failed") {
    return "danger";
  }
  return "neutral";
}

export function workerStatusTone(status: string): "ok" | "warning" | "danger" | "neutral" | "info" {
  if (status === "running") {
    return "ok";
  }
  if (status === "idle") {
    return "danger";
  }
  if (status === "stale") {
    return "danger";
  }
  return "neutral";
}

export function workerStreamTone(status: string): "ok" | "warning" | "danger" | "neutral" | "info" {
  if (status === "running") {
    return "ok";
  }
  if (status === "idle") {
    return "info";
  }
  if (status === "stale") {
    return "warning";
  }
  return "neutral";
}

export function dashboardBoardTone(status: string | null | undefined): "ok" | "warning" | "danger" | "neutral" {
  if (status === "healthy") {
    return "ok";
  }
  if (status === "watch" || status === "thin") {
    return "warning";
  }
  if (status === "needs_attention") {
    return "danger";
  }
  return "neutral";
}

export function dashboardFailureTone(status: string): "ok" | "warning" | "danger" | "neutral" {
  if (status === "failed") {
    return "danger";
  }
  return "neutral";
}

export function tickerTone(): "info" {
  return "info";
}

export function jobTypeLabel(jobType: JobType | string): string {
  if (jobType === "proposal_generation") {
    return "Proposal generation";
  }
  if (jobType === "recommendation_evaluation") {
    return "Recommendation evaluation";
  }
  if (jobType === "plan_generation_tuning") {
    return "Plan generation tuning";
  }
  if (jobType === "performance_assessment") {
    return "Performance assessment";
  }
  if (jobType === "macro_context_refresh") {
    return "Macro context refresh";
  }
  if (jobType === "industry_context_refresh") {
    return "Industry context refresh";
  }
  return jobType;
}

export function directionTone(direction: RecommendationDirection | string): "ok" | "danger" | "neutral" {
  if (direction === "LONG") {
    return "ok";
  }
  if (direction === "SHORT") {
    return "danger";
  }
  return "neutral";
}

export function recommendationStateTone(state: RecommendationState | string): "ok" | "danger" | "warning" | "neutral" {
  if (state === "WIN") {
    return "ok";
  }
  if (state === "LOSS") {
    return "danger";
  }
  if (state === "PENDING") {
    return "warning";
  }
  return "neutral";
}

export function tradeOutcomeTone(status: string): "ok" | "danger" | "warning" | "neutral" {
  if (status === "WIN") {
    return "ok";
  }
  if (status === "LOSS") {
    return "danger";
  }
  if (status === "PENDING") {
    return "warning";
  }
  return "neutral";
}

export function brokerExecutionStatusTone(status: string): "ok" | "warning" | "danger" | "neutral" | "info" {
  if (status === "win") {
    return "ok";
  }
  if (status === "loss" || status === "error") {
    return "danger";
  }
  if (status === "open") {
    return "info";
  }
  if (status === "needs_review") {
    return "warning";
  }
  if (status === "submitted" || status === "accepted" || status === "filled" || status === "partially_filled") {
    return "ok";
  }
  if (status === "canceled" || status === "expired") {
    return "warning";
  }
  if (status === "failed" || status === "rejected") {
    return "danger";
  }
  if (status === "skipped") {
    return "warning";
  }
  return "neutral";
}

export function recommendationPlanEvaluationTone(value: string | null | undefined): "ok" | "warning" | "danger" | "neutral" {
  if (value === "win" || value === "entry") {
    return "ok";
  }
  if (value === "loss") {
    return "danger";
  }
  if (value === "pending") {
    return "warning";
  }
  return "neutral";
}

export function recommendationPlanEvaluationLabel(plan: RecommendationPlan): string {
  if (plan.effective_evaluation_source === "broker" && plan.effective_evaluation) {
    return plan.effective_evaluation;
  }
  if (plan.latest_outcome) {
    return plan.latest_outcome.outcome;
  }
  if (plan.effective_evaluation_source === "missing") {
    return "missing";
  }
  return "open";
}

export function recommendationPlanEvaluationSubtitle(plan: RecommendationPlan): string {
  if (plan.effective_evaluation_source === "broker") {
    return plan.effective_evaluation_detail || (plan.broker_order_status ? `broker ${plan.broker_order_status}` : "broker evaluation");
  }
  if (plan.effective_evaluation_source === "missing") {
    return plan.effective_evaluation_detail || "broker evaluation missing";
  }
  if (plan.latest_outcome) {
    return plan.latest_outcome.notes || "simulated evaluation";
  }
  return "simulated evaluation unavailable";
}

export function toSettingMap(settings: AppSetting[]): Record<string, string> {
  return settings.reduce<Record<string, string>>((accumulator, item) => {
    accumulator[item.key] = item.value;
    return accumulator;
  }, {});
}

export function diagnosticsMessages(diagnostics: RunDiagnostics): string[] {
  const seen = new Set<string>();
  const messages: string[] = [];
  const values = [
    ...diagnostics.warnings,
    ...diagnostics.problems,
    ...diagnostics.news_feed_errors,
    ...diagnostics.provider_errors,
    diagnostics.summary_error,
    diagnostics.llm_error,
  ];
  for (const value of values) {
    if (!value || seen.has(value)) {
      continue;
    }
    seen.add(value);
    messages.push(value);
  }
  return messages;
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function normalizeAnalysisJsonForDisplay(value: string | null): string | null {
  if (!value) {
    return null;
  }
  try {
    const parsed = JSON.parse(value) as unknown;
    if (!isRecord(parsed)) {
      return value;
    }
    const normalized: Record<string, unknown> = { ...parsed };
    if (isRecord(normalized.feature_vector)) {
      delete normalized.short_bullish;
      delete normalized.short_bearish;
      delete normalized.medium_bullish;
      delete normalized.medium_bearish;
    }
    return JSON.stringify(normalized, null, 2);
  } catch (_error) {
    return value;
  }
}

export function parseJsonForDisplay(value: string | null): string | null {
  if (!value) {
    return null;
  }
  try {
    return JSON.stringify(JSON.parse(value), null, 2);
  } catch (_error) {
    return value;
  }
}

export function parseJsonRecord(value: string | null): Record<string, unknown> | null {
  if (!value) {
    return null;
  }
  try {
    const parsed = JSON.parse(value) as unknown;
    return isRecord(parsed) ? parsed : null;
  } catch (_error) {
    return null;
  }
}

function extractStringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string" && item.trim().length > 0)
    : [];
}

function appendWarningMessages(target: string[], seen: Set<string>, values: string[], prefix?: string): void {
  for (const value of values) {
    const normalized = value.trim();
    if (!normalized) {
      continue;
    }
    const message = prefix ? `${prefix}: ${normalized}` : normalized;
    if (seen.has(message)) {
      continue;
    }
    seen.add(message);
    target.push(message);
  }
}

export function extractRunWarnings(detail: RunDetailResponse | null): string[] {
  if (!detail) {
    return [];
  }

  const warnings: string[] = [];
  const seen = new Set<string>();
  const summary = parseJsonRecord(detail.run.summary_json);
  const artifact = parseJsonRecord(detail.run.artifact_json);

  appendWarningMessages(warnings, seen, extractStringArray(summary?.warnings));
  appendWarningMessages(warnings, seen, extractStringArray(artifact?.warnings));

  for (const plan of detail.recommendation_plans) {
    appendWarningMessages(warnings, seen, plan.warnings, `${plan.ticker} plan`);
  }
  for (const signal of detail.ticker_signal_snapshots) {
    appendWarningMessages(warnings, seen, signal.warnings, `${signal.ticker} signal`);
  }
  for (const snapshot of detail.macro_context_snapshots) {
    appendWarningMessages(warnings, seen, snapshot.warnings, "Macro context");
  }
  for (const snapshot of detail.industry_context_snapshots) {
    appendWarningMessages(warnings, seen, snapshot.warnings, `${snapshot.industry_label} context`);
  }

  const warningCount = typeof summary?.warning_count === "number" ? summary.warning_count : null;
  const warningsFound = summary?.warnings_found === true;
  if (warnings.length === 0 && (warningsFound || (warningCount !== null && warningCount > 0))) {
    warnings.push("Run was marked completed_with_warnings, but no explicit warning messages were stored.");
  }

  return warnings;
}

function humanizeKey(value: string): string {
  return value.replace(/_/g, " ");
}

export function extractKeyLabelDetails(value: unknown): KeyLabelDetail[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const details: KeyLabelDetail[] = [];
  const seen = new Set<string>();
  for (const item of value) {
    if (!isRecord(item)) {
      continue;
    }
    const key = typeof item.key === "string" && item.key.trim() ? item.key.trim() : null;
    const label = typeof item.label === "string" && item.label.trim()
      ? item.label.trim()
      : key ? humanizeKey(key) : null;
    if (!key || !label || seen.has(key)) {
      continue;
    }
    seen.add(key);
    details.push({ key, label });
  }
  return details;
}

export function detailLabel(detail: unknown, fallback?: string | null, humanizeFallback = true): string | null {
  if (isRecord(detail) && typeof detail.label === "string" && detail.label.trim()) {
    return detail.label.trim();
  }
  if (typeof fallback === "string" && fallback.trim()) {
    return humanizeFallback ? humanizeKey(fallback.trim()) : fallback.trim();
  }
  return null;
}

export function extractDisplayLabels(
  source: Record<string, unknown> | null | undefined,
  detailKey: string,
  fallbackKey: string,
): string[] {
  const detailLabels = extractKeyLabelDetails(source?.[detailKey]).map((item) => item.label);
  if (detailLabels.length > 0) {
    return detailLabels;
  }
  if (!Array.isArray(source?.[fallbackKey])) {
    return [];
  }
  const seen = new Set<string>();
  const labels: string[] = [];
  for (const item of source[fallbackKey] as unknown[]) {
    if (typeof item !== "string") {
      continue;
    }
    const value = item.trim();
    if (!value || seen.has(value)) {
      continue;
    }
    seen.add(value);
    labels.push(humanizeKey(value));
  }
  return labels;
}
export function yahooFinanceUrl(ticker: string): string {
  return `https://finance.yahoo.com/quote/${encodeURIComponent(ticker)}`;
}

