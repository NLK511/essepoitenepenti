import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { getJson } from "../api";
import { Badge, Card, EmptyState, ErrorState, LoadingState, PageHeader, SectionTitle, StatCard } from "../components/ui";
import { ScoreBadge, WarningSummary } from "../components/decision-surface";
import type { TickerSignalSnapshot } from "../types";
import { detailLabel, extractDisplayLabels, formatDate } from "../utils";

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

function joinSummary(items: string[], empty = "none"): string {
  return items.length > 0 ? items.join(" · ") : empty;
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

  const summary = useMemo(() => {
    const items = signals ?? [];
    const shortlisted = items.filter((signal) => signal.diagnostics.shortlisted === true).length;
    const deepAnalysis = items.filter((signal) => signal.diagnostics.mode === "deep_analysis").length;
    const tailwind = items.filter((signal) => signal.diagnostics.transmission_bias === "tailwind").length;
    return { total: items.length, shortlisted, deepAnalysis, tailwind };
  }, [signals]);

  return (
    <>
      <PageHeader
        kicker="Recommendation workflow"
        title="Ticker signals"
        subtitle="Use signals to understand the shortlist before reading full recommendation plans. This view emphasizes what was promoted, what was blocked, and which transmission conditions shaped the decision."
      />
      {error ? <ErrorState message={error} /> : null}

      <section className="metrics-grid top-gap">
        <StatCard label="Signals loaded" value={signals?.length ?? "—"} helper="Current result set under the active filters" />
        <StatCard label="Shortlisted" value={summary.shortlisted} helper="Names promoted into deeper review lanes" />
        <StatCard label="Deep analysis" value={summary.deepAnalysis} helper="Signals enriched beyond the cheap scan" />
        <StatCard label="Tailwind context" value={summary.tailwind} helper="Signals currently tagged with context tailwinds" />
      </section>

      <Card className="sticky-toolbar">
        <SectionTitle kicker="Filters" title="Find signal snapshots" subtitle="Filter by ticker or run, then scan the compact cards below to see shortlist outcome and transmission quality at a glance." />
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
          <div className="data-stack top-gap-small">
            {signals.map((signal) => {
              const mode = typeof signal.diagnostics.mode === "string" ? signal.diagnostics.mode : "unknown";
              const components = asRecord(signal.diagnostics.cheap_scan_component_scores);
              const shortlisted = signal.diagnostics.shortlisted === true;
              const shortlistRank = typeof signal.diagnostics.shortlist_rank === "number" ? signal.diagnostics.shortlist_rank : null;
              const selectionLane = typeof signal.diagnostics.selection_lane_label === "string" && signal.diagnostics.selection_lane_label
                ? signal.diagnostics.selection_lane_label
                : typeof signal.diagnostics.selection_lane === "string" ? signal.diagnostics.selection_lane : null;
              const shortlistReasons = extractDisplayLabels(signal.diagnostics, "shortlist_reason_details", "shortlist_reasons");
              const transmissionBias = typeof signal.diagnostics.transmission_bias === "string" ? signal.diagnostics.transmission_bias : "unknown";
              const transmissionBiasLabel = detailLabel(signal.diagnostics.transmission_bias_detail, signal.diagnostics.transmission_bias ?? "unknown", false) ?? "unknown";
              const transmissionTags = extractDisplayLabels(signal.diagnostics, "transmission_tag_details", "transmission_tags");
              const primaryDrivers = extractDisplayLabels(signal.diagnostics, "primary_driver_details", "primary_drivers");
              const conflictFlags = extractDisplayLabels(signal.diagnostics, "conflict_flag_details", "conflict_flags");
              const industryExposureChannels = extractDisplayLabels(signal.diagnostics, "industry_exposure_channel_details", "industry_exposure_channels");
              const tickerExposureChannels = extractDisplayLabels(signal.diagnostics, "ticker_exposure_channel_details", "ticker_exposure_channels");
              const expectedWindow = detailLabel(
                signal.diagnostics.expected_transmission_window_detail,
                typeof signal.diagnostics.expected_transmission_window === "string" ? signal.diagnostics.expected_transmission_window : "unknown",
              ) ?? "unknown";
              const transmissionAlignment = typeof signal.diagnostics.transmission_alignment_score === "number"
                ? signal.diagnostics.transmission_alignment_score
                : null;
              const catalystProxyScore = typeof signal.diagnostics.catalyst_proxy_score === "number"
                ? signal.diagnostics.catalyst_proxy_score
                : null;
              return (
                <article key={signal.id ?? `${signal.ticker}-${signal.computed_at}`} className="data-card">
                  <div className="data-card-header">
                    <div>
                      <div className="cluster">
                        <Link to={`/tickers/${signal.ticker}`} className="badge badge-info badge-link">{signal.ticker}</Link>
                        <Badge tone={signal.warnings.length > 0 ? "warning" : "ok"}>{signal.status}</Badge>
                        <Badge tone={directionTone(signal.direction)}>{signal.direction}</Badge>
                        <Badge tone={mode === "deep_analysis" ? "info" : "neutral"}>{mode}</Badge>
                      </div>
                      <div className="cluster top-gap-small"><ScoreBadge label="Confidence" value={`${signal.confidence_percent.toFixed(1)}%`} tone="info" /><ScoreBadge label="Attention" value={signal.attention_score.toFixed(1)} tone="neutral" /></div>
                      <div className="helper-text">{formatDate(signal.computed_at)} · horizon {signal.horizon} · run {signal.run_id ? `#${signal.run_id}` : "—"} · mode {mode}</div>
                    </div>
                    <div className="data-card-meta">
                      <Badge tone={shortlisted ? "info" : "neutral"}>{shortlisted ? `shortlisted${shortlistRank !== null ? ` #${shortlistRank}` : ""}` : "not shortlisted"}</Badge>
                      <Badge tone={biasTone(transmissionBias)}>{transmissionBiasLabel}</Badge>
                    </div>
                  </div>

                  <div className="data-points">
                    <div className="data-point"><span className="data-point-label">shortlist lane</span><span className="data-point-value">{selectionLane ?? "—"}</span></div>
                    <div className="data-point"><span className="data-point-label">catalyst proxy</span><span className="data-point-value">{catalystProxyScore !== null ? catalystProxyScore.toFixed(1) : "—"}</span></div>
                    <div className="data-point"><span className="data-point-label">alignment</span><span className="data-point-value">{transmissionAlignment !== null ? `${transmissionAlignment.toFixed(1)}%` : "—"}</span></div>
                    <div className="data-point"><span className="data-point-label">window</span><span className="data-point-value">{expectedWindow}</span></div>
                  </div>

                  <div className="helper-text top-gap-small">shortlist {joinSummary(shortlistReasons, "eligible")} · drivers {joinSummary(primaryDrivers)} · industry {joinSummary(industryExposureChannels)} · ticker {joinSummary(tickerExposureChannels)}</div>
                  <div className="helper-text">flags {joinSummary(conflictFlags)} · tags {joinSummary(transmissionTags)} · cheap scan trend {typeof components?.trend_score === "number" ? components.trend_score.toFixed(0) : "—"} / momentum {typeof components?.momentum_score === "number" ? components.momentum_score.toFixed(0) : "—"} / breakout {typeof components?.breakout_score === "number" ? components.breakout_score.toFixed(0) : "—"}</div>
                  <div className="helper-text">selection {selectionLane ?? "—"} · catalyst proxy {catalystProxyScore !== null ? catalystProxyScore.toFixed(1) : "—"} · alignment {transmissionAlignment !== null ? `${transmissionAlignment.toFixed(1)}%` : "—"} · window {expectedWindow}</div>
                  <WarningSummary warnings={signal.warnings} />
                </article>
              );
            })}
          </div>
        ) : null}
      </Card>
    </>
  );
}
