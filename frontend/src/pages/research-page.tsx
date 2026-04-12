import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { getJson, postForm } from "../api";
import type { CalibrationReportResponse, CalibrationSummary, PerformanceAssessmentResponse, PerformanceWindowAssessment, WalkForwardValidationResponse } from "../types";
import { formatDate, jobTypeLabel, runTone } from "../utils";
import { Badge, Card, HelpHint, PageHeader, SectionTitle, SegmentedTabs, StatCard } from "../components/ui";

const assessmentWindows = ["7d", "30d", "90d", "180d", "1y"] as const;

function windowStartIso(window: (typeof assessmentWindows)[number]): string {
  const now = Date.now();
  const days = window === "7d" ? 7 : window === "30d" ? 30 : window === "90d" ? 90 : window === "180d" ? 180 : 365;
  return new Date(now - days * 24 * 60 * 60 * 1000).toISOString();
}

function renderAssessment(content: string) {
  const lines = content.split(/\r?\n/);
  const nodes: JSX.Element[] = [];
  let listItems: string[] = [];
  let paragraph: string[] = [];

  const flushList = () => {
    if (!listItems.length) {
      return;
    }
    nodes.push(
      <ul key={`list-${nodes.length}`} className="markdown-list">
        {listItems.map((item, index) => <li key={`${index}-${item.slice(0, 12)}`}>{item}</li>)}
      </ul>,
    );
    listItems = [];
  };

  const flushParagraph = () => {
    if (!paragraph.length) {
      return;
    }
    nodes.push(<p key={`p-${nodes.length}`} className="markdown-paragraph">{paragraph.join(" ")}</p>);
    paragraph = [];
  };

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) {
      flushList();
      flushParagraph();
      continue;
    }
    if (line.startsWith("### ")) {
      flushList();
      flushParagraph();
      nodes.push(<h3 key={`h3-${nodes.length}`} className="markdown-heading markdown-heading-3">{line.slice(4)}</h3>);
      continue;
    }
    if (line.startsWith("## ")) {
      flushList();
      flushParagraph();
      nodes.push(<h2 key={`h2-${nodes.length}`} className="markdown-heading markdown-heading-2">{line.slice(3)}</h2>);
      continue;
    }
    if (line.startsWith("# ")) {
      flushList();
      flushParagraph();
      nodes.push(<h1 key={`h1-${nodes.length}`} className="markdown-heading markdown-heading-1">{line.slice(2)}</h1>);
      continue;
    }
    if (line.startsWith("- ") || line.startsWith("* ")) {
      flushParagraph();
      listItems.push(line.slice(2));
      continue;
    }
    flushList();
    paragraph.push(line);
  }

  flushList();
  flushParagraph();
  return <div className="markdown-content">{nodes}</div>;
}

