import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { deleteJson, getJson, postForm, postJson } from "../api";
import { Badge, Card, DisclosureCard, EmptyState, ErrorState, HelpHint, LoadingState, PageHeader, SectionTitle, StatCard } from "../components/ui";
import { planGenerationTuningConfigTone, runTone } from "../utils";
import type {
  PlanGenerationTuningCandidate,
  PlanGenerationTuningConfigVersion,
  PlanGenerationTuningResponse,
  PlanGenerationTuningRun,
  PlanGenerationWalkForwardSummary,
} from "../types";

const tuningSpecDoc = "/docs?doc=specs-plan-generation-tuning-spec";

type ConfigPortfolioItem = {
  config: PlanGenerationTuningConfigVersion;
  is_current: boolean;
  nominal_performance: Record<string, unknown> | null;
  historical_performance: PerformanceSummary;
  active_period_performance: PerformanceSummary | null;
  active_periods: Array<Record<string, unknown>>;
};

type PerformanceSummary = {
  actionable_count: number;
  win_count: number;
  win_rate_percent: number | null;
  expected_value: number;
  ambiguous_count: number;
  record_count: number;
};

type JobRun = {
  id: number;
  job_id: number | null;
  status: string;
  mode: string;
  search_kind: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  duration_seconds: number | null;
  error_message: string | null;
  summary: Record<string, unknown>;
  timing: Record<string, unknown>;
  request: Record<string, unknown>;
  artifact_path: string | null;
  best_candidate: Record<string, unknown> | null;
  artifact: Record<string, unknown>;
};

type JobRunsResponse = { items: JobRun[]; total: number; limit: number; offset: number };
type PortfolioResponse = { items: ConfigPortfolioItem[]; total: number; limit: number; offset: number };
type TuningRunsResponse = { items: PlanGenerationTuningRun[]; total: number; limit: number; offset: number };
type WalkForwardResponse = { summary: PlanGenerationWalkForwardSummary; candidate_config: Record<string, unknown>; baseline_config: Record<string, unknown>; baseline_version: PlanGenerationTuningConfigVersion; candidate_label: string };
type LargeSearchCandidate = Record<string, unknown> & { config?: Record<string, number> };

