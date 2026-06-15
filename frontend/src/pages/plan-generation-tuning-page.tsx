import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { getJson, postForm } from "../api";
import { Badge, Card, DisclosureCard, EmptyState, ErrorState, HelpHint, LoadingState, PageHeader, SectionTitle, StatCard } from "../components/ui";
import { planGenerationTuningConfigTone, runTone } from "../utils";
import type {
  PlanGenerationTuningConfigVersion,
  PlanGenerationTuningConfigsResponse,
  PlanGenerationTuningExplorationCampaign,
  PlanGenerationTuningResponse,
  PlanGenerationTuningRun,
  PlanGenerationTuningRunsResponse,
  PlanGenerationTuningValidationResponse,
} from "../types";

const glossaryDoc = (section: string) => `/docs?doc=glossary&section=${section}`;
const tuningSpecDoc = "/docs?doc=plan-generation-tuning-spec";

function numberOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function formatPercent(value: number | null, digits = 2): string {
  return value === null ? "—" : `${value.toFixed(digits)}%`;
}

function formatNumber(value: number | null, digits = 4): string {
  return value === null ? "—" : value.toFixed(digits);
}

function humanizeCampaignName(name: string): string {
  return name.split("_").join(" ");
}

function candidateCampaign(candidate: PlanGenerationTuningRun["candidates"][number]): string {
  const breakdown = candidate.metric_breakdown as Record<string, unknown>;
  const campaign = breakdown.campaign;
  if (typeof campaign === "string" && campaign.trim()) {
    return campaign;
  }
  if (candidate.is_baseline) {
    return "baseline";
  }
  return "unknown";
}

function candidateMetric(candidate: PlanGenerationTuningRun["candidates"][number], key: string): number | null {
  return numberOrNull((candidate.metric_breakdown as Record<string, unknown>)[key]);
}

function candidateConfigValue(candidate: PlanGenerationTuningRun["candidates"][number], key: string): string {
  const value = candidate.config[key];
  if (typeof value === "number" && Number.isFinite(value)) {
    return value.toFixed(4);
  }
  return value === null || value === undefined ? "—" : String(value);
}

