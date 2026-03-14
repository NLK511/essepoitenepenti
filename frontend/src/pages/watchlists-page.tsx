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
        subtitle="Most users first group their core symbols here, then attach those groups to manual or scheduled jobs."
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
              <span>Tickers</span>
              <input name="tickers" type="text" placeholder="AAPL, MSFT, NVDA" required />
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
