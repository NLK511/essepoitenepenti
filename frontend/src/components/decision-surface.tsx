import type { ReactNode } from "react";

import { Badge } from "./ui";

export function ScoreBadge(props: {
  label: string;
  value: ReactNode;
  tone?: "ok" | "warning" | "danger" | "neutral" | "info";
  tooltip?: string;
}) {
  return <Badge tone={props.tone} title={props.tooltip}><span className="context-badge-label">{props.label}</span><span className="context-badge-value">{props.value}</span></Badge>;
}

export function MetricCluster(props: {
  items: Array<{ label: string; value: ReactNode; tone?: "ok" | "warning" | "danger" | "neutral" | "info"; tooltip?: string }>;
}) {
  return <div className="cluster">{props.items.map((item) => <ScoreBadge key={item.label} label={item.label} value={item.value} tone={item.tone} tooltip={item.tooltip} />)}</div>;
}

export function WarningSummary(props: {
  warnings: string[];
  title?: string;
}) {
  if (props.warnings.length === 0) {
    return null;
  }
  return (
    <div className="top-gap-small">
      <div className="cluster">
        <Badge tone="warning">{props.title ?? "Warnings"}: {props.warnings.length}</Badge>
      </div>
      <div className="helper-text warning-text top-gap-small">{props.warnings.join(" · ")}</div>
    </div>
  );
}

export function ProvenanceStrip(props: {
  method: string;
  backend: string;
  model?: string | null;
  error?: string | null;
  fallbackLabel?: string;
}) {
  const isLlm = props.method === "llm_summary";
  const model = props.model && props.model !== "—" ? props.model : null;
  const label = isLlm
    ? `LLM · ${props.backend}${model ? ` · ${model}` : ""}`
    : `${props.fallbackLabel ?? "fallback"} · ${props.backend}`;
  return (
    <div className="cluster">
      <Badge tone={props.error ? "warning" : isLlm ? "ok" : "neutral"}>{label}</Badge>
      {props.error ? <Badge tone="warning">summary warning</Badge> : null}
    </div>
  );
}

function contextConfidenceBandLabel(confidence: number): string {
  if (confidence >= 85) {
    return "dominant";
  }
  if (confidence >= 65) {
    return "strong";
  }
  if (confidence >= 40) {
    return "moderate";
  }
  return "light";
}

function contextSaliencyBandLabel(saliency: number): string {
  if (saliency >= 0.85) {
    return "dominant";
  }
  if (saliency >= 0.65) {
    return "strong";
  }
  if (saliency >= 0.4) {
    return "moderate";
  }
  return "light";
}

function contextConfidenceTooltip(confidence: number): string {
  return `Current confidence band: ${contextConfidenceBandLabel(confidence)}. Confidence bands: 0–39.9 light, 40–64.9 moderate, 65–84.9 strong, 85+ dominant.`;
}

function contextSaliencyTooltip(saliency: number): string {
  return `Current saliency band: ${contextSaliencyBandLabel(saliency)}. Saliency bands: 0.00–0.39 light, 0.40–0.64 moderate, 0.65–0.84 strong, 0.85+ dominant.`;
}

export function ContextScoreSummary(props: {
  confidence: number;
  saliency: number;
  coverage?: string | number | null;
  freshness?: string | null;
  tone?: "ok" | "warning" | "danger" | "neutral" | "info";
}) {
  return (
    <MetricCluster
      items={[
        {
          label: "Confidence",
          value: `${props.confidence.toFixed(1)}%`,
          tone: props.tone ?? "info",
          tooltip: contextConfidenceTooltip(props.confidence),
        },
        {
          label: "Saliency",
          value: `${props.saliency.toFixed(2)}`,
          tone: "neutral",
          tooltip: contextSaliencyTooltip(props.saliency),
        },
        { label: "Coverage", value: props.coverage ?? "—", tone: "neutral" },
        { label: "Freshness", value: props.freshness ?? "—", tone: "neutral" },
      ]}
    />
  );
}

export function ContextEventSummary(props: {
  label: string;
  value: ReactNode;
  details?: Array<{ label: string; value: ReactNode }>;
  channels?: string[];
}) {
  return (
    <div className="data-point">
      <span className="data-point-label">{props.label}</span>
      <span className="data-point-value">{props.value}</span>
      {props.details?.length ? (
        <div className="helper-text top-gap-small context-inline-metrics">
          {props.details.map((detail) => (
            <span key={detail.label} className="context-inline-metric"><strong>{detail.label}:</strong> {detail.value}</span>
          ))}
        </div>
      ) : null}
      {props.channels && props.channels.length > 0 ? (
        <div className="helper-text context-inline-metrics">
          <span className="context-inline-metric"><strong>Channels:</strong> {props.channels.join(" · ")}</span>
        </div>
      ) : null}
    </div>
  );
}
