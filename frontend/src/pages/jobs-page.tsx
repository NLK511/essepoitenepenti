import { FormEvent, Fragment, useEffect, useMemo, useState } from "react";
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

type JobCategory = "core" | "research" | "maintenance";

function isProposalJobType(jobType: JobType | string): boolean {
  return jobType === "proposal_generation";
}

function jobCategory(jobType: JobType | string): JobCategory {
  if (jobType === "proposal_generation" || jobType === "recommendation_evaluation") {
    return "core";
  }
  if (jobType === "plan_generation_tuning" || jobType === "performance_assessment") {
    return "research";
  }
  return "maintenance";
}

function jobCategoryLabel(category: JobCategory): string {
  if (category === "core") {
    return "core";
  }
  if (category === "research") {
    return "research";
  }
  return "maintenance";
}

function jobCategoryTone(category: JobCategory): "ok" | "info" | "warning" {
  if (category === "core") {
    return "ok";
  }
  if (category === "research") {
    return "info";
  }
  return "warning";
}

function workflowLabel(jobType: JobType | string): string {
  switch (jobType) {
    case "proposal_generation":
      return "Generate recommendations";
    case "recommendation_evaluation":
      return "Evaluate recommendations";
    case "plan_generation_tuning":
      return "Run plan tuning";
    case "performance_assessment":
      return "Run performance assessment";
    case "macro_context_refresh":
      return "Refresh macro context";
    case "industry_context_refresh":
      return "Refresh industry context";
    default:
      return jobTypeLabel(jobType);
  }
}

