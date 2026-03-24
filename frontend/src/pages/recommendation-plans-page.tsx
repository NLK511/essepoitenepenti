import { FormEvent, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { getJson } from "../api";
import { Badge, Card, EmptyState, ErrorState, LoadingState, PageHeader, SectionTitle } from "../components/ui";
import type { RecommendationPlan } from "../types";
import { formatDate } from "../utils";

function buildQuery(searchParams: URLSearchParams): string {
  const query = searchParams.toString();
  return query ? `/api/recommendation-plans?${query}` : "/api/recommendation-plans";
}

function actionTone(action: string): "ok" | "warning" | "neutral" {
  if (action === "long") {
    return "ok";
  }
  if (action === "short") {
    return "warning";
  }
  return "neutral";
}

export function RecommendationPlansPage() {
  const [searchParams, setSearchParams] = useSearchParams({ limit: "100" });
  const [plans, setPlans] = useState<RecommendationPlan[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        setError(null);
        setPlans(await getJson<RecommendationPlan[]>(buildQuery(searchParams)));
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : "Failed to load recommendation plans");
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
        title="Recommendation plans"
        subtitle="Browse persisted plan outputs outside run detail. This page helps operators review long, short, and no-action decisions produced by the new orchestration layer."
      />
      {error ? <ErrorState message={error} /> : null}
      <Card>
        <SectionTitle kicker="Filters" title="Find recommendation plans" />
        <form className="form-grid" onSubmit={handleSubmit}>
          <label className="form-field"><span>Ticker</span><input name="ticker" defaultValue={searchParams.get("ticker") ?? ""} placeholder="AAPL" /></label>
          <label className="form-field"><span>Action</span><select name="action" defaultValue={searchParams.get("action") ?? ""}><option value="">All</option><option value="long">long</option><option value="short">short</option><option value="no_action">no_action</option></select></label>
          <label className="form-field"><span>Run id</span><input name="run_id" defaultValue={searchParams.get("run_id") ?? ""} placeholder="145" /></label>
          <label className="form-field"><span>Limit</span><select name="limit" defaultValue={searchParams.get("limit") ?? "100"}><option value="25">25</option><option value="50">50</option><option value="100">100</option><option value="200">200</option></select></label>
          <div className="form-actions"><button className="button" type="submit">Apply</button></div>
        </form>
      </Card>

      <Card className="top-gap">
        <SectionTitle title="Results" subtitle={plans ? `${plans.length} recommendation plan(s)` : undefined} />
        {!plans && !error ? <LoadingState message="Loading recommendation plans…" /> : null}
        {plans && plans.length === 0 ? <EmptyState message="No recommendation plans match the current filters." /> : null}
        {plans ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Computed</th>
                  <th>Ticker</th>
                  <th>Action</th>
                  <th>Confidence</th>
                  <th>Execution</th>
                  <th>Thesis</th>
                  <th>Run</th>
                </tr>
              </thead>
              <tbody>
                {plans.map((plan) => (
                  <tr key={plan.id ?? `${plan.ticker}-${plan.computed_at}`}>
                    <td>{formatDate(plan.computed_at)}</td>
                    <td>
                      <div className="cluster">
                        <Link to={`/tickers/${plan.ticker}`} className="badge badge-info badge-link">{plan.ticker}</Link>
                        <Badge tone={plan.warnings.length > 0 ? "warning" : "ok"}>{plan.status}</Badge>
                      </div>
                      <div className="helper-text top-gap-small">horizon {plan.horizon}</div>
                    </td>
                    <td><Badge tone={actionTone(plan.action)}>{plan.action}</Badge></td>
                    <td>{plan.confidence_percent.toFixed(1)}%</td>
                    <td>
                      <div className="helper-text">entry {plan.entry_price_low ?? "—"}{plan.entry_price_high !== null && plan.entry_price_high !== plan.entry_price_low ? ` – ${plan.entry_price_high}` : ""}</div>
                      <div className="helper-text">stop {plan.stop_loss ?? "—"}</div>
                      <div className="helper-text">take {plan.take_profit ?? "—"}</div>
                    </td>
                    <td>
                      <div>{plan.thesis_summary || "No thesis stored."}</div>
                      {plan.rationale_summary ? <div className="helper-text top-gap-small">{plan.rationale_summary}</div> : null}
                    </td>
                    <td>{plan.run_id ? <Link to={`/runs/${plan.run_id}`}>#{plan.run_id}</Link> : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </Card>
    </>
  );
}
