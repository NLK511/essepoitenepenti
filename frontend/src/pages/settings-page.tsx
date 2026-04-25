import { FormEvent, useEffect, useMemo, useState } from "react";

import { getJson, postForm } from "../api";
import { Card, ErrorState, HelpHint, LoadingState, PageHeader, SectionTitle, StatCard } from "../components/ui";
import type { AppSetting, AppPreflightReport, BrokerOrderExecution, EvaluationRealismState, ProviderCredential, SettingsResponse } from "../types";
import { toSettingMap } from "../utils";

interface SettingsViewData {
  settings: AppSetting[];
  providers: ProviderCredential[];
  brokerOrders: BrokerOrderExecution[];
  preflight: AppPreflightReport;
  evaluationRealism: EvaluationRealismState;
  orderExecution: SettingsResponse["order_execution"];
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
      const [settingsResponse, preflight, brokerOrders] = await Promise.all([
        getJson<SettingsResponse>("/api/settings"),
        getJson<AppPreflightReport>("/api/health/preflight"),
        getJson<BrokerOrderExecution[]>("/api/broker-orders?limit=12"),
      ]);
      setData({
        settings: settingsResponse.settings,
        providers: settingsResponse.providers,
        brokerOrders,
        evaluationRealism: settingsResponse.evaluation_realism,
        orderExecution: settingsResponse.order_execution,
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
      setNotice("Summarization settings saved");
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
      setNotice("News ingestion settings saved");
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
      setNotice("Social ingestion settings saved");
      await loadData();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Failed to save social settings");
    } finally {
      setSaving(null);
    }
  }

