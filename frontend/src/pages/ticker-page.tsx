import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { getJson } from "../api";
import { Badge, Card, EmptyState, ErrorState, LoadingState, PageHeader, SectionTitle } from "../components/ui";
import type { TickerAnalysisPage as TickerAnalysisPageData } from "../types";
import { directionTone, formatDate, normalizeAnalysisJsonForDisplay, recommendationStateTone, tickerTone, tradeOutcomeTone, warningCount } from "../utils";

export function TickerPage() {
  const { ticker } = useParams<{ ticker: string }>();
  const [data, setData] = useState<TickerAnalysisPageData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      if (!ticker) {
        setError("Ticker is missing");
        return;
      }
      try {
        setError(null);
        setData(await getJson<TickerAnalysisPageData>(`/api/tickers/${ticker}`));
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : "Failed to load ticker analysis");
      }
    }
    void load();
  }, [ticker]);

  return (
    <>
      <PageHeader
        kicker="Ticker drill-down"
        title={data ? `${data.ticker} recommendation and outcome analysis` : "Ticker analysis"}
        subtitle="Use this page to inspect trade recommendations for one ticker, the states those recommendations reached after evaluation, and the underlying prototype trade outcomes."
        actions={
          <>
            <Link to="/jobs/history" className="button-secondary">Back to history</Link>
            {data ? <a href={`/api/tickers/${data.ticker}`} className="button-subtle" target="_blank" rel="noreferrer">JSON</a> : null}
          </>
        }
      />
      {error ? <ErrorState message={error} /> : null}
      {!data && !error ? <LoadingState message="Loading ticker analysis…" /> : null}
      {data ? (
        <div className="stack-page">
          <section className="metrics-grid">
            <Card><div className="metric-label">Recommendations</div><div className="metric-value">{data.performance.app_recommendation_count}</div></Card>
            <Card><div className="metric-label">Recommendation states</div><div className="metric-value">{data.performance.win_recommendation_count} / {data.performance.loss_recommendation_count}</div></Card>
            <Card><div className="metric-label">Pending recommendations</div><div className="metric-value">{data.performance.pending_recommendation_count}</div></Card>
            <Card><div className="metric-label">Resolved prototype trades</div><div className="metric-value">{data.performance.resolved_trade_count}</div></Card>
            <Card><div className="metric-label">Prototype wins / losses</div><div className="metric-value">{data.performance.win_count} / {data.performance.loss_count}</div></Card>
            <Card><div className="metric-label">Average confidence</div><div className="metric-value">{data.performance.average_confidence !== null ? `${data.performance.average_confidence}%` : "—"}</div></Card>
          </section>

          <Card>
            <SectionTitle kicker="Interpretation" title="What these stats mean" />
            <ul className="checklist">
              <li>Recommendation counts and recommendation states come from the app database.</li>
              <li>Prototype WIN / LOSS / PENDING trade counts come from <code>{data.performance.prototype_trade_log_path}</code>.</li>
              <li>Running the evaluation workflow updates the prototype trade log first, then the app syncs recommendation states from that log.</li>
              <li>Runs are execution records. Recommendations are the trade-ready outputs and should be the main object you review for actual trade decisions.</li>
            </ul>
          </Card>

          <section className="card-grid">
            <Card>
              <SectionTitle kicker="Recommendation mix" title="App-side distribution" />
              <ul className="list-reset">
                <li className="list-item compact-item"><span>LONG</span><Badge tone="ok">{data.performance.long_recommendation_count}</Badge></li>
                <li className="list-item compact-item"><span>SHORT</span><Badge tone="danger">{data.performance.short_recommendation_count}</Badge></li>
                <li className="list-item compact-item"><span>PENDING</span><Badge tone="warning">{data.performance.pending_recommendation_count}</Badge></li>
                <li className="list-item compact-item"><span>WIN</span><Badge tone="ok">{data.performance.win_recommendation_count}</Badge></li>
                <li className="list-item compact-item"><span>LOSS</span><Badge tone="danger">{data.performance.loss_recommendation_count}</Badge></li>
                <li className="list-item compact-item"><span>Warnings</span><Badge tone={data.performance.warning_recommendation_count > 0 ? "warning" : "ok"}>{data.performance.warning_recommendation_count}</Badge></li>
              </ul>
            </Card>
            <Card>
              <SectionTitle kicker="Prototype outcomes" title="Trade log summary" />
              <ul className="list-reset">
                <li className="list-item compact-item"><span>Trade log available</span><Badge tone={data.performance.prototype_trade_log_available ? "ok" : "danger"}>{data.performance.prototype_trade_log_available ? "yes" : "no"}</Badge></li>
                <li className="list-item compact-item"><span>Total logged trades</span><Badge>{data.performance.prototype_trade_count}</Badge></li>
                <li className="list-item compact-item"><span>Average resolved duration</span><Badge>{data.performance.average_resolved_duration_days !== null ? `${data.performance.average_resolved_duration_days}d` : "—"}</Badge></li>
              </ul>
            </Card>
          </section>

          <Card>
            <SectionTitle kicker="Recommendation history" title="App recommendations for this ticker" />
            {data.recommendation_history.length === 0 ? <EmptyState message="No app recommendations stored for this ticker yet." /> : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Created</th>
                      <th>Recommendation</th>
                      <th>Run</th>
                      <th>Risk plan</th>
                      <th>Warnings</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.recommendation_history.map((item) => (
                      <tr key={item.recommendation_id}>
                        <td>{formatDate(item.created_at)}</td>
                        <td>
                          <div className="cluster">
                            <Badge tone={tickerTone()}>{item.ticker}</Badge>
                            <Badge tone={directionTone(item.direction)}>{item.direction}</Badge>
                            <Badge tone={recommendationStateTone(item.state)}>{item.state}</Badge>
                          </div>
                          <div className="helper-text top-gap-small">{item.confidence}% confidence</div>
                          <div className="helper-text top-gap-small">{item.indicator_summary || "No indicator summary stored."}</div>
                          <div className="helper-text top-gap-small"><Link to={`/recommendations/${item.recommendation_id}`}>Open recommendation</Link></div>
                        </td>
                        <td><Link to={`/runs/${item.run_id}`}>#{item.run_id}</Link> · {item.run_status}</td>
                        <td><div>Entry {item.entry_price}</div><div>Stop {item.stop_loss}</div><div>Take profit {item.take_profit}</div></td>
                        <td><Badge tone={warningCount(item) > 0 ? "warning" : "ok"}>{warningCount(item) > 0 ? `${warningCount(item)} issue(s)` : "No warnings"}</Badge></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          <Card>
            <SectionTitle kicker="Resolved performance" title="Prototype trade log for this ticker" />
            {data.prototype_trades.length === 0 ? <EmptyState message="No prototype trade-log entries were found for this ticker." /> : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Opened</th>
                      <th>Status</th>
                      <th>Direction</th>
                      <th>Plan</th>
                      <th>Close / duration</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.prototype_trades.map((trade) => (
                      <tr key={trade.id}>
                        <td>{formatDate(trade.timestamp)}</td>
                        <td><Badge tone={tradeOutcomeTone(trade.status)}>{trade.status}</Badge></td>
                        <td><Badge tone={directionTone(trade.direction)}>{trade.direction}</Badge>{trade.confidence !== null ? ` · ${trade.confidence}%` : ""}</td>
                        <td><div>Entry {trade.entry_price}</div><div>Stop {trade.stop_loss}</div><div>Take profit {trade.take_profit}</div></td>
                        <td><div>{formatDate(trade.close_timestamp)}</div><div className="helper-text">{trade.duration_days !== null ? `${trade.duration_days.toFixed(2)}d` : "—"}</div></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          <Card>
            <SectionTitle kicker="Raw data" title="Prototype analysis payloads" subtitle="Use these to understand why the algorithm behaved the way it did on this ticker." />
            {data.prototype_trades.length === 0 ? <EmptyState message="No prototype raw payloads are available for this ticker." /> : (
              <div className="stack-page">
                {data.prototype_trades.map((trade) => {
                  const normalizedAnalysisJson = normalizeAnalysisJsonForDisplay(trade.analysis_json);
                  return (
                    <article key={`raw-${trade.id}`} className="recommendation-card">
                      <div className="card-headline">
                        <div>
                          <div className="cluster">
                            <div className="kicker">Trade #{trade.id}</div>
                            <Badge tone={directionTone(trade.direction)}>{trade.direction}</Badge>
                          </div>
                          <h3 className="subsection-title">{trade.status}</h3>
                        </div>
                        <Badge tone={tradeOutcomeTone(trade.status)}>{trade.status}</Badge>
                      </div>
                      <div className="helper-text">Opened {formatDate(trade.timestamp)} · Closed {formatDate(trade.close_timestamp)}</div>
                      {normalizedAnalysisJson ? <pre>{normalizedAnalysisJson}</pre> : <div className="helper-text">No analysis payload stored for this trade.</div>}
                    </article>
                  );
                })}
              </div>
            )}
          </Card>
        </div>
      ) : null}
    </>
  );
}
