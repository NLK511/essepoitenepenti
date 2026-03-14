import { FormEvent, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { getJson, postForm } from "../api";
import { Badge, Card, EmptyState, ErrorState, LoadingState, PageHeader, SectionTitle } from "../components/ui";
import type { HistoryResponse, Run, RunStatus } from "../types";
import { directionTone, formatDate, recommendationStateTone, runTone, warningCount } from "../utils";

function buildHistoryQuery(searchParams: URLSearchParams): string {
  const query = searchParams.toString();
  return query ? `/api/history?${query}` : "/api/history";
}

export function HistoryPage() {
  const [searchParams, setSearchParams] = useSearchParams({ sort: "created_at", order: "desc", per_page: "10" });
  const [data, setData] = useState<HistoryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [evaluationMessage, setEvaluationMessage] = useState<string | null>(null);
  const [evaluating, setEvaluating] = useState(false);
  const [evaluatingRecommendationId, setEvaluatingRecommendationId] = useState<number | null>(null);

  useEffect(() => {
    async function load() {
      try {
        setError(null);
        setData(await getJson<HistoryResponse>(buildHistoryQuery(searchParams)));
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : "Failed to load history");
      }
    }
    void load();
  }, [searchParams]);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    const next = new URLSearchParams();
    for (const [key, value] of formData.entries()) {
      const normalized = String(value);
      if (normalized) {
        next.set(key, normalized);
      }
    }
    if (!next.has("sort")) {
      next.set("sort", "created_at");
    }
    if (!next.has("order")) {
      next.set("order", "desc");
    }
    if (!next.has("per_page")) {
      next.set("per_page", "10");
    }
    setSearchParams(next);
  }

  function setPage(page: number) {
    const next = new URLSearchParams(searchParams);
    next.set("page", String(page));
    setSearchParams(next);
  }

  async function runEvaluation() {
    try {
      setEvaluating(true);
      setError(null);
      setEvaluationMessage(null);
      const run = await postForm<Run>("/api/recommendations/evaluate", {});
      setEvaluationMessage(`Queued evaluation run #${run.id}. Open the debugger or run detail to follow progress.`);
      setData(await getJson<HistoryResponse>(buildHistoryQuery(searchParams)));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to queue evaluation");
    } finally {
      setEvaluating(false);
    }
  }

  async function runRecommendationEvaluation(recommendationId: number) {
    try {
      setEvaluatingRecommendationId(recommendationId);
      setError(null);
      setEvaluationMessage(null);
      const run = await postForm<Run>(`/api/recommendations/${recommendationId}/evaluate`, {});
      setEvaluationMessage(`Queued scoped evaluation run #${run.id} for recommendation #${recommendationId}.`);
      setData(await getJson<HistoryResponse>(buildHistoryQuery(searchParams)));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to queue recommendation evaluation");
    } finally {
      setEvaluatingRecommendationId(null);
    }
  }

  return (
    <>
      <PageHeader
        kicker="Historical review"
        title="Review recommendations as trade-ready outputs, separate from runs."
        subtitle="Each row is a recommendation produced by a run. You can queue a full evaluation run or a scoped single-recommendation evaluation, and both paths now create auditable run records."
        actions={
          <>
            <button type="button" className="button" onClick={runEvaluation} disabled={evaluating}>
              {evaluating ? "Queueing…" : "Queue full evaluation"}
            </button>
            <Link to="/jobs/debugger" className="button-secondary">
              Open debugger
            </Link>
          </>
        }
      />
      {error ? <ErrorState message={error} /> : null}
      {evaluationMessage ? <Card><div className="helper-text">{evaluationMessage}</div></Card> : null}
      <Card>
        <SectionTitle kicker="Filters" title="Recommendation history" />
        <form className="form-grid" onSubmit={handleSubmit}>
          <label className="form-field"><span>Ticker</span><input name="ticker" defaultValue={searchParams.get("ticker") ?? ""} placeholder="AAPL" /></label>
          <label className="form-field"><span>Direction</span><select name="direction" defaultValue={searchParams.get("direction") ?? ""}><option value="">All</option><option value="LONG">LONG</option><option value="SHORT">SHORT</option><option value="NEUTRAL">NEUTRAL</option></select></label>
          <label className="form-field"><span>State</span><select name="state" defaultValue={searchParams.get("state") ?? ""}><option value="">All</option><option value="PENDING">PENDING</option><option value="WIN">WIN</option><option value="LOSS">LOSS</option></select></label>
          <label className="form-field"><span>Warnings</span><select name="warnings" defaultValue={searchParams.get("warnings") ?? ""}><option value="">All</option><option value="only">Only warnings</option><option value="none">No warnings</option></select></label>
          <label className="form-field"><span>Sort</span><select name="sort" defaultValue={searchParams.get("sort") ?? "created_at"}><option value="created_at">Created</option><option value="ticker">Ticker</option><option value="direction">Direction</option><option value="state">State</option><option value="confidence">Confidence</option></select></label>
          <label className="form-field"><span>Order</span><select name="order" defaultValue={searchParams.get("order") ?? "desc"}><option value="desc">Descending</option><option value="asc">Ascending</option></select></label>
          <label className="form-field"><span>Per page</span><select name="per_page" defaultValue={searchParams.get("per_page") ?? "10"}><option value="10">10</option><option value="20">20</option><option value="50">50</option><option value="100">100</option></select></label>
          <div className="form-actions"><button className="button" type="submit">Apply</button></div>
        </form>
        {data ? <div className="helper-text">Results {data.pagination.total_results} · Page {data.pagination.page} of {data.pagination.total_pages}</div> : null}
      </Card>

      <Card className="top-gap">
        <SectionTitle title="Results" />
        {!data && !error ? <LoadingState message="Loading history…" /> : null}
        {data && data.items.length === 0 ? <EmptyState message="No recommendations match the current filters." /> : null}
        {data ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Created</th>
                  <th>Recommendation</th>
                  <th>Run</th>
                  <th>Risk plan</th>
                  <th>State</th>
                  <th>Diagnostics</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((item) => (
                  <tr key={item.recommendation_id}>
                    <td>{formatDate(item.created_at)}</td>
                    <td>
                      <div className="cluster">
                        <Link to={`/tickers/${item.ticker}`} className="badge badge-info badge-link">{item.ticker}</Link>
                        <Badge tone={directionTone(item.direction)}>{item.direction}</Badge>
                      </div>
                      <div className="helper-text top-gap-small">{item.confidence}% confidence · Entry {item.entry_price}</div>
                      <div className="helper-text top-gap-small">{item.indicator_summary || "No indicator summary stored."}</div>
                      <div className="helper-text top-gap-small cluster">
                        <Link to={`/recommendations/${item.recommendation_id}`}>Open recommendation</Link>
                        <button
                          type="button"
                          className="button-subtle"
                          disabled={evaluatingRecommendationId === item.recommendation_id}
                          onClick={() => void runRecommendationEvaluation(item.recommendation_id)}
                        >
                          {evaluatingRecommendationId === item.recommendation_id ? "Queueing evaluation…" : "Evaluate this recommendation"}
                        </button>
                      </div>
                    </td>
                    <td><Link to={`/runs/${item.run_id}`}>#{item.run_id}</Link> · <Badge tone={runTone(item.run_status as RunStatus)}>{item.run_status}</Badge></td>
                    <td><div>Stop {item.stop_loss}</div><div>Take profit {item.take_profit}</div></td>
                    <td>
                      <Badge tone={recommendationStateTone(item.state)}>{item.state}</Badge>
                      <div className="helper-text top-gap-small">Evaluated {formatDate(item.evaluated_at)}</div>
                    </td>
                    <td>
                      <Badge tone={warningCount(item) > 0 ? "warning" : "ok"}>
                        {warningCount(item) > 0 ? `${warningCount(item)} issue(s)` : "No warnings"}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
        {data && data.pagination.total_pages > 1 ? (
          <div className="pagination">
            <button type="button" className="button-secondary" disabled={!data.pagination.has_prev} onClick={() => setPage(1)}>First</button>
            <button type="button" className="button-secondary" disabled={!data.pagination.has_prev} onClick={() => setPage(data.pagination.prev_page)}>Previous</button>
            <Badge>{data.pagination.page} / {data.pagination.total_pages}</Badge>
            <button type="button" className="button-secondary" disabled={!data.pagination.has_next} onClick={() => setPage(data.pagination.next_page)}>Next</button>
            <button type="button" className="button-secondary" disabled={!data.pagination.has_next} onClick={() => setPage(data.pagination.total_pages)}>Last</button>
          </div>
        ) : null}
      </Card>
    </>
  );
}
