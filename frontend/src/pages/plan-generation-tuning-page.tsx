import { useEffect, useMemo, useState } from "react";

import { getJson, postForm } from "../api";
import { Badge, Card, EmptyState, ErrorState, HelpHint, LoadingState, PageHeader, SectionTitle, StatCard } from "../components/ui";
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
const CAMPAIGN_PRIORITY: Record<string, number> = {
  entry_calibration: 1,
  risk_protection: 2,
  reward_expansion: 3,
  historical_reuse: 4,
  bounded_random_mutation: 5,
  baseline: 0,
  historical_reuse_or_random_mutation: 6,
  unknown: 7,
};

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

function candidateExperimentSignature(candidate: PlanGenerationTuningRun["candidates"][number]): string {
  const keys = [...candidate.changed_keys].sort();
  return keys.length > 0 ? keys.join(" + ") : "baseline";
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

  const selectedRunCandidates = selectedRun?.candidates ?? [];

  const selectedRunCampaignSummaries = useMemo(() => {
    if (!selectedRun) return [];
    const groups = new Map<
      string,
      {
        campaign: string;
        candidateCount: number;
        bestCandidate: PlanGenerationTuningRun["candidates"][number] | null;
        validationWinRateSum: number;
        validationExpectedValueSum: number;
        validationActionableCount: number;
      }
    >();
    for (const candidate of selectedRun.candidates) {
      const campaign = candidateCampaign(candidate);
      const current = groups.get(campaign) ?? {
        campaign,
        candidateCount: 0,
        bestCandidate: null,
        validationWinRateSum: 0,
        validationExpectedValueSum: 0,
        validationActionableCount: 0,
      };
      current.candidateCount += 1;
      current.validationWinRateSum += candidateMetric(candidate, "validation_win_rate_percent") ?? 0;
      current.validationExpectedValueSum += candidateMetric(candidate, "validation_expected_value") ?? 0;
      current.validationActionableCount += candidateMetric(candidate, "validation_actionable_count") ?? 0;
      if (!current.bestCandidate || (candidate.rank ?? Number.POSITIVE_INFINITY) < (current.bestCandidate.rank ?? Number.POSITIVE_INFINITY)) {
        current.bestCandidate = candidate;
      }
      groups.set(campaign, current);
    }
    return Array.from(groups.values())
      .map((group) => ({
        ...group,
        averageValidationWinRate: group.candidateCount > 0 ? group.validationWinRateSum / group.candidateCount : null,
        averageValidationExpectedValue: group.candidateCount > 0 ? group.validationExpectedValueSum / group.candidateCount : null,
      }))
      .sort((left, right) => (CAMPAIGN_PRIORITY[left.campaign] ?? 99) - (CAMPAIGN_PRIORITY[right.campaign] ?? 99));
  }, [selectedRun]);

  const selectedRunMetricSpread = useMemo(() => {
    if (!selectedRun) return null;
    const searchRates = new Set<string>();
    const validationRates = new Set<string>();
    const validationExpectedValues = new Set<string>();
    for (const candidate of selectedRun.candidates) {
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
  }, [selectedRun]);

  const selectedRunCandidateGroups = useMemo(() => {
    if (!selectedRun) return [];
    const groups = new Map<
      string,
      {
        signature: string;
        changedKeys: string[];
        campaigns: Set<string>;
        candidates: PlanGenerationTuningRun["candidates"];
        bestRank: number;
      }
    >();
    for (const candidate of selectedRun.candidates) {
      const signature = candidateExperimentSignature(candidate);
      const current = groups.get(signature) ?? {
        signature,
        changedKeys: [...candidate.changed_keys].sort(),
        campaigns: new Set<string>(),
        candidates: [],
        bestRank: Number.POSITIVE_INFINITY,
      };
      current.campaigns.add(candidateCampaign(candidate));
      current.candidates.push(candidate);
      current.bestRank = Math.min(current.bestRank, candidate.rank ?? Number.POSITIVE_INFINITY);
      groups.set(signature, current);
    }
    return Array.from(groups.values())
      .map((group) => ({
        ...group,
        candidates: [...group.candidates].sort((left, right) => (left.rank ?? Number.POSITIVE_INFINITY) - (right.rank ?? Number.POSITIVE_INFINITY)),
        bestCandidate: [...group.candidates].sort((left, right) => (left.rank ?? Number.POSITIVE_INFINITY) - (right.rank ?? Number.POSITIVE_INFINITY))[0] ?? null,
      }))
      .sort((left, right) => left.bestRank - right.bestRank || left.signature.localeCompare(right.signature));
  }, [selectedRun]);

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
        subtitle="Inspect the exploration plan, campaign outcomes, and candidate rankings without having to read raw JSON first."
        actions={<HelpHint tooltip="This page shows the dedicated plan-generation tuning workflow: live config, ranked candidates, campaign results, and guarded promotions." to={tuningSpecDoc} />}
      />
      {error ? <ErrorState message={error} /> : null}
      {!state || !runs || !configs ? <LoadingState message="Loading plan generation tuning…" /> : null}
      {state && runs && configs ? (
        <div className="stack-page">
          <section className="metrics-grid">
            <StatCard label="Active config" value={String(state.state.active_config_version_id ?? "baseline")} helper="Current live config version" tooltip="The parameter set that is currently live for plan generation. New tuning runs compare candidates against this active baseline." tooltipTo={tuningSpecDoc} />
            <StatCard label="Auto mode" value={state.state.auto_enabled ? "on" : "off"} helper="Scheduled autonomous tuning" tooltip="Whether this tuning workflow can run on its own schedule instead of only when an operator starts it manually." tooltipTo={tuningSpecDoc} />
            <StatCard label="Auto promote" value={state.state.auto_promote_enabled ? "on" : "off"} helper="Whether winners can be promoted automatically" tooltip="Whether a winning candidate can become the live configuration automatically after it passes the promotion gate." tooltipTo={glossaryDoc("promotion-gate")} />
            <StatCard label="Latest run" value={String(state.state.latest_run?.id ?? "—")} helper="Most recent tuning execution" tooltip="The most recent stored tuning run, including its ranked candidates and any promotion outcome." tooltipTo={tuningSpecDoc} />
          </section>

          <section className="card-grid">
            <Card>
              <SectionTitle kicker="How it works" title="Process overview" subtitle="A short, readable explanation of the tuning flow before you inspect the raw results." actions={<HelpHint tooltip="This explains the order of operations so the results below are easier to interpret." to={tuningSpecDoc} />} />
              <div className="data-stack top-gap-small">
                <article className="data-card">
                  <div className="data-card-header">
                    <div className="cluster"><Badge tone="info">1</Badge><Badge>Split the data</Badge></div>
                  </div>
                  <div className="helper-text top-gap-small">Eligible historical records are split into a search slice and a holdout validation slice. Search helps discover candidates; validation checks whether they still hold up.</div>
                </article>
                <article className="data-card">
                  <div className="data-card-header">
                    <div className="cluster"><Badge tone="info">2</Badge><Badge>Try campaign phases</Badge></div>
                  </div>
                  <div className="helper-text top-gap-small">The tuner spends candidate budget in ordered campaigns: entry calibration, risk protection, reward expansion, historical reuse, then bounded random mutation.</div>
                </article>
                <article className="data-card">
                  <div className="data-card-header">
                    <div className="cluster"><Badge tone="info">3</Badge><Badge>Rank by validation</Badge></div>
                  </div>
                  <div className="helper-text top-gap-small">Candidates are ranked lexicographically by validation win rate, then validation win count, then validation expected value. Search metrics are shown to help explain why a candidate looked promising.</div>
                </article>
              </div>
            </Card>

            <Card>
              <SectionTitle kicker="Controls" title="Run plan generation tuning" subtitle="Launch a dry run or guarded promotion using the immutable backend rules and historical replay." actions={<HelpHint tooltip="Dry runs rank candidates without changing the live config. Apply mode promotes only if the winner passes backend guardrails." to={tuningSpecDoc} />} />
              <div className="cluster top-gap-small">
                <button className="button" type="button" disabled={saving !== null} onClick={() => void runTuning(false)}>{saving === "run" ? "Running…" : "Run dry"}</button>
                <button className="button-secondary" type="button" disabled={saving !== null} onClick={() => void runTuning(true)}>{saving === "apply" ? "Running & applying…" : "Run and promote if eligible"}</button>
              </div>
              <details className="top-gap-small">
                <summary className="helper-text">Show active config JSON</summary>
                <pre className="code-block top-gap-small">{JSON.stringify(state.state.active_config, null, 2)}</pre>
              </details>
            </Card>
          </section>

          <Card>
            <SectionTitle kicker="Exploration" title="Ranked campaign plan" subtitle="The backend exposes the exploration phases and their budgets so you can see where the search effort went." actions={<HelpHint tooltip="This plan keeps exploration ordered: entry first, then risk, then reward, then historical reuse, then random mutation." to={tuningSpecDoc} />} />
            <div className="table-wrapper top-gap-small">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>priority</th>
                    <th>campaign</th>
                    <th>budget</th>
                    <th>primary knobs</th>
                    <th>why it exists</th>
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
            <div className="helper-text top-gap-small">Default exploration budget before deduplication: 144 candidates.</div>
          </Card>

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
            <SectionTitle kicker="Campaign results" title="Results by exploration phase" subtitle="This is the compact summary of what each campaign produced." actions={<HelpHint tooltip="This view rolls up candidate results by campaign so you can see whether entry, risk, reward, reuse, or random mutation produced the best evidence." to={tuningSpecDoc} />} />
            {selectedRun ? (
              selectedRunCampaignSummaries.length > 0 ? (
                <div className="table-wrapper top-gap-small">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>campaign</th>
                        <th>candidates</th>
                        <th>best rank</th>
                        <th>avg search WR</th>
                        <th>avg validation WR</th>
                        <th>avg validation EV</th>
                        <th>actionable rows</th>
                        <th>best changes</th>
                      </tr>
                    </thead>
                    <tbody>
                      {selectedRunCampaignSummaries.map((campaign) => (
                        <tr key={campaign.campaign}>
                          <td>
                            <Badge tone={campaign.campaign === "entry_calibration" || campaign.campaign === "risk_protection" || campaign.campaign === "reward_expansion" ? "ok" : "info"} title={campaign.campaign}>
                              {humanizeCampaignName(campaign.campaign)}
                            </Badge>
                          </td>
                          <td>{campaign.candidateCount}</td>
                          <td>{campaign.bestCandidate?.rank ?? "—"}</td>
                          <td>{formatPercent(campaign.bestCandidate ? candidateMetric(campaign.bestCandidate, "search_win_rate_percent") : null)}</td>
                          <td>{formatPercent(campaign.averageValidationWinRate)}</td>
                          <td>{formatNumber(campaign.averageValidationExpectedValue)}</td>
                          <td>{campaign.validationActionableCount}</td>
                          <td className="helper-text">{campaign.bestCandidate?.changed_keys.join(", ") || "no changes"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <EmptyState message="No campaign results yet." />
              )
            ) : (
              <EmptyState message="No run selected." />
            )}
          </Card>

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
            <SectionTitle kicker="Selected run" title="Candidate ranking" subtitle="The backend ranks candidates lexicographically by validation win rate, then win count, then expected value." actions={<HelpHint tooltip="Candidate ordering is deterministic: valid evidence first, then validation win rate, then validation win count, then validation expected value." to={tuningSpecDoc} />} />
            {selectedRun ? (
              <div className="stack-page">
                <div className="helper-text">Promotion mode: {selectedRun.promotion_mode} · Winner candidate: {selectedRun.winning_candidate_id ?? "—"} · Promoted config: {selectedRun.promoted_config_version_id ?? "—"}</div>
                <div className="helper-text">Search win rate shows the discovery slice; validation win rate uses {selectedRun.summary.validation_mode === "rolling_walk_forward" ? "rolling walk-forward validation across the eligible history" : "a single holdout slice"}. If those disagree, trust the validation number more.</div>
                {selectedRunMetricSpread && selectedRunMetricSpread.searchWinRateCount === 1 && selectedRunMetricSpread.validationWinRateCount === 1 ? (
                  <div className="alert alert-warning top-gap-small">
                    This run is tie-heavy: all candidates share the same search and validation win rates, so ranking is effectively being decided by tie-breakers like expected value, distance from the baseline, and number of changed parameters.
                  </div>
                ) : null}
                <div className="data-stack top-gap-small">
                  {selectedRunCandidateGroups.map((group) => {
                    const campaigns = [...group.campaigns].map(humanizeCampaignName).join(" · ");
                    const sharedChanges = group.changedKeys.length > 0 ? group.changedKeys.join(", ") : "baseline";
                    return (
                      <details key={group.signature} className="workflow-details data-card">
                        <summary>
                          <div className="data-card-header">
                            <div className="cluster">
                              <Badge tone={group.bestRank === 1 ? "ok" : "neutral"}>#{group.bestRank}</Badge>
                              <Badge>{group.candidates.length} candidates</Badge>
                              <Badge>{campaigns}</Badge>
                            </div>
                            <div className="helper-text">{sharedChanges}</div>
                          </div>
                        </summary>
                        <div className="workflow-details-body top-gap-small">
                          <div className="helper-text">Best validation WR {formatPercent(candidateMetric(group.bestCandidate, "validation_win_rate_percent"))} · best validation EV {formatNumber(candidateMetric(group.bestCandidate, "validation_expected_value"))} · {selectedRun.summary.validation_mode === "rolling_walk_forward" ? "qualified slices" : "actionable"} {candidateMetric(group.bestCandidate, "validation_actionable_count") ?? "—"}</div>
                          <div className="table-wrapper top-gap-small">
                            <table className="data-table">
                              <thead>
                                <tr>
                                  <th>rank</th>
                                  <th>campaign</th>
                                  <th>changed values</th>
                                  <th>search WR</th>
                                  <th>validation WR</th>
                                  <th>validation EV</th>
                                  <th>{selectedRun.summary.validation_mode === "rolling_walk_forward" ? "qualified slices" : "actionable"}</th>
                                  <th>promo</th>
                                </tr>
                              </thead>
                              <tbody>
                                {group.candidates.map((candidate) => {
                                  const campaign = humanizeCampaignName(candidateCampaign(candidate));
                                  const changedValues = candidate.changed_keys.length > 0
                                    ? candidate.changed_keys.map((key) => `${key}=${candidateConfigValue(candidate, key)}`).join(" · ")
                                    : "baseline";
                                  return (
                                    <tr key={candidate.id ?? `${selectedRun.id}-${candidate.rank}`}>
                                      <td><Badge tone={candidate.rank === 1 ? "ok" : "neutral"}>#{candidate.rank ?? "?"}</Badge></td>
                                      <td>{campaign}</td>
                                      <td className="helper-text">{changedValues}</td>
                                      <td>{formatPercent(candidateMetric(candidate, "search_win_rate_percent"))}</td>
                                      <td>{formatPercent(candidateMetric(candidate, "validation_win_rate_percent"))}</td>
                                      <td>{formatNumber(candidateMetric(candidate, "validation_expected_value"))}</td>
                                      <td>{candidateMetric(candidate, "validation_actionable_count") ?? "—"}</td>
                                      <td><Badge tone={candidate.promotion_eligible ? "ok" : "warning"}>{candidate.promotion_eligible ? "eligible" : "blocked"}</Badge></td>
                                    </tr>
                                  );
                                })}
                              </tbody>
                            </table>
                          </div>
                        </div>
                      </details>
                    );
                  })}
                </div>
                <details className="top-gap-small">
                  <summary className="helper-text">Show raw candidate breakdown JSON</summary>
                  <pre className="code-block top-gap-small">{JSON.stringify(selectedRun.candidates, null, 2)}</pre>
                </details>
              </div>
            ) : (
              <EmptyState message="No run selected." />
            )}
          </Card>

          <Card>
            <SectionTitle kicker="Configs" title="Config versions" subtitle="Promote a stored version to become the live plan-generation configuration." actions={<HelpHint tooltip="Config versions capture baseline and promoted parameter sets so live plan construction stays auditable." to={tuningSpecDoc} />} />
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
