from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import uuid4

SECRET_KEY_PARTS = ("secret", "token", "password", "x-user-key", "api_key", "api_secret", "key")


def redacted_payload(value: object) -> object:
    if isinstance(value, dict):
        redacted: dict[str, object] = {}
        for key, item in value.items():
            normalized = str(key).lower().replace("_", "-")
            if any(part in normalized for part in SECRET_KEY_PARTS):
                redacted[str(key)] = "[REDACTED]"
            else:
                redacted[str(key)] = redacted_payload(item)
        return redacted
    if isinstance(value, list):
        return [redacted_payload(item) for item in value]
    return value


class BrokerAdapterResultStatus(StrEnum):
    SUCCESS = "success"
    REJECTED = "rejected"
    FAILED = "failed"
    RATE_LIMITED = "rate_limited"
    AMBIGUOUS = "ambiguous"
    NOT_FOUND = "not_found"


@dataclass(slots=True)
class BrokerCredentialValidation:
    valid: bool
    permission_scope: str = "unknown"
    account_mode: str = "unknown"
    permissions: list[str] = field(default_factory=list)
    message: str = ""
    raw_payload: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.raw_payload = redacted_payload(self.raw_payload)  # type: ignore[assignment]


@dataclass(slots=True)
class BrokerCapabilities:
    broker: str
    account_mode: str
    supported_actions: list[str] = field(default_factory=list)
    supported_order_types: list[str] = field(default_factory=list)
    supported_instruments: list[str] = field(default_factory=list)
    supports_cancel: bool = False
    supports_close_position: bool = False
    supports_trade_history: bool = False
    supports_protective_orders: bool = False
    supports_amend_protection: bool = False
    supports_short: bool = False
    min_leverage: float = 1.0
    max_leverage: float = 1.0
    min_notional_usd: float | None = None
    max_notional_usd: float | None = None
    idempotency_field: str = "client_order_id"
    raw_payload: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.raw_payload = redacted_payload(self.raw_payload)  # type: ignore[assignment]


@dataclass(slots=True)
class BrokerInstrument:
    symbol: str
    instrument_id: str
    tradable: bool = True
    ambiguous: bool = False
    product_type: str = "unknown"
    exchange: str = ""
    currency: str = "usd"
    min_notional_usd: float | None = None
    max_notional_usd: float | None = None
    supports_stop_loss: bool = False
    supports_take_profit: bool = False
    market_hours: str = "unknown"
    raw_payload: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.raw_payload = redacted_payload(self.raw_payload)  # type: ignore[assignment]


@dataclass(slots=True)
class BrokerOrderRequest:
    client_order_id: str
    symbol: str
    side: str
    order_type: str
    quantity: int | None = None
    notional_amount: float | None = None
    instrument_id: str | None = None
    time_in_force: str = "gtc"
    leverage: float = 1.0
    stop_loss: float | None = None
    take_profit: float | None = None
    payload: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.payload = redacted_payload(self.payload)  # type: ignore[assignment]


@dataclass(slots=True)
class BrokerProtectionAmendRequest:
    broker_order_id: str
    client_order_id: str | None = None
    symbol: str = ""
    stop_loss: float | None = None
    take_profit: float | None = None
    payload: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.payload = redacted_payload(self.payload)  # type: ignore[assignment]


@dataclass(slots=True)
class BrokerOrderResult:
    status: BrokerAdapterResultStatus
    operation: str
    client_request_id: str
    broker_order_id: str | None = None
    broker_position_id: str | None = None
    broker_status: str = ""
    payload: dict[str, object] = field(default_factory=dict)
    message: str = ""
    needs_review: bool = False
    retry_after_seconds: float | None = None

    def __post_init__(self) -> None:
        self.payload = redacted_payload(self.payload)  # type: ignore[assignment]

    @property
    def is_success(self) -> bool:
        return self.status == BrokerAdapterResultStatus.SUCCESS

    @classmethod
    def ambiguous(
        cls, *, operation: str, client_request_id: str, message: str
    ) -> BrokerOrderResult:
        return cls(
            status=BrokerAdapterResultStatus.AMBIGUOUS,
            operation=operation,
            client_request_id=client_request_id,
            message=message,
            needs_review=True,
        )


@dataclass(slots=True)
class BrokerAccountSnapshot:
    equity: float | None = None
    cash: float | None = None
    currency: str = "usd"
    payload: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.payload = redacted_payload(self.payload)  # type: ignore[assignment]


@dataclass(slots=True)
class BrokerPortfolioResult:
    status: BrokerAdapterResultStatus
    operation: str
    client_request_id: str
    account: BrokerAccountSnapshot | None = None
    items: list[dict[str, object]] = field(default_factory=list)
    payload: dict[str, object] = field(default_factory=dict)
    message: str = ""
    needs_review: bool = False
    retry_after_seconds: float | None = None

    def __post_init__(self) -> None:
        self.items = redacted_payload(self.items)  # type: ignore[assignment]
        self.payload = redacted_payload(self.payload)  # type: ignore[assignment]

    @property
    def is_success(self) -> bool:
        return self.status == BrokerAdapterResultStatus.SUCCESS


@dataclass(slots=True)
class BrokerTradeHistoryResult:
    status: BrokerAdapterResultStatus
    operation: str
    client_request_id: str
    trades: list[dict[str, object]] = field(default_factory=list)
    payload: dict[str, object] = field(default_factory=dict)
    message: str = ""

    def __post_init__(self) -> None:
        self.trades = redacted_payload(self.trades)  # type: ignore[assignment]
        self.payload = redacted_payload(self.payload)  # type: ignore[assignment]


