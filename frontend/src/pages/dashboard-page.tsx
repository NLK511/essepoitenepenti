import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { getJson } from "../api";
import { Badge, Card, EmptyState, ErrorState, HelpHint, LoadingState, PageHeader, SectionTitle, StatCard } from "../components/ui";
import type { DashboardResponse, IndustryContextSnapshot, MacroContextSnapshot } from "../types";
import { formatDate, formatDuration, jobTypeLabel, runTone } from "../utils";

function contextSummaryMethod(snapshot: MacroContextSnapshot | IndustryContextSnapshot | null): string {
  return snapshot && typeof snapshot.metadata?.context_summary_method === "string" ? snapshot.metadata.context_summary_method : "unknown";
}

function contextSummaryError(snapshot: MacroContextSnapshot | IndustryContextSnapshot | null): string | null {
  return snapshot && typeof snapshot.metadata?.context_summary_error === "string" ? snapshot.metadata.context_summary_error : null;
}

export function DashboardPage() {
  const [data, setData] = useState<DashboardResponse | null>(null);
  const [latestMacroContext, setLatestMacroContext] = useState<MacroContextSnapshot | null>(null);
  const [latestIndustryContext, setLatestIndustryContext] = useState<IndustryContextSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        setError(null);
        const [dashboard, macroContexts, industryContexts] = await Promise.all([
          getJson<DashboardResponse>("/api/dashboard"),
          getJson<MacroContextSnapshot[]>("/api/context/macro?limit=1"),
          getJson<IndustryContextSnapshot[]>("/api/context/industry?limit=1"),
        ]);
        setData(dashboard);
        setLatestMacroContext(macroContexts[0] ?? null);
        setLatestIndustryContext(industryContexts[0] ?? null);
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : "Failed to load dashboard");
      }
    }
    void load();
  }, []);

  const attentionItems = useMemo(() => {
    if (!data) {
      return [] as string[];
    }
    const items: string[] = [];
    if (data.watchlists.length === 0) {
      items.push("No watchlists yet. Create one before relying on scheduled proposal jobs.");
    }
    if (data.jobs.length === 0) {
      items.push("No jobs configured yet. Add a proposal workflow to generate candidates and plans.");
    }
    if (data.latest_runs.some((run) => run.status === "failed" || run.status === "completed_with_warnings")) {
      items.push("Recent runs include failures or warnings. Open the debugger before trusting new output.");
    }
    if (!latestMacroContext) {
      items.push("No macro context snapshot is stored yet.");
    }
    if (!latestIndustryContext) {
      items.push("No industry context snapshot is stored yet.");
    }
    if (latestMacroContext && contextSummaryError(latestMacroContext)) {
      items.push("Latest macro summary used a fallback path.");
    }
    if (latestIndustryContext && contextSummaryError(latestIndustryContext)) {
      items.push("Latest industry summary used a fallback path.");
    }
    return items;
  }, [data, latestIndustryContext, latestMacroContext]);

  return (
    <>
      <PageHeader
        kicker="Workspace overview"
        title="Start with what needs attention."
        subtitle="Use the dashboard for fast triage: check workflow health, context freshness, and the next page you should open."
        actions={
          <>
            <HelpHint tooltip="The dashboard is a triage page. Use it to spot what needs attention, then jump into review, jobs, or context." to="/docs?doc=operator-page-field-guide" />
            <Link to="/jobs" className="button">
              Run workflows
            </Link>
            <Link to="/jobs/recommendation-plans" className="button-secondary">
              Review plans
            </Link>
          </>
        }
      />

      {error ? <ErrorState message={error} /> : null}
      {!data && !error ? <LoadingState message="Loading dashboard…" /> : null}

      {data ? (
        <div className="stack-page">
          <section className="metrics-grid">
            <StatCard label="Plans to review" value={data.recommendation_plans.length} helper="Latest persisted recommendation plans" tooltip="A quick count of the most recent recommendation plans available for operator review." tooltipTo="/docs?doc=operator-page-field-guide&section=4-recommendation-plans" />
            <StatCard label="Recent runs" value={data.latest_runs.length} helper="Most recent workflow executions" tooltip="The number of recent workflow runs surfaced on the dashboard for quick health and activity checks." tooltipTo="/docs?doc=glossary&section=run" />
            <StatCard label="Watchlists" value={data.watchlists.length} helper="Reusable universes feeding proposal jobs" tooltip="The number of stored watchlists currently available to seed proposal-generation workflows." tooltipTo="/docs?doc=glossary&section=watchlist" />
            <StatCard label="Jobs" value={data.jobs.length} helper="Saved workflows" tooltip="The number of saved workflows that can be run manually or by the scheduler." tooltipTo="/docs?doc=glossary&section=job" />
            <StatCard
              label="Macro context"
              value={latestMacroContext ? latestMacroContext.status : "—"}
              helper={latestMacroContext ? `${formatDate(latestMacroContext.computed_at)} · ${contextSummaryMethod(latestMacroContext)}` : "No macro snapshot yet"}
            />
            <StatCard
              label="Industry context"
              value={latestIndustryContext ? latestIndustryContext.status : "—"}
              helper={latestIndustryContext ? `${formatDate(latestIndustryContext.computed_at)} · ${contextSummaryMethod(latestIndustryContext)}` : "No industry snapshot yet"}
            />
          </section>

          <section className="card-grid">
            {data.recommendation_quality ? (
              <Card>
                <SectionTitle kicker="Quality snapshot" title="Recommendation quality" actions={<Link to="/recommendation-quality" className="button-secondary">Open summary</Link>} />
                <div className="data-points top-gap-small">
                  <div className="data-point"><span className="data-point-label">status</span><span className="data-point-value">{data.recommendation_quality.summary.status}</span></div>
                  <div className="data-point"><span className="data-point-label">updated</span><span className="data-point-value">{formatDate(data.recommendation_quality.summary.generated_at)}</span></div>
                </div>
                <div className="helper-text top-gap-small">{data.recommendation_quality.next_actions[0] ?? "Maintain the current settings."}</div>
              </Card>
            ) : null}

            <Card>
              <SectionTitle kicker="Primary actions" title="Run the core workflow" />
              <div className="cluster top-gap-small">
                <Link to="/jobs" className="button">Open jobs</Link>
                <Link to="/jobs/ticker-signals" className="button-secondary">Review candidates</Link>
                <Link to="/jobs/recommendation-plans" className="button-secondary">Review plans</Link>
                <Link to="/context" className="button-subtle">Check context</Link>
              </div>
            </Card>

            <Card>
              <SectionTitle kicker="Attention" title="What to check next" />
              {attentionItems.length === 0 ? (
                <EmptyState message="Nothing urgent stands out right now." />
              ) : (
                <ul className="list-reset">
                  {attentionItems.map((item) => (
                    <li key={item} className="list-item compact-item">{item}</li>
                  ))}
                </ul>
              )}
            </Card>
          </section>

          <section className="two-column">
            <Card>
              <SectionTitle kicker="Recent runs" title="Execution triage" actions={<Link to="/jobs/debugger" className="button-subtle">Open debugger</Link>} />
              {data.latest_runs.length === 0 ? (
                <EmptyState message="No runs yet." />
              ) : (
                <ul className="list-reset">
                  {data.latest_runs.map((run) => (
                    <li key={run.id ?? run.created_at} className="list-item">
                      <div>
                        <Link to={`/runs/${run.id}`} className="strong-link">
                          Run #{run.id}
                        </Link>
                        <div className="helper-text">{jobTypeLabel(run.job_type)} · {formatDate(run.created_at)}</div>
                        <div className="helper-text">Duration {formatDuration(run.duration_seconds)}</div>
                        {run.error_message ? <div className="warning-text">{run.error_message}</div> : null}
                      </div>
                      <Badge tone={runTone(run.status)}>{run.status}</Badge>
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            <Card>
              <SectionTitle kicker="Context freshness" title="Latest shared backdrop" actions={<Link to="/context" className="button-subtle">Open context review</Link>} />
              <div className="data-stack top-gap-small">
                <div className="data-card">
                  <div className="data-card-header">
                    <div>
                      <div className="data-card-title">Macro</div>
                      <div className="helper-text">{latestMacroContext ? formatDate(latestMacroContext.computed_at) : "No snapshot stored"}</div>
                    </div>
                    <Badge tone={latestMacroContext?.warnings.length ? "warning" : "neutral"}>{latestMacroContext?.status ?? "missing"}</Badge>
                  </div>
                  <div className="helper-text">
                    {latestMacroContext?.summary_text || "No macro summary stored yet."}
                  </div>
                  {contextSummaryError(latestMacroContext) ? <div className="helper-text top-gap-small">Fallback note: {contextSummaryError(latestMacroContext)}</div> : null}
                </div>
                <div className="data-card">
                  <div className="data-card-header">
                    <div>
                      <div className="data-card-title">Industry</div>
                      <div className="helper-text">{latestIndustryContext ? `${latestIndustryContext.industry_label || latestIndustryContext.industry_key} · ${formatDate(latestIndustryContext.computed_at)}` : "No snapshot stored"}</div>
                    </div>
                    <Badge tone={latestIndustryContext?.warnings.length ? "warning" : "neutral"}>{latestIndustryContext?.status ?? "missing"}</Badge>
                  </div>
                  <div className="helper-text">
                    {latestIndustryContext?.summary_text || "No industry summary stored yet."}
                  </div>
                  {contextSummaryError(latestIndustryContext) ? <div className="helper-text top-gap-small">Fallback note: {contextSummaryError(latestIndustryContext)}</div> : null}
                </div>
              </div>
            </Card>
          </section>

          <Card>
            <SectionTitle kicker="Latest output" title="Recent recommendation plans" actions={<Link to="/jobs/recommendation-plans" className="button-secondary">Browse plans</Link>} />
            {data.recommendation_plans.length === 0 ? (
              <EmptyState message="No recommendation plans persisted yet." />
            ) : (
              <div className="card-grid">
                {data.recommendation_plans.map((item) => (
                  <article key={item.id ?? `${item.ticker}-${item.computed_at}`} className="recommendation-card">
                    <div className="card-headline">
                      <div>
                        <div className="cluster">
                          <Badge tone="info">{item.ticker}</Badge>
                          <Badge tone={item.action === "long" ? "ok" : item.action === "short" ? "warning" : "neutral"}>{item.action}</Badge>
                          <Badge tone={item.latest_outcome?.outcome === "win" ? "ok" : item.latest_outcome?.outcome === "loss" ? "danger" : "neutral"}>
                            {item.latest_outcome?.outcome ?? item.status}
                          </Badge>
                        </div>
                        <div className="helper-text top-gap-small">Confidence {item.confidence_percent}% · {formatDate(item.computed_at)}</div>
                      </div>
                      <Link to={item.run_id ? `/runs/${item.run_id}` : "/jobs/recommendation-plans"} className="button-subtle">
                        Open run
                      </Link>
                    </div>
                    <div className="helper-text">{item.thesis_summary || "No thesis summary stored."}</div>
                  </article>
                ))}
              </div>
            )}
          </Card>
        </div>
      ) : null}
    </>
  );
}
