import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { getJson } from "../api";
import { WorkflowRunResults } from "../components/workflow-run-results";
import { Badge, Card, EmptyState, ErrorState, LoadingState, PageHeader, SectionTitle } from "../components/ui";
import type { Run, RunDetailResponse } from "../types";
import { diagnosticsMessages, directionTone, formatDate, formatDuration, jobTypeLabel, recommendationStateTone, runTone } from "../utils";

export function DebuggerPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [detail, setDetail] = useState<RunDetailResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

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

  return (
    <>
      <PageHeader
        kicker="Problem investigation"
        title="Inspect degraded or failed runs without leaving the app."
        subtitle="Pick a recent run, review visible warnings first, and expand raw details only if the higher-level diagnosis is not enough."
      />
      {error ? <ErrorState message={error} /> : null}
      <section className="two-column debugger-layout">
        <Card>
          <SectionTitle kicker="Recent runs" title="Choose a run" />
          {!runs && !error ? <LoadingState message="Loading runs…" /> : null}
          {runs && runs.length === 0 ? <EmptyState message="No runs available." /> : null}
          {runs ? (
            <ul className="list-reset">
              {runs.map((run) => (
                <li key={run.id ?? run.created_at} className="list-item">
                  <div>
                    <button
                      type="button"
                      className="link-button"
                      onClick={() => run.id && setSearchParams({ run_id: String(run.id) })}
                    >
                      Run #{run.id}
                    </button>
                    <div className="helper-text">Job {run.job_id} · {jobTypeLabel(run.job_type)} · {formatDate(run.created_at)}</div>
                    {run.scheduled_for ? <div className="helper-text">Scheduled slot {formatDate(run.scheduled_for)}</div> : null}
                  </div>
                  <Badge tone={runTone(run.status)}>{run.status}</Badge>
                </li>
              ))}
            </ul>
          ) : null}
        </Card>

        <div className="stack-page">
          {!detail && !error ? <LoadingState message="Select a run to inspect." /> : null}
          {detail ? (
            <Card>
              <SectionTitle kicker="Run outputs" title={`Run #${detail.run.id}`} />
              <div className="cluster">
                <Badge tone={runTone(detail.run.status)}>{detail.run.status}</Badge>
                <Badge>Job {detail.run.job_id}</Badge>
                <Badge>{jobTypeLabel(detail.run.job_type)}</Badge>
                <Badge>{formatDuration(detail.run.duration_seconds)}</Badge>
                <Link to={`/runs/${detail.run.id}`} className="button-secondary">Open run page</Link>
              </div>
              <div className="helper-text">Created {formatDate(detail.run.created_at)}</div>
              <div className="helper-text">Scheduled slot {formatDate(detail.run.scheduled_for)}</div>
              <div className="helper-text">Started {formatDate(detail.run.started_at)}</div>
              <div className="helper-text">Completed {formatDate(detail.run.completed_at)}</div>
              {detail.run.error_message ? <div className="alert alert-danger top-gap-small">{detail.run.error_message}</div> : null}
              {detail.run.timing_json ? (
                <div className="helper-text top-gap-small">Timing data is available but hidden here to avoid repeating run metadata already shown above.</div>
              ) : null}
              {detail.run.job_type === "proposal_generation" ? (
                <>
                  {detail.outputs.length === 0 ? <EmptyState message="No legacy recommendation outputs for the selected run. Review recommendation plans and outcomes instead." /> : null}
                  <div className="stack-page">
                    {detail.outputs.map((output) => {
                      const item = output.recommendation;
                      const messages = diagnosticsMessages(output.diagnostics);
                      return (
                        <article key={item.id ?? `${item.ticker}-${item.created_at}`} className="recommendation-card">
                          <div className="card-headline">
                            <div>
                              <div className="cluster">
                                <Link to={`/tickers/${item.ticker}`} className="badge badge-info badge-link">{item.ticker}</Link>
                                <Badge tone={directionTone(item.direction)}>{item.direction}</Badge>
                                <Badge tone={recommendationStateTone(item.state)}>{item.state}</Badge>
                              </div>
                              <h3 className="subsection-title">{item.confidence}% confidence</h3>
                            </div>
                            <Badge tone={messages.length > 0 ? "warning" : "ok"}>
                              {messages.length > 0 ? `${messages.length} warning(s)` : "No warnings"}
                            </Badge>
                          </div>
                          <div className="summary-grid">
                            <div className="summary-item"><span className="summary-label">Entry</span><span className="summary-value">{item.entry_price}</span></div>
                            <div className="summary-item"><span className="summary-label">Stop</span><span className="summary-value">{item.stop_loss}</span></div>
                            <div className="summary-item"><span className="summary-label">Take profit</span><span className="summary-value">{item.take_profit}</span></div>
                          </div>
                          <div className="helper-text">{item.indicator_summary || "No indicator summary stored for this recommendation."}</div>
                          <div className="helper-text">Legacy recommendation detail pages are retired. Review the run's recommendation plans instead.</div>
                          {messages.length > 0 ? <ul>{messages.map((message) => <li key={message} className="warning-text">{message}</li>)}</ul> : <div className="helper-text">No warnings or errors.</div>}
                          {output.diagnostics.raw_output ? (
                            <details>
                              <summary>Raw details</summary>
                              <pre>{output.diagnostics.raw_output}</pre>
                            </details>
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
          ) : null}
        </div>
      </section>
    </>
  );
}
