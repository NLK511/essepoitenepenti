import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { deleteJson, getJson } from "../api";
import { WorkflowRunResults } from "../components/workflow-run-results";
import { useToast } from "../components/toast";
import { Badge, Card, EmptyState, ErrorState, LoadingState, PageHeader, SectionTitle } from "../components/ui";
import type { Job, RunDetailResponse, WatchlistEvaluationPolicy } from "../types";
import { formatDate, formatDuration, isRecord, jobTypeLabel, parseJsonRecord, runTone } from "../utils";

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
        `Delete run #${detail.run.id}? This will permanently remove the run and its associated recommendation plans, outcomes, context objects, signals, and diagnostics.`,
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
        subtitle="A run is one job execution. This page focuses on execution state and the recommendation plans produced by that run, not on treating the run itself as the trade output."
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
                            const actionReasonDetail = typeof evidenceSummary?.action_reason_detail === "string" ? evidenceSummary.action_reason_detail : null;
                            const entryStyle = typeof evidenceSummary?.entry_style === "string" ? evidenceSummary.entry_style : null;
                            const stopStyle = typeof evidenceSummary?.stop_style === "string" ? evidenceSummary.stop_style : null;
                            const targetStyle = typeof evidenceSummary?.target_style === "string" ? evidenceSummary.target_style : null;
                            const timingExpectation = typeof evidenceSummary?.timing_expectation === "string" ? evidenceSummary.timing_expectation : null;
                            const evaluationFocus = Array.isArray(evidenceSummary?.evaluation_focus)
                              ? evidenceSummary.evaluation_focus.filter((value): value is string => typeof value === "string")
                              : [];
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
                                    <div className="helper-text">{actionReasonDetail ?? "No family-specific action note stored."}</div>
                                    <div className="helper-text">entry style {entryStyle ?? "—"} · timing {timingExpectation ?? "—"}</div>
                                    <div className="helper-text">stop style {stopStyle ?? "—"} · target style {targetStyle ?? "—"}</div>
                                    <div className="helper-text">invalidation {invalidationSummary ?? "—"}</div>
                                    <div className="helper-text">review focus {evaluationFocus.length > 0 ? evaluationFocus.join(" · ") : "—"}</div>
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

          {detail.run.job_type !== "proposal_generation" ? (
            <Card>
              <SectionTitle kicker="Produced output" title="Workflow result stored on the run" />
              <WorkflowRunResults
                jobType={detail.run.job_type}
                summaryJson={detail.run.summary_json}
                artifactJson={detail.run.artifact_json}
              />
            </Card>
          ) : null}
        </div>
      ) : null}
    </>
  );
}
