import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { deleteJson, getJson } from "../api";
import { WorkflowRunResults } from "../components/workflow-run-results";
import { useToast } from "../components/toast";
import { Badge, Card, EmptyState, ErrorState, LoadingState, PageHeader, SectionTitle } from "../components/ui";
import type { Job, RunDetailResponse, WatchlistEvaluationPolicy } from "../types";
import { diagnosticsMessages, directionTone, extractSentimentSnapshotReferences, formatDate, formatDuration, isRecord, jobTypeLabel, parseJsonRecord, recommendationStateTone, runTone } from "../utils";

function scoreColor(value: number, min = -1, max = 1) {
  if (!Number.isFinite(value) || max <= min) {
    return undefined;
  }
  const clamped = Math.max(min, Math.min(max, value));
  const ratio = (clamped - min) / (max - min);
  const hue = ratio * 120;
  return `hsl(${hue}, 75%, 45%)`;
}

function biasTone(value: string): "ok" | "warning" | "neutral" {
  if (value === "tailwind") {
    return "ok";
  }
  if (value === "headwind") {
    return "warning";
  }
  return "neutral";
}

const DOC_BASE = "https://github.com/NLK511/essepoitenepenti/blob/main/docs/recommendation-methodology.md";

const INFO_DESCRIPTIONS = {
  trading: {
    description: "Review the entry, stop loss, and take profit structure that defines the proposal",
    link: `${DOC_BASE}#proposal-structure`,
  },
  summary: {
    description: "See how summary methods and enhanced sentiment characterise the recommendation narrative",
    link: `${DOC_BASE}#summary-and-sentiment`,
  },
  diagnostics: {
    description: "Dive into structured signals and diagnostic warnings recorded for this recommendation",
    link: `${DOC_BASE}#structured-diagnostics`,
  },
  messages: {
    description: "Understand warning classification that operators see when data arrives incomplete",
    link: `${DOC_BASE}#diagnostics`,
  },
  raw: {
    description: "Inspect the raw JSON emitted by the pipeline if you need the un-parsed payload",
    link: `${DOC_BASE}#raw-output`,
  },
  contextFlags: {
    description: "Context flags flag key conditions that influenced this proposal",
    link: `${DOC_BASE}#context-flags`,
  },
  highlights: {
    description: "Normalized highlight metrics show how feature vectors compare across runs",
    link: `${DOC_BASE}#feature-vectors`,
  },
  aggregations: {
    description: "Aggregator totals summarize counts or dollar amounts used in scoring",
    link: `${DOC_BASE}#aggregations`,
  },
  weights: {
    description: "Confidence weights show how each signal contributed to the final recommendation",
    link: `${DOC_BASE}#confidence-weights`,
  },
  news: {
    description: "News coverage aggregates headline data and sentiment for this ticker",
    link: `${DOC_BASE}#news-coverage`,
  },
  coverage: {
    description: "Understand why sentiment stayed neutral by reviewing keyword hits and missing coverage",
    link: `${DOC_BASE}#sentiment-coverage`,
  },
  fieldEntry: {
    description: "Entry price defines where the system would enter the position",
    link: `${DOC_BASE}#proposal-structure`,
  },
  fieldStop: {
    description: "Stop loss caps downside risk for this recommendation",
    link: `${DOC_BASE}#proposal-structure`,
  },
  fieldTake: {
    description: "Take profit outlines the target level for the trade",
    link: `${DOC_BASE}#proposal-structure`,
  },
  summaryMethod: {
    description: "The summary method tells you which service provided this narrative",
    link: `${DOC_BASE}#summary-and-sentiment`,
  },
};

function InfoBadge({ description, link }: { description: string; link: string }) {
  return (
    <a
      className="info-badge"
      href={link}
      target="_blank"
      rel="noreferrer"
      title={description}
    >
      ?
    </a>
  );
}

function calibrationSliceSummary(value: unknown, label: string): string {
  const item = isRecord(value) ? (value as Record<string, unknown>) : null;
  if (!item) {
    return `${label} —`;
  }
  const key = typeof item.key === "string" ? item.key : label;
  const sampleStatus = typeof item.sample_status === "string" ? item.sample_status : "unknown";
  const resolvedCount = typeof item.resolved_count === "number" ? item.resolved_count : 0;
  const winRate = typeof item.win_rate_percent === "number" ? `${item.win_rate_percent}%` : "—";
  return `${label} ${key} · ${sampleStatus} · n=${resolvedCount} · win ${winRate}`;
}

