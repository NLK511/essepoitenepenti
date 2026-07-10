import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { getJson, postForm } from "../api";
import { useToast } from "../components/toast";
import { Badge, Card, DisclosureCard, EmptyState, ErrorState, HelpHint, LoadingState, PageHeader, SectionTitle, SegmentedTabs } from "../components/ui";
import { ContextEventSummary, ContextScoreSummary, ProvenanceStrip, WarningSummary } from "../components/decision-surface";
import type { ContextEventRow, IndustryContextSnapshot, MacroContextSnapshot, Run } from "../types";
import { contextInterpretationTone, contextProvenanceLabel, contextSummaryBackend, contextSummaryError, contextSummaryMethod, contextSummaryModel, contextSnapshotTone, extractDisplayLabels, formatDate } from "../utils";

type IndustryContextSummary = {
  total_count: number;
  status_counts: Record<string, number>;
  evidence_state_counts: Record<string, number>;
  quality_status_counts: Record<string, number>;
  coverage_state_counts?: Record<string, number>;
  neutral_reason_counts?: Record<string, number>;
  active_driver_count: number;
  empty_driver_count: number;
  zero_confidence_count: number;
  stale_count?: number;
  decision_usable_count?: number;
  decision_usable_rate_percent?: number;
  usable_rate_percent: number;
  active_driver_rate_percent: number;
  warning_count: number;
  top_neutral_reasons?: Array<[string, number]>;
  top_warnings: Array<[string, number]>;
  top_missing_inputs: Array<[string, number]>;
};

function topMacroTheme(snapshot: MacroContextSnapshot): ContextEventRow | null {
  return snapshot.active_themes[0] ?? null;
}

function topIndustryDriver(snapshot: IndustryContextSnapshot): ContextEventRow | null {
  return snapshot.active_drivers[0] ?? null;
}

function themeString(value: unknown, fallback = "—"): string {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function detailLabel(detail: unknown, fallback: unknown, empty = "—"): string {
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const label = (detail as { label?: unknown }).label;
    if (typeof label === "string" && label.trim()) {
      return label;
    }
  }
  return themeString(fallback, empty);
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && item.trim().length > 0) : [];
}

function contradictoryMacroThemes(snapshot: MacroContextSnapshot): string[] {
  return stringList(snapshot.metadata?.contradictory_event_labels);
}

function contextBreakdownValue(snapshot: IndustryContextSnapshot, key: string, fallback = "unknown"): string {
  const contextQuality = snapshot.metadata?.context_quality;
  const metadataValue = contextQuality && typeof contextQuality === "object" && !Array.isArray(contextQuality)
    ? (contextQuality as Record<string, unknown>)[key]
    : undefined;
  const value = snapshot.source_breakdown?.[key] ?? metadataValue;
  return typeof value === "string" && value.trim() ? value : fallback;
}

function industryNeutralReason(snapshot: IndustryContextSnapshot): string {
  const scoreReasons = snapshot.source_breakdown?.score_reasons;
  if (Array.isArray(scoreReasons) && scoreReasons.length > 0 && typeof scoreReasons[0] === "string") return scoreReasons[0];
  const quality = contextBreakdownValue(snapshot, "context_quality_status");
  const evidence = contextBreakdownValue(snapshot, "evidence_state");
  const coverage = contextBreakdownValue(snapshot, "coverage_state");
  if (quality === "blocked" || quality === "failed") return "context quality blocked";
  if (quality === "degraded" || quality === "partial") return "context quality degraded";
  if (evidence === "missing" || evidence === "missing_snapshot") return "missing industry evidence";
  if (coverage === "missing") return "missing industry coverage";
  if (snapshot.active_drivers.length === 0) return "no salient industry drivers";
  return "balanced or neutral context";
}

function actionLabel(scope: "macro" | "industry"): string {
  return scope === "macro" ? "Macro" : "Industry";
}

function docsLink(doc: string, section?: string): string {
  const params = new URLSearchParams({ doc });
  if (section) {
    params.set("section", section);
  }
  return `/docs?${params.toString()}`;
}

const contextReviewDoc = (section?: string) => docsLink("operator-page-field-guide", section);

