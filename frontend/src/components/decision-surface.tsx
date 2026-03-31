import type { ReactNode } from "react";

import { Badge } from "./ui";

export function ScoreBadge(props: {
  label: string;
  value: ReactNode;
  tone?: "ok" | "warning" | "danger" | "neutral" | "info";
}) {
  return <Badge tone={props.tone}><span className="context-badge-label">{props.label}</span><span className="context-badge-value">{props.value}</span></Badge>;
}

export function MetricCluster(props: {
  items: Array<{ label: string; value: ReactNode; tone?: "ok" | "warning" | "danger" | "neutral" | "info" }>;
}) {
  return <div className="cluster">{props.items.map((item) => <ScoreBadge key={item.label} label={item.label} value={item.value} tone={item.tone} />)}</div>;
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
        { label: "Confidence", value: `${props.confidence.toFixed(1)}%`, tone: props.tone ?? "info" },
        { label: "Saliency", value: props.saliency.toFixed(2), tone: "neutral" },
        { label: "Coverage", value: props.coverage ?? "—", tone: "neutral" },
        { label: "Freshness", value: props.freshness ?? "—", tone: "neutral" },
      ]}
    />
  );
}