  async function savePlanGenerationTuningSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    try {
      setSaving("plan-generation-tuning");
      setError(null);
      setNotice(null);
      await postForm<{ plan_generation_tuning: SettingsResponse["plan_generation_tuning"]["settings"] }>("/api/settings/plan-generation-tuning", {
        auto_enabled: formData.get("auto_enabled") ? "true" : "false",
        auto_promote_enabled: formData.get("auto_promote_enabled") ? "true" : "false",
        min_actionable_resolved: String(formData.get("min_actionable_resolved") ?? data?.planGenerationTuning.settings.min_actionable_resolved ?? "20"),
        min_validation_resolved: String(formData.get("min_validation_resolved") ?? data?.planGenerationTuning.settings.min_validation_resolved ?? "8"),
      });
      setNotice("Advanced tuning settings saved");
      await loadData();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Failed to save plan generation tuning settings");
    } finally {
      setSaving(null);
    }
  }

  async function saveEvaluationRealismSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    try {
      setSaving("evaluation-realism");
      setError(null);
      setNotice(null);
      await postForm<{ evaluation_realism: EvaluationRealismState }>("/api/settings/evaluation-realism", {
        stop_buffer_pct: String(formData.get("stop_buffer_pct") ?? data?.evaluationRealism.stop_buffer_pct ?? "0.05"),
        take_profit_buffer_pct: String(formData.get("take_profit_buffer_pct") ?? data?.evaluationRealism.take_profit_buffer_pct ?? "0.05"),
        friction_pct: String(formData.get("friction_pct") ?? data?.evaluationRealism.friction_pct ?? "0.1"),
      });
      setNotice("Evaluation realism settings saved");
      await loadData();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Failed to save evaluation realism settings");
    } finally {
      setSaving(null);
    }
  }

  async function saveOrderExecutionSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    try {
      setSaving("order-execution");
      setError(null);
      setNotice(null);
      await postForm<{ order_execution: SettingsResponse["order_execution"] }>("/api/settings/order-execution", {
        enabled: formData.get("enabled") ? "true" : "false",
        broker: String(formData.get("broker") ?? data?.orderExecution.broker ?? "alpaca"),
        account_mode: String(formData.get("account_mode") ?? data?.orderExecution.account_mode ?? "paper"),
        notional_per_plan: String(formData.get("notional_per_plan") ?? data?.orderExecution.notional_per_plan ?? "1000"),
      });
      setNotice("Order execution settings saved");
      await loadData();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Failed to save order execution settings");
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
        kicker="Reference"
        title="Configure the app without digging into internals."
        actions={<HelpHint tooltip="Settings is split into system setup, data ingestion, and advanced research controls." to="/docs?doc=operator-page-field-guide" />}
      />
      {error ? <ErrorState message={error} /> : null}
      {notice ? <Card><div className="helper-text">{notice}</div></Card> : null}
      {!data && !error ? <LoadingState message="Loading settings…" /> : null}
      {data ? (
        <div className="stack-page">
          <section className="metrics-grid">
            <StatCard label="Pipeline health" value={data.preflight.status} helper="Current preflight status" />
            <StatCard label="Summarization" value={settingMap.summary_backend ?? "news_digest"} helper="Active summary backend" />
            <StatCard label="Advanced tuning automation" value={data.planGenerationTuning.settings.auto_enabled ? "on" : "off"} helper="Stored readiness flag for plan tuning" />
            <StatCard label="Live tuning profile" value={data.planGenerationTuning.settings.active_config_version_id ?? "baseline"} helper="Current plan-generation config" />
          </section>

          <section className="card-grid">
            <Card>
              <SectionTitle kicker="Summarization" title="Summary engine" subtitle="System and providers: choose the backend and local Pi CLI settings used for summaries before touching advanced controls." actions={<HelpHint tooltip="Summarization controls which backend and prompt shape context summaries." to="/docs?doc=operator-page-field-guide" />} />
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
                <div className="cluster"><button className="button" type="submit" disabled={saving === "summary"}>{saving === "summary" ? "Saving…" : "Save summarization settings"}</button></div>
              </form>
            </Card>

            {data.providers.map((provider) => (
              <Card key={provider.provider}>
                <SectionTitle kicker="Provider credential" title={provider.provider} subtitle="API secrets are write-only. The UI never rehydrates them." />
                <form className="stack-form" onSubmit={(event) => void saveProvider(event, provider.provider)}>
                  <label className="form-field"><span>API key</span><input name="api_key" defaultValue={provider.api_key} /></label>
                  <label className="form-field"><span>API secret</span><input name="api_secret" type="password" autoComplete="new-password" placeholder="Enter a new secret to create or rotate the credential" defaultValue="" /></label>
                  <div className="cluster"><button className="button" type="submit" disabled={saving === provider.provider}>{saving === provider.provider ? "Saving…" : `Save ${provider.provider}`}</button></div>
                </form>
              </Card>
            ))}
          </section>

          <section className="card-grid">
            <Card>
              <SectionTitle kicker="Execution" title="Alpaca paper order execution" subtitle="Toggle automated paper trading and control the fixed per-plan notional cap." actions={<HelpHint tooltip="When enabled, actionable plans are converted into Alpaca paper bracket orders with the plan entry, stop loss, and take profit levels." to="/docs?doc=alpaca-paper-order-execution-spec" />} />
              <form className="stack-form" onSubmit={(event) => void saveOrderExecutionSettings(event)}>
                <div className="form-grid">
                  <label className="form-field"><span><input type="checkbox" name="enabled" defaultChecked={data.orderExecution.enabled} /> Order execution enabled</span></label>
                  <label className="form-field"><span>Broker</span><input name="broker" defaultValue={data.orderExecution.broker} /></label>
                  <label className="form-field"><span>Account mode</span><input name="account_mode" defaultValue={data.orderExecution.account_mode} /></label>
                  <label className="form-field"><span>Notional per plan</span><input name="notional_per_plan" type="number" min="1" step="1" defaultValue={String(data.orderExecution.notional_per_plan)} /></label>
                </div>
                <div className="helper-text">Actionable long/short plans are submitted as Alpaca paper bracket orders when this toggle is enabled.</div>
                <div className="cluster"><button className="button" type="submit" disabled={saving === "order-execution"}>{saving === "order-execution" ? "Saving…" : "Save order execution settings"}</button></div>
              </form>
            </Card>

            <Card>
              <SectionTitle kicker="Execution audit" title="Recent broker orders" subtitle="Inspect the latest broker submissions, statuses, and per-order quantities." />
              {data.brokerOrders.length === 0 ? (
                <div className="helper-text top-gap-small">No broker orders recorded yet.</div>
              ) : (
                <div className="table-wrap top-gap-small">
                  <table>
                    <thead>
                      <tr>
                        <th>Ticker</th>
                        <th>Action</th>
                        <th>Qty</th>
                        <th>Status</th>
                        <th>Submitted</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.brokerOrders.map((order) => (
                        <tr key={order.id ?? order.client_order_id}>
                          <td>{order.ticker}</td>
                          <td>{order.side.toUpperCase()}</td>
                          <td>{order.quantity}</td>
                          <td>{order.status}</td>
                          <td>{order.submitted_at ? new Date(order.submitted_at).toLocaleString() : "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>
          </section>

          <section className="card-grid">
            <Card>
              <SectionTitle kicker="News ingestion" title="News fetch limits" subtitle="Data ingestion: adjust article limits for macro, industry, and ticker summarization paths before review pages render summaries." actions={<HelpHint tooltip="Article limits cap how much raw source material feeds each summarization path." to="/docs?doc=operator-page-field-guide" />} />
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
              <SectionTitle kicker="Social ingestion" title="Social and Nitter settings" subtitle="Control whether social input participates in the signal layer and how aggressively it is queried." actions={<HelpHint tooltip="Social settings govern whether Nitter-backed social input participates in the signal layer." to="/docs?doc=operator-page-field-guide" />} />
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
            <Card>
              <SectionTitle kicker="Evaluation realism" title="Slippage and friction" subtitle="Control the buffer and fees subtracted during trade evaluation to simulate real-world conditions." actions={<HelpHint tooltip="Realism buffers subtract slippage and fees to produce conservative, trustable backtest results." to="/docs?doc=operator-page-field-guide" />} />
              <form className="stack-form" onSubmit={(event) => void saveEvaluationRealismSettings(event)}>
                <div className="form-grid">
                  <label className="form-field"><span>Stop loss buffer %</span><input name="stop_buffer_pct" type="number" step="0.001" defaultValue={String(data.evaluationRealism.stop_buffer_pct)} /></label>
                  <label className="form-field"><span>Take profit buffer %</span><input name="take_profit_buffer_pct" type="number" step="0.001" defaultValue={String(data.evaluationRealism.take_profit_buffer_pct)} /></label>
                  <label className="form-field"><span>Round-trip friction %</span><input name="friction_pct" type="number" step="0.01" defaultValue={String(data.evaluationRealism.friction_pct)} /></label>
                </div>
                <div className="cluster"><button className="button" type="submit" disabled={saving === "evaluation-realism"}>{saving === "evaluation-realism" ? "Saving…" : "Save realism settings"}</button></div>
              </form>
            </Card>

            <Card>
              <SectionTitle kicker="Advanced research controls" title="Plan generation tuning" subtitle="These controls are for research and tuning workflows, not daily operator review." actions={<HelpHint tooltip="These settings store automation readiness and minimum evidence thresholds for plan-generation tuning." to="/docs?doc=plan-generation-tuning-spec" />} />
              <form className="stack-form" onSubmit={(event) => void savePlanGenerationTuningSettings(event)}>
                <div className="form-grid">
                  <label className="form-field"><span><input type="checkbox" name="auto_enabled" defaultChecked={data.planGenerationTuning.settings.auto_enabled} /> Advanced tuning automation enabled</span></label>
                  <label className="form-field"><span><input type="checkbox" name="auto_promote_enabled" defaultChecked={data.planGenerationTuning.settings.auto_promote_enabled} /> Auto-promote tuned configs</span></label>
                  <label className="form-field"><span>Minimum actionable resolved records</span><input name="min_actionable_resolved" type="number" min="1" defaultValue={String(data.planGenerationTuning.settings.min_actionable_resolved)} /></label>
                  <label className="form-field"><span>Minimum validation resolved records</span><input name="min_validation_resolved" type="number" min="1" defaultValue={String(data.planGenerationTuning.settings.min_validation_resolved)} /></label>
                </div>
                <div className="helper-text">Current live tuning profile: {data.planGenerationTuning.settings.active_config_version_id ?? "baseline"}. Promote or inspect specific configs from the research tuning page.</div>
                <div className="cluster"><button className="button" type="submit" disabled={saving === "plan-generation-tuning"}>{saving === "plan-generation-tuning" ? "Saving…" : "Save advanced tuning settings"}</button></div>
              </form>
              <details className="top-gap-small">
                <summary className="helper-text">Show current live tuning profile</summary>
                <pre className="code-block top-gap-small">{JSON.stringify(data.planGenerationTuning.active_config, null, 2)}</pre>
              </details>
            </Card>
          </section>
        </div>
      ) : null}
    </>
  );
}
