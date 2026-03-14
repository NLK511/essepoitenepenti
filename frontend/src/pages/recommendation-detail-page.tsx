import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { getJson, postForm } from "../api";
import { Badge, Card, EmptyState, ErrorState, LoadingState, PageHeader, SectionTitle } from "../components/ui";
import type { RecommendationDetailResponse, Run } from "../types";
import { diagnosticsMessages, directionTone, formatDate, recommendationStateTone, runTone } from "../utils";

export function RecommendationDetailPage() {
  const { recommendationId } = useParams<{ recommendationId: string }>();
  const [detail, setDetail] = useState<RecommendationDetailResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [evaluating, setEvaluating] = useState(false);

  useEffect(() => {
    async function load() {
      if (!recommendationId) {
        setError("Recommendation id is missing");
        return;
      }
      try {
        setError(null);
        setDetail(await getJson<RecommendationDetailResponse>(`/api/recommendations/${recommendationId}`));
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : "Failed to load recommendation");
      }
    }
    void load();
  }, [recommendationId]);

  async function queueEvaluation() {
    if (!recommendationId) {
      setError("Recommendation id is missing");
      return;
    }
    try {
      setEvaluating(true);
      setError(null);
      setNotice(null);
      const run = await postForm<Run>(`/api/recommendations/${recommendationId}/evaluate`, {});
      setNotice(`Queued scoped evaluation run #${run.id} for this recommendation.`);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to queue recommendation evaluation");
    } finally {
      setEvaluating(false);
    }
  }

  return (
    <>
      <PageHeader
        kicker="Recommendation detail"
        title={detail ? `${detail.recommendation.ticker} recommendation #${detail.recommendation.id}` : "Recommendation detail"}
        subtitle="A recommendation is the trade-ready output. The source run remains visible for traceability, but the main object here is the trade plan itself."
        actions={
          <>
            <Link to="/jobs/history" className="button-secondary">Back to recommendations</Link>
            <button type="button" className="button" onClick={() => void queueEvaluation()} disabled={evaluating || !detail}>
              {evaluating ? "Queueing evaluation…" : "Evaluate this recommendation"}
            </button>
            {detail ? <Link to={`/runs/${detail.run.id}`} className="button-subtle">Open source run</Link> : null}
          </>
        }
      />
      {error ? <ErrorState message={error} /> : null}
      {notice ? <Card><div className="helper-text">{notice}</div></Card> : null}
      {!detail && !error ? <LoadingState message="Loading recommendation detail…" /> : null}
      {detail ? (
        <div className="stack-page">
          <Card>
            <div className="cluster">
              <Badge tone={directionTone(detail.recommendation.direction)}>{detail.recommendation.direction}</Badge>
              <Badge tone={recommendationStateTone(detail.recommendation.state)}>{detail.recommendation.state}</Badge>
              <Badge>{detail.recommendation.confidence}% confidence</Badge>
            </div>
            <div className="summary-grid top-gap-small">
              <div className="summary-item"><span className="summary-label">Entry</span><span className="summary-value">{detail.recommendation.entry_price}</span></div>
              <div className="summary-item"><span className="summary-label">Stop loss</span><span className="summary-value">{detail.recommendation.stop_loss}</span></div>
              <div className="summary-item"><span className="summary-label">Take profit</span><span className="summary-value">{detail.recommendation.take_profit}</span></div>
            </div>
            <div className="helper-text top-gap-small">Created {formatDate(detail.recommendation.created_at)}</div>
            <div className="helper-text">Evaluated {formatDate(detail.recommendation.evaluated_at)}</div>
            <div className="helper-text top-gap-small">{detail.recommendation.indicator_summary || "No indicator summary stored for this recommendation."}</div>
          </Card>

          <Card>
            <SectionTitle kicker="Source run" title={`Run #${detail.run.id}`} />
            <div className="cluster">
              <Badge tone={runTone(detail.run.status)}>{detail.run.status}</Badge>
              <Badge>Job {detail.run.job_id}</Badge>
            </div>
            <div className="helper-text top-gap-small">Created {formatDate(detail.run.created_at)}</div>
            <div className="helper-text">Started {formatDate(detail.run.started_at)}</div>
            <div className="helper-text">Completed {formatDate(detail.run.completed_at)}</div>
            {detail.run.error_message ? <div className="alert alert-danger top-gap-small">{detail.run.error_message}</div> : null}
          </Card>

          <Card>
            <SectionTitle kicker="Diagnostics" title="Run-time context for this recommendation" />
            {diagnosticsMessages(detail.diagnostics).length === 0 ? (
              <EmptyState message="No warnings or errors were stored for this recommendation." />
            ) : (
              <ul>
                {diagnosticsMessages(detail.diagnostics).map((message) => <li key={message} className="warning-text">{message}</li>)}
              </ul>
            )}
            {detail.diagnostics.raw_output ? (
              <details>
                <summary>Raw details</summary>
                <pre>{detail.diagnostics.raw_output}</pre>
              </details>
            ) : null}
          </Card>
        </div>
      ) : null}
    </>
  );
}
