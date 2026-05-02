from __future__ import annotations

from enum import StrEnum

from trade_proposer_app.domain.enums import RunStatus


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
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
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
TERMINAL_EXECUTION_STATUSES = {
    ExecutionStatus.WIN.value,
    ExecutionStatus.LOSS.value,
    ExecutionStatus.CANCELED.value,
    ExecutionStatus.REJECTED.value,
    ExecutionStatus.EXPIRED.value,
    ExecutionStatus.FAILED.value,
    ExecutionStatus.SKIPPED.value,
}
NONTERMINAL_EXECUTION_STATUSES = {
    ExecutionStatus.NEW.value,
    ExecutionStatus.SUBMITTED.value,
    ExecutionStatus.ACCEPTED.value,
    ExecutionStatus.OPEN.value,
}


def normalize_status(value: object) -> str:
    return str(value or "").strip().lower()


def is_terminal_execution_status(value: object) -> bool:
    return normalize_status(value) in TERMINAL_EXECUTION_STATUSES


def is_resolved_trade_outcome(value: object) -> bool:
    return normalize_status(value) in RESOLVED_TRADE_OUTCOMES


def is_failed_run_status(value: object) -> bool:
    return normalize_status(value) == RunStatus.FAILED.value


def is_failed_preflight_status(value: object) -> bool:
    return normalize_status(value) == "failed"


def is_warning_preflight_status(value: object) -> bool:
    return normalize_status(value) == "warning"


def broker_position_status_to_outcome(value: object) -> str:
    normalized = normalize_status(value)
    if normalized in BROKER_RESOLVED_POSITION_STATUSES:
        return normalized
    return TradeOutcome.OPEN.value
