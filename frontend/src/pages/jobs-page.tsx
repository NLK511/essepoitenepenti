import { FormEvent, Fragment, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { getJson, postForm } from "../api";
import { useToast } from "../components/toast";
import { Badge, Card, EmptyState, ErrorState, HelpHint, LoadingState, PageHeader, SectionTitle, StatCard } from "../components/ui";
import type { Job, JobType, Run, Watchlist } from "../types";
import { jobTypeLabel, tickerTone } from "../utils";

const jobsDoc = "/docs?doc=operator-page-field-guide";

interface JobsViewData {
  jobs: Job[];
  watchlists: Watchlist[];
}

function isProposalJobType(jobType: JobType | string): boolean {
  return jobType === "proposal_generation";
}

export function JobsPage() {
  const { showToast } = useToast();
  const navigate = useNavigate();
  const [data, setData] = useState<JobsViewData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [busyJobId, setBusyJobId] = useState<number | null>(null);
  const [editingJobId, setEditingJobId] = useState<number | null>(null);

  async function loadData() {
    try {
      setError(null);
      const [jobs, watchlists] = await Promise.all([
        getJson<Job[]>("/api/jobs"),
        getJson<Watchlist[]>("/api/watchlists"),
      ]);
      setData({ jobs, watchlists });
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to load jobs");
    }
  }

  useEffect(() => {
    void loadData();
  }, []);

  async function handleCreateJob(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const formData = new FormData(form);
    const watchlistId = String(formData.get("watchlist_id") ?? "").trim();
    const tickers = String(formData.get("tickers") ?? "").trim();
    const jobType = String(formData.get("job_type") ?? "proposal_generation") as JobType;
    try {
      setSubmitting(true);
      setError(null);
      await postForm<Job>("/api/jobs", {
        name: String(formData.get("name") ?? "").trim(),
        job_type: jobType,
        tickers: isProposalJobType(jobType) ? tickers : "",
        watchlist_id: isProposalJobType(jobType) ? (watchlistId || undefined) : undefined,
        schedule: String(formData.get("schedule") ?? "").trim(),
      });
      form.reset();
      await loadData();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Failed to create job");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleUpdateJob(event: FormEvent<HTMLFormElement>, jobId: number) {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    const watchlistId = String(formData.get("watchlist_id") ?? "").trim();
    const tickers = String(formData.get("tickers") ?? "").trim();
    try {
      setBusyJobId(jobId);
      setError(null);
      const jobType = String(formData.get("job_type") ?? "proposal_generation") as JobType;
      await postForm<Job>(`/api/jobs/${jobId}`, {
        name: String(formData.get("name") ?? "").trim(),
        job_type: jobType,
        tickers: isProposalJobType(jobType) ? tickers : "",
        watchlist_id: isProposalJobType(jobType) ? (watchlistId || undefined) : undefined,
        schedule: String(formData.get("schedule") ?? "").trim(),
        enabled: formData.get("enabled") ? "true" : "false",
      });
      setEditingJobId(null);
      await loadData();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Failed to update job");
    } finally {
      setBusyJobId(null);
    }
  }

  async function enqueueJob(jobId: number) {
    try {
      setBusyJobId(jobId);
      setError(null);
      const run = await postForm<Run>(`/api/jobs/${jobId}/execute`, {});
      showToast({
        message: run?.id ? `Run #${run.id} queued` : "Run queued",
        tone: "success",
        actionLabel: run?.id ? "View run" : undefined,
        action: run?.id
          ? () => {
              navigate(`/runs/${run.id}`);
            }
          : undefined,
        duration: 8000,
      });
      await loadData();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Failed to enqueue job");
    } finally {
      setBusyJobId(null);
    }
  }

  async function createWatchlistFromJob(jobId: number) {
    try {
      setBusyJobId(jobId);
      setError(null);
      await postForm<Watchlist>(`/api/jobs/${jobId}/watchlist`, {});
      await loadData();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Failed to create watchlist from job");
    } finally {
      setBusyJobId(null);
    }
  }

  async function deleteJob(jobId: number) {
    try {
      setBusyJobId(jobId);
      setError(null);
      await postForm<{ deleted: boolean; job_id: number }>(`/api/jobs/${jobId}/delete`, {});
      if (editingJobId === jobId) {
        setEditingJobId(null);
      }
      await loadData();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Failed to delete job");
    } finally {
      setBusyJobId(null);
    }
  }

  return (
    <>
      <PageHeader
        kicker="Automation"
        title="Jobs and execution"
        subtitle="Jobs define what gets analyzed and when. Use this page to create repeatable workflows, launch manual runs, and keep execution organized around watchlists and recommendation plans."
        actions={
          <>
            <HelpHint tooltip="Jobs define repeatable workflows such as proposal generation, evaluation, and plan-generation tuning." to={jobsDoc} />
            <Link to="/jobs/watchlists" className="button-secondary">
              Manage watchlists
            </Link>
          </>
        }
      />
      {error ? <ErrorState message={error} /> : null}
      <section className="metrics-grid top-gap">
        <StatCard label="Jobs" value={data?.jobs.length ?? "—"} helper="Saved automation workflows" />
        <StatCard label="Watchlists" value={data?.watchlists.length ?? "—"} helper="Reusable ticker universes available to proposal jobs" />
        <StatCard label="Proposal jobs" value={data?.jobs.filter((job) => job.job_type === "proposal_generation").length ?? "—"} helper="Jobs that create signals and plans" />
        <StatCard label="Enabled" value={data?.jobs.filter((job) => job.enabled).length ?? "—"} helper="Workflows currently active for scheduling or manual execution" />
      </section>
      <section className="two-column top-gap">
        <Card className="sticky-toolbar">
          <SectionTitle kicker="Create" title="New job" subtitle="Keep the form minimal: choose the workflow type, then define either a watchlist or manual tickers only when the job actually needs them." actions={<HelpHint tooltip="Proposal jobs use watchlists or tickers. Evaluation and plan-generation tuning work from stored data instead." to={jobsDoc} />} />
          <form className="stack-form" onSubmit={handleCreateJob}>
            <div className="form-grid">
              <label className="form-field">
                <span>Name</span>
                <input name="name" type="text" placeholder="Morning megacaps" required />
              </label>
              <label className="form-field">
                <span>Workflow type</span>
                <select name="job_type" defaultValue="proposal_generation">
                  <option value="proposal_generation">Proposal generation</option>
                  <option value="recommendation_evaluation">Recommendation evaluation</option>
                  <option value="plan_generation_tuning">Plan generation tuning</option>
                  <option value="macro_sentiment_refresh">Macro context refresh</option>
                  <option value="industry_sentiment_refresh">Industry context refresh</option>
                </select>
              </label>
            </div>
            <div className="form-grid">
              <label className="form-field">
                <span>Schedule</span>
                <input name="schedule" type="text" placeholder="30 9 * * 1,2,3,4,5" />
              </label>
              <div className="form-field">
                <span>Source rules</span>
                <div className="helper-text">Proposal generation uses tickers or a watchlist. Evaluation and plan-generation tuning ignore ticker sources.</div>
              </div>
            </div>
            <div className="form-grid">
              <label className="form-field">
                <span>Manual tickers</span>
                <input name="tickers" type="text" placeholder="AAPL, MSFT, NVDA" />
              </label>
              <label className="form-field">
                <span>Watchlist</span>
                <select name="watchlist_id" defaultValue="">
                  <option value="">No watchlist</option>
                  {data?.watchlists.map((watchlist) => (
                    <option key={watchlist.id ?? watchlist.name} value={watchlist.id ?? ""}>
                      {watchlist.name} · {watchlist.tickers.join(", ")}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <button type="submit" className="button" disabled={submitting}>
              {submitting ? "Creating…" : "Create job"}
            </button>
          </form>
        </Card>
        <Card>
          <SectionTitle kicker="Saved jobs" title="Run, edit, and delete" subtitle="Use enqueue for action, edit only when the schedule or source assumptions actually need to change." actions={<HelpHint tooltip="The saved-jobs table shows each workflow's type, source scope, schedule, and enabled state." to={jobsDoc} />} />
        {!data && !error ? <LoadingState message="Loading jobs…" /> : null}
        {data && data.jobs.length === 0 ? <EmptyState message="No jobs created yet." /> : null}
        {data ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Workflow</th>
                  <th>Source</th>
                  <th>Schedule</th>
                  <th>Enabled</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {data.jobs.map((job) => {
                  const isEditing = editingJobId === job.id;
                  return (
                    <Fragment key={job.id ?? job.name}>
                      <tr>
                        <td>{job.name}</td>
                        <td><Badge tone="neutral">{jobTypeLabel(job.job_type)}</Badge></td>
                        <td>
                          {job.job_type === "proposal_generation" ? (
                            job.watchlist_id ? (
                              <Badge tone="info">watchlist: {job.watchlist_name ?? job.watchlist_id}</Badge>
                            ) : (
                              <div className="badge-row">
                                {job.tickers.map((ticker) => (
                                  <Badge key={`${job.name}-${ticker}`} tone={tickerTone()}>{ticker}</Badge>
                                ))}
                              </div>
                            )
                          ) : (
                            <span className="helper-text">No ticker source required</span>
                          )}
                        </td>
                        <td>{job.cron ?? "manual / not set"}</td>
                        <td><Badge tone={job.enabled ? "ok" : "neutral"}>{job.enabled ? "yes" : "no"}</Badge></td>
                        <td>
                          <div className="job-actions" role="group" aria-label={`Actions for ${job.name}`}>
                            <button
                              type="button"
                              className="icon-button icon-button-primary"
                              onClick={() => job.id && enqueueJob(job.id)}
                              disabled={busyJobId === job.id}
                              title="Enqueue run"
                              aria-label="Enqueue run"
                            >
                              <span aria-hidden="true">▶</span>
                            </button>
                            <button
                              type="button"
                              className="icon-button"
                              onClick={() => job.id && createWatchlistFromJob(job.id)}
                              disabled={busyJobId === job.id || job.job_type !== "proposal_generation"}
                              title="Create watchlist"
                              aria-label="Create watchlist"
                            >
                              <span aria-hidden="true">≡</span>
                            </button>
                            <button
                              type="button"
                              className={`icon-button${isEditing ? " is-active" : ""}`}
                              onClick={() => setEditingJobId(isEditing ? null : (job.id ?? null))}
                              disabled={busyJobId === job.id}
                              title={isEditing ? "Close editor" : "Edit job"}
                              aria-label={isEditing ? "Close editor" : "Edit job"}
                            >
                              <span aria-hidden="true">✎</span>
                            </button>
                            <button
                              type="button"
                              className="icon-button icon-button-danger"
                              onClick={() => job.id && deleteJob(job.id)}
                              disabled={busyJobId === job.id}
                              title="Delete job"
                              aria-label="Delete job"
                            >
                              <span aria-hidden="true">✕</span>
                            </button>
                          </div>
                        </td>
                      </tr>
                      {isEditing ? (
                        <tr>
                          <td colSpan={6}>
                            <form className="stack-form inline-job-editor" onSubmit={(event) => job.id && handleUpdateJob(event, job.id)}>
                              <div className="form-grid">
                                <label className="form-field">
                                  <span>Name</span>
                                  <input name="name" type="text" defaultValue={job.name} required />
                                </label>
                                <label className="form-field">
                                  <span>Workflow type</span>
                                  <select name="job_type" defaultValue={job.job_type}>
                                    <option value="proposal_generation">Proposal generation</option>
                                    <option value="recommendation_evaluation">Recommendation evaluation</option>
                                    <option value="plan_generation_tuning">Plan generation tuning</option>
                                    <option value="macro_sentiment_refresh">Macro context refresh</option>
                                    <option value="industry_sentiment_refresh">Industry context refresh</option>
                                  </select>
                                </label>
                              </div>
                              <div className="form-grid">
                                <label className="form-field">
                                  <span>Schedule</span>
                                  <input name="schedule" type="text" defaultValue={job.cron ?? ""} placeholder="30 9 * * 1,2,3,4,5" />
                                </label>
                                <div className="form-field">
                                  <span>Source rules</span>
                                  <div className="helper-text">Non-proposal workflows should leave ticker and watchlist fields empty.</div>
                                </div>
                              </div>
                              <div className="form-grid">
                                <label className="form-field">
                                  <span>Manual tickers</span>
                                  <input name="tickers" type="text" defaultValue={job.job_type === "proposal_generation" && !job.watchlist_id ? job.tickers.join(", ") : ""} placeholder="AAPL, MSFT, NVDA" />
                                </label>
                                <label className="form-field">
                                  <span>Watchlist</span>
                                  <select name="watchlist_id" defaultValue={job.job_type === "proposal_generation" && job.watchlist_id ? String(job.watchlist_id) : ""}>
                                    <option value="">No watchlist</option>
                                    {data.watchlists.map((watchlist) => (
                                      <option key={watchlist.id ?? watchlist.name} value={watchlist.id ?? ""}>
                                        {watchlist.name} · {watchlist.tickers.join(", ")}
                                      </option>
                                    ))}
                                  </select>
                                </label>
                              </div>
                              <label className="checkbox-field">
                                <input name="enabled" type="checkbox" defaultChecked={job.enabled} />
                                <span>Job enabled</span>
                              </label>
                              <div className="cluster">
                                <button type="submit" className="button" disabled={busyJobId === job.id}>Save changes</button>
                                <button type="button" className="button-subtle" onClick={() => setEditingJobId(null)} disabled={busyJobId === job.id}>Cancel</button>
                              </div>
                            </form>
                          </td>
                        </tr>
                      ) : null}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : null}
      </Card>
      </section>
    </>
  );
}
