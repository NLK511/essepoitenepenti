import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { getJson } from "../api";
import { Badge, Card, EmptyState, ErrorState, LoadingState, PageHeader, SectionTitle, SegmentedTabs } from "../components/ui";
import type { IndustryContextSnapshot, MacroContextSnapshot } from "../types";
import { extractDisplayLabels, formatDate } from "../utils";

type ContextScope = "macro" | "industry";

type ContextSnapshot = MacroContextSnapshot | IndustryContextSnapshot;

function isIndustrySnapshot(snapshot: ContextSnapshot): snapshot is IndustryContextSnapshot {
  return "industry_key" in snapshot;
}

function contextTone(snapshot: ContextSnapshot): "ok" | "warning" | "danger" | "neutral" {
  if (snapshot.status === "failed") {
    return "danger";
  }
  if (snapshot.warnings.length > 0 || snapshot.status === "warning") {
    return "warning";
  }
  return "ok";
}

function formatWindow(value: unknown): string {
  if (typeof value !== "string" || !value) {
    return "—";
  }
  switch (value) {
    case "1d":
      return "1 day";
    case "2d_5d":
      return "2–5 days";
    case "1w_plus":
      return "1 week+";
    case "intraday":
      return "intraday";
    default:
      return value;
  }
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function eventLabel(value: unknown): string {
  return typeof value === "string" && value.trim() ? value : "—";
}

function contextEventTitle(row: Record<string, unknown>, index: number, fallbackPrefix: string): string {
  if (typeof row.title === "string" && row.title.trim()) {
    return row.title.trim();
  }
  if (typeof row.label === "string" && row.label.trim()) {
    return row.label.trim();
  }
  const key = eventLabel(row.key);
  return key !== "—" ? key : `${fallbackPrefix} ${index + 1}`;
}

function recordList(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> => typeof item === "object" && item !== null)
    : [];
}

