import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { getJson, postForm } from "../api";
import { useToast } from "../components/toast";
import { Badge, Card, EmptyState, ErrorState, LoadingState, PageHeader, SectionTitle } from "../components/ui";
import type { MacroContextSnapshot, Run, SentimentSnapshot, SentimentSnapshotListResponse } from "../types";
import { formatDate, jobTypeLabel } from "../utils";

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

function macroContextTone(snapshot: MacroContextSnapshot): "ok" | "warning" | "danger" | "neutral" {
  if (snapshot.status === "failed") {
    return "danger";
  }
  if (snapshot.warnings.length > 0 || snapshot.status === "warning") {
    return "warning";
  }
  return "ok";
}

function topMacroTheme(snapshot: MacroContextSnapshot): Record<string, unknown> | null {
  const top = snapshot.active_themes[0];
  return top && typeof top === "object" ? top : null;
}

function themeString(value: unknown, fallback = "—"): string {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function formatWindow(window: string): string {
  switch (window) {
    case "1d":
      return "1 day";
    case "2d_5d":
      return "2–5 days";
    case "1w_plus":
      return "1 week+";
    case "intraday":
      return "intraday";
    default:
      return window || "—";
  }
}

function summaryMethod(snapshot: MacroContextSnapshot): string {
  return typeof snapshot.metadata?.context_summary_method === "string" ? snapshot.metadata.context_summary_method : "unknown";
}

function summaryBackend(snapshot: MacroContextSnapshot): string {
  return typeof snapshot.metadata?.context_summary_backend === "string" ? snapshot.metadata.context_summary_backend : "—";
}

function summaryModel(snapshot: MacroContextSnapshot): string {
  return typeof snapshot.metadata?.context_summary_model === "string" ? snapshot.metadata.context_summary_model : "—";
}

function summaryError(snapshot: MacroContextSnapshot): string | null {
  return typeof snapshot.metadata?.context_summary_error === "string" ? snapshot.metadata.context_summary_error : null;
}

function provenanceTone(snapshot: MacroContextSnapshot): "ok" | "warning" | "neutral" {
  if (summaryError(snapshot)) {
    return "warning";
  }
  if (summaryMethod(snapshot) === "llm_summary") {
    return "ok";
  }
  return "neutral";
}

function provenanceLabel(snapshot: MacroContextSnapshot): string {
  const method = summaryMethod(snapshot);
  if (method === "llm_summary") {
    return `LLM · ${summaryBackend(snapshot)}${summaryModel(snapshot) !== "—" ? ` · ${summaryModel(snapshot)}` : ""}`;
  }
  return `fallback · ${summaryBackend(snapshot)}`;
}

export function SentimentSnapshotsPage() {
  const { showToast } = useToast();
  const [macro, setMacro] = useState<SentimentSnapshot[]>([]);
  const [industry, setIndustry] = useState<SentimentSnapshot[]>([]);
  const [macroContexts, setMacroContexts] = useState<MacroContextSnapshot[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyAction, setBusyAction] = useState<"macro" | "industry" | "macro-now" | "industry-now" | null>(null);

  async function load() {
    try {
      setLoading(true);
      setError(null);
      const [macroResponse, industryResponse, macroContextResponse] = await Promise.all([
        getJson<SentimentSnapshotListResponse>("/api/sentiment-snapshots/macro?limit=6"),
        getJson<SentimentSnapshotListResponse>("/api/sentiment-snapshots/industry?limit=12"),
        getJson<MacroContextSnapshot[]>("/api/context/macro?limit=6"),
      ]);
      setMacro(macroResponse.snapshots);
      setIndustry(industryResponse.snapshots);
      setMacroContexts(macroContextResponse);
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

  async function runRefreshNow(scope: "macro" | "industry") {
    try {
      setBusyAction(scope === "macro" ? "macro-now" : "industry-now");
      setError(null);
      const response = await postForm<{ run: Run; executed: boolean; reason?: string; artifact?: Record<string, unknown> }>(
        `/api/sentiment-snapshots/refresh/${scope}/run-now`,
        {},
      );
      showToast({
        message: response.executed
          ? `${scope === "macro" ? "Macro" : "Industry"} refresh finished in run #${response.run.id}`
          : `${scope === "macro" ? "Macro" : "Industry"} refresh reused existing run #${response.run.id}`,
        tone: response.executed ? "success" : "warning",
      });
      await load();
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : `Failed to run ${scope} refresh now`);
    } finally {
      setBusyAction(null);
    }
  }

  const latestMacroSentiment = macro[0] ?? null;
  const latestIndustry = industry[0] ?? null;
  const latestMacroContext = macroContexts[0] ?? null;
  const topTheme = latestMacroContext ? topMacroTheme(latestMacroContext) : null;

  return (
    <>
      <PageHeader
        kicker="Shared snapshots"
        title="Inspect shared sentiment snapshots and macro context."
        subtitle="Macro sentiment snapshots still exist, but the saliency-first macro overview now comes from stored macro context snapshots. Use this page to see both the old snapshot trail and the current macro context read." 
        actions={
          <>
            <button type="button" className="button" onClick={() => void enqueueRefresh("macro")} disabled={busyAction !== null}>
              {busyAction === "macro" ? "Queueing macro refresh…" : "Queue macro refresh"}
            </button>
            <button type="button" className="button-secondary" onClick={() => void runRefreshNow("macro")} disabled={busyAction !== null}>
              {busyAction === "macro-now" ? "Running macro refresh…" : "Run macro now"}
            </button>
            <button type="button" className="button" onClick={() => void enqueueRefresh("industry")} disabled={busyAction !== null}>
              {busyAction === "industry" ? "Queueing industry refresh…" : "Queue industries refresh"}
            </button>
            <button type="button" className="button-secondary" onClick={() => void runRefreshNow("industry")} disabled={busyAction !== null}>
              {busyAction === "industry-now" ? "Running industry refresh…" : "Run industries now"}
            </button>
            <button type="button" className="button-subtle" onClick={() => void load()} disabled={loading}>
              Reload
            </button>
          </>
        }
      />

      {error ? <ErrorState message={error} /> : null}
      {loading ? <LoadingState message="Loading shared snapshots…" /> : null}

      {!loading ? (
        <div className="stack-page">
          <section className="metrics-grid">
            <Card>
              <div className="metric-label">Top macro event</div>
              <div className="metric-value">{topTheme ? themeString(topTheme.label) : "—"}</div>
              <div className="helper-text">{latestMacroContext ? formatDate(latestMacroContext.computed_at) : "No macro context yet"}</div>
            </Card>
            <Card>
              <div className="metric-label">Macro context confidence</div>
              <div className="metric-value">{latestMacroContext ? `${latestMacroContext.confidence_percent.toFixed(1)}%` : "—"}</div>
              <div className="helper-text">{latestMacroContext ? `Saliency ${latestMacroContext.saliency_score.toFixed(2)}` : "No macro context yet"}</div>
              {latestMacroContext ? (
                <div className="top-gap-small cluster">
                  <Badge tone={provenanceTone(latestMacroContext)}>{provenanceLabel(latestMacroContext)}</Badge>
                  {summaryError(latestMacroContext) ? <Badge tone="warning">summary warning</Badge> : null}
                </div>
              ) : null}
            </Card>
            <Card>
              <div className="metric-label">Latest macro sentiment snapshot</div>
              <div className="metric-value">{latestMacroSentiment ? latestMacroSentiment.label : "—"}</div>
              <div className="helper-text">{latestMacroSentiment ? formatDate(latestMacroSentiment.computed_at) : "No macro snapshot yet"}</div>
            </Card>
            <Card>
              <div className="metric-label">Latest industry snapshot</div>
              <div className="metric-value">{latestIndustry ? latestIndustry.subject_label : "—"}</div>
              <div className="helper-text">{latestIndustry ? `${latestIndustry.label} · ${formatDate(latestIndustry.computed_at)}` : "No industry snapshot yet"}</div>
            </Card>
          </section>

          <section className="two-column">
            <Card>
              <SectionTitle kicker="Macro context" title="Current saliency-first macro overview" />
              {latestMacroContext ? <MacroContextSummary snapshot={latestMacroContext} /> : <EmptyState message="No macro context snapshots available yet." />}
            </Card>
            <Card>
              <SectionTitle kicker="Industry sentiment" title="Latest shared industry sentiment snapshot" />
              {latestIndustry ? <SnapshotSummary snapshot={latestIndustry} /> : <EmptyState message="No industry snapshots available yet." />}
            </Card>
          </section>

          <section className="card-grid">
            <Card>
              <SectionTitle kicker="Macro context history" title="Recent macro context snapshots" />
              {macroContexts.length === 0 ? <EmptyState message="No macro context snapshots stored yet." /> : <MacroContextList snapshots={macroContexts} />}
            </Card>
            <Card>
              <SectionTitle kicker="Macro sentiment history" title="Recent macro sentiment snapshots" />
              {macro.length === 0 ? <EmptyState message="No macro sentiment snapshots stored yet." /> : <SnapshotList snapshots={macro} />}
            </Card>
            <Card>
              <SectionTitle kicker="Industry history" title="Recent industry sentiment snapshots" />
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
              {snapshot.summary_text ? <div className="helper-text top-gap-small">{snapshot.summary_text}</div> : null}
            </div>
            {snapshot.id ? <Link to={`/sentiment/${snapshot.id}`} className="button-subtle">Open</Link> : null}
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
      {snapshot.summary_text ? (
        <div className="summary-text-block top-gap-small">
          <p>{snapshot.summary_text}</p>
        </div>
      ) : null}
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
      {snapshot.id ? <Link to={`/sentiment/${snapshot.id}`} className="button-subtle">Open snapshot detail</Link> : null}
      <pre className="markdown-code-block">{JSON.stringify(snapshot.diagnostics, null, 2)}</pre>
    </div>
  );
}

function MacroContextList({ snapshots }: { snapshots: MacroContextSnapshot[] }) {
  return (
    <ul className="list-reset">
      {snapshots.map((snapshot) => {
        const topTheme = topMacroTheme(snapshot);
        return (
          <li key={snapshot.id ?? snapshot.computed_at} className="list-item">
            <div className="card-headline">
              <div>
                <div className="cluster">
                  <Badge tone="info">macro context</Badge>
                  <Badge tone={macroContextTone(snapshot)}>{snapshot.status}</Badge>
                  {topTheme ? <Badge>{themeString(topTheme.label)}</Badge> : null}
                </div>
                <div className="helper-text">Saliency {snapshot.saliency_score.toFixed(2)} · confidence {snapshot.confidence_percent.toFixed(1)}% · computed {formatDate(snapshot.computed_at)}</div>
                <div className="top-gap-small cluster">
                  <Badge tone={provenanceTone(snapshot)}>{provenanceLabel(snapshot)}</Badge>
                  {summaryError(snapshot) ? <Badge tone="warning">fallback reason stored</Badge> : null}
                </div>
                {snapshot.summary_text ? <div className="helper-text top-gap-small">{snapshot.summary_text}</div> : null}
                {summaryError(snapshot) ? <div className="helper-text top-gap-small">{summaryError(snapshot)}</div> : null}
              </div>
              <div className="cluster">
                {snapshot.id ? <Link to={`/context/macro/${snapshot.id}`} className="button-subtle">Open detail</Link> : null}
                {snapshot.run_id ? <Link to={`/runs/${snapshot.run_id}`} className="button-subtle">Open run</Link> : null}
              </div>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function MacroContextSummary({ snapshot }: { snapshot: MacroContextSnapshot }) {
  const topTheme = topMacroTheme(snapshot);
  const contradictory = Array.isArray(snapshot.metadata?.contradictory_event_labels)
    ? snapshot.metadata.contradictory_event_labels.filter((value): value is string => typeof value === "string")
    : [];
  const topChannels = Array.isArray(topTheme?.transmission_channels)
    ? topTheme.transmission_channels.filter((value): value is string => typeof value === "string").slice(0, 2)
    : [];

  return (
    <div className="stack-page">
      <div className="cluster">
        <Badge tone="info">macro context</Badge>
        <Badge tone={macroContextTone(snapshot)}>{snapshot.status}</Badge>
        {topTheme ? <Badge>{themeString(topTheme.label)}</Badge> : null}
      </div>
      <div className="summary-grid">
        <div className="summary-item"><span className="summary-label">Top event</span><span className="summary-value">{topTheme ? themeString(topTheme.label) : "—"}</span></div>
        <div className="summary-item"><span className="summary-label">State</span><span className="summary-value">{topTheme ? themeString(topTheme.persistence_state) : "—"}</span></div>
        <div className="summary-item"><span className="summary-label">Window</span><span className="summary-value">{topTheme ? formatWindow(themeString(topTheme.window_hint, "")) : "—"}</span></div>
        <div className="summary-item"><span className="summary-label">Source quality</span><span className="summary-value">{topTheme ? themeString(topTheme.source_priority) : "—"}</span></div>
        <div className="summary-item"><span className="summary-label">Saliency</span><span className="summary-value">{snapshot.saliency_score.toFixed(2)}</span></div>
        <div className="summary-item"><span className="summary-label">Confidence</span><span className="summary-value">{snapshot.confidence_percent.toFixed(1)}%</span></div>
      </div>
      <div className="top-gap-small cluster">
        <Badge tone={provenanceTone(snapshot)}>{provenanceLabel(snapshot)}</Badge>
        {summaryError(snapshot) ? <Badge tone="warning">fallback reason stored</Badge> : null}
      </div>
      {snapshot.summary_text ? (
        <div className="summary-text-block top-gap-small">
          <p>{snapshot.summary_text}</p>
        </div>
      ) : null}
      {topChannels.length > 0 ? (
        <div>
          <div className="section-heading"><strong>Main transmission channels</strong></div>
          <div className="cluster">
            {topChannels.map((channel) => <Badge key={channel}>{channel}</Badge>)}
          </div>
        </div>
      ) : null}
      {contradictory.length > 0 ? (
        <div>
          <div className="section-heading"><strong>Contradictions</strong></div>
          <div className="helper-text">{contradictory.join(", ")}</div>
        </div>
      ) : null}
      {snapshot.warnings.length > 0 ? (
        <div>
          <div className="section-heading"><strong>Warnings</strong></div>
          <ul className="list-reset">
            {snapshot.warnings.map((warning) => <li key={warning} className="list-item compact-item">{warning}</li>)}
          </ul>
        </div>
      ) : null}
      {summaryError(snapshot) ? <div className="helper-text top-gap-small">Summary fallback reason: {summaryError(snapshot)}</div> : null}
      <div className="helper-text">Run {snapshot.run_id ?? "—"} · Job {snapshot.job_id ?? "—"}</div>
      <div className="cluster">
        {snapshot.id ? <Link to={`/context/macro/${snapshot.id}`} className="button-subtle">Open context detail</Link> : null}
        {snapshot.run_id ? <Link to={`/runs/${snapshot.run_id}`} className="button-subtle">Open source run</Link> : null}
      </div>
    </div>
  );
}
