import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { deleteJson, getJson } from "../api";
import { WorkflowRunResults } from "../components/workflow-run-results";
import { Badge, Card, DisclosureCard, EmptyState, ErrorState, HelpHint, LoadingState, PageHeader, SectionTitle, StatCard } from "../components/ui";
import { useToast } from "../components/toast";
import type { Run, RunDetailResponse } from "../types";
import { extractRunWarnings, formatDate, formatDuration, isCompletedWithWarningsRunStatus, isFailedRunStatus, isQueuedOrRunningRunStatus, jobTypeLabel, runTone } from "../utils";

function runImportance(detail: RunDetailResponse | null, warnings: string[]): { label: string; tone: "ok" | "warning" | "danger" | "info"; message: string } {
  if (!detail) {
    return { label: "none selected", tone: "info", message: "Choose a run to inspect why it matters." };
  }
  if (isFailedRunStatus(detail.run.status)) {
    return { label: "failed", tone: "danger", message: detail.run.error_message || "This run failed and should be inspected before trusting its downstream artifacts." };
  }
  if (warnings.length > 0 || isCompletedWithWarningsRunStatus(detail.run.status)) {
    return { label: "warnings", tone: "warning", message: warnings.slice(0, 2).join(" · ") || "This run completed with warnings and may have degraded artifacts." };
  }
  if (isQueuedOrRunningRunStatus(detail.run.status)) {
    return { label: "active", tone: "info", message: "This run is still queued or running; inspect worker logs if progress stalls." };
  }
  return { label: "clean", tone: "ok", message: "No failure or warning was detected for the selected run." };
}

const JOB_TYPE_FILTER_OPTIONS = [
  { value: "all", label: "All runs" },
  { value: "proposal_generation", label: "Proposal generation" },
  { value: "recommendation_evaluation", label: "Recommendation evaluation" },
  { value: "plan_generation_tuning", label: "Plan generation tuning" },
  { value: "performance_assessment", label: "Performance assessment" },
  { value: "macro_context_refresh", label: "Macro context refresh" },
  { value: "industry_context_refresh", label: "Industry context refresh" },
  { value: "historical_replay", label: "Historical replay" },
  { value: "bars_data_refresh", label: "Bars data refresh" },
];

