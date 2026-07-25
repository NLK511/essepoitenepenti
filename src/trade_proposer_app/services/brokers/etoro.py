from __future__ import annotations

from uuid import uuid4

import httpx

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
    redacted_payload,
)


class EtoroClientError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        payload: dict[str, object] | None = None,
        error_type: str = "failed",
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = redacted_payload(payload or {})  # type: ignore[assignment]
        self.error_type = error_type
        self.retry_after_seconds = retry_after_seconds


class EtoroClient:
    def __init__(
        self,
        *,
        api_key: str,
        user_key: str,
        base_url: str = "https://public-api.etoro.com",
        http_client: object | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        self.api_key = api_key.strip()
        self.user_key = user_key.strip()
        self.base_url = base_url.rstrip("/")
        self.http_client = http_client
        self.timeout_seconds = timeout_seconds

    def validate(self) -> dict[str, object]:
        return self._request("GET", "/api/v1/trading/info/portfolio")

    def search_market_data(self, symbol: str) -> dict[str, object]:
        return self._request(
            "GET",
            "/api/v1/market-data/search",
            params={
                "fields": "instrumentId",
                "internalSymbolFull": symbol.strip().upper(),
                "pageSize": 25,
            },
        )

    def get_instrument_display_data(self, instrument_id: int | str) -> dict[str, object]:
        return self._request(
            "GET",
            "/api/v1/market-data/instruments",
            params={"instrumentIds": str(instrument_id)},
        )

    def get_market_rates(self, instrument_ids: list[int | str]) -> dict[str, object]:
        return self._request(
            "GET",
            "/api/v1/market-data/instruments/rates",
            params={"instrumentIds": ",".join(str(item) for item in instrument_ids)},
        )

    def get_instrument_candles(
        self,
        *,
        instrument_id: int | str,
        direction: str,
        interval: str,
        candles_count: int,
    ) -> dict[str, object]:
        return self._request(
            "GET",
            f"/api/v1/market-data/instruments/{instrument_id}/history/candles/{direction}/{interval}/{candles_count}",
        )

    def get_portfolio(self) -> dict[str, object]:
        return self._request("GET", "/api/v1/trading/info/portfolio")

    def get_demo_portfolio(self) -> dict[str, object]:
        return self._request("GET", "/api/v1/trading/info/demo/portfolio")

    def get_pnl(self) -> dict[str, object]:
        return self._request("GET", "/api/v1/trading/info/real/pnl")

    def get_demo_pnl(self) -> dict[str, object]:
        return self._request("GET", "/api/v1/trading/info/demo/pnl")

    def get_demo_aggregate_portfolio(self) -> dict[str, object]:
        return self._request("GET", "/api/v1/trading/info/demo/aggregate-portfolio")

    def get_trade_history(self) -> dict[str, object]:
        return self._request("GET", "/api/v1/trading/info/trade/history")

    def get_demo_trade_history(self) -> dict[str, object]:
        return self._request("GET", "/api/v1/trading/info/trade/demo/history")

    def check_demo_eligibility(self, payload: dict[str, object]) -> dict[str, object]:
        return self._request(
            "POST", "/api/v2/trading/info/demo/eligibility", json_payload=payload
        )

    def get_demo_costs(self, payload: dict[str, object]) -> dict[str, object]:
        return self._request("POST", "/api/v2/trading/info/demo/costs", json_payload=payload)

    def submit_demo_order(self, payload: dict[str, object]) -> dict[str, object]:
        return self._request("POST", "/api/v2/trading/execution/demo/orders", json_payload=payload)

    def lookup_demo_order(
        self, order_id: str | None = None, reference_id: str | None = None
    ) -> dict[str, object]:
        params = {"orderId": order_id} if order_id else {"referenceId": reference_id}
        return self._request(
            "GET",
            "/api/v2/trading/info/demo/orders:lookup",
            params={k: v for k, v in params.items() if v},
        )

    def cancel_demo_order(self, order_id: str) -> dict[str, object]:
        return self._request("DELETE", f"/api/v2/trading/execution/demo/orders/{order_id}")

    def close_demo_position(
        self,
        position_id: str,
        quantity: float | None = None,
        instrument_id: int | str | None = None,
    ) -> dict[str, object]:
        payload = {"UnitsToDeduct": quantity}
        if instrument_id is not None:
            payload["InstrumentID"] = int(instrument_id)
        return self._request(
            "POST",
            f"/api/v1/trading/execution/demo/market-close-orders/positions/{position_id}",
            json_payload=payload,
        )

    def cancel_pending_demo_close(self, order_id: str) -> dict[str, object]:
        return self._request(
            "DELETE", f"/api/v1/trading/execution/demo/market-close-orders/{order_id}"
        )

    def lookup_demo_close_order(self, order_id: str) -> dict[str, object]:
        return self._request("GET", f"/api/v1/trading/info/demo/close-orders/{order_id}")

    def amend_demo_position_protection(
        self, position_id: str, payload: dict[str, object]
    ) -> dict[str, object]:
        return self._request(
            "PATCH", f"/api/v2/trading/demo/positions/{position_id}", json_payload=payload
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, object] | None = None,
        json_payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        if not self.api_key or not self.user_key:
            raise EtoroClientError(
                "eToro credentials are missing", error_type="missing_credentials"
            )
        headers = {
            "x-api-key": self.api_key,
            "x-user-key": self.user_key,
            "x-request-id": str(uuid4()),
        }
        if json_payload is not None:
            headers["Content-Type"] = "application/json"
        url = f"{self.base_url}{path}"
        client = self.http_client
        try:
            if client is not None:
                response = client.request(
                    method,
                    url,
                    headers=headers,
                    json=json_payload,
                    params=params,
                    timeout=self.timeout_seconds,
                )
            else:
                with httpx.Client(timeout=self.timeout_seconds) as http_client:
                    response = http_client.request(
                        method,
                        url,
                        headers=headers,
                        json=json_payload,
                        params=params,
                    )
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise EtoroClientError("eToro request timed out", error_type="timeout") from exc
        try:
            payload = response.json()
        except ValueError:
            payload = {"raw_body": response.text}
        normalized_payload = payload if isinstance(payload, dict) else {"items": payload}
        if response.status_code >= 400:
            raise EtoroClientError(
                f"eToro request failed with status {response.status_code}",
                status_code=response.status_code,
                payload=normalized_payload,
                error_type=self._error_type(response.status_code),
                retry_after_seconds=self._retry_after(response.headers),
            )
        return redacted_payload(normalized_payload)  # type: ignore[return-value]

    @staticmethod
    def _error_type(status_code: int) -> str:
        if status_code in {401, 403}:
            return "permission_denied"
        if status_code == 429:
            return "rate_limited"
        return "failed"

    @staticmethod
    def _retry_after(headers: dict[str, str]) -> float | None:
        raw = headers.get("retry-after") or headers.get("Retry-After")
        if raw is None:
            return None
        try:
            return float(raw)
        except ValueError:
            return None


class EtoroReadOnlyBrokerAdapter:
    def __init__(self, *, client: EtoroClient) -> None:
        self.client = client
        self._instrument_cache: dict[str, BrokerInstrument] = {}

    def validate_credentials(self) -> BrokerCredentialValidation:
        try:
            payload = self.client.validate()
        except EtoroClientError as exc:
            return BrokerCredentialValidation(
                valid=False,
                permission_scope="invalid",
                account_mode="unknown",
                message=str(exc),
                raw_payload=exc.payload,
            )
        permissions = (
            [str(item) for item in payload.get("permissions", [])]
            if isinstance(payload.get("permissions"), list)
            else []
        )
        mode = str(payload.get("mode") or payload.get("accountMode") or "unknown").lower()
        scope = (
            "real"
            if "real_trading" in permissions
            else "demo"
            if "demo_trading" in permissions or mode == "demo"
            else "read_only"
        )
        return BrokerCredentialValidation(
            valid=True,
            permission_scope=scope,
            account_mode=mode,
            permissions=permissions,
            raw_payload=payload,
        )

    def get_capabilities(self) -> BrokerCapabilities:
        return BrokerCapabilities(
            broker="etoro",
            account_mode="unknown",
            supported_actions=["long"],
            supported_order_types=["market"],
            supported_instruments=["resolved_equity"],
            supports_cancel=True,
            supports_close_position=True,
            supports_trade_history=True,
            supports_protective_orders=True,
            supports_short=False,
            min_leverage=1.0,
            max_leverage=1.0,
            idempotency_field="x-request-id",
        )

    def resolve_instrument(self, symbol: str) -> BrokerInstrument:
        normalized = symbol.strip().upper()
        if normalized in self._instrument_cache:
            return self._instrument_cache[normalized]
        aliases = self._symbol_aliases(normalized)
        rows: list[dict[str, object]] = []
        attempts: list[dict[str, object]] = []
        for alias in aliases:
            try:
                payload = self.client.search_market_data(alias)
            except EtoroClientError as exc:
                attempts.append({"symbol": alias, "error": exc.payload})
                continue
            attempts.append({"symbol": alias, "payload": payload})
            rows.extend(self._enriched_instrument_rows(alias, payload))
        matches = [
            row
            for row in rows
            if str(row.get("symbolFull") or row.get("symbol") or "").upper() in aliases
        ]
        if len(matches) != 1:
            instrument = BrokerInstrument(
                symbol=normalized,
                instrument_id="",
                tradable=False,
                ambiguous=bool(matches),
                raw_payload={"attempts": attempts, "matched_symbols": aliases},
            )
            self._instrument_cache[normalized] = instrument
            return instrument
        row = matches[0]
        product_type = str(
            row.get("instrumentType")
            or row.get("productType")
            or row.get("product_type")
            or "equity"
        ).lower()
        currency = str(row.get("currency") or row.get("orderCurrency") or "usd").lower()
        min_notional = self._float(row.get("minAmount") or row.get("min_notional_usd"))
        tradable = (
            bool(row.get("tradable", row.get("isCurrentlyTradable", True)))
            and product_type in {"stock", "stocks", "equity"}
            and currency == "usd"
        )
        if min_notional is not None and min_notional > 1000:
            tradable = False
        instrument = BrokerInstrument(
            symbol=normalized,
            instrument_id=str(
                row.get("instrumentId")
                or row.get("instrumentID")
                or row.get("instrument_id")
                or ""
            ),
            tradable=tradable,
            ambiguous=False,
            product_type=product_type,
            exchange=str(row.get("priceSource") or row.get("exchange") or row.get("market") or ""),
            currency=currency,
            min_notional_usd=min_notional,
            max_notional_usd=self._float(row.get("maxAmount") or row.get("max_notional_usd")),
            supports_stop_loss=bool(
                row.get("supportsStopLoss", row.get("supports_stop_loss", False))
            ),
            supports_take_profit=bool(
                row.get("supportsTakeProfit", row.get("supports_take_profit", False))
            ),
            market_hours=str(row.get("marketHours") or row.get("market_hours") or "unknown"),
            raw_payload=row,
        )
        self._instrument_cache[normalized] = instrument
        return instrument

    @staticmethod
    def _symbol_aliases(symbol: str) -> list[str]:
        aliases = [symbol]
        if "-" in symbol:
            aliases.append(symbol.replace("-", "."))
        if "." in symbol:
            aliases.append(symbol.replace(".", "-"))
        if symbol.endswith(".US"):
            aliases.append(symbol.removesuffix(".US"))
        return list(dict.fromkeys(aliases))

    def get_account_snapshot(self) -> BrokerPortfolioResult:
        try:
            payload = self.client.get_portfolio()
        except EtoroClientError as exc:
            return self._portfolio_error("get_account_snapshot", exc)
        portfolio = self._client_portfolio(payload)
        return BrokerPortfolioResult(
            status=BrokerAdapterResultStatus.SUCCESS,
            operation="get_account_snapshot",
            client_request_id=str(uuid4()),
            account=BrokerAccountSnapshot(
                equity=self._float(portfolio.get("equity") or portfolio.get("balance")),
                cash=self._float(
                    portfolio.get("cash")
                    or portfolio.get("availableCash")
                    or portfolio.get("credit")
                ),
                payload=payload,
            ),
            payload=payload,
        )

    def get_open_orders(self) -> BrokerPortfolioResult:
        try:
            payload = self.client.get_portfolio()
        except EtoroClientError as exc:
            return self._portfolio_error("get_open_orders", exc)
        portfolio = self._client_portfolio(payload)
        return BrokerPortfolioResult(
            status=BrokerAdapterResultStatus.SUCCESS,
            operation="get_open_orders",
            client_request_id=str(uuid4()),
            items=self._list(portfolio.get("orders") or portfolio.get("openOrders")),
            payload=payload,
        )

    def get_open_positions(self) -> BrokerPortfolioResult:
        try:
            payload = self.client.get_portfolio()
        except EtoroClientError as exc:
            return self._portfolio_error("get_open_positions", exc)
        portfolio = self._client_portfolio(payload)
        return BrokerPortfolioResult(
            status=BrokerAdapterResultStatus.SUCCESS,
            operation="get_open_positions",
            client_request_id=str(uuid4()),
            items=self._list(portfolio.get("positions") or portfolio.get("openPositions")),
            payload=payload,
        )

    def get_trade_history(self) -> BrokerTradeHistoryResult:
        try:
            payload = self.client.get_trade_history()
        except EtoroClientError as exc:
            return BrokerTradeHistoryResult(
                status=BrokerAdapterResultStatus.FAILED,
                operation="get_trade_history",
                client_request_id=str(uuid4()),
                payload=exc.payload,
                message=str(exc),
            )
        trades = self._list(payload.get("trades") or payload.get("history") or payload.get("items"))
        return BrokerTradeHistoryResult(
            status=BrokerAdapterResultStatus.SUCCESS,
            operation="get_trade_history",
            client_request_id=str(uuid4()),
            trades=trades,
            payload=payload,
        )

    def submit_order(self, request: BrokerOrderRequest) -> BrokerOrderResult:
        return BrokerOrderResult.ambiguous(
            operation="submit_order",
            client_request_id=request.client_order_id,
            message="eToro read-only adapter does not submit orders",
        )

    def lookup_order(
        self, order_id: str | None = None, client_order_id: str | None = None
    ) -> BrokerOrderResult:
        return BrokerOrderResult(
            status=BrokerAdapterResultStatus.FAILED,
            operation="lookup_order",
            client_request_id=client_order_id or order_id or str(uuid4()),
            message="eToro order lookup is not enabled in read-only adapter",
        )

    def lookup_close_order(self, order_id: str) -> BrokerOrderResult:
        return BrokerOrderResult(
            status=BrokerAdapterResultStatus.FAILED,
            operation="lookup_close_order",
            client_request_id=order_id,
            message="eToro close-order lookup is not enabled in read-only adapter",
        )

    def cancel_order(self, order_id: str) -> BrokerOrderResult:
        return BrokerOrderResult.ambiguous(
            operation="cancel_order",
            client_request_id=order_id,
            message="eToro read-only adapter does not cancel orders",
        )

    def close_position(self, position_id: str, quantity: float | None = None) -> BrokerOrderResult:
        return BrokerOrderResult.ambiguous(
            operation="close_position",
            client_request_id=position_id,
            message="eToro read-only adapter does not close positions",
        )

    def amend_position_protection(self, request: BrokerProtectionAmendRequest) -> BrokerOrderResult:
        return BrokerOrderResult.ambiguous(
            operation="amend_position_protection",
            client_request_id=request.client_order_id or request.broker_order_id,
            message="eToro read-only adapter does not amend position protection",
        )

    @staticmethod
    def _portfolio_error(operation: str, exc: EtoroClientError) -> BrokerPortfolioResult:
        status = (
            BrokerAdapterResultStatus.RATE_LIMITED
            if exc.error_type == "rate_limited"
            else BrokerAdapterResultStatus.FAILED
        )
        return BrokerPortfolioResult(
            status=status,
            operation=operation,
            client_request_id=str(uuid4()),
            message=str(exc),
            payload=exc.payload,
            retry_after_seconds=exc.retry_after_seconds,
        )

    @staticmethod
    def _instrument_rows(payload: dict[str, object]) -> list[dict[str, object]]:
        for key in ("instruments", "items", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return []

    def _enriched_instrument_rows(
        self, symbol: str, payload: dict[str, object]
    ) -> list[dict[str, object]]:
        rows = self._instrument_rows(payload)
        if any(row.get("symbol") or row.get("symbolFull") for row in rows):
            return rows
        enriched: list[dict[str, object]] = []
        for row in rows:
            instrument_id = row.get("instrumentId") or row.get("instrumentID")
            if not instrument_id:
                continue
            try:
                display_payload = self.client.get_instrument_display_data(str(instrument_id))
            except EtoroClientError:
                continue
            display_rows = self._list(display_payload.get("instrumentDisplayDatas"))
            enriched.extend(display_rows)
        return [
            row
            for row in enriched
            if str(row.get("symbolFull") or row.get("symbol") or "").upper() == symbol
        ] or enriched

    @staticmethod
    def _list(value: object) -> list[dict[str, object]]:
        return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []

    @staticmethod
    def _client_portfolio(payload: dict[str, object]) -> dict[str, object]:
        nested = payload.get("clientPortfolio")
        return nested if isinstance(nested, dict) else payload

    @staticmethod
    def _float(value: object) -> float | None:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None


class EtoroLiveBrokerAdapter(EtoroReadOnlyBrokerAdapter):
    def get_capabilities(self) -> BrokerCapabilities:
        capabilities = super().get_capabilities()
        capabilities.account_mode = "live"
        capabilities.raw_payload = redacted_payload({"live_mutations_enabled": False})  # type: ignore[assignment]
        return capabilities

    def submit_order(self, request: BrokerOrderRequest) -> BrokerOrderResult:
        return BrokerOrderResult(
            status=BrokerAdapterResultStatus.REJECTED,
            operation="submit_order",
            client_request_id=request.client_order_id,
            message="etoro_live_mutation_disabled",
            payload={"reason": "etoro_live_mutation_disabled"},
        )

    def cancel_order(self, order_id: str) -> BrokerOrderResult:
        return BrokerOrderResult(
            status=BrokerAdapterResultStatus.REJECTED,
            operation="cancel_order",
            client_request_id=order_id,
            message="etoro_live_mutation_disabled",
            payload={"reason": "etoro_live_mutation_disabled"},
        )

    def lookup_close_order(self, order_id: str) -> BrokerOrderResult:
        return BrokerOrderResult(
            status=BrokerAdapterResultStatus.REJECTED,
            operation="lookup_close_order",
            client_request_id=order_id,
            message="etoro_live_close_lookup_disabled",
            payload={"reason": "etoro_live_close_lookup_disabled"},
        )

    def close_position(self, position_id: str, quantity: float | None = None) -> BrokerOrderResult:
        return BrokerOrderResult(
            status=BrokerAdapterResultStatus.REJECTED,
            operation="close_position",
            client_request_id=position_id,
            message="etoro_live_mutation_disabled",
            payload={"reason": "etoro_live_mutation_disabled", "quantity": quantity},
        )

    def amend_position_protection(self, request: BrokerProtectionAmendRequest) -> BrokerOrderResult:
        return BrokerOrderResult(
            status=BrokerAdapterResultStatus.REJECTED,
            operation="amend_position_protection",
            client_request_id=request.client_order_id or request.broker_order_id,
            message="etoro_live_mutation_disabled",
            payload={"reason": "etoro_live_mutation_disabled"},
        )


class EtoroDemoBrokerAdapter(EtoroReadOnlyBrokerAdapter):
    def validate_credentials(self) -> BrokerCredentialValidation:
        try:
            payload = self.client.get_demo_pnl()
        except EtoroClientError as exc:
            return BrokerCredentialValidation(
                valid=False,
                permission_scope="invalid",
                account_mode="unknown",
                message=str(exc),
                raw_payload=exc.payload,
            )
        permissions = (
            [str(item) for item in payload.get("permissions", [])]
            if isinstance(payload.get("permissions"), list)
            else []
        )
        mode = str(payload.get("mode") or payload.get("accountMode") or "demo").lower()
        scope = "demo" if "demo_trading" in permissions or mode == "demo" else "read_only"
        return BrokerCredentialValidation(
            valid=True,
            permission_scope=scope,
            account_mode=mode,
            permissions=permissions,
            raw_payload=payload,
        )

    def get_capabilities(self) -> BrokerCapabilities:
        capabilities = super().get_capabilities()
        capabilities.account_mode = "demo"
        return capabilities

    def get_account_snapshot(self) -> BrokerPortfolioResult:
        try:
            payload = self.client.get_demo_pnl()
        except EtoroClientError as exc:
            return self._portfolio_error("get_account_snapshot", exc)
        portfolio = self._client_portfolio(payload)
        return BrokerPortfolioResult(
            status=BrokerAdapterResultStatus.SUCCESS,
            operation="get_account_snapshot",
            client_request_id=str(uuid4()),
            account=BrokerAccountSnapshot(
                equity=self._float(portfolio.get("equity") or portfolio.get("balance")),
                cash=self._float(
                    portfolio.get("cash")
                    or portfolio.get("availableCash")
                    or portfolio.get("credit")
                ),
                payload=payload,
            ),
            payload=payload,
        )

    def get_open_orders(self) -> BrokerPortfolioResult:
        try:
            payload = self.client.get_demo_portfolio()
        except EtoroClientError as exc:
            return self._portfolio_error("get_open_orders", exc)
        portfolio = self._client_portfolio(payload)
        return BrokerPortfolioResult(
            status=BrokerAdapterResultStatus.SUCCESS,
            operation="get_open_orders",
            client_request_id=str(uuid4()),
            items=self._list(portfolio.get("orders") or portfolio.get("openOrders")),
            payload=payload,
        )

    def get_open_positions(self) -> BrokerPortfolioResult:
        try:
            payload = self.client.get_demo_portfolio()
        except EtoroClientError as exc:
            return self._portfolio_error("get_open_positions", exc)
        portfolio = self._client_portfolio(payload)
        return BrokerPortfolioResult(
            status=BrokerAdapterResultStatus.SUCCESS,
            operation="get_open_positions",
            client_request_id=str(uuid4()),
            items=self._list(portfolio.get("positions") or portfolio.get("openPositions")),
            payload=payload,
        )

    def get_trade_history(self) -> BrokerTradeHistoryResult:
        try:
            payload = self.client.get_demo_trade_history()
        except EtoroClientError as exc:
            return BrokerTradeHistoryResult(
                status=BrokerAdapterResultStatus.FAILED,
                operation="get_trade_history",
                client_request_id=str(uuid4()),
                payload=exc.payload,
                message=str(exc),
            )
        trades = self._list(payload.get("trades") or payload.get("history") or payload.get("items"))
        return BrokerTradeHistoryResult(
            status=BrokerAdapterResultStatus.SUCCESS,
            operation="get_trade_history",
            client_request_id=str(uuid4()),
            trades=trades,
            payload=payload,
        )

    def submit_order(self, request: BrokerOrderRequest) -> BrokerOrderResult:
        rejection = self._validate_demo_order(request)
        if rejection is not None:
            return BrokerOrderResult(
                status=BrokerAdapterResultStatus.REJECTED,
                operation="submit_order",
                client_request_id=request.client_order_id,
                message=rejection,
            )
        payload = self._demo_order_payload(request)
        try:
            result = self.client.submit_demo_order(payload)
        except EtoroClientError as exc:
            if exc.error_type == "timeout":
                return BrokerOrderResult.ambiguous(
                    operation="submit_order",
                    client_request_id=request.client_order_id,
                    message=str(exc),
                )
            status = (
                BrokerAdapterResultStatus.RATE_LIMITED
                if exc.error_type == "rate_limited"
                else BrokerAdapterResultStatus.REJECTED
            )
            return BrokerOrderResult(
                status=status,
                operation="submit_order",
                client_request_id=request.client_order_id,
                payload=exc.payload,
                message=str(exc),
                retry_after_seconds=exc.retry_after_seconds,
            )
        return self._order_result("submit_order", request.client_order_id, result)

    def lookup_order(
        self, order_id: str | None = None, client_order_id: str | None = None
    ) -> BrokerOrderResult:
        request_id = client_order_id or order_id or str(uuid4())
        try:
            result = self.client.lookup_demo_order(order_id=order_id, reference_id=client_order_id)
        except EtoroClientError as exc:
            status = (
                BrokerAdapterResultStatus.NOT_FOUND
                if exc.status_code == 404
                else BrokerAdapterResultStatus.FAILED
            )
            return BrokerOrderResult(
                status=status,
                operation="lookup_order",
                client_request_id=request_id,
                payload=exc.payload,
                message=str(exc),
            )
        return self._order_result("lookup_order", request_id, result)

    def cancel_order(self, order_id: str) -> BrokerOrderResult:
        try:
            result = self.client.cancel_demo_order(order_id)
        except EtoroClientError as exc:
            if exc.error_type == "timeout":
                return BrokerOrderResult.ambiguous(
                    operation="cancel_order",
                    client_request_id=order_id,
                    message=str(exc),
                )
            return BrokerOrderResult(
                status=BrokerAdapterResultStatus.FAILED,
                operation="cancel_order",
                client_request_id=order_id,
                payload=exc.payload,
                message=str(exc),
            )
        return self._order_result("cancel_order", order_id, result)

    def lookup_close_order(self, order_id: str) -> BrokerOrderResult:
        try:
            result = self.client.lookup_demo_close_order(order_id)
        except EtoroClientError as exc:
            status = (
                BrokerAdapterResultStatus.NOT_FOUND
                if exc.status_code == 404
                else BrokerAdapterResultStatus.FAILED
            )
            return BrokerOrderResult(
                status=status,
                operation="lookup_close_order",
                client_request_id=order_id,
                payload=exc.payload,
                message=str(exc),
            )
        return self._order_result("lookup_close_order", order_id, result)

    def close_position(self, position_id: str, quantity: float | None = None) -> BrokerOrderResult:
        try:
            result = self.client.close_demo_position(position_id, quantity=quantity)
        except EtoroClientError as exc:
            if exc.error_type == "timeout":
                return BrokerOrderResult.ambiguous(
                    operation="close_position",
                    client_request_id=position_id,
                    message=str(exc),
                )
            return BrokerOrderResult(
                status=BrokerAdapterResultStatus.FAILED,
                operation="close_position",
                client_request_id=position_id,
                payload=exc.payload,
                message=str(exc),
            )
        return self._order_result("close_position", position_id, result)

    def amend_position_protection(self, request: BrokerProtectionAmendRequest) -> BrokerOrderResult:
        payload: dict[str, object] = {}
        if request.stop_loss is not None:
            payload["stopLossRate"] = request.stop_loss
        if request.take_profit is not None:
            payload["takeProfitRate"] = request.take_profit
        if not payload:
            return BrokerOrderResult(
                status=BrokerAdapterResultStatus.REJECTED,
                operation="amend_position_protection",
                client_request_id=request.client_order_id or request.broker_order_id,
                message="etoro_protective_levels_missing",
            )
        try:
            result = self.client.amend_demo_position_protection(request.broker_order_id, payload)
        except EtoroClientError as exc:
            if exc.error_type == "timeout":
                return BrokerOrderResult.ambiguous(
                    operation="amend_position_protection",
                    client_request_id=request.client_order_id or request.broker_order_id,
                    message=str(exc),
                )
            return BrokerOrderResult(
                status=BrokerAdapterResultStatus.FAILED,
                operation="amend_position_protection",
                client_request_id=request.client_order_id or request.broker_order_id,
                payload=exc.payload,
                message=str(exc),
            )
        return self._order_result(
            "amend_position_protection",
            request.client_order_id or request.broker_order_id,
            result,
        )

    @staticmethod
    def _validate_demo_order(request: BrokerOrderRequest) -> str | None:
        if request.side != "buy":
            return "etoro_short_not_supported_v1"
        if request.order_type not in {"market", "mkt"}:
            return "etoro_order_type_not_supported_v1"
        if request.leverage != 1:
            return "etoro_leverage_not_supported_v1"
        if not request.instrument_id:
            return "etoro_instrument_missing"
        if request.notional_amount is None or request.notional_amount <= 0:
            return "etoro_amount_missing"
        if request.stop_loss is None or request.take_profit is None:
            return "etoro_protective_levels_missing"
        return None

    @staticmethod
    def _demo_order_payload(request: BrokerOrderRequest) -> dict[str, object]:
        return {
            "action": "open",
            "transaction": "buy",
            "instrumentId": request.instrument_id,
            "settlementType": "real",
            "orderType": "mkt",
            "leverage": 1,
            "amount": float(request.notional_amount or 0.0),
            "orderCurrency": "usd",
            "stopLossRate": request.stop_loss,
            "takeProfitRate": request.take_profit,
            "stopLossType": "fixed",
        }

    @staticmethod
    def _order_result(
        operation: str, client_request_id: str, payload: dict[str, object]
    ) -> BrokerOrderResult:
        broker_order_id = (
            payload.get("orderId")
            or payload.get("orderID")
            or payload.get("order_id")
            or payload.get("id")
        )
        broker_position_id = (
            payload.get("positionId") or payload.get("positionID") or payload.get("position_id")
        )
        return BrokerOrderResult(
            status=BrokerAdapterResultStatus.SUCCESS,
            operation=operation,
            client_request_id=client_request_id,
            broker_order_id=str(broker_order_id) if broker_order_id is not None else None,
            broker_position_id=str(broker_position_id) if broker_position_id is not None else None,
            broker_status=str(payload.get("status") or ""),
            payload=payload,
        )
