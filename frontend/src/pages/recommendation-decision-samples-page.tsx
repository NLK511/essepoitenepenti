import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { getJson } from "../api";
import { Badge, Card, EmptyState, ErrorState, LoadingState, PageHeader, SectionTitle, StatCard } from "../components/ui";
import type { RecommendationDecisionSample } from "../types";
import { formatDate } from "../utils";

function decisionTone(decisionType: string): "ok" | "warning" | "danger" | "neutral" | "info" {
  if (decisionType === "actionable") {
    return "ok";
  }
  if (decisionType === "near_miss") {
    return "warning";
  }
  if (decisionType === "degraded") {
    return "danger";
  }
  return "neutral";
}

function priorityTone(priority: string): "ok" | "warning" | "danger" | "neutral" | "info" {
  if (priority === "high") {
    return "danger";
  }
  if (priority === "medium") {
    return "warning";
  }
  return "neutral";
}

function gapLabel(value: number | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "—";
  }
  return `${value > 0 ? "+" : ""}${value.toFixed(1)} pts`;
}

function truncate(value: string, max = 180): string {
  if (value.length <= max) {
    return value;
  }
  return `${value.slice(0, max - 1).trimEnd()}…`;
}

export function RecommendationDecisionSamplesPage() {
  const [samples, setSamples] = useState<RecommendationDecisionSample[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        setError(null);
        setSamples(await getJson<RecommendationDecisionSample[]>('/api/recommendation-decision-samples?limit=100'));
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : "Failed to load decision samples");
      }
    }
    void load();
  }, []);

  const summary = useMemo(() => {
    const items = samples ?? [];
    return {
      total: items.length,
      actionable: items.filter((item) => item.decision_type === "actionable").length,
      nearMiss: items.filter((item) => item.decision_type === "near_miss").length,
      degraded: items.filter((item) => item.decision_type === "degraded").length,
      highPriority: items.filter((item) => item.review_priority === "high").length,
    };
  }, [samples]);

  const highPrioritySamples = useMemo(() => {
    return (samples ?? [])
      .filter((item) => item.review_priority === "high" || item.decision_type === "near_miss")
      .slice(0, 12);
  }, [samples]);

  return (
    <>
      <PageHeader
        kicker="Recommendation workflow"
        title="Decision samples"
        subtitle="This page is for tuning and review. It keeps near-misses, rejected setups, and actionable plans in one compact queue so small action counts do not leave you blind to what the planner is doing."
        actions={<Link to="/jobs/recommendation-plans" className="button-secondary">Back to plans</Link>}
      />

      {error ? <ErrorState message={error} /> : null}
      {!samples && !error ? <LoadingState message="Loading decision samples…" /> : null}

      {samples ? (
        <div className="stack-page">
          <section className="metrics-grid">
            <StatCard label="Samples" value={summary.total} helper="Generated recommendation-plan decision rows" />
            <StatCard label="Actionable" value={summary.actionable} helper="Long and short decisions" />
            <StatCard label="Near misses" value={summary.nearMiss} helper="High-signal no-action plans" />
            <StatCard label="High priority" value={summary.highPriority} helper="Review these first" />
            <StatCard label="Degraded" value={summary.degraded} helper="Plans produced with missing or failed deep analysis" />
          </section>

          <section className="two-column">
            <Card>
              <SectionTitle
                kicker="Review queue"
                title="High-priority samples"
                subtitle="Use this list to inspect borderline no-action plans and the rare actionable cases side by side."
              />
              {highPrioritySamples.length === 0 ? (
                <EmptyState message="No decision samples available yet." />
              ) : (
                <div className="data-stack top-gap-small">
                  {highPrioritySamples.map((sample) => (
                    <article key={sample.id ?? `${sample.ticker}-${sample.created_at}`} className="data-card">
                      <div className="data-card-header">
                        <div className="cluster">
                          <Link to={`/tickers/${sample.ticker}`} className="badge badge-info badge-link">{sample.ticker}</Link>
                          <Badge tone={decisionTone(sample.decision_type)}>{sample.decision_type}</Badge>
                          <Badge tone={priorityTone(sample.review_priority)}>{sample.review_priority}</Badge>
                        </div>
                        <div className="helper-text">{formatDate(sample.created_at)}</div>
                      </div>
                      <div className="cluster top-gap-small">
                        <Badge>{sample.action}</Badge>
                        <Badge>{sample.horizon}</Badge>
                        <Badge tone={sample.shortlisted ? "ok" : "neutral"}>{sample.shortlisted ? `shortlist #${sample.shortlist_rank ?? "?"}` : "not shortlisted"}</Badge>
                        <Badge tone={sample.confidence_gap_percent !== null && sample.confidence_gap_percent >= 0 ? "ok" : "warning"}>{gapLabel(sample.confidence_gap_percent)}</Badge>
                      </div>
                      <div className="helper-text top-gap-small">Reason: {sample.decision_reason || "—"}</div>
                      <div className="helper-text">Notes: {truncate(sample.review_notes || sample.decision_reason || "No review notes stored.")}</div>
                      <div className="helper-text">Run {sample.run_id ?? "—"} · Job {sample.job_id ?? "—"} · Signal {sample.ticker_signal_snapshot_id ?? "—"}</div>
                    </article>
                  ))}
                </div>
              )}
            </Card>

            <Card>
              <SectionTitle
                kicker="Tuning guidance"
                title="How to use the samples"
                subtitle="This dataset is intentionally broader than final outcomes so threshold tuning has enough signal to work with."
              />
              <ul className="checklist">
                <li>Start with high-priority near misses before changing thresholds.</li>
                <li>Compare actionable samples with rejected samples at similar confidence.</li>
                <li>Look at the confidence gap and shortlist decision payload to understand why a plan missed escalation.</li>
                <li>Use the run and ticker links to jump back to the canonical evidence views.</li>
              </ul>
            </Card>
          </section>
        </div>
      ) : null}
    </>
  );
}
