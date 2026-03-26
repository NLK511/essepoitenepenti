import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { getJson } from "../api";
import { Badge, Card, EmptyState, ErrorState, LoadingState, PageHeader, SectionTitle } from "../components/ui";
import type { DashboardResponse, SentimentSnapshotListResponse } from "../types";
import { directionTone, formatDate, formatDuration, jobTypeLabel, recommendationStateTone, runTone, tickerTone } from "../utils";

export function DashboardPage() {
  const [data, setData] = useState<DashboardResponse | null>(null);
  const [latestMacroLabel, setLatestMacroLabel] = useState<string>("—");
  const [latestIndustryLabel, setLatestIndustryLabel] = useState<string>("—");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        setError(null);
        const [dashboard, macroSnapshots, industrySnapshots] = await Promise.all([
          getJson<DashboardResponse>("/api/dashboard"),
          getJson<SentimentSnapshotListResponse>("/api/sentiment-snapshots/macro?limit=1"),
          getJson<SentimentSnapshotListResponse>("/api/sentiment-snapshots/industry?limit=1"),
        ]);
        setData(dashboard);
        setLatestMacroLabel(
          macroSnapshots.snapshots[0]
            ? `${macroSnapshots.snapshots[0].label.toLowerCase()} · ${formatDate(macroSnapshots.snapshots[0].computed_at)}`
            : "no snapshot"
        );
        setLatestIndustryLabel(
          industrySnapshots.snapshots[0]
            ? `${industrySnapshots.snapshots[0].subject_label} · ${industrySnapshots.snapshots[0].label.toLowerCase()}`
            : "no snapshot"
        );
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : "Failed to load dashboard");
      }
    }
    void load();
  }, []);

  return (
    <>
      <PageHeader
        kicker="Daily monitoring"
        title="Review recommendation plans separately from the runs that produced them."
        subtitle="Runs are execution records for jobs. Recommendation plans are the canonical trade-review objects. The dashboard keeps both views visible without reviving retired legacy recommendation surfaces."
        actions={
          <>
            <Link to="/jobs" className="button">
              Create or run jobs
            </Link>
            <Link to="/sentiment" className="button-secondary">
              Inspect snapshots
            </Link>
            <Link to="/settings" className="button-subtle">
              Review setup
            </Link>
          </>
        }
      />

      {error ? <ErrorState message={error} /> : null}
      {!data && !error ? <LoadingState message="Loading dashboard…" /> : null}

      {data ? (
        <div className="stack-page">
          <section className="metrics-grid">
            <Card>
              <div className="metric-label">Latest recommendation plans</div>
              <div className="metric-value">{data.recommendation_plans.length}</div>
            </Card>
            <Card>
              <div className="metric-label">Configured watchlists</div>
              <div className="metric-value">{data.watchlists.length}</div>
            </Card>
            <Card>
              <div className="metric-label">Configured jobs</div>
              <div className="metric-value">{data.jobs.length}</div>
            </Card>
            <Card>
              <div className="metric-label">Recent runs</div>
              <div className="metric-value">{data.latest_runs.length}</div>
            </Card>
            <Card>
              <div className="metric-label">Latest macro snapshot</div>
              <div className="metric-value">{latestMacroLabel.split(" · ")[0]}</div>
              <div className="helper-text">{latestMacroLabel}</div>
            </Card>
            <Card>
              <div className="metric-label">Latest industry snapshot</div>
              <div className="metric-value">{latestIndustryLabel.split(" · ")[0]}</div>
              <div className="helper-text">{latestIndustryLabel}</div>
            </Card>
          </section>

          <section className="two-column">
            <Card>
              <SectionTitle
                kicker="Setup path"
                title="Recommended onboarding flow"
                subtitle="Settings → watchlists → jobs → first run."
              />
              <ol className="checklist">
                <li>Configure provider credentials and summary backend in Settings.</li>
                <li>Create reusable ticker groups in Watchlists.</li>
                <li>Create a job from a watchlist or manual tickers.</li>
                <li>Run the job to create recommendation plans, then evaluate them later to settle outcomes.</li>
              </ol>
            </Card>
            <Card>
              <SectionTitle kicker="Latest runs" title="Execution triage" />
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
                        <div className="helper-text">Job {run.job_id} · {jobTypeLabel(run.job_type)} · {formatDate(run.created_at)}</div>
                        {run.scheduled_for ? <div className="helper-text">Scheduled slot {formatDate(run.scheduled_for)}</div> : null}
                        <div className="helper-text">Duration {formatDuration(run.duration_seconds)}</div>
                        {run.error_message ? <div className="warning-text">{run.error_message}</div> : null}
                      </div>
                      <Badge tone={runTone(run.status)}>{run.status}</Badge>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </section>

          <section className="card-grid">
            <Card>
              <SectionTitle kicker="Configuration" title="Watchlists" />
              {data.watchlists.length === 0 ? (
                <EmptyState message="No watchlists yet." />
              ) : (
                <ul className="list-reset">
                  {data.watchlists.map((watchlist) => (
                    <li key={watchlist.id ?? watchlist.name} className="list-item compact-item">
                      <div>
                        <strong>{watchlist.name}</strong>
                        <div className="badge-row">
                          {watchlist.tickers.map((ticker) => (
                            <Badge key={`${watchlist.name}-${ticker}`} tone={tickerTone()}>{ticker}</Badge>
                          ))}
                        </div>
                      </div>
                      <Badge>{watchlist.tickers.length} ticker(s)</Badge>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
            <Card>
              <SectionTitle kicker="Automation" title="Jobs" />
              {data.jobs.length === 0 ? (
                <EmptyState message="No jobs yet." />
              ) : (
                <ul className="list-reset">
                  {data.jobs.map((job) => (
                    <li key={job.id ?? job.name} className="list-item compact-item">
                      <div>
                        <strong>{job.name}</strong>
                        <div className="badge-row">
                          <Badge tone="neutral">{jobTypeLabel(job.job_type)}</Badge>
                          {job.job_type === "proposal_generation" ? (
                            job.watchlist_id ? (
                              <Badge tone="info">watchlist: {job.watchlist_name ?? job.watchlist_id}</Badge>
                            ) : (
                              job.tickers.map((ticker) => (
                                <Badge key={`${job.name}-${ticker}`} tone={tickerTone()}>{ticker}</Badge>
                              ))
                            )
                          ) : (
                            <Badge tone="info">maintenance workflow</Badge>
                          )}
                        </div>
                      </div>
                      <Badge tone={job.enabled ? "ok" : "neutral"}>{job.enabled ? "enabled" : "disabled"}</Badge>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </section>

          <Card>
            <SectionTitle
              kicker="Latest output"
              title="Recommendation plans"
              actions={
                <Link to="/jobs/recommendation-plans" className="button-secondary">
                  Browse plans
                </Link>
              }
            />
            {data.recommendation_plans.length === 0 ? (
              <EmptyState message="No recommendation plans persisted yet." />
            ) : (
              <div className="card-grid">
                {data.recommendation_plans.map((item) => (
                  <article key={item.id ?? `${item.ticker}-${item.computed_at}`} className="recommendation-card">
                    <div className="card-headline">
                      <div>
                        <div className="cluster">
                          <Link to={`/tickers/${item.ticker}`} className="badge badge-info badge-link">{item.ticker}</Link>
                          <Badge tone={directionTone(item.action === "short" ? "SHORT" : item.action === "long" ? "LONG" : "NEUTRAL")}>{item.action}</Badge>
                          <Badge tone={recommendationStateTone(item.latest_outcome?.outcome === "win" ? "WIN" : item.latest_outcome?.outcome === "loss" ? "LOSS" : "PENDING")}>
                            {item.latest_outcome?.outcome ?? item.status}
                          </Badge>
                        </div>
                        <h3 className="subsection-title">{item.confidence_percent}% confidence</h3>
                      </div>
                      <Link to={item.run_id ? `/runs/${item.run_id}` : "/jobs/recommendation-plans"} className="button-secondary">
                        Open run
                      </Link>
                    </div>
                    <div className="summary-grid">
                      <div className="summary-item"><span className="summary-label">Entry</span><span className="summary-value">{item.entry_price_low ?? item.entry_price_high ?? "—"}</span></div>
                      <div className="summary-item"><span className="summary-label">Stop</span><span className="summary-value">{item.stop_loss ?? "—"}</span></div>
                      <div className="summary-item"><span className="summary-label">Take profit</span><span className="summary-value">{item.take_profit ?? "—"}</span></div>
                    </div>
                    <div className="helper-text">{item.thesis_summary || "No thesis summary captured for this recommendation plan."}</div>
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