export function ResearchPage() {
  const [assessment, setAssessment] = useState<PerformanceAssessmentResponse | null>(null);
  const [calibration, setCalibration] = useState<CalibrationReportResponse | null>(null);
  const [walkForward, setWalkForward] = useState<WalkForwardValidationResponse | null>(null);
  const [activeTab, setActiveTab] = useState<"overview" | "calibration" | "validation" | "tuning">("overview");
  const [selectedWindow, setSelectedWindow] = useState<(typeof assessmentWindows)[number]>("30d");
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [assessmentPayload, calibrationPayload, walkForwardPayload] = await Promise.all([
          getJson<PerformanceAssessmentResponse>("/api/research/performance-assessment"),
          getJson<CalibrationReportResponse>(`/api/recommendation-outcomes/calibration-report?evaluated_after=${encodeURIComponent(windowStartIso(selectedWindow))}&limit=2000`),
          getJson<WalkForwardValidationResponse>("/api/recommendation-outcomes/walk-forward?lookback_days=365&validation_days=90&step_days=30&min_resolved_outcomes=20"),
        ]);
        if (!cancelled) {
          setAssessment(assessmentPayload);
          setCalibration(calibrationPayload);
          setWalkForward(walkForwardPayload);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [selectedWindow]);

  const latestContent = typeof assessment?.latest_assessment?.content === "string" ? assessment.latest_assessment.content : "";
  const latestBackend = typeof assessment?.latest_assessment?.backend === "string" ? assessment.latest_assessment.backend : "—";
  const latestMethod = typeof assessment?.latest_assessment?.method === "string" ? assessment.latest_assessment.method : "—";
  const latestGeneratedAt = typeof assessment?.latest_assessment?.generated_at === "string" ? assessment.latest_assessment.generated_at : assessment?.latest_run?.completed_at ?? null;
  const latestError = typeof assessment?.latest_assessment?.llm_error === "string" ? assessment.latest_assessment.llm_error : null;
  const calibrationSummary: CalibrationSummary | null = calibration?.calibration_summary ?? assessment?.calibration_summary ?? null;
  const calibrationReport = calibration?.calibration_report ?? calibrationSummary?.calibration_report ?? null;
  const calibrationBins = calibrationReport?.bins ?? [];
  const windowedAssessments = Array.isArray(assessment?.windowed_assessments) ? (assessment.windowed_assessments as PerformanceWindowAssessment[]) : [];
  const selectedAssessmentWindow = windowedAssessments.find((window) => window.window === selectedWindow) ?? windowedAssessments[0] ?? null;

  async function handleRunAssessment() {
    setRunning(true);
    setError(null);
    try {
      await postForm("/api/research/performance-assessment/run", {});
      const [assessmentPayload, calibrationPayload, walkForwardPayload] = await Promise.all([
        getJson<PerformanceAssessmentResponse>("/api/research/performance-assessment"),
        getJson<CalibrationReportResponse>(`/api/recommendation-outcomes/calibration-report?evaluated_after=${encodeURIComponent(windowStartIso(selectedWindow))}&limit=2000`),
        getJson<WalkForwardValidationResponse>("/api/recommendation-outcomes/walk-forward?lookback_days=365&validation_days=90&step_days=30&min_resolved_outcomes=20"),
      ]);
      setAssessment(assessmentPayload);
      setCalibration(calibrationPayload);
      setWalkForward(walkForwardPayload);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunning(false);
    }
  }

  return (
    <>
      <PageHeader
        kicker="Research"
        title="Keep advanced review and tuning separate from daily operations."
        subtitle="Use this area for secondary review, tuning, and performance assessment after the main workflow is already running."
        actions={<HelpHint tooltip="Research pages are secondary tools for advanced review, tuning, and performance assessment." to="/docs?doc=operator-page-field-guide" />}
      />

      <div className="stack-page">
        <Card>
          <SectionTitle kicker="Research view" title="Choose a secondary workflow" />
          <div className="top-gap-small">
            <SegmentedTabs
              value={activeTab}
              options={[
                { value: "overview", label: "Overview" },
                { value: "calibration", label: "Calibration" },
                { value: "validation", label: "Validation" },
                { value: "tuning", label: "Tuning" },
              ]}
              onChange={setActiveTab}
            />
          </div>
        </Card>

        <Card>
          <SectionTitle
            kicker="Performance assessment"
            title="Latest automated review"
            subtitle="The performance-assessment job stays available here as a secondary review surface."
            actions={<button type="button" className="button-secondary" onClick={() => void handleRunAssessment()} disabled={running}>{running ? "Queueing…" : "Run now"}</button>}
          />
          {loading ? <div className="helper-text">Loading latest assessment…</div> : null}
          {error ? <div className="helper-text">{error}</div> : null}
          {!loading && !error ? (
            <>
              <div className="data-points top-gap-small">
                <div className="data-point"><span className="data-point-label">workflow</span><span className="data-point-value">{assessment?.job ? jobTypeLabel(assessment.job.job_type) : "—"}</span></div>
                <div className="data-point"><span className="data-point-label">schedule</span><span className="data-point-value">{assessment?.job?.cron ?? "—"}</span></div>
                <div className="data-point"><span className="data-point-label">history kept</span><span className="data-point-value">{assessment?.history_count ?? 0}</span></div>
                <div className="data-point"><span className="data-point-label">latest run</span><span className="data-point-value">{assessment?.latest_run?.status ? <Badge tone={runTone(assessment.latest_run.status)}>{assessment.latest_run.status}</Badge> : "—"}</span></div>
                <div className="data-point"><span className="data-point-label">generated</span><span className="data-point-value">{formatDate(latestGeneratedAt)}</span></div>
                <div className="data-point"><span className="data-point-label">backend</span><span className="data-point-value">{latestBackend} / {latestMethod}</span></div>
              </div>
              {latestError ? <div className="helper-text top-gap-small">Fallback note: {latestError}</div> : null}
              {windowedAssessments.length > 0 ? (
                <Card className="top-gap-medium">
                  <SectionTitle kicker="Rolling windows" title="Assessment snapshots" subtitle="Select a time window to inspect the matching performance-assessment summary." actions={<HelpHint tooltip="These windows summarize recent assessment posture without forcing you to scan every period at once." to="/docs?doc=glossary&section=walk-forward-validation" />} />
                  <div className="top-gap-small">
                    <SegmentedTabs
                      value={selectedWindow}
                      options={assessmentWindows.filter((window) => windowedAssessments.some((item) => item.window === window)).map((window) => ({ value: window, label: window.toUpperCase() }))}
                      onChange={(value) => setSelectedWindow(value as (typeof assessmentWindows)[number])}
                    />
                  </div>
                  {selectedAssessmentWindow ? (
                    <section className="card-grid top-gap-small">
                      <Card>
                        <SectionTitle kicker={`Window ${selectedAssessmentWindow.window}`} title={`${selectedAssessmentWindow.resolved_outcomes} resolved outcomes`} subtitle={`Evaluated after ${formatDate(selectedAssessmentWindow.evaluated_after)}`} />
                        <div className="data-points top-gap-small">
                          <div className="data-point"><span className="data-point-label">overall win rate</span><span className="data-point-value">{selectedAssessmentWindow.overall_win_rate_percent !== null ? `${selectedAssessmentWindow.overall_win_rate_percent.toFixed(1)}%` : "—"}</span></div>
                          <div className="data-point"><span className="data-point-label">actionable win rate</span><span className="data-point-value">{selectedAssessmentWindow.actual_actionable_win_rate_percent !== null ? `${selectedAssessmentWindow.actual_actionable_win_rate_percent.toFixed(1)}%` : "—"}</span></div>
                          <div className="data-point"><span className="data-point-label">high-confidence win rate</span><span className="data-point-value">{selectedAssessmentWindow.high_confidence_win_rate_percent !== null ? `${selectedAssessmentWindow.high_confidence_win_rate_percent.toFixed(1)}%` : "—"}</span></div>
                          <div className="data-point"><span className="data-point-label">actionable return 5d</span><span className="data-point-value">{selectedAssessmentWindow.actual_actionable_average_return_5d !== null ? selectedAssessmentWindow.actual_actionable_average_return_5d.toFixed(3) : "—"}</span></div>
                          <div className="data-point"><span className="data-point-label">confidence return 5d</span><span className="data-point-value">{selectedAssessmentWindow.high_confidence_average_return_5d !== null ? selectedAssessmentWindow.high_confidence_average_return_5d.toFixed(3) : "—"}</span></div>
                          <div className="data-point"><span className="data-point-label">brier / ece</span><span className="data-point-value">{selectedAssessmentWindow.calibration_brier_score !== null ? selectedAssessmentWindow.calibration_brier_score.toFixed(4) : "—"} / {selectedAssessmentWindow.calibration_ece !== null ? selectedAssessmentWindow.calibration_ece.toFixed(4) : "—"}</span></div>
                          <div className="data-point"><span className="data-point-label">family count</span><span className="data-point-value">{selectedAssessmentWindow.family_count}</span></div>
                          <div className="data-point"><span className="data-point-label">expansion</span><span className="data-point-value">{selectedAssessmentWindow.ready_for_expansion ? "yes" : "no"}</span></div>
                        </div>
                      </Card>
                    </section>
                  ) : null}
                </Card>
              ) : null}
              <div className="top-gap-medium">
                {latestContent ? renderAssessment(latestContent) : <div className="helper-text">No assessment has been generated yet.</div>}
              </div>
            </>
          ) : null}
        </Card>

        {activeTab === "overview" ? (
          <section className="card-grid">
            <Card>
              <SectionTitle kicker="Advanced review" title="Decision samples" subtitle="Review near-misses and borderline cases when you need deeper evidence review." />
              <div className="cluster top-gap-small">
                <Link to="/research/decision-samples" className="button-secondary">Open decision samples</Link>
                <Badge tone="info">advanced review</Badge>
              </div>
            </Card>
            <Card>
              <SectionTitle kicker="Advanced review" title="Recommendation quality summary" subtitle="Use this for a consolidated view of calibration, baselines, evidence concentration, and walk-forward readiness." />
              <div className="cluster top-gap-small">
                <Link to="/recommendation-quality" className="button-secondary">Open quality summary</Link>
                <Badge tone="info">advanced review</Badge>
              </div>
            </Card>
            <Card>
              <SectionTitle kicker="Tuning" title="Signal gating tuning" subtitle="Use this when shortlist recall is too strict or too loose." />
              <div className="cluster top-gap-small">
                <Link to="/research/signal-gating/gating-job" className="button-secondary">Open signal gating tuning</Link>
                <Badge tone="info">research</Badge>
              </div>
            </Card>
            <Card>
              <SectionTitle kicker="Tuning" title="Plan generation tuning" subtitle="Use this when actionable plan precision or trade framing needs work." />
              <div className="cluster top-gap-small">
                <Link to="/research/plan-generation-tuning" className="button-secondary">Open plan generation tuning</Link>
                <Badge tone="info">research</Badge>
              </div>
            </Card>
          </section>
        ) : null}

        {activeTab === "validation" ? (
          <>
            {walkForward ? (
              <>
                <section className="card-grid">
                  <StatCard label="Slices" value={walkForward.total_slices} helper="Rolling validation windows" tooltip="The total number of walk-forward slices. A slice is one bounded validation window used to test whether results hold across time instead of one pooled sample." tooltipTo="/docs?doc=glossary&section=slice" />
                  <StatCard label="Lookback" value={`${walkForward.lookback_days}d`} helper="Historical span considered" tooltip="How much prior history each validation cycle can look back on before evaluating the later validation window." tooltipTo="/docs?doc=glossary&section=walk-forward-validation" />
                  <StatCard label="Validation" value={`${walkForward.validation_days}d`} helper="Each window length" tooltip="The length of each held-out validation window used to measure later performance." tooltipTo="/docs?doc=glossary&section=walk-forward-validation" />
                  <StatCard label="Step" value={`${walkForward.step_days}d`} helper="Window stride" tooltip="How far the rolling validation window moves forward between slices." tooltipTo="/docs?doc=glossary&section=walk-forward-validation" />
                </section>
                <section className="card-grid">
                  {walkForward.slices.map((slice) => (
                    <Card key={`${slice.slice_index}-${slice.window_label}`}>
                      <SectionTitle kicker={`Slice ${slice.slice_index}`} title={slice.window_label} subtitle={`${slice.resolved_outcomes} resolved outcomes`} />
                      <div className="data-points top-gap-small">
                        <div className="data-point"><span className="data-point-label">overall win rate</span><span className="data-point-value">{slice.overall_win_rate_percent !== null ? `${slice.overall_win_rate_percent.toFixed(1)}%` : "—"}</span></div>
                        <div className="data-point"><span className="data-point-label">actual actionable</span><span className="data-point-value">{slice.actual_actionable_win_rate_percent !== null ? `${slice.actual_actionable_win_rate_percent.toFixed(1)}%` : "—"}</span></div>
                        <div className="data-point"><span className="data-point-label">high confidence</span><span className="data-point-value">{slice.high_confidence_win_rate_percent !== null ? `${slice.high_confidence_win_rate_percent.toFixed(1)}%` : "—"}</span></div>
                        <div className="data-point"><span className="data-point-label">actionable return 5d</span><span className="data-point-value">{slice.actual_actionable_average_return_5d !== null ? slice.actual_actionable_average_return_5d.toFixed(3) : "—"}</span></div>
                        <div className="data-point"><span className="data-point-label">confidence return 5d</span><span className="data-point-value">{slice.high_confidence_average_return_5d !== null ? slice.high_confidence_average_return_5d.toFixed(3) : "—"}</span></div>
                        <div className="data-point"><span className="data-point-label">ready</span><span className="data-point-value">{slice.ready_for_expansion ? "yes" : "no"}</span></div>
                        <div className="data-point"><span className="data-point-label">brier / ece</span><span className="data-point-value">{slice.calibration_report?.brier_score !== null && slice.calibration_report?.brier_score !== undefined ? slice.calibration_report.brier_score.toFixed(4) : "—"} / {slice.calibration_report?.expected_calibration_error !== null && slice.calibration_report?.expected_calibration_error !== undefined ? slice.calibration_report.expected_calibration_error.toFixed(4) : "—"}</span></div>
                      </div>
                    </Card>
                  ))}
                </section>
              </>
            ) : null}
          </>
        ) : null}

        {activeTab === "tuning" ? (
          <section className="card-grid">
            <Card>
              <SectionTitle kicker="Upstream" title="Signal gating tuning" subtitle="Recall-oriented shortlist tuning." />
              <div className="cluster top-gap-small">
                <Link to="/research/signal-gating/gating-job" className="button-secondary">Open signal gating tuning</Link>
              </div>
            </Card>
            <Card>
              <SectionTitle kicker="Downstream" title="Plan generation tuning" subtitle="Precision-oriented plan-construction tuning." />
              <div className="cluster top-gap-small">
                <Link to="/research/plan-generation-tuning" className="button-secondary">Open plan generation tuning</Link>
              </div>
            </Card>
          </section>
        ) : null}

        {activeTab === "calibration" ? (
          <>
            <Card>
              <SectionTitle kicker="Time window" title="Calibration review window" subtitle="Choose which rolling window the calibration tab should use." actions={<HelpHint tooltip="This selector changes the calibration cohort so you can compare recent versus broader confidence behavior." to="/docs?doc=glossary&section=confidence-bucket" />} />
              <div className="top-gap-small">
                <SegmentedTabs
                  value={selectedWindow}
                  options={assessmentWindows.map((window) => ({ value: window, label: window.toUpperCase() }))}
                  onChange={(value) => setSelectedWindow(value as (typeof assessmentWindows)[number])}
                />
              </div>
            </Card>

            {calibrationSummary ? (
              <section className="card-grid top-gap">
                <StatCard label="Calibration method" value={calibrationReport?.method ?? "—"} helper={`${selectedWindow.toUpperCase()} cohort`} tooltip="The current calibration report method used for this reviewed cohort or filtered comparison group." tooltipTo="/docs?doc=glossary&section=calibration" />
                <StatCard label="Brier score" value={calibrationReport?.brier_score !== null && calibrationReport?.brier_score !== undefined ? calibrationReport.brier_score.toFixed(4) : "—"} helper="Lower is better" tooltip="A proper scoring measure of confidence quality. Lower generally means predicted confidence matched realized outcomes more closely." tooltipTo="/docs?doc=glossary&section=calibration" />
                <StatCard label="ECE" value={calibrationReport?.expected_calibration_error !== null && calibrationReport?.expected_calibration_error !== undefined ? calibrationReport.expected_calibration_error.toFixed(4) : "—"} helper="Average confidence gap" tooltip="Expected calibration error: the average gap between displayed confidence and realized win rate across confidence buckets." tooltipTo="/docs?doc=glossary&section=confidence-bucket" />
                <StatCard label="Resolved outcomes" value={calibrationReport?.resolved_count ?? calibrationSummary.resolved_outcomes} helper="Win/loss cases used for reliability" tooltip="The number of resolved win/loss outcomes contributing to the current calibration view. Thin samples should be read cautiously." tooltipTo="/docs?doc=glossary&section=outcome-evaluation" />
              </section>
            ) : null}

            {calibrationBins.length > 0 ? (
              <Card>
                <SectionTitle kicker="Reliability curve" title="Confidence calibration bins" subtitle="Predicted probability versus realized win rate by confidence band." />
                <div className="table-wrapper top-gap-small">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>bin</th>
                        <th>samples</th>
                        <th>predicted</th>
                        <th>realized win rate</th>
                        <th>brier</th>
                        <th>calibration error</th>
                      </tr>
                    </thead>
                    <tbody>
                      {calibrationBins.map((bin) => (
                        <tr key={bin.bin_key}>
                          <td>{bin.bin_label}</td>
                          <td>{bin.sample_count}</td>
                          <td>{bin.predicted_probability !== null ? `${(bin.predicted_probability * 100).toFixed(1)}%` : "—"}</td>
                          <td>{bin.realized_win_rate_percent !== null ? `${bin.realized_win_rate_percent.toFixed(1)}%` : "—"}</td>
                          <td>{bin.brier_score !== null ? bin.brier_score.toFixed(4) : "—"}</td>
                          <td>{bin.calibration_error !== null ? bin.calibration_error.toFixed(4) : "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
            ) : null}
            {calibrationSummary?.smoothed_calibration_report?.bins?.length ? (
              <Card className="top-gap">
                <SectionTitle kicker="Smoothed curve" title="Smoothed calibration bins" subtitle="Alternative reliability curve with a light Bayesian pull toward the overall rate." />
                <div className="table-wrapper top-gap-small">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>bin</th>
                        <th>samples</th>
                        <th>predicted</th>
                        <th>realized win rate</th>
                        <th>brier</th>
                        <th>calibration error</th>
                      </tr>
                    </thead>
                    <tbody>
                      {calibrationSummary.smoothed_calibration_report.bins.map((bin) => (
                        <tr key={`smoothed-${bin.bin_key}`}>
                          <td>{bin.bin_label}</td>
                          <td>{bin.sample_count}</td>
                          <td>{bin.predicted_probability !== null ? `${(bin.predicted_probability * 100).toFixed(1)}%` : "—"}</td>
                          <td>{bin.realized_win_rate_percent !== null ? `${bin.realized_win_rate_percent.toFixed(1)}%` : "—"}</td>
                          <td>{bin.brier_score !== null ? bin.brier_score.toFixed(4) : "—"}</td>
                          <td>{bin.calibration_error !== null ? bin.calibration_error.toFixed(4) : "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
            ) : null}
          </>
        ) : null}
      </div>
    </>
  );
}
