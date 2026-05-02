import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { getJson, postForm } from "../api";
import { Badge, Card, EmptyState, ErrorState, HelpHint, LoadingState, PageHeader, SectionTitle, SegmentedTabs, StatCard } from "../components/ui";
import type { DashboardResponse, DashboardTrendSeries } from "../types";
import { dashboardBoardTone, dashboardFailureTone, formatDate } from "../utils";

const WINDOW_OPTIONS = [
  { value: "1d", label: "1D" },
  { value: "7d", label: "7D" },
  { value: "1m", label: "1M" },
  { value: "3m", label: "3M" },
  { value: "6m", label: "6M" },
  { value: "all", label: "ALL" },
] as const;

type DashboardWindow = (typeof WINDOW_OPTIONS)[number]["value"];

function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "—";
  }
  return `${value.toFixed(1)}%`;
}

function formatSignedPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "—";
  }
  const prefix = value > 0 ? "+" : "";
  return `${prefix}${value.toFixed(1)}%`;
}

function normalizeWindow(value: string | null): DashboardWindow {
  return (WINDOW_OPTIONS.find((option) => option.value === value)?.value ?? "1m") as DashboardWindow;
}

function MetricSparkline(props: { label: string; series: DashboardTrendSeries | undefined }) {
  const points = props.series?.values
    .map((value, index) => (typeof value === "number" && Number.isFinite(value) ? { index, value } : null))
    .filter((point): point is { index: number; value: number } => point !== null) ?? [];
  if (points.length < 2) {
    return <span className="helper-text">Trend data unavailable</span>;
  }
  const min = Math.min(...points.map((point) => point.value));
  const max = Math.max(...points.map((point) => point.value));
  const range = max - min || 1;
  const width = 100;
  const height = 28;
  const maxIndex = Math.max((props.series?.values.length ?? 1) - 1, 1);
  const coordinates = points.map((point) => {
    const x = (point.index / maxIndex) * width;
    const y = height - 4 - ((point.value - min) / range) * (height - 8);
    return { x, y, value: point.value };
  });
  const path = coordinates.map((point, index) => `${index === 0 ? "M" : "L"}${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ");
  return (
    <svg viewBox="0 0 100 28" className="metric-sparkline" role="img" aria-label={`${props.label} trendline`} preserveAspectRatio="none">
      <title>{props.label} trendline</title>
      <path d={path} />
      {coordinates.map((point, index) => <circle key={`${props.label}-${index}`} cx={point.x.toFixed(1)} cy={point.y.toFixed(1)} r="1.8" />)}
    </svg>
  );
}

export function DashboardPage() {
  const [searchParams, setSearchParams] = useSearchParams({ window: "1m" });
  const selectedWindow = normalizeWindow(searchParams.get("window"));
  const [data, setData] = useState<DashboardResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [lastLoadedAt, setLastLoadedAt] = useState<Date | null>(null);
  const [showTrendlines, setShowTrendlines] = useState(false);

  async function loadDashboard({ clear = false } = {}) {
    try {
      setError(null);
      if (clear) {
        setData(null);
      }
      const query = new URLSearchParams({ window: selectedWindow });
      setData(await getJson<DashboardResponse>(`/api/dashboard?${query.toString()}`));
      setLastLoadedAt(new Date());
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to load dashboard");
    }
  }

  useEffect(() => {
    void loadDashboard({ clear: true });
    const interval = window.setInterval(() => void loadDashboard(), 60000);
    return () => window.clearInterval(interval);
  }, [selectedWindow]);

  const summary = data?.dashboard_summary ?? null;
  const technical = data?.technical_summary ?? null;
  const quality = data?.recommendation_quality?.summary ?? null;
  const majorFailures = data?.major_failures ?? [];
  const distinctWarnings = data?.distinct_warnings ?? [];
  const dashboardTrends = data?.dashboard_trends ?? null;
  const trendSeriesMap = useMemo(() => new Map((dashboardTrends?.series ?? []).map((series) => [series.key, series])), [dashboardTrends]);
  const windowLabel = useMemo(() => WINDOW_OPTIONS.find((option) => option.value === selectedWindow)?.label ?? "1M", [selectedWindow]);

  async function refreshBrokerState() {
    try {
      setRefreshing(true);
      setError(null);
      await postForm("/api/broker-orders/sync", {});
      await loadDashboard();
    } catch (refreshError) {
      setError(refreshError instanceof Error ? refreshError.message : "Failed to refresh dashboard statistics");
    } finally {
      setRefreshing(false);
    }
  }

  return (
    <>
      <PageHeader
        kicker="Performance board"
        title="Green / yellow / red"
        actions={
          <>
            <HelpHint tooltip="Use this board to judge edge and operational risk quickly. Open deeper review screens only after one of the three colors looks concerning." to="/docs?doc=operator-page-field-guide" />
            <button type="button" className="button-secondary" disabled={refreshing} onClick={() => void refreshBrokerState()}>{refreshing ? "Refreshing…" : "Refresh broker stats"}</button>
            <Link to="/jobs/recommendation-plans" className="button-secondary">Review plans</Link>
            <Link to="/recommendation-quality" className="button">Quality report</Link>
          </>
        }
      />

      {error ? <ErrorState message={error} /> : null}
      {!data && !error ? <LoadingState message="Loading dashboard…" /> : null}

      {data ? (
        <div className="stack-page">
          <Card>
            <SectionTitle
              kicker="Time window"
              title={`Showing ${windowLabel}`}
              actions={
                <button type="button" className="button-subtle" onClick={() => setShowTrendlines((current) => !current)}>
                  {showTrendlines ? "Hide trendlines" : "Show trendlines"}
                </button>
              }
            />
            <div className="top-gap-small">
              <SegmentedTabs
                value={selectedWindow}
                onChange={(value) => {
                  const next = new URLSearchParams(searchParams);
                  next.set("window", value);
                  setSearchParams(next, { replace: true });
                }}
                options={[...WINDOW_OPTIONS]}
              />
            </div>
            {showTrendlines ? <div className="helper-text top-gap-small">Trendlines sweep the dashboard windows from 1D through ALL so each metric can be compared without opening another page.</div> : null}
          </Card>

          <Card>
            <SectionTitle
              kicker="Board verdict"
              title={quality ? `Status: ${quality.status}` : "Status unavailable"}
              subtitle={quality?.status_reason || "No quality summary available yet."}
            />
            <div className="cluster top-gap-small">
              <Badge tone={dashboardBoardTone(quality?.status)}>{quality?.status ?? "unknown"}</Badge>
              <Badge tone={dashboardBoardTone(quality?.status)}>{quality?.status === "healthy" ? "green" : quality?.status === "needs_attention" ? "red" : "yellow"}</Badge>
              <span className="helper-text">Updated {lastLoadedAt ? formatDate(lastLoadedAt.toISOString()) : quality?.generated_at ? formatDate(quality.generated_at) : "—"} · resolved outcomes {quality?.resolved_outcomes ?? "—"}</span>
            </div>
          </Card>

          <section className="insight-grid">
            <Card>
              <SectionTitle kicker="Green" title="Edge" subtitle="The only numbers that matter when deciding whether the system is improving." />
              <div className="data-stack top-gap-small">
                <StatCard
                  className={showTrendlines ? "stat-card-compact" : undefined}
                  label="Win rate"
                  value={formatPercent(summary?.win_rate_percent)}
                  trend={showTrendlines ? <MetricSparkline label="Win rate" series={trendSeriesMap.get("win_rate_percent")} /> : null}
                  helper={showTrendlines ? undefined : (summary?.win_rate_source === "broker" ? `${technical?.broker_wins ?? 0} broker wins / ${technical?.broker_closed_positions ?? 0} closed positions` : "Resolved simulated plan outcomes")}
                />
                <StatCard
                  className={showTrendlines ? "stat-card-compact" : undefined}
                  label="Profit %"
                  value={formatPercent(summary?.profit_percent)}
                  trend={showTrendlines ? <MetricSparkline label="Profit %" series={trendSeriesMap.get("profit_percent")} /> : null}
                  helper={showTrendlines ? undefined : (summary?.profit_source === "broker" ? `Broker realized P&L $${technical?.broker_realized_pnl ?? 0}` : "Avg 5d return on actionable plans")}
                />
                <StatCard
                  className={showTrendlines ? "stat-card-compact" : undefined}
                  label="Shortlist rate"
                  value={formatPercent(summary?.shortlist_rate_percent)}
                  trend={showTrendlines ? <MetricSparkline label="Shortlist rate" series={trendSeriesMap.get("shortlist_rate_percent")} /> : null}
                  helper={showTrendlines ? undefined : `${summary?.plan_amount ?? 0} plans / ${summary?.signals_amount ?? 0} signals`}
                />
                <StatCard
                  className={showTrendlines ? "stat-card-compact" : undefined}
                  label="Actionable rate"
                  value={formatPercent(summary?.actionable_rate_percent)}
                  trend={showTrendlines ? <MetricSparkline label="Actionable rate" series={trendSeriesMap.get("actionable_rate_percent")} /> : null}
                  helper={showTrendlines ? undefined : `${summary?.actionable_plans ?? 0} actionable / ${summary?.plan_amount ?? 0} plans`}
                />
                <StatCard
                  className={showTrendlines ? "stat-card-compact" : undefined}
                  label="Actionability gap"
                  value={formatSignedPercent(summary?.actionability_gap_percent)}
                  trend={showTrendlines ? <MetricSparkline label="Actionability gap" series={trendSeriesMap.get("actionability_gap_percent")} /> : null}
                  helper={showTrendlines ? undefined : `${summary?.phantom_win_outcomes ?? 0} phantom wins / ${summary?.phantom_resolved_outcomes ?? 0} phantom resolved · ${summary?.actionable_win_outcomes ?? 0} actionable wins / ${summary?.actionable_resolved_outcomes ?? 0} actionable resolved · positive means skipped setups are outperforming acted-on setups`}
                />
              </div>
            </Card>

            <Card>
              <SectionTitle kicker="Yellow" title="Warnings" subtitle="Recurring problems that may not be fatal yet, but deserve operator attention." />
              {distinctWarnings.length === 0 ? (
                <EmptyState message="No warning patterns collected in the current dashboard window." />
              ) : (
                <div className="data-stack top-gap-small">
                  {distinctWarnings.slice(0, 6).map((warning) => (
                    <details key={warning.label} className="data-card">
                      <summary className="data-card-header" style={{ cursor: "pointer" }}>
                        <div>
                          <div className="data-card-title">{warning.label}</div>
                          <div className="helper-text">Open to see sources</div>
                        </div>
                        <Badge tone={warning.count >= 3 ? "danger" : warning.count === 2 ? "warning" : "neutral"}>{warning.count}</Badge>
                      </summary>
                      <div className="helper-text top-gap-small">Sources: {warning.sources.length > 0 ? warning.sources.join(" · ") : "—"}</div>
                    </details>
                  ))}
                </div>
              )}
            </Card>

            <Card>
              <SectionTitle kicker="Red" title="Failures" subtitle="Only the broken items that should change your behavior right now." />
              {majorFailures.length === 0 ? (
                <EmptyState message="No major failures in the current dashboard window." />
              ) : (
                <div className="data-stack top-gap-small">
                  {majorFailures.map((failure) => (
                    <article key={`${failure.source}-${failure.label}-${failure.run_id ?? failure.created_at ?? failure.detail}`} className="data-card">
                      <div className="data-card-header">
                        <div>
                          <div className="cluster">
                            <Badge tone={dashboardFailureTone(failure.status)}>{failure.status.replace(/_/g, " ")}</Badge>
                            <Badge>{failure.source}</Badge>
                          </div>
                          <div className="data-card-title top-gap-small">{failure.label}</div>
                        </div>
                        {failure.run_id ? <Link to={`/runs/${failure.run_id}`} className="button-subtle">Open run</Link> : null}
                      </div>
                      <div className="helper-text top-gap-small">{failure.detail}</div>
                      <div className="helper-text">{failure.created_at ? formatDate(failure.created_at) : "—"}</div>
                    </article>
                  ))}
                </div>
              )}
            </Card>
          </section>

          <Card>
            <SectionTitle kicker="Next move" title="Open the deeper evidence only when needed" subtitle="The board should stay minimal; everything else belongs on a dedicated detail page." />
            <div className="cluster top-gap-small">
              <Link to="/jobs/recommendation-plans" className="button-secondary">Review plans</Link>
              <Link to="/recommendation-quality" className="button-secondary">Quality report</Link>
              <Link to="/jobs/debugger" className="button-subtle">Debugger</Link>
            </div>
          </Card>

          <Card>
            <SectionTitle kicker="Technical" title="Pipeline volume" subtitle="Selected-window volume of the main data feeds and execution layer." />
            <div className="data-stack top-gap-small">
              <StatCard
                className={showTrendlines ? "stat-card-compact" : undefined}
                label="News processed"
                value={String(technical?.news_processed ?? 0)}
                trend={showTrendlines ? <MetricSparkline label="News processed" series={trendSeriesMap.get("news_processed")} /> : null}
                helper={showTrendlines ? undefined : "Historical news items"}
              />
              <StatCard
                className={showTrendlines ? "stat-card-compact" : undefined}
                label="Tweets processed"
                value={String(technical?.tweets_processed ?? 0)}
                trend={showTrendlines ? <MetricSparkline label="Tweets processed" series={trendSeriesMap.get("tweets_processed")} /> : null}
                helper={showTrendlines ? undefined : "Social items used by plans"}
              />
              <StatCard
                className={showTrendlines ? "stat-card-compact" : undefined}
                label="Bars stored"
                value={String(technical?.bars_stored ?? 0)}
                trend={showTrendlines ? <MetricSparkline label="Bars stored" series={trendSeriesMap.get("bars_stored")} /> : null}
                helper={showTrendlines ? undefined : "Historical market bars"}
              />
              <StatCard
                className={showTrendlines ? "stat-card-compact" : undefined}
                label="Orders placed"
                value={String(technical?.orders_placed ?? 0)}
                trend={showTrendlines ? <MetricSparkline label="Orders placed" series={trendSeriesMap.get("orders_placed")} /> : null}
                helper={showTrendlines ? undefined : "Broker executions"}
              />
              <StatCard
                className={showTrendlines ? "stat-card-compact" : undefined}
                label="Broker closed"
                value={String(technical?.broker_closed_positions ?? 0)}
                trend={showTrendlines ? <MetricSparkline label="Broker closed" series={trendSeriesMap.get("broker_closed_positions")} /> : null}
                helper={showTrendlines ? undefined : `${technical?.broker_wins ?? 0} wins / ${technical?.broker_losses ?? 0} losses`}
              />
              <StatCard
                className={showTrendlines ? "stat-card-compact" : undefined}
                label="Broker realized P&L"
                value={`$${technical?.broker_realized_pnl ?? 0}`}
                trend={showTrendlines ? <MetricSparkline label="Broker realized P&L" series={trendSeriesMap.get("broker_realized_pnl")} /> : null}
                helper={showTrendlines ? undefined : "Closed broker positions in selected window"}
              />
            </div>
          </Card>
        </div>
      ) : null}
    </>
  );
}
