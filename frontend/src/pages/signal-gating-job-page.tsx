import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { getJson, postForm } from "../api";
import { Badge, Card, EmptyState, ErrorState, HelpHint, LoadingState, PageHeader, SectionTitle, StatCard } from "../components/ui";
import type { SignalGatingTuningResponse, SignalGatingTuningRun, SignalGatingTuningRunsResponse, SignalGatingTuningState } from "../types";

function statusTone(status: string): "ok" | "warning" | "danger" | "neutral" | "info" {
  if (status === "completed") return "ok";
  if (status === "completed_with_warnings") return "warning";
  if (status === "failed") return "danger";
  if (status === "running") return "info";
  return "neutral";
}

function formatValue(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "—";
  }
  return value.toFixed(digits);
}

function formatCount(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "—";
  }
  return String(value);
}

export function SignalGatingJobPage() {
  const [tuningState, setTuningState] = useState<SignalGatingTuningResponse | null>(null);
  const [runs, setRuns] = useState<SignalGatingTuningRun[] | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);

  async function loadData(selectLatest = false) {
    try {
      setError(null);
      const [loadedState, loadedRuns] = await Promise.all([
        getJson<SignalGatingTuningResponse>("/api/signal-gating-tuning"),
        getJson<SignalGatingTuningRunsResponse>("/api/signal-gating-tuning/runs?limit=20"),
      ]);
      setTuningState(loadedState);
      setRuns(loadedRuns.runs);
      if (selectLatest) {
        setSelectedRunId(loadedRuns.runs[0]?.id ?? loadedState.latest_run?.id ?? null);
      } else if (selectedRunId === null) {
        setSelectedRunId(loadedRuns.runs[0]?.id ?? loadedState.latest_run?.id ?? null);
      }
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to load signal gating job");
    }
  }

  useEffect(() => {
    void loadData(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selectedRun = useMemo(() => {
    if (!runs || runs.length === 0) {
      return null;
    }
    return runs.find((run) => run.id === selectedRunId) ?? runs[0] ?? null;
  }, [runs, selectedRunId]);

  async function runTuning(apply: boolean) {
    try {
      setSaving(apply ? "apply" : "run");
      setError(null);
      const run = await postForm<SignalGatingTuningRun>(`/api/signal-gating-tuning/run?apply=${apply ? "true" : "false"}`, {});
      await loadData();
      setSelectedRunId(run.id ?? null);
    } catch (runError) {
      setError(runError instanceof Error ? runError.message : "Failed to run signal gating tuning");
    } finally {
      setSaving(null);
    }
  }

  async function saveSignalGatingSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!tuningState) {
      return;
    }
    const formData = new FormData(event.currentTarget);
    try {
      setSaving("config");
      setError(null);
      await postForm<{ key: string; value: string }>("/api/settings/app", {
        key: "confidence_threshold",
        value: String(formData.get("confidence_threshold") ?? tuningState.current_confidence_threshold),
      });
      await postForm<{ signal_gating_tuning: SignalGatingTuningState }>("/api/settings/signal-gating-tuning", {
        threshold_offset: String(formData.get("threshold_offset") ?? tuningState.active_tuning.threshold_offset),
        confidence_adjustment: String(formData.get("confidence_adjustment") ?? tuningState.active_tuning.confidence_adjustment),
        near_miss_gap_cutoff: String(formData.get("near_miss_gap_cutoff") ?? tuningState.active_tuning.near_miss_gap_cutoff),
        shortlist_aggressiveness: String(formData.get("shortlist_aggressiveness") ?? tuningState.active_tuning.shortlist_aggressiveness),
        degraded_penalty: String(formData.get("degraded_penalty") ?? tuningState.active_tuning.degraded_penalty),
      });
      await loadData();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Failed to save signal gating settings");
    } finally {
      setSaving(null);
    }
  }

  return (
    <>
      <PageHeader
        kicker="Research"
        title="Signal gating tuning"
        subtitle="Tune the live gating controls and inspect the job history that produced each result. Decision samples live alongside this page as the review dataset, while the tuning job page stays focused on configuration and outcomes."
        actions={
          <>
            <HelpHint tooltip="Signal-gating tuning adjusts upstream selection thresholds to improve recall before plans are generated." to="/docs?doc=signal-gating-tuning-guide" />
            <Link to="/research" className="button-subtle">Research hub</Link>
            <Link to="/research/decision-samples" className="button-secondary">Decision samples</Link>
          </>
        }
      />

      {error ? <ErrorState message={error} /> : null}
      {!tuningState || !runs ? <LoadingState message="Loading signal gating job…" /> : null}

      {tuningState && runs ? (
        <div className="stack-page">
          <section className="metrics-grid">
            <StatCard label="Current threshold" value={formatValue(tuningState.current_confidence_threshold)} helper="Live confidence threshold" />
            <StatCard label="Active offset" value={formatValue(tuningState.active_tuning.threshold_offset)} helper="Tuning offset in effect" />
            <StatCard label="Latest best" value={formatValue(tuningState.latest_run?.best_threshold)} helper="Winning candidate threshold" />
            <StatCard label="Latest score" value={formatValue(tuningState.latest_run?.best_score, 3)} helper="Winning candidate score" />
          </section>

          <Card>
            <SectionTitle
              kicker="Configuration"
              title="Signal gating controls"
              subtitle="Adjust the live base threshold and the tuning parameters that shape recommendation selection."
              actions={<HelpHint tooltip="These controls tune shortlist selection and threshold behavior before downstream plan generation." to="/docs?doc=signal-gating-tuning-guide" />}
            />
            <form className="stack-form" onSubmit={(event) => void saveSignalGatingSettings(event)}>
              <div className="form-grid">
                <label className="form-field"><span>Confidence threshold</span><input name="confidence_threshold" defaultValue={String(tuningState.current_confidence_threshold)} /></label>
                <label className="form-field"><span>Threshold offset</span><input name="threshold_offset" defaultValue={String(tuningState.active_tuning.threshold_offset)} /></label>
                <label className="form-field"><span>Confidence adjustment</span><input name="confidence_adjustment" defaultValue={String(tuningState.active_tuning.confidence_adjustment)} /></label>
                <label className="form-field"><span>Near-miss cutoff</span><input name="near_miss_gap_cutoff" defaultValue={String(tuningState.active_tuning.near_miss_gap_cutoff)} /></label>
                <label className="form-field"><span>Shortlist aggressiveness</span><input name="shortlist_aggressiveness" defaultValue={String(tuningState.active_tuning.shortlist_aggressiveness)} /></label>
                <label className="form-field"><span>Degraded penalty</span><input name="degraded_penalty" defaultValue={String(tuningState.active_tuning.degraded_penalty)} /></label>
              </div>
              <div className="helper-text">Zeroed settings preserve baseline behavior. The effective live threshold combines the base confidence threshold with the tuning offset.</div>
              <div className="cluster top-gap-small">
                <button className="button" type="submit" disabled={saving !== null}>{saving === "config" ? "Saving…" : "Save gating settings"}</button>
                <button className="button-secondary" type="button" disabled={saving !== null} onClick={() => void runTuning(false)}>{saving === "run" ? "Running…" : "Run tuning"}</button>
                <button className="button-secondary" type="button" disabled={saving !== null} onClick={() => void runTuning(true)}>{saving === "apply" ? "Running & applying…" : "Run and apply"}</button>
              </div>
            </form>
          </Card>

          <Card>
            <SectionTitle
              kicker="Latest result"
              title="Selected tuning run"
              subtitle="Inspect the currently selected run and its candidate scores."
              actions={<HelpHint tooltip="Review the winning threshold, baseline comparison, and candidate score distribution before applying changes." to="/docs?doc=signal-gating-tuning-guide" />}
            />
            {selectedRun ? (
              <div className="stack-page">
                <section className="metrics-grid">
                  <StatCard label="Status" value={selectedRun.status} helper="Run state" />
                  <StatCard label="Applied" value={selectedRun.applied ? "yes" : "no"} helper="Whether the config was saved" />
                  <StatCard label="Samples" value={formatCount(selectedRun.sample_count)} helper="Sample rows scored" />
                  <StatCard label="Resolved" value={formatCount(selectedRun.resolved_sample_count)} helper="Resolved samples used" />
                </section>
                <div className="helper-text">Objective: {selectedRun.objective_name} · Best threshold: {formatValue(selectedRun.best_threshold)} · Best score: {formatValue(selectedRun.best_score, 3)}</div>
                <div className="helper-text">Baseline threshold: {formatValue(selectedRun.baseline_threshold)} · Baseline score: {formatValue(selectedRun.baseline_score, 3)}</div>
                {selectedRun.summary && Object.keys(selectedRun.summary).length > 0 ? (
                  <pre className="code-block top-gap-small">{JSON.stringify(selectedRun.summary, null, 2)}</pre>
                ) : null}
                <SectionTitle kicker="Candidates" title="Run candidate results" subtitle="Sorted from best to worst by the tuning job." />
                {selectedRun.candidate_results.length === 0 ? (
                  <EmptyState message="No candidate results recorded for this run." />
                ) : (
                  <div className="data-stack top-gap-small">
                    {selectedRun.candidate_results.slice(0, 15).map((candidate, index) => (
                      <article key={`${selectedRun.id}-${index}`} className="data-card">
                        <div className="data-card-header">
                          <div className="cluster">
                            <Badge tone={index === 0 ? "ok" : "neutral"}>#{index + 1}</Badge>
                            <Badge>threshold {String(candidate.threshold ?? "—")}</Badge>
                            <Badge>score {String(candidate.score ?? "—")}</Badge>
                          </div>
                          <Badge tone={statusTone(selectedRun.status)}>run {selectedRun.id}</Badge>
                        </div>
                        <div className="cluster top-gap-small">
                          <Badge tone={candidate.selected_count > 0 ? "ok" : "neutral"}>selected {String(candidate.selected_count ?? 0)}</Badge>
                          <Badge tone={candidate.win_count > 0 ? "ok" : "warning"}>wins {String(candidate.win_count ?? 0)}</Badge>
                          <Badge tone={candidate.loss_count > 0 ? "danger" : "neutral"}>losses {String(candidate.loss_count ?? 0)}</Badge>
                          <Badge>precision {candidate.precision_percent ?? "—"}%</Badge>
                          <Badge>recall {candidate.recall_percent ?? "—"}%</Badge>
                        </div>
                        <div className="helper-text top-gap-small">Config: {JSON.stringify({
                          threshold_offset: candidate.threshold_offset,
                          confidence_adjustment: candidate.confidence_adjustment,
                          near_miss_gap_cutoff: candidate.near_miss_gap_cutoff,
                          shortlist_aggressiveness: candidate.shortlist_aggressiveness,
                          degraded_penalty: candidate.degraded_penalty,
                        })}</div>
                      </article>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <EmptyState message="No tuning runs have been recorded yet." />
            )}
          </Card>

          <Card>
            <SectionTitle kicker="History" title="Recent tuning runs" subtitle="Select any run to inspect its results." actions={<HelpHint tooltip="Run history shows whether the tuning objective improved and whether a winning threshold was applied." to="/docs?doc=signal-gating-tuning-guide" />} />
            {runs.length === 0 ? (
              <EmptyState message="No tuning runs available yet." />
            ) : (
              <div className="data-stack top-gap-small">
                {runs.map((run) => (
                  <button
                    key={run.id ?? run.created_at}
                    type="button"
                    className={`data-card data-card-button ${selectedRunId === run.id ? "data-card-selected" : ""}`}
                    onClick={() => setSelectedRunId(run.id ?? null)}
                  >
                    <div className="data-card-header">
                      <div className="cluster">
                        <Badge tone={statusTone(run.status)}>{run.status}</Badge>
                        <Badge>{run.applied ? "applied" : "dry run"}</Badge>
                        <Badge>#{run.id ?? "?"}</Badge>
                      </div>
                      <div className="helper-text">{run.started_at ?? run.created_at}</div>
                    </div>
                    <div className="helper-text top-gap-small">
                      Best threshold {formatValue(run.best_threshold)} · score {formatValue(run.best_score, 3)} · baseline {formatValue(run.baseline_threshold)}
                    </div>
                    <div className="helper-text">Samples {run.sample_count} · resolved {run.resolved_sample_count} · candidates {run.candidate_count}</div>
                  </button>
                ))}
              </div>
            )}
          </Card>
        </div>
      ) : null}
    </>
  );
}
