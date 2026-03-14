import type {
  AppSetting,
  JobType,
  RecommendationDirection,
  RecommendationHistoryItem,
  RecommendationState,
  RunDiagnostics,
  RunOutput,
  RunStatus,
} from "./types";

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

export function runTone(status: RunStatus): "ok" | "warning" | "danger" | "neutral" {
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
  if (jobType === "weight_optimization") {
    return "Weight optimization";
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

export function warningCount(item: RecommendationHistoryItem | RunOutput): number {
  if ("diagnostics" in item) {
    return diagnosticsMessages(item.diagnostics).length;
  }
  const messages = [...item.warnings, ...item.provider_errors];
  if (item.summary_error) {
    messages.push(item.summary_error);
  }
  if (item.llm_error) {
    messages.push(item.llm_error);
  }
  return new Set(messages.filter(Boolean)).size;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
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