export function ContextReviewPage() {
  const { showToast } = useToast();
  const [macroContexts, setMacroContexts] = useState<MacroContextSnapshot[]>([]);
  const [industryContexts, setIndustryContexts] = useState<IndustryContextSnapshot[]>([]);
  const [industrySummary, setIndustrySummary] = useState<IndustryContextSummary | null>(null);
  const [selectedIndustryHistory, setSelectedIndustryHistory] = useState<IndustryContextSnapshot[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyAction, setBusyAction] = useState<"macro" | "industry" | null>(null);
  const [activeTab, setActiveTab] = useState<"macro" | "industry">("macro");

  async function load() {
    try {
      setLoading(true);
      setError(null);
      const [macroContextResponse, industryContextResponse, industrySummaryResponse] = await Promise.all([
        getJson<MacroContextSnapshot[]>("/api/context/macro?limit=6"),
        getJson<IndustryContextSnapshot[]>("/api/context/industry?limit=24"),
        getJson<IndustryContextSummary>("/api/context/industry/summary"),
      ]);
      setMacroContexts(macroContextResponse);
      setIndustryContexts(industryContextResponse);
      setIndustrySummary(industrySummaryResponse);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to load context review data");
    } finally {
      setLoading(false);
    }
  }

  async function loadIndustryHistory(industryKey: string) {
    try {
      const history = await getJson<IndustryContextSnapshot[]>(`/api/context/industry?industry_key=${encodeURIComponent(industryKey)}&limit=50`);
      setSelectedIndustryHistory(history);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : `Failed to load history for ${industryKey}`);
      setSelectedIndustryHistory([]);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function enqueueRefresh(scope: "macro" | "industry") {
    try {
      setBusyAction(scope);
      setError(null);
      const run = await postForm<Run>(`/api/context/refresh/${scope}`, {});
      showToast({
        message: `${actionLabel(scope)} refresh queued as run #${run.id}`,
        tone: "success",
      });
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : `Failed to queue ${scope} refresh`);
    } finally {
      setBusyAction(null);
    }
  }

  const latestMacroContext = macroContexts[0] ?? null;

  const latestIndustryByKey = useMemo(() => {
    const map = new Map<string, IndustryContextSnapshot>();
    industryContexts.forEach((snapshot) => {
      if (!map.has(snapshot.industry_key)) {
        map.set(snapshot.industry_key, snapshot);
      }
    });
    return map;
  }, [industryContexts]);

  const industryOptions = useMemo(
    () => Array.from(latestIndustryByKey.values()).map((snapshot) => ({
      value: snapshot.industry_key,
      label: snapshot.industry_label || snapshot.industry_key,
    })),
    [latestIndustryByKey],
  );

  const [selectedIndustryKey, setSelectedIndustryKey] = useState<string | null>(null);

  useEffect(() => {
    if (industryOptions.length === 0) {
      setSelectedIndustryKey(null);
      setSelectedIndustryHistory([]);
      return;
    }
    if (!selectedIndustryKey || !latestIndustryByKey.has(selectedIndustryKey)) {
      setSelectedIndustryKey(industryOptions[0]?.value ?? null);
    }
  }, [industryOptions, latestIndustryByKey, selectedIndustryKey]);

  useEffect(() => {
    if (!selectedIndustryKey) {
      setSelectedIndustryHistory([]);
      return;
    }
    void loadIndustryHistory(selectedIndustryKey);
  }, [selectedIndustryKey]);

  const latestIndustryContext = selectedIndustryKey ? latestIndustryByKey.get(selectedIndustryKey) ?? null : industryContexts[0] ?? null;
  const visibleIndustryHistory = selectedIndustryKey ? selectedIndustryHistory : industryContexts;

  const headerMetrics = useMemo(() => {
    if (activeTab === "macro") {
      const topTheme = latestMacroContext ? topMacroTheme(latestMacroContext) : null;
      return [
        {
          label: "Top macro event",
          value: topTheme ? themeString(topTheme.label) : "—",
          helper: latestMacroContext ? formatDate(latestMacroContext.computed_at) : "No macro context yet",
        },
        {
          label: "Confidence",
          value: latestMacroContext ? `${latestMacroContext.confidence_percent.toFixed(1)}%` : "—",
          helper: latestMacroContext ? `Saliency ${latestMacroContext.saliency_score.toFixed(2)}` : "No macro context yet",
        },
        {
          label: "Summary provenance",
          value: latestMacroContext ? contextProvenanceLabel(latestMacroContext.metadata) : "—",
          helper: latestMacroContext && contextSummaryError(latestMacroContext.metadata) ? "fallback reason stored" : "Narrative source for this snapshot",
        },
        {
          label: "Snapshot status",
          value: latestMacroContext ? latestMacroContext.status : "—",
          helper: latestMacroContext ? `Run ${latestMacroContext.run_id ?? "—"} · Job ${latestMacroContext.job_id ?? "—"}` : "No macro context yet",
        },
      ];
    }

    const topDriver = latestIndustryContext ? topIndustryDriver(latestIndustryContext) : null;
    return [
      {
        label: "Top industry driver",
        value: topDriver ? themeString(topDriver.label) : "—",
        helper: latestIndustryContext ? `${latestIndustryContext.industry_label} · ${formatDate(latestIndustryContext.computed_at)}` : "No industry context yet",
      },
      {
        label: "Direction",
        value: latestIndustryContext ? latestIndustryContext.direction : "—",
        helper: latestIndustryContext ? `Confidence ${latestIndustryContext.confidence_percent.toFixed(1)}%` : "No industry context yet",
      },
      {
        label: "Summary provenance",
        value: latestIndustryContext ? contextProvenanceLabel(latestIndustryContext.metadata) : "—",
        helper: latestIndustryContext && contextSummaryError(latestIndustryContext.metadata) ? "fallback reason stored" : "Narrative source for this snapshot",
      },
      {
        label: "Snapshot status",
        value: latestIndustryContext ? latestIndustryContext.status : "—",
        helper: latestIndustryContext ? `Run ${latestIndustryContext.run_id ?? "—"} · Job ${latestIndustryContext.job_id ?? "—"}` : "No industry context yet",
      },
    ];
  }, [activeTab, latestIndustryContext, latestMacroContext]);

  const activeScope = activeTab;

  return (
    <>
      <PageHeader
        kicker="Context"
        title="Context review"
        actions={
          <>
            <button type="button" className="button" onClick={() => void enqueueRefresh(activeScope)} disabled={busyAction !== null}>
              {busyAction === activeScope ? `… Queueing ${activeScope}` : `⟳ ${activeScope} context`}
            </button>
            <Link to="/data-quality" className="button-subtle">◇ Data quality</Link>
            <button type="button" className="button-subtle" onClick={() => void load()} disabled={loading || busyAction !== null}>
              ⟳ Reload
            </button>
          </>
        }
      />

      {error ? <ErrorState message={error} /> : null}
      {loading ? <LoadingState message="Loading shared context snapshots…" /> : null}

      {!loading ? (
        <div className="stack-page">
          <Card>
            <SectionTitle
              kicker="Context trust"
              title="Is the shared backdrop usable?"
              subtitle="Macro and industry context remain distinct from data-quality audits; use this page for evidence freshness and backdrop usefulness."
              actions={<HelpHint tooltip="Context review answers whether the shared macro and industry backdrop is fresh, evidence-backed, and useful for current plans. Use Data quality for bars/news/provider gaps." to={contextReviewDoc("context-review")} />}
            />
            <section className="metrics-grid top-gap-small">
              {headerMetrics.map((item) => (
                <Card key={item.label}>
                  <div className="metric-label">{item.label}</div>
                  <div className="metric-value">{item.value}</div>
                  <div className="helper-text">{item.helper}</div>
                </Card>
              ))}
            </section>
          </Card>

          <div className="top-gap-small">
            <SegmentedTabs
              value={activeTab}
              onChange={setActiveTab}
              options={[
                { value: "macro", label: "Macro" },
                { value: "industry", label: "Industry" },
              ]}
            />
          </div>

          {activeTab === "industry" && industrySummary ? (
            <DisclosureCard kicker="Industry coverage" title="Stored industry-context coverage" subtitle="Collapsed because current industry context is the decision surface; aggregate coverage is supporting evidence.">
              <section className="metrics-grid top-gap-small">
                <Card>
                  <div className="metric-label">Industry snapshots</div>
                  <div className="metric-value">{industrySummary.total_count}</div>
                  <div className="helper-text">Stored industry context rows</div>
                </Card>
                <Card>
                  <div className="metric-label">Decision-usable rate</div>
                  <div className="metric-value">{(industrySummary.decision_usable_rate_percent ?? industrySummary.usable_rate_percent).toFixed(1)}%</div>
                  <div className="helper-text">Usable quality + evidence + active drivers</div>
                </Card>
                <Card>
                  <div className="metric-label">Active-driver rate</div>
                  <div className="metric-value">{industrySummary.active_driver_rate_percent.toFixed(1)}%</div>
                  <div className="helper-text">Rows with at least one driver</div>
                </Card>
                <Card>
                  <div className="metric-label">Stale / zero-confidence</div>
                  <div className="metric-value">{industrySummary.stale_count ?? 0} / {industrySummary.zero_confidence_count}</div>
                  <div className="helper-text">Expired rows and rows that resolved to neutral</div>
                </Card>
              </section>
              {industrySummary.top_neutral_reasons && industrySummary.top_neutral_reasons.length > 0 ? (
                <div className="cluster top-gap-small">
                  {industrySummary.top_neutral_reasons.map(([reason, count]) => <Badge key={reason} tone="neutral">{reason.replace(/_/g, " ")} {count}</Badge>)}
                </div>
              ) : null}
            </DisclosureCard>
          ) : null}

          {activeTab === "macro" ? (
            <MacroContextTab snapshot={latestMacroContext} history={macroContexts} />
          ) : (
            <IndustryContextTab
              snapshot={latestIndustryContext}
              history={visibleIndustryHistory}
              industryOptions={industryOptions}
              selectedIndustryKey={selectedIndustryKey}
              onSelectIndustry={setSelectedIndustryKey}
            />
          )}
        </div>
      ) : null}
    </>
  );
}

