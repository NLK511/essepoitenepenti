import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { getJson, postForm } from "../api";
import { useToast } from "../components/toast";
import { Badge, Card, EmptyState, ErrorState, HelpHint, LoadingState, PageHeader, SectionTitle, SegmentedTabs } from "../components/ui";
import type { ContextEventRow, IndustryContextSnapshot, MacroContextSnapshot, Run } from "../types";
import { extractDisplayLabels, formatDate } from "../utils";

function contextTone(snapshot: { status: string; warnings: string[] }): "ok" | "warning" | "danger" | "neutral" {
  if (snapshot.status === "failed") {
    return "danger";
  }
  if (snapshot.warnings.length > 0 || snapshot.status === "warning") {
    return "warning";
  }
  return "ok";
}

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

function summaryMethod(snapshot: { metadata?: Record<string, unknown> }): string {
  return typeof snapshot.metadata?.context_summary_method === "string" ? snapshot.metadata.context_summary_method : "unknown";
}

function summaryBackend(snapshot: { metadata?: Record<string, unknown> }): string {
  return typeof snapshot.metadata?.context_summary_backend === "string" ? snapshot.metadata.context_summary_backend : "—";
}

function summaryModel(snapshot: { metadata?: Record<string, unknown> }): string {
  return typeof snapshot.metadata?.context_summary_model === "string" ? snapshot.metadata.context_summary_model : "—";
}

function summaryError(snapshot: { metadata?: Record<string, unknown> }): string | null {
  return typeof snapshot.metadata?.context_summary_error === "string" ? snapshot.metadata.context_summary_error : null;
}

function provenanceTone(snapshot: { metadata?: Record<string, unknown> }): "ok" | "warning" | "neutral" {
  if (summaryError(snapshot)) {
    return "warning";
  }
  if (summaryMethod(snapshot) === "llm_summary") {
    return "ok";
  }
  return "neutral";
}

function provenanceLabel(snapshot: { metadata?: Record<string, unknown> }): string {
  const method = summaryMethod(snapshot);
  if (method === "llm_summary") {
    return `LLM · ${summaryBackend(snapshot)}${summaryModel(snapshot) !== "—" ? ` · ${summaryModel(snapshot)}` : ""}`;
  }
  return `fallback · ${summaryBackend(snapshot)}`;
}

