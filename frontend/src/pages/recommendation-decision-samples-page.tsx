import { ChangeEvent, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { getJson } from "../api";
import { Badge, Card, EmptyState, ErrorState, HelpHint, LoadingState, PageHeader, SectionTitle, StatCard } from "../components/ui";
import type { RecommendationDecisionSampleListResponse } from "../types";
import { formatDate, recommendationBenchmarkTone, recommendationDecisionTone, recommendationReviewPriorityTone, yahooFinanceUrl } from "../utils";

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
  const benchmarkResult = searchParams.get("benchmark_result") ?? "";

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
    const benchmarked = items.filter((item) => item.benchmark_status === "evaluated");
    const benchmarkHits = benchmarked.filter((item) => item.benchmark_target_1d_hit === true || item.benchmark_target_5d_hit === true);
    const benchmarkMisses = benchmarked.filter((item) => item.benchmark_target_1d_hit !== true && item.benchmark_target_5d_hit !== true);
    return {
      total: items.length,
      actionable: items.filter((item) => item.decision_type === "actionable").length,
      nearMiss: items.filter((item) => item.decision_type === "near_miss").length,
      degraded: items.filter((item) => item.decision_type === "degraded").length,
      highPriority: items.filter((item) => item.review_priority === "high").length,
      benchmarked: benchmarked.length,
      benchmarkHits: benchmarkHits.length,
      benchmarkMisses: benchmarkMisses.length,
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

  function handleBenchmarkResultChange(event: ChangeEvent<HTMLSelectElement>) {
    const next = new URLSearchParams(searchParams);
    if (event.target.value) {
      next.set("benchmark_result", event.target.value);
    } else {
      next.delete("benchmark_result");
    }
    next.set("page", "1");
    setSearchParams(next);
  }

  return (
    <>
      <PageHeader
        kicker="Research"
        title="Decision samples"
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
          <Card>
            <SectionTitle
              kicker="Filters"
              title="Benchmark follow-through"
              actions={<HelpHint tooltip="Use benchmark filters to focus on missed opportunities, clean rejects, or rows that still need follow-through evaluation." to="/docs?doc=signal-gating-benchmark-spec" />}
            />
            <div className="form-grid">
              <label className="form-field">
                <span>Benchmark result</span>
                <select value={benchmarkResult} onChange={handleBenchmarkResultChange}>
                  <option value="">All</option>
                  <option value="pending">Pending only</option>
                  <option value="hit">Hit only</option>
                  <option value="miss">Miss only</option>
                </select>
              </label>
            </div>
            <div className="helper-text top-gap-small">Current filter: {benchmarkResult || "all"}</div>
          </Card>
          <section className="metrics-grid">
            <StatCard label="Samples on page" value={summary.total} helper={`Showing ${summary.total} of ${totalSamples} filtered samples`} tooltip="The number of decision samples shown on the current page after filters are applied." tooltipTo="/docs?doc=glossary&section=recommendation-decision-sample" />
            <StatCard label="Actionable on page" value={summary.actionable} helper="Long and short decisions" tooltip="Samples whose final decision was actionable, usually long or short." tooltipTo="/docs?doc=glossary&section=actionable-plan" />
            <StatCard label="Near misses on page" value={summary.nearMiss} helper="High-signal no-action plans" tooltip="Borderline no-action cases that looked close to passing the gate and are often the most useful samples for tuning review." tooltipTo="/docs?doc=decision-sample-tuning-guide" />
            <StatCard label="High priority on page" value={summary.highPriority} helper="Review these first" tooltip="Samples marked as most informative for operator review because they are borderline, degraded, contradictory, or otherwise tuning-relevant." tooltipTo="/docs?doc=decision-sample-tuning-guide" />
            <StatCard label="Benchmarked on page" value={summary.benchmarked} helper="Discarded signals graded by follow-through" tooltip="Samples that were not primarily plan-linked and now carry a benchmark follow-through label." tooltipTo="/docs?doc=signal-gating-benchmark-spec" />
            <StatCard label="Benchmark hits" value={summary.benchmarkHits} helper="Likely missed opportunities" tooltip="Benchmarked samples whose later price movement satisfied the follow-through target in the signal direction." tooltipTo="/docs?doc=signal-gating-benchmark-spec" />
            <StatCard label="Benchmark misses" value={summary.benchmarkMisses} helper="Likely good rejects" tooltip="Benchmarked samples whose later price movement did not satisfy the follow-through target." tooltipTo="/docs?doc=signal-gating-benchmark-spec" />
            <StatCard label="Degraded on page" value={summary.degraded} helper="Plans produced with missing or failed deep analysis" tooltip="Samples carrying degraded evidence, such as missing or failed deep-analysis inputs, and therefore deserving more caution during review." tooltipTo="/docs?doc=glossary&section=degraded" />
          </section>

          <Card>
            <SectionTitle
              kicker="Review queue"
              title="High-priority samples"
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
                        <Badge tone={recommendationDecisionTone(sample.decision_type)}>{sample.decision_type}</Badge>
                        <Badge tone={recommendationReviewPriorityTone(sample.review_priority)}>{sample.review_priority}</Badge>
                      </div>
                      <div className="helper-text">{formatDate(sample.created_at)}</div>
                    </div>
                    <div className="cluster top-gap-small">
                      <Badge>{sample.action}</Badge>
                      <Badge>{sample.horizon}</Badge>
                      <Badge tone={sample.shortlisted ? "ok" : "neutral"}>{sample.shortlisted ? `shortlist #${sample.shortlist_rank ?? "?"}` : "not shortlisted"}</Badge>
                      <Badge tone={sample.confidence_gap_percent !== null && sample.confidence_gap_percent >= 0 ? "ok" : "warning"}>{gapLabel(sample.confidence_gap_percent)}</Badge>
                      <Badge tone={recommendationBenchmarkTone(sample)}>{sample.benchmark_status === "evaluated" ? (sample.benchmark_target_1d_hit || sample.benchmark_target_5d_hit ? "benchmark hit" : "benchmark miss") : "benchmark pending"}</Badge>
                    </div>
                    <div className="cluster top-gap-small">
                      <Badge>benchmark dir {sample.benchmark_direction ?? "—"}</Badge>
                      <Badge>1d {sample.benchmark_target_1d_hit === null ? "—" : sample.benchmark_target_1d_hit ? "hit" : "miss"}</Badge>
                      <Badge>5d {sample.benchmark_target_5d_hit === null ? "—" : sample.benchmark_target_5d_hit ? "hit" : "miss"}</Badge>
                      <Badge>mfe {sample.benchmark_max_favorable_pct === null ? "—" : `${sample.benchmark_max_favorable_pct.toFixed(2)}%`}</Badge>
                    </div>
                    <div className="helper-text top-gap-small">Reason: {sample.decision_reason || "—"}</div>
                    <div className="helper-text">Notes: {truncate(sample.review_notes || sample.decision_reason || "No review notes stored.")}</div>
                    <div className="helper-text">Run {sample.run_id ?? "—"} · Job {sample.job_id ?? "—"} · Signal {sample.ticker_signal_snapshot_id ?? "—"} · Benchmarked {sample.benchmark_status}</div>
                    <div className="cluster top-gap-small">
                      {sample.recommendation_plan_id ? (
                        <Link to={`/jobs/recommendation-plans?plan_id=${sample.recommendation_plan_id}`} className="button-secondary">
                          Open plan
                        </Link>
                      ) : sample.ticker_signal_snapshot_id ? (
                        <Link to={`/jobs/ticker-signals?snapshot_id=${sample.ticker_signal_snapshot_id}&limit=1`} className="button-secondary">
                          Open signal
                        </Link>
                      ) : (
                        <Link to={`/jobs/ticker-signals?ticker=${encodeURIComponent(sample.ticker)}${sample.run_id ? `&run_id=${sample.run_id}` : ""}&limit=50`} className="button-secondary">
                          Open signals
                        </Link>
                      )}
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
                        <Badge tone={recommendationDecisionTone(sample.decision_type)}>{sample.decision_type}</Badge>
                        <Badge tone={recommendationReviewPriorityTone(sample.review_priority)}>{sample.review_priority}</Badge>
                      </div>
                      <div className="helper-text">{formatDate(sample.created_at)}</div>
                    </div>
                    <div className="cluster top-gap-small">
                      <Badge>{sample.action}</Badge>
                      <Badge>{sample.horizon}</Badge>
                      <Badge tone={sample.shortlisted ? "ok" : "neutral"}>{sample.shortlisted ? `shortlist #${sample.shortlist_rank ?? "?"}` : "not shortlisted"}</Badge>
                      <Badge tone={sample.confidence_gap_percent !== null && sample.confidence_gap_percent >= 0 ? "ok" : "warning"}>{gapLabel(sample.confidence_gap_percent)}</Badge>
                      <Badge tone={recommendationBenchmarkTone(sample)}>{sample.benchmark_status === "evaluated" ? (sample.benchmark_target_1d_hit || sample.benchmark_target_5d_hit ? "benchmark hit" : "benchmark miss") : "benchmark pending"}</Badge>
                    </div>
                    <div className="cluster top-gap-small">
                      <Badge>benchmark dir {sample.benchmark_direction ?? "—"}</Badge>
                      <Badge>1d {sample.benchmark_target_1d_hit === null ? "—" : sample.benchmark_target_1d_hit ? "hit" : "miss"}</Badge>
                      <Badge>5d {sample.benchmark_target_5d_hit === null ? "—" : sample.benchmark_target_5d_hit ? "hit" : "miss"}</Badge>
                      <Badge>mfe {sample.benchmark_max_favorable_pct === null ? "—" : `${sample.benchmark_max_favorable_pct.toFixed(2)}%`}</Badge>
                    </div>
                    <div className="helper-text top-gap-small">Reason: {sample.decision_reason || "—"}</div>
                    <div className="helper-text">Notes: {truncate(sample.review_notes || sample.decision_reason || "No review notes stored.")}</div>
                    <div className="helper-text">Run {sample.run_id ?? "—"} · Job {sample.job_id ?? "—"} · Signal {sample.ticker_signal_snapshot_id ?? "—"} · Benchmarked {sample.benchmark_status}</div>
                    <div className="cluster top-gap-small">
                      {sample.recommendation_plan_id ? (
                        <Link to={`/jobs/recommendation-plans?plan_id=${sample.recommendation_plan_id}`} className="button-secondary">
                          Open plan
                        </Link>
                      ) : sample.ticker_signal_snapshot_id ? (
                        <Link to={`/jobs/ticker-signals?snapshot_id=${sample.ticker_signal_snapshot_id}&limit=1`} className="button-secondary">
                          Open signal
                        </Link>
                      ) : (
                        <Link to={`/jobs/ticker-signals?ticker=${encodeURIComponent(sample.ticker)}${sample.run_id ? `&run_id=${sample.run_id}` : ""}&limit=50`} className="button-secondary">
                          Open signals
                        </Link>
                      )}
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
            />
            <ul className="checklist">
              <li>Start with high-priority near misses before changing thresholds.</li>
              <li>Compare actionable samples with rejected samples at similar confidence.</li>
              <li>Benchmark hits are the most likely shortlist false negatives; benchmark misses are the most likely shortlist true negatives.</li>
              <li>Look at the confidence gap, shortlist decision payload, and benchmark follow-through to understand why a sample missed escalation or likely was a good reject.</li>
              <li>Use the plan button when downstream framing exists; otherwise open the linked signal record to inspect shortlist, cheap-scan, and benchmark context.</li>
            </ul>
          </Card>
        </div>
      ) : null}
    </>
  );
}
