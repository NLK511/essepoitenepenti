from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from trade_proposer_app.domain.models import AccountRiskState, RecommendationPlanOutcome, RecommendationWalkForwardSummary
from trade_proposer_app.domain.statuses import OutcomeStatus, TradeOutcome
from trade_proposer_app.repositories.effective_plan_outcomes import EffectivePlanOutcomeRepository
from trade_proposer_app.services.edge_validation_gate import EdgeValidationGateReport, EdgeValidationGateService
from trade_proposer_app.services.recommendation_evidence_concentration import RecommendationEvidenceConcentrationService
from trade_proposer_app.services.trade_decision_policy import TradeDecisionPolicy, TradeDecisionPolicyService
from trade_proposer_app.services.trade_policy_evaluation import PolicyHealthReport, TradePolicyEvaluationService, TradePolicyEvaluationSummary


@dataclass(frozen=True)
class PolicyTrustReport:
    """Canonical read model for operator-facing policy trust."""

    edge_validation_gate: EdgeValidationGateReport
    policy_health_headline: PolicyHealthReport
    policy_evaluation: dict[str, object]
    reliability_report: dict[str, object]
    walk_forward_validation: dict[str, object] | None
    evidence_concentration: dict[str, object] | None
    degraded_input_summary: dict[str, object] | None
    broker_reconciliation_summary: dict[str, object]
    baseline_comparison_summary: dict[str, object] | None
    drawdown_summary: dict[str, object] | None
    loss_streak_summary: dict[str, object] | None
    missing_inputs: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "edge_validation_gate": self.edge_validation_gate.to_dict(),
            "policy_health_headline": self.policy_health_headline.to_dict(),
            "policy_evaluation": self.policy_evaluation,
            "reliability_report": self.reliability_report,
            "walk_forward_validation": self.walk_forward_validation,
            "evidence_concentration": self.evidence_concentration,
            "degraded_input_summary": self.degraded_input_summary,
            "broker_reconciliation_summary": self.broker_reconciliation_summary,
            "baseline_comparison_summary": self.baseline_comparison_summary,
            "drawdown_summary": self.drawdown_summary,
            "loss_streak_summary": self.loss_streak_summary,
            "missing_inputs": self.missing_inputs,
        }


