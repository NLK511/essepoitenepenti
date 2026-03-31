import { Badge, Card, EmptyState, SectionTitle } from "./ui";
import type { JobType } from "../types";
import { formatDate, jobTypeLabel, parseJsonForDisplay, parseJsonRecord } from "../utils";

function renderLabel(key: string): string {
  return key
    .split("_")
    .join(" ")
    .split(" ")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function metadataTone(value: unknown): "ok" | "warning" | "danger" | "neutral" {
  if (typeof value === "boolean") {
    return value ? "ok" : "neutral";
  }
  return "neutral";
}

function MetadataValue({ label, value }: { label: string; value: unknown }) {
  if (value === null || value === undefined || value === "") {
    return (
      <div className="summary-item">
        <span className="summary-label">{label}</span>
        <span className="summary-value">—</span>
      </div>
    );
  }
  if (typeof value === "boolean") {
    return (
      <div className="summary-item">
        <span className="summary-label">{label}</span>
        <Badge tone={metadataTone(value)}>{value ? "yes" : "no"}</Badge>
      </div>
    );
  }
  if (typeof value === "number" || typeof value === "string") {
    const longText = typeof value === "string" && (value.length > 120 || label.toLowerCase().includes("output") || label.toLowerCase().includes("stderr") || label.toLowerCase().includes("stdout"));
    return (
      <div className="summary-item">
        <span className="summary-label">{label}</span>
        {longText ? <pre>{value}</pre> : <span className="summary-value">{String(value)}</span>}
      </div>
    );
  }
  if (Array.isArray(value)) {
    return (
      <div className="summary-item">
        <span className="summary-label">{label}</span>
        <pre>{JSON.stringify(value, null, 2)}</pre>
      </div>
    );
  }
  return (
    <div className="summary-item">
      <span className="summary-label">{label}</span>
      <MetadataObject value={value as Record<string, unknown>} />
    </div>
  );
}

function MetadataObject({ value }: { value: Record<string, unknown> }) {
  const entries = Object.entries(value);
  const simpleEntries = entries.filter(([, item]) => !isRecord(item));
  const nestedEntries = entries.filter((entry): entry is [string, Record<string, unknown>] => isRecord(entry[1]));

  return (
    <div className="stack-page">
      {simpleEntries.length > 0 ? (
        <div className="summary-grid">
          {simpleEntries.map(([key, item]) => <MetadataValue key={key} label={renderLabel(key)} value={item} />)}
        </div>
      ) : null}
      {nestedEntries.map(([key, item]) => (
        <details key={key} open>
          <summary>{renderLabel(key)}</summary>
          <MetadataObject value={item} />
        </details>
      ))}
    </div>
  );
}

function RawJson({ title, value }: { title: string; value: string | null }) {
  if (!value) {
    return null;
  }
  return (
    <details>
      <summary>{title}</summary>
      <pre>{parseJsonForDisplay(value)}</pre>
    </details>
  );
}

function FingerprintCard({ title, value }: { title: string; value: Record<string, unknown> | null }) {
  if (!value) {
    return null;
  }
  return (
    <Card>
      <SectionTitle title={title} />
      <MetadataObject value={value} />
    </Card>
  );
}

function EvaluationResultView({ summary, artifact, rawSummary, rawArtifact }: {
  summary: Record<string, unknown> | null;
  artifact: Record<string, unknown> | null;
  rawSummary: string | null;
  rawArtifact: string | null;
}) {
  const scope = (summary?.scope ?? artifact?.scope) as Record<string, unknown> | undefined;
  const trigger = (summary?.trigger ?? artifact?.trigger) as Record<string, unknown> | undefined;
  const output = typeof summary?.output === "string" ? summary.output : null;

  return (
    <div className="stack-page">
      <Card>
        <SectionTitle kicker="Evaluation summary" title="Outcome" subtitle="Evaluation workflows settle recommendation-plan outcomes and record summary counts on the run." />
        <div className="summary-grid">
          <div className="summary-item"><span className="summary-label">Plans evaluated</span><span className="summary-value">{String(summary?.evaluated_recommendation_plans ?? "—")}</span></div>
          <div className="summary-item"><span className="summary-label">Plan outcomes synced</span><span className="summary-value">{String(summary?.synced_recommendation_plan_outcomes ?? "—")}</span></div>
          <div className="summary-item"><span className="summary-label">Plan outcomes pending</span><Badge tone="warning">{String(summary?.pending_recommendation_plan_outcomes ?? "—")}</Badge></div>
          <div className="summary-item"><span className="summary-label">Plan wins</span><Badge tone="ok">{String(summary?.win_recommendation_plan_outcomes ?? "—")}</Badge></div>
          <div className="summary-item"><span className="summary-label">Plan losses</span><Badge tone="danger">{String(summary?.loss_recommendation_plan_outcomes ?? "—")}</Badge></div>
          <div className="summary-item"><span className="summary-label">No-action plans</span><Badge tone="neutral">{String(summary?.no_action_recommendation_plan_outcomes ?? "—")}</Badge></div>
          <div className="summary-item"><span className="summary-label">Watchlist plans</span><Badge tone="neutral">{String(summary?.watchlist_recommendation_plan_outcomes ?? "—")}</Badge></div>
        </div>
        {output ? (
          <details className="top-gap-small" open>
            <summary>Evaluator output</summary>
            <pre>{output}</pre>
          </details>
        ) : null}
      </Card>

      {scope ? (
        <Card>
          <SectionTitle kicker="Evaluation scope" title="What this run evaluated" />
          <MetadataObject value={scope} />
        </Card>
      ) : null}

      {trigger ? (
        <Card>
          <SectionTitle kicker="Trigger" title="How this run was started" />
          <MetadataObject value={trigger} />
        </Card>
      ) : null}

      <RawJson title="Raw summary JSON" value={rawSummary} />
      <RawJson title="Raw artifact JSON" value={rawArtifact} />
    </div>
  );
}

function OptimizationResultView({ summary, artifact, rawSummary, rawArtifact }: {
  summary: Record<string, unknown> | null;
  artifact: Record<string, unknown> | null;
  rawSummary: string | null;
  rawArtifact: string | null;
}) {
  const weightsChanged = summary?.weights_changed;
  const backup = isRecord(artifact?.backup) ? artifact.backup : null;
  const before = isRecord(artifact?.before) ? artifact.before : null;
  const after = isRecord(artifact?.after) ? artifact.after : null;
  const stdout = typeof summary?.stdout === "string" ? summary.stdout : null;
  const stderr = typeof summary?.stderr === "string" ? summary.stderr : null;
  const rollbackAvailable = artifact?.rollback_available;
  const backupCreatedAt = typeof backup?.created_at === "string" ? formatDate(backup.created_at) : "—";

  return (
    <div className="stack-page">
      <Card>
        <SectionTitle kicker="Optimization summary" title="Outcome" subtitle="Optimization workflows update weights using resolved recommendation-plan outcomes and persist before/after fingerprint metadata for audit and rollback." />
        <div className="summary-grid">
          <div className="summary-item"><span className="summary-label">Status</span><span className="summary-value">{String(summary?.status ?? "—")}</span></div>
          <div className="summary-item"><span className="summary-label">Resolved plan outcomes</span><span className="summary-value">{String(summary?.resolved_recommendation_plan_outcomes ?? summary?.resolved_trade_count ?? "—")}</span></div>
          <div className="summary-item"><span className="summary-label">Minimum required</span><span className="summary-value">{String(summary?.minimum_resolved_recommendation_plan_outcomes ?? summary?.minimum_resolved_trades ?? "—")}</span></div>
          <div className="summary-item"><span className="summary-label">Weights changed</span><Badge tone={weightsChanged === true ? "ok" : "warning"}>{weightsChanged === true ? "yes" : weightsChanged === false ? "no" : "—"}</Badge></div>
          <div className="summary-item"><span className="summary-label">Rollback available</span><Badge tone={rollbackAvailable === true ? "ok" : "neutral"}>{rollbackAvailable === true ? "yes" : rollbackAvailable === false ? "no" : "—"}</Badge></div>
          <div className="summary-item"><span className="summary-label">Weights path</span><span className="summary-value">{String(artifact?.weights_path ?? "—")}</span></div>
        </div>
      </Card>

      {backup ? (
        <Card>
          <SectionTitle kicker="Recovery" title="Rollback backup" subtitle="Each optimization run records the backup used for rollback before weights are modified." />
          <div className="summary-grid">
            <div className="summary-item"><span className="summary-label">Backup path</span><span className="summary-value">{String(backup.path ?? "—")}</span></div>
            <div className="summary-item"><span className="summary-label">Backup created</span><span className="summary-value">{backupCreatedAt}</span></div>
          </div>
          {isRecord(backup.fingerprint) ? <MetadataObject value={backup.fingerprint} /> : null}
        </Card>
      ) : null}

      <div className="two-column">
        <FingerprintCard title="Weights before optimization" value={before} />
        <FingerprintCard title="Weights after optimization" value={after} />
      </div>

      {stdout ? (
        <Card>
          <SectionTitle title="Optimizer stdout" />
          <pre>{stdout}</pre>
        </Card>
      ) : null}
      {stderr ? (
        <Card>
          <SectionTitle title="Optimizer stderr" />
          <pre>{stderr}</pre>
        </Card>
      ) : null}

      <RawJson title="Raw summary JSON" value={rawSummary} />
      <RawJson title="Raw artifact JSON" value={rawArtifact} />
    </div>
  );
}

function GenericWorkflowResultView({ rawSummary, rawArtifact }: { rawSummary: string | null; rawArtifact: string | null }) {
  const summary = parseJsonRecord(rawSummary);
  const artifact = parseJsonRecord(rawArtifact);
  return (
    <div className="stack-page">
      {summary ? (
        <Card>
          <SectionTitle title="Run summary" />
          <MetadataObject value={summary} />
        </Card>
      ) : null}
      {artifact ? (
        <Card>
          <SectionTitle title="Artifacts" />
          <MetadataObject value={artifact} />
        </Card>
      ) : null}
      <RawJson title="Raw summary JSON" value={rawSummary} />
      <RawJson title="Raw artifact JSON" value={rawArtifact} />
      {!summary && !artifact && !rawSummary && !rawArtifact ? <EmptyState message="No workflow summary or artifact metadata stored for this run yet." /> : null}
    </div>
  );
}

export function WorkflowRunResults({ jobType, summaryJson, artifactJson }: { jobType: JobType | string; summaryJson: string | null; artifactJson: string | null }) {
  const summary = parseJsonRecord(summaryJson);
  const artifact = parseJsonRecord(artifactJson);

  if (jobType === "recommendation_evaluation") {
    return <EvaluationResultView summary={summary} artifact={artifact} rawSummary={summaryJson} rawArtifact={artifactJson} />;
  }
  if (jobType === "weight_optimization") {
    return <OptimizationResultView summary={summary} artifact={artifact} rawSummary={summaryJson} rawArtifact={artifactJson} />;
  }
  return (
    <div className="stack-page">
      <div className="helper-text">This run is a {jobTypeLabel(jobType).toLowerCase()} workflow. It stores summary and artifact metadata on the run instead of legacy recommendation rows.</div>
      <GenericWorkflowResultView rawSummary={summaryJson} rawArtifact={artifactJson} />
    </div>
  );
}
