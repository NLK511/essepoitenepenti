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


class RecommendationDirection(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"


class RecommendationState(StrEnum):
    PENDING = "PENDING"
    WIN = "WIN"
    LOSS = "LOSS"
