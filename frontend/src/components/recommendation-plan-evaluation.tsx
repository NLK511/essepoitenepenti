import type { RecommendationPlan } from "../types";
import { recommendationPlanEvaluationLabel, recommendationPlanEvaluationSubtitle, recommendationPlanEvaluationTone } from "../utils";
import { Badge } from "./ui";

function sourceTone(source: string): "ok" | "warning" | "danger" | "neutral" | "info" {
  if (source === "broker") {
    return "ok";
  }
  return "neutral";
}

function sourceLabel(source: string): string {
  if (source === "broker") {
    return "Broker authoritative";
  }
  if (source === "missing") {
    return "Evaluation missing";
  }
  return "Simulated";
}

export function RecommendationPlanEvaluationSummary(props: {
  plan: RecommendationPlan;
  compact?: boolean;
}) {
  const { plan, compact = false } = props;
  const sourceLabelText = sourceLabel(plan.effective_evaluation_source);
  const label = recommendationPlanEvaluationLabel(plan);
  const detail = plan.effective_evaluation_source === "broker"
    ? plan.effective_evaluation_detail || (plan.broker_order_status ? `broker order ${plan.broker_order_status}` : "broker evaluation")
    : recommendationPlanEvaluationSubtitle(plan);
  const simulatedFallback = plan.effective_evaluation_source === "simulated" && plan.broker_order_status
    ? `Broker order ${plan.broker_order_status} · simulated fallback${plan.latest_outcome?.notes ? ` · ${plan.latest_outcome.notes}` : ""}`
    : null;

  const precedenceNote = plan.effective_evaluation_source === "broker"
    ? "Broker status is the authoritative state; simulated outcome remains as comparison only."
    : plan.effective_evaluation_source === "missing"
      ? "Broker evaluation is missing; only the broker audit record is available."
      : null;

  return (
    <div className={compact ? "evaluation-summary evaluation-summary-compact" : "evaluation-summary"}>
      <div className="cluster">
        <Badge tone={sourceTone(plan.effective_evaluation_source)}>{sourceLabelText}</Badge>
        <Badge tone={recommendationPlanEvaluationTone(label)}>{label}</Badge>
      </div>
      <div className="helper-text top-gap-small">{detail}</div>
      {precedenceNote ? <div className="helper-text">{precedenceNote}</div> : null}
      {simulatedFallback ? <div className="helper-text">{simulatedFallback}</div> : null}
    </div>
  );
}
