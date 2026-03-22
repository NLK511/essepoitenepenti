import { useEffect, useState } from "react";

import { getJson, postForm } from "../api";
import { useToast } from "../components/toast";
import { Badge, Card, EmptyState, ErrorState, LoadingState, PageHeader, SectionTitle } from "../components/ui";
import type { Run, SentimentSnapshot, SentimentSnapshotListResponse } from "../types";
import { formatDate, formatDuration, jobTypeLabel } from "../utils";

function snapshotTone(snapshot: SentimentSnapshot): "ok" | "warning" | "danger" | "neutral" {
  if (snapshot.is_expired) {
    return "danger";
  }
  if (snapshot.label === "POSITIVE") {
    return "ok";
  }
  if (snapshot.label === "NEGATIVE") {
    return "danger";
  }
  return "warning";
}

export function SentimentSnapshotsPage() {
  const { showToast } = useToast();
  const [macro, setMacro] = useState<SentimentSnapshot[]>([]);
  const [industry, setIndustry] = useState<SentimentSnapshot[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyAction, setBusyAction] = useState<"macro" | "industry" | null>(null);

  async function load() {
    try {
      setLoading(true);
      setError(null);
      const [macroResponse, industryResponse] = await Promise.all([
        getJson<SentimentSnapshotListResponse>("/api/sentiment-snapshots/macro?limit=6"),
        getJson<SentimentSnapshotListResponse>("/api/sentiment-snapshots/industry?limit=12"),
      ]);
      setMacro(macroResponse.snapshots);
      setIndustry(industryResponse.snapshots);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to load sentiment snapshots");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function enqueueRefresh(scope: "macro" | "industry") {
    try {
      setBusyAction(scope);
      setError(null);
      const run = await postForm<Run>(`/api/sentiment-snapshots/refresh/${scope}`, {});
      showToast({
        message: `${scope === "macro" ? "Macro" : "Industry"} refresh queued as run #${run.id}`,
        tone: "success",
      });
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : `Failed to queue ${scope} refresh`);
    } finally {
      setBusyAction(null);
    }
  }

  const latestMacro = macro[0] ?? null;
  const latestIndustry = industry[0] ?? null;

  return (
    <>
      <PageHeader
        kicker="Snapshot-backed sentiment"
        title="Inspect shared macro and industry sentiment refreshes."
        subtitle="These snapshots are reused across proposal runs so macro and industry context stay consistent, auditable, and cheaper to compute."
        actions={
          <>
            <button type="button" className="button" onClick={() => void enqueueRefresh("macro")} disabled={busyAction !== null}>
              {busyAction === "macro" ? "Queueing macro refresh…" : "Refresh macro"}
            </button>
            <button type="button" className="button-secondary" onClick={() => void enqueueRefresh("industry")} disabled={busyAction !== null}>
              {busyAction === "industry" ? "Queueing industry refresh…" : "Refresh industries"}
            </button>
            <button type="button" className="button-subtle" onClick={() => void load()} disabled={loading}>
              Reload
            </button>
          </>
        }
      />

      {error ? <ErrorState message={error} /> : null}
      {loading ? <LoadingState message="Loading shared sentiment snapshots…" /> : null}

      {!loading ? (
        <div className="stack-page">
          <section className="metrics-grid">
            <Card>
              <div className="metric-label">Latest macro snapshot</div>
              <div className="metric-value">{latestMacro ? latestMacro.label : "—"}</div>
              <div className="helper-text">{latestMacro ? formatDate(latestMacro.computed_at) : "No macro snapshot yet"}</div>
            </Card>
            <Card>
              <div className="metric-label">Macro freshness</div>
              <div className="metric-value">{latestMacro ? (latestMacro.is_expired ? "stale" : "fresh") : "—"}</div>
              <div className="helper-text">{latestMacro?.expires_at ? `Expires ${formatDate(latestMacro.expires_at)}` : "No expiry recorded"}</div>
            </Card>
            <Card>
              <div className="metric-label">Latest industry snapshot</div>
              <div className="metric-value">{latestIndustry ? latestIndustry.subject_label : "—"}</div>
              <div className="helper-text">{latestIndustry ? `${latestIndustry.label} · ${formatDate(latestIndustry.computed_at)}` : "No industry snapshot yet"}</div>
            </Card>
            <Card>
              <div className="metric-label">Tracked industry snapshots</div>
              <div className="metric-value">{industry.length}</div>
              <div className="helper-text">Most recent {industry.length} industry records</div>
            </Card>
          </section>

          <section className="two-column">
            <Card>
              <SectionTitle kicker="Macro" title="Latest shared macro context" />
              {latestMacro ? <SnapshotSummary snapshot={latestMacro} /> : <EmptyState message="No macro snapshots available yet." />}
            </Card>
            <Card>
              <SectionTitle kicker="Industry" title="Latest shared industry context" />
              {latestIndustry ? <SnapshotSummary snapshot={latestIndustry} /> : <EmptyState message="No industry snapshots available yet." />}
            </Card>
          </section>

          <section className="card-grid">
            <Card>
              <SectionTitle kicker="Macro history" title="Recent macro snapshots" />
              {macro.length === 0 ? <EmptyState message="No macro snapshots stored yet." /> : <SnapshotList snapshots={macro} />}
            </Card>
            <Card>
              <SectionTitle kicker="Industry history" title="Recent industry snapshots" />
              {industry.length === 0 ? <EmptyState message="No industry snapshots stored yet." /> : <SnapshotList snapshots={industry} />}
            </Card>
          </section>
        </div>
      ) : null}
    </>
  );
}

