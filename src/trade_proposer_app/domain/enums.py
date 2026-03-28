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
    WEIGHT_OPTIMIZATION = "weight_optimization"
    MACRO_CONTEXT_REFRESH = "macro_sentiment_refresh"
    INDUSTRY_CONTEXT_REFRESH = "industry_sentiment_refresh"
    MACRO_SENTIMENT_REFRESH = MACRO_CONTEXT_REFRESH
    INDUSTRY_SENTIMENT_REFRESH = INDUSTRY_CONTEXT_REFRESH


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
