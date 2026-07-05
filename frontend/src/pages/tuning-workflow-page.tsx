import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { deleteJson, getJson, patchJson, postJson } from "../api";
import { Badge, Card, DisclosureCard, EmptyState, ErrorState, LoadingState, PageHeader, SectionTitle, StatCard } from "../components/ui";
import type { TuningExperiment, TuningExperimentResponse, TuningExperimentsResponse, Watchlist } from "../types";

const specDoc = "/docs?doc=specs-tuning-workflow-ux-spec";

function fieldText(value: unknown): string {
  if (Array.isArray(value)) return value.join(", ");
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function stageTone(stage: string): "ok" | "warning" | "danger" | "neutral" | "info" {
  if (stage.includes("complete") || stage.includes("promoted")) return "ok";
  if (stage.includes("blocked") || stage.includes("incomplete")) return "warning";
  if (stage.includes("rejected") || stage.includes("failed")) return "danger";
  if (stage.includes("needed") || stage.includes("running")) return "info";
  return "neutral";
}

function SectionStatusCard(props: { title: string; section: Record<string, unknown> | undefined; subtitle: string }) {
  const status = String(props.section?.status ?? "unknown");
  return (
    <Card>
      <SectionTitle kicker="workflow card" title={props.title} subtitle={props.subtitle} />
      <div className="cluster top-gap-small"><Badge tone={stageTone(status)}>{status}</Badge></div>
      {props.section?.reason ? <div className="helper-text top-gap-small">{String(props.section.reason)}</div> : null}
      {Array.isArray(props.section?.blockers) && props.section.blockers.length ? <div className="helper-text top-gap-small">Blocked by: {props.section.blockers.join(", ")}</div> : null}
      {Array.isArray(props.section?.warnings) && props.section.warnings.length ? <div className="helper-text top-gap-small">Warnings: {props.section.warnings.join(", ")}</div> : null}
      {typeof props.section?.progress === "object" && props.section.progress !== null ? <div className="helper-text top-gap-small">Progress: {String((props.section.progress as Record<string, unknown>).completed_count ?? 0)}/{String((props.section.progress as Record<string, unknown>).slice_count ?? 0)} slices · failed/stale: {String((props.section.progress as Record<string, unknown>).failed_count ?? 0)}/{String((props.section.progress as Record<string, unknown>).stale_count ?? 0)}</div> : null}
      {typeof props.section?.comparisons === "object" && props.section.comparisons !== null ? <div className="helper-text top-gap-small">Comparisons available for {Object.keys(props.section.comparisons as Record<string, unknown>).length} candidate(s).</div> : null}
    </Card>
  );
}

export function TuningWorkflowPage() {
  const [experiments, setExperiments] = useState<TuningExperimentsResponse | null>(null);
  const [watchlists, setWatchlists] = useState<Watchlist[]>([]);
  const [selected, setSelected] = useState<TuningExperiment | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [baselineBatchId, setBaselineBatchId] = useState("");
  const [candidateBatchId, setCandidateBatchId] = useState("");
  const [stabilityStatus, setStabilityStatus] = useState("warning");
  const [form, setForm] = useState({
    name: "",
    hypothesis: "",
    universe_mode: "watchlist",
    watchlist_id: "",
    tickers: "AAPL,MSFT,NVDA",
    discovery_start: "",
    discovery_end: "",
    replay_start: "",
    replay_end: "",
    holdout_start: "",
    holdout_end: "",
    objective: "balanced_score",
    discovery_candidate_count: "1000",
    retained_candidate_count: "50",
    replay_candidate_count: "5",
    baseline_source: "current_active_config",
    promotion_target: "paper_config",
  });

  async function load(selectId?: number, refreshList = true) {
    setLoading(true);
    setError(null);
    try {
      let list = experiments;
      if (refreshList || !list) {
        const [experimentList, watchlistList] = await Promise.all([
          getJson<TuningExperimentsResponse>("/api/tuning-workflow/experiments?limit=25"),
          getJson<Watchlist[]>("/api/watchlists"),
        ]);
        list = experimentList;
        setExperiments(list);
        setWatchlists(watchlistList);
        setForm((current) => current.watchlist_id || !watchlistList[0]?.id ? current : { ...current, watchlist_id: String(watchlistList[0].id) });
      }
      const id = selectId ?? (refreshList ? list.experiments[0]?.id : selected?.id ?? list.experiments[0]?.id);
      if (id) {
        const detail = await getJson<TuningExperimentResponse>(`/api/tuning-workflow/experiments/${id}`);
        setSelected(detail.experiment);
      } else {
        setSelected(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load tuning workflow");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); }, []);

  useEffect(() => {
    if (!selected) return;
    setForm((current) => ({
      ...current,
      name: selected.name,
      hypothesis: selected.hypothesis ?? "",
      universe_mode: selected.universe.watchlist_id ? "watchlist" : "tickers",
      watchlist_id: selected.universe.watchlist_id ? String(selected.universe.watchlist_id) : current.watchlist_id,
      tickers: Array.isArray(selected.universe.tickers) ? selected.universe.tickers.join(",") : current.tickers,
      discovery_start: String(selected.windows.discovery_start ?? ""),
      discovery_end: String(selected.windows.discovery_end ?? ""),
      replay_start: String(selected.windows.replay_start ?? ""),
      replay_end: String(selected.windows.replay_end ?? ""),
      holdout_start: String(selected.windows.holdout_start ?? ""),
      holdout_end: String(selected.windows.holdout_end ?? ""),
      objective: selected.objective,
      discovery_candidate_count: String(selected.discovery_settings.candidate_count ?? current.discovery_candidate_count),
      retained_candidate_count: String(selected.discovery_settings.candidate_pool_keep_count ?? current.retained_candidate_count),
      replay_candidate_count: String(selected.replay_settings.max_candidates ?? current.replay_candidate_count),
      baseline_source: String(selected.baseline.source ?? current.baseline_source),
      promotion_target: selected.promotion_target,
    }));
  }, [selected?.id]);

  async function createExperiment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const universe = form.universe_mode === "watchlist"
        ? { watchlist_id: Number(form.watchlist_id), watchlist_name: watchlists.find((item) => String(item.id) === form.watchlist_id)?.name }
        : { tickers: form.tickers.split(",").map((ticker) => ticker.trim().toUpperCase()).filter(Boolean) };
      const response = await postJson<TuningExperimentResponse>("/api/tuning-workflow/experiments", {
        name: form.name,
        hypothesis: form.hypothesis,
        universe,
        windows: {
          discovery_start: form.discovery_start,
          discovery_end: form.discovery_end,
          replay_start: form.replay_start,
          replay_end: form.replay_end,
          holdout_start: form.holdout_start,
          holdout_end: form.holdout_end,
        },
        objective: form.objective,
        baseline: { source: form.baseline_source },
        promotion_target: form.promotion_target,
        discovery_settings: { search_size: "large", candidate_count: Number(form.discovery_candidate_count), candidate_pool_keep_count: Number(form.retained_candidate_count) },
        replay_settings: { max_candidates: Number(form.replay_candidate_count), max_concurrency: 1, cache_only: true },
      });
      setForm((current) => ({ ...current, name: "", hypothesis: "" }));
      await load(response.experiment.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create experiment");
    } finally {
      setSaving(false);
    }
  }

  async function workflowAction(path: string, body: Record<string, unknown> = {}) {
    if (!selected) return;
    setSaving(true);
    setError(null);
    try {
      const response = await postJson<TuningExperimentResponse>(path, body);
      setSelected(response.experiment);
      void load(response.experiment.id, true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Workflow action failed");
    } finally {
      setSaving(false);
    }
  }

  async function updateSelectedFromForm() {
    if (!selected) return;
    setSaving(true);
    setError(null);
    try {
      const universe = form.universe_mode === "watchlist"
        ? { watchlist_id: Number(form.watchlist_id), watchlist_name: watchlists.find((item) => String(item.id) === form.watchlist_id)?.name }
        : { tickers: form.tickers.split(",").map((ticker) => ticker.trim().toUpperCase()).filter(Boolean) };
      const response = await patchJson<TuningExperimentResponse>(`/api/tuning-workflow/experiments/${selected.id}`, {
        name: form.name || selected.name,
        hypothesis: form.hypothesis,
        universe,
        windows: {
          discovery_start: form.discovery_start,
          discovery_end: form.discovery_end,
          replay_start: form.replay_start,
          replay_end: form.replay_end,
          holdout_start: form.holdout_start,
          holdout_end: form.holdout_end,
        },
        objective: form.objective,
        baseline: { source: form.baseline_source },
        promotion_target: form.promotion_target,
        discovery_settings: { search_size: "large", candidate_count: Number(form.discovery_candidate_count), candidate_pool_keep_count: Number(form.retained_candidate_count) },
        replay_settings: { max_candidates: Number(form.replay_candidate_count), max_concurrency: 1, cache_only: true },
      });
      await load(response.experiment.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update experiment");
    } finally {
      setSaving(false);
    }
  }

  async function deleteSelected() {
    if (!selected || !confirm(`Delete experiment ${selected.name}? Replay batches and run history are not deleted.`)) return;
    setSaving(true);
    setError(null);
    try {
      await deleteJson(`/api/tuning-workflow/experiments/${selected.id}`);
      await load(undefined, true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete experiment");
    } finally {
      setSaving(false);
    }
  }

  async function archiveSelected() {
    if (!selected) return;
    setSaving(true);
    setError(null);
    try {
      await postJson<TuningExperimentResponse>(`/api/tuning-workflow/experiments/${selected.id}/archive`, {});
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to archive experiment");
    } finally {
      setSaving(false);
    }
  }

  const candidates = useMemo(() => {
    const raw = selected?.sections.candidate_pool?.candidates;
    return Array.isArray(raw) ? raw.filter((item): item is Record<string, unknown> => typeof item === "object" && item !== null) : [];
  }, [selected]);
  const shortlistedIds = useMemo(() => {
    const raw = selected?.sections.shortlist?.candidate_ids;
    return Array.isArray(raw) ? raw.map(String) : [];
  }, [selected]);
  const firstShortlistedId = shortlistedIds[0] ?? String(candidates[0]?.id ?? "");

  const funnel = useMemo(() => {
    const sections = selected?.sections ?? {};
    return {
      pool: fieldText(sections.candidate_pool?.status),
      shortlist: fieldText(sections.shortlist?.status),
      replay: fieldText(sections.candidate_replay_validation?.status),
      proposal: fieldText(sections.promotion_proposal?.status),
    };
  }, [selected]);

  return (
    <>
      <PageHeader
        kicker="Research workflow"
        title="Tuning Workflow"
        subtitle="One operator path from experiment setup to replay validation, holdout checks, and guarded promotion. Discovery-only evidence is never shown as promotion evidence."
        actions={<><Link to={specDoc} className="button-secondary">Spec</Link><Link to="/research/plan-generation-tuning" className="button-subtle">Advanced tuning</Link></>}
      />
      <div className="page-stack">
        {error ? <ErrorState message={error} /> : null}
        {loading ? <LoadingState message="Loading tuning workflow…" /> : null}

        {!loading ? (
          <section className="split-layout">
            <Card>
              <SectionTitle kicker="Create experiment" title="Setup" subtitle="Required fields become the parent context for candidate discovery, replay validation, and promotion gates." />
              <form className="form-grid top-gap-small" onSubmit={(event) => void createExperiment(event)}>
                <label className="form-field"><span>Name</span><input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} required placeholder="July US plan tuning" /></label>
                <label className="form-field"><span>Hypothesis</span><input value={form.hypothesis} onChange={(event) => setForm({ ...form, hypothesis: event.target.value })} placeholder="Improve Tier A win rate via stricter geometry" /></label>
                <label className="form-field"><span>Universe source</span><select value={form.universe_mode} onChange={(event) => setForm({ ...form, universe_mode: event.target.value })}><option value="watchlist">Existing watchlist</option><option value="tickers">Explicit tickers</option></select></label>
                {form.universe_mode === "watchlist" ? <label className="form-field"><span>Watchlist</span><select value={form.watchlist_id} onChange={(event) => setForm({ ...form, watchlist_id: event.target.value })} required><option value="">Select watchlist…</option>{watchlists.map((watchlist) => <option key={watchlist.id ?? watchlist.name} value={String(watchlist.id)}>{watchlist.name} · {watchlist.tickers.length} tickers</option>)}</select></label> : null}
                {form.universe_mode === "tickers" ? <label className="form-field"><span>Universe tickers</span><input value={form.tickers} onChange={(event) => setForm({ ...form, tickers: event.target.value })} /></label> : null}
                <label className="form-field"><span>Objective</span><select value={form.objective} onChange={(event) => setForm({ ...form, objective: event.target.value })}><option value="balanced_score">Balanced score</option><option value="tier_a_win_rate">Tier A win rate</option><option value="expected_value">Expected value</option><option value="average_5d_return">Average 5d return</option><option value="loss_severity">Minimize loss severity</option></select></label>
                <label className="form-field"><span>Discovery candidates searched</span><input type="number" min="1" max="1000000" value={form.discovery_candidate_count} onChange={(event) => setForm({ ...form, discovery_candidate_count: event.target.value })} /><small>Cheap discovery/search budget. Large values queue a worker discovery job and are not promotion evidence.</small></label>
                <label className="form-field"><span>Candidates retained</span><input type="number" min="1" max="500" value={form.retained_candidate_count} onChange={(event) => setForm({ ...form, retained_candidate_count: event.target.value })} /><small>Top candidates imported into this workflow after discovery.</small></label>
                <label className="form-field"><span>Replay candidates</span><input type="number" min="1" max="10" value={form.replay_candidate_count} onChange={(event) => setForm({ ...form, replay_candidate_count: event.target.value })} /><small>Shortlisted candidates queued for expensive replay; capped at 10.</small></label>
                {["discovery_start", "discovery_end", "replay_start", "replay_end", "holdout_start", "holdout_end"].map((key) => <label className="form-field" key={key}><span>{key.replace(/_/g, " ")}</span><input type="date" value={form[key as keyof typeof form]} onChange={(event) => setForm({ ...form, [key]: event.target.value })} /></label>)}
                <label className="form-field"><span>Baseline</span><select value={form.baseline_source} onChange={(event) => setForm({ ...form, baseline_source: event.target.value })}><option value="current_active_config">Current active config</option><option value="selected_config_version">Selected config version</option><option value="existing_replay_batch">Existing replay batch</option><option value="rerun_baseline_replay">Rerun baseline replay</option></select></label>
                <label className="form-field"><span>Promotion target</span><select value={form.promotion_target} onChange={(event) => setForm({ ...form, promotion_target: event.target.value })}><option value="research_only">Research only</option><option value="paper_config">Paper config</option><option value="live_guarded_config">Live guarded config</option><option value="live_full_autonomy" disabled>Live full autonomy disabled</option></select></label>
                <div className="cluster"><button className="button" disabled={saving}>{saving ? "… Saving" : "Create experiment"}</button></div>
              </form>
            </Card>

            <Card>
              <SectionTitle kicker="Experiments" title="Active workflow list" subtitle="Select an experiment to review lifecycle state and next action." />
              {experiments?.experiments.length ? <div className="stack top-gap-small">{experiments.experiments.map((experiment) => <button type="button" className="button-subtle" key={experiment.id} onClick={() => void load(experiment.id, false)}><span>{experiment.name}</span> <Badge tone={stageTone(experiment.current_stage)}>{experiment.current_stage}</Badge></button>)}</div> : <EmptyState message="No active tuning experiments yet." />}
            </Card>
          </section>
        ) : null}

        {selected ? (
          <>
            <Card>
              <SectionTitle kicker="Lifecycle banner" title={selected.name} subtitle={selected.next_action} actions={<><Badge tone={stageTone(selected.current_stage)}>{selected.current_stage}</Badge><button className="button-secondary" onClick={() => void updateSelectedFromForm()} disabled={saving}>Update from setup form</button><button className="button-subtle" onClick={() => void archiveSelected()} disabled={saving}>Archive</button><button className="button-subtle" onClick={() => void deleteSelected()} disabled={saving}>Delete</button></>} />
              <section className="metrics-grid top-gap-small">
                <StatCard label="Candidate pool" value={funnel.pool} helper="Discovery-only until replay validated" />
                <StatCard label="Shortlist" value={funnel.shortlist} helper="Replay pass capped at 5 by default" />
                <StatCard label="Replay validation" value={funnel.replay} helper="Cache-only and sequential" />
                <StatCard label="Promotion proposal" value={funnel.proposal} helper="Blocked until replay and holdout pass" />
              </section>
              {selected.blockers.length ? <div className="alert alert-warning top-gap-small">Blockers: {selected.blockers.join(", ")}</div> : null}
            </Card>

            <Card>
              <SectionTitle kicker="Recommended next action" title={selected.next_action} subtitle="Use the guided control below only when it matches the current stage. Full controls are collapsed to keep the workflow readable." />
              <div className="cluster top-gap-small">
                <button className="button" disabled={saving} onClick={() => void workflowAction(`/api/tuning-workflow/experiments/${selected.id}/autonomous-run`)}>Run autonomously until wait/manual gate</button>
                {selected.current_stage === "readiness_needed" ? <button className="button-secondary" disabled={saving} onClick={() => void workflowAction(`/api/tuning-workflow/experiments/${selected.id}/readiness-audit`)}>Run readiness audit</button> : null}
                {selected.current_stage === "candidate_discovery_needed" ? <button className="button" disabled={saving} onClick={() => void workflowAction(Number(selected.discovery_settings.candidate_count ?? 0) > 10 ? `/api/tuning-workflow/experiments/${selected.id}/discovery/queue-large` : `/api/tuning-workflow/experiments/${selected.id}/candidate-pool/generate`)}>{Number(selected.discovery_settings.candidate_count ?? 0) > 10 ? "Queue large discovery" : "Generate candidate pool"}</button> : null}
                {selected.current_stage === "discovery_running" ? <button className="button-secondary" disabled={saving} onClick={() => void workflowAction(`/api/tuning-workflow/experiments/${selected.id}/discovery/import`)}>Import completed discovery</button> : null}
                {selected.current_stage === "shortlist_needed" ? <button className="button" disabled={saving || !candidates.length} onClick={() => void workflowAction(`/api/tuning-workflow/experiments/${selected.id}/shortlist`, { candidate_ids: candidates.slice(0, Number(selected.sections.shortlist?.max_candidates ?? 5)).map((candidate) => String(candidate.id)) })}>Shortlist top candidates</button> : null}
                {selected.current_stage === "baseline_needed" ? <button className="button" disabled={saving} onClick={() => void workflowAction(`/api/tuning-workflow/experiments/${selected.id}/baseline-replay/create?enqueue=true`)}>Create baseline replay</button> : null}
                {selected.current_stage === "candidate_replay_needed" ? <button className="button" disabled={saving || !shortlistedIds.length} onClick={() => void workflowAction(`/api/tuning-workflow/experiments/${selected.id}/candidate-replay/create?enqueue=true`)}>Create candidate replays</button> : null}
                {selected.current_stage === "stability_validation_needed" ? <button className="button" disabled={saving || !firstShortlistedId} onClick={() => void workflowAction(`/api/tuning-workflow/experiments/${selected.id}/holdout-replay/create?candidate_id=${encodeURIComponent(firstShortlistedId)}&enqueue=true`)}>Create holdout replays</button> : null}
                {selected.current_stage === "promotion_proposal_needed" ? <button className="button" disabled={saving || !firstShortlistedId} onClick={() => void workflowAction(`/api/tuning-workflow/experiments/${selected.id}/promotion-proposal`, { candidate_id: firstShortlistedId })}>Create promotion proposal</button> : null}
              </div>
            </Card>

            <DisclosureCard kicker="Advanced controls" title="All workflow actions" subtitle="Use these only when binding existing batches or correcting workflow state manually.">
              <div className="cluster top-gap-small">
                <button className="button-secondary" disabled={saving} onClick={() => void workflowAction(`/api/tuning-workflow/experiments/${selected.id}/readiness-audit`)}>Run readiness audit</button>
                <button className="button-secondary" disabled={saving} onClick={() => void workflowAction(`/api/tuning-workflow/experiments/${selected.id}/candidate-pool/generate`)}>Generate seeded pool</button>
                <button className="button-secondary" disabled={saving} onClick={() => void workflowAction(`/api/tuning-workflow/experiments/${selected.id}/discovery/queue-large`)}>Queue large discovery</button>
                <button className="button-secondary" disabled={saving} onClick={() => void workflowAction(`/api/tuning-workflow/experiments/${selected.id}/discovery/import`)}>Import discovery candidates</button>
                <button className="button-secondary" disabled={saving || !candidates.length} onClick={() => void workflowAction(`/api/tuning-workflow/experiments/${selected.id}/shortlist`, { candidate_ids: candidates.slice(0, Number(selected.sections.shortlist?.max_candidates ?? 5)).map((candidate) => String(candidate.id)) })}>Shortlist top candidates</button>
              </div>
              <div className="cluster top-gap-small">
                <label className="form-field compact-field"><span>Baseline batch id</span><input value={baselineBatchId} onChange={(event) => setBaselineBatchId(event.target.value)} placeholder="22" /></label>
                <button className="button-subtle" disabled={saving || !baselineBatchId} onClick={() => void workflowAction(`/api/tuning-workflow/experiments/${selected.id}/baseline-replay/bind`, { replay_batch_id: Number(baselineBatchId) })}>Bind baseline replay</button>
                <button className="button-subtle" disabled={saving} onClick={() => void workflowAction(`/api/tuning-workflow/experiments/${selected.id}/baseline-replay/create?enqueue=true`)}>Create baseline replay</button>
                <label className="form-field compact-field"><span>Candidate batch id</span><input value={candidateBatchId} onChange={(event) => setCandidateBatchId(event.target.value)} placeholder="23" /></label>
                <button className="button-subtle" disabled={saving || !candidateBatchId || !firstShortlistedId} onClick={() => void workflowAction(`/api/tuning-workflow/experiments/${selected.id}/candidate-replay/record`, { batch_ids_by_candidate: { [firstShortlistedId]: Number(candidateBatchId) } })}>Record candidate replay</button>
                <button className="button-subtle" disabled={saving || !shortlistedIds.length} onClick={() => void workflowAction(`/api/tuning-workflow/experiments/${selected.id}/candidate-replay/create?enqueue=true`)}>Create candidate replays</button>
                <button className="button-subtle" disabled={saving} onClick={() => void workflowAction(`/api/tuning-workflow/experiments/${selected.id}/replay-summaries/refresh`)}>Refresh replay summaries</button>
                <button className="button-subtle" disabled={saving} onClick={() => void workflowAction(`/api/tuning-workflow/experiments/${selected.id}/candidate-replay/stop-after-current-slice`)}>Stop after current slice</button>
              </div>
              <div className="cluster top-gap-small">
                <label className="form-field compact-field"><span>Stability status</span><select value={stabilityStatus} onChange={(event) => setStabilityStatus(event.target.value)}><option value="warning">Warning / needs more holdout</option><option value="pass">Pass</option><option value="fail">Fail</option></select></label>
                <button className="button-subtle" disabled={saving || !firstShortlistedId} onClick={() => void workflowAction(`/api/tuning-workflow/experiments/${selected.id}/stability-validation/record`, { candidate_id: firstShortlistedId, status: stabilityStatus, notes: "operator-recorded workflow validation" })}>Record stability</button>
                <button className="button-subtle" disabled={saving || !firstShortlistedId} onClick={() => void workflowAction(`/api/tuning-workflow/experiments/${selected.id}/holdout-replay/create?candidate_id=${encodeURIComponent(firstShortlistedId)}&enqueue=true`)}>Create holdout replays</button>
                <button className="button" disabled={saving || !firstShortlistedId} onClick={() => void workflowAction(`/api/tuning-workflow/experiments/${selected.id}/promotion-proposal`, { candidate_id: firstShortlistedId })}>Create promotion proposal</button>
                <button className="button-secondary" disabled={saving} onClick={() => void workflowAction(`/api/tuning-workflow/experiments/${selected.id}/promotion-execution/paper`, { reason: "operator-approved paper promotion from workflow" })}>Create paper config</button>
                <button className="button-subtle" disabled={saving} onClick={() => void workflowAction(`/api/tuning-workflow/experiments/${selected.id}/paper-trial/extend`, { days: 30, reason: "operator extended paper trial" })}>Extend paper trial</button>
                <button className="button-subtle" disabled={saving} onClick={() => void workflowAction(`/api/tuning-workflow/experiments/${selected.id}/rollback`, { reason: "operator rollback from workflow" })}>Rollback paper config</button>
              </div>
            </DisclosureCard>

            <section className="card-grid">
              <SectionStatusCard title="Experiment setup" subtitle="Name, universe, windows, objective, baseline, and promotion target." section={selected.sections.setup} />
              <SectionStatusCard title="Evidence readiness" subtitle="Cache-only coverage audit and repeated bar-gap warnings." section={selected.sections.evidence_readiness} />
              <SectionStatusCard title="Candidate discovery" subtitle={selected.computation_labels.discovery} section={selected.sections.candidate_pool} />
              <SectionStatusCard title="Candidate shortlist" subtitle="Small shortlist for expensive validation, normally 5–10 candidates." section={selected.sections.shortlist} />
              <SectionStatusCard title="Baseline replay" subtitle="Required before candidate comparison is valid." section={selected.sections.baseline_replay} />
              <SectionStatusCard title="Candidate replay validation" subtitle={selected.computation_labels.replay} section={selected.sections.candidate_replay_validation} />
              <SectionStatusCard title="Walk-forward / holdout" subtitle={selected.computation_labels.holdout} section={selected.sections.stability_validation} />
              <SectionStatusCard title="Promotion proposal" subtitle="Paper-only by default; live full autonomy fails closed." section={selected.sections.promotion_proposal} />
              <SectionStatusCard title="Promotion execution" subtitle="Creates a paper config and records rollback evidence; live execution is disabled." section={selected.sections.promotion_execution} />
              <SectionStatusCard title="Post-promotion monitoring" subtitle="Shown after paper promotion exists." section={selected.sections.post_promotion_monitoring} />
              <SectionStatusCard title="Rollback" subtitle="Records rollback reason and source/target evidence for paper configs." section={selected.sections.rollback} />
            </section>
          </>
        ) : null}
      </div>
    </>
  );
}
