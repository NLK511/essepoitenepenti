import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { getJson } from "../api";
import { Badge, Card, EmptyState, ErrorState, HelpHint, LoadingState, PageHeader, SectionTitle, SegmentedTabs, StatCard } from "../components/ui";
import type { DashboardResponse } from "../types";
import { formatDate } from "../utils";

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

function boardTone(status: string | null | undefined): "ok" | "warning" | "danger" | "neutral" {
  if (status === "healthy") {
    return "ok";
  }
  if (status === "watch" || status === "thin") {
    return "warning";
  }
  if (status === "needs_attention") {
    return "danger";
  }
  return "neutral";
}

function failureTone(status: string): "ok" | "warning" | "danger" | "neutral" {
  if (status === "failed") {
    return "danger";
  }
  return "neutral";
}

function normalizeWindow(value: string | null): DashboardWindow {
  return (WINDOW_OPTIONS.find((option) => option.value === value)?.value ?? "1m") as DashboardWindow;
}

export function DashboardPage() {
  const [searchParams, setSearchParams] = useSearchParams({ window: "1m" });
  const selectedWindow = normalizeWindow(searchParams.get("window"));
  const [data, setData] = useState<DashboardResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        setError(null);
        setData(null);
        const query = new URLSearchParams({ window: selectedWindow });
        setData(await getJson<DashboardResponse>(`/api/dashboard?${query.toString()}`));
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : "Failed to load dashboard");
      }
    }
    void load();
  }, [selectedWindow]);

  const summary = data?.dashboard_summary ?? null;
  const technical = data?.technical_summary ?? null;
  const quality = data?.recommendation_quality?.summary ?? null;
  const majorFailures = data?.major_failures ?? [];
  const distinctWarnings = data?.distinct_warnings ?? [];
  const windowLabel = useMemo(() => WINDOW_OPTIONS.find((option) => option.value === selectedWindow)?.label ?? "1M", [selectedWindow]);

  return (
    <>
      <PageHeader
        kicker="Performance board"
        title="Green / yellow / red"
        actions={
          <>
            <HelpHint tooltip="Use this board to judge edge and operational risk quickly. Open deeper review screens only after one of the three colors looks concerning." to="/docs?doc=operator-page-field-guide" />
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
          </Card>

          <Card>
            <SectionTitle
              kicker="Board verdict"
              title={quality ? `Status: ${quality.status}` : "Status unavailable"}
              subtitle={quality?.status_reason || "No quality summary available yet."}
            />
            <div className="cluster top-gap-small">
              <Badge tone={boardTone(quality?.status)}>{quality?.status ?? "unknown"}</Badge>
              <Badge tone={boardTone(quality?.status)}>{quality?.status === "healthy" ? "green" : quality?.status === "needs_attention" ? "red" : "yellow"}</Badge>
              <span className="helper-text">Updated {quality?.generated_at ? formatDate(quality.generated_at) : "—"} · resolved outcomes {quality?.resolved_outcomes ?? "—"}</span>
            </div>
          </Card>

          <section className="insight-grid">
            <Card>
              <SectionTitle kicker="Green" title="Edge" subtitle="The only numbers that matter when deciding whether the system is improving." />
              <div className="data-stack top-gap-small">
                <StatCard label="Win rate" value={formatPercent(summary?.win_rate_percent)} helper="Resolved plan outcomes" />
                <StatCard label="Profit %" value={formatPercent(summary?.profit_percent)} helper="Avg 5d return on actionable plans" />
                <StatCard label="Shortlist rate" value={formatPercent(summary?.shortlist_rate_percent)} helper={`${summary?.plan_amount ?? 0} plans / ${summary?.signals_amount ?? 0} signals`} />
                <StatCard label="Actionable rate" value={formatPercent(summary?.actionable_rate_percent)} helper={`${summary?.actionable_plans ?? 0} actionable / ${summary?.plan_amount ?? 0} plans`} />
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
                            <Badge tone={failureTone(failure.status)}>{failure.status.replace(/_/g, " ")}</Badge>
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
              <StatCard label="News processed" value={String(technical?.news_processed ?? 0)} helper="Historical news items" />
              <StatCard label="Tweets processed" value={String(technical?.tweets_processed ?? 0)} helper="Social items used by plans" />
              <StatCard label="Bars stored" value={String(technical?.bars_stored ?? 0)} helper="Historical market bars" />
              <StatCard label="Orders placed" value={String(technical?.orders_placed ?? 0)} helper="Broker executions" />
            </div>
          </Card>
        </div>
      ) : null}
    </>
  );
}