function SnapshotList({ snapshots }: { snapshots: SentimentSnapshot[] }) {
  return (
    <ul className="list-reset">
      {snapshots.map((snapshot) => (
        <li key={`${snapshot.scope}-${snapshot.id}`} className="list-item">
          <div className="card-headline">
            <div>
              <div className="cluster">
                <Badge tone="info">{snapshot.subject_label}</Badge>
                <Badge tone={snapshotTone(snapshot)}>{snapshot.label}</Badge>
                <Badge tone={snapshot.is_expired ? "danger" : "ok"}>{snapshot.is_expired ? "expired" : "fresh"}</Badge>
              </div>
              <div className="helper-text">Score {snapshot.score.toFixed(2)} · computed {formatDate(snapshot.computed_at)}</div>
              {snapshot.expires_at ? <div className="helper-text">Expires {formatDate(snapshot.expires_at)}</div> : null}
            </div>
            <Badge tone="neutral">#{snapshot.id}</Badge>
          </div>
        </li>
      ))}
    </ul>
  );
}

function SnapshotSummary({ snapshot }: { snapshot: SentimentSnapshot }) {
  const socialCount = Number(snapshot.coverage.social_count ?? 0);
  const queryCount = Number(snapshot.coverage.query_count ?? 0);
  const trackedTickers = Array.isArray(snapshot.coverage.tracked_tickers) ? snapshot.coverage.tracked_tickers.length : 0;
  return (
    <div className="stack-page">
      <div className="cluster">
        <Badge tone="info">{snapshot.subject_label}</Badge>
        <Badge tone={snapshotTone(snapshot)}>{snapshot.label}</Badge>
        <Badge tone={snapshot.is_expired ? "danger" : "ok"}>{snapshot.is_expired ? "expired" : "fresh"}</Badge>
      </div>
      <div className="summary-grid">
        <div className="summary-item"><span className="summary-label">Score</span><span className="summary-value">{snapshot.score.toFixed(2)}</span></div>
        <div className="summary-item"><span className="summary-label">Computed</span><span className="summary-value">{formatDate(snapshot.computed_at)}</span></div>
        <div className="summary-item"><span className="summary-label">Expires</span><span className="summary-value">{snapshot.expires_at ? formatDate(snapshot.expires_at) : "—"}</span></div>
        <div className="summary-item"><span className="summary-label">Social items</span><span className="summary-value">{socialCount}</span></div>
        <div className="summary-item"><span className="summary-label">Queries</span><span className="summary-value">{queryCount || "—"}</span></div>
        <div className="summary-item"><span className="summary-label">Tracked tickers</span><span className="summary-value">{trackedTickers || "—"}</span></div>
      </div>
      {snapshot.drivers.length > 0 ? (
        <div>
          <div className="section-heading"><strong>Drivers</strong></div>
          <ul className="list-reset">
            {snapshot.drivers.map((driver) => (
              <li key={driver} className="list-item compact-item">{driver}</li>
            ))}
          </ul>
        </div>
      ) : null}
      <div className="helper-text">Run {snapshot.run_id ?? "—"} · Job {snapshot.job_id ?? "—"} · {jobTypeLabel(snapshot.scope === "macro" ? "macro_sentiment_refresh" : "industry_sentiment_refresh")}</div>
      <pre className="markdown-code-block">{JSON.stringify(snapshot.diagnostics, null, 2)}</pre>
    </div>
  );
}
