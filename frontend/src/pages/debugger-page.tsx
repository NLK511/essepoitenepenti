import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { deleteJson, getJson } from "../api";
import { WorkflowRunResults } from "../components/workflow-run-results";
import { Badge, Card, EmptyState, ErrorState, LoadingState, PageHeader, SectionTitle, StatCard } from "../components/ui";
import { useToast } from "../components/toast";
import type { Run, RunDetailResponse } from "../types";
import { formatDate, formatDuration, jobTypeLabel, runTone } from "../utils";

export function DebuggerPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [detail, setDetail] = useState<RunDetailResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [isDeletingRun, setIsDeletingRun] = useState(false);
  const { showToast } = useToast();

  useEffect(() => {
    async function loadRuns() {
      try {
        setError(null);
        const loadedRuns = await getJson<Run[]>("/api/runs");
        setRuns(loadedRuns);
        const selectedId = searchParams.get("run_id");
        if (!selectedId && loadedRuns[0]?.id) {
          setSearchParams({ run_id: String(loadedRuns[0].id) }, { replace: true });
        }
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : "Failed to load runs");
      }
    }
    void loadRuns();
  }, [searchParams, setSearchParams]);

  useEffect(() => {
    async function loadDetail() {
      const selectedId = searchParams.get("run_id");
      if (!selectedId) {
        setDetail(null);
        return;
      }
      try {
        setError(null);
        setDetail(await getJson<RunDetailResponse>(`/api/runs/${selectedId}`));
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : "Failed to load run detail");
      }
    }
    void loadDetail();
  }, [searchParams]);

  const runStats = useMemo(() => {
    const items = runs ?? [];
    return {
      total: items.length,
      failed: items.filter((run) => run.status === "failed").length,
      warnings: items.filter((run) => run.status === "completed_with_warnings").length,
      active: items.filter((run) => run.status === "queued" || run.status === "running").length,
    };
  }, [runs]);

  const selectedRunId = searchParams.get("run_id");
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

  return (
    <>
      <PageHeader
        kicker="Execution diagnostics"
        title="Run debugger"
        subtitle="Use debugger mode for fast investigation: select a recent run, review warnings first, and jump to the canonical run page only when you need the full orchestration detail."
      />
      {error ? <ErrorState message={error} /> : null}

      <section className="metrics-grid debugger-metrics-grid top-gap">
        <StatCard className="stat-card-compact" label="Runs loaded" value={runStats.total} />
        <StatCard className="stat-card-compact" label="Failed" value={runStats.failed} />
        <StatCard className="stat-card-compact" label="Warnings" value={runStats.warnings} />
        <StatCard className="stat-card-compact" label="Active" value={runStats.active} />
      </section>

      <section className="two-column debugger-layout top-gap">
        <Card className="sticky-toolbar">
          <SectionTitle
            kicker="Recent runs"
            title="Choose a run"
            subtitle="Pick a run from the left, then scan the summary on the right before opening the full run page."
          />
          {deleteError ? <ErrorState message={deleteError} /> : null}
          {!runs && !error ? <LoadingState message="Loading runs…" /> : null}
          {runs && runs.length === 0 ? <EmptyState message="No runs available." /> : null}
          {runs ? (
            <div className="data-stack top-gap-small">
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
                        <div className="helper-text">{jobTypeLabel(run.job_type)} · job {run.job_id}</div>
                      </div>
                      <Badge tone={runTone(run.status)}>{run.status}</Badge>
                    </div>
                    <div className="helper-text">Created {formatDate(run.created_at)}</div>
                    {run.scheduled_for ? <div className="helper-text">Scheduled {formatDate(run.scheduled_for)}</div> : null}
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
              <div className="debugger-stat-strip top-gap" aria-label="Selected run summary">
                <div className="debugger-stat-inline">
                  <span className="debugger-stat-label">Status</span>
                  <Badge tone={runTone(detail.run.status)}>{detail.run.status}</Badge>
                </div>
                <div className="debugger-stat-inline">
                  <span className="debugger-stat-label">Duration</span>
                  <span className="debugger-stat-value">{formatDuration(detail.run.duration_seconds)}</span>
                </div>
                <div className="debugger-stat-inline">
                  <span className="debugger-stat-label">Plans written</span>
                  <span className="debugger-stat-value">{detail.recommendation_plans.length}</span>
                </div>
                <div className="debugger-stat-inline">
                  <span className="debugger-stat-label">Signals written</span>
                  <span className="debugger-stat-value">{detail.ticker_signal_snapshots.length}</span>
                </div>
              </div>

              <Card>
                <SectionTitle
                  kicker="Selected run"
                  title={`Run #${detail.run.id}`}
                  actions={<Link to={`/runs/${detail.run.id}`} className="button-secondary">Open full run review</Link>}
                />
                <div className="cluster">
                  <Badge tone={runTone(detail.run.status)}>{detail.run.status}</Badge>
                  <Badge>Job {detail.run.job_id}</Badge>
                  <Badge>{jobTypeLabel(detail.run.job_type)}</Badge>
                  <Badge>{formatDuration(detail.run.duration_seconds)}</Badge>
                </div>
                <div className="helper-text top-gap-small">Created {formatDate(detail.run.created_at)} · Started {formatDate(detail.run.started_at)} · Completed {formatDate(detail.run.completed_at)}</div>
                {detail.run.error_message ? <div className="alert alert-danger top-gap-small">{detail.run.error_message}</div> : null}

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
              </Card>
            </>
          ) : null}
        </div>
      </section>
    </>
  );
}
