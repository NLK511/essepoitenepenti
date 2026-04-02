import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { getJson, postForm } from "../api";
import { Badge, Card, EmptyState, ErrorState, LoadingState, PageHeader, SectionTitle, StatCard } from "../components/ui";
import type { RecommendationDecisionSample, SignalGatingTuningResponse, SignalGatingTuningRun, SignalGatingTuningState } from "../types";
import { formatDate, yahooFinanceUrl } from "../utils";

function decisionTone(decisionType: string): "ok" | "warning" | "danger" | "neutral" | "info" {
  if (decisionType === "actionable") {
    return "ok";
  }
  if (decisionType === "near_miss") {
    return "warning";
  }
  if (decisionType === "degraded") {
    return "danger";
  }
  return "neutral";
}

function priorityTone(priority: string): "ok" | "warning" | "danger" | "neutral" | "info" {
  if (priority === "high") {
    return "danger";
  }
  if (priority === "medium") {
    return "warning";
  }
  return "neutral";
}

function gapLabel(value: number | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "—";
  }
  return `${value > 0 ? "+" : ""}${value.toFixed(1)} pts`;
}

function truncate(value: string, max = 180): string {
  if (value.length <= max) {
    return value;
  }
  return `${value.slice(0, max - 1).trimEnd()}…`;
}

