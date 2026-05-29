from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from trade_proposer_app.domain.models import AccountRiskState, RecommendationWalkForwardSummary
from trade_proposer_app.repositories.effective_plan_outcomes import EffectivePlanOutcomeRepository
from trade_proposer_app.services.edge_validation_gate import EdgeValidationGateReport, EdgeValidationGateService
from trade_proposer_app.services.recommendation_evidence_concentration import RecommendationEvidenceConcentrationService
from trade_proposer_app.services.trade_decision_policy import TradeDecisionPolicyService
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
        return self.build(
            policy_review,
            walk_forward_validation=walk_forward_validation,
            evidence_concentration=evidence_concentration,
            degraded_input_summary=degraded_input_summary,
            risk_state=risk_state,
        )

    def build(
        self,
        policy_review: TradePolicyEvaluationSummary,
        *,
        walk_forward_validation: RecommendationWalkForwardSummary | dict[str, Any] | None = None,
        evidence_concentration: Any | None = None,
        degraded_input_summary: dict[str, object] | None = None,
        risk_state: AccountRiskState | dict[str, Any] | None = None,
    ) -> PolicyTrustReport:
        broker_summary = self._broker_reconciliation_summary(risk_state)
        degraded_share = self._optional_float((degraded_input_summary or {}).get("degraded_input_share_percent")) if degraded_input_summary else None
        concentration_ready = self._concentration_ready(evidence_concentration)
        missing_inputs = self._missing_inputs(
            walk_forward_validation=walk_forward_validation,
            evidence_concentration=evidence_concentration,
            degraded_input_summary=degraded_input_summary,
            broker_reconciliation_summary=broker_summary,
        )
        gate = EdgeValidationGateService().evaluate(
            policy_review.policy_evaluation,
            walk_forward_validation=walk_forward_validation,
            broker_reconciliation_uncertain=broker_summary["uncertain"],
            evidence_concentration_ready_for_expansion=concentration_ready,
            degraded_input_share_percent=degraded_share,
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
            missing_inputs=missing_inputs,
        )

    @staticmethod
    def _missing_inputs(
        *,
        walk_forward_validation: object | None,
        evidence_concentration: object | None,
        degraded_input_summary: dict[str, object] | None,
        broker_reconciliation_summary: dict[str, object],
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
        return missing

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
