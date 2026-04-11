import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { getJson, postForm } from "../api";
import type { CalibrationReportResponse, CalibrationSummary, PerformanceAssessmentResponse } from "../types";
import { formatDate, jobTypeLabel, runTone } from "../utils";
import { Badge, Card, HelpHint, PageHeader, SectionTitle, SegmentedTabs, StatCard } from "../components/ui";

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
  const [activeTab, setActiveTab] = useState<"overview" | "calibration" | "tuning">("overview");
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [assessmentPayload, calibrationPayload] = await Promise.all([
          getJson<PerformanceAssessmentResponse>("/api/research/performance-assessment"),
          getJson<CalibrationReportResponse>("/api/recommendation-outcomes/calibration-report?limit=500"),
        ]);
        if (!cancelled) {
          setAssessment(assessmentPayload);
          setCalibration(calibrationPayload);
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
  }, []);

  const latestContent = typeof assessment?.latest_assessment?.content === "string" ? assessment.latest_assessment.content : "";
  const latestBackend = typeof assessment?.latest_assessment?.backend === "string" ? assessment.latest_assessment.backend : "—";
  const latestMethod = typeof assessment?.latest_assessment?.method === "string" ? assessment.latest_assessment.method : "—";
  const latestGeneratedAt = typeof assessment?.latest_assessment?.generated_at === "string" ? assessment.latest_assessment.generated_at : assessment?.latest_run?.completed_at ?? null;
  const latestError = typeof assessment?.latest_assessment?.llm_error === "string" ? assessment.latest_assessment.llm_error : null;
  const calibrationSummary: CalibrationSummary | null = calibration?.calibration_summary ?? assessment?.calibration_summary ?? null;
  const calibrationReport = calibration?.calibration_report ?? calibrationSummary?.calibration_report ?? null;
  const calibrationBins = calibrationReport?.bins ?? [];

  async function handleRunAssessment() {
    setRunning(true);
    setError(null);
    try {
      await postForm("/api/research/performance-assessment/run", {});
      const [assessmentPayload, calibrationPayload] = await Promise.all([
        getJson<PerformanceAssessmentResponse>("/api/research/performance-assessment"),
        getJson<CalibrationReportResponse>("/api/recommendation-outcomes/calibration-report?limit=500"),
      ]);
      setAssessment(assessmentPayload);
      setCalibration(calibrationPayload);
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
            {calibrationSummary ? (
              <section className="card-grid">
                <StatCard label="Calibration method" value={calibrationReport?.method ?? "—"} helper="Latest assessed cohort" />
                <StatCard label="Brier score" value={calibrationReport?.brier_score !== null && calibrationReport?.brier_score !== undefined ? calibrationReport.brier_score.toFixed(4) : "—"} helper="Lower is better" />
                <StatCard label="ECE" value={calibrationReport?.expected_calibration_error !== null && calibrationReport?.expected_calibration_error !== undefined ? calibrationReport.expected_calibration_error.toFixed(4) : "—"} helper="Average confidence gap" />
                <StatCard label="Resolved outcomes" value={calibrationReport?.resolved_count ?? calibrationSummary.resolved_outcomes} helper="Win/loss cases used for reliability" />
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
          </>
        ) : null}
      </div>
    </>
  );
}
