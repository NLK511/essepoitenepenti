import { FormEvent, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { getJson, postForm } from "../api";
import { Badge, Card, EmptyState, ErrorState, LoadingState, PageHeader, SectionTitle } from "../components/ui";
import type {
  RecommendationBaselineSummary,
  RecommendationCalibrationSummary,
  RecommendationEvidenceConcentrationSummary,
  RecommendationPlan,
  RecommendationSetupFamilyReviewSummary,
  Run,
} from "../types";
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

function sampleTone(status: string): "ok" | "warning" | "neutral" {
  if (status === "strong" || status === "usable") {
    return "ok";
  }
  if (status === "limited") {
    return "warning";
  }
  return "neutral";
}

function calibrationSliceSummary(calibrationReview: Record<string, unknown> | null, key: string): string {
  const item = asRecord(calibrationReview?.[key]);
  if (!item) {
    return "—";
  }
  const sliceKey = typeof item.key === "string" ? item.key : key;
  const sampleStatus = typeof item.sample_status === "string" ? item.sample_status : "unknown";
  const resolvedCount = typeof item.resolved_count === "number" ? item.resolved_count : 0;
  const winRate = typeof item.win_rate_percent === "number" ? `${item.win_rate_percent}%` : "—";
  return `${sliceKey} · ${sampleStatus} · n=${resolvedCount} · win ${winRate}`;
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
              <th>Sample</th>
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
                <td>
                  <Badge tone={sampleTone(bucket.sample_status)}>{bucket.sample_status}</Badge>
                  <div className="helper-text top-gap-small">min {bucket.min_required_resolved_count}</div>
                </td>
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

function SetupFamilySliceTable({
  title,
  buckets,
}: {
  title: string;
  buckets: RecommendationCalibrationSummary["by_confidence_bucket"];
}) {
  return (
    <div className="table-wrap top-gap-small">
      <table>
        <thead>
          <tr>
            <th>{title}</th>
            <th>Total</th>
            <th>Resolved</th>
            <th>Sample</th>
            <th>Win rate</th>
            <th>Avg 5d</th>
          </tr>
        </thead>
        <tbody>
          {buckets.length > 0 ? (
            buckets.map((bucket) => (
              <tr key={bucket.key}>
                <td>{bucket.label}</td>
                <td>{bucket.total_count}</td>
                <td>{bucket.resolved_count}</td>
                <td>
                  <Badge tone={sampleTone(bucket.sample_status)}>{bucket.sample_status}</Badge>
                  <div className="helper-text top-gap-small">min {bucket.min_required_resolved_count}</div>
                </td>
                <td>{bucket.win_rate_percent ?? "—"}%</td>
                <td>{bucket.average_return_5d ?? "—"}%</td>
              </tr>
            ))
          ) : (
            <tr>
              <td colSpan={6} className="helper-text">No slices stored yet.</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

export function RecommendationPlansPage() {
  const [searchParams, setSearchParams] = useSearchParams({ limit: "100" });
  const [plans, setPlans] = useState<RecommendationPlan[] | null>(null);
  const [calibration, setCalibration] = useState<RecommendationCalibrationSummary | null>(null);
  const [baselines, setBaselines] = useState<RecommendationBaselineSummary | null>(null);
  const [familyReview, setFamilyReview] = useState<RecommendationSetupFamilyReviewSummary | null>(null);
  const [evidenceConcentration, setEvidenceConcentration] = useState<RecommendationEvidenceConcentrationSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [evaluationMessage, setEvaluationMessage] = useState<string | null>(null);
  const [evaluating, setEvaluating] = useState(false);
  const [evaluatingPlanId, setEvaluatingPlanId] = useState<number | null>(null);

  useEffect(() => {
    async function load() {
      try {
        setError(null);
        const summaryParams = new URLSearchParams({ limit: "500" });
        const runId = searchParams.get("run_id");
        const ticker = searchParams.get("ticker");
        const setupFamily = searchParams.get("setup_family");
        if (runId) {
          summaryParams.set("run_id", runId);
        }
        if (ticker) {
          summaryParams.set("ticker", ticker);
        }
        if (setupFamily) {
          summaryParams.set("setup_family", setupFamily);
        }
        const summaryQuery = summaryParams.toString();
        setPlans(await getJson<RecommendationPlan[]>(buildQuery(searchParams)));
        setCalibration(await getJson<RecommendationCalibrationSummary>(`/api/recommendation-outcomes/summary?${summaryQuery}`));
        setBaselines(await getJson<RecommendationBaselineSummary>(`/api/recommendation-plans/baselines?${summaryQuery}`));
        setFamilyReview(await getJson<RecommendationSetupFamilyReviewSummary>(`/api/recommendation-outcomes/setup-family-review?${summaryQuery}`));
        setEvidenceConcentration(await getJson<RecommendationEvidenceConcentrationSummary>(`/api/recommendation-outcomes/evidence-concentration?${summaryQuery}`));
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
          <label className="form-field"><span>Setup family</span><select name="setup_family" defaultValue={searchParams.get("setup_family") ?? ""}><option value="">All</option><option value="breakout">breakout</option><option value="continuation">continuation</option><option value="mean_reversion">mean_reversion</option><option value="breakdown">breakdown</option><option value="catalyst_follow_through">catalyst_follow_through</option><option value="macro_beneficiary_loser">macro_beneficiary_loser</option></select></label>
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
          <>
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
            <SectionTitle
              title="Setup-family cohorts"
              subtitle="Directly compare breakout, continuation, mean-reversion, breakdown, catalyst, and macro cohorts without relying only on shared calibration slices."
            />
            <div className="table-wrap top-gap-small">
              <table>
                <thead>
                  <tr>
                    <th>Family cohort</th>
                    <th>Trade plans</th>
                    <th>Open</th>
                    <th>Resolved</th>
                    <th>Win rate</th>
                    <th>Avg 5d</th>
                    <th>Avg confidence</th>
                  </tr>
                </thead>
                <tbody>
                  {baselines.family_cohorts.map((item) => (
                    <tr key={item.key}>
                      <td>
                        <div>{item.label}</div>
                        {item.description ? <div className="helper-text top-gap-small">{item.description}</div> : null}
                      </td>
                      <td>{item.trade_plan_count}</td>
                      <td>{item.open_trade_count}</td>
                      <td>{item.resolved_trade_count}</td>
                      <td>{item.win_rate_percent ?? "—"}%</td>
                      <td>{item.average_return_5d ?? "—"}%</td>
                      <td>{item.average_confidence_percent ?? "—"}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : null}
      </Card>

      <Card className="top-gap">
        <SectionTitle
          title="Evidence concentration"
          subtitle={evidenceConcentration ? `Resolved ${evidenceConcentration.resolved_outcomes_reviewed} of ${evidenceConcentration.total_outcomes_reviewed} reviewed outcomes` : undefined}
        />
        {!evidenceConcentration && !error ? <LoadingState message="Loading evidence concentration…" /> : null}
        {evidenceConcentration ? (
          <>
            <div className="stats-grid top-gap-small">
              <Card><strong>{evidenceConcentration.overall_win_rate_percent ?? "—"}%</strong><div className="helper-text">overall resolved win rate</div></Card>
              <Card><strong>{evidenceConcentration.overall_average_return_5d ?? "—"}%</strong><div className="helper-text">overall avg 5d return</div></Card>
              <Card><strong>{evidenceConcentration.ready_for_expansion ? "yes" : "not yet"}</strong><div className="helper-text">ready for broader concentration</div></Card>
            </div>
            <div className="helper-text top-gap-small">{evidenceConcentration.focus_message}</div>
            <SectionTitle title="Strongest positive cohorts" />
            <div className="table-wrap top-gap-small">
              <table>
                <thead>
                  <tr>
                    <th>Cohort</th>
                    <th>Sample</th>
                    <th>Win rate edge</th>
                    <th>5d edge</th>
                    <th>Score</th>
                    <th>Interpretation</th>
                  </tr>
                </thead>
                <tbody>
                  {evidenceConcentration.strongest_positive_cohorts.map((item) => (
                    <tr key={`${item.slice_name}-${item.key}`}>
                      <td>{item.label}<div className="helper-text top-gap-small">{item.slice_name}</div></td>
                      <td><Badge tone={sampleTone(item.sample_status)}>{item.sample_status}</Badge><div className="helper-text top-gap-small">n={item.resolved_count} / min {item.min_required_resolved_count}</div></td>
                      <td>{item.edge_vs_overall_win_rate_percent ?? "—"} pts</td>
                      <td>{item.edge_vs_overall_return_5d ?? "—"}%</td>
                      <td>{item.concentration_score}</td>
                      <td>{item.interpretation}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <SectionTitle title="Weakest cohorts" />
            <div className="table-wrap top-gap-small">
              <table>
                <thead>
                  <tr>
                    <th>Cohort</th>
                    <th>Sample</th>
                    <th>Win rate edge</th>
                    <th>5d edge</th>
                    <th>Score</th>
                    <th>Interpretation</th>
                  </tr>
                </thead>
                <tbody>
                  {evidenceConcentration.weakest_cohorts.map((item) => (
                    <tr key={`${item.slice_name}-${item.key}`}>
                      <td>{item.label}<div className="helper-text top-gap-small">{item.slice_name}</div></td>
                      <td><Badge tone={sampleTone(item.sample_status)}>{item.sample_status}</Badge><div className="helper-text top-gap-small">n={item.resolved_count} / min {item.min_required_resolved_count}</div></td>
                      <td>{item.edge_vs_overall_win_rate_percent ?? "—"} pts</td>
                      <td>{item.edge_vs_overall_return_5d ?? "—"}%</td>
                      <td>{item.concentration_score}</td>
                      <td>{item.interpretation}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : null}
      </Card>

      <Card className="top-gap">
        <SectionTitle
          title="Setup-family evaluation review"
          subtitle={familyReview ? `Built from ${familyReview.total_outcomes_reviewed} stored outcome(s) across the current filters` : undefined}
        />
        {!familyReview && !error ? <LoadingState message="Loading setup-family review…" /> : null}
        {familyReview ? (
          <div className="top-gap-small">
            {familyReview.families.map((family) => (
              <Card key={family.family} className="top-gap-small">
                <SectionTitle
                  title={family.label}
                  subtitle={`resolved ${family.resolved_outcomes} · open ${family.open_outcomes} · wins ${family.win_outcomes} · losses ${family.loss_outcomes}`}
                />
                <div className="stats-grid top-gap-small">
                  <Card><strong>{family.overall_win_rate_percent ?? "—"}%</strong><div className="helper-text">resolved win rate</div></Card>
                  <Card><strong>{family.average_return_5d ?? "—"}%</strong><div className="helper-text">avg 5d return</div></Card>
                  <Card><strong>{family.average_mfe ?? "—"}%</strong><div className="helper-text">avg MFE</div></Card>
                  <Card><strong>{family.average_mae ?? "—"}%</strong><div className="helper-text">avg MAE</div></Card>
                </div>
                <SetupFamilySliceTable title="By horizon" buckets={family.by_horizon} />
                <SetupFamilySliceTable title="By transmission bias" buckets={family.by_transmission_bias} />
                <SetupFamilySliceTable title="By context regime" buckets={family.by_context_regime} />
              </Card>
            ))}
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
                  const actionReasonDetail = typeof evidenceSummary?.action_reason_detail === "string" ? evidenceSummary.action_reason_detail : "—";
                  const entryStyle = typeof evidenceSummary?.entry_style === "string" ? evidenceSummary.entry_style : "—";
                  const stopStyle = typeof evidenceSummary?.stop_style === "string" ? evidenceSummary.stop_style : "—";
                  const targetStyle = typeof evidenceSummary?.target_style === "string" ? evidenceSummary.target_style : "—";
                  const timingExpectation = typeof evidenceSummary?.timing_expectation === "string" ? evidenceSummary.timing_expectation : "—";
                  const evaluationFocus = Array.isArray(evidenceSummary?.evaluation_focus)
                    ? evidenceSummary.evaluation_focus.filter((value): value is string => typeof value === "string")
                    : [];
                  const invalidationSummary = typeof evidenceSummary?.invalidation_summary === "string" ? evidenceSummary.invalidation_summary : "—";
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
                  const effectiveThreshold = typeof calibrationReview?.effective_confidence_threshold === "number"
                    ? calibrationReview.effective_confidence_threshold
                    : null;
                  const rawConfidence = typeof calibrationReview?.raw_confidence_percent === "number"
                    ? calibrationReview.raw_confidence_percent
                    : null;
                  const calibratedConfidence = typeof calibrationReview?.calibrated_confidence_percent === "number"
                    ? calibrationReview.calibrated_confidence_percent
                    : null;
                  const confidenceAdjustment = typeof calibrationReview?.confidence_adjustment === "number"
                    ? calibrationReview.confidence_adjustment
                    : null;
                  const calibrationReviewStatus = typeof calibrationReview?.review_status === "string"
                    ? calibrationReview.review_status
                    : "disabled";
                  const calibrationReasons = Array.isArray(calibrationReview?.reasons)
                    ? calibrationReview.reasons.filter((value): value is string => typeof value === "string")
                    : [];
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
                        <div className="helper-text">{actionReasonDetail}</div>
                      </td>
                      <td>
                        <div>{plan.confidence_percent.toFixed(1)}%</div>
                        <div className="helper-text top-gap-small">raw {rawConfidence !== null ? `${rawConfidence.toFixed(1)}%` : "—"} · calibrated {calibratedConfidence !== null ? `${calibratedConfidence.toFixed(1)}%` : "—"}</div>
                        <div className="helper-text">adjustment {confidenceAdjustment !== null ? `${confidenceAdjustment > 0 ? "+" : ""}${confidenceAdjustment.toFixed(1)} pts` : "—"}</div>
                        <div className="helper-text">threshold {effectiveThreshold !== null ? `${effectiveThreshold.toFixed(1)}%` : "—"}</div>
                        <div className="helper-text">calibration {calibrationReviewStatus}</div>
                        <div className="helper-text">horizon {calibrationSliceSummary(calibrationReview, "horizon")}</div>
                        <div className="helper-text">setup {calibrationSliceSummary(calibrationReview, "setup_family")}</div>
                        <div className="helper-text">bucket {calibrationSliceSummary(calibrationReview, "confidence_bucket")}</div>
                        <div className="helper-text">reasons {calibrationReasons.length > 0 ? calibrationReasons.join(" · ") : "none"}</div>
                      </td>
                      <td>
                        <div className="helper-text">entry {plan.entry_price_low ?? "—"}{plan.entry_price_high !== null && plan.entry_price_high !== plan.entry_price_low ? ` – ${plan.entry_price_high}` : ""}</div>
                        <div className="helper-text">entry style {entryStyle}</div>
                        <div className="helper-text">stop {plan.stop_loss ?? "—"} · {stopStyle}</div>
                        <div className="helper-text">take {plan.take_profit ?? "—"} · {targetStyle}</div>
                        <div className="helper-text">timing {timingExpectation}</div>
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
                        <div className="helper-text top-gap-small">invalidation {invalidationSummary}</div>
                        <div className="helper-text">review focus {evaluationFocus.length > 0 ? evaluationFocus.join(" · ") : "—"}</div>
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