function MacroContextTab(props: {
  snapshot: MacroContextSnapshot | null;
  history: MacroContextSnapshot[];
}) {
  const snapshot = props.snapshot;

  return (
    <div className="stack-page">
      <Card>
        <SectionTitle
          kicker="Macro context"
          title="Current macro context"
          actions={snapshot ? (
            <div className="cluster">
              <HelpHint tooltip="Review the latest macro context snapshot first when checking whether the broad market backdrop is supportive or contradictory." to={contextReviewDoc("context-review")} />
              {snapshot.id ? <Link to={`/context/macro/${snapshot.id}`} className="button-subtle">↗ Detail</Link> : null}
              {snapshot.run_id ? <Link to={`/runs/${snapshot.run_id}`} className="button-subtle">↗ Source run</Link> : null}
            </div>
          ) : <HelpHint tooltip="Review the latest macro context snapshot first when checking whether the broad market backdrop is supportive or contradictory." to={contextReviewDoc("context-review")} />}
        />
        {snapshot ? <MacroContextSummary snapshot={snapshot} /> : <EmptyState message="No macro context snapshots available yet." />}
      </Card>

      <section className="card-grid context-review-history-grid">
        <Card>
          <SectionTitle kicker="History" title="Recent macro snapshots" actions={<HelpHint tooltip="Recent macro context snapshots show how the shared backdrop changed over time." to={contextReviewDoc("history-lists")} />} />
          {props.history.length === 0 ? <EmptyState message="No macro context snapshots stored yet." /> : <MacroContextList snapshots={props.history} />}
        </Card>
      </section>
    </div>
  );
}

