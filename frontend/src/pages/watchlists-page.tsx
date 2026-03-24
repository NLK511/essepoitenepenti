import { FormEvent, useEffect, useState } from "react";

import { getJson, postForm } from "../api";
import { Card, EmptyState, ErrorState, LoadingState, PageHeader, SectionTitle, Badge } from "../components/ui";
import type { Watchlist } from "../types";
import { tickerTone } from "../utils";

export function WatchlistsPage() {
  const [watchlists, setWatchlists] = useState<Watchlist[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function loadWatchlists() {
    try {
      setError(null);
      setWatchlists(await getJson<Watchlist[]>("/api/watchlists"));
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

  return (
    <>
      <PageHeader
        kicker="Setup journey"
        title="Create reusable watchlists before automating jobs."
        subtitle="Watchlists can now store region, exchange, horizon, shorting, and timing preferences so later analysis can be scheduled more efficiently."
      />
      {error ? <ErrorState message={error} /> : null}
      <section className="two-column">
        <Card>
          <SectionTitle kicker="Create" title="New watchlist" />
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
          <SectionTitle kicker="Review" title="Saved watchlists" />
          {!watchlists && !error ? <LoadingState message="Loading watchlists…" /> : null}
          {watchlists && watchlists.length === 0 ? <EmptyState message="No watchlists created yet." /> : null}
          {watchlists ? (
            <ul className="list-reset">
              {watchlists.map((watchlist) => (
                <li key={watchlist.id ?? watchlist.name} className="list-item compact-item">
                  <div>
                    <strong>{watchlist.name}</strong>
                    {watchlist.description ? <div className="helper-text">{watchlist.description}</div> : null}
                    <div className="badge-row">
                      {watchlist.region ? <Badge tone="info">region: {watchlist.region}</Badge> : null}
                      {watchlist.exchange ? <Badge tone="info">exchange: {watchlist.exchange}</Badge> : null}
                      {watchlist.timezone ? <Badge tone="info">tz: {watchlist.timezone}</Badge> : null}
                      <Badge tone="info">horizon: {watchlist.default_horizon}</Badge>
                      <Badge tone={watchlist.allow_shorts ? "warning" : "neutral"}>
                        {watchlist.allow_shorts ? "shorts on" : "shorts off"}
                      </Badge>
                      {watchlist.optimize_evaluation_timing ? <Badge tone="ok">timing optimized</Badge> : null}
                    </div>
                    <div className="badge-row">
                      {watchlist.tickers.map((ticker) => (
                        <Badge key={`${watchlist.name}-${ticker}`} tone={tickerTone()}>{ticker}</Badge>
                      ))}
                    </div>
                  </div>
                  <Badge>{watchlist.tickers.length} ticker(s)</Badge>
                </li>
              ))}
            </ul>
          ) : null}
        </Card>
      </section>
    </>
  );
}
