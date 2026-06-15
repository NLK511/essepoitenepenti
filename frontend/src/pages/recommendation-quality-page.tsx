import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { getJson } from "../api";
import type { RecommendationQualityResponse } from "../types";
import { cohortSampleStatusTone, formatDate, normalizeReviewWindow, REVIEW_WINDOW_OPTIONS } from "../utils";
import { Badge, Card, DisclosureCard, EmptyState, ErrorState, HelpHint, LoadingState, PageHeader, SectionTitle, SegmentedTabs, StatCard } from "../components/ui";

const glossaryDoc = (section: string) => `/docs?doc=glossary&section=${section}`;
const recommendationQualityDoc = "/docs?doc=recommendation-quality-improvement-plan";

function percent(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${value.toFixed(1)}%`;
}

function currency(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `$${value.toFixed(2)}`;
}

function gatingSeverityTone(severity: string | null | undefined): "ok" | "warning" | "danger" | "neutral" | "info" {
  const normalized = (severity ?? "").trim().toLowerCase();
  if (normalized === "critical") return "danger";
  if (normalized === "warning") return "warning";
  if (normalized === "info") return "ok";
  return "neutral";
}

function trustTone(label: string | null | undefined): "ok" | "warning" | "danger" | "neutral" | "info" {
  const normalized = (label ?? "").trim().toLowerCase();
  if (normalized === "healthy" || normalized === "eligible_for_cautious_expansion") return "ok";
  if (normalized === "watch" || normalized === "research_only" || normalized === "insufficient") return "warning";
  if (normalized === "degraded" || normalized === "demote_or_halt" || normalized === "blocked") return "danger";
  return "info";
}

export function RecommendationQualityPage() {
  const [data, setData] = useState<RecommendationQualityResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedWindow, setSelectedWindow] = useState<(typeof REVIEW_WINDOW_OPTIONS)[number]["value"]>("1d");

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
    return data.windowed_summaries.find((item) => normalizeReviewWindow(item.window_label ?? null, "1d") === selectedWindow) ?? data.summary;
  }, [data, selectedWindow]);

  const reliabilityReport = data?.reliability_report ?? null;
  const confidenceBucket = reliabilityReport?.by_confidence_bucket[0] ?? null;
  const familyBucket = reliabilityReport?.by_setup_family[0] ?? null;
  const actionBucket = reliabilityReport?.by_action[0] ?? null;
  const planGenerationSettings = data?.summary.tuning_settings.plan_generation_tuning ?? data?.summary.tuning_settings.plan_generation ?? null;
  const entryDiagnostics = selectedSummary?.simulated_entry_miss_diagnostics ?? selectedSummary?.entry_miss_diagnostics ?? null;
  const gatingAlert = data?.gating_severity_alert ?? null;

  return (
    <>
      <PageHeader
        kicker="Performance authority"
        title="Quality & Edge"
        actions={<HelpHint tooltip="This is the canonical page for edge validation, effective outcomes, calibration, baselines, reliability, and evidence-backed improvement actions." to="/docs?doc=recommendation-quality-improvement-plan" />}
      />
      {error ? <ErrorState message={error} /> : null}
      {!data && !error ? <LoadingState message="Loading recommendation quality summary…" /> : null}
      {data && selectedSummary ? (
        <div className="stack-page">
          <section className="insight-grid">
            <Card>
              <SectionTitle kicker="Edge gate" title="Can this policy be trusted?" subtitle="This is the authoritative autonomy gate. Policy health is only a compact headline." />
              <div className="data-stack top-gap-small">
                <div className="operator-status-item">
                  <div className="operator-status-head"><span className="summary-label">edge validation</span><Badge tone={trustTone(data.summary.edge_validation_gate?.label)}>{data.summary.edge_validation_gate?.label ?? "unknown"}</Badge></div>
                  <div className="operator-status-value">{data.summary.edge_validation_gate?.broker_selected_outcomes ?? "—"} broker selected outcomes</div>
                  <div className="helper-text">{data.summary.edge_validation_gate?.reasons?.slice(0, 3).join(" · ") || "No edge-gate reasons reported"}</div>
                </div>
                <div className="operator-status-item">
                  <div className="operator-status-head"><span className="summary-label">policy health</span><Badge tone={trustTone(data.summary.policy_health?.label)}>{data.summary.policy_health?.label ?? "unknown"}</Badge></div>
                  <div className="operator-status-value">{data.summary.policy_health?.resolved_selected_outcomes ?? "—"} selected resolved</div>
                  <div className="helper-text">{data.summary.policy_health?.reasons?.slice(0, 3).join(" · ") || "No policy-health reasons reported"}</div>
                </div>
                <div className="operator-status-item">
                  <div className="operator-status-head"><span className="summary-label">gating severity</span><Badge tone={gatingSeverityTone(gatingAlert?.severity)}>{gatingAlert?.severity ?? "unknown"}</Badge></div>
                  <div className="operator-status-value">{gatingAlert?.metrics?.near_miss_non_shortlisted ?? "—"} non-shortlisted near misses</div>
                  <div className="helper-text">{gatingAlert?.reasons?.slice(0, 3).join(" · ") || "No gating-severity check recorded"}</div>
                </div>
              </div>
            </Card>

            <Card>
              <SectionTitle kicker="Effective outcomes" title="What actually happened?" subtitle={`${selectedSummary.window_label ?? "current"} window · ${selectedSummary.status_reason || `Updated ${formatDate(selectedSummary.generated_at)}`}`} />
              <div className="data-stack top-gap-small">
                <StatCard label="Quality status" value={selectedSummary.status} helper="Current quality posture" tooltip="Overall recommendation-quality posture from confidence quality, baseline comparisons, where results look strongest, and walk-forward checks." tooltipTo={recommendationQualityDoc} />
                <StatCard label="Resolved outcomes" value={selectedSummary.resolved_outcomes} helper="Broker/effective current outcome sample" tooltip="The number of stored outcomes that have resolved strongly enough to contribute to current review metrics." tooltipTo={glossaryDoc("outcome-evaluation")} />
                <StatCard label="Win rate" value={percent(selectedSummary.overall_win_rate_percent)} helper={`Policy P&L ${currency(data.summary.policy_health?.realized_pnl)}`} tooltip="Overall win/loss rate across the currently reviewed resolved outcome set. This is useful, but it should be read alongside calibration and return metrics." tooltipTo={recommendationQualityDoc} />
              </div>
            </Card>

            <Card>
              <SectionTitle kicker="Reliability" title="Where is the evidence strong?" subtitle="Use these as evidence concentration and calibration headlines; details stay lower on the page." />
              <div className="data-stack top-gap-small">
                <StatCard label="Where it works best" value={selectedSummary.ready_for_expansion ? "some groups stand out" : "nothing clear yet"} helper={`${selectedSummary.strongest_positive_count} stronger · ${selectedSummary.weakest_count} weaker`} tooltip="This asks whether a few groups inside the current cohort clearly look better than the rest." tooltipTo={glossaryDoc("evidence-concentration")} />
                <StatCard label="Calibration ECE" value={selectedSummary.calibration_report?.expected_calibration_error !== null && selectedSummary.calibration_report?.expected_calibration_error !== undefined ? selectedSummary.calibration_report.expected_calibration_error.toFixed(4) : "—"} helper="Average confidence gap" tooltip="Expected calibration error: the average gap between displayed confidence and realized win rate across confidence buckets." tooltipTo={glossaryDoc("confidence-bucket")} />
                <StatCard label="Families" value={selectedSummary.family_count} helper="Setup families reviewed" tooltip="The number of setup families included in the current review surfaces." tooltipTo={glossaryDoc("setup-family")} />
              </div>
            </Card>

            <Card>
              <SectionTitle kicker="Next action" title="What should change?" subtitle="Only act when the evidence points to a specific improvement path." />
              {data.next_actions.length === 0 ? <EmptyState message="No next actions generated." /> : <ul className="list-reset top-gap-small">{data.next_actions.slice(0, 3).map((item) => <li key={item} className="list-item compact-item">{item}</li>)}</ul>}
              <div className="cluster top-gap-small">
                <Badge tone={data.summary.walk_forward_promotion_recommended ? "ok" : data.summary.walk_forward_error ? "danger" : "warning"}>walk-forward {data.summary.walk_forward_promotion_recommended ? "recommended" : data.summary.walk_forward_error ? "error" : "watch"}</Badge>
                <Link to="/research" className="button-subtle">⌂ Research Lab</Link>
              </div>
            </Card>
          </section>

          <section className="card-grid">
            <Card>
              <SectionTitle kicker="Time windows" title="Rolling quality snapshots" subtitle="Choose a rolling window and use it across calibration, baselines, evidence, and family review." actions={<HelpHint tooltip="These rolling windows replace the old fixed latest-record summary so quality metrics can stay meaningful as plan volume grows." to={recommendationQualityDoc} />} />
              {data.windowed_summaries.length === 0 ? <EmptyState message="No rolling quality windows available." /> : (
                <>
                  <div className="top-gap-small">
                    <SegmentedTabs
                      value={selectedWindow}
                      onChange={(value) => setSelectedWindow(normalizeReviewWindow(value, "1d"))}
                      options={REVIEW_WINDOW_OPTIONS}
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
              <SectionTitle kicker="Gating alert" title="Is shortlist gating too severe?" subtitle={gatingAlert?.interpretation ?? "Weekly diagnostic; do not lower gates without benchmark and walk-forward evidence."} />
              {gatingAlert ? (
                <div className="data-stack top-gap-small">
                  <div className="cluster">
                    <Badge tone={gatingSeverityTone(gatingAlert.severity)}>{gatingAlert.severity}</Badge>
                    <Badge tone="neutral">{gatingAlert.window_days ?? "—"}d window</Badge>
                    <span className="helper-text">checked {gatingAlert.created_at ? formatDate(gatingAlert.created_at) : "—"}</span>
                  </div>
                  <div className="data-points">
                    <div className="data-point"><span className="data-point-label">samples</span><span className="data-point-value">{gatingAlert.metrics?.total_samples ?? "—"}</span></div>
                    <div className="data-point"><span className="data-point-label">shortlist rate</span><span className="data-point-value">{percent(gatingAlert.metrics?.shortlist_rate_percent)}</span></div>
                    <div className="data-point"><span className="data-point-label">near misses rejected</span><span className="data-point-value">{gatingAlert.metrics?.near_miss_non_shortlisted ?? "—"}</span></div>
                    <div className="data-point"><span className="data-point-label">high priority rejected</span><span className="data-point-value">{gatingAlert.metrics?.high_priority_non_shortlisted ?? "—"}</span></div>
                    <div className="data-point"><span className="data-point-label">positive-gap rejected</span><span className="data-point-value">{gatingAlert.metrics?.positive_gap_non_shortlisted ?? "—"}</span></div>
                    <div className="data-point"><span className="data-point-label">positive-gap rate</span><span className="data-point-value">{percent(gatingAlert.metrics?.positive_gap_non_shortlisted_rate_percent)}</span></div>
                    <div className="data-point"><span className="data-point-label">benchmark coverage</span><span className="data-point-value">{percent(gatingAlert.metrics?.benchmark_coverage_non_shortlisted_percent)}</span></div>
                    <div className="data-point"><span className="data-point-label">actionable plans</span><span className="data-point-value">{gatingAlert.metrics?.actionable_plans ?? "—"}</span></div>
                  </div>
                  <div className="helper-text">Reasons: {gatingAlert.reasons?.join(" · ") || "—"}</div>
                  <div className="helper-text">Window: {gatingAlert.window_start ? formatDate(gatingAlert.window_start) : "—"} → {gatingAlert.window_end ? formatDate(gatingAlert.window_end) : "—"}</div>
                </div>
              ) : <EmptyState message="No gating-severity check has been recorded yet." />}
            </Card>

            <DisclosureCard kicker="Current tuning" title="Live thresholds and guardrails" subtitle="Advanced reference: record the active settings before changing anything." actions={<HelpHint tooltip="These are the live thresholds and safeguards now affecting recommendation generation and promotion decisions." to={recommendationQualityDoc} />}>
              <div className="data-points top-gap-small">
                <div className="data-point"><span className="data-point-label">confidence threshold</span><span className="data-point-value">{data.summary.tuning_settings.confidence_threshold.toFixed(1)}</span></div>
                <div className="data-point"><span className="data-point-label">shortlist aggressiveness</span><span className="data-point-value">{data.summary.tuning_settings.signal_gating.shortlist_aggressiveness.toFixed(2)}</span></div>
                <div className="data-point"><span className="data-point-label">degraded penalty</span><span className="data-point-value">{data.summary.tuning_settings.signal_gating.degraded_penalty.toFixed(2)}</span></div>
                <div className="data-point"><span className="data-point-label">plan-gen min actionable</span><span className="data-point-value">{planGenerationSettings?.min_actionable_resolved ?? "—"}</span></div>
                <div className="data-point"><span className="data-point-label">plan-gen min validation</span><span className="data-point-value">{planGenerationSettings?.min_validation_resolved ?? "—"}</span></div>
                <div className="data-point"><span className="data-point-label">auto promote</span><span className="data-point-value">{planGenerationSettings?.auto_promote_enabled ? "on" : "off"}</span></div>
              </div>
              {data.summary.active_policy_evaluation ? (
                <div className="data-points top-gap-medium">
                  <div className="data-point"><span className="data-point-label">policy sample</span><span className="data-point-value">{data.summary.active_policy_evaluation.resolved_selected_outcomes} resolved</span></div>
                  <div className="data-point"><span className="data-point-label">policy win rate</span><span className="data-point-value">{data.summary.active_policy_evaluation.win_rate_percent !== null ? `${data.summary.active_policy_evaluation.win_rate_percent.toFixed(1)}%` : "—"}</span></div>
                  <div className="data-point"><span className="data-point-label">policy P&L</span><span className="data-point-value">${data.summary.active_policy_evaluation.realized_pnl.toFixed(2)}</span></div>
                  <div className="data-point"><span className="data-point-label">policy robustness</span><span className="data-point-value"><Badge tone={data.summary.active_policy_evaluation.robustness_label === "strong" || data.summary.active_policy_evaluation.robustness_label === "usable" ? "ok" : data.summary.active_policy_evaluation.robustness_label === "limited" ? "warning" : "neutral"}>{data.summary.active_policy_evaluation.robustness_label}</Badge></span></div>
                </div>
              ) : null}
            </DisclosureCard>
          </section>

          <section className="card-grid">
            <Card>
              <SectionTitle kicker="Reliability" title="Shared broker/effective cohorts" subtitle="One canonical reliability report now feeds recommendation-quality review." actions={<HelpHint tooltip="The reliability report groups broker-preferred outcomes by confidence band, setup family, and action so policy reviews do not re-implement cohort logic locally." to={recommendationQualityDoc} />} />
              {reliabilityReport ? (
                <div className="data-points top-gap-small">
                  <div className="data-point"><span className="data-point-label">resolved outcomes</span><span className="data-point-value">{reliabilityReport.resolved_outcomes}</span></div>
                  <div className="data-point"><span className="data-point-label">broker outcomes</span><span className="data-point-value">{reliabilityReport.broker_outcomes}</span></div>
                  <div className="data-point"><span className="data-point-label">simulation outcomes</span><span className="data-point-value">{reliabilityReport.simulation_outcomes}</span></div>
                  <div className="data-point"><span className="data-point-label">top confidence cohort</span><span className="data-point-value">{confidenceBucket ? <Badge tone={cohortSampleStatusTone(confidenceBucket.sample_status)}>{confidenceBucket.label}</Badge> : "—"}</span></div>
                  <div className="data-point"><span className="data-point-label">top setup family</span><span className="data-point-value">{familyBucket ? <Badge tone={cohortSampleStatusTone(familyBucket.sample_status)}>{familyBucket.label}</Badge> : "—"}</span></div>
                  <div className="data-point"><span className="data-point-label">top action</span><span className="data-point-value">{actionBucket ? <Badge tone={cohortSampleStatusTone(actionBucket.sample_status)}>{actionBucket.label}</Badge> : "—"}</span></div>
                </div>
              ) : (
                <EmptyState message="No reliability report available." />
              )}
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
              <SectionTitle kicker="Next actions" title="What to do next" subtitle="Recommended follow-ups based on the current summary." actions={<Link to="/research" className="button-secondary">⌂ Research</Link>} />
              {data.next_actions.length === 0 ? <EmptyState message="No next actions generated." /> : <ul className="list-reset top-gap-small">{data.next_actions.map((item) => <li key={item} className="list-item compact-item">{item}</li>)}</ul>}
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

            <DisclosureCard kicker="Simulation-only entry quality" title="Almost entered, then moved" subtitle="Diagnostic only: useful for entry-framing research, not broker-preferred outcome evidence." actions={<HelpHint tooltip="These simulation-only numbers highlight plans that never filled, but came very close to entry. They are useful diagnostics, not broker-preferred outcome evidence." to={glossaryDoc("entry-stop-take-profit")} />}>
              <div className="data-points top-gap-small">
                <div className="data-point"><span className="data-point-label">never entered</span><span className="data-point-value">{entryDiagnostics?.never_entered_count ?? "—"}</span></div>
                <div className="data-point"><span className="data-point-label">almost entered</span><span className="data-point-value">{entryDiagnostics?.near_entry_miss_count ?? "—"}</span></div>
                <div className="data-point"><span className="data-point-label">still moved right</span><span className="data-point-value">{entryDiagnostics?.direction_worked_without_entry_count ?? "—"}</span></div>
                <div className="data-point"><span className="data-point-label">almost entered + worked</span><span className="data-point-value">{entryDiagnostics?.near_entry_and_worked_count ?? "—"}</span></div>
                <div className="data-point"><span className="data-point-label">almost-entered rate</span><span className="data-point-value">{entryDiagnostics?.near_entry_miss_rate_percent !== null && entryDiagnostics?.near_entry_miss_rate_percent !== undefined ? `${entryDiagnostics.near_entry_miss_rate_percent.toFixed(1)}%` : "—"}</span></div>
                <div className="data-point"><span className="data-point-label">avg miss distance</span><span className="data-point-value">{entryDiagnostics?.average_entry_miss_distance_percent !== null && entryDiagnostics?.average_entry_miss_distance_percent !== undefined ? `${entryDiagnostics.average_entry_miss_distance_percent.toFixed(2)}%` : "—"}</span></div>
              </div>
            </DisclosureCard>

            <Card>
              <SectionTitle kicker="Walk-forward" title="Promotion gate" actions={<HelpHint tooltip="The promotion gate decides whether a tuning change is allowed to become live. It uses walk-forward validation and sample thresholds so thin evidence does not auto-promote a change." to={glossaryDoc("promotion-gate")} />} />
              <div className="data-points top-gap-small">
                <div className="data-point"><span className="data-point-label">promotion</span><span className="data-point-value">{data.summary.walk_forward_promotion_recommended ? "recommended" : "not yet"}</span></div>
                <div className="data-point"><span className="data-point-label">avg win-rate delta</span><span className="data-point-value">{data.summary.walk_forward_average_win_rate_delta !== null ? data.summary.walk_forward_average_win_rate_delta.toFixed(2) : "—"}</span></div>
                <div className="data-point"><span className="data-point-label">avg EV delta</span><span className="data-point-value">{data.summary.walk_forward_average_expected_value_delta !== null ? data.summary.walk_forward_average_expected_value_delta.toFixed(4) : "—"}</span></div>
                <div className="data-point"><span className="data-point-label">family count</span><span className="data-point-value">{data.summary.family_count}</span></div>
              </div>
            </Card>

            <DisclosureCard kicker="Assessment" title="Latest performance assessment" subtitle="Collapsed by default so the summary page can stay focused on the actual metrics." actions={<HelpHint tooltip="This is the latest narrative assessment snapshot for recent recommendation behavior. Use it as a summary aid, not as a substitute for the underlying metrics." to={recommendationQualityDoc} />}>
              <div className="helper-text">{typeof data.summary.latest_assessment?.content === "string" ? data.summary.latest_assessment.content.slice(0, 400) : "No assessment text available."}</div>
            </DisclosureCard>
          </section>

          <section className="card-grid">
            <Card>
              <SectionTitle kicker="Details" title="Calibration buckets" subtitle="Use the research page for the full reliability curves." actions={<HelpHint tooltip="Calibration buckets are confidence bands used to compare predicted confidence against what actually happened after outcomes resolved." to={glossaryDoc("confidence-bucket")} />} />
              <div className="cluster top-gap-small">
                <Badge tone="info">{selectedSummary.status}</Badge>
                <Link to="/research" className="button-secondary">⌂ Research</Link>
              </div>
            </Card>
          </section>
        </div>
      ) : null}
    </>
  );
}