function IndustryContextTab(props: {
  snapshot: IndustryContextSnapshot | null;
  history: IndustryContextSnapshot[];
  industryOptions: Array<{ value: string; label: string }>;
  selectedIndustryKey: string | null;
  onSelectIndustry: (industryKey: string) => void;
}) {
  const snapshot = props.snapshot;

  return (
    <div className="stack-page">
      {props.industryOptions.length > 1 && props.selectedIndustryKey ? (
        <Card>
          <SectionTitle
            kicker="Industry selector"
            title="Choose industry"
            actions={<HelpHint tooltip="Switch between industries so the current context card and history stay tied to one sector backdrop at a time." to={contextReviewDoc("context-review")} />}
          />
          <SegmentedTabs
            value={props.selectedIndustryKey}
            onChange={props.onSelectIndustry}
            options={props.industryOptions}
          />
        </Card>
      ) : null}

      <Card>
        <SectionTitle
          kicker="Industry context"
          title="Current industry context"
          actions={snapshot ? (
            <div className="cluster">
              <HelpHint tooltip="Use industry context to check whether sector-specific transmission supports or fights the current trade ideas." to={contextReviewDoc("context-review")} />
              {snapshot.id ? <Link to={`/context/industry/${snapshot.id}`} className="button-subtle">↗ Detail</Link> : null}
              {snapshot.run_id ? <Link to={`/runs/${snapshot.run_id}`} className="button-subtle">↗ Source run</Link> : null}
            </div>
          ) : <HelpHint tooltip="Use industry context to check whether sector-specific transmission supports or fights the current trade ideas." to={contextReviewDoc("context-review")} />}
        />
        {snapshot ? <IndustryContextSummary snapshot={snapshot} /> : <EmptyState message="No industry context snapshots available yet." />}
      </Card>

      <section className="card-grid context-review-history-grid">
        <Card>
          <SectionTitle kicker="History" title="Recent industry snapshots" actions={<HelpHint tooltip="Recent industry context snapshots help you see whether the sector backdrop is stable, shifting, or degraded." to={contextReviewDoc("history-lists")} />} />
          {props.history.length === 0 ? <EmptyState message="No industry context snapshots stored yet." /> : <IndustryContextList snapshots={props.history} />}
        </Card>
      </section>
    </div>
  );
}