function contradictoryMacroThemes(snapshot: MacroContextSnapshot): string[] {
  return stringList(snapshot.metadata?.contradictory_event_labels);
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

function LabeledBadge(props: {
  label: string;
  value: string;
  tone?: "ok" | "warning" | "danger" | "neutral" | "info";
}) {
  return (
    <Badge tone={props.tone}>
      <span className="context-badge-label">{props.label}</span>
      <span className="context-badge-value">{props.value}</span>
    </Badge>
  );
}

function InlineMetric(props: { label: string; value: string }) {
  return (
    <span className="context-inline-metric">
      <strong>{props.label}:</strong> {props.value}
    </span>
  );
}

export function ContextReviewPage() {
  const { showToast } = useToast();
  const [macroContexts, setMacroContexts] = useState<MacroContextSnapshot[]>([]);
  const [industryContexts, setIndustryContexts] = useState<IndustryContextSnapshot[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyAction, setBusyAction] = useState<"macro" | "industry" | null>(null);
  const [activeTab, setActiveTab] = useState<"macro" | "industry">("macro");

  async function load() {
    try {
      setLoading(true);
      setError(null);
      const [macroContextResponse, industryContextResponse] = await Promise.all([
        getJson<MacroContextSnapshot[]>("/api/context/macro?limit=6"),
        getJson<IndustryContextSnapshot[]>("/api/context/industry?limit=24"),
      ]);
      setMacroContexts(macroContextResponse);
      setIndustryContexts(industryContextResponse);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to load context review data");
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
      const run = await postForm<Run>(`/api/support-snapshots/refresh/${scope}`, {});
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
      return;
    }
    if (!selectedIndustryKey || !latestIndustryByKey.has(selectedIndustryKey)) {
      setSelectedIndustryKey(industryOptions[0]?.value ?? null);
    }
  }, [industryOptions, latestIndustryByKey, selectedIndustryKey]);

  const latestIndustryContext = selectedIndustryKey ? latestIndustryByKey.get(selectedIndustryKey) ?? null : industryContexts[0] ?? null;
  const visibleIndustryHistory = selectedIndustryKey
    ? industryContexts.filter((snapshot) => snapshot.industry_key === selectedIndustryKey)
    : industryContexts;

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
          value: latestMacroContext ? provenanceLabel(latestMacroContext) : "—",
          helper: latestMacroContext && summaryError(latestMacroContext) ? "fallback reason stored" : "Narrative source for this snapshot",
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
        value: latestIndustryContext ? provenanceLabel(latestIndustryContext) : "—",
        helper: latestIndustryContext && summaryError(latestIndustryContext) ? "fallback reason stored" : "Narrative source for this snapshot",
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
        kicker="Shared context"
        title="Context review"
        subtitle="Review macro and industry context in dedicated tabs, with the latest context snapshots shown first so shared backdrop changes are easier to inspect."
        actions={
          <>
            <button type="button" className="button" onClick={() => void enqueueRefresh(activeScope)} disabled={busyAction !== null}>
              {busyAction === activeScope ? `Queueing ${activeScope} refresh…` : `Refresh ${activeScope} context`}
            </button>
            <button type="button" className="button-subtle" onClick={() => void load()} disabled={loading || busyAction !== null}>
              Reload
            </button>
          </>
        }
      />

      {error ? <ErrorState message={error} /> : null}
      {loading ? <LoadingState message="Loading shared context snapshots…" /> : null}

      {!loading ? (
        <div className="stack-page">
          <section className="metrics-grid">
            {headerMetrics.map((item) => (
              <Card key={item.label}>
                <div className="metric-label">{item.label}</div>
                <div className="metric-value">{item.value}</div>
                <div className="helper-text">{item.helper}</div>
              </Card>
            ))}
          </section>

          <Card>
            <SectionTitle title="Choose context scope" actions={<HelpHint tooltip="Switch between macro and industry review so one shared context layer stays in focus at a time." to={contextReviewDoc("context-review")} />} />
            <SegmentedTabs
              value={activeTab}
              onChange={setActiveTab}
              options={[
                { value: "macro", label: "Macro" },
                { value: "industry", label: "Industry" },
              ]}
            />
          </Card>

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
              {snapshot.id ? <Link to={`/context/macro/${snapshot.id}`} className="button-subtle">Open context detail</Link> : null}
              {snapshot.run_id ? <Link to={`/runs/${snapshot.run_id}`} className="button-subtle">Open source run</Link> : null}
            </div>
          ) : <HelpHint tooltip="Review the latest macro context snapshot first when checking whether the broad market backdrop is supportive or contradictory." to={contextReviewDoc("context-review")} />}
        />
        {snapshot ? <MacroContextSummary snapshot={snapshot} /> : <EmptyState message="No macro context snapshots available yet." />}
      </Card>

      <section className="card-grid context-review-history-grid">
        <Card>
          <SectionTitle kicker="Macro context history" title="Recent macro context snapshots" actions={<HelpHint tooltip="Recent macro context snapshots show how the shared backdrop changed over time." to={contextReviewDoc("history-lists")} />} />
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
              {snapshot.id ? <Link to={`/context/industry/${snapshot.id}`} className="button-subtle">Open context detail</Link> : null}
              {snapshot.run_id ? <Link to={`/runs/${snapshot.run_id}`} className="button-subtle">Open source run</Link> : null}
            </div>
          ) : <HelpHint tooltip="Use industry context to check whether sector-specific transmission supports or fights the current trade ideas." to={contextReviewDoc("context-review")} />}
        />
        {snapshot ? <IndustryContextSummary snapshot={snapshot} /> : <EmptyState message="No industry context snapshots available yet." />}
      </Card>

      <section className="card-grid context-review-history-grid">
        <Card>
          <SectionTitle kicker="Industry context history" title="Recent industry context snapshots" actions={<HelpHint tooltip="Recent industry context snapshots help you see whether the sector backdrop is stable, shifting, or degraded." to={contextReviewDoc("history-lists")} />} />
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
                <div className="cluster">
                  <Badge tone="info">industry context</Badge>
                  <LabeledBadge tone={contextTone(snapshot)} label="status" value={snapshot.status} />
                  <LabeledBadge label="industry" value={snapshot.industry_label || snapshot.industry_key} />
                  {topDriver ? <LabeledBadge label="driver" value={themeString(topDriver.label)} /> : null}
                  <LabeledBadge tone={provenanceTone(snapshot)} label="summary" value={provenanceLabel(snapshot)} />
                </div>
                <div className="helper-text context-inline-metrics"><InlineMetric label="Direction" value={snapshot.direction} /><InlineMetric label="Saliency" value={snapshot.saliency_score.toFixed(2)} /><InlineMetric label="Confidence" value={`${snapshot.confidence_percent.toFixed(1)}%`} /><InlineMetric label="Computed" value={formatDate(snapshot.computed_at)} /></div>
                {snapshot.summary_text ? <div className="helper-text top-gap-small">{snapshot.summary_text}</div> : null}
                {summaryError(snapshot) ? <div className="helper-text top-gap-small">{summaryError(snapshot)}</div> : null}
              </div>
              <div className="cluster">
                {snapshot.id ? <Link to={`/context/industry/${snapshot.id}`} className="button-subtle">Open detail</Link> : null}
                {snapshot.run_id ? <Link to={`/runs/${snapshot.run_id}`} className="button-subtle">Open run</Link> : null}
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
                <div className="cluster">
                  <Badge tone="info">macro context</Badge>
                  <LabeledBadge tone={contextTone(snapshot)} label="status" value={snapshot.status} />
                  {topTheme ? <LabeledBadge label="theme" value={themeString(topTheme.label)} /> : null}
                  <LabeledBadge tone={provenanceTone(snapshot)} label="summary" value={provenanceLabel(snapshot)} />
                </div>
                <div className="helper-text context-inline-metrics"><InlineMetric label="Saliency" value={snapshot.saliency_score.toFixed(2)} /><InlineMetric label="Confidence" value={`${snapshot.confidence_percent.toFixed(1)}%`} /><InlineMetric label="Computed" value={formatDate(snapshot.computed_at)} /></div>
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

