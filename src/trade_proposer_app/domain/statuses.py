from __future__ import annotations

from enum import StrEnum


class OutcomeStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    NEEDS_REVIEW = "needs_review"


class TradeOutcome(StrEnum):
    WIN = "win"
    LOSS = "loss"
    OPEN = "open"
    NO_ACTION = "no_action"
    WATCHLIST = "watchlist"


class BrokerPositionStatus(StrEnum):
    SUBMITTED = "submitted"
    OPEN = "open"
    WIN = "win"
    LOSS = "loss"
    CANCELED = "canceled"
    ERROR = "error"
    NEEDS_REVIEW = "needs_review"


class ExecutionStatus(StrEnum):
    NEW = "new"
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    OPEN = "open"
    WIN = "win"
    LOSS = "loss"
    CANCELED = "canceled"
    EXPIRED = "expired"
    REJECTED = "rejected"
    FAILED = "failed"
    SKIPPED = "skipped"


class PlanStatus(StrEnum):
    OK = "ok"
    PARTIAL = "partial"
    DEGRADED = "degraded"


BROKER_RESOLVED_POSITION_STATUSES = {BrokerPositionStatus.WIN.value, BrokerPositionStatus.LOSS.value}
RESOLVED_TRADE_OUTCOMES = {TradeOutcome.WIN.value, TradeOutcome.LOSS.value}