export function PlanGenerationTuningPage() {
  const [state, setState] = useState<PlanGenerationTuningResponse | null>(null);
  const [runs, setRuns] = useState<PlanGenerationTuningRun[] | null>(null);
  const [configs, setConfigs] = useState<PlanGenerationTuningConfigVersion[] | null>(null);
  const [validation, setValidation] = useState<PlanGenerationTuningValidationResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null);
  const [runMode, setRunMode] = useState<"manual" | "explore" | "wide">("manual");
  const [largeCoarseCandidates, setLargeCoarseCandidates] = useState(20000);
  const [largeFineCandidates, setLargeFineCandidates] = useState(5000);
  const [showAllCandidates, setShowAllCandidates] = useState(false);

  async function loadData() {
    try {
      setError(null);
      const [loadedState, loadedRuns, loadedConfigs, loadedValidation] = await Promise.all([
        getJson<PlanGenerationTuningResponse>("/api/plan-generation-tuning"),
        getJson<PlanGenerationTuningRunsResponse>("/api/plan-generation-tuning/runs?limit=20"),
        getJson<PlanGenerationTuningConfigsResponse>("/api/plan-generation-tuning/configs?limit=20"),
        getJson<PlanGenerationTuningValidationResponse>("/api/plan-generation-tuning/validation"),
      ]);
      setState(loadedState);
      setRuns(loadedRuns.items);
      setConfigs(loadedConfigs.items);
      setValidation(loadedValidation);
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

  const selectedRunCandidates = useMemo(() => {
    if (!selectedRun) return [];
    return [...selectedRun.candidates].sort((left, right) => (left.rank ?? Number.POSITIVE_INFINITY) - (right.rank ?? Number.POSITIVE_INFINITY));
  }, [selectedRun]);
  const selectedRunVisibleCandidates = useMemo(() => {
    if (showAllCandidates) return selectedRunCandidates;
    return selectedRunCandidates.filter((candidate) => candidate.promotion_eligible || candidate.is_baseline);
  }, [selectedRunCandidates, showAllCandidates]);
  const selectedRunMetricSpread = useMemo(() => {
    if (!selectedRun) return null;
    const searchRates = new Set<string>();
    const validationRates = new Set<string>();
    const validationExpectedValues = new Set<string>();
    for (const candidate of selectedRunCandidates) {
      const searchRate = candidateMetric(candidate, "search_win_rate_percent");
      const validationRate = candidateMetric(candidate, "validation_win_rate_percent");
      const validationExpectedValue = candidateMetric(candidate, "validation_expected_value");
      if (searchRate !== null) searchRates.add(searchRate.toFixed(2));
      if (validationRate !== null) validationRates.add(validationRate.toFixed(2));
      if (validationExpectedValue !== null) validationExpectedValues.add(validationExpectedValue.toFixed(4));
    }
    return {
      searchWinRateCount: searchRates.size,
      validationWinRateCount: validationRates.size,
      validationExpectedValueCount: validationExpectedValues.size,
    };
  }, [selectedRun, selectedRunCandidates]);


  const selectedRunWinner = selectedRunCandidates[0] ?? null;
  const selectedRunBaseline = useMemo(() => selectedRunCandidates.find((candidate) => candidate.is_baseline) ?? null, [selectedRunCandidates]);

  async function runTuning(mode: string, apply: boolean) {
    try {
      setSaving(apply ? `apply-${mode}` : `run-${mode}`);
      setError(null);
      await postForm<unknown>(`/api/plan-generation-tuning/run?mode=${encodeURIComponent(mode)}&apply=${apply ? "true" : "false"}`, {});
      await loadData();
    } catch (runError) {
      setError(runError instanceof Error ? runError.message : "Failed to run plan generation tuning");
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
      await loadData();
    } catch (runError) {
      setError(runError instanceof Error ? runError.message : "Failed to queue large tuning search");
    } finally {
      setSaving(null);
    }
  }

  async function promote(configVersionId: number | null) {
    if (!configVersionId) return;
    try {
      setSaving(`promote-config-${configVersionId}`);
      setError(null);
      await postForm(`/api/plan-generation-tuning/configs/${configVersionId}/promote`, {});
      await loadData();
    } catch (promoteError) {
      setError(promoteError instanceof Error ? promoteError.message : "Failed to promote config");
    } finally {
      setSaving(null);
    }
  }

  async function promoteCandidate(runId: number | null, candidateId: number | null) {
    if (!runId || !candidateId) return;
    try {
      setSaving(`promote-candidate-${candidateId}`);
      setError(null);
      await postForm(`/api/plan-generation-tuning/runs/${runId}/candidates/${candidateId}/promote`, {});
      await loadData();
    } catch (promoteError) {
      setError(promoteError instanceof Error ? promoteError.message : "Failed to promote candidate");
    } finally {
      setSaving(null);
    }
  }

  return (
    <>
      <PageHeader
        kicker="Research Lab"
        title="Plan generation tuning"
        subtitle="Change downstream plan construction only when Quality & Edge points to entry, risk, reward, or precision problems."
        actions={<HelpHint tooltip="This page shows the dedicated plan-generation tuning workflow: live config, ranked candidates, and guarded promotions." to={tuningSpecDoc} />}
      />
      {error ? <ErrorState message={error} /> : null}
      {!state || !runs || !configs ? <LoadingState message="Loading plan generation tuning…" /> : null}
      {state && runs && configs ? (
        <div className="stack-page">
          <Card>
            <SectionTitle
              kicker="Downstream construction"
              title="Should plan framing parameters change?"
              subtitle="Start with validation and promotion safety. Process details and raw configs stay below as supporting evidence."
              actions={<Link to="/recommendation-quality" className="button-subtle">◈ Quality & Edge</Link>}
            />
            <section className="metrics-grid top-gap-small">
              <StatCard label="Active config" value={String(state.state.active_config_version_id ?? "baseline")} helper="Current live config version" tooltip="The parameter set that is currently live for plan generation. New tuning runs compare candidates against this active baseline." tooltipTo={tuningSpecDoc} />
              <StatCard label="Auto promote" value={state.state.auto_promote_enabled ? "on" : "off"} helper="Whether winners can be promoted automatically" tooltip="Whether a winning candidate can become the live configuration automatically after it passes the promotion gate." tooltipTo={glossaryDoc("promotion-gate")} />
              <StatCard label="Latest run" value={String(state.state.latest_run?.id ?? "—")} helper="Most recent tuning execution" tooltip="The most recent stored tuning run, including its ranked candidates and any promotion outcome." tooltipTo={tuningSpecDoc} />
              <StatCard label="Auto mode" value={state.state.auto_enabled ? "on" : "off"} helper="Scheduled autonomous tuning" tooltip="Whether this tuning workflow can run on its own schedule instead of only when an operator starts it manually." tooltipTo={tuningSpecDoc} />
            </section>
          </Card>

          <section className="card-grid">
            <DisclosureCard kicker="Process" title="How it works" subtitle="Reference explanation of the tuning flow; collapse it once the workflow is familiar." actions={<HelpHint tooltip="This explains the order of operations so the results below are easier to interpret." to={tuningSpecDoc} />}>
              <div className="data-stack top-gap-small">
                <article className="data-card">
                  <div className="data-card-header">
                    <div className="cluster"><Badge tone="info">1</Badge><Badge>Split the data</Badge></div>
                  </div>
                  <div className="helper-text top-gap-small">Eligible historical records are split into a search slice and a holdout validation slice. Search helps discover candidates; validation checks whether they still hold up.</div>
                </article>
                <article className="data-card">
                  <div className="data-card-header">
                    <div className="cluster"><Badge tone="info">2</Badge><Badge>Try four phases</Badge></div>
                  </div>
                  <div className="helper-text top-gap-small">The tuner spends candidate budget on four bounded phases: entry calibration, selectivity, risk protection, and reward expansion.</div>
                </article>
                <article className="data-card">
                  <div className="data-card-header">
                    <div className="cluster"><Badge tone="info">3</Badge><Badge>Rank by validation</Badge></div>
                  </div>
                  <div className="helper-text top-gap-small">Candidates are ranked lexicographically by validation win rate, then validation win count, then validation expected value. Search metrics are shown to help explain why a candidate looked promising.</div>
                </article>
              </div>
            </DisclosureCard>

            <Card>
              <SectionTitle kicker="Controls" title="Queue plan generation tuning" subtitle="Queue a worker-backed dry run, guarded promotion, or research-only large search so the run appears in the debugger and worker logs." actions={<HelpHint tooltip="The run is queued to a worker. Dry runs rank candidates without changing the live config. Apply mode promotes only if the winner passes backend guardrails. Large tuning search is research-only and cannot promote." to={tuningSpecDoc} />} />
              <div className="data-stack top-gap-small">
                <label className="form-field">
                  <span>Run mode</span>
                  <select value={runMode} onChange={(event) => setRunMode(event.target.value as "manual" | "explore" | "wide") }>
                    <option value="manual">Standard tuning search</option>
                    <option value="explore">Exploratory tuning search</option>
                    <option value="wide">Wide tuning search</option>
                  </select>
                </label>
                <div className="helper-text">
                  {runMode === "manual"
                    ? "Standard tuning search uses the narrower default candidate pool."
                    : runMode === "explore"
                      ? "Exploratory tuning search widens the step size and validation view a bit."
                      : "Wide tuning search uses the broadest built-in deterministic sweep and rolling walk-forward validation. The large parameter search is a separate non-schedulable research tuning search."}
                </div>
                <div className="cluster">
                  <button className="button" type="button" disabled={saving !== null} onClick={() => void runTuning(runMode, false)}>{saving === `run-${runMode}` ? "… Queueing" : `▶ ${runMode === "manual" ? "Standard dry run" : `${runMode} dry run`}`}</button>
                  <button className="button-secondary" type="button" disabled={saving !== null} onClick={() => void runTuning(runMode, true)}>{saving === `apply-${runMode}` ? "… Applying" : `↑ ${runMode === "manual" ? "Promote standard winner if eligible" : `${runMode} promote if eligible`}`}</button>
                </div>
              </div>
              <div className="data-card top-gap-medium">
                <div className="data-card-header">
                  <div>
                    <div className="data-card-title">Plan Generation Large Tuning Search</div>
                    <div className="helper-text">Research-only, non-schedulable coarse/fine search. It writes a resumable cache and never promotes config. Increase counts manually for multi-hour searches.</div>
                  </div>
                  <Badge tone="warning">large</Badge>
                </div>
                <div className="cluster top-gap-small">
                  <label className="form-field compact-field">
                    <span>Coarse candidates</span>
                    <input type="number" min="1" max="1000000" value={largeCoarseCandidates} onChange={(event) => setLargeCoarseCandidates(Number(event.target.value || 1))} />
                  </label>
                  <label className="form-field compact-field">
                    <span>Fine candidates</span>
                    <input type="number" min="0" max="500000" value={largeFineCandidates} onChange={(event) => setLargeFineCandidates(Number(event.target.value || 0))} />
                  </label>
                </div>
                <div className="cluster top-gap-small">
                  <button className="button-secondary" type="button" disabled={saving !== null} onClick={() => void runLargeSearch()}>{saving === "run-large" ? "… Queueing" : "▶ Queue large tuning search"}</button>
                  <span className="helper-text">Use the run/debugger page for progress. This can take hours.</span>
                </div>
              </div>
              <details className="top-gap-small">
                <summary className="helper-text">Show active config JSON</summary>
                <pre className="code-block top-gap-small">{JSON.stringify(state.state.active_config, null, 2)}</pre>
              </details>
            </Card>
          </section>

          <DisclosureCard kicker="Exploration" title="Search shape" subtitle="Supporting detail: deterministic phases and budgets used by the backend." actions={<HelpHint tooltip="This plan keeps exploration ordered: entry first, then risk, then reward." to={tuningSpecDoc} />}>
            <div className="table-wrapper top-gap-small">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>priority</th>
                    <th>campaign</th>
                    <th>budget</th>
                    <th>primary knobs</th>
                    <th>description</th>
                  </tr>
                </thead>
                <tbody>
                  {state.exploration_campaigns.map((campaign: PlanGenerationTuningExplorationCampaign) => (
                    <tr key={campaign.name}>
                      <td><Badge tone={campaign.priority <= 3 ? "ok" : "info"}>#{campaign.priority}</Badge></td>
                      <td>{humanizeCampaignName(campaign.name)}</td>
                      <td>{campaign.candidate_budget}</td>
                      <td>{campaign.parameter_keys.join(", ")}</td>
                      <td className="helper-text">{campaign.description}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="helper-text top-gap-small">Base sweep starts with the live baseline plus bounded local perturbations; a small refinement pass may add a few more around the top seeds.</div>
          </DisclosureCard>

          {validation ? (
            <Card>
              <SectionTitle kicker="Validation" title="Walk-forward promotion gate" subtitle={validation.summary.promotion_rationale} actions={<HelpHint tooltip="This gate decides whether a candidate tuning change can become live. It relies on walk-forward validation so later slices, not just one pooled sample, influence the decision." to={glossaryDoc("walk-forward-validation")} />} />
              <section className="metrics-grid top-gap-small">
                <StatCard label="Promotion" value={validation.summary.promotion_recommended ? "recommended" : "not yet"} helper="Walk-forward gate outcome" tooltip="Whether the current candidate passed the backend promotion gate strongly enough to be recommended for promotion." tooltipTo={glossaryDoc("promotion-gate")} />
                <StatCard label="Qualified slices" value={validation.summary.qualified_slices} helper="Slices with enough resolved records" tooltip="How many walk-forward slices had enough resolved records to count as meaningful evidence. Thin slices are intentionally not treated as strong proof." tooltipTo={glossaryDoc("slice")} />
                <StatCard label="Avg win-rate delta" value={validation.summary.average_win_rate_delta !== null ? validation.summary.average_win_rate_delta.toFixed(2) : "—"} helper="Candidate minus baseline" tooltip="Average change in win rate for the candidate versus the current baseline across qualified validation slices." tooltipTo={tuningSpecDoc} />
                <StatCard label="Avg EV delta" value={validation.summary.average_expected_value_delta !== null ? validation.summary.average_expected_value_delta.toFixed(4) : "—"} helper="Candidate minus baseline" tooltip="Average change in expected-value-style return for the candidate versus the current baseline across qualified validation slices." tooltipTo={tuningSpecDoc} />
              </section>
              <div className="helper-text top-gap-small">Candidate: {validation.candidate_version.version_label} · Baseline: {validation.baseline_version.version_label}</div>
            </Card>
          ) : null}


          <Card>
            <SectionTitle kicker="Runs" title="Recent tuning runs" subtitle="Select a run to inspect ranked candidates and promotion outcomes." actions={<HelpHint tooltip="Each run stores the candidate ranking, winner, validation counts, and whether promotion happened or was blocked." to={tuningSpecDoc} />} />
            {runs.length === 0 ? (
              <EmptyState message="No plan generation tuning runs recorded yet." />
            ) : (
              <div className="data-stack top-gap-small">
                {runs.map((run) => (
                  <button key={run.id ?? run.created_at} type="button" className={`data-card data-card-button ${selectedRunId === run.id ? "data-card-selected" : ""}`} onClick={() => setSelectedRunId(run.id ?? null)}>
                    <div className="data-card-header">
                      <div className="cluster">
                        <Badge tone={runTone(run.status)}>{run.status}</Badge>
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
            <SectionTitle kicker="Selected run" title="Ranked comparison" subtitle="Start with the winner, baseline, and top few candidates. Expand to the full ranked table only when you need it." actions={<HelpHint tooltip="This view is designed to answer three questions quickly: what won, why it won, and whether promotion is safe." to={tuningSpecDoc} />} />
            {selectedRun ? (
              <div className="stack-page">
                <section className="card-grid top-gap-small">
                  <Card>
                    <SectionTitle kicker="Winner" title={`#${selectedRunWinner?.rank ?? "?"} ${selectedRunWinner ? humanizeCampaignName(candidateCampaign(selectedRunWinner)) : "candidate"}`} subtitle="Best candidate versus baseline." />
                    <div className="data-stack top-gap-small">
                      <div className="helper-text">Validation WR {formatPercent(candidateMetric(selectedRunWinner, "validation_win_rate_percent"))} · validation EV {formatNumber(candidateMetric(selectedRunWinner, "validation_expected_value"))} · promo {selectedRunWinner ? (selectedRunWinner.promotion_eligible ? "eligible" : "blocked") : "—"}</div>
                      <div className="helper-text">Changed keys: {selectedRunWinner?.changed_keys.join(", ") || "baseline"}</div>
                      <div className="helper-text">Baseline comparison: {selectedRunBaseline ? `${formatPercent(candidateMetric(selectedRunBaseline, "validation_win_rate_percent"))} WR / ${formatNumber(candidateMetric(selectedRunBaseline, "validation_expected_value"))} EV` : "—"}</div>
                    </div>
                  </Card>
                  <Card>
                    <SectionTitle kicker="Run" title={`#${selectedRun.id ?? "?"} · ${selectedRun.mode}`} subtitle={`Promotion mode: ${selectedRun.promotion_mode}`} />
                    <div className="metrics-grid top-gap-small">
                      <StatCard label="Candidates" value={selectedRun.candidate_count} helper="Stored ranked rows" />
                      <StatCard label="Eligible records" value={selectedRun.eligible_record_count} helper="Evidence pool" />
                      <StatCard label="Validation records" value={selectedRun.validation_record_count} helper="Holdout slice" />
                      <StatCard label="Promotion" value={selectedRun.promoted_config_version_id ? "applied" : selectedRun.winning_candidate_id ? "blocked" : "—"} helper="Backend guardrail outcome" />
                    </div>
                    <div className="helper-text top-gap-small">Winner candidate: {selectedRun.winning_candidate_id ?? "—"} · Promoted config: {selectedRun.promoted_config_version_id ?? "—"}</div>
                  </Card>
                </section>

                <DisclosureCard kicker="Candidates" title="Ranked table" subtitle="Read rows from top to bottom. Baseline stays pinned for comparison." actions={<button className="button-secondary" type="button" onClick={() => setShowAllCandidates((current) => !current)}>{showAllCandidates ? "Show eligible only" : "Show all candidates"}</button>}>
                  {selectedRunMetricSpread && selectedRunMetricSpread.searchWinRateCount === 1 && selectedRunMetricSpread.validationWinRateCount === 1 ? (
                    <div className="alert alert-warning top-gap-small">
                      This run is tie-heavy: most rows share the same search and validation win rates, so expected value and changed keys matter more here.
                    </div>
                  ) : null}
                  {!showAllCandidates && selectedRunCandidates.length !== selectedRunVisibleCandidates.length ? (
                    <div className="helper-text top-gap-small">Showing {selectedRunVisibleCandidates.length} eligible candidate{selectedRunVisibleCandidates.length === 1 ? "" : "s"} out of {selectedRunCandidates.length}. Blocked rows are hidden by default.</div>
                  ) : null}
                  {selectedRunVisibleCandidates.length > 0 ? (
                    <div className="table-wrapper top-gap-small">
                      <table className="data-table">
                        <thead>
                          <tr>
                            <th>rank</th>
                            <th>campaign</th>
                            <th>changes</th>
                            <th>search WR</th>
                            <th>validation WR</th>
                            <th>validation EV</th>
                            <th>promo</th>
                          </tr>
                        </thead>
                        <tbody>
                          {selectedRunVisibleCandidates.map((candidate) => (
                            <tr key={candidate.id ?? `${selectedRun.id}-${candidate.rank}`}>
                              <td><Badge tone={candidate.rank === 1 ? "ok" : candidate.is_baseline ? "info" : "neutral"}>#{candidate.rank ?? "?"}</Badge></td>
                              <td>{candidate.is_baseline ? "baseline" : humanizeCampaignName(candidateCampaign(candidate))}</td>
                              <td className="helper-text">{candidate.changed_keys.length > 0 ? candidate.changed_keys.join(", ") : "baseline"}</td>
                              <td>{formatPercent(candidateMetric(candidate, "search_win_rate_percent"))}</td>
                              <td>{formatPercent(candidateMetric(candidate, "validation_win_rate_percent"))}</td>
                              <td>{formatNumber(candidateMetric(candidate, "validation_expected_value"))}</td>
                              <td>
                                <div className="cluster">
                                  <Badge tone={candidate.promotion_eligible ? "ok" : "warning"}>{candidate.promotion_eligible ? "eligible" : "blocked"}</Badge>
                                  {candidate.promotion_eligible && candidate.id && selectedRun.id ? (
                                    <button className="button-secondary" type="button" disabled={saving === `promote-candidate-${candidate.id}`} onClick={() => void promoteCandidate(selectedRun.id, candidate.id)}>
                                      {saving === `promote-candidate-${candidate.id}` ? "… Promoting" : "Promote"}
                                    </button>
                                  ) : null}
                                </div>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <EmptyState message={showAllCandidates ? "No candidates available." : "No eligible candidates available in this run."} />
                  )}
                </DisclosureCard>

                <details className="top-gap-small">
                  <summary className="helper-text">Show raw candidate breakdown JSON</summary>
                  <pre className="code-block top-gap-small">{JSON.stringify(selectedRun.candidates, null, 2)}</pre>
                </details>
              </div>
            ) : (
              <EmptyState message="No run selected." />
            )}
          </Card>

          <DisclosureCard kicker="Configs" title="Config versions" subtitle="Promote a stored version to become the live plan-generation configuration only after validation supports it." actions={<HelpHint tooltip="Config versions capture baseline and promoted parameter sets so live plan construction stays auditable." to={tuningSpecDoc} />}>
            {configs.length === 0 ? (
              <EmptyState message="No config versions available yet." />
            ) : (
              <div className="data-stack top-gap-small">
                {configs.map((config) => (
                  <article key={config.id ?? config.version_label} className="data-card">
                    <div className="data-card-header">
                      <div className="cluster">
                        <Badge tone={planGenerationTuningConfigTone(config.status)}>{config.status}</Badge>
                        <Badge>{config.version_label}</Badge>
                        <Badge>{config.source}</Badge>
                      </div>
                      <div className="helper-text">#{config.id ?? "?"}</div>
                    </div>
                    <div className="cluster top-gap-small">
                      <button className="button-secondary" type="button" disabled={saving === `promote-${config.id ?? 0}` || config.id === state.state.active_config_version_id} onClick={() => void promote(config.id)}>
                        {saving === `promote-${config.id ?? 0}` ? "… Promoting" : config.id === state.state.active_config_version_id ? "✓ Active" : "↑ Promote"}
                      </button>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </DisclosureCard>
        </div>
      ) : null}
    </>
  );
}
