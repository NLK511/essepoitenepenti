import { FormEvent, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { getJson, postForm } from "../api";
import { Badge, Card, EmptyState, ErrorState, LoadingState, PageHeader, SectionTitle } from "../components/ui";
import type { RecommendationPlan, Run } from "../types";
import { formatDate } from "../utils";

function buildQuery(searchParams: URLSearchParams): string {
  const query = searchParams.toString();
  return query ? `/api/recommendation-plans?${query}` : "/api/recommendation-plans";
}

function actionTone(action: string): "ok" | "warning" | "neutral" {
  if (action === "long") {
    return "ok";
  }
  if (action === "short") {
    return "warning";
  }
  return "neutral";
}

export function RecommendationPlansPage() {
  const [searchParams, setSearchParams] = useSearchParams({ limit: "100" });
  const [plans, setPlans] = useState<RecommendationPlan[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [evaluationMessage, setEvaluationMessage] = useState<string | null>(null);
  const [evaluating, setEvaluating] = useState(false);
  const [evaluatingPlanId, setEvaluatingPlanId] = useState<number | null>(null);

  useEffect(() => {
    async function load() {
      try {
        setError(null);
        setPlans(await getJson<RecommendationPlan[]>(buildQuery(searchParams)));
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : "Failed to load recommendation plans");
      }
    }
    void load();
  }, [searchParams]);

  async function queueEvaluation(planId?: number) {
    try {
      if (planId) {
        setEvaluatingPlanId(planId);
      } else {
        setEvaluating(true);
      }
      setError(null);
      setEvaluationMessage(null);
      const run = planId
        ? await postForm<Run>(`/api/recommendation-plans/${planId}/evaluate`, {})
        : await postForm<Run>("/api/recommendation-plans/evaluate", {});
      setEvaluationMessage(
        planId
          ? `Queued recommendation-plan evaluation run #${run.id} for plan #${planId}.`
          : `Queued recommendation-plan evaluation run #${run.id}.`,
      );
      setPlans(await getJson<RecommendationPlan[]>(buildQuery(searchParams)));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to queue recommendation-plan evaluation");
    } finally {
      setEvaluating(false);
      setEvaluatingPlanId(null);
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    const next = new URLSearchParams();
    for (const [key, value] of formData.entries()) {
      const normalized = String(value).trim();
      if (normalized) {
        next.set(key, normalized);
      }
    }
    if (!next.has("limit")) {
      next.set("limit", "100");
    }
    setSearchParams(next);
  }

  return (
    <>
      <PageHeader
        kicker="Redesign browse"
        title="Recommendation plans"
        subtitle="Browse persisted plan outputs outside run detail. This page helps operators review long, short, and no-action decisions produced by the new orchestration layer."
        actions={
          <button type="button" className="button" onClick={() => void queueEvaluation()} disabled={evaluating}>
            {evaluating ? "Queueing…" : "Queue plan evaluation"}
          </button>
        }
      />
      {error ? <ErrorState message={error} /> : null}
      {evaluationMessage ? <Card><div className="helper-text">{evaluationMessage}</div></Card> : null}
      <Card>
        <SectionTitle kicker="Filters" title="Find recommendation plans" />
        <form className="form-grid" onSubmit={handleSubmit}>
          <label className="form-field"><span>Ticker</span><input name="ticker" defaultValue={searchParams.get("ticker") ?? ""} placeholder="AAPL" /></label>
          <label className="form-field"><span>Action</span><select name="action" defaultValue={searchParams.get("action") ?? ""}><option value="">All</option><option value="long">long</option><option value="short">short</option><option value="no_action">no_action</option></select></label>
          <label className="form-field"><span>Run id</span><input name="run_id" defaultValue={searchParams.get("run_id") ?? ""} placeholder="145" /></label>
          <label className="form-field"><span>Limit</span><select name="limit" defaultValue={searchParams.get("limit") ?? "100"}><option value="25">25</option><option value="50">50</option><option value="100">100</option><option value="200">200</option></select></label>
          <div className="form-actions"><button className="button" type="submit">Apply</button></div>
        </form>
      </Card>

      <Card className="top-gap">
        <SectionTitle title="Results" subtitle={plans ? `${plans.length} recommendation plan(s)` : undefined} />
        {!plans && !error ? <LoadingState message="Loading recommendation plans…" /> : null}
        {plans && plans.length === 0 ? <EmptyState message="No recommendation plans match the current filters." /> : null}
        {plans ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Computed</th>
                  <th>Ticker</th>
                  <th>Action</th>
                  <th>Confidence</th>
                  <th>Execution</th>
                  <th>Latest outcome</th>
                  <th>Thesis</th>
                  <th>Run</th>
                </tr>
              </thead>
              <tbody>
                {plans.map((plan) => (
                  <tr key={plan.id ?? `${plan.ticker}-${plan.computed_at}`}>
                    <td>{formatDate(plan.computed_at)}</td>
                    <td>
                      <div className="cluster">
                        <Link to={`/tickers/${plan.ticker}`} className="badge badge-info badge-link">{plan.ticker}</Link>
                        <Badge tone={plan.warnings.length > 0 ? "warning" : "ok"}>{plan.status}</Badge>
                      </div>
                      <div className="helper-text top-gap-small">horizon {plan.horizon}</div>
                    </td>
                    <td><Badge tone={actionTone(plan.action)}>{plan.action}</Badge></td>
                    <td>{plan.confidence_percent.toFixed(1)}%</td>
                    <td>
                      <div className="helper-text">entry {plan.entry_price_low ?? "—"}{plan.entry_price_high !== null && plan.entry_price_high !== plan.entry_price_low ? ` – ${plan.entry_price_high}` : ""}</div>
                      <div className="helper-text">stop {plan.stop_loss ?? "—"}</div>
                      <div className="helper-text">take {plan.take_profit ?? "—"}</div>
                    </td>
                    <td>
                      {plan.latest_outcome ? (
                        <>
                          <div className="cluster">
                            <Badge tone={plan.latest_outcome.outcome === "win" ? "ok" : plan.latest_outcome.outcome === "loss" ? "danger" : "neutral"}>{plan.latest_outcome.outcome}</Badge>
                            <span className="helper-text">{plan.latest_outcome.status}</span>
                          </div>
                          <div className="helper-text top-gap-small">1d {plan.latest_outcome.horizon_return_1d ?? "—"}% · 5d {plan.latest_outcome.horizon_return_5d ?? "—"}%</div>
                          <div className="helper-text top-gap-small">MFE {plan.latest_outcome.max_favorable_excursion ?? "—"}% · MAE {plan.latest_outcome.max_adverse_excursion ?? "—"}%</div>
                        </>
                      ) : (
                        <div className="helper-text">No outcome stored yet.</div>
                      )}
                    </td>
                    <td>
                      <div>{plan.thesis_summary || "No thesis stored."}</div>
                      {plan.rationale_summary ? <div className="helper-text top-gap-small">{plan.rationale_summary}</div> : null}
                      {plan.id ? (
                        <div className="helper-text top-gap-small">
                          <button
                            type="button"
                            className="button-subtle"
                            disabled={evaluatingPlanId === plan.id}
                            onClick={() => void queueEvaluation(plan.id ?? undefined)}
                          >
                            {evaluatingPlanId === plan.id ? "Queueing evaluation…" : "Evaluate this plan"}
                          </button>
                        </div>
                      ) : null}
                    </td>
                    <td>{plan.run_id ? <Link to={`/runs/${plan.run_id}`}>#{plan.run_id}</Link> : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </Card>
    </>
  );
}
