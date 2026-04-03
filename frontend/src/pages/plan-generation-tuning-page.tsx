import { useEffect, useMemo, useState } from "react";

import { getJson, postForm } from "../api";
import { Badge, Card, EmptyState, ErrorState, HelpHint, LoadingState, PageHeader, SectionTitle, StatCard } from "../components/ui";
import type {
  PlanGenerationTuningConfigVersion,
  PlanGenerationTuningConfigsResponse,
  PlanGenerationTuningResponse,
  PlanGenerationTuningRun,
  PlanGenerationTuningRunsResponse,
} from "../types";

function tone(status: string): "ok" | "warning" | "danger" | "neutral" | "info" {
  if (status === "completed" || status === "active") return "ok";
  if (status === "failed") return "danger";
  if (status === "running") return "info";
  return "neutral";
}

export function PlanGenerationTuningPage() {
  const [state, setState] = useState<PlanGenerationTuningResponse | null>(null);
  const [runs, setRuns] = useState<PlanGenerationTuningRun[] | null>(null);
  const [configs, setConfigs] = useState<PlanGenerationTuningConfigVersion[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null);

  async function loadData() {
    try {
      setError(null);
      const [loadedState, loadedRuns, loadedConfigs] = await Promise.all([
        getJson<PlanGenerationTuningResponse>("/api/plan-generation-tuning"),
        getJson<PlanGenerationTuningRunsResponse>("/api/plan-generation-tuning/runs?limit=20"),
        getJson<PlanGenerationTuningConfigsResponse>("/api/plan-generation-tuning/configs?limit=20"),
      ]);
      setState(loadedState);
      setRuns(loadedRuns.items);
      setConfigs(loadedConfigs.items);
      setSelectedRunId((current) => current ?? loadedRuns.items[0]?.id ?? null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to load plan generation tuning state");
    }
  }

  useEffect(() => {
    void loadData();
  }, []);

  const selectedRun = useMemo(() => {
    if (!runs || runs.length === 0) return null;
    return runs.find((run) => run.id === selectedRunId) ?? runs[0];
  }, [runs, selectedRunId]);

  async function runTuning(apply: boolean) {
    try {
      setSaving(apply ? "apply" : "run");
      setError(null);
      await postForm<PlanGenerationTuningRun>(`/api/plan-generation-tuning/run?apply=${apply ? "true" : "false"}`, {});
      await loadData();
    } catch (runError) {
      setError(runError instanceof Error ? runError.message : "Failed to run plan generation tuning");
    } finally {
      setSaving(null);
    }
  }

  async function promote(configVersionId: number | null) {
    if (!configVersionId) return;
    try {
      setSaving(`promote-${configVersionId}`);
      setError(null);
      await postForm(`/api/plan-generation-tuning/configs/${configVersionId}/promote`, {});
      await loadData();
    } catch (promoteError) {
      setError(promoteError instanceof Error ? promoteError.message : "Failed to promote config");
    } finally {
      setSaving(null);
    }
  }

  return (
    <>
      <PageHeader
        kicker="Research"
        title="Plan generation tuning"
        subtitle="Run candidate-based precision tuning for live plan construction, inspect ranked backtests, and promote guarded config versions."
        actions={<HelpHint tooltip="This page shows the dedicated plan-generation tuning workflow: live config, ranked candidates, and guarded promotions." to="/docs?doc=plan-generation-tuning-spec" />}
      />
      {error ? <ErrorState message={error} /> : null}
      {!state || !runs || !configs ? <LoadingState message="Loading plan generation tuning…" /> : null}
      {state && runs && configs ? (
        <div className="stack-page">
          <section className="metrics-grid">
            <StatCard label="Active config" value={String(state.state.active_config_version_id ?? "baseline")} helper="Current live config version" />
            <StatCard label="Auto mode" value={state.state.auto_enabled ? "on" : "off"} helper="Scheduled autonomous tuning" />
            <StatCard label="Auto promote" value={state.state.auto_promote_enabled ? "on" : "off"} helper="Whether winners can be promoted automatically" />
            <StatCard label="Latest run" value={String(state.state.latest_run?.id ?? "—")} helper="Most recent tuning execution" />
          </section>

          <Card>
            <SectionTitle kicker="Controls" title="Run plan generation tuning" subtitle="Launch a dry run or guarded promotion using the immutable backend rules and historical replay." actions={<HelpHint tooltip="Dry runs rank candidates without changing the live config. Apply mode promotes only if the winner passes backend guardrails." to="/docs?doc=plan-generation-tuning-spec" />} />
            <div className="cluster top-gap-small">
              <button className="button" type="button" disabled={saving !== null} onClick={() => void runTuning(false)}>{saving === "run" ? "Running…" : "Run dry"}</button>
              <button className="button-secondary" type="button" disabled={saving !== null} onClick={() => void runTuning(true)}>{saving === "apply" ? "Running & applying…" : "Run and promote if eligible"}</button>
            </div>
            <pre className="code-block top-gap-small">{JSON.stringify(state.state.active_config, null, 2)}</pre>
          </Card>

          <Card>
            <SectionTitle kicker="Runs" title="Recent tuning runs" subtitle="Select a run to inspect ranked candidates and promotion outcomes." actions={<HelpHint tooltip="Each run stores the candidate ranking, winner, validation counts, and whether promotion happened or was blocked." to="/docs?doc=plan-generation-tuning-spec" />} />
            {runs.length === 0 ? (
              <EmptyState message="No plan generation tuning runs recorded yet." />
            ) : (
              <div className="data-stack top-gap-small">
                {runs.map((run) => (
                  <button key={run.id ?? run.created_at} type="button" className={`data-card data-card-button ${selectedRunId === run.id ? "data-card-selected" : ""}`} onClick={() => setSelectedRunId(run.id ?? null)}>
                    <div className="data-card-header">
                      <div className="cluster">
                        <Badge tone={tone(run.status)}>{run.status}</Badge>
                        <Badge>{run.mode}</Badge>
                        <Badge>#{run.id ?? "?"}</Badge>
                      </div>
                      <div className="helper-text">eligible {run.eligible_record_count} · validation {run.validation_record_count}</div>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </Card>

          <Card>
            <SectionTitle kicker="Selected run" title="Candidate ranking" subtitle="The backend ranks candidates lexicographically by win rate, then win count, then expected value." actions={<HelpHint tooltip="Candidate ordering is deterministic: validity first, then actionable win rate, then win count, then expected value." to="/docs?doc=plan-generation-tuning-spec" />} />
            {selectedRun ? (
              <div className="stack-page">
                <div className="helper-text">Promotion mode: {selectedRun.promotion_mode} · Winner candidate: {selectedRun.winning_candidate_id ?? "—"} · Promoted config: {selectedRun.promoted_config_version_id ?? "—"}</div>
                <div className="data-stack top-gap-small">
                  {selectedRun.candidates.map((candidate) => (
                    <article key={candidate.id ?? `${selectedRun.id}-${candidate.rank}`} className="data-card">
                      <div className="data-card-header">
                        <div className="cluster">
                          <Badge tone={candidate.rank === 1 ? "ok" : "neutral"}>#{candidate.rank ?? "?"}</Badge>
                          <Badge>{candidate.is_baseline ? "baseline" : "candidate"}</Badge>
                          <Badge tone={candidate.promotion_eligible ? "ok" : "warning"}>{candidate.promotion_eligible ? "eligible" : "blocked"}</Badge>
                        </div>
                        <div className="helper-text">{candidate.changed_keys.join(", ") || "no changes"}</div>
                      </div>
                      <pre className="code-block top-gap-small">{JSON.stringify(candidate.metric_breakdown, null, 2)}</pre>
                    </article>
                  ))}
                </div>
              </div>
            ) : (
              <EmptyState message="No run selected." />
            )}
          </Card>

          <Card>
            <SectionTitle kicker="Configs" title="Config versions" subtitle="Promote a stored version to become the live plan-generation configuration." actions={<HelpHint tooltip="Config versions capture baseline and promoted parameter sets so live plan construction stays auditable." to="/docs?doc=plan-generation-tuning-spec" />} />
            {configs.length === 0 ? (
              <EmptyState message="No config versions available yet." />
            ) : (
              <div className="data-stack top-gap-small">
                {configs.map((config) => (
                  <article key={config.id ?? config.version_label} className="data-card">
                    <div className="data-card-header">
                      <div className="cluster">
                        <Badge tone={tone(config.status)}>{config.status}</Badge>
                        <Badge>{config.version_label}</Badge>
                        <Badge>{config.source}</Badge>
                      </div>
                      <div className="helper-text">#{config.id ?? "?"}</div>
                    </div>
                    <div className="cluster top-gap-small">
                      <button className="button-secondary" type="button" disabled={saving === `promote-${config.id ?? 0}` || config.id === state.state.active_config_version_id} onClick={() => void promote(config.id)}>
                        {saving === `promote-${config.id ?? 0}` ? "Promoting…" : config.id === state.state.active_config_version_id ? "Active" : "Promote"}
                      </button>
                    </div>
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