export function RunDetailPage() {
  const { runId } = useParams<{ runId: string }>();
  const navigate = useNavigate();
  const { showToast } = useToast();
  const [detail, setDetail] = useState<RunDetailResponse | null>(null);
  const [watchlistPolicy, setWatchlistPolicy] = useState<WatchlistEvaluationPolicy | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  useEffect(() => {
    async function load() {
      if (!runId) {
        setError("Run id is missing");
        return;
      }
      try {
        setError(null);
        const runDetail = await getJson<RunDetailResponse>(`/api/runs/${runId}`);
        setDetail(runDetail);
        const jobs = await getJson<Job[]>("/api/jobs");
        const job = jobs.find((item) => item.id === runDetail.run.job_id);
        if (job?.watchlist_id) {
          setWatchlistPolicy(await getJson<WatchlistEvaluationPolicy>(`/api/watchlists/${job.watchlist_id}/policy`));
        } else {
          setWatchlistPolicy(null);
        }
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : "Failed to load run");
      }
    }
    void load();
  }, [runId]);

  async function handleDelete() {
    if (!detail?.run.id) {
      return;
    }
    if (
      !window.confirm(
        `Delete run #${detail.run.id}? This will permanently remove the run and its associated recommendations and diagnostics.`,
      )
    ) {
      return;
    }
    setDeleteError(null);
    setIsDeleting(true);
    try {
      await deleteJson<{ deleted: boolean; run_id: number }>(`/api/runs/${detail.run.id}`);
      showToast({ message: `Run #${detail.run.id} deleted`, tone: "success" });
      navigate("/jobs/debugger");
    } catch (deleteErr) {
      setDeleteError(deleteErr instanceof Error ? deleteErr.message : "Failed to delete run");
    } finally {
      setIsDeleting(false);
    }
  }

  const runSummary = parseJsonRecord(detail?.run.summary_json ?? null);
  const runArtifact = parseJsonRecord(detail?.run.artifact_json ?? null);
  const artifactSnapshotIds = Array.isArray(runArtifact?.snapshot_ids)
    ? runArtifact.snapshot_ids.filter((value): value is number => typeof value === "number")
    : [];
  const artifactSnapshotId = typeof runArtifact?.snapshot_id === "number" ? runArtifact.snapshot_id : null;
  const shortlistRules = isRecord(runSummary?.shortlist_rules) ? runSummary.shortlist_rules : null;
  const shortlistRejections = isRecord(runSummary?.shortlist_rejections) ? runSummary.shortlist_rejections : null;
  const shortlistDecisions = Array.isArray(runArtifact?.shortlist_decisions)
    ? runArtifact.shortlist_decisions.filter((item): item is Record<string, unknown> => isRecord(item))
    : [];
  const orchestrationSourceKind = typeof runSummary?.source_kind === "string"
    ? runSummary.source_kind
    : typeof runArtifact?.source_kind === "string"
      ? runArtifact.source_kind
      : null;
  const orchestrationExecutionPath = typeof runSummary?.execution_path === "string"
    ? runSummary.execution_path
    : typeof runArtifact?.execution_path === "string"
      ? runArtifact.execution_path
      : null;
  const orchestrationEffectiveHorizon = typeof runSummary?.effective_horizon === "string"
    ? runSummary.effective_horizon
    : typeof runArtifact?.effective_horizon === "string"
      ? runArtifact.effective_horizon
      : null;
  const manualJobDefaults = isRecord(runSummary?.manual_job_defaults)
    ? runSummary.manual_job_defaults
    : isRecord(runArtifact?.manual_job_defaults)
      ? runArtifact.manual_job_defaults
      : null;

  return (
    <>
      <PageHeader
        kicker="Run detail"
        title={detail ? `Run #${detail.run.id}` : "Run detail"}
        subtitle="A run is one job execution. This page focuses on execution state and the recommendations produced by that run, not on treating the run itself as the trade output."
        actions={
          <>
            <Link to="/jobs/debugger" className="button-secondary">Back to debugger</Link>
            <Link to="/jobs/recommendation-plans" className="button-subtle">Browse recommendation plans</Link>
            {detail ? (
              <button
                type="button"
                className="button button-danger"
                disabled={isDeleting}
                onClick={handleDelete}
              >
                {isDeleting ? "Deleting…" : "Delete run"}
              </button>
            ) : null}
          </>
        }
      />
      {deleteError ? <ErrorState message={deleteError} /> : null}
      {error ? <ErrorState message={error} /> : null}
      {!detail && !error ? <LoadingState message="Loading run detail…" /> : null}
      {detail ? (
        <div className="stack-page">
          <Card>
            <div className="cluster">
              <Badge tone={runTone(detail.run.status)}>{detail.run.status}</Badge>
              <Badge>Job {detail.run.job_id}</Badge>
              <Badge>{jobTypeLabel(detail.run.job_type)}</Badge>
              <Badge>{formatDuration(detail.run.duration_seconds)}</Badge>
            </div>
            <div className="helper-text">Created {formatDate(detail.run.created_at)}</div>
            <div className="helper-text">Scheduled slot {formatDate(detail.run.scheduled_for)}</div>
            <div className="helper-text">Started {formatDate(detail.run.started_at)}</div>
            <div className="helper-text">Completed {formatDate(detail.run.completed_at)}</div>
            {detail.run.error_message ? <div className="alert alert-danger top-gap-small">{detail.run.error_message}</div> : null}
            {detail.run.timing_json ? (
              <div className="helper-text top-gap-small">Timing data is available but hidden on this page to keep the view focused on the trade proposal.</div>
            ) : null}
            {artifactSnapshotId ? (
              <div className="top-gap-small">
                <Link to={`/sentiment/${artifactSnapshotId}`} className="button-subtle">Open created snapshot</Link>
              </div>
            ) : null}
            {artifactSnapshotIds.length > 0 ? (
              <div className="top-gap-small cluster">
                {artifactSnapshotIds.map((snapshotId) => (
                  <Link key={snapshotId} to={`/sentiment/${snapshotId}`} className="button-subtle">Snapshot #{snapshotId}</Link>
                ))}
              </div>
            ) : null}
          </Card>

          {detail.ticker_signal_snapshots.length > 0 || detail.recommendation_plans.length > 0 || detail.macro_context_snapshots.length > 0 || detail.industry_context_snapshots.length > 0 ? (
            <Card>
              <SectionTitle
                kicker="Redesign orchestration"
                title="Cheap scan, shortlist, deep analysis, and plan outputs"
                subtitle="These persisted redesign objects show what the orchestration layer scanned, shortlisted, and converted into actionable or no-action plans."
                actions={
                  <>
                    <Link to={detail.run.id ? `/jobs/ticker-signals?run_id=${detail.run.id}` : "/jobs/ticker-signals"} className="button-subtle">Browse ticker signals</Link>
                    <Link to={detail.run.id ? `/jobs/recommendation-plans?run_id=${detail.run.id}` : "/jobs/recommendation-plans"} className="button-subtle">Browse recommendation plans</Link>
                  </>
                }
              />
              <div className="stack-page">
                {orchestrationSourceKind || orchestrationExecutionPath || orchestrationEffectiveHorizon || manualJobDefaults ? (
                  <section>
                    <div className="section-heading">
                      <strong>Execution source</strong>
                    </div>
                    <div className="cluster top-gap-small">
                      {orchestrationSourceKind ? (
                        <Badge tone={orchestrationSourceKind === "manual_tickers" ? "warning" : "info"}>
                          source: {orchestrationSourceKind}
                        </Badge>
                      ) : null}
                      {orchestrationExecutionPath ? <Badge tone="info">path: {orchestrationExecutionPath}</Badge> : null}
                      {orchestrationEffectiveHorizon ? <Badge tone="info">effective horizon: {orchestrationEffectiveHorizon}</Badge> : null}
                    </div>
                    {orchestrationSourceKind === "manual_tickers" ? (
                      <div className="top-gap-small">
                        <div className="helper-text">
                          Manual ticker jobs now run through redesign orchestration using an explicit synthetic wrapper instead of the old legacy-only loop.
                        </div>
                        <div className="helper-text">
                          Recommendation plans and outcomes are the canonical review path; new proposal runs no longer emit legacy recommendation artifacts.
                        </div>
                      </div>
                    ) : null}
                    {manualJobDefaults ? (
                      <div className="cluster top-gap-small">
                        <Badge tone="info">default horizon: {typeof manualJobDefaults.default_horizon === "string" ? manualJobDefaults.default_horizon : "—"}</Badge>
                        <Badge tone={manualJobDefaults.allow_shorts === true ? "warning" : "neutral"}>
                          {manualJobDefaults.allow_shorts === true ? "shorts enabled" : "shorts disabled"}
                        </Badge>
                        <Badge tone={manualJobDefaults.optimize_evaluation_timing === true ? "ok" : "neutral"}>
                          {manualJobDefaults.optimize_evaluation_timing === true ? "optimized timing on" : "optimized timing off"}
                        </Badge>
                      </div>
                    ) : null}
                    {typeof manualJobDefaults?.job_name === "string" ? (
                      <div className="helper-text top-gap-small">Synthetic wrapper job name: {manualJobDefaults.job_name}</div>
                    ) : null}
                  </section>
                ) : null}

                {watchlistPolicy ? (
                  <section>
                    <div className="section-heading">
                      <strong>Watchlist policy</strong>
                    </div>
                    <div className="cluster top-gap-small">
                      <Badge tone="info">source: {watchlistPolicy.schedule_source}</Badge>
                      <Badge tone="info">timezone: {watchlistPolicy.schedule_timezone || "—"}</Badge>
                      <Badge tone={watchlistPolicy.primary_cron ? "ok" : "neutral"}>
                        cron: {watchlistPolicy.primary_cron ?? "none"}
                      </Badge>
                      <Badge tone="info">horizon: {watchlistPolicy.default_horizon}</Badge>
                      <Badge tone="info">strategy: {watchlistPolicy.shortlist_strategy}</Badge>
                    </div>
                    <div className="helper-text top-gap-small">Primary window: {watchlistPolicy.primary_window_label || "—"}</div>
                    {watchlistPolicy.secondary_window_label ? (
                      <div className="helper-text">Secondary window: {watchlistPolicy.secondary_window_label}</div>
                    ) : null}
                    {watchlistPolicy.warnings.length > 0 ? (
                      <div className="cluster top-gap-small">
                        {watchlistPolicy.warnings.map((warning) => (
                          <Badge key={warning} tone="warning">{warning}</Badge>
                        ))}
                      </div>
                    ) : null}
                  </section>
                ) : null}

                {shortlistRules || shortlistDecisions.length > 0 ? (
                  <section>
                    <div className="section-heading">
                      <strong>Shortlist reasoning</strong>
                    </div>
                    {shortlistRules ? (
                      <div className="cluster top-gap-small">
                        <Badge tone="info">limit {typeof shortlistRules.limit === "number" ? shortlistRules.limit : "—"}</Badge>
                        <Badge tone="info">core {typeof shortlistRules.core_limit === "number" ? shortlistRules.core_limit : "—"}</Badge>
                        <Badge tone="info">catalyst lane {typeof shortlistRules.catalyst_lane_limit === "number" ? shortlistRules.catalyst_lane_limit : "—"}</Badge>
                        <Badge tone="info">min confidence {typeof shortlistRules.minimum_confidence_percent === "number" ? `${shortlistRules.minimum_confidence_percent}%` : "—"}</Badge>
                        <Badge tone="info">min attention {typeof shortlistRules.minimum_attention_score === "number" ? shortlistRules.minimum_attention_score : "—"}</Badge>
                        <Badge tone="info">min catalyst proxy {typeof shortlistRules.minimum_catalyst_proxy_score === "number" ? shortlistRules.minimum_catalyst_proxy_score : "—"}</Badge>
                        <Badge tone={shortlistRules.allow_shorts === true ? "warning" : "neutral"}>{shortlistRules.allow_shorts === true ? "shorts allowed" : "shorts disabled"}</Badge>
                      </div>
                    ) : null}
                    {shortlistRejections ? (
                      <div className="top-gap-small helper-text">
                        Rejections: {Object.entries(shortlistRejections).map(([reason, count]) => `${reason} ${count}`).join(" · ") || "none"}
                      </div>
                    ) : null}
                    {shortlistDecisions.length > 0 ? (
                      <div className="table-wrap top-gap-small">
                        <table>
                          <thead>
                            <tr>
                              <th>Ticker</th>
                              <th>Outcome</th>
                              <th>Lane</th>
                              <th>Rank</th>
                              <th>Confidence</th>
                              <th>Attention</th>
                              <th>Catalyst proxy</th>
                              <th>Reasons</th>
                            </tr>
                          </thead>
                          <tbody>
                            {shortlistDecisions.map((decision, index) => {
                              const ticker = typeof decision.ticker === "string" ? decision.ticker : `ticker-${index}`;
                              const shortlisted = decision.shortlisted === true;
                              const reasons = Array.isArray(decision.reasons) ? decision.reasons.filter((value): value is string => typeof value === "string") : [];
                              return (
                                <tr key={`${ticker}-${index}`}>
                                  <td><Link to={`/tickers/${ticker}`} className="badge badge-info badge-link">{ticker}</Link></td>
                                  <td><Badge tone={shortlisted ? "info" : "neutral"}>{shortlisted ? `shortlisted #${typeof decision.shortlist_rank === "number" ? decision.shortlist_rank : "—"}` : "rejected"}</Badge></td>
                                  <td>{typeof decision.selection_lane === "string" ? decision.selection_lane : "—"}</td>
                                  <td>{typeof decision.rank === "number" ? decision.rank : "—"}</td>
                                  <td>{typeof decision.confidence_percent === "number" ? `${decision.confidence_percent.toFixed(1)}%` : "—"}</td>
                                  <td>{typeof decision.attention_score === "number" ? decision.attention_score.toFixed(1) : "—"}</td>
                                  <td>{typeof decision.catalyst_proxy_score === "number" ? decision.catalyst_proxy_score.toFixed(1) : "—"}</td>
                                  <td>{reasons.length > 0 ? reasons.join(" · ") : "eligible"}</td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                    ) : null}
                  </section>
                ) : null}

                {detail.ticker_signal_snapshots.length > 0 ? (
                  <section>
                    <div className="section-heading">
                      <strong>Ticker signal snapshots</strong>
                    </div>
                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr>
                            <th>Ticker</th>
                            <th>Mode</th>
                            <th>Direction</th>
                            <th>Confidence</th>
                            <th>Attention</th>
                            <th>Shortlist</th>
                            <th>Transmission</th>
                            <th>Cheap-scan components</th>
                            <th>Status</th>
                          </tr>
                        </thead>
                        <tbody>
                          {detail.ticker_signal_snapshots.map((item) => {
                            const mode = typeof item.diagnostics.mode === "string" ? item.diagnostics.mode : "unknown";
                            const shortlisted = item.diagnostics.shortlisted === true;
                            const componentScores = item.diagnostics.cheap_scan_component_scores;
                            const componentRecord = componentScores && typeof componentScores === "object" && !Array.isArray(componentScores)
                              ? (componentScores as Record<string, unknown>)
                              : null;
                            const trendScore = typeof componentRecord?.trend_score === "number" ? componentRecord.trend_score : null;
                            const momentumScore = typeof componentRecord?.momentum_score === "number" ? componentRecord.momentum_score : null;
                            const breakoutScore = typeof componentRecord?.breakout_score === "number" ? componentRecord.breakout_score : null;
                            const volatilityScore = typeof componentRecord?.volatility_score === "number" ? componentRecord.volatility_score : null;
                            const liquidityScore = typeof componentRecord?.liquidity_score === "number" ? componentRecord.liquidity_score : null;
                            const directionalScore = typeof item.diagnostics.cheap_scan_directional_score === "number"
                              ? item.diagnostics.cheap_scan_directional_score
                              : null;
                            const shortlistReasons = Array.isArray(item.diagnostics.shortlist_reasons)
                              ? item.diagnostics.shortlist_reasons.filter((value): value is string => typeof value === "string")
                              : [];
                            const selectionLane = typeof item.diagnostics.selection_lane === "string" ? item.diagnostics.selection_lane : null;
                            const transmissionBias = typeof item.diagnostics.transmission_bias === "string" ? item.diagnostics.transmission_bias : "unknown";
                            const transmissionAlignment = typeof item.diagnostics.transmission_alignment_score === "number"
                              ? item.diagnostics.transmission_alignment_score
                              : null;
                            const transmissionTags = Array.isArray(item.diagnostics.transmission_tags)
                              ? item.diagnostics.transmission_tags.filter((value): value is string => typeof value === "string")
                              : [];
                            const primaryDrivers = Array.isArray(item.diagnostics.primary_drivers)
                              ? item.diagnostics.primary_drivers.filter((value): value is string => typeof value === "string")
                              : [];
                            const conflictFlags = Array.isArray(item.diagnostics.conflict_flags)
                              ? item.diagnostics.conflict_flags.filter((value): value is string => typeof value === "string")
                              : [];
                            const expectedWindow = typeof item.diagnostics.expected_transmission_window === "string"
                              ? item.diagnostics.expected_transmission_window
                              : "unknown";
                            const catalystProxyScore = typeof item.diagnostics.catalyst_proxy_score === "number"
                              ? item.diagnostics.catalyst_proxy_score
                              : null;
                            return (
                              <tr key={item.id ?? `${item.ticker}-${item.computed_at}`}>
                                <td>
                                  <div className="cluster">
                                    <Link to={`/tickers/${item.ticker}`} className="badge badge-info badge-link">{item.ticker}</Link>
                                    {shortlisted ? <Badge tone="info">shortlisted</Badge> : <Badge tone="neutral">not shortlisted</Badge>}
                                  </div>
                                </td>
                                <td>{mode}</td>
                                <td><Badge tone={item.direction === "long" ? "ok" : item.direction === "short" ? "warning" : "neutral"}>{item.direction}</Badge></td>
                                <td>
                                  <span style={{ color: scoreColor(item.confidence_percent, 0, 100) }}>{item.confidence_percent.toFixed(1)}%</span>
                                </td>
                                <td>{item.attention_score.toFixed(1)}</td>
                                <td>
                                  <div className="helper-text">{shortlisted ? `rank ${typeof item.diagnostics.shortlist_rank === "number" ? item.diagnostics.shortlist_rank : "—"}` : "not shortlisted"}</div>
                                  <div className="helper-text">lane {selectionLane ?? "—"}</div>
                                  <div className="helper-text">{shortlistReasons.length > 0 ? shortlistReasons.join(" · ") : "eligible"}</div>
                                  <div className="helper-text">catalyst proxy {catalystProxyScore !== null ? catalystProxyScore.toFixed(1) : "—"}</div>
                                </td>
                                <td>
                                  <Badge tone={biasTone(transmissionBias)}>{transmissionBias}</Badge>
                                  <div className="helper-text top-gap-small">alignment {transmissionAlignment !== null ? `${transmissionAlignment.toFixed(1)}%` : "—"}</div>
                                  <div className="helper-text">window {expectedWindow}</div>
                                  <div className="helper-text">drivers {primaryDrivers.length > 0 ? primaryDrivers.join(" · ") : "none"}</div>
                                  <div className="helper-text">conflicts {conflictFlags.length > 0 ? conflictFlags.join(" · ") : "none"}</div>
                                  <div className="helper-text">tags {transmissionTags.length > 0 ? transmissionTags.join(" · ") : "none"}</div>
                                </td>
                                <td>
                                  <div className="helper-text">trend {trendScore !== null ? trendScore.toFixed(0) : "—"}</div>
                                  <div className="helper-text">momentum {momentumScore !== null ? momentumScore.toFixed(0) : "—"}</div>
                                  <div className="helper-text">breakout {breakoutScore !== null ? breakoutScore.toFixed(0) : "—"}</div>
                                  <div className="helper-text">volatility {volatilityScore !== null ? volatilityScore.toFixed(0) : "—"}</div>
                                  <div className="helper-text">liquidity {liquidityScore !== null ? liquidityScore.toFixed(0) : "—"}</div>
                                  <div className="helper-text">directional {directionalScore !== null ? directionalScore.toFixed(2) : "—"}</div>
                                </td>
                                <td><Badge tone={item.warnings.length > 0 ? "warning" : "ok"}>{item.status}</Badge></td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </section>
                ) : null}

                {detail.recommendation_plans.length > 0 ? (
                  <section>
                    <div className="section-heading">
                      <strong>Recommendation plans</strong>
                    </div>
                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr>
                            <th>Ticker</th>
                            <th>Action</th>
                            <th>Confidence</th>
                            <th>Transmission</th>
                            <th>Entry</th>
                            <th>Stop</th>
                            <th>Take profit</th>
                            <th>Latest outcome</th>
                          </tr>
                        </thead>
                        <tbody>
                          {detail.recommendation_plans.map((plan) => {
                            const signalBreakdown = isRecord(plan.signal_breakdown) ? plan.signal_breakdown : null;
                            const evidenceSummary = isRecord(plan.evidence_summary) ? plan.evidence_summary : null;
                            const transmissionSummary = isRecord(signalBreakdown?.transmission_summary)
                              ? signalBreakdown.transmission_summary as Record<string, unknown>
                              : isRecord(evidenceSummary?.transmission_summary)
                                ? evidenceSummary.transmission_summary as Record<string, unknown>
                                : null;
                            const calibrationReview = isRecord(signalBreakdown?.calibration_review)
                              ? signalBreakdown.calibration_review as Record<string, unknown>
                              : isRecord(evidenceSummary?.calibration_review)
                                ? evidenceSummary.calibration_review as Record<string, unknown>
                                : null;
                            const transmissionBias = typeof transmissionSummary?.context_bias === "string" ? transmissionSummary.context_bias : "unknown";
                            const transmissionAlignment = typeof transmissionSummary?.alignment_percent === "number" ? transmissionSummary.alignment_percent : null;
                            const transmissionTags = Array.isArray(transmissionSummary?.transmission_tags)
                              ? transmissionSummary.transmission_tags.filter((value): value is string => typeof value === "string")
                              : [];
                            const primaryDrivers = Array.isArray(transmissionSummary?.primary_drivers)
                              ? transmissionSummary.primary_drivers.filter((value): value is string => typeof value === "string")
                              : [];
                            const conflictFlags = Array.isArray(transmissionSummary?.conflict_flags)
                              ? transmissionSummary.conflict_flags.filter((value): value is string => typeof value === "string")
                              : [];
                            const expectedWindow = typeof transmissionSummary?.expected_transmission_window === "string"
                              ? transmissionSummary.expected_transmission_window
                              : "unknown";
                            const setupFamily = typeof signalBreakdown?.setup_family === "string" ? signalBreakdown.setup_family : null;
                            const actionReason = typeof evidenceSummary?.action_reason === "string" ? evidenceSummary.action_reason : null;
                            const entryStyle = typeof evidenceSummary?.entry_style === "string" ? evidenceSummary.entry_style : null;
                            const invalidationSummary = typeof evidenceSummary?.invalidation_summary === "string" ? evidenceSummary.invalidation_summary : null;
                            const effectiveThreshold = typeof calibrationReview?.effective_confidence_threshold === "number"
                              ? calibrationReview.effective_confidence_threshold
                              : null;
                            const calibrationReviewStatus = typeof calibrationReview?.review_status === "string"
                              ? calibrationReview.review_status
                              : "disabled";
                            const calibrationReasons = Array.isArray(calibrationReview?.reasons)
                              ? calibrationReview.reasons.filter((value): value is string => typeof value === "string")
                              : [];
                            return (
                              <tr key={plan.id ?? `${plan.ticker}-${plan.computed_at}`}>
                                <td>
                                  <div>
                                    <Link to={`/tickers/${plan.ticker}`} className="badge badge-info badge-link">{plan.ticker}</Link>
                                    <div className="helper-text top-gap-small">{plan.thesis_summary || plan.rationale_summary || "No thesis stored."}</div>
                                    <div className="helper-text">setup {setupFamily ?? "—"} · reason {actionReason ?? "—"}</div>
                                    <div className="helper-text">entry style {entryStyle ?? "—"}</div>
                                    <div className="helper-text">invalidation {invalidationSummary ?? "—"}</div>
                                  </div>
                                </td>
                                <td><Badge tone={plan.action === "long" ? "ok" : plan.action === "short" ? "warning" : "neutral"}>{plan.action}</Badge></td>
                                <td>
                                  <span style={{ color: scoreColor(plan.confidence_percent, 0, 100) }}>{plan.confidence_percent.toFixed(1)}%</span>
                                  <div className="helper-text top-gap-small">threshold {effectiveThreshold !== null ? `${effectiveThreshold.toFixed(1)}%` : "—"}</div>
                                  <div className="helper-text">calibration {calibrationReviewStatus}</div>
                                  <div className="helper-text">{calibrationSliceSummary(calibrationReview?.horizon, "horizon")}</div>
                                  <div className="helper-text">{calibrationSliceSummary(calibrationReview?.setup_family, "setup")}</div>
                                  <div className="helper-text">{calibrationSliceSummary(calibrationReview?.confidence_bucket, "bucket")}</div>
                                  <div className="helper-text">reasons {calibrationReasons.length > 0 ? calibrationReasons.join(" · ") : "none"}</div>
                                </td>
                                <td>
                                  <Badge tone={biasTone(transmissionBias)}>{transmissionBias}</Badge>
                                  <div className="helper-text top-gap-small">alignment {transmissionAlignment !== null ? `${transmissionAlignment.toFixed(1)}%` : "—"}</div>
                                  <div className="helper-text">window {expectedWindow}</div>
                                  <div className="helper-text">drivers {primaryDrivers.length > 0 ? primaryDrivers.join(" · ") : "none"}</div>
                                  <div className="helper-text">conflicts {conflictFlags.length > 0 ? conflictFlags.join(" · ") : "none"}</div>
                                  <div className="helper-text">tags {transmissionTags.length > 0 ? transmissionTags.join(" · ") : "none"}</div>
                                </td>
                                <td>
                                  {plan.entry_price_low !== null && plan.entry_price_high !== null
                                    ? plan.entry_price_low === plan.entry_price_high
                                      ? plan.entry_price_low
                                      : `${plan.entry_price_low} – ${plan.entry_price_high}`
                                    : "—"}
                                </td>
                                <td>{plan.stop_loss ?? "—"}</td>
                                <td>{plan.take_profit ?? "—"}</td>
                                <td>
                                  {plan.latest_outcome ? (
                                    <>
                                      <Badge tone={plan.latest_outcome.outcome === "win" ? "ok" : plan.latest_outcome.outcome === "loss" ? "danger" : "neutral"}>{plan.latest_outcome.outcome}</Badge>
                                      <div className="helper-text top-gap-small">1d {plan.latest_outcome.horizon_return_1d ?? "—"}% · 5d {plan.latest_outcome.horizon_return_5d ?? "—"}%</div>
                                    </>
                                  ) : "—"}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </section>
                ) : null}

                {detail.macro_context_snapshots.length > 0 || detail.industry_context_snapshots.length > 0 ? (
                  <section>
                    <div className="section-heading">
                      <strong>Context objects written by this run</strong>
                    </div>
                    {detail.macro_context_snapshots.map((item) => (
                      <div key={item.id ?? item.computed_at} className="top-gap-small">
                        <Badge tone={item.warnings.length > 0 ? "warning" : "ok"}>macro context</Badge>
                        <span className="helper-text"> {item.summary_text || "No macro summary stored."}</span>
                      </div>
                    ))}
                    {detail.industry_context_snapshots.map((item) => (
                      <div key={item.id ?? `${item.industry_key}-${item.computed_at}`} className="top-gap-small">
                        <Badge tone={item.warnings.length > 0 ? "warning" : "ok"}>{item.industry_label || item.industry_key}</Badge>
                        <span className="helper-text"> {item.summary_text || "No industry summary stored."}</span>
                      </div>
                    ))}
                  </section>
                ) : null}
              </div>
            </Card>
          ) : null}

          <Card>
            <SectionTitle kicker="Produced output" title={detail.run.job_type === "proposal_generation" ? "Retired legacy recommendation artifacts" : "Workflow result stored on the run"} />
            {detail.run.job_type === "proposal_generation" ? (
              <>
                {detail.outputs.length === 0 ? <EmptyState message="No legacy recommendation artifacts were written for this run. Review the recommendation plans above instead." /> : null}
                <div className="stack-page">
                  {detail.outputs.map((output) => {
                    const item = output.recommendation;
                    const messages = diagnosticsMessages(output.diagnostics);
                    const analysis = parseJsonRecord(output.diagnostics.analysis_json);
                    const summarySection = isRecord(analysis?.summary) ? (analysis?.summary as Record<string, unknown>) : null;
                    const newsSection = isRecord(analysis?.news) ? (analysis?.news as Record<string, unknown>) : null;
                    const summaryText = typeof summarySection?.text === "string" && summarySection.text ? summarySection.text : null;
                    const summaryMethod = typeof summarySection?.method === "string" ? summarySection.method : null;
                    const summaryBackend = typeof summarySection?.backend === "string" ? summarySection.backend : null;
                    const newsDigest = (() => {
                      const digest = typeof newsSection?.digest === "string" ? newsSection.digest : summarySection?.digest;
                      return typeof digest === "string" && digest ? digest : null;
                    })();
                    const sentimentSection = isRecord(analysis?.sentiment) ? (analysis.sentiment as Record<string, unknown>) : null;
                    const enhancedSentiment = sentimentSection && isRecord(sentimentSection.enhanced) ? (sentimentSection.enhanced as Record<string, unknown>) : null;
                    const enhancedSentimentScore = enhancedSentiment && typeof enhancedSentiment.score === "number" ? enhancedSentiment.score : null;
                    const enhancedSentimentLabel = enhancedSentiment && typeof enhancedSentiment.label === "string" ? enhancedSentiment.label : null;
                    const enhancedComponents = enhancedSentiment && enhancedSentiment.components && isRecord(enhancedSentiment.components) ? (enhancedSentiment.components as Record<string, unknown>) : null;
                    const summaryMethodLabel = summaryMethod || (newsDigest ? "news_digest" : "price_only");
                    const summaryBackendLabel = summaryBackend || "news_digest";
                    const contextFlagsSection = isRecord(analysis?.context_flags) ? (analysis.context_flags as Record<string, unknown>) : null;
                    const featureVectorsSection = isRecord(analysis?.feature_vectors) ? (analysis.feature_vectors as Record<string, unknown>) : null;
                    const normalizedFeatureVectors =
                      featureVectorsSection && isRecord(featureVectorsSection.normalized)
                        ? (featureVectorsSection.normalized as Record<string, unknown>)
                        : null;
                    const aggregatorSection = isRecord(analysis?.aggregations) ? (analysis.aggregations as Record<string, unknown>) : null;
                    const confidenceWeightsSection = isRecord(analysis?.confidence_weights)
                      ? (analysis.confidence_weights as Record<string, unknown>)
                      : null;
                    const contextFlagEntries = contextFlagsSection
                      ? (Object.entries(contextFlagsSection) as [string, unknown][]).filter((entry): entry is [string, number] =>
                          typeof entry[1] === "number" && entry[1] > 0
                        )
                      : [];
                    const highlightKeys = [
                      "sentiment_score",
                      "enhanced_sentiment_score",
                      "news_point_count",
                      "context_count",
                      "polarity_trend",
                    ] as const;
                    const normalizedHighlights = highlightKeys.map((key) => {
                      const rawValue = normalizedFeatureVectors?.[key];
                      return {
                        key,
                        rawValue: typeof rawValue === "number" ? rawValue : null,
                        display: typeof rawValue === "number" ? rawValue.toFixed(2) : rawValue ?? "—",
                      };
                    });
                    const aggregatorEntries = aggregatorSection ? Object.entries(aggregatorSection) : [];
                    const confidenceEntries = confidenceWeightsSection ? Object.entries(confidenceWeightsSection) : [];
                    const newsItemCount = typeof newsSection?.item_count === "number" ? newsSection.item_count : null;
                    const newsPointCount = typeof newsSection?.point_count === "number" ? newsSection.point_count : null;
                    const newsSourceCount = typeof newsSection?.source_count === "number" ? newsSection.source_count : null;
                    const rawNewsItems = Array.isArray(newsSection?.items) ? (newsSection.items as unknown[]) : [];
                    const newsItemsList = rawNewsItems.filter(isRecord);
                    const newsStats = [
                      newsItemCount !== null ? { label: "news items", value: newsItemCount } : null,
                      newsPointCount !== null ? { label: "news points", value: newsPointCount } : null,
                      newsSourceCount !== null ? { label: "news sources", value: newsSourceCount } : null,
                    ].filter(Boolean) as { label: string; value: number }[];
                    const newsFeedErrors = Array.isArray(newsSection?.feed_errors)
                      ? (newsSection.feed_errors as unknown[]).filter((value): value is string => typeof value === "string")
                      : [];
                    const sentimentKeywordHits =
                      typeof sentimentSection?.keyword_hits === "number" ? sentimentSection.keyword_hits : null;
                    const coverageInsights = Array.isArray(sentimentSection?.coverage_insights)
                      ? (sentimentSection.coverage_insights as unknown[]).filter(
                          (entry): entry is string => typeof entry === "string"
                        )
                      : [];
                    const snapshotReferences = extractSentimentSnapshotReferences(output.diagnostics.analysis_json);
                    return (
                      <article key={item.id ?? `${item.ticker}-${item.created_at}`} className="recommendation-card">
                        <div className="card-headline">
                          <div>
                            <div className="cluster">
                              <Link to={`/tickers/${item.ticker}`} className="badge badge-info badge-link">{item.ticker}</Link>
                              <Badge tone={directionTone(item.direction)}>{item.direction}</Badge>
                              <Badge tone={recommendationStateTone(item.state)}>{item.state}</Badge>
                            </div>
                            <h3 className="subsection-title">
                              <span style={{ color: scoreColor(item.confidence, 0, 100) }}>{item.confidence}%</span>
                              {' '}confidence
                            </h3>
                          </div>
                          <Badge tone={messages.length > 0 ? "warning" : "ok"}>
                            {messages.length > 0 ? `${messages.length} warning(s)` : "No warnings"}
                          </Badge>
                        </div>
                        <section className="recommendation-section">
                          <div className="section-heading">
                            <strong>Trading parameters</strong>
                            <InfoBadge {...INFO_DESCRIPTIONS.trading} />
                          </div>
                          <div className="summary-grid">
                            <div className="summary-item">
                              <span className="summary-label summary-label-with-info">
                                Entry
                                <InfoBadge {...INFO_DESCRIPTIONS.fieldEntry} />
                              </span>
                              <span className="summary-value">{item.entry_price}</span>
                            </div>
                            <div className="summary-item">
                              <span className="summary-label summary-label-with-info">
                                Stop loss
                                <InfoBadge {...INFO_DESCRIPTIONS.fieldStop} />
                              </span>
                              <span className="summary-value">{item.stop_loss}</span>
                            </div>
                            <div className="summary-item">
                              <span className="summary-label summary-label-with-info">
                                Take profit
                                <InfoBadge {...INFO_DESCRIPTIONS.fieldTake} />
                              </span>
                              <span className="summary-value">{item.take_profit}</span>
                            </div>
                          </div>
                          <div className="helper-text">{item.indicator_summary || "No indicator summary stored for this recommendation."}</div>
                        </section>
                        {summaryText || newsDigest ? (
                          <section className="recommendation-section">
                            <div className="section-heading">
                              <strong>Summary & sentiment</strong>
                              <InfoBadge {...INFO_DESCRIPTIONS.summary} />
                            </div>
                            <div className="stack-page top-gap-small">
                              <div className="summary-grid">
                                <div className="summary-item summary-method-block">
                                  <span className="summary-label summary-label-with-info">
                                    Summary method
                                    <InfoBadge {...INFO_DESCRIPTIONS.summaryMethod} />
                                  </span>
                                  <span className="summary-method-value">{summaryMethodLabel} ({summaryBackendLabel})</span>
                                </div>
                              </div>
                              {summaryText ? (
                                <div className="summary-text-block">
                                  <p>{summaryText}</p>
                                </div>
                              ) : null}
                              {newsDigest && newsDigest !== summaryText ? (
                                <div className="helper-text">Headline digest: {newsDigest}</div>
                              ) : null}
                              {enhancedSentimentScore !== null ? (
                                <div className="enhanced-sentiment-card">
                                  <div className="summary-grid enhanced-sentiment-grid">
                                    <div className="summary-item">
                                      <span className="summary-label summary-label-with-info">
                                        Enhanced sentiment
                                        <InfoBadge {...INFO_DESCRIPTIONS.summary} />
                                      </span>
                                      <span className="summary-value" style={{ color: scoreColor(enhancedSentimentScore) }}>{enhancedSentimentScore.toFixed(2)}</span>
                                    </div>
                                    {enhancedSentimentLabel ? (
                                      <div className="summary-item">
                                        <span className="summary-label summary-label-with-info">
                                          Label
                                          <InfoBadge {...INFO_DESCRIPTIONS.summary} />
                                        </span>
                                        <span className="summary-value">{enhancedSentimentLabel}</span>
                                      </div>
                                    ) : null}
                                  </div>
                                  {enhancedComponents ? (
                                    <div className="summary-item">
                                      <span className="summary-label">Components</span>
                                      <pre>{JSON.stringify(enhancedComponents, null, 2)}</pre>
                                    </div>
                                  ) : null}
                                </div>
                              ) : null}
                            </div>
                          </section>
                        ) : null}
                        {snapshotReferences.length > 0 ? (
                          <section className="recommendation-section">
                            <div className="section-heading">
                              <strong>Shared snapshot lineage</strong>
                              <InfoBadge {...INFO_DESCRIPTIONS.diagnostics} />
                            </div>
                            <ul className="list-reset">
                              {snapshotReferences.map((reference) => (
                                <li key={`${reference.scope}-${reference.snapshotId}`} className="list-item compact-item">
                                  <div className="card-headline">
                                    <div>
                                      <div className="cluster">
                                        <Badge tone="info">{reference.scope}</Badge>
                                        {reference.label ? <Badge>{reference.label}</Badge> : null}
                                        <Badge>#{reference.snapshotId}</Badge>
                                      </div>
                                      <div className="helper-text">{reference.subjectLabel ?? reference.subjectKey ?? "Snapshot reference"}</div>
                                    </div>
                                    <Link to={`/sentiment/${reference.snapshotId}`} className="button-subtle">Open snapshot</Link>
                                  </div>
                                </li>
                              ))}
                            </ul>
                          </section>
                        ) : null}
                        {analysis ? (
                          <section className="recommendation-section">
                            <div className="section-heading">
                              <strong>Structured diagnostics</strong>
                              <InfoBadge {...INFO_DESCRIPTIONS.diagnostics} />
                            </div>
                            <details className="top-gap-small structured-diagnostics">
                              <summary>Expand diagnostics</summary>
                              <div className="stack-page top-gap-small">
                                <section className="diagnostic-subsection">
                                  <div className="section-heading">
                                    <strong>Context flags</strong>
                                    <InfoBadge {...INFO_DESCRIPTIONS.contextFlags} />
                                  </div>
                                  {contextFlagEntries.length > 0 ? (
                                    <div className="summary-grid">
                                      {contextFlagEntries.map(([flag, value]) => (
                                        <div key={flag} className="summary-item">
                                          <span className="summary-label">{flag.replace(/_/g, " ")}</span>
                                          <span className="summary-value">
                                            {typeof value === "number" ? value.toFixed(2) : value ?? "—"}
                                          </span>
                                        </div>
                                      ))}
                                    </div>
                                  ) : (
                                    <div className="helper-text">No active context flags.</div>
                                  )}
                                </section>
                                <section className="diagnostic-subsection">
                                  <div className="section-heading">
                                    <strong>Normalized highlights</strong>
                                    <InfoBadge {...INFO_DESCRIPTIONS.highlights} />
                                  </div>
                                  <div className="summary-grid">
                                    {normalizedHighlights.map((entry) => (
                                      <div key={entry.key} className="summary-item">
                                        <span className="summary-label">{entry.key.replace(/_/g, " ")}</span>
                                        <span
                                          className="summary-value"
                                          style={entry.rawValue !== null ? { color: scoreColor(entry.rawValue, 0, 1) } : undefined}
                                        >
                                          {String(entry.display)}
                                        </span>
                                      </div>
                                    ))}
                                  </div>
                                </section>
                                <section className="diagnostic-subsection">
                                  <div className="section-heading">
                                    <strong>Aggregations</strong>
                                    <InfoBadge {...INFO_DESCRIPTIONS.aggregations} />
                                  </div>
                                  {aggregatorEntries.length > 0 ? (
                                    <div className="summary-grid">
                                      {aggregatorEntries.slice(0, 6).map(([key, value]) => (
                                        <div key={key} className="summary-item">
                                          <span className="summary-label">{key.replace(/_/g, " ")}</span>
                                          <span className="summary-value">
                                            {typeof value === "number" ? value.toFixed(2) : String(value ?? "—")}
                                          </span>
                                        </div>
                                      ))}
                                      {aggregatorEntries.length > 6 && (
                                        <div className="summary-item">
                                          <span className="summary-label">+ more aggregators</span>
                                          <span className="summary-value">+{aggregatorEntries.length - 6} more</span>
                                        </div>
                                      )}
                                    </div>
                                  ) : (
                                    <div className="helper-text">Aggregator totals not available.</div>
                                  )}
                                </section>
                                <section className="diagnostic-subsection">
                                  <div className="section-heading">
                                    <strong>Confidence weights</strong>
                                    <InfoBadge {...INFO_DESCRIPTIONS.weights} />
                                  </div>
                                  {confidenceEntries.length > 0 ? (
                                    <div className="summary-grid">
                                      {confidenceEntries.slice(0, 6).map(([key, value]) => (
                                        <div key={key} className="summary-item">
                                          <span className="summary-label">{key.replace(/_/g, " ")}</span>
                                          <span className="summary-value">
                                            {typeof value === "number" ? value.toFixed(2) : String(value ?? "—")}
                                          </span>
                                        </div>
                                      ))}
                                      {confidenceEntries.length > 6 && (
                                        <div className="summary-item">
                                          <span className="summary-label">+ more weights</span>
                                          <span className="summary-value">+{confidenceEntries.length - 6} more</span>
                                        </div>
                                      )}
                                    </div>
                                  ) : (
                                    <div className="helper-text">Confidence weights are not stored.</div>
                                  )}
                                </section>
                                <section className="diagnostic-subsection">
                                  <div className="section-heading">
                                    <strong>News coverage</strong>
                                    <InfoBadge {...INFO_DESCRIPTIONS.news} />
                                  </div>
                                  {newsStats.length > 0 ? (
                                    <div className="summary-grid">
                                      {newsStats.map((stat) => (
                                        <div key={stat.label} className="summary-item">
                                          <span className="summary-label">{stat.label}</span>
                                          <span className="summary-value">{stat.value}</span>
                                        </div>
                                      ))}
                                    </div>
                                  ) : (
                                    <div className="helper-text">No aggregated news totals.</div>
                                  )}
                                  {newsItemsList.length > 0 ? (
                                    <div className="news-coverage-card">
                                      <ul className="news-coverage-list">
                                        {newsItemsList.slice(0, 5).map((newsItem, index) => {
                                          const title = typeof newsItem.title === "string" ? newsItem.title : "Untitled article";
                                          const link = typeof newsItem.link === "string" && newsItem.link ? newsItem.link : null;
                                          const publishedAt = typeof newsItem.published_at === "string" ? formatDate(newsItem.published_at) : "—";
                                          const compoundScore = typeof newsItem.compound === "number" ? newsItem.compound.toFixed(2) : "—";
                                          const scoreStyle = typeof newsItem.compound === "number" ? { color: scoreColor(newsItem.compound, -1, 1) } : undefined;
                                          return (
                                            <li key={`${title}-${index}`} className="news-coverage-item">
                                              <div className="news-coverage-title-row">
                                                <div className="news-coverage-title-group">
                                                  {link ? (
                                                    <a className="news-coverage-link" href={link} target="_blank" rel="noreferrer">
                                                      {title}
                                                    </a>
                                                  ) : (
                                                    <span className="news-coverage-title">{title}</span>
                                                  )}
                                                  <span className="news-coverage-score" style={scoreStyle}>{`score ${compoundScore}`}</span>
                                                </div>
                                                <span className="news-coverage-date">{publishedAt}</span>
                                              </div>
                                            </li>
                                          );
                                        })}
                                      </ul>
                                      {newsItemsList.length > 5 ? (
                                        <div className="helper-text top-gap-small">
                                          +{newsItemsList.length - 5} more articles truncated.
                                        </div>
                                      ) : null}
                                    </div>
                                  ) : (
                                    <div className="helper-text">No news items stored for this proposal.</div>
                                  )}
                                  {newsFeedErrors.length > 0 ? (
                                    <ul className="warning-text">
                                      {newsFeedErrors.map((error, index) => (
                                        <li key={`${error}-${index}`}>{error}</li>
                                      ))}
                                    </ul>
                                  ) : null}
                                </section>
                                <section className="diagnostic-subsection">
                                  <div className="section-heading">
                                    <strong>Sentiment coverage</strong>
                                    <InfoBadge {...INFO_DESCRIPTIONS.coverage} />
                                  </div>
                                  {sentimentKeywordHits !== null ? (
                                    <div className="summary-grid">
                                      <div className="summary-item">
                                        <span className="summary-label">Keyword hits</span>
                                        <span className="summary-value">{sentimentKeywordHits}</span>
                                      </div>
                                    </div>
                                  ) : null}
                                  {coverageInsights.length > 0 ? (
                                    <>
                                      <div className="helper-text">Each insight describes why the sentiment signal stayed neutral (no articles, no keyword hits, provider failures, etc.).</div>
                                      <ul className="coverage-insights-list">
                                        {coverageInsights.map((insight, index) => (
                                          <li key={`${insight}-${index}`}>{insight}</li>
                                        ))}
                                      </ul>
                                    </>
                                  ) : (
                                    <div className="helper-text">Coverage insights report no detected issues.</div>
                                  )}
                                </section>
                              </div>
                            </details>
                          </section>
                        ) : null}
                        <section className="recommendation-section">
                          <div className="section-heading">
                            <strong>Diagnostic messages</strong>
                            <InfoBadge {...INFO_DESCRIPTIONS.messages} />
                          </div>
                          {messages.length > 0 ? (
                            <ul className="warning-text">
                              {messages.map((message) => (
                                <li key={message}>{message}</li>
                              ))}
                            </ul>
                          ) : (
                            <div className="helper-text">No warnings or errors.</div>
                          )}
                        </section>
                        {output.diagnostics.raw_output ? (
                          <section className="recommendation-section">
                            <div className="section-heading">
                              <strong>Raw details</strong>
                              <InfoBadge {...INFO_DESCRIPTIONS.raw} />
                            </div>
                            <details>
                              <summary>View raw output</summary>
                              <pre>{output.diagnostics.raw_output}</pre>
                            </details>
                          </section>
                        ) : null}
                      </article>
                    );
                  })}
                </div>
              </>
            ) : (
              <WorkflowRunResults
                jobType={detail.run.job_type}
                summaryJson={detail.run.summary_json}
                artifactJson={detail.run.artifact_json}
              />
            )}
          </Card>
        </div>
      ) : null}
    </>
  );
}
