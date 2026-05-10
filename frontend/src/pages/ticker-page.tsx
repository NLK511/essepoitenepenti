import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { getJson } from "../api";
import { Badge, Card, DisclosureCard, EmptyState, ErrorState, LoadingState, PageHeader, SectionTitle, SegmentedTabs, StatCard } from "../components/ui";
import { ScoreBadge } from "../components/decision-surface";
import { RecommendationPlanEvaluationSummary } from "../components/recommendation-plan-evaluation";
import {
  matchedRelationshipsFromPlan,
  relationshipSummary,
  storedRelationshipEdgesFromPlan,
  TickerRelationshipReadthroughCard,
} from "../components/ticker-relationship-readthrough";
import type { TickerAnalysisPage as TickerAnalysisPageData, TickerChartPoint, TickerChartSeries } from "../types";
import { detailLabel, formatDate, normalizeReviewWindow, REVIEW_WINDOW_OPTIONS } from "../utils";

type WindowValue = (typeof REVIEW_WINDOW_OPTIONS)[number]["value"];

const CHART_ZOOM_MIN = 0.6;
const CHART_ZOOM_MAX = 3;
const CHART_ZOOM_STEP = 1.12;

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function formatPrice(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "—";
  }
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(value);
}

function formatDateTime(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short" }).format(parsed);
}

