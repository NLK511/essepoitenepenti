import { FormEvent, useEffect, useMemo, useState } from "react";

import { getJson, postForm } from "../api";
import { Card, ErrorState, LoadingState, PageHeader, SectionTitle } from "../components/ui";
import type { AppSetting, AppPreflightReport, ProviderCredential, SettingsResponse } from "../types";
import { toSettingMap } from "../utils";

interface SettingsViewData {
  settings: AppSetting[];
  providers: ProviderCredential[];
  preflight: AppPreflightReport;
  planGenerationTuning: SettingsResponse["plan_generation_tuning"];
}

export function SettingsPage() {
  const [data, setData] = useState<SettingsViewData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);

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
        planGenerationTuning: settingsResponse.plan_generation_tuning,
        preflight,
      });
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to load settings");
    }
  }

  useEffect(() => {
    void loadData();
  }, []);

  const settingMap = useMemo(() => toSettingMap(data?.settings ?? []), [data]);

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
        pi_cli_args: String(formData.get("pi_cli_args") ?? ""),
        prompt: String(formData.get("prompt") ?? ""),
      });
      setNotice("Summary settings saved");
      await loadData();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Failed to save summary settings");
    } finally {
      setSaving(null);
    }
  }

  async function saveNewsSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    try {
      setSaving("news");
      setError(null);
      setNotice(null);
      await postForm<{ settings: Record<string, string> }>("/api/settings/news", {
        macro_article_limit: String(formData.get("macro_article_limit") ?? "12"),
        industry_article_limit: String(formData.get("industry_article_limit") ?? "12"),
        ticker_article_limit: String(formData.get("ticker_article_limit") ?? "12"),
      });
      setNotice("News settings saved");
      await loadData();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Failed to save news settings");
    } finally {
      setSaving(null);
    }
  }

  async function saveSocialSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    try {
      setSaving("social");
      setError(null);
      setNotice(null);
      await postForm<{ settings: Record<string, string> }>("/api/settings/social", {
        sentiment_enabled: formData.get("sentiment_enabled") ? "true" : "false",
        nitter_enabled: formData.get("nitter_enabled") ? "true" : "false",
        nitter_base_url: String(formData.get("nitter_base_url") ?? settingMap.social_nitter_base_url ?? "http://127.0.0.1:8080"),
        nitter_timeout_seconds: String(formData.get("nitter_timeout_seconds") ?? settingMap.social_nitter_timeout_seconds ?? "6"),
        nitter_max_items_per_query: String(formData.get("nitter_max_items_per_query") ?? settingMap.social_nitter_max_items_per_query ?? "12"),
        nitter_query_window_hours: String(formData.get("nitter_query_window_hours") ?? settingMap.social_nitter_query_window_hours ?? "12"),
        nitter_include_replies: formData.get("nitter_include_replies") ? "true" : "false",
        nitter_enable_ticker: formData.get("nitter_enable_ticker") ? "true" : "false",
        weight_news: settingMap.social_weight_news ?? "1.0",
        weight_social: settingMap.social_weight_social ?? "0.6",
        weight_macro: settingMap.social_weight_macro ?? "0.2",
        weight_industry: settingMap.social_weight_industry ?? "0.3",
        weight_ticker: settingMap.social_weight_ticker ?? "0.5",
        enable_author_weighting: settingMap.social_enable_author_weighting ?? "true",
        enable_engagement_weighting: settingMap.social_enable_engagement_weighting ?? "true",
        enable_duplicate_suppression: settingMap.social_enable_duplicate_suppression ?? "true",
      });
      setNotice("Social settings saved");
      await loadData();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Failed to save social settings");
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
      setNotice(`${provider} credential saved`);
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
        title="Configure providers, summarization, and tuning guardrails."
        subtitle="The retired weight-optimization job is gone. This page now exposes only active system settings and the new plan-generation tuning controls."
      />
      {error ? <ErrorState message={error} /> : null}
      {notice ? <Card><div className="helper-text">{notice}</div></Card> : null}
      {!data && !error ? <LoadingState message="Loading settings…" /> : null}
      {data ? (
        <div className="stack-page">
          <section className="metrics-grid">
            <Card><div className="metric-label">Internal pipeline health</div><div className="metric-value">{data.preflight.status}</div></Card>
            <Card><div className="metric-label">Summary backend</div><div className="metric-value">{settingMap.summary_backend ?? "news_digest"}</div></Card>
            <Card><div className="metric-label">Plan tuning auto mode</div><div className="metric-value">{data.planGenerationTuning.settings.auto_enabled ? "on" : "off"}</div></Card>
            <Card><div className="metric-label">Active tuning config</div><div className="metric-value">{data.planGenerationTuning.settings.active_config_version_id ?? "baseline"}</div></Card>
          </section>

          <section className="card-grid">
            <Card>
              <SectionTitle kicker="Plan generation tuning" title="Active tuning state" subtitle="These are the live settings for the new candidate-based tuning subsystem." />
              <div className="helper-text">Auto mode: {data.planGenerationTuning.settings.auto_enabled ? "enabled" : "disabled"}</div>
              <div className="helper-text">Auto promote: {data.planGenerationTuning.settings.auto_promote_enabled ? "enabled" : "disabled"}</div>
              <div className="helper-text">Minimum actionable resolved records: {data.planGenerationTuning.settings.min_actionable_resolved}</div>
              <div className="helper-text">Minimum validation resolved records: {data.planGenerationTuning.settings.min_validation_resolved}</div>
              <pre className="code-block top-gap-small">{JSON.stringify(data.planGenerationTuning.active_config, null, 2)}</pre>
            </Card>

            <Card>
              <SectionTitle kicker="Summary engine" title="LLM-backed news summarization" subtitle="Choose the backend and local Pi CLI settings used for summaries." />
              <form className="stack-form" onSubmit={(event) => void saveSummarySettings(event)}>
                <div className="form-grid">
                  <label className="form-field"><span>Backend</span><select name="backend" defaultValue={settingMap.summary_backend ?? "news_digest"}><option value="news_digest">news_digest</option><option value="openai_api">openai_api</option><option value="pi_agent">pi_agent</option></select></label>
                  <label className="form-field"><span>Model</span><input name="model" defaultValue={settingMap.summary_model ?? ""} /></label>
                  <label className="form-field"><span>Timeout seconds</span><input name="timeout_seconds" defaultValue={settingMap.summary_timeout_seconds ?? "60"} /></label>
                  <label className="form-field"><span>Max tokens</span><input name="max_tokens" defaultValue={settingMap.summary_max_tokens ?? "220"} /></label>
                  <label className="form-field"><span>pi command</span><input name="pi_command" defaultValue={settingMap.summary_pi_command ?? "pi"} /></label>
                  <label className="form-field"><span>PI_CODING_AGENT_DIR</span><input name="pi_agent_dir" defaultValue={settingMap.summary_pi_agent_dir ?? ""} /></label>
                  <label className="form-field"><span>pi CLI args</span><input name="pi_cli_args" defaultValue={settingMap.summary_pi_cli_args ?? ""} /></label>
                </div>
                <label className="form-field"><span>Summary prompt</span><textarea name="prompt" rows={6} defaultValue={settingMap.summary_prompt ?? ""} /></label>
                <div className="cluster"><button className="button" type="submit" disabled={saving === "summary"}>{saving === "summary" ? "Saving…" : "Save summary settings"}</button></div>
              </form>
            </Card>

            <Card>
              <SectionTitle kicker="News ingestion" title="News fetch limits" subtitle="Adjust article limits for macro, industry, and ticker summarization paths." />
              <form className="stack-form" onSubmit={(event) => void saveNewsSettings(event)}>
                <div className="form-grid">
                  <label className="form-field"><span>Macro article limit</span><input name="macro_article_limit" defaultValue={settingMap.news_macro_article_limit ?? "12"} /></label>
                  <label className="form-field"><span>Industry article limit</span><input name="industry_article_limit" defaultValue={settingMap.news_industry_article_limit ?? "12"} /></label>
                  <label className="form-field"><span>Ticker article limit</span><input name="ticker_article_limit" defaultValue={settingMap.news_ticker_article_limit ?? "12"} /></label>
                </div>
                <div className="cluster"><button className="button" type="submit" disabled={saving === "news"}>{saving === "news" ? "Saving…" : "Save news settings"}</button></div>
              </form>
            </Card>

            <Card>
              <SectionTitle kicker="Social ingestion" title="Social signal settings" subtitle="Control Nitter and social-signal toggles used by the signal layer." />
              <form className="stack-form" onSubmit={(event) => void saveSocialSettings(event)}>
                <div className="form-grid">
                  <label className="form-field"><span><input type="checkbox" name="sentiment_enabled" defaultChecked={(settingMap.social_sentiment_enabled ?? "false") === "true"} /> Sentiment enabled</span></label>
                  <label className="form-field"><span><input type="checkbox" name="nitter_enabled" defaultChecked={(settingMap.social_nitter_enabled ?? "false") === "true"} /> Nitter enabled</span></label>
                  <label className="form-field"><span><input type="checkbox" name="nitter_include_replies" defaultChecked={(settingMap.social_nitter_include_replies ?? "false") === "true"} /> Include replies</span></label>
                  <label className="form-field"><span><input type="checkbox" name="nitter_enable_ticker" defaultChecked={(settingMap.social_nitter_enable_ticker ?? "false") === "true"} /> Enable ticker queries</span></label>
                  <label className="form-field"><span>Base URL</span><input name="nitter_base_url" defaultValue={settingMap.social_nitter_base_url ?? "http://127.0.0.1:8080"} /></label>
                  <label className="form-field"><span>Timeout seconds</span><input name="nitter_timeout_seconds" defaultValue={settingMap.social_nitter_timeout_seconds ?? "6"} /></label>
                  <label className="form-field"><span>Max items per query</span><input name="nitter_max_items_per_query" defaultValue={settingMap.social_nitter_max_items_per_query ?? "12"} /></label>
                  <label className="form-field"><span>Query window hours</span><input name="nitter_query_window_hours" defaultValue={settingMap.social_nitter_query_window_hours ?? "12"} /></label>
                </div>
                <div className="cluster"><button className="button" type="submit" disabled={saving === "social"}>{saving === "social" ? "Saving…" : "Save social settings"}</button></div>
              </form>
            </Card>
          </section>

          <section className="card-grid">
            {data.providers.map((provider) => (
              <Card key={provider.provider}>
                <SectionTitle kicker="Provider credential" title={provider.provider} subtitle="Credentials are stored server-side and redelivered through the existing settings API." />
                <form className="stack-form" onSubmit={(event) => void saveProvider(event, provider.provider)}>
                  <label className="form-field"><span>API key</span><input name="api_key" defaultValue={provider.api_key} /></label>
                  <label className="form-field"><span>API secret</span><input name="api_secret" defaultValue={provider.api_secret} /></label>
                  <div className="cluster"><button className="button" type="submit" disabled={saving === provider.provider}>{saving === provider.provider ? "Saving…" : `Save ${provider.provider}`}</button></div>
                </form>
              </Card>
            ))}
          </section>
        </div>
      ) : null}
    </>
  );
}
