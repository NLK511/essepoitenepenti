import { FormEvent, useEffect, useState } from "react";

import { getJson, postForm, deleteJson } from "../api";
import { Card, EmptyState, ErrorState, LoadingState, PageHeader, SectionTitle, Badge, StatCard } from "../components/ui";
import type { Watchlist, WatchlistEvaluationPolicy } from "../types";
import { tickerTone } from "../utils";

export function WatchlistsPage() {
  const [watchlists, setWatchlists] = useState<Watchlist[] | null>(null);
  const [policies, setPolicies] = useState<Record<number, WatchlistEvaluationPolicy>>({});
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function loadWatchlists() {
    try {
      setError(null);
      const [watchlistItems, policyItems] = await Promise.all([
        getJson<Watchlist[]>("/api/watchlists"),
        getJson<WatchlistEvaluationPolicy[]>("/api/watchlists/policies"),
      ]);
      setWatchlists(watchlistItems);
      setPolicies(
        Object.fromEntries(
          policyItems
            .filter((policy) => typeof policy.watchlist_id === "number")
            .map((policy) => [policy.watchlist_id as number, policy]),
        ),
      );
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to load watchlists");
    }
  }

  useEffect(() => {
    void loadWatchlists();
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    try {
      setSubmitting(true);
      setError(null);
      await postForm<Watchlist>("/api/watchlists", {
        name: String(formData.get("name") ?? ""),
        description: String(formData.get("description") ?? ""),
        region: String(formData.get("region") ?? ""),
        exchange: String(formData.get("exchange") ?? ""),
        timezone: String(formData.get("timezone") ?? ""),
        default_horizon: String(formData.get("default_horizon") ?? "1w"),
        allow_shorts: formData.get("allow_shorts") ? "true" : "false",
        optimize_evaluation_timing: formData.get("optimize_evaluation_timing") ? "true" : "false",
        tickers: String(formData.get("tickers") ?? ""),
      });
      event.currentTarget.reset();
      await loadWatchlists();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Failed to create watchlist");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDelete(watchlistId: number) {
    if (!window.confirm("Are you sure you want to delete this watchlist? This may fail if it is currently in use by a job.")) {
      return;
    }
    try {
      setSubmitting(true);
      setError(null);
      await deleteJson(`/api/watchlists/${watchlistId}`);
      await loadWatchlists();
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : "Failed to delete watchlist");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <PageHeader
        kicker="Automation"
        title="Watchlists"
        subtitle="Define the universes the app should monitor. Each watchlist carries market metadata, scheduling assumptions, and evaluation policy context so later recommendation runs remain interpretable."
      />
      {error ? <ErrorState message={error} /> : null}
      <section className="metrics-grid top-gap">
        <StatCard label="Watchlists" value={watchlists?.length ?? "—"} helper="Reusable universes currently stored" />
        <StatCard label="Tickers tracked" value={watchlists ? watchlists.reduce((count, item) => count + item.tickers.length, 0) : "—"} helper="Total ticker slots across all watchlists" />
        <StatCard label="Shorts enabled" value={watchlists ? watchlists.filter((item) => item.allow_shorts).length : "—"} helper="Watchlists that allow short recommendations" />
        <StatCard label="Timing optimized" value={watchlists ? watchlists.filter((item) => item.optimize_evaluation_timing).length : "—"} helper="Watchlists using evaluation-timing optimization" />
      </section>
      <section className="two-column top-gap">
        <Card className="sticky-toolbar">
          <SectionTitle kicker="Create" title="New watchlist" subtitle="Keep the metadata practical: only enter region, exchange, and timezone details that actually improve scheduling or review quality." />
          <form className="stack-form" onSubmit={handleSubmit}>
            <label className="form-field">
              <span>Name</span>
              <input name="name" type="text" placeholder="Core Tech" required />
            </label>
            <label className="form-field">
              <span>Description</span>
              <input name="description" type="text" placeholder="US tech swing basket" />
            </label>
            <div className="two-column" style={{ gap: "0.75rem" }}>
              <label className="form-field">
                <span>Region</span>
                <input name="region" type="text" placeholder="US" />
              </label>
              <label className="form-field">
                <span>Exchange</span>
                <input name="exchange" type="text" placeholder="NASDAQ" />
              </label>
            </div>
            <div className="two-column" style={{ gap: "0.75rem" }}>
              <label className="form-field">
                <span>Timezone</span>
                <input name="timezone" type="text" placeholder="America/New_York" />
              </label>
              <label className="form-field">
                <span>Default horizon</span>
                <select name="default_horizon" defaultValue="1w">
                  <option value="1d">1 day</option>
                  <option value="1w">1 week</option>
                  <option value="1m">1 month</option>
                </select>
              </label>
            </div>
            <label className="form-field">
              <span>Tickers</span>
              <input name="tickers" type="text" placeholder="AAPL, MSFT, NVDA" required />
            </label>
            <label className="form-field" style={{ flexDirection: "row", alignItems: "center", gap: "0.5rem" }}>
              <input name="allow_shorts" type="checkbox" defaultChecked />
              <span>Allow short recommendations for this watchlist</span>
            </label>
            <label className="form-field" style={{ flexDirection: "row", alignItems: "center", gap: "0.5rem" }}>
              <input name="optimize_evaluation_timing" type="checkbox" />
              <span>Optimize evaluation timing for the watchlist exchange</span>
            </label>
            <button type="submit" className="button" disabled={submitting}>
              {submitting ? "Creating…" : "Create watchlist"}
            </button>
          </form>
        </Card>
        <Card>
          <SectionTitle kicker="Review" title="Saved watchlists" subtitle="Scan market metadata, policy assumptions, and ticker membership without leaving the page." />
          {!watchlists && !error ? <LoadingState message="Loading watchlists…" /> : null}
          {watchlists && watchlists.length === 0 ? <EmptyState message="No watchlists created yet." /> : null}
          {watchlists ? (
            <div className="data-stack top-gap-small">
              {watchlists.map((watchlist) => {
                const policy = watchlist.id ? policies[watchlist.id] : undefined;
                return (
                  <article key={watchlist.id ?? watchlist.name} className="data-card">
                    <div className="data-card-header">
                      <div>
                        <h3 className="data-card-title">{watchlist.name}</h3>
                        {watchlist.description ? <div className="helper-text">{watchlist.description}</div> : null}
                      </div>
                      <div className="badge-row" style={{ alignItems: "center" }}>
                        <Badge>{watchlist.tickers.length} ticker(s)</Badge>
                        {watchlist.id ? (
                          <button
                            type="button"
                            className="button button-small button-danger"
                            onClick={() => watchlist.id && handleDelete(watchlist.id)}
                            disabled={submitting}
                            title="Delete watchlist"
                            style={{ padding: "2px 8px", fontSize: "0.75rem" }}
                          >
                            Delete
                          </button>
                        ) : null}
                      </div>
                    </div>
                    <div className="data-points">
                      <div className="data-point"><span className="data-point-label">region</span><span className="data-point-value">{watchlist.region || "—"}</span></div>
                      <div className="data-point"><span className="data-point-label">exchange</span><span className="data-point-value">{watchlist.exchange || "—"}</span></div>
                      <div className="data-point"><span className="data-point-label">timezone</span><span className="data-point-value">{watchlist.timezone || "—"}</span></div>
                      <div className="data-point"><span className="data-point-label">default horizon</span><span className="data-point-value">{watchlist.default_horizon}</span></div>
                    </div>
                    <div className="badge-row top-gap-small">
                      <Badge tone={watchlist.allow_shorts ? "warning" : "neutral"}>{watchlist.allow_shorts ? "shorts on" : "shorts off"}</Badge>
                      <Badge tone={watchlist.optimize_evaluation_timing ? "ok" : "neutral"}>{watchlist.optimize_evaluation_timing ? "timing optimized" : "timing standard"}</Badge>
                      {policy ? <Badge tone="info">schedule: {policy.schedule_source}</Badge> : null}
                      {policy ? <Badge tone={policy.primary_cron ? "ok" : "neutral"}>cron: {policy.primary_cron ?? "none"}</Badge> : null}
                      {policy ? <Badge tone="info">strategy: {policy.shortlist_strategy}</Badge> : null}
                    </div>
                    {policy ? (
                      <div className="helper-text top-gap-small">
                        Primary window: {policy.primary_window_label || "—"}
                        {policy.secondary_window_label ? ` · Secondary window: ${policy.secondary_window_label}` : ""}
                      </div>
                    ) : null}
                    {policy && policy.warnings.length > 0 ? (
                      <div className="badge-row top-gap-small">
                        {policy.warnings.map((warning) => (
                          <Badge key={`${watchlist.name}-${warning}`} tone="warning">{warning}</Badge>
                        ))}
                      </div>
                    ) : null}
                    <div className="badge-row top-gap-small">
                      {watchlist.tickers.map((ticker) => (
                        <Badge key={`${watchlist.name}-${ticker}`} tone={tickerTone()}>{ticker}</Badge>
                      ))}
                    </div>
                  </article>
                );
              })}
            </div>
          ) : null}
        </Card>
      </section>
    </>
  );
}
