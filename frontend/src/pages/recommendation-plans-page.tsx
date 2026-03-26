import { FormEvent, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { getJson, postForm } from "../api";
import { Badge, Card, EmptyState, ErrorState, LoadingState, PageHeader, SectionTitle } from "../components/ui";
import type { RecommendationBaselineSummary, RecommendationCalibrationSummary, RecommendationPlan, Run } from "../types";
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

function biasTone(value: string): "ok" | "warning" | "neutral" {
  if (value === "tailwind") {
    return "ok";
  }
  if (value === "headwind") {
    return "warning";
  }
  return "neutral";
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function CalibrationBucketTable({ title, buckets }: { title: string; buckets: RecommendationCalibrationSummary["by_confidence_bucket"] }) {
  return (
    <div className="top-gap">
      <SectionTitle title={title} />
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Slice</th>
              <th>Total</th>
              <th>Resolved</th>
              <th>Win rate</th>
              <th>Avg 5d</th>
            </tr>
          </thead>
          <tbody>
            {buckets.map((bucket) => (
              <tr key={bucket.key}>
                <td>{bucket.label}</td>
                <td>{bucket.total_count}</td>
                <td>{bucket.resolved_count}</td>
                <td>{bucket.win_rate_percent ?? "—"}%</td>
                <td>{bucket.average_return_5d ?? "—"}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function RecommendationPlansPage() {
  const [searchParams, setSearchParams] = useSearchParams({ limit: "100" });
  const [plans, setPlans] = useState<RecommendationPlan[] | null>(null);
  const [calibration, setCalibration] = useState<RecommendationCalibrationSummary | null>(null);
  const [baselines, setBaselines] = useState<RecommendationBaselineSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [evaluationMessage, setEvaluationMessage] = useState<string | null>(null);
  const [evaluating, setEvaluating] = useState(false);
  const [evaluatingPlanId, setEvaluatingPlanId] = useState<number | null>(null);

  useEffect(() => {
    async function load() {
      try {
        setError(null);
        const summaryQuery = `limit=500${searchParams.get("run_id") ? `&run_id=${searchParams.get("run_id")}` : ""}${searchParams.get("ticker") ? `&ticker=${encodeURIComponent(searchParams.get("ticker") ?? "")}` : ""}`;
        setPlans(await getJson<RecommendationPlan[]>(buildQuery(searchParams)));
        setCalibration(await getJson<RecommendationCalibrationSummary>(`/api/recommendation-outcomes/summary?${summaryQuery}`));
        setBaselines(await getJson<RecommendationBaselineSummary>(`/api/recommendation-plans/baselines?${summaryQuery}`));
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
        <SectionTitle
          title="Calibration snapshot"
          subtitle={calibration ? `Resolved ${calibration.resolved_outcomes} of ${calibration.total_outcomes} stored outcome(s)` : undefined}
        />
        {!calibration && !error ? <LoadingState message="Loading calibration summary…" /> : null}
        {calibration ? (
          <>
            <div className="stats-grid top-gap-small">
              <Card><strong>{calibration.overall_win_rate_percent ?? "—"}%</strong><div className="helper-text">overall resolved win rate</div></Card>
              <Card><strong>{calibration.win_outcomes}</strong><div className="helper-text">wins</div></Card>
              <Card><strong>{calibration.loss_outcomes}</strong><div className="helper-text">losses</div></Card>
              <Card><strong>{calibration.no_action_outcomes}</strong><div className="helper-text">no_action outcomes</div></Card>
            </div>
            <CalibrationBucketTable title="By confidence bucket" buckets={calibration.by_confidence_bucket} />
            <CalibrationBucketTable title="By setup family" buckets={calibration.by_setup_family} />
            <CalibrationBucketTable title="By horizon" buckets={calibration.by_horizon} />
            <CalibrationBucketTable title="By transmission bias" buckets={calibration.by_transmission_bias} />
            <CalibrationBucketTable title="By context regime" buckets={calibration.by_context_regime} />
            <CalibrationBucketTable title="By horizon + setup family" buckets={calibration.by_horizon_setup_family} />
          </>
        ) : null}
      </Card>

      <Card className="top-gap">
        <SectionTitle
          title="Baseline comparisons"
          subtitle={baselines ? `Reviewed ${baselines.total_trade_plans_reviewed} trade plan(s) across ${baselines.total_plans_reviewed} total plan(s)` : undefined}
        />
        {!baselines && !error ? <LoadingState message="Loading baseline comparisons…" /> : null}
        {baselines ? (
          <div className="table-wrap top-gap-small">
            <table>
              <thead>
                <tr>
                  <th>Baseline</th>
                  <th>Trade plans</th>
                  <th>Resolved</th>
                  <th>Win rate</th>
                  <th>Avg 5d</th>
                  <th>Avg confidence</th>
                </tr>
              </thead>
              <tbody>
                {baselines.comparisons.map((item) => (
                  <tr key={item.key}>
                    <td>
                      <div>{item.label}</div>
                      {item.description ? <div className="helper-text top-gap-small">{item.description}</div> : null}
                    </td>
                    <td>{item.trade_plan_count}</td>
                    <td>{item.resolved_trade_count}</td>
                    <td>{item.win_rate_percent ?? "—"}%</td>
                    <td>{item.average_return_5d ?? "—"}%</td>
                    <td>{item.average_confidence_percent ?? "—"}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
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
                  <th>Transmission</th>
                  <th>Latest outcome</th>
                  <th>Thesis</th>
                  <th>Run</th>
                </tr>
              </thead>
              <tbody>
                {plans.map((plan) => {
                  const signalBreakdown = asRecord(plan.signal_breakdown);
                  const evidenceSummary = asRecord(plan.evidence_summary);
                  const transmissionSummary = asRecord(signalBreakdown?.transmission_summary) ?? asRecord(evidenceSummary?.transmission_summary);
                  const calibrationReview = asRecord(signalBreakdown?.calibration_review) ?? asRecord(evidenceSummary?.calibration_review);
                  const setupFamily = typeof signalBreakdown?.setup_family === "string" ? signalBreakdown.setup_family : "—";
                  const actionReason = typeof evidenceSummary?.action_reason === "string" ? evidenceSummary.action_reason : "—";
                  const transmissionBias = typeof transmissionSummary?.context_bias === "string" ? transmissionSummary.context_bias : "unknown";
                  const transmissionAlignment = typeof transmissionSummary?.alignment_percent === "number" ? transmissionSummary.alignment_percent : null;
                  const transmissionTags = Array.isArray(transmissionSummary?.transmission_tags)
                    ? transmissionSummary.transmission_tags.filter((value): value is string => typeof value === "string")
                    : [];
                  const effectiveThreshold = typeof calibrationReview?.effective_confidence_threshold === "number"
                    ? calibrationReview.effective_confidence_threshold
                    : null;
                  return (
                    <tr key={plan.id ?? `${plan.ticker}-${plan.computed_at}`}>
                      <td>{formatDate(plan.computed_at)}</td>
                      <td>
                        <div className="cluster">
                          <Link to={`/tickers/${plan.ticker}`} className="badge badge-info badge-link">{plan.ticker}</Link>
                          <Badge tone={plan.warnings.length > 0 ? "warning" : "ok"}>{plan.status}</Badge>
                        </div>
                        <div className="helper-text top-gap-small">horizon {plan.horizon}</div>
                        <div className="helper-text">setup {setupFamily}</div>
                      </td>
                      <td>
                        <Badge tone={actionTone(plan.action)}>{plan.action}</Badge>
                        <div className="helper-text top-gap-small">reason {actionReason}</div>
                      </td>
                      <td>
                        <div>{plan.confidence_percent.toFixed(1)}%</div>
                        <div className="helper-text top-gap-small">threshold {effectiveThreshold !== null ? `${effectiveThreshold.toFixed(1)}%` : "—"}</div>
                      </td>
                      <td>
                        <div className="helper-text">entry {plan.entry_price_low ?? "—"}{plan.entry_price_high !== null && plan.entry_price_high !== plan.entry_price_low ? ` – ${plan.entry_price_high}` : ""}</div>
                        <div className="helper-text">stop {plan.stop_loss ?? "—"}</div>
                        <div className="helper-text">take {plan.take_profit ?? "—"}</div>
                      </td>
                      <td>
                        <Badge tone={biasTone(transmissionBias)}>{transmissionBias}</Badge>
                        <div className="helper-text top-gap-small">alignment {transmissionAlignment !== null ? `${transmissionAlignment.toFixed(1)}%` : "—"}</div>
                        <div className="helper-text">tags {transmissionTags.length > 0 ? transmissionTags.join(" · ") : "none"}</div>
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
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : null}
      </Card>
    </>
  );
}
