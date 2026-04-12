import { Fragment, FormEvent, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { getJson, postForm } from "../api";
import { relationshipSummary } from "../components/ticker-relationship-readthrough";
import { Badge, Card, EmptyState, ErrorState, HelpHint, LoadingState, PageHeader, SectionTitle, SegmentedTabs, StatCard } from "../components/ui";
import { ScoreBadge } from "../components/decision-surface";
import type {
  IndustryContextSnapshot,
  MacroContextSnapshot,
  RecommendationBaselineSummary,
  RecommendationCalibrationSummary,
  RecommendationEvidenceConcentrationSummary,
  RecommendationPlan,
  RecommendationPlanListResponse,
  RecommendationPlanStats,
  RecommendationSetupFamilyReviewSummary,
  Run,
} from "../types";
import { detailLabel, extractDisplayLabels, formatDate, yahooFinanceUrl } from "../utils";

function buildQuery(searchParams: URLSearchParams): string {
  const query = new URLSearchParams(searchParams);
  const limit = Math.max(1, Number(query.get("limit") ?? "100") || 100);
  const page = Math.max(1, Number(query.get("page") ?? "1") || 1);
  query.set("limit", String(limit));
  query.set("offset", String((page - 1) * limit));
  query.delete("page");
  const queryString = query.toString();
  return queryString ? `/api/recommendation-plans?${queryString}` : "/api/recommendation-plans";
}

function actionTone(action: string): "ok" | "warning" | "neutral" {
  if (action === "long") {
    return "ok";
  }
  if (action === "short") {
    return "warning";
  }
  return "neutral";
}

function biasTone(value: string): "ok" | "warning" | "neutral" {
  if (value === "tailwind") {
    return "ok";
  }
  if (value === "headwind") {
    return "warning";
  }
  return "neutral";
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function calibrationSliceSummary(calibrationReview: unknown, key: string): string {
  const review = asRecord(calibrationReview);
  const item = asRecord(review?.[key]);
  if (!item) {
    return "—";
  }
  const sliceKey = typeof item.key === "string" ? item.key : key;
  const sliceLabel = typeof item.label === "string" && item.label ? item.label : sliceKey;
  const sampleStatus = typeof item.sample_status === "string" ? item.sample_status : "unknown";
  const resolvedCount = typeof item.resolved_count === "number" ? item.resolved_count : 0;
  const winRate = typeof item.win_rate_percent === "number" ? `${item.win_rate_percent}%` : "—";
  return `${sliceLabel} · ${sampleStatus} · n=${resolvedCount} · win ${winRate}`;
}

function joinSummary(items: string[], empty = "none"): string {
  return items.length > 0 ? items.join(" · ") : empty;
}

function formatPriceRange(low: number | null | undefined, high: number | null | undefined): string {
  if (low === null || low === undefined) {
    return "—";
  }
  if (high === null || high === undefined || high === low) {
    return String(low);
  }
  return `${low} – ${high}`;
}

function truncateText(value: string, maxLength: number): string {
  if (value.length <= maxLength) {
    return value;
  }
  return `${value.slice(0, Math.max(0, maxLength - 1)).trimEnd()}…`;
}

function contextSummaryMethod(snapshot: MacroContextSnapshot | IndustryContextSnapshot | null | undefined): string {
  return snapshot && typeof snapshot.metadata?.context_summary_method === "string" ? snapshot.metadata.context_summary_method : "unknown";
}

function contextSummaryBackend(snapshot: MacroContextSnapshot | IndustryContextSnapshot | null | undefined): string {
  return snapshot && typeof snapshot.metadata?.context_summary_backend === "string" ? snapshot.metadata.context_summary_backend : "—";
}

function contextSummaryModel(snapshot: MacroContextSnapshot | IndustryContextSnapshot | null | undefined): string {
  return snapshot && typeof snapshot.metadata?.context_summary_model === "string" ? snapshot.metadata.context_summary_model : "—";
}

function contextSummaryError(snapshot: MacroContextSnapshot | IndustryContextSnapshot | null | undefined): string | null {
  return snapshot && typeof snapshot.metadata?.context_summary_error === "string" ? snapshot.metadata.context_summary_error : null;
}

function contextProvenanceTone(snapshot: MacroContextSnapshot | IndustryContextSnapshot | null | undefined): "ok" | "warning" | "neutral" {
  if (contextSummaryError(snapshot)) {
    return "warning";
  }
  if (contextSummaryMethod(snapshot) === "llm_summary") {
    return "ok";
  }
  return "neutral";
}

function contextProvenanceLabel(snapshot: MacroContextSnapshot | IndustryContextSnapshot | null | undefined): string {
  if (contextSummaryMethod(snapshot) === "llm_summary") {
    const model = contextSummaryModel(snapshot);
    return `LLM · ${contextSummaryBackend(snapshot)}${model !== "—" ? ` · ${model}` : ""}`;
  }
  return `fallback · ${contextSummaryBackend(snapshot)}`;
}

function docsLink(doc: string, section?: string): string {
  const params = new URLSearchParams({ doc });
  if (section) {
    params.set("section", section);
  }
  return `/docs?${params.toString()}`;
}

const recommendationPlansDoc = (section?: string) => docsLink("operator-page-field-guide", section);
const glossaryDoc = (section?: string) => docsLink("glossary", section);
const analyticsWindows = ["all", "7d", "30d", "90d", "180d", "1y"] as const;

function analyticsWindowStartIso(window: (typeof analyticsWindows)[number]): string | null {
  if (window === "all") {
    return null;
  }
  const days = window === "7d" ? 7 : window === "30d" ? 30 : window === "90d" ? 90 : window === "180d" ? 180 : 365;
  return new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString();
}

function HelpLabel({ label, tooltip, to }: { label: string; tooltip: string; to: string }) {
  return (
    <span className="help-label">
      <span>{label}</span>
      <HelpHint tooltip={tooltip} to={to} ariaLabel={`${label}. ${tooltip}. Open documentation.`} />
    </span>
  );
}

export function RecommendationPlansPage() {
  const [searchParams, setSearchParams] = useSearchParams({ limit: "100", page: "1" });
  const focusedPlanId = searchParams.get("plan_id");
  const [plansResponse, setPlansResponse] = useState<RecommendationPlanListResponse | null>(null);
  const [planStats, setPlanStats] = useState<RecommendationPlanStats | null>(null);
  const [analyticsWindow, setAnalyticsWindow] = useState<(typeof analyticsWindows)[number]>("30d");
  const [macroContextByRun, setMacroContextByRun] = useState<Record<number, MacroContextSnapshot | null>>({});
  const [industryContextByRun, setIndustryContextByRun] = useState<Record<number, IndustryContextSnapshot | null>>({});
  const [calibration, setCalibration] = useState<RecommendationCalibrationSummary | null>(null);
  const [baselines, setBaselines] = useState<RecommendationBaselineSummary | null>(null);
  const [familyReview, setFamilyReview] = useState<RecommendationSetupFamilyReviewSummary | null>(null);
  const [evidenceConcentration, setEvidenceConcentration] = useState<RecommendationEvidenceConcentrationSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [evaluationMessage, setEvaluationMessage] = useState<string | null>(null);
  const [evaluating, setEvaluating] = useState(false);
  const [evaluatingPlanId, setEvaluatingPlanId] = useState<number | null>(null);
  const [expandedPlanRows, setExpandedPlanRows] = useState<Record<string, boolean>>({});
  const [pageMode, setPageMode] = useState<"review" | "analytics">("review");
  const pageSize = Math.max(1, Number(searchParams.get("limit") ?? "100") || 100);
  const currentPage = Math.max(1, Number(searchParams.get("page") ?? "1") || 1);
  const plans = plansResponse?.items ?? null;
  const planTotal = plansResponse?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(planTotal / pageSize));
  const planStart = plans && plans.length > 0 ? (currentPage - 1) * pageSize + 1 : 0;
  const planEnd = plans && plans.length > 0 ? planStart + plans.length - 1 : 0;
  const hasNextPlans = currentPage < pageCount;

  useEffect(() => {
    async function load() {
      try {
        setError(null);
        setExpandedPlanRows({});
        const summaryParams = new URLSearchParams({ limit: "2000" });
        const runId = searchParams.get("run_id");
        const ticker = searchParams.get("ticker");
        const setupFamily = searchParams.get("setup_family");
        const planId = searchParams.get("plan_id");
        const resolved = searchParams.get("resolved");
        const outcome = searchParams.get("outcome");
        const computedAfter = analyticsWindowStartIso(analyticsWindow);
        if (runId) {
          summaryParams.set("run_id", runId);
        }
        if (ticker) {
          summaryParams.set("ticker", ticker);
        }
        if (setupFamily) {
          summaryParams.set("setup_family", setupFamily);
        }
        if (planId) {
          summaryParams.set("plan_id", planId);
        }
        if (resolved) {
          summaryParams.set("resolved", resolved);
        }
        if (outcome) {
          summaryParams.set("outcome", outcome);
        }
        const summaryQuery = summaryParams.toString();
        const statsParams = new URLSearchParams();
        if (computedAfter) {
          summaryParams.set("computed_after", computedAfter);
          summaryParams.set("evaluated_after", computedAfter);
          statsParams.set("computed_after", computedAfter);
        }
        const [planResults, stats] = await Promise.all([
          getJson<RecommendationPlanListResponse>(buildQuery(searchParams)),
          getJson<RecommendationPlanStats>(`/api/recommendation-plans/stats?${statsParams.toString()}`),
        ]);
        setPlansResponse(planResults);
        setPlanStats(stats);
        setCalibration(await getJson<RecommendationCalibrationSummary>(`/api/recommendation-outcomes/summary?${summaryQuery}`));
        setBaselines(await getJson<RecommendationBaselineSummary>(`/api/recommendation-plans/baselines?${summaryQuery}`));
        setFamilyReview(await getJson<RecommendationSetupFamilyReviewSummary>(`/api/recommendation-outcomes/setup-family-review?${summaryQuery}`));
        setEvidenceConcentration(await getJson<RecommendationEvidenceConcentrationSummary>(`/api/recommendation-outcomes/evidence-concentration?${summaryQuery}`));

        const runIds = Array.from(new Set(planResults.items.map((item) => item.run_id).filter((value): value is number => typeof value === "number"))).slice(0, 20);
        if (planId) {
          const targetPlanId = Number(planId);
          if (!Number.isNaN(targetPlanId)) {
            const targetPlan = planResults.items.find((item) => item.id === targetPlanId);
            if (targetPlan?.id !== null && targetPlan?.id !== undefined) {
              setExpandedPlanRows({ [String(targetPlan.id)]: true });
            }
          }
        }
        if (runIds.length === 0) {
          setMacroContextByRun({});
          setIndustryContextByRun({});
        } else {
          const macroEntries = await Promise.all(
            runIds.map(async (id) => [id, (await getJson<MacroContextSnapshot[]>(`/api/context/macro?run_id=${id}&limit=1`))[0] ?? null] as const),
          );
          const industryEntries = await Promise.all(
            runIds.map(async (id) => [id, (await getJson<IndustryContextSnapshot[]>(`/api/context/industry?run_id=${id}&limit=1`))[0] ?? null] as const),
          );
          setMacroContextByRun(Object.fromEntries(macroEntries));
          setIndustryContextByRun(Object.fromEntries(industryEntries));
        }
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : "Failed to load recommendation plans");
      }
    }
    void load();
  }, [searchParams, analyticsWindow]);

  useEffect(() => {
    if (!focusedPlanId || !plans) {
      return;
    }
    const targetPlanId = Number(focusedPlanId);
    if (Number.isNaN(targetPlanId)) {
      return;
    }
    const row = document.getElementById(`recommendation-plan-row-${targetPlanId}`);
    if (!row) {
      return;
    }
    row.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [focusedPlanId, plans]);

  async function queueEvaluation(planId?: number) {
    try {
      if (planId) {
        setEvaluatingPlanId(planId);
      } else {
        setEvaluating(true);
      }
      setError(null);
      setEvaluationMessage(null);
      const run = planId
        ? await postForm<Run>(`/api/recommendation-plans/${planId}/evaluate`, {})
        : await postForm<Run>("/api/recommendation-plans/evaluate", {});
      setEvaluationMessage(
        planId
          ? `Queued recommendation-plan evaluation run #${run.id} for plan #${planId}.`
          : `Queued recommendation-plan evaluation run #${run.id}.`,
      );
      setPlansResponse(await getJson<RecommendationPlanListResponse>(buildQuery(searchParams)));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to queue recommendation-plan evaluation");
    } finally {
      setEvaluating(false);
      setEvaluatingPlanId(null);
    }
  }

  function togglePlanRow(planKey: string) {
    setExpandedPlanRows((current) => ({
      ...current,
      [planKey]: !current[planKey],
    }));
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    const next = new URLSearchParams();
    for (const [key, value] of formData.entries()) {
      const normalized = String(value).trim();
      if (normalized) {
        next.set(key, normalized);
      }
    }
    if (!next.has("limit")) {
      next.set("limit", "100");
    }
    next.set("page", "1");
    setSearchParams(next);
  }

  function goToPage(nextPage: number) {
    const next = new URLSearchParams(searchParams);
    next.set("page", String(Math.max(1, nextPage)));
    setSearchParams(next);
  }

  return (
    <>
      <PageHeader
        kicker="Review"
        title="Recommendation plans"
        subtitle="Use this page as the main action-review queue. Review plans here, then open Recommendation Quality or Research when you need deeper trust or validation analysis."
        actions={
          <button
            type="button"
            className="icon-button icon-button-primary"
            onClick={() => void queueEvaluation()}
            disabled={evaluating}
            title={evaluating ? "Queueing plan evaluation" : "Queue plan evaluation"}
            aria-label={evaluating ? "Queueing plan evaluation" : "Queue plan evaluation"}
          >
            ↻
          </button>
        }
      />
      {error ? <ErrorState message={error} /> : null}
      {evaluationMessage ? <Card><div className="helper-text">{evaluationMessage}</div></Card> : null}
      <Card className="top-gap">
        <SectionTitle
          kicker="Global stats"
          title="Recommendation plan review stats"
          subtitle="These headline stats are broad posture checks across recommendation plans. They are not the canonical trust surface."
          actions={<HelpHint tooltip="These headline numbers are global review stats, not just the current table filters. Use them as top-level posture checks before drilling into cohorts or individual plans." to={recommendationPlansDoc("recommendation-plans")} />}
        />
        <div className="top-gap-small">
          <SegmentedTabs
            value={analyticsWindow}
            onChange={(value) => setAnalyticsWindow(value as (typeof analyticsWindows)[number])}
            options={analyticsWindows.map((window) => ({ value: window, label: window === "all" ? "All" : window.toUpperCase() }))}
          />
        </div>
        <section className="metrics-grid top-gap-small">
          <StatCard label="Total plans" value={planStats?.total_plans ?? "—"} helper={`Broad posture check · ${analyticsWindow === "all" ? "all time" : analyticsWindow.toUpperCase()}`} tooltip="The total number of stored recommendation plans in the selected broad review window, regardless of the current table filters." tooltipTo={recommendationPlansDoc("recommendation-plans")} />
          <StatCard label="Open plans" value={planStats?.open_plans ?? "—"} helper="Open plans across all recommendations" tooltip="Plans that have not yet resolved to a terminal measured outcome in the selected stats window." tooltipTo={recommendationPlansDoc("outcome-fields")} />
          <StatCard label="Expired plans" value={planStats?.expired_plans ?? "—"} helper="Terminal expired outcomes across all recommendations" tooltip="Plans whose evaluation horizon elapsed without a terminal win or loss. Expired is operator-visible, but it is excluded from default win/loss scoring." tooltipTo={glossaryDoc("expired-plan")} />
          <StatCard label="Win rate" value={planStats?.win_rate_percent !== null && planStats?.win_rate_percent !== undefined ? `${planStats.win_rate_percent}%` : "—"} helper={`Broad posture check · ${analyticsWindow === "all" ? "all time" : analyticsWindow.toUpperCase()}`} tooltip="Overall win/loss rate in the selected broad review window. Treat this as a quick pulse, not as the full trust verdict." tooltipTo={recommendationPlansDoc("recommendation-plans")} />
          <StatCard label="Evidence concentration" value={evidenceConcentration ? (evidenceConcentration.ready_for_expansion ? "Ready" : "Focused") : "—"} helper="This card still reflects the current filtered review cohort" tooltip="Shows whether the current filtered cohort has clear enough separation between stronger and weaker groups to justify broader trust, or whether review should stay selective." tooltipTo={glossaryDoc("evidence-concentration")} />
        </section>
      </Card>

      <Card className="top-gap">
        <SectionTitle kicker="Page focus" title="Choose the page focus" subtitle="Keep the default path list-first. Use the secondary cohort pulse only for lightweight queue context, then jump to Research or Recommendation Quality for deeper analysis." actions={<HelpHint tooltip="Review queue is the main operator path for reading plans one by one. The secondary cohort pulse is only lightweight context, not the canonical research surface." to={recommendationPlansDoc("review-workspace-tabs")} />} />
        <div className="top-gap-small">
          <SegmentedTabs
            value={pageMode}
            onChange={(value) => setPageMode(value as "review" | "analytics")}
            options={[
              { value: "review", label: "Review queue" },
              { value: "analytics", label: "Cohort pulse" },
            ]}
          />
        </div>
      </Card>

      {pageMode === "review" ? (
      <Card className="sticky-toolbar">
        <SectionTitle kicker="Filters" title="Find recommendation plans" subtitle="Filter the review queue by ticker, run, setup, resolution, or outcome." actions={<HelpHint tooltip="Use filters to narrow the recommendation-plan review set before opening plan details." to={recommendationPlansDoc("filter-bar")} />} />
        <form className="form-grid" onSubmit={handleSubmit}>
          <label className="form-field"><span>Ticker</span><input name="ticker" defaultValue={searchParams.get("ticker") ?? ""} placeholder="AAPL" /></label>
          <label className="form-field"><span>Action</span><select name="action" defaultValue={searchParams.get("action") ?? ""}><option value="">All</option><option value="long">long</option><option value="short">short</option><option value="no_action">no_action</option></select></label>
          <label className="form-field"><span>Run id</span><input name="run_id" defaultValue={searchParams.get("run_id") ?? ""} placeholder="145" /></label>
          <label className="form-field"><span>Plan id</span><input name="plan_id" defaultValue={searchParams.get("plan_id") ?? ""} placeholder="812" /></label>
          <label className="form-field"><span>Setup family</span><select name="setup_family" defaultValue={searchParams.get("setup_family") ?? ""}><option value="">All</option><option value="breakout">breakout</option><option value="continuation">continuation</option><option value="mean_reversion">mean_reversion</option><option value="breakdown">breakdown</option><option value="catalyst_follow_through">catalyst_follow_through</option><option value="macro_beneficiary_loser">macro_beneficiary_loser</option></select></label>
          <label className="form-field"><span>Resolution</span><select name="resolved" defaultValue={searchParams.get("resolved") ?? ""}><option value="">All</option><option value="resolved">Resolved only</option><option value="unresolved">Unresolved only</option></select></label>
          <label className="form-field"><span>Outcome</span><select name="outcome" defaultValue={searchParams.get("outcome") ?? ""}><option value="">All</option><option value="win">win</option><option value="loss">loss</option><option value="expired">expired</option></select></label>
          <label className="form-field"><span>Limit</span><select name="limit" defaultValue={searchParams.get("limit") ?? "100"}><option value="25">25</option><option value="50">50</option><option value="100">100</option><option value="200">200</option></select></label>
          <div className="form-actions">
            <button className="icon-button icon-button-primary" type="submit" title="Apply filters" aria-label="Apply filters">
              ✓
            </button>
          </div>
        </form>
      </Card>
      ) : null}

      {pageMode === "analytics" ? (
      <Card className="top-gap">
        <SectionTitle
          kicker="Filtered cohort pulse"
          title="Use this only as a lightweight queue-side pulse"
          subtitle={`This page now keeps only a compact pulse for the ${analyticsWindow === "all" ? "all-time" : analyticsWindow.toUpperCase()} filtered cohort. Use Recommendation Quality and Research for canonical calibration, baselines, evidence concentration, family review, and validation.`}
          actions={<HelpHint tooltip="Recommendation Plans is now a lighter operator review surface. Use Recommendation Quality and Research for the canonical trust and validation views." to={recommendationPlansDoc("review-workspace-tabs")} />}
        />
        <div className="insight-grid top-gap-small">
          <div className="data-card">
            <div className="data-card-header">
              <div>
                <h3 className="data-card-title"><HelpLabel label="Filtered cohort pulse" tooltip="A lightweight summary of the currently filtered review cohort so operators can keep context without duplicating the full research surfaces." to={recommendationPlansDoc("recommendation-plans")} /></h3>
              </div>
              <Badge tone={evidenceConcentration?.ready_for_expansion ? "ok" : "warning"}>{analyticsWindow === "all" ? "all time" : analyticsWindow.toUpperCase()}</Badge>
            </div>
            <div className="data-points">
              <div className="data-point"><span className="data-point-label">resolved outcomes</span><span className="data-point-value">{calibration?.resolved_outcomes ?? "—"}</span></div>
              <div className="data-point"><span className="data-point-label">overall win rate</span><span className="data-point-value">{calibration?.overall_win_rate_percent ?? "—"}%</span></div>
              <div className="data-point"><span className="data-point-label">actual actionable 5d</span><span className="data-point-value">{baselines?.comparisons.find((item) => item.key === "actual_actionable")?.average_return_5d ?? "—"}%</span></div>
              <div className="data-point"><span className="data-point-label">evidence posture</span><span className="data-point-value">{evidenceConcentration?.ready_for_expansion ? "ready" : "focused"}</span></div>
            </div>
            <div className="helper-text top-gap-small">{evidenceConcentration?.focus_message ?? "Use the dedicated research surfaces for full calibration, baselines, evidence concentration, and family review."}</div>
          </div>
          <div className="data-card">
            <div className="data-card-header">
              <div>
                <h3 className="data-card-title">Open the canonical trust surfaces</h3>
              </div>
              <Badge tone="info">research</Badge>
            </div>
            <div className="cluster top-gap-small">
              <Link to="/recommendation-quality" className="button-secondary">Recommendation quality</Link>
              <Link to="/research" className="button-secondary">Research hub</Link>
            </div>
            <ul className="list-reset top-gap-small">
              <li className="list-item compact-item">Calibration, baselines, evidence concentration, family review, and validation now live on the dedicated quality and research surfaces.</li>
              <li className="list-item compact-item">Use this page for queue review, plan details, and lightweight filtered-cohort triage.</li>
            </ul>
          </div>
        </div>
      </Card>
      ) : null}

      {pageMode === "review" ? (
      <Card className="top-gap">
        <SectionTitle title="Review queue" subtitle={plans ? `${planTotal} recommendation plan(s) · page ${currentPage} of ${pageCount}` : undefined} actions={<HelpHint tooltip="The main recommendation-plan table: review action, confidence, execution framing, outcomes, and thesis together." to={recommendationPlansDoc("results-table")} />} />
        {!plans && !error ? <LoadingState message="Loading recommendation plans…" /> : null}
        {plans && plans.length === 0 ? <EmptyState message="No recommendation plans match the current filters." /> : null}
        {plans ? (
          <>
            <div className="pagination">
              <button type="button" className="button-subtle" onClick={() => goToPage(currentPage - 1)} disabled={currentPage <= 1}>
                Previous
              </button>
              <div className="helper-text">
                Page {currentPage} of {pageCount}{plans && plans.length > 0 ? ` · showing ${planStart}–${planEnd} of ${planTotal}` : " · no results on this page"}
              </div>
              <button type="button" className="button-subtle" onClick={() => goToPage(currentPage + 1)} disabled={!hasNextPlans}>
                Next
              </button>
            </div>
            <div className="table-wrap recommendation-plans-table-wrap">
              <div className="recommendation-plans-table-scroll">
                <table className="recommendation-plans-table">
                  <colgroup>
                <col style={{ width: "96px" }} />
                <col style={{ width: "160px" }} />
                <col style={{ width: "100px" }} />
                <col style={{ width: "170px" }} />
                <col style={{ width: "220px" }} />
                <col style={{ width: "190px" }} />
                <col style={{ width: "150px" }} />
                <col style={{ width: "340px" }} />
                <col style={{ width: "96px" }} />
                <col style={{ width: "96px" }} />
              </colgroup>
              <thead>
                <tr>
                  <th><HelpLabel label="Computed" tooltip="When this recommendation plan was persisted." to={recommendationPlansDoc("results-table")} /></th>
                  <th><HelpLabel label="Ticker" tooltip="The instrument the plan is about, along with status, horizon, and setup family context." to={recommendationPlansDoc("trade-fields")} /></th>
                  <th><HelpLabel label="Action" tooltip="The final recommendation state: long, short, watchlist, or no_action." to={glossaryDoc("action")} /></th>
                  <th><HelpLabel label="Confidence" tooltip="Evidence-weighted plan trust, including raw confidence, calibration adjustment, and gating threshold." to={glossaryDoc("confidence")} /></th>
                  <th><HelpLabel label="Execution" tooltip="How the trade is framed: entry zone, stop, take profit, and timing expectations." to={recommendationPlansDoc("execution-style-fields")} /></th>
                  <th><HelpLabel label="Transmission" tooltip="How macro and industry context is expected to carry through to this ticker setup." to={glossaryDoc("transmission")} /></th>
                  <th><HelpLabel label="Latest outcome" tooltip="The most recent stored evaluation result for this plan, if one exists." to={recommendationPlansDoc("outcome-fields")} /></th>
                  <th className="recommendation-plan-thesis-col"><HelpLabel label="Thesis" tooltip="The summary of why the plan exists, what could invalidate it, and what to focus on during review." to={recommendationPlansDoc("explanation-fields")} /></th>
                  <th><HelpLabel label="Run" tooltip="The workflow run that produced this plan." to={glossaryDoc("run")} /></th>
                  <th>⋯</th>
                </tr>
              </thead>
              <tbody>
                {plans.map((plan) => {
                  const signalBreakdown = plan.signal_breakdown;
                  const evidenceSummary = plan.evidence_summary;
                  const transmissionSummary = signalBreakdown.transmission_summary ?? evidenceSummary.transmission_summary ?? null;
                  const calibrationReview = signalBreakdown.calibration_review ?? evidenceSummary.calibration_review ?? null;
                  const setupFamily = typeof signalBreakdown?.setup_family === "string" ? signalBreakdown.setup_family : "—";
                  const actionReason = typeof evidenceSummary?.action_reason_label === "string" && evidenceSummary.action_reason_label
                    ? evidenceSummary.action_reason_label
                    : typeof evidenceSummary?.action_reason === "string" ? evidenceSummary.action_reason : "—";
                  const actionReasonDetail = typeof evidenceSummary?.action_reason_detail === "string" ? evidenceSummary.action_reason_detail : "—";
                  const entryStyle = typeof evidenceSummary?.entry_style === "string" ? evidenceSummary.entry_style : "—";
                  const stopStyle = typeof evidenceSummary?.stop_style === "string" ? evidenceSummary.stop_style : "—";
                  const targetStyle = typeof evidenceSummary?.target_style === "string" ? evidenceSummary.target_style : "—";
                  const timingExpectation = typeof evidenceSummary?.timing_expectation === "string" ? evidenceSummary.timing_expectation : "—";
                  const evaluationFocus = Array.isArray(evidenceSummary?.evaluation_focus)
                    ? evidenceSummary.evaluation_focus.filter((value): value is string => typeof value === "string")
                    : [];
                  const invalidationSummary = typeof evidenceSummary?.invalidation_summary === "string" ? evidenceSummary.invalidation_summary : "—";
                  const transmissionBias = typeof transmissionSummary?.transmission_bias === "string"
                    ? transmissionSummary.transmission_bias
                    : typeof transmissionSummary?.context_bias === "string"
                      ? transmissionSummary.context_bias
                      : "unknown";
                  const transmissionBiasLabel = detailLabel(transmissionSummary?.transmission_bias_detail, transmissionSummary?.transmission_bias ?? transmissionSummary?.context_bias ?? "unknown", false) ?? "unknown";
                  const transmissionAlignment = typeof transmissionSummary?.alignment_percent === "number" ? transmissionSummary.alignment_percent : null;
                  const transmissionTags = extractDisplayLabels(transmissionSummary, "transmission_tag_details", "transmission_tags");
                  const primaryDrivers = extractDisplayLabels(transmissionSummary, "primary_driver_details", "primary_drivers");
                  const conflictFlags = extractDisplayLabels(transmissionSummary, "conflict_flag_details", "conflict_flags");
                  const industryExposureChannels = extractDisplayLabels(transmissionSummary, "industry_exposure_channel_details", "industry_exposure_channels");
                  const tickerExposureChannels = extractDisplayLabels(transmissionSummary, "ticker_exposure_channel_details", "ticker_exposure_channels");
                  const expectedWindow = detailLabel(
                    transmissionSummary?.expected_transmission_window_detail,
                    typeof transmissionSummary?.expected_transmission_window === "string" ? transmissionSummary.expected_transmission_window : "unknown",
                  ) ?? "unknown";
                  const effectiveThreshold = typeof calibrationReview?.effective_confidence_threshold === "number"
                    ? calibrationReview.effective_confidence_threshold
                    : null;
                  const rawConfidence = typeof calibrationReview?.raw_confidence_percent === "number"
                    ? calibrationReview.raw_confidence_percent
                    : null;
                  const calibratedConfidence = typeof calibrationReview?.calibrated_confidence_percent === "number"
                    ? calibrationReview.calibrated_confidence_percent
                    : null;
                  const confidenceAdjustment = typeof calibrationReview?.confidence_adjustment === "number"
                    ? calibrationReview.confidence_adjustment
                    : null;
                  const calibrationReviewStatus = typeof calibrationReview?.review_status_label === "string" && calibrationReview.review_status_label
                    ? calibrationReview.review_status_label
                    : typeof calibrationReview?.review_status === "string"
                      ? calibrationReview.review_status
                      : "disabled";
                  const calibrationReasons = extractDisplayLabels(calibrationReview, "reason_details", "reasons");
                  const macroContext = plan.run_id ? macroContextByRun[plan.run_id] : null;
                  const industryContext = plan.run_id ? industryContextByRun[plan.run_id] : null;
                  const planKey = plan.id !== null && plan.id !== undefined ? String(plan.id) : `${plan.ticker}-${plan.computed_at}`;
                  const isExpanded = expandedPlanRows[planKey] ?? false;
                  const entryRange = formatPriceRange(plan.entry_price_low, plan.entry_price_high);
                  const stopLabel = plan.stop_loss !== null && plan.stop_loss !== undefined ? String(plan.stop_loss) : "—";
                  const takeLabel = plan.take_profit !== null && plan.take_profit !== undefined ? String(plan.take_profit) : "—";
                  return (
                    <Fragment key={planKey}>
                      <tr
                        id={plan.id !== null && plan.id !== undefined ? `recommendation-plan-row-${plan.id}` : undefined}
                        className={`recommendation-plan-row${isExpanded ? " is-expanded" : ""}${focusedPlanId && plan.id !== null && String(plan.id) === focusedPlanId ? " is-highlighted" : ""}`}
                      >
                        <td>{formatDate(plan.computed_at)}</td>
                        <td>
                          <div className="cluster">
                            <a href={yahooFinanceUrl(plan.ticker)} className="badge badge-info badge-link" target="_blank" rel="noreferrer noopener">{plan.ticker}</a>
                                                        <Badge tone={plan.warnings.length > 0 ? "warning" : "ok"}>{plan.status}</Badge>
                          </div>
                          <div className="helper-text top-gap-small">horizon {plan.horizon} · setup {setupFamily}</div>
                        </td>
                        <td>
                          <Badge tone={actionTone(plan.action)}>{plan.action}</Badge>
                          <div className="helper-text top-gap-small">{actionReason}</div>
                        </td>
                        <td>
                          <ScoreBadge label="Confidence" value={`${plan.confidence_percent.toFixed(1)}%`} tone="info" />
                          <div className="helper-text top-gap-small">raw {rawConfidence !== null ? `${rawConfidence.toFixed(1)}%` : "—"} · calibrated {calibratedConfidence !== null ? `${calibratedConfidence.toFixed(1)}%` : "—"}</div>
                        </td>
                        <td>
                          <div className="cluster">
                            <ScoreBadge label="Entry" value={entryRange} tone="info" />
                            <ScoreBadge label="Stop" value={stopLabel} tone="warning" />
                            <ScoreBadge label="Take" value={takeLabel} tone="ok" />
                          </div>
                        </td>
                        <td>
                          <Badge tone={biasTone(transmissionBias)}>{transmissionBiasLabel}</Badge>
                          <div className="helper-text top-gap-small">alignment {transmissionAlignment !== null ? `${transmissionAlignment.toFixed(1)}%` : "—"} · window {expectedWindow}</div>
                        </td>
                        <td>
                          {plan.latest_outcome ? (
                            <>
                              <div className="cluster">
                                <Badge tone={plan.latest_outcome.outcome === "win" ? "ok" : plan.latest_outcome.outcome === "loss" ? "danger" : "neutral"}>{plan.latest_outcome.outcome}</Badge>
                                <span className="helper-text">{plan.latest_outcome.status}</span>
                              </div>
                              <div className="helper-text top-gap-small">1d {plan.latest_outcome.horizon_return_1d ?? "—"}% · 5d {plan.latest_outcome.horizon_return_5d ?? "—"}%</div>
                            </>
                          ) : (
                            <div className="helper-text">No outcome stored yet.</div>
                          )}
                        </td>
                        <td className="recommendation-plan-thesis-col">
                          <div className="recommendation-plan-thesis-preview" title={plan.thesis_summary || "No thesis stored."}>
                            {truncateText(plan.thesis_summary || "No thesis stored.", 180)}
                          </div>
                        </td>
                        <td>{plan.run_id ? <Link to={`/runs/${plan.run_id}`}>#{plan.run_id}</Link> : "—"}</td>
                        <td>
                          <div className="cluster">
                            <button
                              type="button"
                              className="icon-button"
                              onClick={() => togglePlanRow(planKey)}
                              aria-expanded={isExpanded}
                              aria-label={isExpanded ? "Hide details" : "Show details"}
                              title={isExpanded ? "Hide details" : "Show details"}
                            >
                              {isExpanded ? "▴" : "▾"}
                            </button>
                            {plan.id ? (
                              <button
                                type="button"
                                className="icon-button icon-button-primary"
                                disabled={evaluatingPlanId === plan.id}
                                onClick={() => void queueEvaluation(plan.id ?? undefined)}
                                aria-label={evaluatingPlanId === plan.id ? "Queueing plan evaluation" : "Evaluate this plan"}
                                title={evaluatingPlanId === plan.id ? "Queueing plan evaluation" : "Evaluate this plan"}
                              >
                                ↻
                              </button>
                            ) : null}
                          </div>
                        </td>
                      </tr>
                      {isExpanded ? (
                        <tr className="recommendation-plan-expanded-row">
                          <td colSpan={10}>
                            <div className="recommendation-plan-expanded-panel">
                              <div className="cluster top-gap-small">
                                </div>
                              <div className="summary-grid recommendation-plan-compact-grid">
                                <div className="summary-item"><span className="summary-label">Action reason</span><span className="summary-value">{actionReason}</span></div>
                                <div className="summary-item"><span className="summary-label">Confidence gate</span><span className="summary-value">{effectiveThreshold !== null ? `${effectiveThreshold.toFixed(1)}%` : "—"}</span></div>
                                <div className="summary-item"><span className="summary-label">Calibration</span><span className="summary-value">{calibrationReviewStatus}</span></div>
                                <div className="summary-item"><span className="summary-label">Adjust</span><span className="summary-value">{confidenceAdjustment !== null ? `${confidenceAdjustment > 0 ? "+" : ""}${confidenceAdjustment.toFixed(1)} pts` : "—"}</span></div>
                                <div className="summary-item"><span className="summary-label">Entry style</span><span className="summary-value">{entryStyle}</span></div>
                                <div className="summary-item"><span className="summary-label">Stop style</span><span className="summary-value">{stopStyle}</span></div>
                                <div className="summary-item"><span className="summary-label">Take style</span><span className="summary-value">{targetStyle}</span></div>
                                <div className="summary-item"><span className="summary-label">Timing</span><span className="summary-value">{timingExpectation}</span></div>
                                <div className="summary-item"><span className="summary-label">Macro / industry</span><span className="summary-value">{macroContext ? contextProvenanceLabel(macroContext) : "—"} · {industryContext ? contextProvenanceLabel(industryContext) : "—"}</span></div>
                              </div>
                              <div className="recommendation-plan-detail-stack top-gap-small">
                                <div className="recommendation-plan-detail-block">
                                  <div className="recommendation-plan-detail-label">Action detail</div>
                                  <div className="recommendation-plan-detail-value">{actionReasonDetail}</div>
                                </div>
                                <div className="recommendation-plan-detail-block">
                                  <div className="recommendation-plan-detail-label">Calibration reasons</div>
                                  <div className="recommendation-plan-detail-value">{joinSummary(calibrationReasons, "—")}</div>
                                </div>
                                <div className="recommendation-plan-detail-block">
                                  <div className="recommendation-plan-detail-label">Transmission</div>
                                  <div className="recommendation-plan-detail-value">drivers {joinSummary(primaryDrivers)} · industry {joinSummary(industryExposureChannels)} · ticker {joinSummary(tickerExposureChannels)}</div>
                                </div>
                                <div className="recommendation-plan-detail-block">
                                  <div className="recommendation-plan-detail-label">Relationships</div>
                                  <div className="recommendation-plan-detail-value">{relationshipSummary(plan)}</div>
                                </div>
                                <div className="recommendation-plan-detail-block">
                                  <div className="recommendation-plan-detail-label">Conflicts</div>
                                  <div className="recommendation-plan-detail-value">{joinSummary(conflictFlags)}</div>
                                </div>
                                <div className="recommendation-plan-detail-block">
                                  <div className="recommendation-plan-detail-label">Tags</div>
                                  <div className="recommendation-plan-detail-value">{joinSummary(transmissionTags)}</div>
                                </div>
                                <div className="recommendation-plan-detail-block">
                                  <div className="recommendation-plan-detail-label">Outcome bias / regime</div>
                                  <div className="recommendation-plan-detail-value">{plan.latest_outcome ? `${detailLabel(plan.latest_outcome.transmission_bias_detail, plan.latest_outcome.transmission_bias_label ?? plan.latest_outcome.transmission_bias, false) ?? "—"} · ${detailLabel(plan.latest_outcome.context_regime_detail, plan.latest_outcome.context_regime_label ?? plan.latest_outcome.context_regime, false) ?? "—"}` : "—"}</div>
                                </div>
                                <div className="recommendation-plan-detail-block">
                                  <div className="recommendation-plan-detail-label">Invalidation</div>
                                  <div className="recommendation-plan-detail-value">{invalidationSummary}</div>
                                </div>
                                <div className="recommendation-plan-detail-block">
                                  <div className="recommendation-plan-detail-label">Review focus</div>
                                  <div className="recommendation-plan-detail-value">{joinSummary(evaluationFocus, "—")}</div>
                                </div>
                                {contextSummaryError(macroContext) ? <div className="helper-text">macro fallback: {contextSummaryError(macroContext)}</div> : null}
                                {contextSummaryError(industryContext) ? <div className="helper-text">industry fallback: {contextSummaryError(industryContext)}</div> : null}
                                <div className="recommendation-plan-detail-block">
                                  <div className="recommendation-plan-detail-label">Thesis</div>
                                  <div className="recommendation-plan-detail-value">{plan.thesis_summary || "No thesis stored."}</div>
                                </div>
                                {plan.rationale_summary ? (
                                  <div className="recommendation-plan-detail-block">
                                    <div className="recommendation-plan-detail-label">Rationale</div>
                                    <div className="recommendation-plan-detail-value">{plan.rationale_summary}</div>
                                  </div>
                                ) : null}
                              </div>
                            </div>
                          </td>
                        </tr>
                      ) : null}
                    </Fragment>
                  );
                })}
              </tbody>
              </table>
            </div>
          </div>
          </>
        ) : null}
      </Card>
      ) : null}
    </>
  );
}
