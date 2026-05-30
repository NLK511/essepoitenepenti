import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { getJson } from "../api";
import { Badge, Card, DisclosureCard, EmptyState, ErrorState, LoadingState, PageHeader, SectionTitle, StatCard } from "../components/ui";

type DataQualityAuditItem = {
  ticker: string;
  watchlists: string[];
  bar_count: number;
  latest_bar_at: string | null;
  news_count: number;
  latest_news_at: string | null;
  broker_reject_count: number;
  latest_broker_reject_at: string | null;
  latest_broker_reject_message: string;
  issues: string[];
};

type DataQualityAuditResponse = {
  generated_at: string;
  ticker_count: number;
  issue_ticker_count: number;
  issue_counts: Record<string, number>;
  items: DataQualityAuditItem[];
};

function formatDate(value: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
}

function issueLabel(issue: string): string {
  return issue.replace(/_/g, " ");
}

function issueTone(issue: string): "danger" | "warning" | "neutral" {
  if (issue === "broker_rejected" || issue === "no_bars") return "danger";
  if (issue.startsWith("stale") || issue === "no_news") return "warning";
  return "neutral";
}

function issueCount(payload: DataQualityAuditResponse | null, issues: string[]): number {
  if (!payload) return 0;
  return issues.reduce((total, issue) => total + (payload.issue_counts[issue] ?? 0), 0);
}

export function DataQualityPage() {
  const [payload, setPayload] = useState<DataQualityAuditResponse | null>(null);
  const [ticker, setTicker] = useState("");
  const [staleAfterDays, setStaleAfterDays] = useState("14");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const query = useMemo(() => {
    const params = new URLSearchParams();
    if (ticker.trim()) params.set("ticker", ticker.trim().toUpperCase());
    params.set("stale_after_days", staleAfterDays || "14");
    params.set("limit", "300");
    return params.toString();
  }, [ticker, staleAfterDays]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getJson<DataQualityAuditResponse>(`/api/data-quality/audit?${query}`)
      .then((next) => {
        if (!cancelled) setPayload(next);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [query]);

  const blockingIssueCount = issueCount(payload, ["broker_rejected", "no_bars"]);
  const degradedIssueCount = issueCount(payload, ["no_news", "stale_bars", "stale_news", "stale_coverage"]);

  return (
    <div className="page-stack">
      <PageHeader
        kicker="Input authority"
        title="Data quality"
        actions={<Link to="/context" className="button-subtle">◔ Context review</Link>}
      />

      <Card>
        <SectionTitle
          kicker="Input trust"
          title="Are provider or ticker issues invalidating results?"
          subtitle="Find repeated no-bars, no-news, stale-coverage, and broker-reject ticker issues. Use Context review for macro/industry backdrop freshness."
        />
        <div className="form-grid compact top-gap-small">
          <label>
            <span>Ticker filter</span>
            <input value={ticker} onChange={(event) => setTicker(event.target.value)} placeholder="Optional, e.g. AAPL" />
          </label>
          <label>
            <span>Stale after days</span>
            <input type="number" min="1" max="365" value={staleAfterDays} onChange={(event) => setStaleAfterDays(event.target.value)} />
          </label>
        </div>
      </Card>

      {error && <ErrorState message={error} />}
      {loading && <LoadingState message="Loading data-quality audit…" />}

      {!loading && payload && (
        <>
          <section className="metrics-grid">
            <StatCard label="Input status" value={blockingIssueCount > 0 ? "blocking" : payload.issue_ticker_count > 0 ? "degraded" : "clear"} helper={blockingIssueCount > 0 ? "No-bars or broker rejects present" : payload.issue_ticker_count > 0 ? "Non-blocking input issues present" : "No persisted audit issues found"} />
            <StatCard label="Tickers checked" value={payload.ticker_count} helper="Ticker universe audited" />
            <StatCard label="Tickers with issues" value={payload.issue_ticker_count} helper="Affected ticker count" />
            <StatCard label="Blocking issues" value={blockingIssueCount} helper="Broker rejects or no-bars" />
            <StatCard label="Degraded issues" value={degradedIssueCount} helper="No-news or stale coverage" />
          </section>

          <DisclosureCard kicker="Issue counts" title="Issue-type breakdown" subtitle="Supporting counts by raw audit issue type.">
            <section className="metrics-grid top-gap-small">
              {Object.entries(payload.issue_counts).map(([issue, count]) => (
                <Card key={issue}><div className="metric-label">{issueLabel(issue)}</div><div className="metric-value">{count}</div></Card>
              ))}
            </section>
          </DisclosureCard>

          <Card>
            <SectionTitle kicker="Affected tickers" title="Ticker-level audit results" subtitle="Prioritized list of tickers whose missing, stale, or rejected inputs may distort scans and evaluation." />
            {payload.items.length === 0 ? (
              <EmptyState message="No data-quality issues found. The selected ticker set has recent bars/news and no broker rejects in the persisted audit sources." />
            ) : (
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Ticker</th>
                      <th>Issues</th>
                      <th>Bars</th>
                      <th>Latest bar</th>
                      <th>News</th>
                      <th>Latest news</th>
                      <th>Broker rejects</th>
                      <th>Watchlists</th>
                    </tr>
                  </thead>
                  <tbody>
                    {payload.items.map((item) => (
                      <tr key={item.ticker}>
                        <td><strong>{item.ticker}</strong></td>
                        <td className="chip-list">{item.issues.map((issue) => <Badge key={issue} tone={issueTone(issue)}>{issueLabel(issue)}</Badge>)}</td>
                        <td>{item.bar_count}</td>
                        <td>{formatDate(item.latest_bar_at)}</td>
                        <td>{item.news_count}</td>
                        <td>{formatDate(item.latest_news_at)}</td>
                        <td title={item.latest_broker_reject_message}>{item.broker_reject_count}</td>
                        <td>{item.watchlists.join(", ") || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
