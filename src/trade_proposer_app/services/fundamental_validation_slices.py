from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from trade_proposer_app.persistence.models import RecommendationPlanRecord
from trade_proposer_app.repositories.effective_plan_outcomes import EffectivePlanOutcomeRepository


class FundamentalValidationSliceService:
    SLICE_NAMES = (
        "event_regime",
        "earnings_window",
        "analyst_action_bucket",
        "valuation_bucket",
        "profitability_quality_bucket",
        "growth_bucket",
        "balance_sheet_risk_bucket",
        "setup_family_event_regime",
        "mispricing_signal",
        "directional_support",
        "setup_family_mispricing_signal",
    )

    def __init__(self, session: Session) -> None:
        self.session = session
        self.outcomes = EffectivePlanOutcomeRepository(session)

    def summarize(self, *, limit: int = 5000) -> dict[str, object]:
        outcomes = self.outcomes.list_outcomes(limit=limit, resolved="resolved")
        plan_ids = [item.recommendation_plan_id for item in outcomes if item.recommendation_plan_id is not None]
        plans = self._plans_by_id(plan_ids)
        buckets: dict[str, dict[str, dict[str, int]]] = {name: defaultdict(lambda: {"resolved_count": 0, "wins": 0, "losses": 0}) for name in self.SLICE_NAMES}
        for outcome in outcomes:
            plan = plans.get(int(outcome.recommendation_plan_id or 0))
            if plan is None or outcome.outcome not in {"win", "loss"}:
                continue
            features = self._fundamental_features(plan)
            setup_family = self._setup_family(plan)
            values = {
                "event_regime": features.get("event_regime", "unknown"),
                "earnings_window": features.get("event_regime", "unknown"),
                "analyst_action_bucket": features.get("analyst_action_bucket", "unknown"),
                "valuation_bucket": features.get("valuation", "unknown"),
                "profitability_quality_bucket": features.get("profitability_quality", "unknown"),
                "growth_bucket": features.get("growth", "unknown"),
                "balance_sheet_risk_bucket": features.get("balance_sheet_risk", "unknown"),
                "setup_family_event_regime": f"{setup_family}:{features.get('event_regime', 'unknown')}",
                "mispricing_signal": features.get("mispricing_signal", "unknown"),
                "directional_support": features.get("directional_support", "unknown"),
                "setup_family_mispricing_signal": f"{setup_family}:{features.get('mispricing_signal', 'unknown')}",
            }
            for slice_name, bucket_name in values.items():
                rec = buckets[slice_name][str(bucket_name or "unknown")]
                rec["resolved_count"] += 1
                rec["wins"] += 1 if outcome.outcome == "win" else 0
                rec["losses"] += 1 if outcome.outcome == "loss" else 0
        return {
            "limit": limit,
            "uses_effective_outcomes": True,
            "slices": {name: self._slice_payload(bucket_map) for name, bucket_map in buckets.items()},
        }

    def _plans_by_id(self, plan_ids: list[int]) -> dict[int, RecommendationPlanRecord]:
        if not plan_ids:
            return {}
        rows = self.session.scalars(select(RecommendationPlanRecord).where(RecommendationPlanRecord.id.in_(plan_ids))).all()
        return {int(row.id): row for row in rows if row.id is not None}

    @staticmethod
    def _slice_payload(bucket_map: dict[str, dict[str, int]]) -> dict[str, object]:
        bucket_rows = []
        total_resolved = 0
        total_wins = 0
        total_losses = 0
        for name, values in sorted(bucket_map.items()):
            resolved = int(values["resolved_count"])
            wins = int(values["wins"])
            losses = int(values["losses"])
            total_resolved += resolved
            total_wins += wins
            total_losses += losses
            bucket_rows.append(
                {
                    "bucket": name,
                    "resolved_count": resolved,
                    "wins": wins,
                    "losses": losses,
                    "effective_win_rate_percent": round((wins / resolved) * 100.0, 2) if resolved else None,
                    "sparse_evidence": resolved < 10,
                }
            )
        return {
            "resolved_count": total_resolved,
            "wins": total_wins,
            "losses": total_losses,
            "effective_win_rate_percent": round((total_wins / total_resolved) * 100.0, 2) if total_resolved else None,
            "sparse_evidence": total_resolved < 30,
            "uses_effective_outcomes": True,
            "buckets": bucket_rows,
        }

    @classmethod
    def _fundamental_features(cls, plan: RecommendationPlanRecord) -> dict[str, Any]:
        signal = cls._loads(plan.signal_breakdown_json)
        buckets = signal.get("fundamental_feature_buckets") if isinstance(signal.get("fundamental_feature_buckets"), dict) else {}
        snapshot = signal.get("fundamental_snapshot") if isinstance(signal.get("fundamental_snapshot"), dict) else {}
        payload = snapshot.get("payload") if isinstance(snapshot.get("payload"), dict) else {}
        analyst = payload.get("analyst_context") if isinstance(payload.get("analyst_context"), dict) else {}
        valuation_context = (
            signal.get("fundamental_valuation_context")
            if isinstance(signal.get("fundamental_valuation_context"), dict)
            else payload.get("valuation_context") if isinstance(payload.get("valuation_context"), dict) else {}
        )
        normalized = dict(buckets)
        recommendation = str(analyst.get("recommendation_key") or "unknown").strip().lower() or "unknown"
        normalized["analyst_action_bucket"] = recommendation
        normalized["mispricing_signal"] = str(
            valuation_context.get("mispricing_signal") or "unknown"
        )
        support = valuation_context.get("directional_support")
        action = str(getattr(plan, "action", "") or "").strip().lower()
        normalized["directional_support"] = (
            str(support.get(action) or "unknown") if isinstance(support, dict) else "unknown"
        )
        return normalized

    @classmethod
    def _setup_family(cls, plan: RecommendationPlanRecord) -> str:
        signal = cls._loads(plan.signal_breakdown_json)
        return str(signal.get("setup_family") or "unknown")

    @staticmethod
    def _loads(raw: str | None) -> dict[str, Any]:
        try:
            parsed = json.loads(raw or "{}")
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
