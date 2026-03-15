import { FormEvent, useEffect, useMemo, useState } from "react";

import { getJson, postForm } from "../api";
import { Badge, Card, ErrorState, LoadingState, PageHeader, SectionTitle } from "../components/ui";
import type { AppSetting, AppPreflightReport, OptimizationState, ProviderCredential, SettingsResponse } from "../types";
import { toSettingMap } from "../utils";

interface SettingsViewData {
  settings: AppSetting[];
  providers: ProviderCredential[];
  optimization: OptimizationState;
  preflight: AppPreflightReport;
}

export function SettingsPage() {
  const [data, setData] = useState<SettingsViewData | null>(null);
  const [dataVersion, setDataVersion] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [selectedBackupPath, setSelectedBackupPath] = useState<string>("");

  async function loadData() {
    try {
      setError(null);
      const [settingsResponse, preflight] = await Promise.all([
        getJson<SettingsResponse>("/api/settings"),
        getJson<AppPreflightReport>("/api/health/preflight"),
      ]);
      setData({
        settings: settingsResponse.settings,
        providers: settingsResponse.providers,
        optimization: settingsResponse.optimization,
        preflight,
      });
      setSelectedBackupPath(settingsResponse.optimization.latest_backup?.path ?? "");
      setDataVersion((v) => v + 1);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to load settings");
    }
  }

  useEffect(() => {
    void loadData();
  }, []);

  const settingMap = useMemo(() => toSettingMap(data?.settings ?? []), [data]);

  async function saveAppSetting(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    try {
      setSaving("app");
      setError(null);
      setNotice(null);
      await postForm<AppSetting>("/api/settings/app", {
        key: String(formData.get("key") ?? "confidence_threshold"),
        value: String(formData.get("value") ?? ""),
      });
      await loadData();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Failed to save app setting");
    } finally {
      setSaving(null);
    }
  }

  async function saveSummarySettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    try {
      setSaving("summary");
      setError(null);
      setNotice(null);
      await postForm<{ settings: Record<string, string> }>("/api/settings/summary", {
        backend: String(formData.get("backend") ?? "news_digest"),
        model: String(formData.get("model") ?? ""),
        timeout_seconds: String(formData.get("timeout_seconds") ?? "60"),
        max_tokens: String(formData.get("max_tokens") ?? "220"),
        pi_command: String(formData.get("pi_command") ?? "pi"),
        pi_agent_dir: String(formData.get("pi_agent_dir") ?? ""),
        pi_api_url: String(formData.get("pi_api_url") ?? ""),
        pi_api_key: String(formData.get("pi_api_key") ?? ""),
        prompt: String(formData.get("prompt") ?? ""),
      });
      await loadData();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Failed to save summary settings");
    } finally {
      setSaving(null);
    }
  }

  async function saveOptimizationSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    try {
      setSaving("optimization");
      setError(null);
      setNotice(null);
      await postForm<{ optimization: OptimizationState }>("/api/settings/optimization", {
        minimum_resolved_trades: String(formData.get("minimum_resolved_trades") ?? "50"),
      });
      await loadData();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Failed to save optimization settings");
    } finally {
      setSaving(null);
    }
  }

  async function rollbackOptimizationWeights() {
    try {
      setSaving("optimization-rollback");
      setError(null);
      setNotice(null);
      const result = await postForm<{ rollback: Record<string, unknown>; optimization: OptimizationState }>("/api/settings/optimization/rollback", {
        backup_path: selectedBackupPath,
      });
      const restoredFrom = typeof result.rollback.restored_from === "string" ? result.rollback.restored_from : selectedBackupPath;
      setNotice(`Weights restored from backup: ${restoredFrom}`);
      await loadData();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Failed to roll back weights");
    } finally {
      setSaving(null);
    }
  }

  async function saveProvider(event: FormEvent<HTMLFormElement>, provider: string) {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    try {
      setSaving(provider);
      setError(null);
      setNotice(null);
      await postForm<ProviderCredential>("/api/settings/providers", {
        provider,
        api_key: String(formData.get("api_key") ?? ""),
        api_secret: String(formData.get("api_secret") ?? ""),
      });
      await loadData();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : `Failed to save ${provider} credential`);
    } finally {
      setSaving(null);
    }
  }

  return (
    <>
      <PageHeader
        kicker="System operation"
        title="Configure credentials, summary behavior, and internal engine health in one place."
        subtitle="The settings page remains the control point for first-time setup and troubleshooting, but now uses typed client-side forms over the same backend endpoints."
      />
      {error ? <ErrorState message={error} /> : null}
      {notice ? <Card><div className="helper-text">{notice}</div></Card> : null}
      {!data && !error ? <LoadingState message="Loading settings…" /> : null}
      {data ? (
        <div className="stack-page">
          <section className="metrics-grid">
            <Card><div className="metric-label">Internal pipeline health</div><div className="metric-value">{data.preflight.status}</div></Card>
            <Card><div className="metric-label">Summary backend</div><div className="metric-value">{settingMap.summary_backend ?? "news_digest"}</div></Card>
            <Card><div className="metric-label">Optimization threshold</div><div className="metric-value">{data.optimization.minimum_resolved_trades}</div></Card>
            <Card><div className="metric-label">Weight backups</div><div className="metric-value">{data.optimization.backup_count}</div></Card>
          </section>

          <section className="card-grid" key={dataVersion}>
            <Card>
              <SectionTitle kicker="Application settings" title="Core operator controls" subtitle="Rotating the secret key without a migration path will invalidate stored credentials." />
              <form className="stack-form" onSubmit={saveAppSetting}>
                <input type="hidden" name="key" value="confidence_threshold" />
                <label className="form-field">
                  <span>Confidence threshold</span>
                  <input name="value" defaultValue={settingMap.confidence_threshold ?? "60"} />
                </label>
                <button className="button" type="submit" disabled={saving === "app"}>{saving === "app" ? "Saving…" : "Save confidence threshold"}</button>
              </form>
            </Card>

            <Card>
              <SectionTitle kicker="Optimization guardrails" title="Weight optimization safety controls" subtitle="These settings affect scheduled and manual optimization runs. Each optimization now creates a rollback-capable backup of weights.json before the prototype script mutates it." />
              <form className="stack-form" onSubmit={saveOptimizationSettings}>
                <label className="form-field">
                  <span>Minimum resolved trades</span>
                  <input name="minimum_resolved_trades" defaultValue={String(data.optimization.minimum_resolved_trades)} />
                </label>
                <div className="helper-text">Current weights file: {data.optimization.weights_path}</div>
                <div className="helper-text">Backup directory: {data.optimization.backup_dir}</div>
                <div className="helper-text">Recovery flow: choose a backup below, restore it, then rerun optimization only after verifying the previous run details.</div>
                <div className="cluster">
                  <button className="button" type="submit" disabled={saving === "optimization"}>{saving === "optimization" ? "Saving…" : "Save optimization settings"}</button>
                </div>
              </form>
              <div className="top-gap stack-page">
                <h3 className="subsection-title">Available backups</h3>
                {data.optimization.recent_backups.length === 0 ? (
                  <div className="helper-text">No weight backups available yet.</div>
                ) : (
                  <>
                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr><th>Use</th><th>Created</th><th>Path</th><th>Size</th><th>SHA256</th></tr>
                        </thead>
                        <tbody>
                          {data.optimization.recent_backups.map((backup) => (
                            <tr key={backup.path}>
                              <td>
                                <input
                                  type="radio"
                                  name="selected_backup"
                                  checked={selectedBackupPath === backup.path}
                                  onChange={() => setSelectedBackupPath(backup.path)}
                                />
                              </td>
                              <td>{backup.created_at}</td>
                              <td>{backup.path}</td>
                              <td>{backup.fingerprint.size_bytes ?? "—"}</td>
                              <td>{backup.fingerprint.sha256 ?? "—"}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <div className="cluster">
                      <button
                        className="button-secondary"
                        type="button"
                        disabled={saving === "optimization-rollback" || !selectedBackupPath}
                        onClick={() => void rollbackOptimizationWeights()}
                      >
                        {saving === "optimization-rollback" ? "Rolling back…" : "Restore selected backup"}
                      </button>
                    </div>
                    <div className="helper-text">If no backup is selected, the latest known backup is used automatically.</div>
                  </>
                )}
              </div>
            </Card>

            <Card>
              <SectionTitle kicker="Summary engine" title="LLM-backed news summarization" subtitle="Choose news_digest for the fallback headline digest, openai_api for OpenAI narratives, or pi_agent to run your Pi CLI locally. The form exposes the `pi` command, working directory, and optional HTTP bridge settings so the pipeline can treat a vanilla Pi tool just like any other LLM provider." />
              <form className="stack-form" onSubmit={saveSummarySettings}>
                <div className="form-grid">
                  <label className="form-field"><span>Backend</span><select name="backend" defaultValue={settingMap.summary_backend ?? "news_digest"}><option value="news_digest">news_digest (headline digest only)</option><option value="openai_api">openai_api (OpenAI LLM)</option><option value="pi_agent">pi_agent (local Pi LLM)</option></select></label>
                  <label className="form-field"><span>Model</span><input name="model" defaultValue={settingMap.summary_model ?? ""} placeholder="Leave empty to use the backend defaults" /></label>
                  <label className="form-field"><span>Timeout seconds</span><input name="timeout_seconds" defaultValue={settingMap.summary_timeout_seconds ?? "60"} /></label>
                  <label className="form-field"><span>Max tokens</span><input name="max_tokens" defaultValue={settingMap.summary_max_tokens ?? "220"} /></label>
                  <label className="form-field"><span>pi command</span><input name="pi_command" defaultValue={settingMap.summary_pi_command ?? "pi"} /></label>
                  <label className="form-field"><span>PI_CODING_AGENT_DIR</span><input name="pi_agent_dir" defaultValue={settingMap.summary_pi_agent_dir ?? ""} /></label>
                  <label className="form-field"><span>pi CLI args</span><input name="pi_cli_args" defaultValue={settingMap.summary_pi_cli_args ?? ""} placeholder="--provider openai --model gpt-4o-mini" /></label>
                </div>
                <div className="helper-text">pi_agent now invokes the configured `pi` CLI (command, working directory, and optional arguments) so a vanilla Pi tool can serve as the LLM backend; the native digest remains the safe fallback.</div>
                <label className="form-field">
                  <span>Summary prompt</span>
                  <textarea
                    name="prompt"
                    rows={6}
                    defaultValue={settingMap.summary_prompt ?? ""}
                    placeholder="Describe exactly how the LLM should summarize the news"
                  />
                </label>
                <button className="button" type="submit" disabled={saving === "summary"}>{saving === "summary" ? "Saving…" : "Save summary settings"}</button>
              </form>
            </Card>
          </section>

          <Card>
            <SectionTitle kicker="Internal preflight" title="Current pipeline readiness" />
            <div className="cluster">
              <Badge tone={data.preflight.status === "ok" ? "ok" : data.preflight.status === "warning" ? "warning" : "danger"}>
                {data.preflight.status}
              </Badge>
              <span className="helper-text">Checked {data.preflight.checked_at}</span>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr><th>Check</th><th>Status</th><th>Message</th></tr>
                </thead>
                <tbody>
                  {data.preflight.checks.map((check) => (
                    <tr key={check.name}>
                      <td>{check.name}</td>
                      <td><Badge tone={check.status === "ok" ? "ok" : check.status === "failed" ? "danger" : "warning"}>{check.status}</Badge></td>
                      <td>{check.message}{check.details.length > 0 ? <div className="helper-text">{check.details.join(", ")}</div> : null}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          <Card key={`providers-${dataVersion}`}>
            <SectionTitle kicker="Provider credentials" title="Encrypted credential storage" subtitle="These values are stored encrypted at rest and injected into the prototype subprocess when relevant." />
            <div className="stack-page">
              {data.providers.map((provider) => (
                <form key={provider.provider} className="provider-form" onSubmit={(event) => void saveProvider(event, provider.provider)}>
                  <div className="provider-form-header">
                    <h3 className="subsection-title">{provider.provider}</h3>
                    <button className="button-secondary" type="submit" disabled={saving === provider.provider}>
                      {saving === provider.provider ? "Saving…" : "Save"}
                    </button>
                  </div>
                  <div className="form-grid">
                    <label className="form-field"><span>API key</span><input name="api_key" defaultValue={provider.api_key} /></label>
                    <label className="form-field"><span>API secret</span><input name="api_secret" defaultValue={provider.api_secret} /></label>
                  </div>
                </form>
              ))}
            </div>
          </Card>
        </div>
      ) : null}
    </>
  );
}