function TickerPriceChart(props: {
  series: TickerChartSeries;
  selectedPlanIds: number[];
  fitToScreen: boolean;
  onTogglePlan: (planId: number) => void;
  onSelectAll: () => void;
  onSelectNone: () => void;
}) {
  const bars = props.series.bars;
  const overlays = props.series.overlays;
  const chartScrollRef = useRef<HTMLDivElement | null>(null);
  const [zoomLevel, setZoomLevel] = useState(1);
  const [hoveredPoint, setHoveredPoint] = useState<{
    overlayLabel: string;
    pointLabel: string;
    kind: string;
    x: number;
    y: number;
    value: number;
    time: string;
    color: string;
  } | null>(null);

  useEffect(() => {
    setZoomLevel(1);
    setHoveredPoint(null);
  }, [props.series.ticker, props.series.timeframe]);

  useEffect(() => {
    const element = chartScrollRef.current;
    if (!element) {
      return;
    }
    const handleWheel = (event: WheelEvent) => {
      if (!event.ctrlKey) {
        return;
      }
      event.preventDefault();
      const factor = event.deltaY > 0 ? 1 / CHART_ZOOM_STEP : CHART_ZOOM_STEP;
      setZoomLevel((current) => clamp(current * factor, CHART_ZOOM_MIN, CHART_ZOOM_MAX));
    };
    element.addEventListener("wheel", handleWheel, { passive: false });
    return () => element.removeEventListener("wheel", handleWheel);
  }, []);

  if (bars.length === 0) {
    return <EmptyState message="No stored 1m bars are available for this ticker in the selected window." />;
  }

  const barTimestamps = bars.map((bar) => new Date(bar.bar_time).getTime()).filter((value) => Number.isFinite(value));
  const prices = [
    ...bars.flatMap((bar) => [bar.open_price, bar.high_price, bar.low_price, bar.close_price]),
    ...overlays.flatMap((overlay) => overlay.points.map((point) => point.y)),
  ].filter((value) => Number.isFinite(value));

  const minPrice = Math.min(...prices);
  const maxPrice = Math.max(...prices);
  const priceRange = Math.max(maxPrice - minPrice, 1e-6);

  const height = 420;
  const margin = { top: 24, right: 20, bottom: 36, left: 70 };
  const barSpacing = 12 * zoomLevel;
  const chartWidth = Math.max(420, margin.left + margin.right + Math.max(bars.length - 1, 1) * barSpacing + 40);
  const plotWidth = chartWidth - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const maxBarIndex = Math.max(bars.length - 1, 1);

  function xForBarIndex(index: number) {
    return margin.left + (index / maxBarIndex) * plotWidth;
  }

  function nearestBarIndex(time: number) {
    if (barTimestamps.length === 0) {
      return 0;
    }
    let low = 0;
    let high = barTimestamps.length - 1;
    while (low < high) {
      const mid = Math.floor((low + high) / 2);
      if (barTimestamps[mid] < time) {
        low = mid + 1;
      } else {
        high = mid;
      }
    }
    if (low === 0) {
      return 0;
    }
    const prev = low - 1;
    return Math.abs(barTimestamps[low] - time) < Math.abs(barTimestamps[prev] - time) ? low : prev;
  }

  function xFor(value: string | Date) {
    const time = value instanceof Date ? value.getTime() : new Date(value).getTime();
    return xForBarIndex(nearestBarIndex(time));
  }

  function yFor(value: number) {
    return margin.top + (1 - (value - minPrice) / priceRange) * plotHeight;
  }

  const selected = new Set(props.selectedPlanIds);
  const visibleOverlays = overlays.filter((overlay) => selected.has(overlay.plan_id));
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((ratio) => minPrice + (1 - ratio) * priceRange);
  const xTickCandidates = [0, Math.floor((bars.length - 1) / 2), bars.length - 1].filter((value, index, arr) => arr.indexOf(value) === index);
  const xTickIndexes: number[] = [];
  for (const index of xTickCandidates) {
    const x = xFor(bars[index].bar_time);
    const previousX = xTickIndexes.length > 0 ? xFor(bars[xTickIndexes[xTickIndexes.length - 1]].bar_time) : null;
    if (previousX === null || Math.abs(x - previousX) >= 180 || index === bars.length - 1) {
      xTickIndexes.push(index);
    }
  }
  if (xTickIndexes.length > 2) {
    xTickIndexes.splice(1, xTickIndexes.length - 2);
  }

  return (
    <div className="data-stack top-gap-small">
      <div className="cluster">
        <Badge tone="info">{props.series.ticker}</Badge>
        <Badge>{props.series.timeframe}</Badge>
        <Badge>{bars.length} bars</Badge>
        <Badge>{visibleOverlays.length}/{overlays.length} overlays</Badge>
        <button type="button" className="button-subtle" onClick={props.onSelectAll}>☑ All</button>
        <button type="button" className="button-subtle" onClick={props.onSelectNone}>☐ None</button>
      </div>
      <div className="chart-scroll-shell" ref={chartScrollRef}>
        <svg
          viewBox={`0 0 ${chartWidth} ${height}`}
          width={props.fitToScreen ? "100%" : chartWidth}
          height={height}
          className="ticker-price-chart"
          role="img"
          aria-label="Ticker price chart with actionable plan overlays"
          preserveAspectRatio={props.fitToScreen ? "xMidYMid meet" : "none"}
        >
          <title>{`${props.series.ticker} ${props.series.timeframe} chart`}</title>
          {yTicks.map((value, index) => {
            const y = yFor(value);
            return <line key={`grid-y-${index}`} x1={margin.left} x2={chartWidth - margin.right} y1={y} y2={y} className="chart-grid-line" />;
          })}
          {xTickIndexes.map((index) => {
            const x = xForBarIndex(index);
            return <line key={`grid-x-${index}`} x1={x} x2={x} y1={margin.top} y2={height - margin.bottom} className="chart-grid-line chart-grid-line-vertical" />;
          })}
          {bars.map((bar, index) => {
            const x = xForBarIndex(index);
            const highY = yFor(bar.high_price);
            const lowY = yFor(bar.low_price);
            const openY = yFor(bar.open_price);
            const closeY = yFor(bar.close_price);
            const bodyTop = Math.min(openY, closeY);
            const bodyHeight = Math.max(Math.abs(closeY - openY), 1.5);
            const bodyColor = bar.close_price >= bar.open_price ? "#16a34a" : "#dc2626";
            return (
              <g key={`${bar.ticker}-${bar.bar_time}-${index}`}>
                <line x1={x} x2={x} y1={highY} y2={lowY} className="chart-bar-wick" stroke={bodyColor} />
                <rect x={x - 1.8} y={bodyTop} width={3.6} height={bodyHeight} fill={bodyColor} opacity={0.85}>
                  <title>{`${formatDate(bar.bar_time)} · O ${formatPrice(bar.open_price)} H ${formatPrice(bar.high_price)} L ${formatPrice(bar.low_price)} C ${formatPrice(bar.close_price)}`}</title>
                </rect>
              </g>
            );
          })}
          {visibleOverlays.map((overlay) => (
            <g key={overlay.plan_id}>
              {overlay.points.map((point: TickerChartPoint, index) => {
                const x = xFor(point.x);
                const y = yFor(point.y);
                return (
                  <g key={`${overlay.plan_id}-${point.kind}-${index}`}>
                    <circle
                      cx={x}
                      cy={y}
                      r={4.2}
                      fill={point.color || overlay.color}
                      stroke="#0f172a"
                      strokeWidth="1.2"
                      onMouseEnter={() => setHoveredPoint({
                        overlayLabel: overlay.label,
                        pointLabel: point.label,
                        kind: point.kind,
                        x,
                        y,
                        value: point.y,
                        time: point.x,
                        color: point.color || overlay.color,
                      })}
                      onMouseMove={() => setHoveredPoint({
                        overlayLabel: overlay.label,
                        pointLabel: point.label,
                        kind: point.kind,
                        x,
                        y,
                        value: point.y,
                        time: point.x,
                        color: point.color || overlay.color,
                      })}
                      onMouseLeave={() => setHoveredPoint(null)}
                    />
                    {index === 0 ? <text x={x + 6} y={y - 6} className="chart-overlay-label">{overlay.action} #{overlay.plan_id}</text> : null}
                  </g>
                );
              })}
            </g>
          ))}
          {hoveredPoint ? (() => {
            const tooltipWidth = 210;
            const tooltipHeight = 58;
            const tooltipX = clamp(hoveredPoint.x + 12, margin.left, chartWidth - margin.right - tooltipWidth);
            const tooltipY = clamp(hoveredPoint.y - tooltipHeight - 12, margin.top, height - margin.bottom - tooltipHeight);
            return (
              <g pointerEvents="none">
                <rect x={tooltipX} y={tooltipY} width={tooltipWidth} height={tooltipHeight} rx={10} ry={10} fill="rgba(10, 18, 16, 0.96)" stroke="rgba(214, 186, 120, 0.35)" />
                <text x={tooltipX + 10} y={tooltipY + 20} className="chart-tooltip-title">{hoveredPoint.overlayLabel}</text>
                <text x={tooltipX + 10} y={tooltipY + 35} className="chart-tooltip-body">{formatDateTime(hoveredPoint.time)}</text>
                <text x={tooltipX + 10} y={tooltipY + 50} className="chart-tooltip-body">Price {formatPrice(hoveredPoint.value)} · {hoveredPoint.kind}</text>
              </g>
            );
          })() : null}
          <line x1={margin.left} x2={chartWidth - margin.right} y1={height - margin.bottom} y2={height - margin.bottom} className="chart-axis" />
          <line x1={margin.left} x2={margin.left} y1={margin.top} y2={height - margin.bottom} className="chart-axis" />
          {yTicks.map((value, index) => (
            <g key={`y-label-${index}`}>
              <text x={margin.left - 10} y={yFor(value) + 4} className="chart-axis-label chart-axis-label-left">{formatPrice(value)}</text>
            </g>
          ))}
          {xTickIndexes.map((index) => (
            <text key={`x-label-${index}`} x={xForBarIndex(index)} y={height - 10} className="chart-axis-label chart-axis-label-bottom">
              {new Date(bars[index].bar_time).toLocaleDateString()}
            </text>
          ))}
        </svg>
      </div>
      <div className="data-stack top-gap-small">
        {overlays.length === 0 ? <span className="helper-text">No actionable plan overlays are available for this ticker.</span> : null}
        <div className="cluster wrap">
          {overlays.map((overlay) => {
            const checked = selected.has(overlay.plan_id);
            return (
              <button
                key={overlay.plan_id}
                type="button"
                className={`plan-toggle ${checked ? "plan-toggle-selected" : ""}`}
                onClick={() => props.onTogglePlan(overlay.plan_id)}
                title={overlay.label}
              >
                <span className="plan-toggle-swatch" style={{ backgroundColor: overlay.color }} />
                <span>{overlay.action} #{overlay.plan_id}</span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

export function TickerPage() {
  const { ticker } = useParams<{ ticker: string }>();
  const [searchParams, setSearchParams] = useSearchParams({ window: "7d" });
  const [data, setData] = useState<TickerAnalysisPageData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [section, setSection] = useState<"overview" | "plans">("overview");
  const [selectedPlanIds, setSelectedPlanIds] = useState<number[]>([]);
  const [fitChartToScreen, setFitChartToScreen] = useState(false);
  const chartSectionRef = useRef<HTMLDivElement | null>(null);

  const selectedWindow = normalizeReviewWindow(searchParams.get("window"), "7d") as WindowValue;

  useEffect(() => {
    async function load() {
      if (!ticker) {
        setError("Ticker is missing");
        return;
      }
      try {
        setError(null);
        setData(await getJson<TickerAnalysisPageData>(`/api/tickers/${ticker}?window=${selectedWindow}`));
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : "Failed to load ticker analysis");
      }
    }
    void load();
  }, [ticker, selectedWindow]);

  useEffect(() => {
    if (!data) {
      return;
    }
    const fallback = data.chart.selected_plan_ids.length > 0 ? data.chart.selected_plan_ids : data.chart.overlays.map((overlay) => overlay.plan_id);
    setSelectedPlanIds(fallback);
  }, [data?.ticker, data?.window]);

  const latestPlan = useMemo(() => data?.recommendation_plans[0] ?? null, [data]);
  const latestMatchedTickerRelationships = latestPlan ? matchedRelationshipsFromPlan(latestPlan) : [];
  const latestTickerRelationshipEdges = latestPlan ? storedRelationshipEdgesFromPlan(latestPlan) : [];
  const latestOutcomeBias = latestPlan?.latest_outcome
    ? detailLabel(latestPlan.latest_outcome.transmission_bias_detail, latestPlan.latest_outcome.transmission_bias_label ?? latestPlan.latest_outcome.transmission_bias, false) ?? "—"
    : "—";
  const latestOutcomeRegime = latestPlan?.latest_outcome
    ? detailLabel(latestPlan.latest_outcome.context_regime_detail, latestPlan.latest_outcome.context_regime_label ?? latestPlan.latest_outcome.context_regime, false) ?? "—"
    : "—";

  function togglePlan(planId: number) {
    setSelectedPlanIds((current) => (current.includes(planId) ? current.filter((id) => id !== planId) : [...current, planId]));
  }

  function focusPlanOnChart(planId: number) {
    setSelectedPlanIds([planId]);
    window.requestAnimationFrame(() => {
      chartSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  function selectAllPlans() {
    if (!data) {
      return;
    }
    setSelectedPlanIds(data.chart.overlays.map((overlay) => overlay.plan_id));
  }

  function selectNoPlans() {
    setSelectedPlanIds([]);
  }

  function updateWindow(windowValue: string) {
    setSearchParams({ window: normalizeReviewWindow(windowValue, "7d") });
  }

  return (
    <>
      <PageHeader
        kicker="Ticker drill-down"
        title={data ? `${data.ticker} review` : "Ticker analysis"}
        actions={
          <>
            <Link to="/jobs/recommendation-plans" className="button-secondary">← Plans</Link>
            {data ? <a href={`/api/tickers/${data.ticker}`} className="button-subtle" target="_blank" rel="noreferrer">{} JSON</a> : null}
          </>
        }
      />
      {error ? <ErrorState message={error} /> : null}
      {!data && !error ? <LoadingState message="Loading ticker analysis…" /> : null}
      {data ? (
        <div className="stack-page">
          <section className="metrics-grid">
            <StatCard label="WR" value={data.summary.win_rate_percent !== null ? `${data.summary.win_rate_percent}%` : "—"} helper="Resolved plan win rate" />
            <StatCard label="Profit" value={data.summary.total_profit !== null ? formatPrice(data.summary.total_profit) : "—"} helper="Total realized + simulated profit" />
            <StatCard label="Plans" value={data.summary.plan_count} helper="Stored plans in the selected window" />
            <StatCard label="Orders" value={data.summary.broker_order_count} helper="Broker order executions" />
            <StatCard label="Bars" value={data.summary.bar_count} helper="Stored 1m bars in the selected window" />
            <StatCard label="Avg confidence" value={data.performance.average_confidence !== null ? `${data.performance.average_confidence}%` : "—"} helper="Mean stored plan confidence" />
          </section>

          <div ref={chartSectionRef}>
            <Card>
              <SectionTitle kicker="Chart" title="Price chart with actionable plan overlays" subtitle="Toggle plans on and off to inspect the price path around each setup." />
              <div className="cluster space-between top-gap-small">
                <SegmentedTabs
                  value={selectedWindow}
                  onChange={updateWindow}
                  options={REVIEW_WINDOW_OPTIONS}
                />
                <button type="button" className="button-subtle" onClick={() => setFitChartToScreen((current) => !current)}>
                  {fitChartToScreen ? "↔ Scroll" : "⛶ Fit"}
                </button>
              </div>
              <div className="top-gap-small">
                <TickerPriceChart
                  series={data.chart}
                  selectedPlanIds={selectedPlanIds}
                  fitToScreen={fitChartToScreen}
                  onTogglePlan={togglePlan}
                  onSelectAll={selectAllPlans}
                  onSelectNone={selectNoPlans}
                />
              </div>
            </Card>
          </div>

          <Card>
            <SectionTitle kicker="Navigation" title="Ticker review sections" subtitle="Keep one task visible at a time: overview for the big picture, plans for the full recommendation-plan history." />
            <SegmentedTabs
              value={section}
              onChange={setSection}
              options={[
                { value: "overview", label: "Overview" },
                { value: "plans", label: "Plans" },
              ]}
            />
          </Card>

          {section === "overview" ? (
            <section className="insight-grid">
              <DisclosureCard title="Interpretation" subtitle="Keep the mental model visible without over-explaining the page." defaultOpen>
                <ul className="checklist">
                  <li>Recommendation plans and plan outcomes are the canonical app-side review objects.</li>
                  <li>Use plan mix and recent outcome state to decide whether this ticker deserves repeated operator attention.</li>
                  <li>Use the chart to inspect whether entries, stops, and exits line up with actual price movement.</li>
                </ul>
              </DisclosureCard>
              <DisclosureCard title="Plan mix" subtitle="The current distribution is still visible, but not forced into the first screen.">
                <div className="data-points top-gap-small">
                  <div className="data-point"><span className="data-point-label">long</span><span className="data-point-value">{data.performance.long_plan_count}</span></div>
                  <div className="data-point"><span className="data-point-label">short</span><span className="data-point-value">{data.performance.short_plan_count}</span></div>
                  <div className="data-point"><span className="data-point-label">no_action</span><span className="data-point-value">{data.performance.no_action_plan_count}</span></div>
                  <div className="data-point"><span className="data-point-label">watchlist</span><span className="data-point-value">{data.performance.watchlist_plan_count}</span></div>
                  <div className="data-point"><span className="data-point-label">warnings</span><span className="data-point-value">{data.performance.warning_plan_count}</span></div>
                </div>
              </DisclosureCard>
              <DisclosureCard title="Latest plan" subtitle="Most recent operator context and evaluation summary." defaultOpen>
                {latestPlan ? (
                  <div className="data-stack top-gap-small">
                    <div className="cluster"><Badge tone={latestPlan.action === "long" ? "ok" : latestPlan.action === "short" ? "warning" : "neutral"}>{latestPlan.action}</Badge><Badge>{latestPlan.horizon}</Badge><Badge>{typeof latestPlan.signal_breakdown?.setup_family === "string" ? latestPlan.signal_breakdown.setup_family : "setup —"}</Badge><ScoreBadge label="Confidence" value={`${latestPlan.confidence_percent}%`} tone="info" /></div>
                    <div className="helper-text">{latestPlan.thesis_summary || latestPlan.rationale_summary || "No thesis summary stored."}</div>
                    <div className="helper-text">Entry {latestPlan.entry_price_low ?? latestPlan.entry_price_high ?? "—"} · Stop {latestPlan.stop_loss ?? "—"} · Take {latestPlan.take_profit ?? "—"}</div>
                    <div className="helper-text">Relationships {relationshipSummary(latestPlan ?? {})} · Bias {latestOutcomeBias} · Regime {latestOutcomeRegime}</div>
                    <RecommendationPlanEvaluationSummary plan={latestPlan} />
                    {latestPlan.latest_outcome?.entry_touched === false ? (
                      <div className="helper-text">Entry miss {latestPlan.latest_outcome.entry_miss_distance_percent !== null ? `${latestPlan.latest_outcome.entry_miss_distance_percent.toFixed(2)}%` : "—"}{latestPlan.latest_outcome.near_entry_miss ? " · almost entered" : ""}{latestPlan.latest_outcome.direction_worked_without_entry ? " · then still moved right" : ""}</div>
                    ) : null}
                  </div>
                ) : (
                  <EmptyState message="No plans stored for this ticker yet." />
                )}
              </DisclosureCard>
              {latestPlan ? (
                <TickerRelationshipReadthroughCard
                  title="Latest matched ticker relationships"
                  matched={latestMatchedTickerRelationships}
                  storedEdges={latestTickerRelationshipEdges}
                  emptyMessage="No ticker relationship read-through was stored for the latest plan yet."
                />
              ) : null}
            </section>
          ) : null}

          {section === "plans" ? (
            <Card>
              <SectionTitle kicker="Plan history" title="Recommendation plans for this ticker" />
              {data.recommendation_plans.length === 0 ? <EmptyState message="No recommendation plans are stored for this ticker yet." /> : (
                <div className="data-stack top-gap-small">
                  {data.recommendation_plans.map((item) => {
                    const setupFamily = typeof item.signal_breakdown?.setup_family === "string"
                      ? item.signal_breakdown.setup_family
                      : "—";
                    const outcomeBias = item.latest_outcome
                      ? detailLabel(item.latest_outcome.transmission_bias_detail, item.latest_outcome.transmission_bias_label ?? item.latest_outcome.transmission_bias, false) ?? "—"
                      : "—";
                    const outcomeRegime = item.latest_outcome
                      ? detailLabel(item.latest_outcome.context_regime_detail, item.latest_outcome.context_regime_label ?? item.latest_outcome.context_regime, false) ?? "—"
                      : "—";
                    const isSelected = item.id !== null && selectedPlanIds.includes(item.id);
                    return (
                      <article
                        key={`${item.id}-${item.computed_at}`}
                        className="data-card data-card-clickable"
                        role="button"
                        tabIndex={0}
                        onClick={() => item.id !== null ? focusPlanOnChart(item.id) : undefined}
                        onKeyDown={(event) => {
                          if (item.id === null) {
                            return;
                          }
                          if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault();
                            focusPlanOnChart(item.id);
                          }
                        }}
                        title="Click to focus this plan on the chart"
                      >
                        <div className="data-card-header">
                          <div>
                            <div className="cluster">
                              <Badge tone={item.action === "long" ? "ok" : item.action === "short" ? "warning" : "neutral"}>{item.action}</Badge>
                              <Badge>{setupFamily}</Badge>
                              <Badge>{item.horizon}</Badge>
                              {item.run_id ? <Link to={`/runs/${item.run_id}`} className="badge badge-info badge-link" onClick={(event) => event.stopPropagation()}>run #{item.run_id}</Link> : null}
                              {item.id !== null ? <button type="button" className="button-subtle" onClick={(event) => { event.stopPropagation(); togglePlan(item.id!); }}>{isSelected ? "⊖ Chart" : "⊕ Chart"}</button> : null}
                            </div>
                            <div className="cluster top-gap-small"><ScoreBadge label="Confidence" value={`${item.confidence_percent}%`} tone="info" /></div>
                            <div className="helper-text">{formatDate(item.computed_at)} · relationships {relationshipSummary(item)} · source {item.effective_evaluation_source === "broker" ? "broker" : item.effective_evaluation_source === "missing" ? "missing" : "simulated"}</div>
                            <RecommendationPlanEvaluationSummary plan={item} compact />
                          </div>
                        </div>
                        <div className="helper-text">{item.thesis_summary || item.rationale_summary || "No thesis summary stored."}</div>
                        <div className="helper-text top-gap-small">relationships {relationshipSummary(item)} · entry {item.entry_price_low ?? item.entry_price_high ?? "—"}{item.entry_price_high && item.entry_price_low && item.entry_price_high !== item.entry_price_low ? ` to ${item.entry_price_high}` : ""} · stop {item.stop_loss ?? "—"} · take {item.take_profit ?? "—"}</div>
                        <div className="helper-text">outcome {item.effective_evaluation_source === "broker" ? item.effective_evaluation_detail || "broker evaluation" : item.effective_evaluation_source === "missing" ? item.effective_evaluation_detail || "broker evaluation missing" : item.latest_outcome?.notes || (item.warnings.length > 0 ? `${item.warnings.length} warning(s)` : "—")} · analytics {item.latest_outcome ? `${outcomeBias} · ${outcomeRegime}` : "—"}</div>
                        {item.latest_outcome?.entry_touched === false ? (
                          <div className="helper-text">entry miss {item.latest_outcome.entry_miss_distance_percent !== null ? `${item.latest_outcome.entry_miss_distance_percent.toFixed(2)}%` : "—"}{item.latest_outcome.near_entry_miss ? " · almost entered" : ""}{item.latest_outcome.direction_worked_without_entry ? " · then still moved right" : ""}</div>
                        ) : null}
                      </article>
                    );
                  })}
                </div>
              )}
            </Card>
          ) : null}

        </div>
      ) : null}
    </>
  );
}