@runtime_checkable
class BrokerAdapter(Protocol):
    def validate_credentials(self) -> BrokerCredentialValidation: ...

    def get_capabilities(self) -> BrokerCapabilities: ...

    def resolve_instrument(self, symbol: str) -> BrokerInstrument: ...

    def get_account_snapshot(self) -> BrokerPortfolioResult: ...

    def get_open_orders(self) -> BrokerPortfolioResult: ...

    def get_open_positions(self) -> BrokerPortfolioResult: ...

    def submit_order(self, request: BrokerOrderRequest) -> BrokerOrderResult: ...

    def lookup_order(
        self, order_id: str | None = None, client_order_id: str | None = None
    ) -> BrokerOrderResult: ...

    def cancel_order(self, order_id: str) -> BrokerOrderResult: ...

    def close_position(
        self, position_id: str, quantity: float | None = None
    ) -> BrokerOrderResult: ...

    def amend_position_protection(
        self, request: BrokerProtectionAmendRequest
    ) -> BrokerOrderResult: ...

    def get_trade_history(self) -> BrokerTradeHistoryResult: ...


class FakeBrokerAdapter:
    def __init__(self, *, capabilities: BrokerCapabilities | None = None) -> None:
        self._capabilities = capabilities or BrokerCapabilities(broker="fake", account_mode="paper")
        self.orders: dict[str, BrokerOrderResult] = {}

    def validate_credentials(self) -> BrokerCredentialValidation:
        return BrokerCredentialValidation(
            valid=True, permission_scope="test", account_mode=self._capabilities.account_mode
        )

    def get_capabilities(self) -> BrokerCapabilities:
        return self._capabilities

    def resolve_instrument(self, symbol: str) -> BrokerInstrument:
        return BrokerInstrument(symbol=symbol.upper(), instrument_id=symbol.upper(), tradable=True)

    def get_account_snapshot(self) -> BrokerPortfolioResult:
        return BrokerPortfolioResult(
            status=BrokerAdapterResultStatus.SUCCESS,
            operation="get_account_snapshot",
            client_request_id=str(uuid4()),
            account=BrokerAccountSnapshot(equity=100000.0, cash=100000.0),
        )

    def get_open_orders(self) -> BrokerPortfolioResult:
        return BrokerPortfolioResult(
            status=BrokerAdapterResultStatus.SUCCESS,
            operation="get_open_orders",
            client_request_id=str(uuid4()),
            items=[],
        )

    def get_open_positions(self) -> BrokerPortfolioResult:
        return BrokerPortfolioResult(
            status=BrokerAdapterResultStatus.SUCCESS,
            operation="get_open_positions",
            client_request_id=str(uuid4()),
            items=[],
        )

    def submit_order(self, request: BrokerOrderRequest) -> BrokerOrderResult:
        broker_order_id = f"fake-{len(self.orders) + 1}"
        result = BrokerOrderResult(
            status=BrokerAdapterResultStatus.SUCCESS,
            operation="submit_order",
            client_request_id=request.client_order_id,
            broker_order_id=broker_order_id,
            broker_status="accepted",
            payload={"id": broker_order_id, "status": "accepted"},
        )
        self.orders[broker_order_id] = result
        return result

    def lookup_order(
        self, order_id: str | None = None, client_order_id: str | None = None
    ) -> BrokerOrderResult:
        if order_id and order_id in self.orders:
            return self.orders[order_id]
        return BrokerOrderResult(
            status=BrokerAdapterResultStatus.NOT_FOUND,
            operation="lookup_order",
            client_request_id=client_order_id or order_id or str(uuid4()),
            message="order not found",
        )

    def cancel_order(self, order_id: str) -> BrokerOrderResult:
        return BrokerOrderResult(
            status=BrokerAdapterResultStatus.SUCCESS,
            operation="cancel_order",
            client_request_id=str(uuid4()),
            broker_order_id=order_id,
            broker_status="canceled",
        )

    def close_position(self, position_id: str, quantity: float | None = None) -> BrokerOrderResult:
        return BrokerOrderResult(
            status=BrokerAdapterResultStatus.SUCCESS,
            operation="close_position",
            client_request_id=str(uuid4()),
            broker_position_id=position_id,
            broker_status="closing",
            payload={"position_id": position_id, "quantity": quantity},
        )

    def amend_position_protection(self, request: BrokerProtectionAmendRequest) -> BrokerOrderResult:
        if not self._capabilities.supports_amend_protection:
            return BrokerOrderResult(
                status=BrokerAdapterResultStatus.REJECTED,
                operation="amend_position_protection",
                client_request_id=request.client_order_id or request.broker_order_id,
                broker_order_id=request.broker_order_id,
                message="broker_amend_protection_unsupported",
            )
        return BrokerOrderResult(
            status=BrokerAdapterResultStatus.SUCCESS,
            operation="amend_position_protection",
            client_request_id=request.client_order_id or request.broker_order_id,
            broker_order_id=request.broker_order_id,
            broker_status="accepted",
            payload={
                "id": request.broker_order_id,
                "status": "accepted",
                "stop_loss": request.stop_loss,
                "take_profit": request.take_profit,
            },
        )

    def get_trade_history(self) -> BrokerTradeHistoryResult:
        return BrokerTradeHistoryResult(
            status=BrokerAdapterResultStatus.SUCCESS,
            operation="get_trade_history",
            client_request_id=str(uuid4()),
            trades=[],
        )