function groupedJobs(jobs: Job[]): Array<{ category: JobCategory; title: string; subtitle: string; items: Job[] }> {
  const groups: Array<{ category: JobCategory; title: string; subtitle: string; items: Job[] }> = [
    {
      category: "core",
      title: "Core workflows",
      subtitle: "Day-to-day recommendation generation and evaluation.",
      items: jobs.filter((job) => jobCategory(job.job_type) === "core"),
    },
    {
      category: "research",
      title: "Research workflows",
      subtitle: "Advanced review and tuning workflows.",
      items: jobs.filter((job) => jobCategory(job.job_type) === "research"),
    },
    {
      category: "maintenance",
      title: "Maintenance workflows",
      subtitle: "Context refresh and supporting upkeep.",
      items: jobs.filter((job) => jobCategory(job.job_type) === "maintenance"),
    },
  ];
  return groups;
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

  const groups = useMemo(() => groupedJobs(data?.jobs ?? []), [data]);

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
        action: run?.id ? () => navigate(`/runs/${run.id}`) : undefined,
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
        title="Launch workflows by goal, not by internal job type."
        actions={
          <>
            <HelpHint tooltip="Jobs are grouped into core, research, and maintenance workflows." to={jobsDoc} />
            <Link to="/jobs/watchlists" className="button-secondary">
              Manage watchlists
            </Link>
          </>
        }
      />
      {error ? <ErrorState message={error} /> : null}
      <section className="metrics-grid top-gap">
        <StatCard label="Jobs" value={data?.jobs.length ?? "—"} helper="Saved workflows" />
        <StatCard label="Core workflows" value={data?.jobs.filter((job) => jobCategory(job.job_type) === "core").length ?? "—"} helper="Generation and evaluation" />
        <StatCard label="Research workflows" value={data?.jobs.filter((job) => jobCategory(job.job_type) === "research").length ?? "—"} helper="Tuning and assessment" />
        <StatCard label="Maintenance workflows" value={data?.jobs.filter((job) => jobCategory(job.job_type) === "maintenance").length ?? "—"} helper="Context refresh" />
      </section>
      <section className="two-column top-gap">
        <Card className="sticky-toolbar">
          <SectionTitle kicker="Create" title="New workflow" subtitle="Choose the workflow goal first. Only proposal generation needs a watchlist or manual tickers." actions={<HelpHint tooltip="Proposal generation uses watchlists or tickers. Evaluation, tuning, and refresh workflows use stored data instead." to={jobsDoc} />} />
          <form className="stack-form" onSubmit={handleCreateJob}>
            <div className="form-grid">
              <label className="form-field">
                <span>Name</span>
                <input name="name" type="text" placeholder="Morning megacaps" required />
              </label>
              <label className="form-field">
                <span>Workflow</span>
                <select name="job_type" defaultValue="proposal_generation">
                  <optgroup label="Core workflows">
                    <option value="proposal_generation">Generate recommendations</option>
                    <option value="recommendation_evaluation">Evaluate recommendations</option>
                  </optgroup>
                  <optgroup label="Research workflows">
                    <option value="plan_generation_tuning">Run plan tuning</option>
                    <option value="performance_assessment">Run performance assessment</option>
                  </optgroup>
                  <optgroup label="Maintenance workflows">
                    <option value="macro_context_refresh">Refresh macro context</option>
                    <option value="industry_context_refresh">Refresh industry context</option>
                  </optgroup>
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
                <div className="helper-text">Only recommendation generation uses tickers or watchlists. Everything else works from stored app data.</div>
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
              {submitting ? "Creating…" : "Create workflow"}
            </button>
          </form>
        </Card>
        <Card>
          <SectionTitle kicker="Saved workflows" title="Run, edit, and delete" subtitle="Core workflows should dominate daily use. Research and maintenance flows stay grouped below." actions={<HelpHint tooltip="Each saved workflow shows its category, source scope, schedule, and enabled state." to={jobsDoc} />} />
          {!data && !error ? <LoadingState message="Loading workflows…" /> : null}
          {data && data.jobs.length === 0 ? <EmptyState message="No workflows created yet." /> : null}
          {data ? (
            <div className="stack-page top-gap-small">
              {groups.map((group) => (
                <div key={group.category}>
                  <SectionTitle title={group.title} subtitle={group.subtitle} />
                  {group.items.length === 0 ? (
                    <EmptyState message={`No ${group.title.toLowerCase()} yet.`} />
                  ) : (
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
                          {group.items.map((job) => {
                            const isEditing = editingJobId === job.id;
                            const category = jobCategory(job.job_type);
                            return (
                              <Fragment key={job.id ?? job.name}>
                                <tr>
                                  <td>{job.name}</td>
                                  <td>
                                    <div className="badge-row">
                                      <Badge tone={jobCategoryTone(category)}>{jobCategoryLabel(category)}</Badge>
                                      <Badge tone="neutral">{workflowLabel(job.job_type)}</Badge>
                                    </div>
                                    <div className="helper-text top-gap-small">{jobTypeLabel(job.job_type)}</div>
                                  </td>
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
                                      <span className="helper-text">Stored app data</span>
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
                                        title={isEditing ? "Close editor" : "Edit workflow"}
                                        aria-label={isEditing ? "Close editor" : "Edit workflow"}
                                      >
                                        <span aria-hidden="true">✎</span>
                                      </button>
                                      <button
                                        type="button"
                                        className="icon-button icon-button-danger"
                                        onClick={() => job.id && deleteJob(job.id)}
                                        disabled={busyJobId === job.id}
                                        title="Delete workflow"
                                        aria-label="Delete workflow"
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
                                            <span>Workflow</span>
                                            <select name="job_type" defaultValue={job.job_type}>
                                              <optgroup label="Core workflows">
                                                <option value="proposal_generation">Generate recommendations</option>
                                                <option value="recommendation_evaluation">Evaluate recommendations</option>
                                              </optgroup>
                                              <optgroup label="Research workflows">
                                                <option value="plan_generation_tuning">Run plan tuning</option>
                                                <option value="performance_assessment">Run performance assessment</option>
                                              </optgroup>
                                              <optgroup label="Maintenance workflows">
                                                <option value="macro_context_refresh">Refresh macro context</option>
                                                <option value="industry_context_refresh">Refresh industry context</option>
                                              </optgroup>
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
                                            <div className="helper-text">Leave tickers and watchlist empty for evaluation, research, and maintenance workflows.</div>
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
                                          <span>Workflow enabled</span>
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
                  )}
                </div>
              ))}
            </div>
          ) : null}
        </Card>
      </section>
    </>
  );
}
