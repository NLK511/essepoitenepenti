import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { getJson, postForm } from "../api";
import type { CalibrationSummary, PerformanceAssessmentResponse, PerformanceWindowAssessment } from "../types";
import { cohortSampleStatusTone, formatDate, jobTypeLabel, normalizeReviewWindow, reviewWindowLabel, reviewWindowStartIso, REVIEW_WINDOW_OPTIONS, runTone } from "../utils";
import { Badge, Card, DisclosureCard, ErrorState, HelpHint, PageHeader, SectionTitle, SegmentedTabs, StatCard } from "../components/ui";

const assessmentWindows = REVIEW_WINDOW_OPTIONS;

function policyHealthTone(label: string | null | undefined): "ok" | "warning" | "danger" | "neutral" | "info" {
  const normalized = (label ?? "").trim().toLowerCase();
  if (normalized === "healthy" || normalized === "eligible_for_cautious_expansion") {
    return "ok";
  }
  if (normalized === "watch" || normalized === "research_only") {
    return "warning";
  }
  if (normalized === "degraded" || normalized === "demote_or_halt" || normalized === "blocked") {
    return "danger";
  }
  if (normalized === "insufficient") {
    return "neutral";
  }
  return "info";
}

function policyHealthStance(label: string | null | undefined): string {
  const normalized = (label ?? "").trim().toLowerCase();
  if (normalized === "healthy") {
    return "Policy can be reviewed for cautious expansion if broker and risk gates also pass.";
  }
  if (normalized === "watch") {
    return "Keep operator review active; do not expand autonomy without stronger broker-backed evidence.";
  }
  if (normalized === "degraded") {
    return "Do not expand autonomy; investigate weak outcome, P&L, calibration, or broker-evidence reasons.";
  }
  if (normalized === "insufficient") {
    return "Collect more resolved evidence before treating the policy as trusted.";
  }
  return "Policy health is unavailable; keep autonomy conservative.";
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

  const [activeTab, setActiveTab] = useState<"overview" | "calibration" | "validation" | "tuning">("overview");
  const [selectedWindow, setSelectedWindow] = useState<(typeof REVIEW_WINDOW_OPTIONS)[number]["value"]>("1d");
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const windowStart = reviewWindowStartIso(selectedWindow);
        const assessmentPayload = await getJson<PerformanceAssessmentResponse>(windowStart ? `/api/research/performance-workbench?calibration_evaluated_after=${encodeURIComponent(windowStart)}` : "/api/research/performance-workbench");
        if (!cancelled) {
          setAssessment(assessmentPayload);
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
  const calibrationSummary: CalibrationSummary | null = assessment?.calibration_summary ?? null;
  const calibrationReport = assessment?.calibration_report ?? calibrationSummary?.calibration_report ?? null;
  const calibrationBins = calibrationReport?.bins ?? [];
  const walkForward = assessment?.walk_forward_validation ?? null;
  const policyHealth = assessment?.policy_health ?? null;
  const edgeGate = assessment?.edge_validation_gate ?? null;
  const reliabilityReport = assessment?.reliability_report ?? null;
  const topReliabilityBuckets = reliabilityReport?.by_confidence_bucket?.slice(0, 4) ?? [];
  const nearMissWinners = assessment?.near_miss_winners ?? [];
  const windowedAssessments = Array.isArray(assessment?.windowed_assessments) ? (assessment.windowed_assessments as PerformanceWindowAssessment[]) : [];
  const selectedAssessmentWindow = windowedAssessments.find((window) => normalizeReviewWindow(window.window, "1d") === selectedWindow) ?? windowedAssessments[0] ?? null;
  const nearMissFamilies = Object.entries(
    (assessment?.near_miss_winners ?? []).reduce<Record<string, { count: number; workedCount: number; missDistances: number[] }>>((acc, item) => {
      const key = (item.setup_family || "uncategorized").trim() || "uncategorized";
      const current = acc[key] ?? { count: 0, workedCount: 0, missDistances: [] };
      current.count += 1;
      if (item.direction_worked_without_entry) {
        current.workedCount += 1;
      }
      if (typeof item.entry_miss_distance_percent === "number") {
        current.missDistances.push(item.entry_miss_distance_percent);
      }
      acc[key] = current;
      return acc;
    }, {}),
  )
    .map(([family, stats]) => {
      const sortedDistances = [...stats.missDistances].sort((left, right) => left - right);
      const averageMissDistance = sortedDistances.length > 0
        ? sortedDistances.reduce((sum, value) => sum + value, 0) / sortedDistances.length
        : null;
      const medianMissDistance = sortedDistances.length > 0
        ? (sortedDistances.length % 2 === 1
          ? sortedDistances[(sortedDistances.length - 1) / 2]
          : (sortedDistances[sortedDistances.length / 2 - 1] + sortedDistances[sortedDistances.length / 2]) / 2)
        : null;
      return {
        family,
        count: stats.count,
        workedCount: stats.workedCount,
        averageMissDistance,
        medianMissDistance,
        minMissDistance: sortedDistances.length > 0 ? sortedDistances[0] : null,
        maxMissDistance: sortedDistances.length > 0 ? sortedDistances[sortedDistances.length - 1] : null,
      };
    })
    .sort((left, right) => right.count - left.count || left.family.localeCompare(right.family));
  const nearMissTickers = Object.entries(
    (assessment?.near_miss_winners ?? []).reduce<Record<string, { count: number; missDistances: number[] }>>((acc, item) => {
      const key = (item.ticker || "unknown").trim() || "unknown";
      const current = acc[key] ?? { count: 0, missDistances: [] };
      current.count += 1;
      if (typeof item.entry_miss_distance_percent === "number") {
        current.missDistances.push(item.entry_miss_distance_percent);
      }
      acc[key] = current;
      return acc;
    }, {}),
  )
    .map(([ticker, stats]) => ({
      ticker,
      count: stats.count,
      averageMissDistance: stats.missDistances.length > 0
        ? stats.missDistances.reduce((sum, value) => sum + value, 0) / stats.missDistances.length
        : null,
    }))
    .sort((left, right) => right.count - left.count || left.ticker.localeCompare(right.ticker));

  async function handleRunAssessment() {
    setRunning(true);
    setError(null);
    try {
      await postForm("/api/research/performance-assessment/run", {});
      const windowStart = reviewWindowStartIso(selectedWindow);
      const assessmentPayload = await getJson<PerformanceAssessmentResponse>(windowStart ? `/api/research/performance-workbench?calibration_evaluated_after=${encodeURIComponent(windowStart)}` : "/api/research/performance-workbench");
      setAssessment(assessmentPayload);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunning(false);
    }
  }

  return (
    <>
      <PageHeader
        kicker="Research Lab"
        title="Advanced tools"
        subtitle="Use this page as a launcher. The canonical performance verdict lives on Quality & Edge."
        actions={<HelpHint tooltip="Research Lab keeps advanced review and tuning tools reachable without duplicating the daily performance surfaces." to="/docs?doc=operator-page-field-guide" />}
      />

      <div className="stack-page">
        {error ? <ErrorState message={error} /> : null}

        <Card>
          <SectionTitle
            kicker="Evidence status"
            title="Start from Quality & Edge before tuning"
            subtitle="This page should not be used as a second performance authority. Use it only to open a justified research workflow."
            actions={<Link to="/recommendation-quality" className="button-secondary">◈ Quality & Edge</Link>}
          />
          {loading ? <div className="helper-text top-gap-small">Loading current research status…</div> : null}
          {!loading ? (
            <section className="metrics-grid top-gap-small">
              <StatCard label="Edge gate" value={edgeGate?.label ?? "unknown"} helper={edgeGate?.reasons?.slice(0, 2).join(" · ") || "Open Quality & Edge for the authoritative gate detail"} />
              <StatCard label="Policy health" value={policyHealth?.label ?? "unknown"} helper={policyHealth ? `${policyHealth.resolved_selected_outcomes} selected resolved` : "Policy health unavailable"} />
              <StatCard label="Latest assessment" value={assessment?.latest_run?.status ?? "—"} helper={latestGeneratedAt ? `Generated ${formatDate(latestGeneratedAt)}` : "No latest assessment timestamp"} />
              <StatCard label="Almost-entered cases" value={nearMissWinners.length} helper="Simulation-only entry-framing research candidates" />
            </section>
          ) : null}
          <div className="cluster top-gap-small">
            <button type="button" className="button-secondary" onClick={() => void handleRunAssessment()} disabled={running}>{running ? "… Queueing assessment" : "▶ Run assessment"}</button>
            <Link to="/jobs/recommendation-plans?entry_touched=false&near_entry_miss=true&direction_worked_without_entry=true&page=1&limit=100" className="button-subtle">↗ Almost-entered plans</Link>
          </div>
        </Card>

        <section className="card-grid">
          <Card>
            <SectionTitle kicker="Performance authority" title="Quality & Edge" subtitle="Edge validation, effective outcomes, calibration, baselines, evidence concentration, and next actions." />
            <div className="cluster top-gap-small">
              <Link to="/recommendation-quality" className="button-secondary">◈ Open Quality & Edge</Link>
              <Badge tone="info">canonical</Badge>
            </div>
          </Card>

          <Card>
            <SectionTitle kicker="Upstream tuning" title="Signal gating tuning" subtitle="Use when Quality & Edge indicates shortlist recall is too strict or too loose." />
            <div className="cluster top-gap-small">
              <Link to="/research/signal-gating/gating-job" className="button-secondary">↯ Open gating tuning</Link>
              <Badge tone="info">research</Badge>
            </div>
          </Card>

          <Card>
            <SectionTitle kicker="Downstream tuning" title="Plan generation tuning" subtitle="Use when Quality & Edge indicates plan construction, entry framing, or reward/risk parameters need work." />
            <div className="cluster top-gap-small">
              <Link to="/research/plan-generation-tuning" className="button-secondary">⚒ Open plan tuning</Link>
              <Badge tone="info">research</Badge>
            </div>
          </Card>

          <Card>
            <SectionTitle kicker="Advanced review" title="Decision samples" subtitle="Inspect near-misses and discarded signals when tuning evidence requires sample-level review." />
            <div className="cluster top-gap-small">
              <Link to="/research/decision-samples" className="button-secondary">◉ Open samples</Link>
              <Badge tone="info">advanced</Badge>
            </div>
          </Card>
        </section>

        <DisclosureCard kicker="Assessment narrative" title="Latest performance assessment" subtitle="Kept for reference only; Quality & Edge owns the metric verdict.">
          {latestContent ? renderAssessment(latestContent) : <div className="helper-text">No assessment has been generated yet.</div>}
          {latestError ? <div className="helper-text top-gap-small">Fallback note: {latestError}</div> : null}
          <div className="helper-text top-gap-small">Backend {latestBackend} / {latestMethod}</div>
        </DisclosureCard>

        <DisclosureCard kicker="Entry-framing research" title="Almost entered, then still worked" subtitle="Simulation-only diagnostic links for investigating entry thresholds without treating them as broker-backed evidence.">
          <div className="data-points top-gap-small">
            <div className="data-point"><span className="data-point-label">matching plans</span><span className="data-point-value">{nearMissWinners.length}</span></div>
            <div className="data-point"><span className="data-point-label">top setup family</span><span className="data-point-value">{nearMissFamilies[0]?.family ?? "—"}</span></div>
          </div>
          <div className="cluster top-gap-small">
            <Link to="/jobs/recommendation-plans?entry_touched=false&near_entry_miss=true&direction_worked_without_entry=true&page=1&limit=100" className="button-secondary">↗ Filtered plans</Link>
          </div>
        </DisclosureCard>
      </div>
    </>
  );
}
