import { Badge, Card, SectionTitle } from "./ui";

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

export function relationshipItems(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => !!item && typeof item === "object" && !Array.isArray(item)) : [];
}

export function relationshipLabel(item: Record<string, unknown>): string {
  const relationType = typeof item.type === "string" ? item.type.split("_").join(" ") : "relationship";
  const target = typeof item.target === "string"
    ? item.target
    : typeof item.target_label === "string"
      ? item.target_label
      : "target";
  const channel = typeof item.channel === "string" ? item.channel.split("_").join(" ") : null;
  return channel ? `${relationType} · ${target} · ${channel}` : `${relationType} · ${target}`;
}

export function transmissionSummaryFromPlan(plan: { signal_breakdown?: unknown; evidence_summary?: unknown }): Record<string, unknown> | null {
  const signalBreakdown = asRecord(plan.signal_breakdown);
  const evidenceSummary = asRecord(plan.evidence_summary);
  return asRecord(signalBreakdown?.transmission_summary) ?? asRecord(evidenceSummary?.transmission_summary);
}

export function matchedRelationshipsFromPlan(plan: { signal_breakdown?: unknown; evidence_summary?: unknown }): Array<Record<string, unknown>> {
  return relationshipItems(transmissionSummaryFromPlan(plan)?.matched_ticker_relationships);
}

export function storedRelationshipEdgesFromPlan(plan: { signal_breakdown?: unknown; evidence_summary?: unknown }): Array<Record<string, unknown>> {
  return relationshipItems(transmissionSummaryFromPlan(plan)?.ticker_relationship_edges);
}

export function relationshipSummary(plan: { signal_breakdown?: unknown; evidence_summary?: unknown }, limit = 2): string {
  const matched = matchedRelationshipsFromPlan(plan);
  if (matched.length > 0) {
    return matched.slice(0, limit).map((item) => relationshipLabel(item)).join(" · ");
  }
  const stored = storedRelationshipEdgesFromPlan(plan);
  if (stored.length > 0) {
    return `${stored.length} stored`;
  }
  return "none";
}

export function TickerRelationshipReadthroughCard(props: {
  title: string;
  subtitle?: string;
  matched: Array<Record<string, unknown>>;
  storedEdges: Array<Record<string, unknown>>;
  emptyMessage?: string;
}) {
  const matched = props.matched;
  const storedEdges = props.storedEdges;
  const fallbackEdges = storedEdges.slice(0, 4);

  return (
    <Card>
      <SectionTitle kicker="Ticker read-through" title={props.title} subtitle={props.subtitle} />
      {matched.length > 0 ? (
        <>
          <div className="cluster top-gap-small">
            <Badge tone="ok">matched {matched.length}</Badge>
            {storedEdges.length > 0 ? <Badge tone="neutral">stored {storedEdges.length}</Badge> : null}
          </div>
          <div className="data-stack top-gap-small">
            {matched.slice(0, 4).map((item, index) => {
              const note = typeof item.note === "string" ? item.note : null;
              const strength = typeof item.strength === "string" ? item.strength : null;
              const hits = typeof item.relevance_hits === "number" ? item.relevance_hits : null;
              return (
                <article key={`${relationshipLabel(item)}-${index}`} className="data-card">
                  <div className="helper-text">{relationshipLabel(item)}</div>
                  <div className="cluster top-gap-small">
                    {strength ? <Badge tone="neutral">{strength}</Badge> : null}
                    {hits !== null ? <Badge tone="info">hits {hits}</Badge> : null}
                  </div>
                  {note ? <div className="helper-text top-gap-small">{note}</div> : null}
                </article>
              );
            })}
          </div>
        </>
      ) : fallbackEdges.length > 0 ? (
        <>
          <div className="cluster top-gap-small">
            <Badge tone="neutral">matched 0</Badge>
            <Badge tone="neutral">stored {storedEdges.length}</Badge>
          </div>
          <div className="helper-text top-gap-small">No stored ticker relationship edge matched the current evidence strongly enough yet.</div>
          <div className="data-stack top-gap-small">
            {fallbackEdges.map((item, index) => (
              <article key={`${relationshipLabel(item)}-${index}`} className="data-card">
                <div className="helper-text">{relationshipLabel(item)}</div>
              </article>
            ))}
          </div>
        </>
      ) : (
        <div className="helper-text top-gap-small">{props.emptyMessage ?? "No ticker relationship read-through was stored for this plan."}</div>
      )}
    </Card>
  );
}