function IndustryContextSummary({ snapshot }: { snapshot: IndustryContextSnapshot }) {
  const topDriver = topIndustryDriver(snapshot);
  const linkedMacroThemes = snapshot.linked_macro_themes.slice(0, 6);
  const linkedIndustryThemes = snapshot.linked_industry_themes.slice(0, 6);
  const drivers = snapshot.active_drivers.slice(0, 4);

  return (
    <div className="stack-page top-gap-small">
      <div className="cluster">
        <Badge tone="info">industry context</Badge>
        <LabeledBadge tone={contextTone(snapshot)} label="status" value={snapshot.status} />
        <LabeledBadge label="industry" value={snapshot.industry_label || snapshot.industry_key} />
        <LabeledBadge tone="neutral" label="direction" value={snapshot.direction || "—"} />
        <LabeledBadge tone="neutral" label="confidence" value={`${snapshot.confidence_percent.toFixed(1)}%`} />
        <LabeledBadge tone={provenanceTone(snapshot)} label="summary" value={provenanceLabel(snapshot)} />
        {snapshot.warnings.length > 0 ? <LabeledBadge tone="warning" label="warnings" value={String(snapshot.warnings.length)} /> : null}
        {snapshot.missing_inputs.length > 0 ? <LabeledBadge tone="warning" label="missing" value={String(snapshot.missing_inputs.length)} /> : null}
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
        <div className="data-card">
          <div className="data-card-header">
            <div>
              <h3 className="data-card-title">Active drivers</h3>
            </div>
          </div>
          {drivers.length > 0 ? (
            <div className="data-stack">
              {drivers.map((driver, index) => {
                const channels = extractDisplayLabels(driver, "transmission_channel_details", "transmission_channels").slice(0, 4);
                return (
                  <div key={`${themeString(driver.label)}-${index}`} className="data-point">
                    <span className="data-point-label">Driver {index + 1}</span>
                    <span className="data-point-value">{themeString(driver.label)}</span>
                    <div className="helper-text top-gap-small context-inline-metrics">
                      <InlineMetric label="Window" value={detailLabel(driver.window_hint_detail, driver.window_hint)} />
                      <InlineMetric label="Source" value={detailLabel(driver.source_priority_detail, driver.source_priority)} />
                    </div>
                    {channels.length > 0 ? <div className="helper-text context-inline-metrics"><InlineMetric label="Channels" value={channels.join(" · ")} /></div> : null}
                  </div>
                );
              })}
            </div>
          ) : (
            <EmptyState message="No active drivers stored for this industry snapshot." />
          )}
        </div>

        <div className="data-card">
          <div className="data-card-header">
            <div>
              <h3 className="data-card-title">Theme links and caveats</h3>
            </div>
          </div>
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
          {snapshot.warnings.length > 0 ? (
            <div className="top-gap-small">
              <div className="section-heading"><strong>Warnings</strong></div>
              <ul className="list-reset">{snapshot.warnings.map((warning) => <li key={warning} className="list-item compact-item">{warning}</li>)}</ul>
            </div>
          ) : null}
          {snapshot.missing_inputs.length > 0 ? (
            <div className="top-gap-small">
              <div className="section-heading"><strong>Missing inputs</strong></div>
              <ul className="list-reset">{snapshot.missing_inputs.map((item) => <li key={item} className="list-item compact-item">{item}</li>)}</ul>
            </div>
          ) : null}
          {summaryError(snapshot) ? <div className="helper-text top-gap-small">Summary fallback reason: {summaryError(snapshot)}</div> : null}
        </div>
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
      <div className="cluster">
        <Badge tone="info">macro context</Badge>
        <LabeledBadge tone={contextTone(snapshot)} label="status" value={snapshot.status} />
        {topTheme ? <LabeledBadge label="theme" value={themeString(topTheme.label)} /> : null}
        <LabeledBadge tone="neutral" label="confidence" value={`${snapshot.confidence_percent.toFixed(1)}%`} />
        <LabeledBadge tone="neutral" label="saliency" value={snapshot.saliency_score.toFixed(2)} />
        <LabeledBadge tone={provenanceTone(snapshot)} label="summary" value={provenanceLabel(snapshot)} />
        {snapshot.warnings.length > 0 ? <LabeledBadge tone="warning" label="warnings" value={String(snapshot.warnings.length)} /> : null}
        {snapshot.missing_inputs.length > 0 ? <LabeledBadge tone="warning" label="missing" value={String(snapshot.missing_inputs.length)} /> : null}
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
        <div className="data-point"><span className="data-point-label">Source quality</span><span className="data-point-value">{topTheme ? detailLabel(topTheme.source_priority_detail, topTheme.source_priority) : "—"}</span></div>
        <div className="data-point"><span className="data-point-label">Computed</span><span className="data-point-value">{formatDate(snapshot.computed_at)}</span></div>
        <div className="data-point"><span className="data-point-label">Run / job</span><span className="data-point-value">{snapshot.run_id ?? "—"} / {snapshot.job_id ?? "—"}</span></div>
      </div>

      <div className="context-review-main-grid">
        <div className="data-card">
          <div className="data-card-header">
            <div>
              <h3 className="data-card-title">Active themes</h3>
            </div>
          </div>
          {themes.length > 0 ? (
            <div className="data-stack">
              {themes.map((theme, index) => {
                const channels = extractDisplayLabels(theme, "transmission_channel_details", "transmission_channels").slice(0, 4);
                return (
                  <div key={`${themeString(theme.label)}-${index}`} className="data-point">
                    <span className="data-point-label">Theme {index + 1}</span>
                    <span className="data-point-value">{themeString(theme.label)}</span>
                    <div className="helper-text top-gap-small context-inline-metrics">
                      <InlineMetric label="State" value={detailLabel(theme.persistence_state_detail, theme.persistence_state)} />
                      <InlineMetric label="Window" value={detailLabel(theme.window_hint_detail, theme.window_hint)} />
                    </div>
                    <div className="helper-text context-inline-metrics"><InlineMetric label="Source" value={detailLabel(theme.source_priority_detail, theme.source_priority)} /></div>
                    {channels.length > 0 ? <div className="helper-text context-inline-metrics"><InlineMetric label="Channels" value={channels.join(" · ")} /></div> : null}
                  </div>
                );
              })}
            </div>
          ) : (
            <EmptyState message="No active macro themes stored yet." />
          )}
        </div>

        <div className="data-card">
          <div className="data-card-header">
            <div>
              <h3 className="data-card-title">Transmission and caveats</h3>
            </div>
          </div>
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
          {snapshot.warnings.length > 0 ? (
            <div className="top-gap-small">
              <div className="section-heading"><strong>Warnings</strong></div>
              <ul className="list-reset">{snapshot.warnings.map((warning) => <li key={warning} className="list-item compact-item">{warning}</li>)}</ul>
            </div>
          ) : null}
          {snapshot.missing_inputs.length > 0 ? (
            <div className="top-gap-small">
              <div className="section-heading"><strong>Missing inputs</strong></div>
              <ul className="list-reset">{snapshot.missing_inputs.map((item) => <li key={item} className="list-item compact-item">{item}</li>)}</ul>
            </div>
          ) : null}
          {summaryError(snapshot) ? <div className="helper-text top-gap-small">Summary fallback reason: {summaryError(snapshot)}</div> : null}
        </div>
      </div>
    </div>
  );
}