export function ContextSnapshotDetailPage() {
  const navigate = useNavigate();
  const { scope, snapshotId } = useParams<{ scope: ContextScope; snapshotId: string }>();
  const [snapshot, setSnapshot] = useState<ContextSnapshot | null>(null);
  const [industryTabs, setIndustryTabs] = useState<IndustryContextSnapshot[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      if (!scope || !snapshotId) {
        setError("Context snapshot route is incomplete");
        return;
      }
      try {
        setError(null);
        const endpoint = scope === "macro" ? `/api/context/macro/${snapshotId}` : `/api/context/industry/${snapshotId}`;
        const payload = scope === "macro"
          ? await getJson<MacroContextSnapshot>(endpoint)
          : await getJson<IndustryContextSnapshot>(endpoint);
        setSnapshot(payload);
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : "Failed to load context snapshot");
      }
    }
    void load();
  }, [scope, snapshotId]);

  useEffect(() => {
    async function loadIndustryTabs() {
      if (scope !== "industry") {
        setIndustryTabs([]);
        return;
      }
      try {
        const snapshots = await getJson<IndustryContextSnapshot[]>("/api/context/industry?limit=100");
        const latestByIndustry = new Map<string, IndustryContextSnapshot>();
        snapshots.forEach((item) => {
          if (!latestByIndustry.has(item.industry_key)) {
            latestByIndustry.set(item.industry_key, item);
          }
        });
        setIndustryTabs(Array.from(latestByIndustry.values()));
      } catch {
        setIndustryTabs([]);
      }
    }
    void loadIndustryTabs();
  }, [scope]);

  const title = snapshot
    ? isIndustrySnapshot(snapshot)
      ? `${snapshot.industry_label || snapshot.industry_key} context #${snapshot.id}`
      : `Macro context #${snapshot.id}`
    : "Context detail";

  const summaryMethod = typeof snapshot?.metadata?.context_summary_method === "string" ? snapshot.metadata.context_summary_method : "—";
  const summaryBackend = typeof snapshot?.metadata?.context_summary_backend === "string" ? snapshot.metadata.context_summary_backend : "—";
  const summaryModel = typeof snapshot?.metadata?.context_summary_model === "string" ? snapshot.metadata.context_summary_model : "—";
  const summaryError = typeof snapshot?.metadata?.context_summary_error === "string" ? snapshot.metadata.context_summary_error : null;
  const summaryDuration = typeof snapshot?.metadata?.context_summary_duration_seconds === "number"
    ? snapshot.metadata.context_summary_duration_seconds
    : null;
  const lifecycle = snapshot && typeof snapshot.metadata?.event_lifecycle_summary === "object" && snapshot.metadata?.event_lifecycle_summary !== null
    ? snapshot.metadata.event_lifecycle_summary as Record<string, unknown>
    : null;
  const contradictions = snapshot ? stringList(snapshot.metadata?.contradictory_event_labels) : [];
  const eventRows = snapshot
    ? isIndustrySnapshot(snapshot)
      ? snapshot.active_drivers
      : snapshot.active_themes
    : [];
  const triagedEvidence = snapshot ? recordList(snapshot.metadata?.triaged_primary_evidence) : [];
  const linkedMacroLabels = snapshot && isIndustrySnapshot(snapshot)
    ? stringList(snapshot.metadata?.linked_macro_event_labels).concat(snapshot.linked_macro_themes)
    : [];
  const ontologyProfile = snapshot && isIndustrySnapshot(snapshot) && typeof snapshot.metadata?.ontology_profile === "object" && snapshot.metadata?.ontology_profile !== null
    ? snapshot.metadata.ontology_profile as Record<string, unknown>
    : null;
  const sectorDefinition = snapshot && isIndustrySnapshot(snapshot) && typeof snapshot.metadata?.sector_definition === "object" && snapshot.metadata?.sector_definition !== null
    ? snapshot.metadata.sector_definition as Record<string, unknown>
    : null;
  const ontologyRelationships = snapshot && isIndustrySnapshot(snapshot) ? recordList(snapshot.metadata?.matched_ontology_relationships) : [];

  const industryTabOptions = useMemo(() => {
    if (!snapshot || !isIndustrySnapshot(snapshot)) {
      return [] as Array<{ value: string; label: string }>;
    }
    const items = [...industryTabs];
    if (!items.some((item) => item.industry_key === snapshot.industry_key)) {
      items.unshift(snapshot);
    }
    return items.map((item) => ({
      value: item.industry_key,
      label: item.industry_label || item.industry_key,
    }));
  }, [industryTabs, snapshot]);

  function handleIndustryTabChange(industryKey: string) {
    const selected = industryTabs.find((item) => item.industry_key === industryKey);
    if (selected?.id) {
      navigate(`/context/industry/${selected.id}`);
    }
  }

  return (
    <>
      <PageHeader
        kicker="Context detail"
        title={title}
        subtitle="Inspect the stored context summary, summary provenance, top events, lifecycle, source mix, and warnings behind a macro or industry context object."
        actions={
          <>
            <Link to="/context" className="button-secondary">Back to context review</Link>
            {snapshot?.run_id ? <Link to={`/runs/${snapshot.run_id}`} className="button-subtle">Open source run</Link> : null}
          </>
        }
      />
      {error ? <ErrorState message={error} /> : null}
      {!snapshot && !error ? <LoadingState message="Loading context snapshot…" /> : null}
      {snapshot ? (
        <div className="stack-page">
          {isIndustrySnapshot(snapshot) && industryTabOptions.length > 1 ? (
            <Card>
              <SectionTitle kicker="Industry selector" title="Jump between industries" />
              <div className="helper-text">Pick an industry to open its latest stored context snapshot.</div>
              <div className="top-gap-small">
                <SegmentedTabs
                  value={snapshot.industry_key}
                  onChange={handleIndustryTabChange}
                  options={industryTabOptions}
                />
              </div>
            </Card>
          ) : null}

          <Card>
            <div className="cluster">
              <Badge tone="info">{scope}</Badge>
              <Badge tone={contextTone(snapshot)}>{snapshot.status}</Badge>
              <Badge>#{snapshot.id}</Badge>
              {isIndustrySnapshot(snapshot) ? <Badge>{snapshot.industry_label || snapshot.industry_key}</Badge> : null}
            </div>
            <div className="summary-grid top-gap-small">
              <div className="summary-item"><span className="summary-label">Computed</span><span className="summary-value">{formatDate(snapshot.computed_at)}</span></div>
              <div className="summary-item"><span className="summary-label">Saliency</span><span className="summary-value">{snapshot.saliency_score.toFixed(2)}</span></div>
              <div className="summary-item"><span className="summary-label">Confidence</span><span className="summary-value">{snapshot.confidence_percent.toFixed(1)}%</span></div>
              <div className="summary-item"><span className="summary-label">Run</span><span className="summary-value">{snapshot.run_id ?? "—"}</span></div>
              <div className="summary-item"><span className="summary-label">Job</span><span className="summary-value">{snapshot.job_id ?? "—"}</span></div>
              {isIndustrySnapshot(snapshot) ? <div className="summary-item"><span className="summary-label">Direction</span><span className="summary-value">{snapshot.direction}</span></div> : null}
            </div>
            {snapshot.summary_text ? (
              <div className="summary-text-block top-gap-small">
                <p>{snapshot.summary_text}</p>
              </div>
            ) : null}
          </Card>

          <section className="card-grid">
            <Card>
              <SectionTitle kicker="Summary provenance" title="How the summary was generated" />
              <div className="summary-grid">
                <div className="summary-item"><span className="summary-label">Method</span><span className="summary-value">{summaryMethod}</span></div>
                <div className="summary-item"><span className="summary-label">Backend</span><span className="summary-value">{summaryBackend}</span></div>
                <div className="summary-item"><span className="summary-label">Model</span><span className="summary-value">{summaryModel}</span></div>
                <div className="summary-item"><span className="summary-label">Duration</span><span className="summary-value">{summaryDuration !== null ? `${summaryDuration.toFixed(2)}s` : "—"}</span></div>
              </div>
              {summaryError ? <div className="helper-text top-gap-small">Fallback reason: {summaryError}</div> : null}
              <pre className="markdown-code-block top-gap-small">{JSON.stringify(snapshot.metadata?.context_summary_metadata ?? {}, null, 2)}</pre>
            </Card>
            <Card>
              <SectionTitle kicker="Lifecycle" title="Event lifecycle and contradiction state" />
              {lifecycle ? (
                <div className="summary-grid">
                  <div className="summary-item"><span className="summary-label">New</span><span className="summary-value">{String(lifecycle.new_event_count ?? 0)}</span></div>
                  <div className="summary-item"><span className="summary-label">Escalating</span><span className="summary-value">{String(lifecycle.escalating_event_count ?? 0)}</span></div>
                  <div className="summary-item"><span className="summary-label">Persistent</span><span className="summary-value">{String(lifecycle.persistent_event_count ?? 0)}</span></div>
                  <div className="summary-item"><span className="summary-label">Fading</span><span className="summary-value">{String(lifecycle.fading_event_count ?? 0)}</span></div>
                  <div className="summary-item"><span className="summary-label">Contradictions</span><span className="summary-value">{String(lifecycle.contradiction_count ?? 0)}</span></div>
                </div>
              ) : <EmptyState message="No lifecycle summary stored on this snapshot." />}
              {contradictions.length > 0 ? <div className="helper-text top-gap-small">Contradictory labels: {contradictions.join(", ")}</div> : null}
            </Card>
          </section>

          <Card>
            <SectionTitle kicker="Top events" title={isIndustrySnapshot(snapshot) ? "Stored industry drivers" : "Stored macro events"} />
            {eventRows.length === 0 ? <EmptyState message="No stored events on this snapshot." /> : (
              <ul className="list-reset">
                {eventRows.map((event, index) => {
                  const row = typeof event === "object" && event !== null ? event as Record<string, unknown> : {};
                  const channels = extractDisplayLabels(row, "transmission_channel_details", "transmission_channels");
                  const contradictionReasons = extractDisplayLabels(row, "contradiction_reason_details", "contradiction_reasons");
                  const persistenceLabel = typeof (row.persistence_state_detail as { label?: unknown } | undefined)?.label === "string"
                    ? (row.persistence_state_detail as { label: string }).label
                    : eventLabel(row.persistence_state);
                  const sourcePriorityLabel = typeof (row.source_priority_detail as { label?: unknown } | undefined)?.label === "string"
                    ? (row.source_priority_detail as { label: string }).label
                    : eventLabel(row.source_priority);
                  const windowLabel = typeof (row.window_hint_detail as { label?: unknown } | undefined)?.label === "string"
                    ? (row.window_hint_detail as { label: string }).label
                    : formatWindow(row.window_hint);
                  const recencyLabel = typeof (row.recency_bucket_detail as { label?: unknown } | undefined)?.label === "string"
                    ? (row.recency_bucket_detail as { label: string }).label
                    : eventLabel(row.recency_bucket);
                  const eventTitle = contextEventTitle(row, index, isIndustrySnapshot(snapshot) ? "Industry driver" : "Macro event");
                  const eventKeyLabel = eventLabel(row.key);
                  const eventLabelText = eventLabel(row.label);
                  return (
                    <li key={`${index}-${eventKeyLabel}`} className="list-item">
                      <div className="top-gap-small"><strong>{eventTitle}</strong></div>
                      {eventLabelText !== "—" && eventLabelText !== eventTitle ? <div className="helper-text">Label: {eventLabelText}</div> : null}
                      {eventKeyLabel !== "—" && eventKeyLabel !== eventTitle && eventKeyLabel !== eventLabelText ? <div className="helper-text">Key: {eventKeyLabel}</div> : null}
                      <div className="cluster top-gap-small">
                        <Badge>{eventLabel(row.label)}</Badge>
                        <Badge>{persistenceLabel}</Badge>
                        <Badge>{sourcePriorityLabel}</Badge>
                        <Badge>{windowLabel}</Badge>
                        <Badge>{recencyLabel}</Badge>
                        {typeof row.saliency_weight === "number" ? <Badge>saliency {row.saliency_weight}</Badge> : null}
                      </div>
                      {channels.length > 0 ? <div className="helper-text top-gap-small">Channels: {channels.join(", ")}</div> : null}
                      {contradictionReasons.length > 0 ? <div className="helper-text top-gap-small">Contradiction reasons: {contradictionReasons.join(", ")}</div> : null}
                      {Array.isArray(row.evidence_samples) && row.evidence_samples.length > 0 ? (
                        <div className="helper-text top-gap-small">Evidence: {row.evidence_samples.slice(0, 3).join(" | ")}</div>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            )}
          </Card>

          <section className="card-grid">
            <Card>
              <SectionTitle kicker="Evidence" title="Triaged primary evidence" />
              {triagedEvidence.length === 0 ? <EmptyState message="No triaged primary evidence was stored on this snapshot." /> : (
                <ul className="list-reset">
                  {triagedEvidence.map((item, index) => (
                    <li key={`${index}-${eventLabel(item.title)}`} className="list-item">
                      <div className="cluster">
                        <Badge>{eventLabel(item.source_priority)}</Badge>
                        <span>{eventLabel(item.publisher)}</span>
                      </div>
                      <div className="top-gap-small"><strong>{eventLabel(item.title)}</strong></div>
                      {typeof item.summary === "string" && item.summary.trim() ? <div className="helper-text top-gap-small">{item.summary}</div> : null}
                    </li>
                  ))}
                </ul>
              )}
            </Card>
            <Card>
              <SectionTitle kicker="Warnings" title="Warnings and missing inputs" />
              {snapshot.warnings.length === 0 && snapshot.missing_inputs.length === 0 ? <EmptyState message="No warnings or missing inputs recorded." /> : (
                <>
                  {snapshot.warnings.length > 0 ? (
                    <ul className="list-reset">
                      {snapshot.warnings.map((warning) => <li key={warning} className="list-item compact-item">{warning}</li>)}
                    </ul>
                  ) : null}
                  {snapshot.missing_inputs.length > 0 ? <div className="helper-text top-gap-small">Missing inputs: {snapshot.missing_inputs.join(", ")}</div> : null}
                </>
              )}
            </Card>
          </section>

          <section className="card-grid">
            <Card>
              <SectionTitle kicker="Source breakdown" title="Stored source mix" />
              <div className="summary-grid">
                <div className="summary-item"><span className="summary-label">Primary news items</span><span className="summary-value">{String(snapshot.source_breakdown?.primary_news_item_count ?? 0)}</span></div>
                <div className="summary-item"><span className="summary-label">Supporting social items</span><span className="summary-value">{String(snapshot.source_breakdown?.supporting_social_item_count ?? 0)}</span></div>
                <div className="summary-item"><span className="summary-label">Coverage quality</span><span className="summary-value">{eventLabel(snapshot.source_breakdown?.primary_news_coverage_quality)}</span></div>
                <div className="summary-item"><span className="summary-label">Providers</span><span className="summary-value">{stringList(snapshot.source_breakdown?.primary_news_providers).join(", ") || "—"}</span></div>
              </div>
              <div className="helper-text top-gap-small">Publishers: {stringList(snapshot.source_breakdown?.primary_news_publishers).join(", ") || "—"}</div>
              <div className="helper-text top-gap-small">Source priorities: {stringList(snapshot.source_breakdown?.primary_news_source_priorities).join(", ") || "—"}</div>
              {isIndustrySnapshot(snapshot) ? <div className="helper-text top-gap-small">Linked macro themes: {linkedMacroLabels.join(", ") || "—"}</div> : null}
            </Card>
            {isIndustrySnapshot(snapshot) ? (
              <Card>
                <SectionTitle kicker="Ontology" title="Stored industry ontology context" />
                <div className="summary-grid">
                  <div className="summary-item"><span className="summary-label">Sector</span><span className="summary-value">{eventLabel(sectorDefinition?.label ?? ontologyProfile?.sector)}</span></div>
                  <div className="summary-item"><span className="summary-label">Peer industries</span><span className="summary-value">{stringList(ontologyProfile?.peer_industries).join(", ") || "—"}</span></div>
                  <div className="summary-item"><span className="summary-label">Risk flags</span><span className="summary-value">{stringList(ontologyProfile?.risk_flags).join(", ") || "—"}</span></div>
                  <div className="summary-item"><span className="summary-label">Taxonomy source</span><span className="summary-value">{eventLabel(snapshot.metadata?.taxonomy_source_mode)}</span></div>
                </div>
                <div className="helper-text top-gap-small">Transmission channels: {extractDisplayLabels(ontologyProfile, "transmission_channel_details", "transmission_channels").join(", ") || "—"}</div>
                <div className="helper-text top-gap-small">Matched ontology relationships: {ontologyRelationships.length}</div>
                {ontologyRelationships.length > 0 ? (
                  <ul className="list-reset top-gap-small">
                    {ontologyRelationships.map((relationship, index) => (
                      <li key={`${index}-${eventLabel(relationship.target)}`} className="list-item compact-item">
                        {eventLabel(relationship.type_label ?? relationship.type)} {eventLabel(relationship.target_label ?? relationship.target)} via {eventLabel(relationship.channel_label ?? relationship.channel)}
                      </li>
                    ))}
                  </ul>
                ) : null}
              </Card>
            ) : (
              <Card>
                <SectionTitle kicker="Diagnostics" title="Stored JSON detail" />
                <pre className="markdown-code-block">{JSON.stringify({ source_breakdown: snapshot.source_breakdown, metadata: snapshot.metadata }, null, 2)}</pre>
              </Card>
            )}
          </section>
          {isIndustrySnapshot(snapshot) ? (
            <Card>
              <SectionTitle kicker="Diagnostics" title="Stored JSON detail" />
              <pre className="markdown-code-block">{JSON.stringify({ source_breakdown: snapshot.source_breakdown, metadata: snapshot.metadata }, null, 2)}</pre>
            </Card>
          ) : null}
        </div>
      ) : null}
    </>
  );
}
