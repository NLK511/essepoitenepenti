import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { getJson } from "../api";
import type { RecommendationQualityResponse } from "../types";
import { formatDate } from "../utils";
import { Badge, Card, EmptyState, ErrorState, HelpHint, LoadingState, PageHeader, SectionTitle, SegmentedTabs, StatCard } from "../components/ui";

const glossaryDoc = (section: string) => `/docs?doc=glossary&section=${section}`;
const recommendationQualityDoc = "/docs?doc=recommendation-quality-improvement-plan";
const qualityWindows = ["7d", "30d", "90d", "180d", "1y"] as const;

export function RecommendationQualityPage() {
  const [data, setData] = useState<RecommendationQualityResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedWindow, setSelectedWindow] = useState<(typeof qualityWindows)[number]>("30d");

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

  const selectedSummary = useMemo(() => {
    if (!data) {
      return null;
    }
    return data.windowed_summaries.find((item) => item.window_label === selectedWindow) ?? data.summary;
  }, [data, selectedWindow]);

  return (
    <>
      <PageHeader
        kicker="Advanced review"
        title="Recommendation quality summary"
        actions={<HelpHint tooltip="This page combines the metrics that matter for recommendation quality into one review surface." to="/docs?doc=recommendation-quality-improvement-plan" />}
      />
      {error ? <ErrorState message={error} /> : null}
      {!data && !error ? <LoadingState message="Loading recommendation quality summary…" /> : null}
      {data && selectedSummary ? (
        <div className="stack-page">
          <section className="metrics-grid">
            <StatCard label="Quality status" value={selectedSummary.status} helper={`${selectedSummary.window_label ?? "current"} window · ${selectedSummary.status_reason || `Updated ${formatDate(selectedSummary.generated_at)}`}`} tooltip="Overall recommendation-quality posture from confidence quality, baseline comparisons, where results look strongest, and walk-forward checks." tooltipTo={recommendationQualityDoc} />
            <StatCard label="Resolved outcomes" value={selectedSummary.resolved_outcomes} helper="Current outcome sample" tooltip="The number of stored outcomes that have resolved strongly enough to contribute to current review metrics." tooltipTo={glossaryDoc("outcome-evaluation")} />
            <StatCard label="Win rate" value={selectedSummary.overall_win_rate_percent !== null ? `${selectedSummary.overall_win_rate_percent.toFixed(1)}%` : "—"} helper="Overall resolved win rate" tooltip="Overall win/loss rate across the currently reviewed resolved outcome set. This is useful, but it should be read alongside calibration and return metrics." tooltipTo={recommendationQualityDoc} />
            <StatCard label="Where it works best" value={selectedSummary.ready_for_expansion ? "some groups stand out" : "nothing clear yet"} helper="Checks whether a few groups clearly beat the average" tooltip="This asks a simple question: do a few types of recommendations clearly look better than the rest? If yes, trust can expand there first. If not, stay selective and cautious." tooltipTo={glossaryDoc("evidence-concentration")} />
            <StatCard label="Almost entered" value={selectedSummary.entry_miss_diagnostics.near_entry_miss_count} helper={selectedSummary.entry_miss_diagnostics.near_entry_and_worked_count > 0 ? `${selectedSummary.entry_miss_diagnostics.near_entry_and_worked_count} then still worked` : "Unfilled plans that came very close"} tooltip="Counts plans that never entered but came within the fixed near-miss threshold. This helps separate bad theses from entries that were likely too strict." tooltipTo={glossaryDoc("entry-stop-take-profit")} />
            <StatCard label="Walk-forward" value={data.summary.walk_forward_promotion_recommended ? "recommended" : data.summary.walk_forward_error ? "error" : "watch"} helper="Active tuning gate status" tooltip="Shows whether later time-slice validation supports promotion. Walk-forward validation checks whether a change still looks good on later data instead of only one pooled sample." tooltipTo={glossaryDoc("walk-forward-validation")} />
            <StatCard label="Families" value={selectedSummary.family_count} helper="Setup families reviewed" tooltip="The number of setup families included in the current review surfaces. Family-level checks help show whether one trade archetype is carrying or hurting results." tooltipTo={glossaryDoc("setup-family")} />
          </section>

          <section className="card-grid">
            <Card>
              <SectionTitle kicker="Time windows" title="Rolling quality snapshots" subtitle="Choose a rolling window and use it across calibration, baselines, evidence, and family review." actions={<HelpHint tooltip="These rolling windows replace the old fixed latest-record summary so quality metrics can stay meaningful as plan volume grows." to={recommendationQualityDoc} />} />
              {data.windowed_summaries.length === 0 ? <EmptyState message="No rolling quality windows available." /> : (
                <>
                  <div className="top-gap-small">
                    <SegmentedTabs
                      value={selectedWindow}
                      onChange={(value) => setSelectedWindow(value as (typeof qualityWindows)[number])}
                      options={qualityWindows.map((window) => ({ value: window, label: window.toUpperCase() }))}
                    />
                  </div>
                  <article className="data-card top-gap-small">
                    <div className="data-card-header">
                      <div className="cluster">
                        <Badge tone={selectedSummary.status === "healthy" ? "ok" : selectedSummary.status === "needs_attention" ? "warning" : "neutral"}>{selectedSummary.window_label ?? "window"}</Badge>
                        <Badge>{selectedSummary.status}</Badge>
                      </div>
                      <div className="helper-text">{selectedSummary.resolved_outcomes} resolved · win rate {selectedSummary.overall_win_rate_percent !== null ? `${selectedSummary.overall_win_rate_percent.toFixed(1)}%` : "—"}</div>
                    </div>
                    <div className="data-points top-gap-small">
                      <div className="data-point"><span className="data-point-label">actual actionable 5d</span><span className="data-point-value">{selectedSummary.actual_actionable_average_return_5d !== null ? selectedSummary.actual_actionable_average_return_5d.toFixed(3) : "—"}</span></div>
                      <div className="data-point"><span className="data-point-label">high-confidence 5d</span><span className="data-point-value">{selectedSummary.high_confidence_average_return_5d !== null ? selectedSummary.high_confidence_average_return_5d.toFixed(3) : "—"}</span></div>
                      <div className="data-point"><span className="data-point-label">clear bright spots?</span><span className="data-point-value">{selectedSummary.ready_for_expansion ? "yes" : "no"}</span></div>
                      <div className="data-point"><span className="data-point-label">families</span><span className="data-point-value">{selectedSummary.family_count}</span></div>
                    </div>
                    <div className="helper-text top-gap-small">{selectedSummary.status_reason}</div>
                  </article>
                </>
              )}
            </Card>

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
                <div className="data-point"><span className="data-point-label">brier</span><span className="data-point-value">{selectedSummary.calibration_report?.brier_score !== null && selectedSummary.calibration_report?.brier_score !== undefined ? selectedSummary.calibration_report.brier_score.toFixed(4) : "—"}</span></div>
                <div className="data-point"><span className="data-point-label">ece</span><span className="data-point-value">{selectedSummary.calibration_report?.expected_calibration_error !== null && selectedSummary.calibration_report?.expected_calibration_error !== undefined ? selectedSummary.calibration_report.expected_calibration_error.toFixed(4) : "—"}</span></div>
                <div className="data-point"><span className="data-point-label">smoothed brier</span><span className="data-point-value">{selectedSummary.smoothed_calibration_report?.brier_score !== null && selectedSummary.smoothed_calibration_report?.brier_score !== undefined ? selectedSummary.smoothed_calibration_report.brier_score.toFixed(4) : "—"}</span></div>
                <div className="data-point"><span className="data-point-label">smoothed ece</span><span className="data-point-value">{selectedSummary.smoothed_calibration_report?.expected_calibration_error !== null && selectedSummary.smoothed_calibration_report?.expected_calibration_error !== undefined ? selectedSummary.smoothed_calibration_report.expected_calibration_error.toFixed(4) : "—"}</span></div>
              </div>
            </Card>

            <Card>
              <SectionTitle kicker="Baselines" title="Baseline comparison" actions={<HelpHint tooltip="Baseline comparisons check whether the full recommendation workflow is outperforming simpler comparison groups." to={glossaryDoc("baseline-comparison")} />} />
              <div className="data-points top-gap-small">
                <div className="data-point"><span className="data-point-label">actual actionable win rate</span><span className="data-point-value">{selectedSummary.actual_actionable_win_rate_percent !== null ? `${selectedSummary.actual_actionable_win_rate_percent.toFixed(1)}%` : "—"}</span></div>
                <div className="data-point"><span className="data-point-label">actual actionable 5d return</span><span className="data-point-value">{selectedSummary.actual_actionable_average_return_5d !== null ? selectedSummary.actual_actionable_average_return_5d.toFixed(3) : "—"}</span></div>
                <div className="data-point"><span className="data-point-label">high-confidence win rate</span><span className="data-point-value">{selectedSummary.high_confidence_win_rate_percent !== null ? `${selectedSummary.high_confidence_win_rate_percent.toFixed(1)}%` : "—"}</span></div>
                <div className="data-point"><span className="data-point-label">high-confidence 5d return</span><span className="data-point-value">{selectedSummary.high_confidence_average_return_5d !== null ? selectedSummary.high_confidence_average_return_5d.toFixed(3) : "—"}</span></div>
              </div>
            </Card>
          </section>

          <section className="card-grid">
            <Card>
              <SectionTitle kicker="Where it works best" title="Which groups stand out" actions={<HelpHint tooltip="This section tries to answer one down-to-earth question: are a few groups clearly doing better than the rest, or is the picture still too mixed to trust much?" to={glossaryDoc("evidence-concentration")} />} />
              <div className="data-points top-gap-small">
                <div className="data-point"><span className="data-point-label">better-performing groups</span><span className="data-point-value">{selectedSummary.strongest_positive_count}</span></div>
                <div className="data-point"><span className="data-point-label">weaker groups</span><span className="data-point-value">{selectedSummary.weakest_count}</span></div>
                <div className="data-point"><span className="data-point-label">safe to widen trust?</span><span className="data-point-value">{selectedSummary.ready_for_expansion ? "yes" : "not yet"}</span></div>
              </div>
            </Card>

            <Card>
              <SectionTitle kicker="Entry quality" title="Almost entered, then moved" actions={<HelpHint tooltip="These numbers highlight plans that never filled, but came very close to entry. They help show when the idea may have been fine but the entry was too strict." to={glossaryDoc("entry-stop-take-profit")} />} />
              <div className="data-points top-gap-small">
                <div className="data-point"><span className="data-point-label">never entered</span><span className="data-point-value">{selectedSummary.entry_miss_diagnostics.never_entered_count}</span></div>
                <div className="data-point"><span className="data-point-label">almost entered</span><span className="data-point-value">{selectedSummary.entry_miss_diagnostics.near_entry_miss_count}</span></div>
                <div className="data-point"><span className="data-point-label">still moved right</span><span className="data-point-value">{selectedSummary.entry_miss_diagnostics.direction_worked_without_entry_count}</span></div>
                <div className="data-point"><span className="data-point-label">almost entered + worked</span><span className="data-point-value">{selectedSummary.entry_miss_diagnostics.near_entry_and_worked_count}</span></div>
                <div className="data-point"><span className="data-point-label">almost-entered rate</span><span className="data-point-value">{selectedSummary.entry_miss_diagnostics.near_entry_miss_rate_percent !== null ? `${selectedSummary.entry_miss_diagnostics.near_entry_miss_rate_percent.toFixed(1)}%` : "—"}</span></div>
                <div className="data-point"><span className="data-point-label">avg miss distance</span><span className="data-point-value">{selectedSummary.entry_miss_diagnostics.average_entry_miss_distance_percent !== null ? `${selectedSummary.entry_miss_diagnostics.average_entry_miss_distance_percent.toFixed(2)}%` : "—"}</span></div>
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
                <Badge tone="info">{selectedSummary.status}</Badge>
                <Link to="/research" className="button-secondary">Open research</Link>
              </div>
            </Card>
          </section>
        </div>
      ) : null}
    </>
  );
}
