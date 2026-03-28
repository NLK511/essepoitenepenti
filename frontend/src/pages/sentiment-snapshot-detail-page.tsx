import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { getJson } from "../api";
import { Badge, Card, EmptyState, ErrorState, LoadingState, PageHeader, SectionTitle } from "../components/ui";
import type { SupportSnapshot } from "../types";
import { formatDate } from "../utils";

function snapshotTone(snapshot: SupportSnapshot): "ok" | "warning" | "danger" | "neutral" {
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

export function SupportSnapshotDetailPage() {
  const { snapshotId } = useParams<{ snapshotId: string }>();
  const [snapshot, setSnapshot] = useState<SupportSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      if (!snapshotId) {
        setError("Snapshot id is missing");
        return;
      }
      try {
        setError(null);
        setSnapshot(await getJson<SupportSnapshot>(`/api/sentiment-snapshots/${snapshotId}`));
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : "Failed to load support snapshot");
      }
    }
    void load();
  }, [snapshotId]);

  return (
    <>
      <PageHeader
        kicker="Support snapshot detail"
        title={snapshot ? `${snapshot.subject_label} snapshot #${snapshot.id}` : "Support snapshot detail"}
        subtitle="Inspect the stored transitional support snapshot used for refresh auditing, freshness checks, and compatibility with the context-first workflow."
        actions={
          <>
            <Link to="/context" className="button-secondary">Back to context snapshots</Link>
            {snapshot?.run_id ? <Link to={`/runs/${snapshot.run_id}`} className="button-subtle">Open source run</Link> : null}
          </>
        }
      />
      {error ? <ErrorState message={error} /> : null}
      {!snapshot && !error ? <LoadingState message="Loading support snapshot…" /> : null}
      {snapshot ? (
        <div className="stack-page">
          <Card>
            <div className="cluster">
              <Badge tone="info">{snapshot.scope}</Badge>
              <Badge tone={snapshotTone(snapshot)}>{snapshot.label}</Badge>
              <Badge tone={snapshot.is_expired ? "danger" : "ok"}>{snapshot.is_expired ? "expired" : "fresh"}</Badge>
              <Badge>#{snapshot.id}</Badge>
            </div>
            <div className="summary-grid top-gap-small">
              <div className="summary-item"><span className="summary-label">Subject</span><span className="summary-value">{snapshot.subject_label}</span></div>
              <div className="summary-item"><span className="summary-label">Score</span><span className="summary-value">{snapshot.score.toFixed(2)}</span></div>
              <div className="summary-item"><span className="summary-label">Computed</span><span className="summary-value">{formatDate(snapshot.computed_at)}</span></div>
              <div className="summary-item"><span className="summary-label">Expires</span><span className="summary-value">{snapshot.expires_at ? formatDate(snapshot.expires_at) : "—"}</span></div>
              <div className="summary-item"><span className="summary-label">Run</span><span className="summary-value">{snapshot.run_id ?? "—"}</span></div>
              <div className="summary-item"><span className="summary-label">Job</span><span className="summary-value">{snapshot.job_id ?? "—"}</span></div>
            </div>
            {snapshot.summary_text ? (
              <div className="summary-text-block top-gap-small">
                <p>{snapshot.summary_text}</p>
              </div>
            ) : null}
          </Card>

          <Card>
            <SectionTitle kicker="Drivers" title="Primary narrative drivers" />
            {snapshot.drivers.length === 0 ? <EmptyState message="No drivers stored on this snapshot." /> : (
              <ul className="list-reset">
                {snapshot.drivers.map((driver) => <li key={driver} className="list-item">{driver}</li>)}
              </ul>
            )}
          </Card>

          <section className="card-grid">
            <Card>
              <SectionTitle kicker="Coverage" title="Coverage summary" />
              <pre className="markdown-code-block">{JSON.stringify(snapshot.coverage, null, 2)}</pre>
            </Card>
            <Card>
              <SectionTitle kicker="Source breakdown" title="Source contribution" />
              <pre className="markdown-code-block">{JSON.stringify(snapshot.source_breakdown, null, 2)}</pre>
            </Card>
            <Card>
              <SectionTitle kicker="Signals" title="Normalized signals" />
              <pre className="markdown-code-block">{JSON.stringify(snapshot.signals, null, 2)}</pre>
            </Card>
            <Card>
              <SectionTitle kicker="Diagnostics" title="Diagnostics and warnings" />
              <pre className="markdown-code-block">{JSON.stringify(snapshot.diagnostics, null, 2)}</pre>
            </Card>
          </section>
        </div>
      ) : null}
    </>
  );
}

export const SentimentSnapshotDetailPage = SupportSnapshotDetailPage;