function IndustryContextList({ snapshots }: { snapshots: IndustryContextSnapshot[] }) {
  return (
    <ul className="list-reset">
      {snapshots.map((snapshot) => {
        const topDriver = topIndustryDriver(snapshot);
        return (
          <li key={snapshot.id ?? `${snapshot.industry_key}-${snapshot.computed_at}`} className="list-item">
            <div className="card-headline">
              <div>
                <ContextScoreSummary
                  confidence={snapshot.confidence_percent}
                  saliency={snapshot.saliency_score}
                  coverage={snapshot.active_drivers.length}
                  freshness={formatDate(snapshot.computed_at)}
                  tone={contextSnapshotTone(snapshot)}
                />
                <div className="top-gap-small">
                  <div className="cluster">
                    <Badge tone={contextSnapshotTone(snapshot)}>status {snapshot.status}</Badge>
                    <Badge tone={contextBreakdownValue(snapshot, "context_quality_status") === "usable" ? "ok" : "warning"}>quality {contextBreakdownValue(snapshot, "context_quality_status")}</Badge>
                    <Badge tone="neutral">evidence {contextBreakdownValue(snapshot, "evidence_state")}</Badge>
                    <Badge tone="neutral">coverage {contextBreakdownValue(snapshot, "coverage_state")}</Badge>
                    <Badge tone="neutral">industry {snapshot.industry_label || snapshot.industry_key}</Badge>
                    {topDriver ? <Badge tone="neutral">driver {themeString(topDriver.label)}</Badge> : <Badge tone="warning">{industryNeutralReason(snapshot)}</Badge>}
                  </div>
                </div>
                <div className="helper-text context-inline-metrics"><span className="context-inline-metric"><strong>Direction:</strong> {snapshot.direction}</span><span className="context-inline-metric"><strong>Computed:</strong> {formatDate(snapshot.computed_at)}</span></div>
                {topDriver ? (
                  <div className="cluster top-gap-small">
                    <Badge tone={contextInterpretationTone(topDriver.state_transition)}>state {themeString(topDriver.state_transition)}</Badge>
                    <Badge tone={contextInterpretationTone(topDriver.market_interpretation)}>read {themeString(topDriver.market_interpretation)}</Badge>
                    {themeString(topDriver.trigger_actor) !== "—" ? <Badge tone="neutral">actor {themeString(topDriver.trigger_actor)}</Badge> : null}
                  </div>
                ) : null}
                {snapshot.summary_text ? <div className="helper-text top-gap-small">{snapshot.summary_text}</div> : null}
                <WarningSummary warnings={snapshot.warnings} />
                {contextSummaryError(snapshot.metadata) ? <div className="helper-text top-gap-small">{contextSummaryError(snapshot.metadata)}</div> : null}
              </div>
              <div className="cluster">
                {snapshot.id ? <Link to={`/context/industry/${snapshot.id}`} className="button-subtle">↗ Detail</Link> : null}
                {snapshot.run_id ? <Link to={`/runs/${snapshot.run_id}`} className="button-subtle">↗ Run</Link> : null}
              </div>
            </div>
          </li>
        );
      })}
    </ul>
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
                <ContextScoreSummary
                  confidence={snapshot.confidence_percent}
                  saliency={snapshot.saliency_score}
                  coverage={snapshot.active_themes.length}
                  coverageLabel="Themes"
                  coverageTooltip="Number of active macro themes selected for the snapshot."
                  freshness={formatDate(snapshot.computed_at)}
                  tone={contextSnapshotTone(snapshot)}
                />
                <div className="top-gap-small">
                  <div className="cluster">
                    <Badge tone={contextSnapshotTone(snapshot)}>status {snapshot.status}</Badge>
                    {topTheme ? <Badge tone="neutral">theme {themeString(topTheme.label)}</Badge> : null}
                  </div>
                </div>
                {topTheme ? (
                  <div className="cluster top-gap-small">
                    <Badge tone={contextInterpretationTone(topTheme.state_transition)}>state {themeString(topTheme.state_transition)}</Badge>
                    <Badge tone={contextInterpretationTone(topTheme.market_interpretation)}>read {themeString(topTheme.market_interpretation)}</Badge>
                    {themeString(topTheme.trigger_actor) !== "—" ? <Badge tone="neutral">actor {themeString(topTheme.trigger_actor)}</Badge> : null}
                  </div>
                ) : null}
                {snapshot.summary_text ? <div className="helper-text top-gap-small">{snapshot.summary_text}</div> : null}
                <WarningSummary warnings={snapshot.warnings} />
                {contextSummaryError(snapshot.metadata) ? <div className="helper-text top-gap-small">{contextSummaryError(snapshot.metadata)}</div> : null}
              </div>
              <div className="cluster">
                {snapshot.id ? <Link to={`/context/macro/${snapshot.id}`} className="button-subtle">↗ Detail</Link> : null}
                {snapshot.run_id ? <Link to={`/runs/${snapshot.run_id}`} className="button-subtle">↗ Run</Link> : null}
              </div>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function IndustryContextSummary({ snapshot }: { snapshot: IndustryContextSnapshot }) {
  const topDriver = topIndustryDriver(snapshot);
  const linkedMacroThemes = snapshot.linked_macro_themes.slice(0, 6);
  const linkedIndustryThemes = snapshot.linked_industry_themes.slice(0, 6);
  const drivers = snapshot.active_drivers.slice(0, 4);

  return (
    <div className="stack-page top-gap-small">
      <ContextScoreSummary
        confidence={snapshot.confidence_percent}
        saliency={snapshot.saliency_score}
        coverage={snapshot.active_drivers.length}
        freshness={formatDate(snapshot.computed_at)}
        tone={contextSnapshotTone(snapshot)}
      />
      <div className="top-gap-small">
        <div className="cluster">
          <Badge tone={contextSnapshotTone(snapshot)}>status {snapshot.status}</Badge>
          <Badge tone={contextBreakdownValue(snapshot, "context_quality_status") === "usable" ? "ok" : "warning"}>quality {contextBreakdownValue(snapshot, "context_quality_status")}</Badge>
          <Badge tone="neutral">evidence {contextBreakdownValue(snapshot, "evidence_state")}</Badge>
          <Badge tone="neutral">coverage {contextBreakdownValue(snapshot, "coverage_state")}</Badge>
          <Badge tone="neutral">industry {snapshot.industry_label || snapshot.industry_key}</Badge>
          <Badge tone="neutral">direction {snapshot.direction || "—"}</Badge>
          {snapshot.warnings.length > 0 ? <Badge tone="warning">warnings {snapshot.warnings.length}</Badge> : null}
          {snapshot.missing_inputs.length > 0 ? <Badge tone="warning">missing {snapshot.missing_inputs.length}</Badge> : null}
        </div>
      </div>
      <div className="top-gap-small">
        <ProvenanceStrip method={contextSummaryMethod(snapshot.metadata)} backend={contextSummaryBackend(snapshot.metadata)} model={contextSummaryModel(snapshot.metadata)} error={contextSummaryError(snapshot.metadata)} />
      </div>

      {snapshot.summary_text ? (
        <div className="summary-text-block">
          <p>{snapshot.summary_text}</p>
        </div>
      ) : null}

      <div className="data-points">
        <div className="data-point"><span className="data-point-label">Top driver</span><span className="data-point-value">{topDriver ? themeString(topDriver.label) : "—"}</span></div>
        <div className="data-point"><span className="data-point-label">Window</span><span className="data-point-value">{topDriver ? detailLabel(topDriver.window_hint_detail, topDriver.window_hint) : "—"}</span></div>
        <div className="data-point"><span className="data-point-label">Source quality</span><span className="data-point-value">{topDriver ? detailLabel(topDriver.source_priority_detail, topDriver.source_priority) : "—"}</span></div>
        <div className="data-point"><span className="data-point-label">Saliency</span><span className="data-point-value">{snapshot.saliency_score.toFixed(2)}</span></div>
        <div className="data-point"><span className="data-point-label">Computed</span><span className="data-point-value">{formatDate(snapshot.computed_at)}</span></div>
        <div className="data-point"><span className="data-point-label">Run / job</span><span className="data-point-value">{snapshot.run_id ?? "—"} / {snapshot.job_id ?? "—"}</span></div>
      </div>

      <div className="context-review-main-grid">
        <DisclosureCard title="Active drivers" subtitle="Driver detail stays available without dominating the summary." defaultOpen>
          {drivers.length > 0 ? (
            <div className="data-stack">
              {drivers.map((driver, index) => {
                const channels = extractDisplayLabels(driver, "transmission_channel_details", "transmission_channels").slice(0, 4);
                return (
                  <ContextEventSummary
                    key={`${themeString(driver.label)}-${index}`}
                    label={`Driver ${index + 1}`}
                    value={themeString(driver.label)}
                    details={[
                      { label: "Window", value: detailLabel(driver.window_hint_detail, driver.window_hint) },
                      { label: "State", value: themeString(driver.state_transition) },
                      { label: "Catalyst", value: themeString(driver.catalyst_type) },
                      { label: "Read", value: themeString(driver.market_interpretation) },
                      { label: "Source", value: detailLabel(driver.source_priority_detail, driver.source_priority) },
                    ]}
                    channels={channels}
                  />
                );
              })}
            </div>
          ) : (
            <EmptyState message="No active drivers stored for this industry snapshot." />
          )}
        </DisclosureCard>

        <DisclosureCard title="Theme links and caveats" subtitle="Secondary links are collapsed until needed.">
          {linkedMacroThemes.length > 0 ? (
            <div>
              <div className="section-heading"><strong>Linked macro themes</strong></div>
              <div className="cluster">{linkedMacroThemes.map((theme) => <Badge key={theme}>{theme}</Badge>)}</div>
            </div>
          ) : null}
          {linkedIndustryThemes.length > 0 ? (
            <div className="top-gap-small">
              <div className="section-heading"><strong>Industry-native themes</strong></div>
              <div className="cluster">{linkedIndustryThemes.map((theme) => <Badge key={theme}>{theme}</Badge>)}</div>
            </div>
          ) : null}
          <WarningSummary warnings={snapshot.warnings} />
          {snapshot.missing_inputs.length > 0 ? (
            <div className="top-gap-small">
              <div className="section-heading"><strong>Missing inputs</strong></div>
              <ul className="list-reset">{snapshot.missing_inputs.map((item) => <li key={item} className="list-item compact-item">{item}</li>)}</ul>
            </div>
          ) : null}
          {contextSummaryError(snapshot.metadata) ? <div className="helper-text top-gap-small">Summary fallback reason: {contextSummaryError(snapshot.metadata)}</div> : null}
        </DisclosureCard>
      </div>
    </div>
  );
}

function MacroContextSummary({ snapshot }: { snapshot: MacroContextSnapshot }) {
  const topTheme = topMacroTheme(snapshot);
  const topChannels = stringList(topTheme?.transmission_channels).slice(0, 6);
  const contradictory = contradictoryMacroThemes(snapshot);
  const themes = snapshot.active_themes.slice(0, 4);

  return (
    <div className="stack-page top-gap-small">
      <ContextScoreSummary
        confidence={snapshot.confidence_percent}
        saliency={snapshot.saliency_score}
        coverage={snapshot.active_themes.length}
        coverageLabel="Themes"
        coverageTooltip="Number of active macro themes selected for the snapshot."
        freshness={formatDate(snapshot.computed_at)}
        tone={contextSnapshotTone(snapshot)}
      />
      <div className="top-gap-small">
        <div className="cluster">
          <Badge tone={contextSnapshotTone(snapshot)}>status {snapshot.status}</Badge>
          {topTheme ? <Badge tone="neutral">theme {themeString(topTheme.label)}</Badge> : null}
          {snapshot.warnings.length > 0 ? <Badge tone="warning">warnings {snapshot.warnings.length}</Badge> : null}
          {snapshot.missing_inputs.length > 0 ? <Badge tone="warning">missing {snapshot.missing_inputs.length}</Badge> : null}
        </div>
      </div>
      <div className="top-gap-small">
        <ProvenanceStrip method={contextSummaryMethod(snapshot.metadata)} backend={contextSummaryBackend(snapshot.metadata)} model={contextSummaryModel(snapshot.metadata)} error={contextSummaryError(snapshot.metadata)} />
      </div>

      {snapshot.summary_text ? (
        <div className="summary-text-block">
          <p>{snapshot.summary_text}</p>
        </div>
      ) : null}

      <div className="data-points">
        <div className="data-point"><span className="data-point-label">Top event</span><span className="data-point-value">{topTheme ? themeString(topTheme.label) : "—"}</span></div>
        <div className="data-point"><span className="data-point-label">State</span><span className="data-point-value">{topTheme ? detailLabel(topTheme.persistence_state_detail, topTheme.persistence_state) : "—"}</span></div>
        <div className="data-point"><span className="data-point-label">Window</span><span className="data-point-value">{topTheme ? detailLabel(topTheme.window_hint_detail, topTheme.window_hint) : "—"}</span></div>
        <div className="data-point"><span className="data-point-label">Primary news items</span><span className="data-point-value">{String(snapshot.source_breakdown?.primary_news_item_count ?? 0)}</span></div>
        <div className="data-point"><span className="data-point-label">Source quality</span><span className="data-point-value">{topTheme ? detailLabel(topTheme.source_priority_detail, topTheme.source_priority) : "—"}</span></div>
        <div className="data-point"><span className="data-point-label">Computed</span><span className="data-point-value">{formatDate(snapshot.computed_at)}</span></div>
        <div className="data-point"><span className="data-point-label">Run / job</span><span className="data-point-value">{snapshot.run_id ?? "—"} / {snapshot.job_id ?? "—"}</span></div>
      </div>

      <div className="context-review-main-grid">
        <DisclosureCard title="Active themes" subtitle="Theme detail stays collapsible to reduce list fatigue on mobile." defaultOpen>
          {themes.length > 0 ? (
            <div className="data-stack">
              {themes.map((theme, index) => {
                const channels = extractDisplayLabels(theme, "transmission_channel_details", "transmission_channels").slice(0, 4);
                return (
                  <ContextEventSummary
                    key={`${themeString(theme.label)}-${index}`}
                    label={`Theme ${index + 1}`}
                    value={themeString(theme.label)}
                    details={[
                      { label: "Persistence", value: detailLabel(theme.persistence_state_detail, theme.persistence_state) },
                      { label: "Transition", value: themeString(theme.state_transition) },
                      { label: "Catalyst", value: themeString(theme.catalyst_type) },
                      { label: "Read", value: themeString(theme.market_interpretation) },
                      { label: "Window", value: detailLabel(theme.window_hint_detail, theme.window_hint) },
                      { label: "Source", value: detailLabel(theme.source_priority_detail, theme.source_priority) },
                    ]}
                    channels={channels}
                  />
                );
              })}
            </div>
          ) : (
            <EmptyState message="No active macro themes stored yet." />
          )}
        </DisclosureCard>

        <DisclosureCard title="Transmission and caveats" subtitle="Secondary transmission notes remain available without filling the first screen.">
          {topChannels.length > 0 ? (
            <div>
              <div className="section-heading"><strong>Main transmission channels</strong></div>
              <div className="cluster">{topChannels.map((channel) => <Badge key={channel}>{channel}</Badge>)}</div>
            </div>
          ) : null}
          {snapshot.regime_tags.length > 0 ? (
            <div className="top-gap-small">
              <div className="section-heading"><strong>Regime tags</strong></div>
              <div className="cluster">{snapshot.regime_tags.map((tag) => <Badge key={tag}>{tag}</Badge>)}</div>
            </div>
          ) : null}
          {contradictory.length > 0 ? (
            <div className="top-gap-small">
              <div className="section-heading"><strong>Contradictions</strong></div>
              <div className="helper-text">{contradictory.join(" · ")}</div>
            </div>
          ) : null}
          <WarningSummary warnings={snapshot.warnings} />
          {snapshot.missing_inputs.length > 0 ? (
            <div className="top-gap-small">
              <div className="section-heading"><strong>Missing inputs</strong></div>
              <ul className="list-reset">{snapshot.missing_inputs.map((item) => <li key={item} className="list-item compact-item">{item}</li>)}</ul>
            </div>
          ) : null}
          {contextSummaryError(snapshot.metadata) ? <div className="helper-text top-gap-small">Summary fallback reason: {contextSummaryError(snapshot.metadata)}</div> : null}
        </DisclosureCard>
      </div>
    </div>
  );
}
