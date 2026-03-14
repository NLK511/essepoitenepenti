import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { getJson } from "../api";
import { WorkflowRunResults } from "../components/workflow-run-results";
import { Badge, Card, EmptyState, ErrorState, LoadingState, PageHeader, SectionTitle } from "../components/ui";
import type { RunDetailResponse } from "../types";
import { diagnosticsMessages, directionTone, formatDate, formatDuration, jobTypeLabel, recommendationStateTone, runTone } from "../utils";

export function RunDetailPage() {
  const { runId } = useParams<{ runId: string }>();
  const [detail, setDetail] = useState<RunDetailResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      if (!runId) {
        setError("Run id is missing");
        return;
      }
      try {
        setError(null);
        setDetail(await getJson<RunDetailResponse>(`/api/runs/${runId}`));
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : "Failed to load run");
      }
    }
    void load();
  }, [runId]);

  return (
    <>
      <PageHeader
        kicker="Run detail"
        title={detail ? `Run #${detail.run.id}` : "Run detail"}
        subtitle="A run is one job execution. This page focuses on execution state and the recommendations produced by that run, not on treating the run itself as the trade output."
        actions={
          <>
            <Link to="/jobs/debugger" className="button-secondary">Back to debugger</Link>
            <Link to="/jobs/history" className="button-subtle">Open history</Link>
          </>
        }
      />
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
          </Card>

          <Card>
            <SectionTitle kicker="Produced output" title={detail.run.job_type === "proposal_generation" ? "Recommendations created by this run" : "Workflow result stored on the run"} />
            {detail.run.job_type === "proposal_generation" ? (
              <>
                {detail.outputs.length === 0 ? <EmptyState message="No recommendations stored for this run." /> : null}
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
                          <div className="summary-item"><span className="summary-label">Stop loss</span><span className="summary-value">{item.stop_loss}</span></div>
                          <div className="summary-item"><span className="summary-label">Take profit</span><span className="summary-value">{item.take_profit}</span></div>
                        </div>
                        <div className="helper-text">{item.indicator_summary || "No indicator summary stored for this recommendation."}</div>
                        <div className="helper-text">Evaluated {formatDate(item.evaluated_at)}</div>
                        <div className="helper-text"><Link to={`/recommendations/${item.id}`}>Open recommendation detail</Link></div>
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
        </div>
      ) : null}
    </>
  );
}
