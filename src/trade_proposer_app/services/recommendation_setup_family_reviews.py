from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from trade_proposer_app.domain.statuses import OutcomeStatus, TradeOutcome
from trade_proposer_app.domain.models import (
    RecommendationCalibrationBucket,
    RecommendationPlanOutcome,
    RecommendationSetupFamilyReview,
    RecommendationSetupFamilyReviewSummary,
)
from trade_proposer_app.repositories.recommendation_outcomes import RecommendationOutcomeRepository
from trade_proposer_app.services.recommendation_outcome_cohorts import MIN_RESOLVED_COUNTS as OUTCOME_COHORT_MIN_RESOLVED_COUNTS, RecommendationOutcomeCohortBuilder
from trade_proposer_app.services.taxonomy import TickerTaxonomyService


class RecommendationSetupFamilyReviewService:
    FAMILY_LABELS: dict[str, str] = {
        "breakout": "Breakout",
        "continuation": "Continuation",
        "mean_reversion": "Mean reversion",
        "breakdown": "Breakdown",
        "catalyst_follow_through": "Catalyst follow-through",
        "macro_beneficiary_loser": "Macro beneficiary / loser",
    }

    def __init__(self, outcomes: RecommendationOutcomeRepository, taxonomy_service: TickerTaxonomyService | None = None) -> None:
        self.outcomes = outcomes
        self.taxonomy_service = taxonomy_service or TickerTaxonomyService()
        self.cohorts = RecommendationOutcomeCohortBuilder(self.taxonomy_service)

    def summarize(
        self,
        *,
        ticker: str | None = None,
        run_id: int | None = None,
        setup_family: str | None = None,
        resolved: str | None = None,
        outcome: str | None = None,
        evaluated_after: datetime | None = None,
        evaluated_before: datetime | None = None,
        limit: int = 500,
    ) -> RecommendationSetupFamilyReviewSummary:
        normalized_setup_family = setup_family.strip().lower() if setup_family else None
        outcomes = self.outcomes.list_outcomes(
            ticker=ticker,
            run_id=run_id,
            setup_family=normalized_setup_family,
            resolved=resolved,
            outcome=outcome,
            evaluated_after=evaluated_after,
            evaluated_before=evaluated_before,
            limit=limit,
        )
        grouped: dict[str, list[RecommendationPlanOutcome]] = defaultdict(list)
        for item in outcomes:
            family = str(item.setup_family or "uncategorized").strip() or "uncategorized"
            grouped[family].append(item)
        family_order = [normalized_setup_family] if normalized_setup_family else list(self.FAMILY_LABELS)
        families = [self._build_family_review(family, grouped.get(family, [])) for family in family_order if family is not None]
        families.sort(key=lambda item: (item.resolved_outcomes, item.total_outcomes, item.win_outcomes), reverse=True)
        return RecommendationSetupFamilyReviewSummary(
            total_outcomes_reviewed=len(outcomes),
            families=families,
        )

    def _build_family_review(
        self,
        family: str,
        items: list[RecommendationPlanOutcome],
    ) -> RecommendationSetupFamilyReview:
        resolved = [item for item in items if item.outcome in {TradeOutcome.WIN.value, TradeOutcome.LOSS.value}]
        return RecommendationSetupFamilyReview(
            family=family,
            label=self.FAMILY_LABELS.get(family, family.replace("_", " ")),
            total_outcomes=len(items),
            resolved_outcomes=len(resolved),
            open_outcomes=sum(1 for item in items if item.status == OutcomeStatus.OPEN.value),
            win_outcomes=sum(1 for item in items if item.outcome == TradeOutcome.WIN.value),
            loss_outcomes=sum(1 for item in items if item.outcome == TradeOutcome.LOSS.value),
            overall_win_rate_percent=self._win_rate(resolved),
            average_return_1d=self._average([item.horizon_return_1d for item in items]),
            average_return_3d=self._average([item.horizon_return_3d for item in items]),
            average_return_5d=self._average([item.horizon_return_5d for item in items]),
            average_mfe=self._average([item.max_favorable_excursion for item in items]),
            average_mae=self._average([item.max_adverse_excursion for item in items]),
            by_horizon=self._grouped_summary(items, group_by="horizon", default_key="unknown_horizon"),
            by_transmission_bias=self._grouped_summary(items, group_by="transmission_bias", default_key="unknown"),
            by_context_regime=self._grouped_summary(items, group_by="context_regime", default_key="mixed_context"),
        )

    def _grouped_summary(
        self,
        items: list[RecommendationPlanOutcome],
        *,
        group_by: str,
        default_key: str,
    ) -> list[RecommendationCalibrationBucket]:
        return self.cohorts.grouped_summary(
            items,
            group_by=group_by,
            default_key=default_key,
            min_required_resolved_count=OUTCOME_COHORT_MIN_RESOLVED_COUNTS.get(group_by, 0),
        )


    @staticmethod
    def _win_rate(items: list[RecommendationPlanOutcome]) -> float | None:
        if not items:
            return None
        wins = sum(1 for item in items if item.outcome == TradeOutcome.WIN.value)
        return round((wins / len(items)) * 100.0, 1)

    @staticmethod
    def _average(values: list[float | None]) -> float | None:
        numeric = [float(value) for value in values if isinstance(value, (int, float))]
        if not numeric:
            return None
        return round(sum(numeric) / len(numeric), 3)
