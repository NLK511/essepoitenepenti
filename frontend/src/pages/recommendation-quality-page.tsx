import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { getJson } from "../api";
import type { RecommendationQualityResponse } from "../types";
import { formatDate } from "../utils";
import { Badge, Card, EmptyState, ErrorState, HelpHint, LoadingState, PageHeader, SectionTitle, StatCard } from "../components/ui";

const glossaryDoc = (section: string) => `/docs?doc=glossary&section=${section}`;
const recommendationQualityDoc = "/docs?doc=recommendation-quality-improvement-plan";

export function RecommendationQualityPage() {
  const [data, setData] = useState<RecommendationQualityResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        setError(null);
        const payload = await getJson<RecommendationQualityResponse>("/api/recommendation-quality/summary");
        if (!cancelled) {
          setData(payload);
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : "Failed to load recommendation quality summary");
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <>
      <PageHeader
        kicker="Advanced review"
        title="Recommendation quality summary"
        subtitle="A single operator view for calibration, baselines, evidence concentration, and walk-forward promotion readiness."
        actions={<HelpHint tooltip="This page combines the metrics that matter for recommendation quality into one review surface." to="/docs?doc=recommendation-quality-improvement-plan" />}
      />
      {error ? <ErrorState message={error} /> : null}
      {!data && !error ? <LoadingState message="Loading recommendation quality summary…" /> : null}
      {data ? (
        <div className="stack-page">
          <section className="metrics-grid">
            <StatCard label="Quality status" value={data.summary.status} helper={data.summary.status_reason || `Updated ${formatDate(data.summary.generated_at)}`} tooltip="Overall recommendation-quality posture from calibration, baseline comparisons, evidence concentration, and walk-forward checks." tooltipTo={recommendationQualityDoc} />
            <StatCard label="Resolved outcomes" value={data.summary.resolved_outcomes} helper="Current outcome sample" tooltip="The number of stored outcomes that have resolved strongly enough to contribute to current review metrics." tooltipTo={glossaryDoc("outcome-evaluation")} />
            <StatCard label="Win rate" value={data.summary.overall_win_rate_percent !== null ? `${data.summary.overall_win_rate_percent.toFixed(1)}%` : "—"} helper="Overall resolved win rate" tooltip="Overall win/loss rate across the currently reviewed resolved outcome set. This is useful, but it should be read alongside calibration and return metrics." tooltipTo={recommendationQualityDoc} />
            <StatCard label="Evidence" value={data.summary.ready_for_expansion ? "ready" : "conservative"} helper="Whether strong cohorts separate clearly enough to trust broader usage" tooltip="Shows whether similar recommendation groups, called cohorts, are separating clearly enough to deserve more trust, or whether the evidence is still too thin and should stay conservative." tooltipTo={glossaryDoc("cohort")} />
            <StatCard label="Walk-forward" value={data.summary.walk_forward_promotion_recommended ? "recommended" : data.summary.walk_forward_error ? "error" : "watch"} helper="Active tuning gate status" tooltip="Shows whether later time-slice validation supports promotion. Walk-forward validation checks whether a change still looks good on later data instead of only one pooled sample." tooltipTo={glossaryDoc("walk-forward-validation")} />
            <StatCard label="Families" value={data.summary.family_count} helper="Setup families reviewed" tooltip="The number of setup families included in the current review surfaces. Family-level checks help show whether one trade archetype is carrying or hurting results." tooltipTo={glossaryDoc("setup-family")} />
          </section>

          <section className="card-grid">
            <Card>
              <SectionTitle kicker="Current tuning" title="Live thresholds and guardrails" subtitle="Record the active settings before changing anything." actions={<HelpHint tooltip="These are the live thresholds and safeguards now affecting recommendation generation and promotion decisions." to={recommendationQualityDoc} />} />
              <div className="data-points top-gap-small">
                <div className="data-point"><span className="data-point-label">confidence threshold</span><span className="data-point-value">{data.summary.tuning_settings.confidence_threshold.toFixed(1)}</span></div>
                <div className="data-point"><span className="data-point-label">shortlist aggressiveness</span><span className="data-point-value">{data.summary.tuning_settings.signal_gating.shortlist_aggressiveness.toFixed(2)}</span></div>
                <div className="data-point"><span className="data-point-label">degraded penalty</span><span className="data-point-value">{data.summary.tuning_settings.signal_gating.degraded_penalty.toFixed(2)}</span></div>
                <div className="data-point"><span className="data-point-label">plan-gen min actionable</span><span className="data-point-value">{data.summary.tuning_settings.plan_generation.min_actionable_resolved}</span></div>
                <div className="data-point"><span className="data-point-label">plan-gen min validation</span><span className="data-point-value">{data.summary.tuning_settings.plan_generation.min_validation_resolved}</span></div>
                <div className="data-point"><span className="data-point-label">auto promote</span><span className="data-point-value">{data.summary.tuning_settings.plan_generation.auto_promote_enabled ? "on" : "off"}</span></div>
              </div>
            </Card>
          </section>

          <section className="card-grid">
            <Card>
              <SectionTitle kicker="Next actions" title="What to do next" subtitle="Recommended follow-ups based on the current summary." actions={<Link to="/research" className="button-secondary">Open research</Link>} />
              {data.next_actions.length === 0 ? <EmptyState message="No next actions generated." /> : <ul className="list-reset top-gap-small">{data.next_actions.map((item) => <li key={item} className="list-item compact-item">{item}</li>)}</ul>}
            </Card>

            <Card>
              <SectionTitle kicker="Calibration" title="Calibration status" actions={<HelpHint tooltip="Calibration asks whether higher displayed confidence has actually deserved more trust after outcomes resolved." to={glossaryDoc("calibration")} />} />
              <div className="data-points top-gap-small">
                <div className="data-point"><span className="data-point-label">brier</span><span className="data-point-value">{data.summary.calibration_report?.brier_score !== null && data.summary.calibration_report?.brier_score !== undefined ? data.summary.calibration_report.brier_score.toFixed(4) : "—"}</span></div>
                <div className="data-point"><span className="data-point-label">ece</span><span className="data-point-value">{data.summary.calibration_report?.expected_calibration_error !== null && data.summary.calibration_report?.expected_calibration_error !== undefined ? data.summary.calibration_report.expected_calibration_error.toFixed(4) : "—"}</span></div>
                <div className="data-point"><span className="data-point-label">smoothed brier</span><span className="data-point-value">{data.summary.smoothed_calibration_report?.brier_score !== null && data.summary.smoothed_calibration_report?.brier_score !== undefined ? data.summary.smoothed_calibration_report.brier_score.toFixed(4) : "—"}</span></div>
                <div className="data-point"><span className="data-point-label">smoothed ece</span><span className="data-point-value">{data.summary.smoothed_calibration_report?.expected_calibration_error !== null && data.summary.smoothed_calibration_report?.expected_calibration_error !== undefined ? data.summary.smoothed_calibration_report.expected_calibration_error.toFixed(4) : "—"}</span></div>
              </div>
            </Card>

            <Card>
              <SectionTitle kicker="Baselines" title="Baseline comparison" actions={<HelpHint tooltip="Baseline comparisons check whether the full recommendation workflow is outperforming simpler comparison groups." to={glossaryDoc("baseline-comparison")} />} />
              <div className="data-points top-gap-small">
                <div className="data-point"><span className="data-point-label">actual actionable win rate</span><span className="data-point-value">{data.summary.actual_actionable_win_rate_percent !== null ? `${data.summary.actual_actionable_win_rate_percent.toFixed(1)}%` : "—"}</span></div>
                <div className="data-point"><span className="data-point-label">actual actionable 5d return</span><span className="data-point-value">{data.summary.actual_actionable_average_return_5d !== null ? data.summary.actual_actionable_average_return_5d.toFixed(3) : "—"}</span></div>
                <div className="data-point"><span className="data-point-label">high-confidence win rate</span><span className="data-point-value">{data.summary.high_confidence_win_rate_percent !== null ? `${data.summary.high_confidence_win_rate_percent.toFixed(1)}%` : "—"}</span></div>
                <div className="data-point"><span className="data-point-label">high-confidence 5d return</span><span className="data-point-value">{data.summary.high_confidence_average_return_5d !== null ? data.summary.high_confidence_average_return_5d.toFixed(3) : "—"}</span></div>
              </div>
            </Card>
          </section>

          <section className="card-grid">
            <Card>
              <SectionTitle kicker="Evidence concentration" title="Concentration posture" actions={<HelpHint tooltip="Evidence concentration shows where the strongest and weakest measured cohorts are, so operators know where to trust results more and where to stay skeptical." to={glossaryDoc("evidence-concentration")} />} />
              <div className="data-points top-gap-small">
                <div className="data-point"><span className="data-point-label">strongest cohorts</span><span className="data-point-value">{data.summary.strongest_positive_count}</span></div>
                <div className="data-point"><span className="data-point-label">weakest cohorts</span><span className="data-point-value">{data.summary.weakest_count}</span></div>
                <div className="data-point"><span className="data-point-label">evidence ready</span><span className="data-point-value">{data.summary.ready_for_expansion ? "yes" : "no"}</span></div>
              </div>
            </Card>

            <Card>
              <SectionTitle kicker="Walk-forward" title="Promotion gate" actions={<HelpHint tooltip="The promotion gate decides whether a tuning change is allowed to become live. It uses walk-forward validation and sample thresholds so thin evidence does not auto-promote a change." to={glossaryDoc("promotion-gate")} />} />
              <div className="data-points top-gap-small">
                <div className="data-point"><span className="data-point-label">promotion</span><span className="data-point-value">{data.summary.walk_forward_promotion_recommended ? "recommended" : "not yet"}</span></div>
                <div className="data-point"><span className="data-point-label">avg win-rate delta</span><span className="data-point-value">{data.summary.walk_forward_average_win_rate_delta !== null ? data.summary.walk_forward_average_win_rate_delta.toFixed(2) : "—"}</span></div>
                <div className="data-point"><span className="data-point-label">avg EV delta</span><span className="data-point-value">{data.summary.walk_forward_average_expected_value_delta !== null ? data.summary.walk_forward_average_expected_value_delta.toFixed(4) : "—"}</span></div>
                <div className="data-point"><span className="data-point-label">family count</span><span className="data-point-value">{data.summary.family_count}</span></div>
              </div>
            </Card>

            <Card>
              <SectionTitle kicker="Assessment" title="Latest performance assessment" actions={<HelpHint tooltip="This is the latest narrative assessment snapshot for recent recommendation behavior. Use it as a summary aid, not as a substitute for the underlying metrics." to={recommendationQualityDoc} />} />
              <div className="helper-text">{typeof data.summary.latest_assessment?.content === "string" ? data.summary.latest_assessment.content.slice(0, 400) : "No assessment text available."}</div>
            </Card>
          </section>

          <section className="card-grid">
            <Card>
              <SectionTitle kicker="Details" title="Calibration buckets" subtitle="Use the research page for the full reliability curves." actions={<HelpHint tooltip="Calibration buckets are confidence bands used to compare predicted confidence against what actually happened after outcomes resolved." to={glossaryDoc("confidence-bucket")} />} />
              <div className="cluster top-gap-small">
                <Badge tone="info">{data.summary.status}</Badge>
                <Link to="/research" className="button-secondary">Open research</Link>
              </div>
            </Card>
          </section>
        </div>
      ) : null}
    </>
  );
}
