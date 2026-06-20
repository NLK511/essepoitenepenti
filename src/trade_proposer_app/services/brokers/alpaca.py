from __future__ import annotations

from uuid import uuid4

from trade_proposer_app.services.alpaca_paper_client import (
    AlpacaPaperClient,
    AlpacaPaperClientError,
)
from trade_proposer_app.services.brokers.adapter import (
    BrokerAccountSnapshot,
    BrokerAdapterResultStatus,
    BrokerCapabilities,
    BrokerCredentialValidation,
    BrokerInstrument,
    BrokerOrderRequest,
    BrokerOrderResult,
    BrokerPortfolioResult,
    BrokerProtectionAmendRequest,
    BrokerTradeHistoryResult,
)


class AlpacaPaperBrokerAdapter:
    def __init__(self, *, client: AlpacaPaperClient) -> None:
        self.client = client

    def validate_credentials(self) -> BrokerCredentialValidation:
        try:
            result = self.client.get_account()
        except AlpacaPaperClientError as exc:
            return BrokerCredentialValidation(
                valid=False,
                permission_scope="paper",
                account_mode="paper",
                message=str(exc),
                raw_payload=exc.payload,
            )
        return BrokerCredentialValidation(
            valid=True,
            permission_scope="paper_trading",
            account_mode="paper",
            permissions=["paper_trading"],
            raw_payload=result.payload,
        )

    def get_capabilities(self) -> BrokerCapabilities:
        return BrokerCapabilities(
            broker="alpaca",
            account_mode="paper",
            supported_actions=["long", "short"],
            supported_order_types=["market", "limit"],
            supported_instruments=["us_equity"],
            supports_cancel=True,
            supports_close_position=True,
            supports_trade_history=False,
            supports_protective_orders=True,
            supports_amend_protection=True,
            supports_short=True,
            min_leverage=1.0,
            max_leverage=1.0,
            idempotency_field="client_order_id",
        )

    def resolve_instrument(self, symbol: str) -> BrokerInstrument:
        normalized = symbol.strip().upper()
        return BrokerInstrument(
            symbol=normalized,
            instrument_id=normalized,
            tradable=bool(normalized),
            product_type="us_equity",
            currency="usd",
            supports_stop_loss=True,
            supports_take_profit=True,
        )

    def get_account_snapshot(self) -> BrokerPortfolioResult:
        try:
            result = self.client.get_account()
        except AlpacaPaperClientError as exc:
            return self._portfolio_error("get_account_snapshot", exc)
        return BrokerPortfolioResult(
            status=BrokerAdapterResultStatus.SUCCESS,
            operation="get_account_snapshot",
            client_request_id=str(uuid4()),
            account=BrokerAccountSnapshot(
                equity=self._float_or_none(result.payload.get("equity")),
                cash=self._float_or_none(result.payload.get("cash")),
                payload=result.payload,
            ),
            payload=result.payload,
        )

    def get_open_orders(self) -> BrokerPortfolioResult:
        try:
            result = self.client.list_open_orders()
        except AlpacaPaperClientError as exc:
            return self._portfolio_error("get_open_orders", exc)
        items = result.payload.get("items", [])
        return BrokerPortfolioResult(
            status=BrokerAdapterResultStatus.SUCCESS,
            operation="get_open_orders",
            client_request_id=str(uuid4()),
            items=items if isinstance(items, list) else [],
            payload=result.payload,
        )

    def get_open_positions(self) -> BrokerPortfolioResult:
        try:
            result = self.client.list_open_positions()
        except AlpacaPaperClientError as exc:
            return self._portfolio_error("get_open_positions", exc)
        items = result.payload.get("items", [])
        return BrokerPortfolioResult(
            status=BrokerAdapterResultStatus.SUCCESS,
            operation="get_open_positions",
            client_request_id=str(uuid4()),
            items=items if isinstance(items, list) else [],
            payload=result.payload,
        )

    def submit_order(self, request: BrokerOrderRequest) -> BrokerOrderResult:
        payload = self._alpaca_order_payload(request)
        try:
            result = self.client.submit_order(payload)
        except AlpacaPaperClientError as exc:
            return self._order_error("submit_order", request.client_order_id, exc)
        return self._order_success("submit_order", request.client_order_id, result.payload)

    def lookup_order(
        self,
        order_id: str | None = None,
        client_order_id: str | None = None,
    ) -> BrokerOrderResult:
        lookup_id = order_id or client_order_id or ""
        try:
            result = self.client.get_order(lookup_id)
        except AlpacaPaperClientError as exc:
            return self._order_error("lookup_order", lookup_id, exc)
        return self._order_success("lookup_order", lookup_id, result.payload)

    def cancel_order(self, order_id: str) -> BrokerOrderResult:
        try:
            result = self.client.cancel_order(order_id)
        except AlpacaPaperClientError as exc:
            return self._order_error("cancel_order", order_id, exc)
        return self._order_success("cancel_order", order_id, result.payload)

    def close_position(self, position_id: str, quantity: float | None = None) -> BrokerOrderResult:
        try:
            result = self.client.close_position(position_id)
        except AlpacaPaperClientError as exc:
            return self._order_error("close_position", position_id, exc)
        return self._order_success("close_position", position_id, result.payload)

    def amend_position_protection(self, request: BrokerProtectionAmendRequest) -> BrokerOrderResult:
        payload: dict[str, object] = {"client_order_id": request.client_order_id or ""}
        if request.stop_loss is not None:
            payload["stop_loss"] = {"stop_price": request.stop_loss}
        if request.take_profit is not None:
            payload["take_profit"] = {"limit_price": request.take_profit}
        try:
            result = self.client.amend_order(request.broker_order_id, payload)
        except AlpacaPaperClientError as exc:
            return self._order_error("amend_position_protection", request.broker_order_id, exc)
        return self._order_success(
            "amend_position_protection",
            request.client_order_id or request.broker_order_id,
            result.payload,
        )

    def get_trade_history(self) -> BrokerTradeHistoryResult:
        return BrokerTradeHistoryResult(
            status=BrokerAdapterResultStatus.SUCCESS,
            operation="get_trade_history",
            client_request_id=str(uuid4()),
            trades=[],
            message="alpaca paper trade history is derived from order/position sync",
        )

    def _alpaca_order_payload(self, request: BrokerOrderRequest) -> dict[str, object]:
        payload: dict[str, object] = {
            "symbol": request.symbol.strip().upper(),
            "side": request.side,
            "type": request.order_type,
            "time_in_force": request.time_in_force,
            "client_order_id": request.client_order_id,
        }
        if request.quantity is not None:
            payload["qty"] = request.quantity
        if request.notional_amount is not None and request.quantity is None:
            payload["notional"] = request.notional_amount
        if "limit_price" in request.payload:
            payload["limit_price"] = request.payload["limit_price"]
        take_profit = self._payload_take_profit(request.payload, fallback=request.take_profit)
        stop_loss = self._payload_stop_loss(request.payload, fallback=request.stop_loss)
        if stop_loss is not None or take_profit is not None:
            payload["order_class"] = "bracket"
            if take_profit is not None:
                payload["take_profit"] = {"limit_price": take_profit}
            if stop_loss is not None:
                payload["stop_loss"] = {"stop_price": stop_loss}
        return payload

    @staticmethod
    def _payload_take_profit(payload: dict[str, object], *, fallback: float | None) -> float | None:
        take_profit = payload.get("take_profit")
        if isinstance(take_profit, dict):
            value = take_profit.get("limit_price")
            if isinstance(value, (int, float)):
                return float(value)
        return fallback

    @staticmethod
    def _payload_stop_loss(payload: dict[str, object], *, fallback: float | None) -> float | None:
        stop_loss = payload.get("stop_loss")
        if isinstance(stop_loss, dict):
            value = stop_loss.get("stop_price")
            if isinstance(value, (int, float)):
                return float(value)
        return fallback

    def _order_success(
        self,
        operation: str,
        client_request_id: str,
        payload: dict[str, object],
    ) -> BrokerOrderResult:
        return BrokerOrderResult(
            status=BrokerAdapterResultStatus.SUCCESS,
            operation=operation,
            client_request_id=client_request_id,
            broker_order_id=self._str_or_none(payload.get("id")),
            broker_position_id=self._str_or_none(payload.get("position_id")),
            broker_status=str(payload.get("status") or ""),
            payload=payload,
        )

    def _order_error(
        self,
        operation: str,
        client_request_id: str,
        exc: AlpacaPaperClientError,
    ) -> BrokerOrderResult:
        status = BrokerAdapterResultStatus.FAILED
        if exc.status_code == 404:
            status = BrokerAdapterResultStatus.NOT_FOUND
        elif exc.status_code == 429:
            status = BrokerAdapterResultStatus.RATE_LIMITED
        elif exc.status_code is not None and 400 <= exc.status_code < 500:
            status = BrokerAdapterResultStatus.REJECTED
        return BrokerOrderResult(
            status=status,
            operation=operation,
            client_request_id=client_request_id,
            message=str(exc),
            payload=exc.payload,
            retry_after_seconds=None,
        )

    def _portfolio_error(
        self, operation: str, exc: AlpacaPaperClientError
    ) -> BrokerPortfolioResult:
        status = (
            BrokerAdapterResultStatus.RATE_LIMITED
            if exc.status_code == 429
            else BrokerAdapterResultStatus.FAILED
        )
        return BrokerPortfolioResult(
            status=status,
            operation=operation,
            client_request_id=str(uuid4()),
            message=str(exc),
            payload=exc.payload,
        )

    @staticmethod
    def _float_or_none(value: object) -> float | None:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _str_or_none(value: object) -> str | None:
        return str(value) if value is not None else None
