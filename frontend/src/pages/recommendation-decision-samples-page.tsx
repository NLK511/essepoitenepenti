import { ChangeEvent, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { getJson } from "../api";
import { Badge, Card, EmptyState, ErrorState, HelpHint, LoadingState, PageHeader, SectionTitle, StatCard } from "../components/ui";
import type { RecommendationDecisionSample, RecommendationDecisionSampleListResponse } from "../types";
import { formatDate, yahooFinanceUrl } from "../utils";

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

function buildQuery(searchParams: URLSearchParams): string {
  const query = new URLSearchParams(searchParams);
  const limit = Math.max(1, Number(query.get("limit") ?? "50") || 50);
  const page = Math.max(1, Number(query.get("page") ?? "1") || 1);
  query.set("limit", String(limit));
  query.set("offset", String((page - 1) * limit));
  query.delete("page");
  const queryString = query.toString();
  return queryString ? `/api/recommendation-decision-samples?${queryString}` : "/api/recommendation-decision-samples";
}

export function RecommendationDecisionSamplesPage() {
  const [searchParams, setSearchParams] = useSearchParams({ limit: "50", page: "1" });
  const [samplesResponse, setSamplesResponse] = useState<RecommendationDecisionSampleListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const pageSize = Math.max(1, Number(searchParams.get("limit") ?? "50") || 50);
  const currentPage = Math.max(1, Number(searchParams.get("page") ?? "1") || 1);

  useEffect(() => {
    async function load() {
      try {
        setError(null);
        const loadedSamples = await getJson<RecommendationDecisionSampleListResponse>(buildQuery(searchParams));
        setSamplesResponse(loadedSamples);
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : "Failed to load decision samples");
      }
    }
    void load();
  }, [searchParams]);

  const samples = samplesResponse?.items ?? null;
  const totalSamples = samplesResponse?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(totalSamples / pageSize));
  const pageStart = samples && samples.length > 0 ? (currentPage - 1) * pageSize + 1 : 0;
  const pageEnd = samples && samples.length > 0 ? pageStart + samples.length - 1 : 0;
  const hasNextPage = currentPage < pageCount;

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

  const allSamples = samples ?? [];

  function goToPage(nextPage: number) {
    const next = new URLSearchParams(searchParams);
    next.set("page", String(Math.max(1, nextPage)));
    setSearchParams(next);
  }

  function handlePageSizeChange(event: ChangeEvent<HTMLSelectElement>) {
    const next = new URLSearchParams(searchParams);
    next.set("limit", event.target.value);
    next.set("page", "1");
    setSearchParams(next);
  }

  return (
    <>
      <PageHeader
        kicker="Research"
        title="Decision samples"
        subtitle="This page is for reviewing samples and learning from the plans the system already produced. It keeps near-misses, rejected setups, and actionable plans in one central review surface so small action counts do not leave you blind to what the planner is doing."
        actions={
          <>
            <HelpHint tooltip="Decision samples are for review and learning: actionable, near-miss, and degraded cases stay visible even when final action counts are small." to="/docs?doc=operator-page-field-guide" />
            <Link to="/research" className="button-subtle">Research hub</Link>
            <Link to="/research/signal-gating/gating-job" className="button-secondary">Gating tuning job</Link>
            <Link to="/jobs/recommendation-plans" className="button-secondary">Back to plans</Link>
          </>
        }
      />

      {error ? <ErrorState message={error} /> : null}
      {!samplesResponse && !error ? <LoadingState message="Loading decision samples…" /> : null}

      {samples ? (
        <div className="stack-page">
          <section className="metrics-grid">
            <StatCard label="Samples on page" value={summary.total} helper={`Showing ${summary.total} of ${totalSamples} filtered samples`} tooltip="The number of decision samples shown on the current page after filters are applied." tooltipTo="/docs?doc=glossary&section=recommendation-decision-sample" />
            <StatCard label="Actionable on page" value={summary.actionable} helper="Long and short decisions" tooltip="Samples whose final decision was actionable, usually long or short." tooltipTo="/docs?doc=glossary&section=actionable-plan" />
            <StatCard label="Near misses on page" value={summary.nearMiss} helper="High-signal no-action plans" tooltip="Borderline no-action cases that looked close to passing the gate and are often the most useful samples for tuning review." tooltipTo="/docs?doc=decision-sample-tuning-guide" />
            <StatCard label="High priority on page" value={summary.highPriority} helper="Review these first" tooltip="Samples marked as most informative for operator review because they are borderline, degraded, contradictory, or otherwise tuning-relevant." tooltipTo="/docs?doc=decision-sample-tuning-guide" />
            <StatCard label="Degraded on page" value={summary.degraded} helper="Plans produced with missing or failed deep analysis" tooltip="Samples carrying degraded evidence, such as missing or failed deep-analysis inputs, and therefore deserving more caution during review." tooltipTo="/docs?doc=glossary&section=degraded" />
          </section>

          <Card>
            <SectionTitle
              kicker="Review queue"
              title="High-priority samples"
              subtitle="Use this list to inspect borderline no-action plans and the rare actionable cases on the current page side by side."
              actions={<HelpHint tooltip="High-priority samples help you inspect the most informative review cases on the current page first." to="/docs?doc=operator-page-field-guide" />}
            />
            {highPrioritySamples.length === 0 ? (
              <EmptyState message="No high-priority samples available yet." />
            ) : (
              <div className="data-stack top-gap-small">
                {highPrioritySamples.map((sample) => (
                  <article key={sample.id ?? `${sample.ticker}-${sample.created_at}`} className="data-card">
                    <div className="data-card-header">
                      <div className="cluster">
                        <a href={yahooFinanceUrl(sample.ticker)} className="badge badge-info badge-link" target="_blank" rel="noreferrer noopener">{sample.ticker}</a>
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
                    <div className="cluster top-gap-small">
                      <Link
                        to={sample.recommendation_plan_id ? `/jobs/recommendation-plans?plan_id=${sample.recommendation_plan_id}` : "/jobs/recommendation-plans"}
                        className="button-secondary"
                      >
                        Open plan
                      </Link>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </Card>

          <div className="pagination">
            <label className="form-field">
              <span>Page size</span>
              <select value={String(pageSize)} onChange={handlePageSizeChange}>
                <option value="25">25</option>
                <option value="50">50</option>
                <option value="100">100</option>
                <option value="200">200</option>
              </select>
            </label>
            <button type="button" className="button-subtle" onClick={() => goToPage(currentPage - 1)} disabled={currentPage <= 1}>
              Previous
            </button>
            <div className="helper-text">
              Page {currentPage} of {pageCount}{allSamples.length > 0 ? ` · showing ${pageStart}–${pageEnd} of ${totalSamples}` : " · no results on this page"}
            </div>
            <button type="button" className="button-subtle" onClick={() => goToPage(currentPage + 1)} disabled={!hasNextPage}>
              Next
            </button>
          </div>

          <Card>
            <SectionTitle
              kicker="All samples"
              title="Decision sample archive"
              subtitle="Browse the current page of samples so older records remain visible for review and future research work."
            />
            {allSamples.length === 0 ? (
              <EmptyState message="No decision samples available yet." />
            ) : (
              <div className="data-stack top-gap-small">
                {allSamples.map((sample) => (
                  <article key={sample.id ?? `${sample.ticker}-${sample.created_at}`} className="data-card">
                    <div className="data-card-header">
                      <div className="cluster">
                        <a href={yahooFinanceUrl(sample.ticker)} className="badge badge-info badge-link" target="_blank" rel="noreferrer noopener">{sample.ticker}</a>
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
                    <div className="cluster top-gap-small">
                      <Link
                        to={sample.recommendation_plan_id ? `/jobs/recommendation-plans?plan_id=${sample.recommendation_plan_id}` : "/jobs/recommendation-plans"}
                        className="button-secondary"
                      >
                        Open plan
                      </Link>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </Card>

          <Card>
            <SectionTitle
              kicker="Research"
              title="How to use the samples"
              subtitle="This dataset is intentionally broader than final outcomes so tuning and replay work can reuse it later."
            />
            <ul className="checklist">
              <li>Start with high-priority near misses before changing thresholds.</li>
              <li>Compare actionable samples with rejected samples at similar confidence.</li>
              <li>Look at the confidence gap and shortlist decision payload to understand why a plan missed escalation.</li>
              <li>Use the plan button to jump directly to the canonical recommendation output.</li>
            </ul>
          </Card>
        </div>
      ) : null}
    </>
  );
}
