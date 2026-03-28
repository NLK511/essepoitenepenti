import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { getJson } from "../api";
import {
  matchedRelationshipsFromPlan,
  relationshipSummary,
  storedRelationshipEdgesFromPlan,
  TickerRelationshipReadthroughCard,
} from "../components/ticker-relationship-readthrough";
import { Badge, Card, EmptyState, ErrorState, LoadingState, PageHeader, SectionTitle, SegmentedTabs, StatCard } from "../components/ui";
import type { TickerAnalysisPage as TickerAnalysisPageData } from "../types";
import { formatDate } from "../utils";

export function TickerPage() {
  const { ticker } = useParams<{ ticker: string }>();
  const [data, setData] = useState<TickerAnalysisPageData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [section, setSection] = useState<"overview" | "plans">("overview");

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

  const latestPlan = useMemo(() => data?.recommendation_plans[0] ?? null, [data]);
  const latestMatchedTickerRelationships = latestPlan ? matchedRelationshipsFromPlan(latestPlan) : [];
  const latestTickerRelationshipEdges = latestPlan ? storedRelationshipEdgesFromPlan(latestPlan) : [];

  return (
    <>
      <PageHeader
        kicker="Ticker drill-down"
        title={data ? `${data.ticker} review` : "Ticker analysis"}
        subtitle="This page is optimized for one question: should this ticker earn more operator attention? Review plan history, outcome mix, and the latest plan context without wading through redundant run-level detail."
        actions={
          <>
            <Link to="/jobs/recommendation-plans" className="button-secondary">Back to plans</Link>
            {data ? <a href={`/api/tickers/${data.ticker}`} className="button-subtle" target="_blank" rel="noreferrer">JSON</a> : null}
          </>
        }
      />
      {error ? <ErrorState message={error} /> : null}
      {!data && !error ? <LoadingState message="Loading ticker analysis…" /> : null}
      {data ? (
        <div className="stack-page">
          <section className="metrics-grid">
            <StatCard label="Stored plans" value={data.performance.app_plan_count} helper="Recommendation plans recorded for this ticker" />
            <StatCard label="Actionable plans" value={data.performance.actionable_plan_count} helper="Long and short plans only" />
            <StatCard label="Win / loss" value={`${data.performance.win_plan_count} / ${data.performance.loss_plan_count}`} helper="Resolved plan outcomes" />
            <StatCard label="Open plans" value={data.performance.open_plan_count} helper="Plans still awaiting resolution" />
            <StatCard label="Avg confidence" value={data.performance.average_confidence !== null ? `${data.performance.average_confidence}%` : "—"} helper="Mean stored plan confidence" />
          </section>

          <Card>
            <SectionTitle kicker="Navigation" title="Ticker review sections" subtitle="Keep one task visible at a time: overview for the big picture, plans for the full recommendation-plan history." />
            <SegmentedTabs
              value={section}
              onChange={setSection}
              options={[
                { value: "overview", label: "Overview" },
                { value: "plans", label: "Plans" },
              ]}
            />
          </Card>

          {section === "overview" ? (
            <section className="insight-grid">
              <Card>
                <SectionTitle kicker="Interpretation" title="How to read this ticker" />
                <ul className="checklist">
                  <li>Recommendation plans and plan outcomes are the canonical app-side review objects.</li>
                  <li>Use plan mix and recent outcome state to decide whether this ticker deserves repeated operator attention.</li>
                  <li>Prefer run detail only when you need execution provenance that the ticker page does not summarize.</li>
                </ul>
              </Card>
              <Card>
                <SectionTitle kicker="Plan mix" title="Current distribution" />
                <div className="data-points top-gap-small">
                  <div className="data-point"><span className="data-point-label">long</span><span className="data-point-value">{data.performance.long_plan_count}</span></div>
                  <div className="data-point"><span className="data-point-label">short</span><span className="data-point-value">{data.performance.short_plan_count}</span></div>
                  <div className="data-point"><span className="data-point-label">no_action</span><span className="data-point-value">{data.performance.no_action_plan_count}</span></div>
                  <div className="data-point"><span className="data-point-label">watchlist</span><span className="data-point-value">{data.performance.watchlist_plan_count}</span></div>
                  <div className="data-point"><span className="data-point-label">warnings</span><span className="data-point-value">{data.performance.warning_plan_count}</span></div>
                </div>
              </Card>
              <Card>
                <SectionTitle kicker="Latest plan" title="Most recent operator context" />
                {latestPlan ? (
                  <div className="data-stack top-gap-small">
                    <div className="cluster">
                      <Badge tone={latestPlan.action === "long" ? "ok" : latestPlan.action === "short" ? "warning" : "neutral"}>{latestPlan.action}</Badge>
                      <Badge>{latestPlan.horizon}</Badge>
                      <Badge>{typeof latestPlan.signal_breakdown?.setup_family === "string" ? latestPlan.signal_breakdown.setup_family : "setup —"}</Badge>
                    </div>
                    <div className="helper-text">{latestPlan.thesis_summary || latestPlan.rationale_summary || "No thesis summary stored."}</div>
                    <div className="helper-text">Entry {latestPlan.entry_price_low ?? latestPlan.entry_price_high ?? "—"} · Stop {latestPlan.stop_loss ?? "—"} · Take profit {latestPlan.take_profit ?? "—"}</div>
                    <div className="helper-text">Ticker relationships {relationshipSummary(latestPlan ?? {})}</div>
                    <div className="helper-text">Latest outcome {latestPlan.latest_outcome?.outcome ?? "open"}</div>
                  </div>
                ) : (
                  <EmptyState message="No plans stored for this ticker yet." />
                )}
              </Card>
              {latestPlan ? (
                <TickerRelationshipReadthroughCard
                  title="Latest matched ticker relationships"
                  subtitle="Use this as secondary read-through. It should explain why peer, supplier, or customer structure mattered for the latest stored plan."
                  matched={latestMatchedTickerRelationships}
                  storedEdges={latestTickerRelationshipEdges}
                  emptyMessage="No ticker relationship read-through was stored for the latest plan yet."
                />
              ) : null}
            </section>
          ) : null}

          {section === "plans" ? (
            <Card>
              <SectionTitle kicker="Plan history" title="Recommendation plans for this ticker" />
              {data.recommendation_plans.length === 0 ? <EmptyState message="No recommendation plans are stored for this ticker yet." /> : (
                <div className="data-stack top-gap-small">
                  {data.recommendation_plans.map((item) => {
                    const setupFamily = typeof item.signal_breakdown === "object" && item.signal_breakdown !== null && !Array.isArray(item.signal_breakdown) && typeof (item.signal_breakdown as Record<string, unknown>).setup_family === "string"
                      ? (item.signal_breakdown as Record<string, unknown>).setup_family as string
                      : "—";
                    return (
                      <article key={`${item.id}-${item.computed_at}`} className="data-card">
                        <div className="data-card-header">
                          <div>
                            <div className="cluster">
                              <Badge tone={item.action === "long" ? "ok" : item.action === "short" ? "warning" : "neutral"}>{item.action}</Badge>
                              <Badge>{setupFamily}</Badge>
                              <Badge>{item.horizon}</Badge>
                              {item.run_id ? <Link to={`/runs/${item.run_id}`} className="badge badge-info badge-link">run #{item.run_id}</Link> : null}
                            </div>
                            <h3 className="data-card-title top-gap-small">{item.confidence_percent}% confidence</h3>
                            <div className="helper-text">{formatDate(item.computed_at)}</div>
                          </div>
                          <div className="data-card-meta">
                            <Badge tone={item.latest_outcome?.outcome === "win" ? "ok" : item.latest_outcome?.outcome === "loss" ? "danger" : "neutral"}>{item.latest_outcome?.outcome ?? "open"}</Badge>
                            <Badge tone={item.latest_outcome?.status === "resolved" ? "ok" : "warning"}>{item.latest_outcome?.status ?? "pending"}</Badge>
                          </div>
                        </div>
                        <div className="helper-text">{item.thesis_summary || item.rationale_summary || "No thesis summary stored."}</div>
                        <div className="helper-text top-gap-small">ticker relationships {relationshipSummary(item)}</div>
                        <div className="data-points top-gap-small">
                          <div className="data-point"><span className="data-point-label">entry</span><span className="data-point-value">{item.entry_price_low ?? item.entry_price_high ?? "—"}{item.entry_price_high && item.entry_price_low && item.entry_price_high !== item.entry_price_low ? ` to ${item.entry_price_high}` : ""}</span></div>
                          <div className="data-point"><span className="data-point-label">stop</span><span className="data-point-value">{item.stop_loss ?? "—"}</span></div>
                          <div className="data-point"><span className="data-point-label">take profit</span><span className="data-point-value">{item.take_profit ?? "—"}</span></div>
                          <div className="data-point"><span className="data-point-label">outcome note</span><span className="data-point-value">{item.latest_outcome?.notes || (item.warnings.length > 0 ? `${item.warnings.length} warning(s)` : "—")}</span></div>
                        </div>
                      </article>
                    );
                  })}
                </div>
              )}
            </Card>
          ) : null}

        </div>
      ) : null}
    </>
  );
}