class PolicyTrustReportService:
    """Assemble the authoritative policy trust report from shared lower-level services."""

    def __init__(self, outcomes: EffectivePlanOutcomeRepository, *, policy_service: TradeDecisionPolicyService | None = None) -> None:
        self.outcomes = outcomes
        self.policy_service = policy_service

    def summarize_active_policy(
        self,
        *,
        evaluated_after: datetime | None = None,
        evaluated_before: datetime | None = None,
        limit: int = 5000,
        walk_forward_validation: RecommendationWalkForwardSummary | dict[str, Any] | None = None,
        evidence_concentration: Any | None = None,
        degraded_input_summary: dict[str, object] | None = None,
        risk_state: AccountRiskState | dict[str, Any] | None = None,
    ) -> PolicyTrustReport:
        if self.policy_service is None:
            raise ValueError("policy_service is required to summarize the active policy")
        policy_review = TradePolicyEvaluationService(
            self.outcomes,
            policy_service=self.policy_service,
        ).summarize_active_policy(evaluated_after=evaluated_after, evaluated_before=evaluated_before, limit=limit)
        if evidence_concentration is None:
            evidence_concentration = RecommendationEvidenceConcentrationService(self.outcomes).summarize(
                evaluated_after=evaluated_after,
                evaluated_before=evaluated_before,
                limit=limit,
            )
        policy = self.policy_service.active_policy()
        outcomes = self.outcomes.list_outcomes(evaluated_after=evaluated_after, evaluated_before=evaluated_before, limit=limit)
        return self.build(
            policy_review,
            walk_forward_validation=walk_forward_validation,
            evidence_concentration=evidence_concentration,
            degraded_input_summary=degraded_input_summary,
            risk_state=risk_state,
            baseline_comparison_summary=self._baseline_comparison_summary(outcomes, policy_review.policy_evaluation.win_rate_percent),
            drawdown_summary=self._drawdown_summary(outcomes, policy),
            loss_streak_summary=self._loss_streak_summary(outcomes, policy),
        )

    def build(
        self,
        policy_review: TradePolicyEvaluationSummary,
        *,
        walk_forward_validation: RecommendationWalkForwardSummary | dict[str, Any] | None = None,
        evidence_concentration: Any | None = None,
        degraded_input_summary: dict[str, object] | None = None,
        risk_state: AccountRiskState | dict[str, Any] | None = None,
        baseline_comparison_summary: dict[str, object] | None = None,
        drawdown_summary: dict[str, object] | None = None,
        loss_streak_summary: dict[str, object] | None = None,
    ) -> PolicyTrustReport:
        broker_summary = self._broker_reconciliation_summary(risk_state)
        degraded_share = self._optional_float((degraded_input_summary or {}).get("degraded_input_share_percent")) if degraded_input_summary else None
        concentration_ready = self._concentration_ready(evidence_concentration)
        missing_inputs = self._missing_inputs(
            walk_forward_validation=walk_forward_validation,
            evidence_concentration=evidence_concentration,
            degraded_input_summary=degraded_input_summary,
            broker_reconciliation_summary=broker_summary,
            baseline_comparison_summary=baseline_comparison_summary,
            drawdown_summary=drawdown_summary,
            loss_streak_summary=loss_streak_summary,
        )
        gate = EdgeValidationGateService().evaluate(
            policy_review.policy_evaluation,
            walk_forward_validation=walk_forward_validation,
            broker_reconciliation_uncertain=broker_summary["uncertain"],
            evidence_concentration_ready_for_expansion=concentration_ready,
            degraded_input_share_percent=degraded_share,
            baseline_comparison_summary=baseline_comparison_summary,
            drawdown_summary=drawdown_summary,
            loss_streak_summary=loss_streak_summary,
        )
        headline = self._policy_health_headline(policy_review.policy_health, gate)
        return PolicyTrustReport(
            edge_validation_gate=gate,
            policy_health_headline=headline,
            policy_evaluation=policy_review.policy_evaluation.to_dict(),
            reliability_report=policy_review.reliability_report.to_dict(),
            walk_forward_validation=self._model_or_dict(walk_forward_validation),
            evidence_concentration=self._model_or_dict(evidence_concentration),
            degraded_input_summary=degraded_input_summary,
            broker_reconciliation_summary=broker_summary,
            baseline_comparison_summary=baseline_comparison_summary,
            drawdown_summary=drawdown_summary,
            loss_streak_summary=loss_streak_summary,
            missing_inputs=missing_inputs,
        )

    @staticmethod
    def _missing_inputs(
        *,
        walk_forward_validation: object | None,
        evidence_concentration: object | None,
        degraded_input_summary: dict[str, object] | None,
        broker_reconciliation_summary: dict[str, object],
        baseline_comparison_summary: dict[str, object] | None,
        drawdown_summary: dict[str, object] | None,
        loss_streak_summary: dict[str, object] | None,
    ) -> list[str]:
        missing: list[str] = []
        if walk_forward_validation is None:
            missing.append("walk_forward_input_missing")
        if evidence_concentration is None:
            missing.append("concentration_input_missing")
        if degraded_input_summary is None:
            missing.append("degraded_input_input_missing")
        if broker_reconciliation_summary.get("status") in {"missing", "not_checked"}:
            missing.append("broker_reconciliation_input_missing")
        if baseline_comparison_summary is None:
            missing.append("baseline_comparison_input_missing")
        if drawdown_summary is None:
            missing.append("drawdown_input_missing")
        if loss_streak_summary is None:
            missing.append("loss_streak_input_missing")
        return missing

    @classmethod
    def _baseline_comparison_summary(cls, outcomes: list[RecommendationPlanOutcome], selected_win_rate_percent: float | None) -> dict[str, object]:
        resolved = [item for item in outcomes if item.status == OutcomeStatus.RESOLVED.value and item.outcome in {TradeOutcome.WIN.value, TradeOutcome.LOSS.value}]
        if not resolved or selected_win_rate_percent is None:
            return {"passed": False, "reason": "baseline_sample_missing", "baseline_win_rate_percent": None, "selected_win_rate_percent": selected_win_rate_percent}
        wins = sum(1 for item in resolved if item.outcome == TradeOutcome.WIN.value)
        baseline_win_rate = round((wins / len(resolved)) * 100.0, 1)
        delta = round(float(selected_win_rate_percent) - baseline_win_rate, 2)
        return {
            "passed": delta >= 5.0,
            "baseline_win_rate_percent": baseline_win_rate,
            "selected_win_rate_percent": selected_win_rate_percent,
            "win_rate_delta_percent": delta,
            "resolved_baseline_outcomes": len(resolved),
        }

    @classmethod
    def _drawdown_summary(cls, outcomes: list[RecommendationPlanOutcome], policy: TradeDecisionPolicy) -> dict[str, object]:
        selected = cls._selected_resolved_outcomes(outcomes, policy)
        cumulative = 0.0
        peak = 0.0
        max_drawdown = 0.0
        for item in sorted(selected, key=lambda row: row.evaluated_at):
            cumulative += float(item.realized_pnl or 0.0)
            peak = max(peak, cumulative)
            max_drawdown = min(max_drawdown, cumulative - peak)
        return {"breached": max_drawdown < 0 and abs(max_drawdown) > max(100.0, abs(peak) * 0.25), "max_drawdown": round(max_drawdown, 4), "selected_resolved_outcomes": len(selected)}

    @classmethod
    def _loss_streak_summary(cls, outcomes: list[RecommendationPlanOutcome], policy: TradeDecisionPolicy) -> dict[str, object]:
        selected = cls._selected_resolved_outcomes(outcomes, policy)
        current = 0
        max_streak = 0
        for item in sorted(selected, key=lambda row: row.evaluated_at):
            if item.outcome == TradeOutcome.LOSS.value:
                current += 1
                max_streak = max(max_streak, current)
            else:
                current = 0
        return {"breached": max_streak >= 5, "max_loss_streak": max_streak, "selected_resolved_outcomes": len(selected)}

    @staticmethod
    def _selected_resolved_outcomes(outcomes: list[RecommendationPlanOutcome], policy: TradeDecisionPolicy) -> list[RecommendationPlanOutcome]:
        return [
            item
            for item in outcomes
            if item.status == OutcomeStatus.RESOLVED.value
            and item.outcome in {TradeOutcome.WIN.value, TradeOutcome.LOSS.value}
            and policy.action_allowed(item.action)
            and policy.setup_family_allowed(item.setup_family)
            and isinstance(item.confidence_percent, (int, float))
            and float(item.confidence_percent) >= policy.effective_confidence_threshold()
        ]

    @staticmethod
    def _broker_reconciliation_summary(risk_state: AccountRiskState | dict[str, Any] | None) -> dict[str, object]:
        if risk_state is None:
            return {"status": "missing", "uncertain": None, "reasons": []}
        if isinstance(risk_state, dict):
            metrics = risk_state.get("metrics") if isinstance(risk_state.get("metrics"), dict) else {}
            reasons = risk_state.get("reasons") if isinstance(risk_state.get("reasons"), list) else []
        else:
            metrics = risk_state.metrics
            reasons = risk_state.reasons
        severity = str(metrics.get("broker_drift_severity") or "missing") if isinstance(metrics, dict) else "missing"
        uncertain = None if severity in {"missing", "not_checked"} else severity != "ok"
        return {
            "status": severity,
            "uncertain": uncertain,
            "reasons": list(reasons),
            "broker_snapshot_available": bool(metrics.get("broker_snapshot_available")) if isinstance(metrics, dict) else False,
        }

    @staticmethod
    def _policy_health_headline(health: PolicyHealthReport, gate: EdgeValidationGateReport) -> PolicyHealthReport:
        if gate.label == "eligible_for_cautious_expansion":
            return health
        reasons = list(dict.fromkeys([*health.reasons, "edge_gate_not_expansion_ready"]))
        if gate.label == "blocked":
            label = "insufficient"
        elif gate.label in {"demote_or_halt", "research_only"}:
            label = "degraded"
        else:
            label = "watch" if health.label == "healthy" else health.label
        return PolicyHealthReport(
            label=label,
            reasons=reasons,
            resolved_selected_outcomes=health.resolved_selected_outcomes,
            win_rate_percent=health.win_rate_percent,
            realized_pnl=health.realized_pnl,
            calibration_gap_percent=health.calibration_gap_percent,
            broker_outcome_share_percent=health.broker_outcome_share_percent,
        )

    @staticmethod
    def _concentration_ready(evidence_concentration: object | None) -> bool | None:
        if evidence_concentration is None:
            return None
        if isinstance(evidence_concentration, dict):
            value = evidence_concentration.get("ready_for_expansion")
        else:
            value = getattr(evidence_concentration, "ready_for_expansion", None)
        return value if isinstance(value, bool) else None

    @staticmethod
    def _model_or_dict(value: object | None) -> dict[str, object] | None:
        if value is None:
            return None
        if isinstance(value, dict):
            return value
        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            return model_dump(mode="json")
        to_dict = getattr(value, "to_dict", None)
        if callable(to_dict):
            return to_dict()
        return None

    @staticmethod
    def _optional_float(value: object) -> float | None:
        try:
            return float(value) if value is not None and str(value).strip() != "" else None
        except (TypeError, ValueError):
            return None