export function DebuggerPage() {
  const [searchParams, setSearchParams] = useSearchParams({ limit: "10" });
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [detail, setDetail] = useState<RunDetailResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [isDeletingRun, setIsDeletingRun] = useState(false);
  const { showToast } = useToast();

  const selectedJobType = searchParams.get("job_type") || "all";
  const selectedLimit = Number.parseInt(searchParams.get("limit") || "10", 10) || 10;
  const selectedRunId = searchParams.get("run_id");

  useEffect(() => {
    async function loadRuns() {
      try {
        setError(null);
        const query = new URLSearchParams();
        query.set("limit", String(selectedLimit));
        if (selectedJobType !== "all") {
          query.set("job_type", selectedJobType);
        }
        const loadedRuns = await getJson<Run[]>(`/api/runs?${query.toString()}`);
        setRuns(loadedRuns);
        const matchingRun = selectedRunId ? loadedRuns.find((run) => String(run.id) === selectedRunId) : null;
        if (matchingRun?.id) {
          return;
        }
        if (loadedRuns[0]?.id) {
          setSearchParams({ run_id: String(loadedRuns[0].id), job_type: selectedJobType, limit: String(selectedLimit) }, { replace: true });
        } else {
          setSearchParams({ job_type: selectedJobType, limit: String(selectedLimit) }, { replace: true });
        }
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : "Failed to load runs");
      }
    }
    void loadRuns();
  }, [setSearchParams, selectedJobType, selectedLimit]);

  useEffect(() => {
    async function loadDetail() {
      if (!selectedRunId) {
        setDetail(null);
        return;
      }
      try {
        setError(null);
        setDetail(await getJson<RunDetailResponse>(`/api/runs/${selectedRunId}`));
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : "Failed to load run detail");
      }
    }
    void loadDetail();
  }, [selectedRunId]);

  const runStats = useMemo(() => {
    const items = runs ?? [];
    return {
      total: items.length,
      failed: items.filter((run) => isFailedRunStatus(run.status)).length,
      warnings: items.filter((run) => isCompletedWithWarningsRunStatus(run.status)).length,
      active: items.filter((run) => isQueuedOrRunningRunStatus(run.status)).length,
    };
  }, [runs]);

  async function handleDeleteRun(runId: number) {
    if (
      !window.confirm(
        `Delete run #${runId}? This will permanently remove the run and its associated recommendation plans, outcomes, context objects, signals, and diagnostics.`,
      )
    ) {
      return;
    }
    setDeleteError(null);
    setIsDeletingRun(true);
    try {
      await deleteJson<{ deleted: boolean; run_id: number }>(`/api/runs/${runId}`);
      showToast({ message: `Run #${runId} deleted`, tone: "success" });
      setRuns((currentRuns) => {
        const remainingRuns = currentRuns?.filter((run) => run.id !== runId) ?? null;
        if (selectedRunId === String(runId)) {
          if (remainingRuns?.[0]?.id) {
            setSearchParams({ run_id: String(remainingRuns[0].id) }, { replace: true });
          } else {
            setSearchParams({}, { replace: true });
          }
        }
        return remainingRuns;
      });
      setDetail((currentDetail) => (currentDetail?.run.id === runId ? null : currentDetail));
    } catch (deleteErr) {
      setDeleteError(deleteErr instanceof Error ? deleteErr.message : "Failed to delete run");
    } finally {
      setIsDeletingRun(false);
    }
  }

  const activeWarnings = useMemo<string[]>(() => extractRunWarnings(detail), [detail]);
  const selectedRunImportance = useMemo(() => runImportance(detail, activeWarnings), [detail, activeWarnings]);

  return (
    <>
      <PageHeader
        kicker="Execution diagnostics"
        title="Run debugger"
        actions={<HelpHint tooltip="Debugger mode keeps run investigation compact: pick a run, inspect warnings and artifacts, then open the full detail only if needed." to="/docs?doc=operator-page-field-guide" />}
      />
      {error ? <ErrorState message={error} /> : null}

      <Card className="top-gap">
        <SectionTitle kicker="Run triage" title="What needs investigation?" subtitle="Start with failed, warning, or active runs; open full run detail only after the compact triage points to a real issue." />
        <section className="metrics-grid debugger-metrics-grid top-gap-small">
          <StatCard className="stat-card-compact" label="Runs loaded" value={runStats.total} />
          <StatCard className="stat-card-compact" label="Failed" value={runStats.failed} />
          <StatCard className="stat-card-compact" label="Warnings" value={runStats.warnings} />
          <StatCard className="stat-card-compact" label="Active" value={runStats.active} />
        </section>
      </Card>

      <Card className="top-gap">
        <SectionTitle kicker="Filters" title="Run list filter" subtitle="Narrow the debugger to a specific workflow type." />
        <div className="cluster wrap">
          <label className="form-field">
            <span>Job type</span>
            <select
              value={selectedJobType}
              onChange={(event) => setSearchParams({ job_type: event.target.value, limit: String(selectedLimit) })}
            >
              {JOB_TYPE_FILTER_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </label>
          <label className="form-field">
            <span>Limit</span>
            <select
              value={String(selectedLimit)}
              onChange={(event) => setSearchParams({ job_type: selectedJobType, limit: event.target.value })}
            >
              {[10, 20, 50, 100].map((option) => (
                <option key={option} value={String(option)}>{option}</option>
              ))}
            </select>
          </label>
        </div>
      </Card>

      <section className="two-column debugger-layout top-gap">
        <Card className="sticky-toolbar debugger-sidebar-panel">
          <SectionTitle
            kicker="Recent runs"
            title="Choose a run"
            actions={<HelpHint tooltip="Use the left list to move quickly between recent runs without leaving the debugger workflow." to="/docs?doc=operator-page-field-guide" />}
          />
          {deleteError ? <ErrorState message={deleteError} /> : null}
          {!runs && !error ? <LoadingState message="Loading runs…" /> : null}
          {runs && runs.length === 0 ? <EmptyState message="No runs available." /> : null}
          {runs ? (
            <div className="data-stack debugger-run-list top-gap-small">
              {runs.map((run) => (
                <div key={run.id ?? run.created_at} className={`debugger-run-row${selectedRunId === String(run.id) ? " is-selected" : ""}`}>
                  <button
                    type="button"
                    className={`data-card link-button debugger-run-select${selectedRunId === String(run.id) ? " is-selected" : ""}`}
                    onClick={() => run.id && setSearchParams({ run_id: String(run.id) })}
                  >
                    <div className="data-card-header">
                      <div>
                        <div className="data-card-title">Run #{run.id}</div>
                        <div className="helper-text">{jobTypeLabel(run.job_type)} · job {run.job_id}{run.job_name ? ` · ${run.job_name}` : ""}</div>
                      </div>
                      <Badge tone={runTone(run.status)}>{run.status}</Badge>
                    </div>
                    <div className="debugger-run-meta">
                      <span className="helper-text">Created {formatDate(run.created_at)}</span>
                      {run.scheduled_for ? <span className="helper-text">Scheduled {formatDate(run.scheduled_for)}</span> : null}
                    </div>
                  </button>
                  {run.id ? (
                    <button
                      type="button"
                      className="icon-button icon-button-danger debugger-run-delete"
                      aria-label={`Delete run #${run.id}`}
                      title={`Delete run #${run.id}`}
                      disabled={isDeletingRun}
                      onClick={(event) => {
                        event.preventDefault();
                        event.stopPropagation();
                        void handleDeleteRun(run.id as number);
                      }}
                    >
                      🗑
                    </button>
                  ) : null}
                </div>
              ))}
            </div>
          ) : null}
        </Card>

        <div className="stack-page debugger-detail-panel">
          {!detail && !error ? (
            <Card>
              <SectionTitle kicker="Selected run" title="Choose a run" subtitle="The right panel stays compact until you select a run from the left-hand list." />
              <EmptyState message="Select a run to inspect its summary, run context, and persisted objects." />
            </Card>
          ) : null}
          {detail ? (
            <>
              <Card>
                <SectionTitle kicker="Why this run matters" title={selectedRunImportance.message} actions={<Badge tone={selectedRunImportance.tone}>{selectedRunImportance.label}</Badge>} />
                <div className="cluster top-gap-small">
                  <Badge tone={runTone(detail.run.status)}>{detail.run.status}</Badge>
                  <span className="helper-text">{jobTypeLabel(detail.run.job_type)} · job {detail.run.job_id}{detail.run.job_name ? ` · ${detail.run.job_name}` : ""}</span>
                </div>
                {activeWarnings.length > 0 ? (
                  <div className="alert alert-warning top-gap-small">
                    <ul className="bullet-list-compact">
                      {activeWarnings.slice(0, 4).map((warning, index) => <li key={index}>{warning}</li>)}
                    </ul>
                  </div>
                ) : null}
              </Card>

              <Card className="debugger-summary-card">
                <SectionTitle
                  kicker="Selected run"
                  title={`Run #${detail.run.id}`}
                  actions={<Link to={`/runs/${detail.run.id}`} className="button-secondary">↗ Full run</Link>}
                />
                <div className="data-points debugger-summary-points top-gap-small" aria-label="Selected run summary">
                  <div className="data-point"><span className="data-point-label">status</span><span className="data-point-value"><Badge tone={runTone(detail.run.status)}>{detail.run.status}</Badge></span></div>
                  <div className="data-point"><span className="data-point-label">job</span><span className="data-point-value">{detail.run.job_id}</span></div>
                  <div className="data-point"><span className="data-point-label">workflow</span><span className="data-point-value">{jobTypeLabel(detail.run.job_type)}</span></div>
                  <div className="data-point"><span className="data-point-label">job name</span><span className="data-point-value">{detail.run.job_name ?? "—"}</span></div>
                  <div className="data-point"><span className="data-point-label">duration</span><span className="data-point-value">{formatDuration(detail.run.duration_seconds)}</span></div>
                  <div className="data-point"><span className="data-point-label">plans written</span><span className="data-point-value">{detail.recommendation_plans.length}</span></div>
                  <div className="data-point"><span className="data-point-label">signals written</span><span className="data-point-value">{detail.ticker_signal_snapshots.length}</span></div>
                </div>
                <div className="debugger-timestamp-list top-gap-small">
                  <div className="helper-text">Created {formatDate(detail.run.created_at)}</div>
                  <div className="helper-text">Started {formatDate(detail.run.started_at)}</div>
                  <div className="helper-text">Completed {formatDate(detail.run.completed_at)}</div>
                </div>
                {detail.run.error_message ? <div className="alert alert-danger top-gap-small">{detail.run.error_message}</div> : null}
              </Card>

              <DisclosureCard
                kicker="Run output"
                title={detail.run.job_type === "proposal_generation" ? "Proposal-run triage" : "Workflow metadata"}
                subtitle={detail.run.job_type === "proposal_generation" ? "Debugger mode is best for quick triage. Use the full run page when you need the complete proposal, signal, and context walkthrough." : "Non-proposal runs store their useful output as run-level summary and artifact metadata."}
                defaultOpen
              >
                {detail.run.job_type === "proposal_generation" ? (
                  <div className="insight-grid top-gap">
                    <div className="data-card">
                      <h3 className="data-card-title">Proposal-run guidance</h3>
                      <div className="helper-text top-gap-small">
                        Proposal-generation runs are reviewed through recommendation plans, ticker signals, and run detail. Use debugger mode only for quick triage.
                      </div>
                    </div>
                    <div className="data-card">
                      <h3 className="data-card-title">Persisted objects</h3>
                      <div className="data-points top-gap-small">
                        <div className="data-point"><span className="data-point-label">plans</span><span className="data-point-value">{detail.recommendation_plans.length}</span></div>
                        <div className="data-point"><span className="data-point-label">signals</span><span className="data-point-value">{detail.ticker_signal_snapshots.length}</span></div>
                        <div className="data-point"><span className="data-point-label">context</span><span className="data-point-value">{detail.macro_context_snapshots.length + detail.industry_context_snapshots.length}</span></div>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="top-gap">
                    <WorkflowRunResults
                      jobType={detail.run.job_type}
                      summaryJson={detail.run.summary_json}
                      artifactJson={detail.run.artifact_json}
                    />
                  </div>
                )}
              </DisclosureCard>
            </>
          ) : null}
        </div>
      </section>
    </>
  );
}
