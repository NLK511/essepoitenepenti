import { FormEvent, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { getJson } from "../api";
import { Badge, Card, EmptyState, ErrorState, LoadingState, PageHeader, SectionTitle } from "../components/ui";
import type { TickerSignalSnapshot } from "../types";
import { formatDate } from "../utils";

function buildQuery(searchParams: URLSearchParams): string {
  const query = searchParams.toString();
  return query ? `/api/context/ticker-signals?${query}` : "/api/context/ticker-signals";
}

function directionTone(direction: string): "ok" | "warning" | "neutral" {
  if (direction === "long") {
    return "ok";
  }
  if (direction === "short") {
    return "warning";
  }
  return "neutral";
}

function biasTone(value: string): "ok" | "warning" | "neutral" {
  if (value === "tailwind") {
    return "ok";
  }
  if (value === "headwind") {
    return "warning";
  }
  return "neutral";
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

export function TickerSignalsPage() {
  const [searchParams, setSearchParams] = useSearchParams({ limit: "100" });
  const [signals, setSignals] = useState<TickerSignalSnapshot[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        setError(null);
        setSignals(await getJson<TickerSignalSnapshot[]>(buildQuery(searchParams)));
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : "Failed to load ticker signals");
      }
    }
    void load();
  }, [searchParams]);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    const next = new URLSearchParams();
    for (const [key, value] of formData.entries()) {
      const normalized = String(value).trim();
      if (normalized) {
        next.set(key, normalized);
      }
    }
    if (!next.has("limit")) {
      next.set("limit", "100");
    }
    setSearchParams(next);
  }

  return (
    <>
      <PageHeader
        kicker="Redesign browse"
        title="Ticker signals"
        subtitle="Browse cheap-scan and deep-analysis signal snapshots outside the run detail page. Use this view to inspect shortlist inputs, directional bias, and signal quality across runs."
      />
      {error ? <ErrorState message={error} /> : null}
      <Card>
        <SectionTitle kicker="Filters" title="Find signal snapshots" />
        <form className="form-grid" onSubmit={handleSubmit}>
          <label className="form-field"><span>Ticker</span><input name="ticker" defaultValue={searchParams.get("ticker") ?? ""} placeholder="AAPL" /></label>
          <label className="form-field"><span>Run id</span><input name="run_id" defaultValue={searchParams.get("run_id") ?? ""} placeholder="145" /></label>
          <label className="form-field"><span>Limit</span><select name="limit" defaultValue={searchParams.get("limit") ?? "100"}><option value="25">25</option><option value="50">50</option><option value="100">100</option><option value="200">200</option></select></label>
          <div className="form-actions"><button className="button" type="submit">Apply</button></div>
        </form>
      </Card>

      <Card className="top-gap">
        <SectionTitle title="Results" subtitle={signals ? `${signals.length} ticker signal snapshot(s)` : undefined} />
        {!signals && !error ? <LoadingState message="Loading ticker signals…" /> : null}
        {signals && signals.length === 0 ? <EmptyState message="No ticker signals match the current filters." /> : null}
        {signals ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Computed</th>
                  <th>Ticker</th>
                  <th>Mode</th>
                  <th>Direction</th>
                  <th>Confidence</th>
                  <th>Attention</th>
                  <th>Shortlist lane</th>
                  <th>Transmission</th>
                  <th>Components</th>
                  <th>Run</th>
                </tr>
              </thead>
              <tbody>
                {signals.map((signal) => {
                  const mode = typeof signal.diagnostics.mode === "string" ? signal.diagnostics.mode : "unknown";
                  const components = asRecord(signal.diagnostics.cheap_scan_component_scores);
                  const shortlisted = signal.diagnostics.shortlisted === true;
                  const shortlistRank = typeof signal.diagnostics.shortlist_rank === "number" ? signal.diagnostics.shortlist_rank : null;
                  const selectionLane = typeof signal.diagnostics.selection_lane === "string" ? signal.diagnostics.selection_lane : null;
                  const shortlistReasons = Array.isArray(signal.diagnostics.shortlist_reasons)
                    ? signal.diagnostics.shortlist_reasons.filter((value): value is string => typeof value === "string")
                    : [];
                  const transmissionBias = typeof signal.diagnostics.transmission_bias === "string" ? signal.diagnostics.transmission_bias : "unknown";
                  const transmissionTags = Array.isArray(signal.diagnostics.transmission_tags)
                    ? signal.diagnostics.transmission_tags.filter((value): value is string => typeof value === "string")
                    : [];
                  const primaryDrivers = Array.isArray(signal.diagnostics.primary_drivers)
                    ? signal.diagnostics.primary_drivers.filter((value): value is string => typeof value === "string")
                    : [];
                  const conflictFlags = Array.isArray(signal.diagnostics.conflict_flags)
                    ? signal.diagnostics.conflict_flags.filter((value): value is string => typeof value === "string")
                    : [];
                  const expectedWindow = typeof signal.diagnostics.expected_transmission_window === "string"
                    ? signal.diagnostics.expected_transmission_window
                    : "unknown";
                  const transmissionAlignment = typeof signal.diagnostics.transmission_alignment_score === "number"
                    ? signal.diagnostics.transmission_alignment_score
                    : null;
                  const catalystProxyScore = typeof signal.diagnostics.catalyst_proxy_score === "number"
                    ? signal.diagnostics.catalyst_proxy_score
                    : null;
                  return (
                    <tr key={signal.id ?? `${signal.ticker}-${signal.computed_at}`}>
                      <td>{formatDate(signal.computed_at)}</td>
                      <td>
                        <div className="cluster">
                          <Link to={`/tickers/${signal.ticker}`} className="badge badge-info badge-link">{signal.ticker}</Link>
                          <Badge tone={signal.warnings.length > 0 ? "warning" : "ok"}>{signal.status}</Badge>
                        </div>
                        {signal.warnings.length > 0 ? <div className="helper-text top-gap-small">{signal.warnings.join(" · ")}</div> : null}
                      </td>
                      <td>
                        <Badge tone={mode === "deep_analysis" ? "info" : "neutral"}>{mode}</Badge>
                        <div className="helper-text top-gap-small">{signal.horizon}</div>
                      </td>
                      <td><Badge tone={directionTone(signal.direction)}>{signal.direction}</Badge></td>
                      <td>{signal.confidence_percent.toFixed(1)}%</td>
                      <td>{signal.attention_score.toFixed(1)}</td>
                      <td>
                        <Badge tone={shortlisted ? "info" : "neutral"}>{shortlisted ? `shortlisted${shortlistRank !== null ? ` #${shortlistRank}` : ""}` : "not shortlisted"}</Badge>
                        <div className="helper-text top-gap-small">lane {selectionLane ?? "—"}</div>
                        <div className="helper-text">{shortlistReasons.length > 0 ? shortlistReasons.join(" · ") : "eligible"}</div>
                        <div className="helper-text">catalyst proxy {catalystProxyScore !== null ? catalystProxyScore.toFixed(1) : "—"}</div>
                      </td>
                      <td>
                        <Badge tone={biasTone(transmissionBias)}>{transmissionBias}</Badge>
                        <div className="helper-text top-gap-small">alignment {transmissionAlignment !== null ? `${transmissionAlignment.toFixed(1)}%` : "—"}</div>
                        <div className="helper-text">window {expectedWindow}</div>
                        <div className="helper-text">drivers {primaryDrivers.length > 0 ? primaryDrivers.join(" · ") : "none"}</div>
                        <div className="helper-text">conflicts {conflictFlags.length > 0 ? conflictFlags.join(" · ") : "none"}</div>
                        <div className="helper-text">tags {transmissionTags.length > 0 ? transmissionTags.join(" · ") : "none"}</div>
                      </td>
                      <td>
                        <div className="helper-text">trend {typeof components?.trend_score === "number" ? components.trend_score.toFixed(0) : "—"}</div>
                        <div className="helper-text">momentum {typeof components?.momentum_score === "number" ? components.momentum_score.toFixed(0) : "—"}</div>
                        <div className="helper-text">breakout {typeof components?.breakout_score === "number" ? components.breakout_score.toFixed(0) : "—"}</div>
                      </td>
                      <td>{signal.run_id ? <Link to={`/runs/${signal.run_id}`}>#{signal.run_id}</Link> : "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : null}
      </Card>
    </>
  );
}