export function RecommendationDecisionSamplesPage() {
  const [samples, setSamples] = useState<RecommendationDecisionSample[] | null>(null);
  const [tuningState, setTuningState] = useState<SignalGatingTuningResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [savingTuning, setSavingTuning] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        setError(null);
        const [loadedSamples, loadedTuningState] = await Promise.all([
          getJson<RecommendationDecisionSample[]>('/api/recommendation-decision-samples?limit=100'),
          getJson<SignalGatingTuningResponse>('/api/signal-gating-tuning'),
        ]);
        setSamples(loadedSamples);
        setTuningState(loadedTuningState);
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : "Failed to load decision samples");
      }
    }
    void load();
  }, []);

  const summary = useMemo(() => {
    const items = samples ?? [];
    return {
      total: items.length,
      actionable: items.filter((item) => item.decision_type === "actionable").length,
      nearMiss: items.filter((item) => item.decision_type === "near_miss").length,
      degraded: items.filter((item) => item.decision_type === "degraded").length,
      highPriority: items.filter((item) => item.review_priority === "high").length,
    };
  }, [samples]);

  const highPrioritySamples = useMemo(() => {
    return (samples ?? [])
      .filter((item) => item.review_priority === "high" || item.decision_type === "near_miss")
      .slice(0, 12);
  }, [samples]);

  async function runTuning(apply: boolean) {
    try {
      setSavingTuning(apply ? "apply" : "run");
      setError(null);
      await postForm<SignalGatingTuningRun>(`/api/signal-gating-tuning/run?apply=${apply ? "true" : "false"}`, {});
      const loadedTuningState = await getJson<SignalGatingTuningResponse>("/api/signal-gating-tuning");
      setTuningState(loadedTuningState);
      setError(null);
    } catch (runError) {
      setError(runError instanceof Error ? runError.message : "Failed to run signal gating tuning");
    } finally {
      setSavingTuning(null);
    }
  }

  async function saveSignalGatingTuningSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!tuningState) {
      return;
    }
    const formData = new FormData(event.currentTarget);
    try {
      setSavingTuning("config");
      setError(null);
      await postForm<{ signal_gating_tuning: SignalGatingTuningState }>("/api/settings/signal-gating-tuning", {
        threshold_offset: String(formData.get("threshold_offset") ?? tuningState.active_tuning.threshold_offset),
        confidence_adjustment: String(formData.get("confidence_adjustment") ?? tuningState.active_tuning.confidence_adjustment),
        near_miss_gap_cutoff: String(formData.get("near_miss_gap_cutoff") ?? tuningState.active_tuning.near_miss_gap_cutoff),
        shortlist_aggressiveness: String(formData.get("shortlist_aggressiveness") ?? tuningState.active_tuning.shortlist_aggressiveness),
        degraded_penalty: String(formData.get("degraded_penalty") ?? tuningState.active_tuning.degraded_penalty),
      });
      const loadedTuningState = await getJson<SignalGatingTuningResponse>("/api/signal-gating-tuning");
      setTuningState(loadedTuningState);
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Failed to save signal gating tuning settings");
    } finally {
      setSavingTuning(null);
    }
  }

  return (
    <>
      <PageHeader
        kicker="Research"
        title="Decision samples"
        subtitle="This page is for tuning and review. It keeps near-misses, rejected setups, and actionable plans in one central review surface so small action counts do not leave you blind to what the planner is doing."
        actions={
          <>
            <Link to="/research" className="button-subtle">Research hub</Link>
            <Link to="/jobs/recommendation-plans" className="button-secondary">Back to plans</Link>
          </>
        }
      />

      {error ? <ErrorState message={error} /> : null}
      {!samples && !error ? <LoadingState message="Loading decision samples…" /> : null}

      {samples ? (
        <div className="stack-page">
          <section className="metrics-grid">
            <StatCard label="Samples" value={summary.total} helper="Generated recommendation-plan decision rows" />
            <StatCard label="Actionable" value={summary.actionable} helper="Long and short decisions" />
            <StatCard label="Near misses" value={summary.nearMiss} helper="High-signal no-action plans" />
            <StatCard label="High priority" value={summary.highPriority} helper="Review these first" />
            <StatCard label="Degraded" value={summary.degraded} helper="Plans produced with missing or failed deep analysis" />
          </section>

          <Card>
            <SectionTitle
              kicker="Review queue"
              title="High-priority samples"
              subtitle="Use this list to inspect borderline no-action plans and the rare actionable cases side by side."
            />
            {highPrioritySamples.length === 0 ? (
              <EmptyState message="No decision samples available yet." />
            ) : (
              <div className="data-stack top-gap-small">
                {highPrioritySamples.map((sample) => (
                  <article key={sample.id ?? `${sample.ticker}-${sample.created_at}`} className="data-card">
                    <div className="data-card-header">
                      <div className="cluster">
                        <a href={yahooFinanceUrl(sample.ticker)} className="badge badge-info badge-link" target="_blank" rel="noreferrer noopener">{sample.ticker}</a>
                                                <Badge tone={decisionTone(sample.decision_type)}>{sample.decision_type}</Badge>
                        <Badge tone={priorityTone(sample.review_priority)}>{sample.review_priority}</Badge>
                      </div>
                      <div className="helper-text">{formatDate(sample.created_at)}</div>
                    </div>
                    <div className="cluster top-gap-small">
                      <Badge>{sample.action}</Badge>
                      <Badge>{sample.horizon}</Badge>
                      <Badge tone={sample.shortlisted ? "ok" : "neutral"}>{sample.shortlisted ? `shortlist #${sample.shortlist_rank ?? "?"}` : "not shortlisted"}</Badge>
                      <Badge tone={sample.confidence_gap_percent !== null && sample.confidence_gap_percent >= 0 ? "ok" : "warning"}>{gapLabel(sample.confidence_gap_percent)}</Badge>
                    </div>
                    <div className="helper-text top-gap-small">Reason: {sample.decision_reason || "—"}</div>
                    <div className="helper-text">Notes: {truncate(sample.review_notes || sample.decision_reason || "No review notes stored.")}</div>
                    <div className="helper-text">Run {sample.run_id ?? "—"} · Job {sample.job_id ?? "—"} · Signal {sample.ticker_signal_snapshot_id ?? "—"}</div>
                    <div className="cluster top-gap-small">
                      <Link
                        to={sample.recommendation_plan_id ? `/jobs/recommendation-plans?plan_id=${sample.recommendation_plan_id}` : "/jobs/recommendation-plans"}
                        className="button-secondary"
                      >
                        Open plan
                      </Link>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </Card>

          <Card>
            <SectionTitle
              kicker="Tuning guidance"
              title="How to use the samples"
              subtitle="This dataset is intentionally broader than final outcomes so threshold tuning has enough signal to work with."
            />
            <ul className="checklist">
              <li>Start with high-priority near misses before changing thresholds.</li>
              <li>Compare actionable samples with rejected samples at similar confidence.</li>
              <li>Look at the confidence gap and shortlist decision payload to understand why a plan missed escalation.</li>
              <li>Use the plan button to jump directly to the canonical recommendation output.</li>
            </ul>
          </Card>

          <Card>
            <SectionTitle
              kicker="Research"
              title="Signal gating configuration"
              subtitle="Edit the active gating controls that shape live recommendation selection."
            />
            {tuningState ? (
              <form className="stack-form" onSubmit={(event) => void saveSignalGatingTuningSettings(event)}>
                <div className="form-grid">
                  <label className="form-field"><span>Threshold offset</span><input name="threshold_offset" defaultValue={String(tuningState.active_tuning.threshold_offset)} /></label>
                  <label className="form-field"><span>Confidence adjustment</span><input name="confidence_adjustment" defaultValue={String(tuningState.active_tuning.confidence_adjustment)} /></label>
                  <label className="form-field"><span>Near-miss cutoff</span><input name="near_miss_gap_cutoff" defaultValue={String(tuningState.active_tuning.near_miss_gap_cutoff)} /></label>
                  <label className="form-field"><span>Shortlist aggressiveness</span><input name="shortlist_aggressiveness" defaultValue={String(tuningState.active_tuning.shortlist_aggressiveness)} /></label>
                  <label className="form-field"><span>Degraded penalty</span><input name="degraded_penalty" defaultValue={String(tuningState.active_tuning.degraded_penalty)} /></label>
                </div>
                <div className="helper-text">These values control the live proposal path. Zeroed settings preserve baseline behavior.</div>
                <div className="cluster top-gap-small">
                  <button className="button" type="submit" disabled={savingTuning !== null}>
                    {savingTuning === "config" ? "Saving…" : "Save tuning config"}
                  </button>
                </div>
              </form>
            ) : (
              <div className="helper-text">Loading tuning state…</div>
            )}
          </Card>

          <Card>
            <SectionTitle
              kicker="Research"
              title="Signal gating tuning"
              subtitle="Run the raw grid-search tuner against the sample set, then inspect the latest winner and whether it was applied."
            />
            {tuningState ? (
              <div className="stack-page">
                <section className="metrics-grid">
                  <StatCard label="Current threshold" value={tuningState.current_confidence_threshold} helper="Live confidence threshold" />
                  <StatCard label="Active offset" value={tuningState.active_tuning.threshold_offset} helper="Current tuning offset" />
                  <StatCard label="Latest best" value={tuningState.latest_run?.best_threshold ?? "—"} helper="Winning candidate threshold" />
                  <StatCard label="Latest score" value={tuningState.latest_run?.best_score ?? "—"} helper="Winning candidate score" />
                </section>
                {tuningState.latest_run ? (
                  <>
                    <div className="helper-text">Objective: {tuningState.latest_run.objective_name} · Status: {tuningState.latest_run.status} · Applied: {tuningState.latest_run.applied ? "yes" : "no"}</div>
                    <div className="helper-text">Sample count: {tuningState.latest_run.sample_count} · Resolved samples: {tuningState.latest_run.resolved_sample_count} · Candidates: {tuningState.latest_run.candidate_count}</div>
                    <div className="helper-text">Baseline threshold: {tuningState.latest_run.baseline_threshold ?? "—"} · Baseline score: {tuningState.latest_run.baseline_score ?? "—"}</div>
                  </>
                ) : (
                  <div className="helper-text">No tuning run has been recorded yet.</div>
                )}
                <div className="cluster top-gap-small">
                  <button className="button" type="button" disabled={savingTuning !== null} onClick={() => void runTuning(false)}>
                    {savingTuning === "run" ? "Running…" : "Run tuning"}
                  </button>
                  <button className="button-secondary" type="button" disabled={savingTuning !== null} onClick={() => void runTuning(true)}>
                    {savingTuning === "apply" ? "Running & applying…" : "Run and apply"}
                  </button>
                </div>
              </div>
            ) : (
              <div className="helper-text">Loading tuning state…</div>
            )}
          </Card>
        </div>
      ) : null}
    </>
  );
}