function n(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function s(value: unknown): string {
  return typeof value === "string" ? value : value === null || value === undefined ? "" : String(value);
}

function formatPercent(value: number | null, digits = 2): string {
  return value === null ? "—" : `${value.toFixed(digits)}%`;
}

function formatNumber(value: number | null, digits = 4): string {
  return value === null ? "—" : value.toFixed(digits);
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function candidateMetric(candidate: PlanGenerationTuningCandidate | null, key: string): number | null {
  return candidate ? n(candidate.metric_breakdown[key]) : null;
}

function bestMetric(run: JobRun, key: string): number | null {
  return n(run.best_candidate?.[key]);
}

function largeSearchCandidates(run: JobRun | null): LargeSearchCandidate[] {
  const large = run?.artifact.large_plan_generation_tuning_search;
  if (!large || typeof large !== "object" || Array.isArray(large)) return [];
  const candidates = (large as Record<string, unknown>).top_candidates;
  return Array.isArray(candidates) ? candidates.filter((candidate): candidate is LargeSearchCandidate => Boolean(candidate && typeof candidate === "object" && !Array.isArray(candidate))) : [];
}

function largeCandidateLabel(candidate: LargeSearchCandidate, index: number): string {
  return `${s(candidate.phase) || "large"} #${index + 1} · WR ${formatPercent(n(candidate.validation_win_rate_percent))} · EV ${formatNumber(n(candidate.validation_expected_value))}`;
}

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function arrayValue(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object" && !Array.isArray(item))) : [];
}

function performanceLine(performance: PerformanceSummary | null): string {
  if (!performance) return "No records in active period";
  return `${performance.actionable_count} actionable · WR ${formatPercent(performance.win_rate_percent)} · EV ${formatNumber(performance.expected_value)} · ${performance.record_count} records`;
}

function candidateLabel(candidate: PlanGenerationTuningCandidate): string {
  const campaign = candidate.metric_breakdown.campaign;
  return `${candidate.is_baseline ? "baseline" : s(campaign) || "candidate"} #${candidate.rank ?? candidate.id ?? "?"}`;
}

function validationDepthLabel(depth: string | undefined): string {
  if (depth === "rescore_only") return "rescore only";
  if (depth === "frozen_input_plan_regeneration") return "frozen-input plan regen";
  if (depth === "full_orchestration_replay") return "full replay";
  return "depth unknown";
}

export function PlanGenerationTuningPage() {
  const [state, setState] = useState<PlanGenerationTuningResponse | null>(null);
  const [portfolio, setPortfolio] = useState<ConfigPortfolioItem[] | null>(null);
  const [jobRuns, setJobRuns] = useState<JobRun[] | null>(null);
  const [tuningRuns, setTuningRuns] = useState<PlanGenerationTuningRun[] | null>(null);
  const [jobOffset, setJobOffset] = useState(0);
  const [jobTotal, setJobTotal] = useState(0);
  const [selectedJobId, setSelectedJobId] = useState<number | null>(null);
  const [selectedTuningRunId, setSelectedTuningRunId] = useState<number | null>(null);
  const [selectedCandidateId, setSelectedCandidateId] = useState<number | null>(null);
  const [selectedLargeCandidateIndex, setSelectedLargeCandidateIndex] = useState(0);
  const [selectedConfigId, setSelectedConfigId] = useState<number | null>(null);
  const [walkForward, setWalkForward] = useState<WalkForwardResponse | null>(null);
  const [replayArtifacts, setReplayArtifacts] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [standardMode, setStandardMode] = useState<"point_in_time_replay" | "wide_point_in_time_replay" | "stored_plan_rescore" | "explore">("point_in_time_replay");
  const [largeCoarseCandidates, setLargeCoarseCandidates] = useState(20000);
  const [largeFineCandidates, setLargeFineCandidates] = useState(5000);
  const [lookbackDays, setLookbackDays] = useState(365);
  const [validationDays, setValidationDays] = useState(90);
  const [stepDays, setStepDays] = useState(30);
  const [minValidationResolved, setMinValidationResolved] = useState(8);

  const pageSize = 20;

  async function loadPortfolio(activeConfigId: number | null = state?.state.active_config_version_id ?? null) {
    const loadedPortfolio = await getJson<PortfolioResponse>("/api/plan-generation-tuning/configs/portfolio?limit=100");
    setPortfolio(loadedPortfolio.items);
    setSelectedConfigId((current) => current ?? activeConfigId ?? loadedPortfolio.items[0]?.config.id ?? null);
  }

  async function loadData(nextOffset = jobOffset) {
    try {
      setError(null);
      const [loadedState, loadedJobs, loadedTuningRuns] = await Promise.all([
        getJson<PlanGenerationTuningResponse>("/api/plan-generation-tuning"),
        getJson<JobRunsResponse>(`/api/plan-generation-tuning/job-runs?limit=${pageSize}&offset=${nextOffset}`),
        getJson<TuningRunsResponse>("/api/plan-generation-tuning/runs?limit=50"),
      ]);
      setState(loadedState);
      setJobRuns(loadedJobs.items);
      setJobTotal(loadedJobs.total);
      setJobOffset(loadedJobs.offset);
      setTuningRuns(loadedTuningRuns.items);
      setSelectedJobId((current) => current ?? loadedJobs.items[0]?.id ?? null);
      setSelectedTuningRunId((current) => current ?? loadedTuningRuns.items[0]?.id ?? null);
      void loadPortfolio(loadedState.state.active_config_version_id ?? null).catch((portfolioError: unknown) => {
        setError(portfolioError instanceof Error ? portfolioError.message : "Failed to load config portfolio");
      });
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to load tuning research state");
    }
  }

  useEffect(() => {
    void loadData(0);
  }, []);

  useEffect(() => {
    setSelectedLargeCandidateIndex(0);
  }, [selectedJobId]);

  useEffect(() => {
    if (!selectedTuningRunId) {
      setReplayArtifacts(null);
      return;
    }
    getJson<Record<string, unknown>>(`/api/plan-generation-tuning/runs/${selectedTuningRunId}/replay-artifacts`)
      .then(setReplayArtifacts)
      .catch(() => setReplayArtifacts(null));
  }, [selectedTuningRunId]);

  const selectedJob = useMemo(() => jobRuns?.find((run) => run.id === selectedJobId) ?? jobRuns?.[0] ?? null, [jobRuns, selectedJobId]);
  const selectedTuningRun = useMemo(() => tuningRuns?.find((run) => run.id === selectedTuningRunId) ?? tuningRuns?.[0] ?? null, [tuningRuns, selectedTuningRunId]);
  const selectedCandidate = useMemo(() => selectedTuningRun?.candidates.find((candidate) => candidate.id === selectedCandidateId) ?? selectedTuningRun?.candidates.find((candidate) => !candidate.is_baseline) ?? null, [selectedTuningRun, selectedCandidateId]);
  const selectedConfig = useMemo(() => portfolio?.find((item) => item.config.id === selectedConfigId) ?? portfolio?.find((item) => item.is_current) ?? null, [portfolio, selectedConfigId]);
  const activeConfig = useMemo(() => portfolio?.find((item) => item.is_current) ?? null, [portfolio]);
  const selectedJobLargeCandidates = useMemo(() => largeSearchCandidates(selectedJob), [selectedJob]);
  const selectedLargeCandidate = selectedJobLargeCandidates[selectedLargeCandidateIndex] ?? selectedJobLargeCandidates[0] ?? null;

  async function runTuning(mode: "point_in_time_replay" | "wide_point_in_time_replay" | "stored_plan_rescore" | "explore") {
    try {
      setSaving(`run-${mode}`);
      setError(null);
      await postForm<unknown>(`/api/plan-generation-tuning/run?mode=${encodeURIComponent(mode)}&apply=false`, {});
      await loadData(0);
    } catch (runError) {
      setError(runError instanceof Error ? runError.message : "Failed to queue tuning job");
    } finally {
      setSaving(null);
    }
  }

  async function runLargeSearch() {
    try {
      setSaving("run-large");
      setError(null);
      const query = new URLSearchParams({
        coarse_candidates: String(largeCoarseCandidates),
        fine_candidates: String(largeFineCandidates),
        top_k: "100",
        fine_seeds: "20",
      });
      await postForm<unknown>(`/api/plan-generation-tuning/large-search/run?${query.toString()}`, {});
      await loadData(0);
    } catch (runError) {
      setError(runError instanceof Error ? runError.message : "Failed to queue large search");
    } finally {
      setSaving(null);
    }
  }

  async function promoteConfig(configId: number | null) {
    if (!configId) return;
    try {
      setSaving(`promote-${configId}`);
      await postForm(`/api/plan-generation-tuning/configs/${configId}/promote`, {});
      await loadData(jobOffset);
    } catch (promoteError) {
      setError(promoteError instanceof Error ? promoteError.message : "Failed to promote config");
    } finally {
      setSaving(null);
    }
  }

  async function deleteConfig(configId: number | null) {
    if (!configId) return;
    try {
      setSaving(`delete-${configId}`);
      await deleteJson(`/api/plan-generation-tuning/configs/${configId}`);
      await loadData(jobOffset);
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : "Failed to delete config");
    } finally {
      setSaving(null);
    }
  }

  async function runWalkForward(target: "candidate" | "large-candidate" | "config") {
    try {
      setSaving(`walk-${target}`);
      setError(null);
      const payload: Record<string, unknown> = {
        baseline_config_version_id: activeConfig?.config.id ?? state?.state.active_config_version_id ?? null,
        lookback_days: lookbackDays,
        validation_days: validationDays,
        step_days: stepDays,
        min_validation_resolved: minValidationResolved,
      };
      if (target === "candidate") {
        if (!selectedCandidate?.id) throw new Error("Select a candidate first");
        payload.candidate_id = selectedCandidate.id;
      } else if (target === "large-candidate") {
        if (!selectedLargeCandidate?.config) throw new Error("Select a large-search candidate first");
        payload.candidate_config = selectedLargeCandidate.config;
        payload.candidate_label = `large-run-${selectedJob?.id ?? "unknown"}-candidate-${selectedLargeCandidateIndex + 1}`;
      } else {
        if (!selectedConfig?.config.id) throw new Error("Select a config first");
        payload.candidate_config_version_id = selectedConfig.config.id;
      }
      const response = await postJson<WalkForwardResponse>("/api/plan-generation-tuning/walk-forward", payload);
      setWalkForward(response);
    } catch (walkError) {
      setError(walkError instanceof Error ? walkError.message : "Failed to run walk-forward validation");
    } finally {
      setSaving(null);
    }
  }

  if (error) return <ErrorState message={error} />;
  if (!state || !jobRuns || !tuningRuns) return <LoadingState message="Loading tuning research…" />;

  return (
    <>
      <PageHeader
        kicker="Research"
        title="Plan-generation tuning"
        subtitle="Manage promoted configs, launch tuning jobs, inspect job history, and run focused baseline comparisons."
        actions={<HelpHint tooltip="Large searches are research-only. Revalidate selected configs/candidates with walk-forward before promotion." to={tuningSpecDoc} />}
      />

      <section className="card-grid">
        <Card>
          <SectionTitle kicker="Live baseline" title={activeConfig?.config.version_label ?? "No active config"} subtitle="Currently promoted plan-generation config used as the default comparison baseline." />
          <div className="metrics-grid top-gap-small">
            <StatCard label="Config id" value={activeConfig?.config.id ?? "—"} helper="Active version" />
            <StatCard label="Historical WR" value={formatPercent(activeConfig?.historical_performance.win_rate_percent ?? null)} helper={performanceLine(activeConfig?.historical_performance ?? null)} />
            <StatCard label="Active-period WR" value={formatPercent(activeConfig?.active_period_performance?.win_rate_percent ?? null)} helper={performanceLine(activeConfig?.active_period_performance ?? null)} />
            <StatCard label="Active periods" value={activeConfig?.active_periods.length ?? 0} helper="Inferred from promotion events" />
          </div>
        </Card>
        <Card>
          <SectionTitle kicker="Launch" title="Run tuning jobs" subtitle="Replay-based tuning is the default. Stored-plan rescore remains a manual diagnostic/regression mode." />
          <div className="cluster top-gap-small">
            <select className="input" value={standardMode} onChange={(event) => setStandardMode(event.target.value as "point_in_time_replay" | "wide_point_in_time_replay" | "stored_plan_rescore" | "explore")}>
              <option value="point_in_time_replay">Replay standard</option>
              <option value="wide_point_in_time_replay">Replay wide</option>
              <option value="stored_plan_rescore">Stored-plan diagnostic</option>
              <option value="explore">Stored-plan exploratory</option>
            </select>
            <button className="button" type="button" disabled={saving !== null} onClick={() => void runTuning(standardMode)}>{saving === `run-${standardMode}` ? "… Queueing" : "Queue tuning job"}</button>
          </div>
          <div className="cluster top-gap-medium">
            <label className="form-field compact-field"><span>Coarse</span><input type="number" min="1" max="1000000" value={largeCoarseCandidates} onChange={(event) => setLargeCoarseCandidates(Number(event.target.value || 1))} /></label>
            <label className="form-field compact-field"><span>Fine</span><input type="number" min="0" max="500000" value={largeFineCandidates} onChange={(event) => setLargeFineCandidates(Number(event.target.value || 0))} /></label>
            <button className="button-secondary" type="button" disabled={saving !== null} onClick={() => void runLargeSearch()}>{saving === "run-large" ? "… Queueing" : "Queue large search"}</button>
          </div>
        </Card>
      </section>

      <DisclosureCard kicker="Configurations" title="Promoted configuration management" subtitle="Nominal performance comes from the source tuning candidate when available; historical performance rescoring uses all current eligible records.">
        <div className="data-stack top-gap-small">
          {!portfolio ? <LoadingState message="Loading config portfolio…" /> : portfolio.map((item) => (
            <article key={item.config.id ?? item.config.version_label} className={`data-card ${selectedConfig?.config.id === item.config.id ? "data-card-selected" : ""}`}>
              <div className="data-card-header">
                <button className="button-link" type="button" onClick={() => setSelectedConfigId(item.config.id)}>{item.config.version_label}</button>
                <div className="cluster"><Badge tone={item.is_current ? "ok" : planGenerationTuningConfigTone(item.config.status)}>{item.is_current ? "live" : item.config.status}</Badge><Badge>{item.config.source}</Badge><Badge>#{item.config.id ?? "?"}</Badge></div>
              </div>
              <div className="metrics-grid top-gap-small">
                <StatCard label="Historical" value={formatPercent(item.historical_performance.win_rate_percent)} helper={performanceLine(item.historical_performance)} />
                <StatCard label="Active period" value={formatPercent(item.active_period_performance?.win_rate_percent ?? null)} helper={performanceLine(item.active_period_performance)} />
                <StatCard label="Nominal source" value={item.nominal_performance ? `rank ${s((item.nominal_performance.metrics as Record<string, unknown> | undefined)?.rank) || s(item.nominal_performance.rank) || "—"}` : "—"} helper={item.nominal_performance ? "Source candidate data available" : "Baseline/manual config"} />
                <StatCard label="Periods" value={item.active_periods.length} helper={item.active_periods.map((period) => `${formatDate(s(period.started_at))} → ${period.ended_at ? formatDate(s(period.ended_at)) : "now"}`).join("; ") || "Never active"} />
              </div>
              <div className="cluster top-gap-small">
                <button className="button-secondary" type="button" disabled={saving !== null || item.is_current || item.config.status === "deleted"} onClick={() => void promoteConfig(item.config.id)}>{saving === `promote-${item.config.id}` ? "… Promoting" : "Promote live"}</button>
                <button className="button-danger" type="button" disabled={saving !== null || item.is_current || item.config.status === "deleted"} onClick={() => void deleteConfig(item.config.id)}>{saving === `delete-${item.config.id}` ? "… Deleting" : "Delete"}</button>
                <button className="button-secondary" type="button" disabled={saving !== null} onClick={() => void runWalkForward("config")}>Compare selected config</button>
              </div>
            </article>
          ))}
        </div>
      </DisclosureCard>

      <section className="card-grid">
        <Card>
          <SectionTitle kicker="Job history" title="Tuning job runs" subtitle="Paged history includes standard/wide/exploratory tuning and large-search artifact jobs." />
          <div className="data-stack top-gap-small">
            {jobRuns.length === 0 ? <EmptyState message="No tuning job runs yet." /> : jobRuns.map((run) => (
              <button key={run.id} type="button" className={`data-card data-card-button ${selectedJob?.id === run.id ? "data-card-selected" : ""}`} onClick={() => setSelectedJobId(run.id)}>
                <div className="data-card-header">
                  <div className="cluster"><Badge tone={runTone(run.status)}>{run.status}</Badge><Badge>{run.mode}</Badge><Badge>#{run.id}</Badge></div>
                  <div className="helper-text">{formatDate(run.started_at ?? run.created_at)} · {run.duration_seconds !== null ? `${run.duration_seconds.toFixed(1)}s` : "queued"}</div>
                </div>
                <div className="helper-text top-gap-small">Best: WR {formatPercent(bestMetric(run, "validation_win_rate_percent"))} · EV {formatNumber(bestMetric(run, "validation_expected_value"))} · actionable {bestMetric(run, "validation_actionable_count") ?? "—"}</div>
              </button>
            ))}
          </div>
          <div className="cluster top-gap-small">
            <button className="button-secondary" disabled={jobOffset <= 0} onClick={() => void loadData(Math.max(0, jobOffset - pageSize))}>Previous</button>
            <span className="helper-text">{jobOffset + 1}-{Math.min(jobOffset + pageSize, jobTotal)} of {jobTotal}</span>
            <button className="button-secondary" disabled={jobOffset + pageSize >= jobTotal} onClick={() => void loadData(jobOffset + pageSize)}>Next</button>
          </div>
        </Card>
        <Card>
          <SectionTitle kicker="Selected job" title={selectedJob ? `Run #${selectedJob.id}` : "No run selected"} subtitle="Expand raw payloads only when investigating details." />
          {selectedJob ? (
            <div className="stack-page">
              <section className="metrics-grid top-gap-small">
                <StatCard label="Status" value={selectedJob.status} helper={selectedJob.mode} />
                <StatCard label="Started" value={formatDate(selectedJob.started_at)} helper={`Completed ${formatDate(selectedJob.completed_at)}`} />
                <StatCard label="Best validation WR" value={formatPercent(bestMetric(selectedJob, "validation_win_rate_percent"))} helper={`EV ${formatNumber(bestMetric(selectedJob, "validation_expected_value"))}`} />
                <StatCard label="Artifact" value={selectedJob.artifact_path ? "yes" : "—"} helper={selectedJob.artifact_path ?? "No artifact path"} />
              </section>
              <details><summary className="helper-text">Best candidate JSON</summary><pre className="code-block top-gap-small">{JSON.stringify(selectedJob.best_candidate, null, 2)}</pre></details>
              <details><summary className="helper-text">Run summary/artifact JSON</summary><pre className="code-block top-gap-small">{JSON.stringify({ summary: selectedJob.summary, request: selectedJob.request, artifact: selectedJob.artifact }, null, 2)}</pre></details>
            </div>
          ) : <EmptyState message="Select a job run." />}
        </Card>
      </section>

      <DisclosureCard kicker="Tuning run detail" title={selectedTuningRun ? `Run #${selectedTuningRun.id}` : "No tuning run selected"} subtitle="Replay-aware visibility for the selected persisted tuning run.">
        {selectedTuningRun ? (() => {
          const summary = selectedTuningRun.summary;
          const replayExecution = objectValue(summary.candidate_replay_execution);
          const aggregate = objectValue(replayExecution.aggregate);
          const rerank = arrayValue(aggregate.rerank);
          const results = arrayValue(aggregate.results);
          const replayPromotion = objectValue(summary.replay_promotion);
          const sourceMode = s(summary.tuning_source_mode) || (selectedTuningRun.filters.replay_mode ? "point_in_time_replay" : "stored_plan_rescore");
          return <div className="stack-page">
            <section className="metrics-grid top-gap-small">
              <StatCard label="Tuning mode" value={sourceMode} helper={`run mode ${selectedTuningRun.mode}`} />
              <StatCard label="Tier A evidence" value={selectedTuningRun.eligible_tier_a_count} helper={`${selectedTuningRun.eligible_record_count} eligible records`} />
              <StatCard label="Replay winner" value={String(aggregate.replay_winner_candidate_id ?? replayPromotion.replay_winner_candidate_id ?? "—")} helper={`promotion ${summary.promotion_applied ? "applied" : "blocked"}`} />
              <StatCard label="Replay execution" value={String(replayExecution.executed_run_count ?? "—")} helper="candidate replay slice runs" />
            </section>
            {results.length > 0 ? <div className="table-wrapper top-gap-small"><table className="data-table"><thead><tr><th>candidate</th><th>tier counts</th><th>outcomes</th><th>resolution split</th><th>replay link</th></tr></thead><tbody>
              {results.map((result) => <tr key={`${result.candidate_id}-${result.replay_batch_id}`}><td>#{String(result.candidate_rank ?? result.candidate_id ?? "?")}</td><td>{JSON.stringify(result.tier_counts ?? {})}</td><td>{JSON.stringify(result.outcome_counts ?? {})}</td><td>{JSON.stringify(result.resolution_source_counts ?? {})}</td><td>{result.replay_batch_id ? <Link to={`/research/historical-replay?batch=${result.replay_batch_id}`} className="button-link">Batch #{String(result.replay_batch_id)}</Link> : "—"}</td></tr>)}
            </tbody></table></div> : <div className="helper-text top-gap-small">No per-candidate replay aggregate stored for this run yet.</div>}
            {rerank.length > 0 ? <div className="data-card top-gap-small"><div className="data-card-header"><div className="data-card-title">Replay rerank</div><Badge>auditable</Badge></div><div className="helper-text">{rerank.map((item) => `#${String(item.candidate_rank ?? item.candidate_id)} score ${String(item.replay_score ?? "—")} · Tier A ${String(item.tier_a_count ?? 0)} · W/L ${String(item.win_count ?? 0)}/${String(item.loss_count ?? 0)}`).join("; ")}</div></div> : null}
            {replayArtifacts && arrayValue(replayArtifacts.batches).length > 0 ? <details><summary className="helper-text">Replay artifact links: slices, plans, outcomes</summary><pre className="code-block top-gap-small">{JSON.stringify(replayArtifacts, null, 2)}</pre></details> : null}
            {replayPromotion.promotion_rejection_reasons ? <div className="helper-text top-gap-small">Promotion rejection: {JSON.stringify(replayPromotion.promotion_rejection_reasons)}</div> : null}
          </div>;
        })() : <EmptyState message="Select a tuning run." />}
      </DisclosureCard>

      <DisclosureCard kicker="Candidates" title="Custom walk-forward validation" subtitle="Select a persisted tuning candidate or a research-only large-search candidate, then compare it against the promoted baseline.">
        <div className="data-stack top-gap-small">
          <div className="data-card">
            <div className="data-card-header"><div className="data-card-title">Standard/wide/exploratory candidates</div><Badge>promotable source</Badge></div>
            <div className="cluster top-gap-small">
              <select className="input" value={selectedTuningRunId ?? ""} onChange={(event) => { setSelectedTuningRunId(Number(event.target.value)); setSelectedCandidateId(null); }}>
                {tuningRuns.map((run) => <option key={run.id ?? run.created_at} value={run.id ?? ""}>Run #{run.id} · {run.mode} · {formatDate(run.started_at ?? run.created_at)}</option>)}
              </select>
              <select className="input" value={selectedCandidate?.id ?? ""} onChange={(event) => setSelectedCandidateId(Number(event.target.value))}>
                {selectedTuningRun?.candidates.map((candidate) => <option key={candidate.id ?? `${candidate.rank}`} value={candidate.id ?? ""}>{candidateLabel(candidate)} · WR {formatPercent(candidateMetric(candidate, "validation_win_rate_percent"))} · EV {formatNumber(candidateMetric(candidate, "validation_expected_value"))}</option>)}
              </select>
              <button className="button" type="button" disabled={saving !== null || !selectedCandidate} onClick={() => void runWalkForward("candidate")}>{saving === "walk-candidate" ? "… Validating" : "Walk-forward candidate"}</button>
            </div>
            {selectedCandidate ? <div className="cluster top-gap-small">
              <Badge tone={selectedCandidate.validation_depth === "full_orchestration_replay" ? "warning" : "neutral"}>{validationDepthLabel(selectedCandidate.validation_depth)}</Badge>
              <span className="helper-text">{selectedCandidate.validation_depth_reason || "Validation depth explains the cheapest safe recomputation boundary for this candidate."}</span>
            </div> : null}
          </div>
          <div className="data-card">
            <div className="data-card-header"><div className="data-card-title">Large-search candidates</div><Badge tone="warning">research only</Badge></div>
            {selectedJobLargeCandidates.length > 0 ? (
              <div className="cluster top-gap-small">
                <select className="input" value={selectedLargeCandidateIndex} onChange={(event) => setSelectedLargeCandidateIndex(Number(event.target.value || 0))}>
                  {selectedJobLargeCandidates.map((candidate, index) => <option key={`${selectedJob?.id ?? "large"}-${index}`} value={index}>{largeCandidateLabel(candidate, index)}</option>)}
                </select>
                <button className="button-secondary" type="button" disabled={saving !== null || !selectedLargeCandidate?.config} onClick={() => void runWalkForward("large-candidate")}>{saving === "walk-large-candidate" ? "… Validating" : "Walk-forward large candidate"}</button>
              </div>
            ) : <div className="helper-text top-gap-small">Select a completed large-search job in Job history to validate one of its top candidates. Large-search candidates are raw research configs and are not promotion-capable by themselves.</div>}
          </div>
        </div>
        <div className="cluster top-gap-small">
          <label className="form-field compact-field"><span>Lookback days</span><input type="number" min="30" max="3650" value={lookbackDays} onChange={(event) => setLookbackDays(Number(event.target.value || 365))} /></label>
          <label className="form-field compact-field"><span>Validation days</span><input type="number" min="5" max="730" value={validationDays} onChange={(event) => setValidationDays(Number(event.target.value || 90))} /></label>
          <label className="form-field compact-field"><span>Step days</span><input type="number" min="1" max="365" value={stepDays} onChange={(event) => setStepDays(Number(event.target.value || 30))} /></label>
          <label className="form-field compact-field"><span>Min resolved</span><input type="number" min="1" max="500" value={minValidationResolved} onChange={(event) => setMinValidationResolved(Number(event.target.value || 8))} /></label>
        </div>
      </DisclosureCard>

      <Card>
        <SectionTitle kicker="Comparison" title="Baseline delta" subtitle="Latest selected walk-forward comparison against the currently promoted baseline." />
        {walkForward ? (
          <div className="stack-page">
            <section className="metrics-grid top-gap-small">
              <StatCard label="Promotion" value={walkForward.summary.promotion_recommended ? "recommended" : "blocked"} helper={walkForward.summary.promotion_rationale} />
              <StatCard label="Qualified slices" value={walkForward.summary.qualified_slices} helper={`${walkForward.summary.total_slices} total`} />
              <StatCard label="Avg WR delta" value={formatPercent(walkForward.summary.average_win_rate_delta)} helper="Candidate minus baseline" />
              <StatCard label="Avg EV delta" value={formatNumber(walkForward.summary.average_expected_value_delta)} helper="Candidate minus baseline" />
            </section>
            <div className="table-wrapper top-gap-small">
              <table className="data-table"><thead><tr><th>slice</th><th>baseline act/WR/EV</th><th>candidate act/WR/EV</th><th>delta</th><th>status</th></tr></thead><tbody>
                {walkForward.summary.slices.map((slice) => <tr key={slice.slice_index}><td>{slice.window_label}</td><td>{slice.baseline_actionable_count} · {formatPercent(slice.baseline_win_rate_percent)} · {formatNumber(slice.baseline_expected_value)}</td><td>{slice.candidate_actionable_count} · {formatPercent(slice.candidate_win_rate_percent)} · {formatNumber(slice.candidate_expected_value)}</td><td>{formatPercent(slice.win_rate_delta)} · {formatNumber(slice.expected_value_delta)}</td><td><Badge tone={slice.sample_status === "qualified" ? "ok" : "warning"}>{slice.sample_status}</Badge></td></tr>)}
              </tbody></table>
            </div>
          </div>
        ) : <EmptyState message="Select a config or candidate, set validation windows, then run walk-forward validation." />}
      </Card>
    </>
  );
}
