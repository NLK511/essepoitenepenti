import type {
  AppSetting,
  JobType,
  RecommendationDirection,
  RecommendationState,
  RunDiagnostics,
  RunStatus,
} from "./types";

export interface SupportSnapshotReference {
  scope: string;
  snapshotId: number;
  subjectKey: string | null;
  subjectLabel: string | null;
  source: string | null;
  label: string | null;
  score: number | null;
}

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
  if (jobType === "macro_sentiment_refresh") {
    return "Macro context refresh";
  }
  if (jobType === "industry_sentiment_refresh") {
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

export function extractSupportSnapshotReferences(value: string | null): SupportSnapshotReference[] {
  const parsed = parseJsonRecord(value);
  const sentiment = parsed && isRecord(parsed.sentiment) ? parsed.sentiment : null;
  if (!sentiment) {
    return [];
  }
  const references: SupportSnapshotReference[] = [];
  for (const scope of ["macro", "industry"]) {
    const section = sentiment[scope];
    if (!isRecord(section)) {
      continue;
    }
    const snapshotId = section.snapshot_id;
    if (typeof snapshotId !== "number") {
      continue;
    }
    references.push({
      scope,
      snapshotId,
      subjectKey: typeof section.subject_key === "string" ? section.subject_key : null,
      subjectLabel: typeof section.subject_label === "string" ? section.subject_label : null,
      source: typeof section.source === "string" ? section.source : null,
      label: typeof section.label === "string" ? section.label : null,
      score: typeof section.score === "number" ? section.score : null,
    });
  }
  return references;
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
