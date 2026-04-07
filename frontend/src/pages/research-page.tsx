import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { getJson, postForm } from "../api";
import type { PerformanceAssessmentResponse } from "../types";
import { formatDate, jobTypeLabel, runTone } from "../utils";
import { Badge, Card, HelpHint, PageHeader, SectionTitle } from "../components/ui";

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
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const payload = await getJson<PerformanceAssessmentResponse>("/api/research/performance-assessment");
        if (!cancelled) {
          setAssessment(payload);
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

  async function handleRunAssessment() {
    setRunning(true);
    setError(null);
    try {
      await postForm("/api/research/performance-assessment/run", {});
      const payload = await getJson<PerformanceAssessmentResponse>("/api/research/performance-assessment");
      setAssessment(payload);
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
        title="Calibration, tuning, and review work lives here."
        subtitle="Use this area for evidence-oriented review surfaces that help you learn from past decisions before changing how the planner behaves. The latest automated performance assessment is shown here, while detailed tuning pages remain below."
        actions={<HelpHint tooltip="Research pages are for review, calibration, and tuning workflows rather than day-to-day operational execution." to="/docs?doc=operator-page-field-guide" />}
      />

      <div className="stack-page">
        <Card>
          <SectionTitle
            kicker="Automated review"
            title="Latest performance assessment"
            subtitle="A scheduled performance-assessment job runs daily at midnight, preserves history in runs, and keeps this page focused on the latest assessment only."
            actions={<button type="button" className="button-secondary" onClick={() => void handleRunAssessment()} disabled={running}>{running ? "Queueing…" : "Run now"}</button>}
          />
          {loading ? <div className="helper-text">Loading latest assessment…</div> : null}
          {error ? <div className="helper-text">{error}</div> : null}
          {!loading && !error ? (
            <>
              <div className="data-points top-gap-small">
                <div className="data-point"><span className="data-point-label">job</span><span className="data-point-value">{assessment?.job ? jobTypeLabel(assessment.job.job_type) : "—"}</span></div>
                <div className="data-point"><span className="data-point-label">schedule</span><span className="data-point-value">{assessment?.job?.cron ?? "—"}</span></div>
                <div className="data-point"><span className="data-point-label">history kept</span><span className="data-point-value">{assessment?.history_count ?? 0}</span></div>
                <div className="data-point"><span className="data-point-label">latest run</span><span className="data-point-value">{assessment?.latest_run?.status ? <Badge tone={runTone(assessment.latest_run.status)}>{assessment.latest_run.status}</Badge> : "—"}</span></div>
                <div className="data-point"><span className="data-point-label">generated</span><span className="data-point-value">{formatDate(latestGeneratedAt)}</span></div>
                <div className="data-point"><span className="data-point-label">backend</span><span className="data-point-value">{latestBackend} / {latestMethod}</span></div>
              </div>
              {latestError ? <div className="helper-text top-gap-small">LLM fallback note: {latestError}</div> : null}
              <div className="top-gap-medium">
                {latestContent ? renderAssessment(latestContent) : <div className="helper-text">No assessment has been generated yet.</div>}
              </div>
            </>
          ) : null}
        </Card>

        <section className="card-grid">
          <Card>
            <SectionTitle
              kicker="Available now"
              title="Decision samples"
              subtitle="Review near-misses, actionable cases, and the evidence that may feed future tuning and replay workflows."
            />
            <div className="helper-text">This is the shared evidence surface. It is not exclusive to signal gating, even though gating uses it today.</div>
            <div className="cluster top-gap-small">
              <Link to="/research/decision-samples" className="button-secondary">Open decision samples</Link>
              <Badge tone="info">active</Badge>
            </div>
          </Card>

          <Card>
            <SectionTitle
              kicker="Available now"
              title="Signal gating"
              subtitle="The signal-gating subsection collects the tuning job and supporting review links so the controls stay grouped without owning the samples themselves."
            />
            <div className="helper-text">Use the gating subsection when you want to adjust live gating parameters or inspect tuning history.</div>
            <div className="cluster top-gap-small">
              <Link to="/research/signal-gating" className="button-secondary">Open signal gating</Link>
              <Badge tone="info">active</Badge>
            </div>
          </Card>

          <Card>
            <SectionTitle
              kicker="Available now"
              title="Plan generation tuning"
              subtitle="Run candidate-based precision tuning for live entry, stop-loss, and take-profit construction with ranked backtest results."
            />
            <div className="helper-text">Use this page to inspect active config versions, tuning runs, guarded promotions, and the candidate ranking output.</div>
            <div className="cluster top-gap-small">
              <Link to="/research/plan-generation-tuning" className="button-secondary">Open plan generation tuning</Link>
              <Badge tone="info">active</Badge>
            </div>
          </Card>

          <Card>
            <SectionTitle
              kicker="Planned"
              title="Backtesting"
              subtitle="A future page for historical replay, comparison, and scenario analysis."
            />
            <div className="helper-text">This slot is reserved for replay-style experiments and historical validation workflows.</div>
            <div className="cluster top-gap-small">
              <Badge tone="neutral">coming soon</Badge>
            </div>
          </Card>
        </section>
      </div>
    </>
  );
}
