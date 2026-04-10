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

function sampleTone(status: string): "ok" | "warning" | "neutral" {
  if (status === "strong" || status === "usable") {
    return "ok";
  }
  if (status === "limited") {
    return "warning";
  }
  return "neutral";
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

function HelpLabel({ label, tooltip, to }: { label: string; tooltip: string; to: string }) {
  return (
    <span className="help-label">
      <span>{label}</span>
      <HelpHint tooltip={tooltip} to={to} ariaLabel={`${label}. ${tooltip}. Open documentation.`} />
    </span>
  );
}

function CalibrationBucketTable({ title, buckets }: { title: string; buckets: RecommendationCalibrationSummary["by_confidence_bucket"] }) {
  return (
    <div className="top-gap">
      <SectionTitle title={title} actions={<HelpHint tooltip="Grouped calibration view for this slice: sample size, win rate, and average 5-day return." to={recommendationPlansDoc("calibration-fields")} />} />
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Slice</th>
              <th>Total</th>
              <th>Resolved</th>
              <th>Sample</th>
              <th>Win rate</th>
              <th>Avg 5d</th>
            </tr>
          </thead>
          <tbody>
            {buckets.map((bucket) => (
              <tr key={bucket.key}>
                <td>{bucket.label}</td>
                <td>{bucket.total_count}</td>
                <td>{bucket.resolved_count}</td>
                <td>
                  <Badge tone={sampleTone(bucket.sample_status)}>{bucket.sample_status}</Badge>
                  <div className="helper-text top-gap-small">min {bucket.min_required_resolved_count}</div>
                </td>
                <td>{bucket.win_rate_percent ?? "—"}%</td>
                <td>{bucket.average_return_5d ?? "—"}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SetupFamilySliceTable({
  title,
  buckets,
}: {
  title: string;
  buckets: RecommendationCalibrationSummary["by_confidence_bucket"];
}) {
  return (
    <div className="table-wrap top-gap-small">
      <table>
        <thead>
          <tr>
            <th>{title}</th>
            <th>Total</th>
            <th>Resolved</th>
            <th>Sample</th>
            <th>Win rate</th>
            <th>Avg 5d</th>
          </tr>
        </thead>
        <tbody>
          {buckets.length > 0 ? (
            buckets.map((bucket) => (
              <tr key={bucket.key}>
                <td>{bucket.label}</td>
                <td>{bucket.total_count}</td>
                <td>{bucket.resolved_count}</td>
                <td>
                  <Badge tone={sampleTone(bucket.sample_status)}>{bucket.sample_status}</Badge>
                  <div className="helper-text top-gap-small">min {bucket.min_required_resolved_count}</div>
                </td>
                <td>{bucket.win_rate_percent ?? "—"}%</td>
                <td>{bucket.average_return_5d ?? "—"}%</td>
              </tr>
            ))
          ) : (
            <tr>
              <td colSpan={6} className="helper-text">No slices stored yet.</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

export function RecommendationPlansPage() {
  const [searchParams, setSearchParams] = useSearchParams({ limit: "100", page: "1" });
  const focusedPlanId = searchParams.get("plan_id");
  const [plansResponse, setPlansResponse] = useState<RecommendationPlanListResponse | null>(null);
  const [planStats, setPlanStats] = useState<RecommendationPlanStats | null>(null);
  const [statsWindow, setStatsWindow] = useState<"all" | "day" | "week" | "month" | "year">("all");
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
  const [reviewSection, setReviewSection] = useState<"overview" | "calibration" | "baselines" | "evidence" | "families">("overview");
  const [analyticsExpanded, setAnalyticsExpanded] = useState(false);
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
        const summaryParams = new URLSearchParams({ limit: "500" });
        const runId = searchParams.get("run_id");
        const ticker = searchParams.get("ticker");
        const setupFamily = searchParams.get("setup_family");
        const planId = searchParams.get("plan_id");
        const resolved = searchParams.get("resolved");
        const outcome = searchParams.get("outcome");
        const window = statsWindow;
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
        statsParams.set("window", window);
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
  }, [searchParams, statsWindow]);

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
        kicker="Recommendation workflow"
        title="Recommendation plans"
        subtitle="Use this page as the main decision-review surface: filter plans, inspect calibrated confidence, compare cohorts, and queue evaluation runs without digging through raw run payloads."
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
          subtitle="These headline stats are computed across all recommendation plans, independent of the current list filters."
        />
        <div className="top-gap-small">
          <SegmentedTabs
            value={statsWindow}
            onChange={(value) => setStatsWindow(value as "all" | "day" | "week" | "month" | "year")}
            options={[
              { value: "all", label: "All" },
              { value: "day", label: "Day" },
              { value: "week", label: "Week" },
              { value: "month", label: "Month" },
              { value: "year", label: "Year" },
            ]}
          />
        </div>
        <section className="metrics-grid top-gap-small">
          <StatCard label="Total plans" value={planStats?.total_plans ?? "—"} helper={`All recommendations · ${planStats?.window ?? "all"}`} />
          <StatCard label="Open plans" value={planStats?.open_plans ?? "—"} helper="Open plans across all recommendations" />
          <StatCard label="Expired plans" value={planStats?.expired_plans ?? "—"} helper="Terminal expired outcomes across all recommendations" />
          <StatCard label="Win rate" value={planStats?.win_rate_percent !== null && planStats?.win_rate_percent !== undefined ? `${planStats.win_rate_percent}%` : "—"} helper={`Excludes open and expired plans · ${planStats?.window ?? "all"}`} />
          <StatCard label="Evidence concentration" value={evidenceConcentration ? (evidenceConcentration.ready_for_expansion ? "Ready" : "Focused") : "—"} helper="This card still reflects the current filtered review cohort" />
        </section>
      </Card>

      <Card className="sticky-toolbar">
        <SectionTitle kicker="Filters" title="Find recommendation plans" actions={<HelpHint tooltip="Use filters to narrow the recommendation-plan review set before comparing calibration, baselines, and evidence." to={recommendationPlansDoc("filter-bar")} />} />
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

      <Card className="top-gap">
        <SectionTitle
          kicker="Review workspace"
          title="Analytics and cohort review"
          subtitle="Advanced review surfaces stay collapsed by default so the page remains plan-list first."
          actions={<HelpHint tooltip="Each tab answers a different operator question: trust, comparison, evidence concentration, or family-specific behavior." to={recommendationPlansDoc("review-workspace-tabs")} />}
        />
        <div className="cluster top-gap-small">
          <button type="button" className="button-secondary" onClick={() => setAnalyticsExpanded((current) => !current)}>
            {analyticsExpanded ? "Hide analytics" : "Show analytics"}
          </button>
        </div>
        {analyticsExpanded ? (
          <div className="top-gap-small">
            <SegmentedTabs
              value={reviewSection}
              onChange={setReviewSection}
              options={[
                { value: "overview", label: "Overview" },
                { value: "calibration", label: "Calibration" },
                { value: "baselines", label: "Baselines" },
                { value: "evidence", label: "Evidence" },
                { value: "families", label: "Setup families" },
              ]}
            />
          </div>
        ) : null}
      </Card>

      {analyticsExpanded && reviewSection === "overview" ? (
        <Card className="top-gap">
          <SectionTitle title="Review overview" actions={<HelpHint tooltip="High-level posture for recommendation plans: calibration trust, baseline comparisons, and where evidence is strongest or weakest." to={recommendationPlansDoc("recommendation-plans")} />} />
          <div className="insight-grid top-gap-small">
            <div className="data-card">
              <div className="data-card-header">
                <div>
                  <h3 className="data-card-title"><HelpLabel label="Calibration posture" tooltip="Shows whether stored outcomes are sufficient to trust current confidence and threshold behavior." to={glossaryDoc("calibration")} /></h3>
                </div>
                <Badge tone={planStats && planStats.scored_outcomes >= 10 ? "ok" : "warning"}>{planStats?.scored_outcomes ?? 0} win/loss scored</Badge>
              </div>
              <div className="data-points">
                <div className="data-point"><span className="data-point-label">overall win rate</span><span className="data-point-value">{calibration?.overall_win_rate_percent ?? "—"}%</span></div>
                <div className="data-point"><span className="data-point-label">wins / losses</span><span className="data-point-value">{calibration ? `${calibration.win_outcomes} / ${calibration.loss_outcomes}` : "—"}</span></div>
                <div className="data-point"><span className="data-point-label">expired / open</span><span className="data-point-value">{planStats ? `${planStats.expired_plans} / ${planStats.open_plans}` : "—"}</span></div>
              </div>
            </div>
            <div className="data-card">
              <div className="data-card-header">
                <div>
                  <h3 className="data-card-title"><HelpLabel label="Baseline reality check" tooltip="Compares actual recommendation-plan outcomes against simpler cohorts to see whether added complexity is helping." to={glossaryDoc("baseline-comparison")} /></h3>
                </div>
                <Badge tone="info">{baselines?.total_trade_plans_reviewed ?? 0} trades</Badge>
              </div>
              <div className="data-points">
                <div className="data-point"><span className="data-point-label">actual actionable</span><span className="data-point-value">{baselines?.comparisons.find((item) => item.key === "actual_actionable")?.win_rate_percent ?? "—"}%</span></div>
                <div className="data-point"><span className="data-point-label">high confidence only</span><span className="data-point-value">{baselines?.comparisons.find((item) => item.key === "high_confidence_only")?.win_rate_percent ?? "—"}%</span></div>
                <div className="data-point"><span className="data-point-label">cheap-scan leaders</span><span className="data-point-value">{baselines?.comparisons.find((item) => item.key === "cheap_scan_attention_leaders")?.win_rate_percent ?? "—"}%</span></div>
              </div>
            </div>
            <div className="data-card">
              <div className="data-card-header">
                <div>
                  <h3 className="data-card-title"><HelpLabel label="Evidence concentration" tooltip="Shows where measured edge is concentrated so operators know whether to stay selective or broaden usage." to={glossaryDoc("evidence-concentration")} /></h3>
                </div>
                <Badge tone={evidenceConcentration?.ready_for_expansion ? "ok" : "warning"}>{evidenceConcentration?.ready_for_expansion ? "ready" : "focus"}</Badge>
              </div>
              <div className="data-points">
                <div className="data-point"><span className="data-point-label">overall avg 5d</span><span className="data-point-value">{evidenceConcentration?.overall_average_return_5d ?? "—"}%</span></div>
                <div className="data-point"><span className="data-point-label">best cohort</span><span className="data-point-value">{evidenceConcentration?.strongest_positive_cohorts[0]?.label ?? "—"}</span></div>
                <div className="data-point"><span className="data-point-label">weakest cohort</span><span className="data-point-value">{evidenceConcentration?.weakest_cohorts[0]?.label ?? "—"}</span></div>
              </div>
              <div className="helper-text top-gap-small">{evidenceConcentration?.focus_message ?? "Loading evidence concentration…"}</div>
            </div>
          </div>
        </Card>
      ) : null}

      {analyticsExpanded && reviewSection === "calibration" ? (
      <Card className="top-gap">
        <SectionTitle
          title="Calibration snapshot"
          subtitle={calibration ? `Win/loss scored ${calibration.resolved_outcomes} of ${calibration.total_outcomes} stored outcome(s)` : undefined}
          actions={<HelpHint tooltip="Review how confidence buckets and slices have actually behaved after outcomes resolved." to={recommendationPlansDoc("calibration-fields")} />}
        />
        {!calibration && !error ? <LoadingState message="Loading calibration summary…" /> : null}
        {calibration ? (
          <>
            <div className="stats-grid top-gap-small">
              <Card><strong>{calibration.overall_win_rate_percent ?? "—"}%</strong><div className="helper-text">overall win/loss win rate</div></Card>
              <Card><strong>{calibration.win_outcomes}</strong><div className="helper-text">wins</div></Card>
              <Card><strong>{calibration.loss_outcomes}</strong><div className="helper-text">losses</div></Card>
              <Card><strong>{calibration.no_action_outcomes}</strong><div className="helper-text">no_action outcomes</div></Card>
            </div>
            <CalibrationBucketTable title="By confidence bucket" buckets={calibration.by_confidence_bucket} />
            <CalibrationBucketTable title="By setup family" buckets={calibration.by_setup_family} />
            <CalibrationBucketTable title="By horizon" buckets={calibration.by_horizon} />
            <CalibrationBucketTable title="By transmission bias" buckets={calibration.by_transmission_bias} />
            <CalibrationBucketTable title="By context regime" buckets={calibration.by_context_regime} />
            <CalibrationBucketTable title="By horizon + setup family" buckets={calibration.by_horizon_setup_family} />
          </>
        ) : null}
      </Card>
      ) : null}

      {analyticsExpanded && reviewSection === "baselines" ? (
      <Card className="top-gap">
        <SectionTitle
          title="Baseline comparisons"
          subtitle={baselines ? `Reviewed ${baselines.total_trade_plans_reviewed} trade plan(s) across ${baselines.total_plans_reviewed} total plan(s)` : undefined}
          actions={<HelpHint tooltip="Compare live plan behavior against simpler heuristic cohorts before trusting the full workflow." to={glossaryDoc("baseline-comparison")} />}
        />
        {!baselines && !error ? <LoadingState message="Loading baseline comparisons…" /> : null}
        {baselines ? (
          <>
            <div className="table-wrap top-gap-small">
              <table>
                <thead>
                  <tr>
                    <th>Baseline</th>
                    <th>Trade plans</th>
                    <th>Resolved</th>
                    <th>Win rate</th>
                    <th>Avg 5d</th>
                    <th>Avg confidence</th>
                  </tr>
                </thead>
                <tbody>
                  {baselines.comparisons.map((item) => (
                    <tr key={item.key}>
                      <td>
                        <div>{item.label}</div>
                        {item.description ? <div className="helper-text top-gap-small">{item.description}</div> : null}
                      </td>
                      <td>{item.trade_plan_count}</td>
                      <td>{item.resolved_trade_count}</td>
                      <td>{item.win_rate_percent ?? "—"}%</td>
                      <td>{item.average_return_5d ?? "—"}%</td>
                      <td>{item.average_confidence_percent ?? "—"}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <SectionTitle
              title="Setup-family cohorts"
              actions={<HelpHint tooltip="Family-specific cohorts help show whether one setup type is carrying most of the measured performance." to={glossaryDoc("setup-family")} />}
            />
            <div className="table-wrap top-gap-small">
              <table>
                <thead>
                  <tr>
                    <th>Family cohort</th>
                    <th>Trade plans</th>
                    <th>Open</th>
                    <th>Resolved</th>
                    <th>Win rate</th>
                    <th>Avg 5d</th>
                    <th>Avg confidence</th>
                  </tr>
                </thead>
                <tbody>
                  {baselines.family_cohorts.map((item) => (
                    <tr key={item.key}>
                      <td>
                        <div>{item.label}</div>
                        {item.description ? <div className="helper-text top-gap-small">{item.description}</div> : null}
                      </td>
                      <td>{item.trade_plan_count}</td>
                      <td>{item.open_trade_count}</td>
                      <td>{item.resolved_trade_count}</td>
                      <td>{item.win_rate_percent ?? "—"}%</td>
                      <td>{item.average_return_5d ?? "—"}%</td>
                      <td>{item.average_confidence_percent ?? "—"}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : null}
      </Card>
      ) : null}

      {analyticsExpanded && reviewSection === "evidence" ? (
      <Card className="top-gap">
        <SectionTitle
          title="Evidence concentration"
          subtitle={evidenceConcentration ? `Win/loss scored ${evidenceConcentration.resolved_outcomes_reviewed} of ${evidenceConcentration.total_outcomes_reviewed} reviewed outcomes` : undefined}
          actions={<HelpHint tooltip="Shows where measured results are concentrated so operators can see which cohorts deserve the most trust." to={glossaryDoc("evidence-concentration")} />}
        />
        {!evidenceConcentration && !error ? <LoadingState message="Loading evidence concentration…" /> : null}
        {evidenceConcentration ? (
          <>
            <div className="stats-grid top-gap-small">
              <Card><strong>{evidenceConcentration.overall_win_rate_percent ?? "—"}%</strong><div className="helper-text">overall win/loss win rate</div></Card>
              <Card><strong>{evidenceConcentration.overall_average_return_5d ?? "—"}%</strong><div className="helper-text">overall avg 5d return</div></Card>
              <Card><strong>{evidenceConcentration.ready_for_expansion ? "yes" : "not yet"}</strong><div className="helper-text">ready for broader concentration</div></Card>
            </div>
            <div className="helper-text top-gap-small">{evidenceConcentration.focus_message}</div>
            <SectionTitle title="Strongest positive cohorts" actions={<HelpHint tooltip="These are the best-performing measured cohorts versus the overall review set." to={glossaryDoc("evidence-concentration")} />} />
            <div className="table-wrap top-gap-small">
              <table>
                <thead>
                  <tr>
                    <th>Cohort</th>
                    <th>Sample</th>
                    <th>Win rate edge</th>
                    <th>5d edge</th>
                    <th>Score</th>
                    <th>Interpretation</th>
                  </tr>
                </thead>
                <tbody>
                  {evidenceConcentration.strongest_positive_cohorts.map((item) => (
                    <tr key={`${item.slice_name}-${item.key}`}>
                      <td>{item.label}<div className="helper-text top-gap-small">{item.slice_label || item.slice_name}</div></td>
                      <td><Badge tone={sampleTone(item.sample_status)}>{item.sample_status}</Badge><div className="helper-text top-gap-small">n={item.resolved_count} / min {item.min_required_resolved_count}</div></td>
                      <td>{item.edge_vs_overall_win_rate_percent ?? "—"} pts</td>
                      <td>{item.edge_vs_overall_return_5d ?? "—"}%</td>
                      <td>{item.concentration_score}</td>
                      <td>{item.interpretation}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <SectionTitle title="Weakest cohorts" actions={<HelpHint tooltip="These cohorts have the weakest measured results and often deserve stricter skepticism or gating." to={glossaryDoc("evidence-concentration")} />} />
            <div className="table-wrap top-gap-small">
              <table>
                <thead>
                  <tr>
                    <th>Cohort</th>
                    <th>Sample</th>
                    <th>Win rate edge</th>
                    <th>5d edge</th>
                    <th>Score</th>
                    <th>Interpretation</th>
                  </tr>
                </thead>
                <tbody>
                  {evidenceConcentration.weakest_cohorts.map((item) => (
                    <tr key={`${item.slice_name}-${item.key}`}>
                      <td>{item.label}<div className="helper-text top-gap-small">{item.slice_label || item.slice_name}</div></td>
                      <td><Badge tone={sampleTone(item.sample_status)}>{item.sample_status}</Badge><div className="helper-text top-gap-small">n={item.resolved_count} / min {item.min_required_resolved_count}</div></td>
                      <td>{item.edge_vs_overall_win_rate_percent ?? "—"} pts</td>
                      <td>{item.edge_vs_overall_return_5d ?? "—"}%</td>
                      <td>{item.concentration_score}</td>
                      <td>{item.interpretation}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : null}
      </Card>
      ) : null}

      {analyticsExpanded && reviewSection === "families" ? (
      <Card className="top-gap">
        <SectionTitle
          title="Setup-family evaluation review"
          subtitle={familyReview ? `Built from ${familyReview.total_outcomes_reviewed} stored outcome(s) across the current filters` : undefined}
          actions={<HelpHint tooltip="Breaks evaluation down by setup family so you can see whether breakout, continuation, catalyst, or other families behave differently." to={glossaryDoc("setup-family")} />}
        />
        {!familyReview && !error ? <LoadingState message="Loading setup-family review…" /> : null}
        {familyReview ? (
          <div className="top-gap-small">
            {familyReview.families.map((family) => (
              <Card key={family.family} className="top-gap-small">
                <SectionTitle
                  title={family.label}
                  subtitle={`win/loss scored ${family.resolved_outcomes} · open ${family.open_outcomes} · wins ${family.win_outcomes} · losses ${family.loss_outcomes}`}
                />
                <div className="stats-grid top-gap-small">
                  <Card><strong>{family.overall_win_rate_percent ?? "—"}%</strong><div className="helper-text">win/loss win rate</div></Card>
                  <Card><strong>{family.average_return_5d ?? "—"}%</strong><div className="helper-text">avg 5d return</div></Card>
                  <Card><strong>{family.average_mfe ?? "—"}%</strong><div className="helper-text">avg MFE</div></Card>
                  <Card><strong>{family.average_mae ?? "—"}%</strong><div className="helper-text">avg MAE</div></Card>
                </div>
                <SetupFamilySliceTable title="By horizon" buckets={family.by_horizon} />
                <SetupFamilySliceTable title="By transmission bias" buckets={family.by_transmission_bias} />
                <SetupFamilySliceTable title="By context regime" buckets={family.by_context_regime} />
              </Card>
            ))}
          </div>
        ) : null}
      </Card>
      ) : null}

      <Card className="top-gap">
        <SectionTitle title="Results" subtitle={plans ? `${planTotal} recommendation plan(s) · page ${currentPage} of ${pageCount}` : undefined} actions={<HelpHint tooltip="The main recommendation-plan table: review action, confidence, execution framing, transmission, outcomes, and thesis together." to={recommendationPlansDoc("results-table")} />} />
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
    </>
  );
}
