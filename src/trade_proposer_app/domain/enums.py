from __future__ import annotations

from enum import StrEnum


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"
    CANCELED = "canceled"


class JobType(StrEnum):
    PROPOSAL_GENERATION = "proposal_generation"
    RECOMMENDATION_EVALUATION = "recommendation_evaluation"
    PLAN_GENERATION_TUNING = "plan_generation_tuning"
    PERFORMANCE_ASSESSMENT = "performance_assessment"
    MACRO_CONTEXT_REFRESH = "macro_context_refresh"
    INDUSTRY_CONTEXT_REFRESH = "industry_context_refresh"
    HISTORICAL_REPLAY = "historical_replay"

    @classmethod
    def parse(cls, value: str | "JobType") -> "JobType":
        if isinstance(value, cls):
            return value
        normalized = str(value or "").strip()
        legacy_aliases = {
            "macro_context_refresh": cls.MACRO_CONTEXT_REFRESH,
            "industry_context_refresh": cls.INDUSTRY_CONTEXT_REFRESH,
        }
        if normalized in legacy_aliases:
            return legacy_aliases[normalized]
        return cls(normalized)


class RecommendationDirection(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"


class RecommendationState(StrEnum):
    PENDING = "PENDING"
    WIN = "WIN"
    LOSS = "LOSS"


class StrategyHorizon(StrEnum):
    ONE_DAY = "1d"
    ONE_WEEK = "1w"
    ONE_MONTH = "1m"
