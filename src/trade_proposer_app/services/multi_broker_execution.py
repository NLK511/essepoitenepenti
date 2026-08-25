from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol

from trade_proposer_app.domain.models import BrokerAccount, BrokerOrderExecution, RecommendationPlan
from trade_proposer_app.domain.statuses import TERMINAL_EXECUTION_STATUSES, ExecutionStatus
from trade_proposer_app.repositories.broker_account_safety import BrokerAccountSafetyRepository
from trade_proposer_app.repositories.broker_accounts import BrokerAccountRepository
from trade_proposer_app.repositories.broker_order_executions import BrokerOrderExecutionRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.brokers import (
    BrokerAdapter,
    BrokerAdapterResultStatus,
    BrokerOrderRequest,
)
from trade_proposer_app.services.execution_candidates import ExecutionCandidateBuilder
from trade_proposer_app.services.settings_domains import SettingsDomainService


class AccountAdapterFactory(Protocol):
    def for_account_id(self, broker_account_id: str) -> BrokerAdapter: ...


@dataclass(slots=True)
class MultiBrokerExecutionOutcome:
    summary: dict[str, object]
    orders: list[BrokerOrderExecution] = field(default_factory=list)


class MultiBrokerExecutionService:
    def __init__(
        self,
        *,
        settings: SettingsRepository,
        accounts: BrokerAccountRepository,
        executions: BrokerOrderExecutionRepository,
        adapter_factory: AccountAdapterFactory,
        safety: BrokerAccountSafetyRepository | None = None,
        latest_price_lookup: Callable[[str], float | None] | None = None,
    ) -> None:
        self.settings = settings
        self.accounts = accounts
        self.executions = executions
        self.adapter_factory = adapter_factory
        self.safety = safety
        self.latest_price_lookup = latest_price_lookup
        self.candidate_builder = ExecutionCandidateBuilder()

    def execute_plans(
        self,
        plans: list[RecommendationPlan],
        *,
        run_id: int | None = None,
        job_id: int | None = None,
    ) -> MultiBrokerExecutionOutcome:
        config = (
            SettingsDomainService(repository=self.settings)
            .execution_settings()
            .broker_order_execution
        )
        setting_map = self.settings.get_setting_map()
        global_halt_enabled = self._setting_bool(
            setting_map.get("broker_global_halt_enabled"), False
        )
        enabled_accounts = self.accounts.list_enabled()
        existing_orders = self.executions.list_all(limit=5000)
        orders: list[BrokerOrderExecution] = []
        skip_reasons: dict[str, int] = {}
        submitted = 0
        failed = 0
        duplicates = 0

        for plan in plans:
            for account in enabled_accounts:
                existing = self.executions.get_by_run_plan_and_account(
                    run_id,
                    plan.id or 0,
                    account.broker_account_id,
                )
                if existing is not None:
                    duplicates += 1
                    orders.append(existing)
                    continue
                order = self._evaluate_and_execute(
                    plan,
                    account=account,
                    config=config,
                    global_halt_enabled=global_halt_enabled,
                    existing_orders=existing_orders + orders,
                    run_id=run_id,
                    job_id=job_id,
                )
                orders.append(order)
                if order.status == ExecutionStatus.SKIPPED.value:
                    self._bump(skip_reasons, order.error_message or "skipped")
                elif order.status in {ExecutionStatus.FAILED.value, ExecutionStatus.REJECTED.value}:
                    failed += 1
                else:
                    submitted += 1

        summary = {
            "enabled": bool(config["enabled"]),
            "plan_count": len(plans),
            "broker_account_count": len(enabled_accounts),
            "candidate_count": len(orders),
            "submitted_order_count": submitted,
            "skipped_order_count": sum(skip_reasons.values()),
            "failed_order_count": failed,
            "duplicate_order_count": duplicates,
            "skips": [
                {"reason": reason, "count": count} for reason, count in sorted(skip_reasons.items())
            ],
            "broker_accounts": self._group_counts(orders),
            "orders": [order.model_dump(mode="json") for order in orders],
        }
        return MultiBrokerExecutionOutcome(summary=summary, orders=orders)

    def _evaluate_and_execute(
        self,
        plan: RecommendationPlan,
        *,
        account: BrokerAccount,
        config: dict[str, object],
        global_halt_enabled: bool,
        existing_orders: list[BrokerOrderExecution],
        run_id: int | None,
        job_id: int | None,
    ) -> BrokerOrderExecution:
        skip_reason = self._account_skip_reason(
            account=account,
            config=config,
            global_halt_enabled=global_halt_enabled,
        )
        candidate_result = self.candidate_builder.build(
            plan,
            notional_per_plan=self._notional_for_account(account, config),
            run_id=run_id,
            allow_amount_sizing=account.broker == "etoro" and account.account_mode == "demo",
        )
        if skip_reason is None and candidate_result.skip_reason is not None:
            skip_reason = candidate_result.skip_reason
        if skip_reason is None:
            skip_reason = self._pre_submit_risk_reason(
                plan=plan,
                account=account,
                candidate_notional=self._candidate_notional_for_account(
                    account, config, candidate_result
                ),
                existing_orders=existing_orders,
            )
        if candidate_result.candidate is None:
            return self._store_skip(
                plan,
                account=account,
                run_id=run_id,
                job_id=job_id,
                reason=skip_reason or "candidate_unavailable",
                entry_price=candidate_result.entry_price,
                stop_loss=candidate_result.stop_loss,
                take_profit=candidate_result.take_profit,
            )
        candidate = candidate_result.candidate
        adapter: BrokerAdapter | None = None
        instrument_id: str | None = None
        if skip_reason is None and account.broker == "etoro" and account.account_mode == "demo":
            try:
                adapter = self.adapter_factory.for_account_id(account.broker_account_id)
                skip_reason, instrument_id = self._etoro_demo_preflight(
                    adapter, symbol=plan.ticker
                )
            except Exception:
                skip_reason = "etoro_demo_preflight_failed"
        entry_price = self._normalize_price(candidate.entry_price)
        stop_loss = self._normalize_price(candidate.stop_loss)
        take_profit = self._normalize_price(candidate.take_profit)
        order_type = self._order_type_for_account(account)
        notional_amount = self._order_notional_amount(
            account=account,
            config=config,
            quantity=candidate.quantity,
            entry_price=entry_price,
            adjusted_notional_amount=candidate.notional_amount,
        )
        order = BrokerOrderExecution(
            broker_account_id=account.broker_account_id,
            broker=account.broker,
            account_mode=account.account_mode,
            recommendation_plan_id=plan.id or 0,
            recommendation_plan_ticker=plan.ticker,
            run_id=run_id,
            job_id=job_id,
            ticker=plan.ticker.upper(),
            action=plan.action,
            side=candidate.side,
            order_type=order_type,
            time_in_force="gtc",
            quantity=candidate.quantity,
            notional_amount=notional_amount,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            status=ExecutionStatus.SKIPPED.value if skip_reason else "queued",
            client_order_id=f"{candidate.client_order_id}-{account.broker_account_id}",
            request_payload=self._order_payload(
                candidate,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                account=account,
                notional_amount=notional_amount,
                instrument_id=instrument_id,
                skip_reason=skip_reason,
            ),
            error_message=skip_reason or "",
        )
        if skip_reason:
            return self.executions.create_candidate_once(order)
        try:
            if adapter is None:
                adapter = self.adapter_factory.for_account_id(account.broker_account_id)
            result = adapter.submit_order(self._broker_order_request(order))
            order.submitted_at = datetime.now(UTC)
            order.response_payload = result.payload
            order.broker_order_id = result.broker_order_id
            if result.status == BrokerAdapterResultStatus.AMBIGUOUS:
                order.status = ExecutionStatus.NEEDS_REVIEW.value
                order.error_message = result.message or "ambiguous_submit_order"
                if self.safety is not None:
                    self.safety.activate_circuit_breaker(
                        account.broker_account_id,
                        reason="ambiguous_submit_order",
                    )
            elif result.status == BrokerAdapterResultStatus.RATE_LIMITED:
                order.status = ExecutionStatus.FAILED.value
                order.error_message = result.message or "rate_limited_submit_order"
                if self.safety is not None:
                    self.safety.activate_circuit_breaker(
                        account.broker_account_id,
                        reason="rate_limited_submit_order",
                    )
            else:
                order.status = result.broker_status or (
                    "submitted" if result.is_success else "failed"
                )
                order.error_message = (
                    "" if result.is_success else result.message or str(result.status)
                )
        except Exception as exc:  # pragma: no cover - defensive adapter boundary
            order.status = ExecutionStatus.FAILED.value
            order.error_message = str(exc)
            order.submitted_at = datetime.now(UTC)
        return self.executions.create_candidate_once(order)

    @staticmethod
    def _account_skip_reason(
        *,
        account: BrokerAccount,
        config: dict[str, object],
        global_halt_enabled: bool,
    ) -> str | None:
        if not bool(config.get("enabled")):
            return "broker_execution_disabled"
        if global_halt_enabled:
            return "broker_global_halt_active"
        if not account.autonomous_execution_enabled:
            return "broker_account_autonomous_disabled"
        if account.halt_enabled:
            return "broker_account_halt_active"
        return None

    def _pre_submit_risk_reason(
        self,
        *,
        plan: RecommendationPlan,
        account: BrokerAccount,
        candidate_notional: float,
        existing_orders: list[BrokerOrderExecution],
    ) -> str | None:
        safety_reason = self._safety_reason(account)
        if safety_reason is not None:
            return safety_reason
        ticker = plan.ticker.upper()
        allowlist = {item.upper() for item in account.symbol_allowlist}
        denylist = {item.upper() for item in account.symbol_denylist}
        if ticker in denylist:
            return "broker_symbol_denied"
        if allowlist and ticker not in allowlist:
            return "broker_symbol_not_allowlisted"
        if account.broker == "etoro" and plan.action != "long":
            return "etoro_short_not_supported_v1"
        if account.max_position_notional_usd is not None and account.max_position_notional_usd > 0:
            if candidate_notional > float(account.max_position_notional_usd):
                return "risk_position_notional_limit_exceeded"
        account_active = self._active_orders_for_account(existing_orders, account.broker_account_id)
        active_count = len(account_active)
        active_notional = sum(
            max(0.0, float(order.notional_amount or 0.0)) for order in account_active
        )
        same_ticker_count = sum(1 for order in account_active if order.ticker.upper() == ticker)
        if account.max_open_positions is not None and account.max_open_positions > 0:
            if active_count + 1 > int(account.max_open_positions):
                return "risk_open_position_limit_exceeded"
        if account.max_open_notional_usd is not None and account.max_open_notional_usd > 0:
            if active_notional + candidate_notional > float(account.max_open_notional_usd):
                return "risk_open_notional_limit_exceeded"
        if (
            account.max_same_ticker_open_positions is not None
            and account.max_same_ticker_open_positions > 0
        ):
            if same_ticker_count + 1 > int(account.max_same_ticker_open_positions):
                return "risk_same_ticker_limit_exceeded"
        max_daily_order_count = self._risk_setting_int(account, "max_daily_order_count")
        if max_daily_order_count is not None and max_daily_order_count > 0:
            today_count = self._today_order_count(account_active)
            if today_count + 1 > max_daily_order_count:
                return "risk_daily_order_count_limit_exceeded"
        if account.broker == "etoro" and account.account_mode == "live":
            etoro_reason = self._etoro_live_gate_reason(account, plan=plan)
            if etoro_reason is not None:
                return etoro_reason
        if account.account_mode == "live":
            global_reason = self._global_live_risk_reason(
                candidate_notional=candidate_notional,
                existing_orders=existing_orders,
            )
            if global_reason is not None:
                return global_reason
        return None

    def _safety_reason(self, account: BrokerAccount) -> str | None:
        if self.safety is None:
            return None
        breaker = self.safety.get_circuit_breaker(account.broker_account_id)
        if breaker.active:
            return "broker_circuit_breaker_active"
        if account.account_mode != "live":
            return None
        drawdown = self.safety.get_drawdown_state(account.broker_account_id)
        if drawdown is None or not drawdown.trusted or drawdown.current_equity is None:
            return "risk_drawdown_evidence_unavailable"
        current_equity = float(drawdown.current_equity)
        daily_high = float(drawdown.daily_high_water_equity or current_equity)
        total_high = float(drawdown.total_high_water_equity or current_equity)
        daily_drawdown = max(0.0, daily_high - current_equity)
        total_drawdown = max(0.0, total_high - current_equity)
        max_daily_usd = self._risk_setting_float(account, "max_daily_drawdown_usd")
        if max_daily_usd is not None and max_daily_usd > 0 and daily_drawdown >= max_daily_usd:
            return "risk_daily_drawdown_limit_exceeded"
        max_daily_pct = self._risk_setting_float(account, "max_daily_drawdown_pct")
        daily_pct = (daily_drawdown / daily_high * 100.0) if daily_high > 0 else 0.0
        if max_daily_pct is not None and max_daily_pct > 0 and daily_pct >= max_daily_pct:
            return "risk_daily_drawdown_limit_exceeded"
        max_total_usd = self._risk_setting_float(account, "max_total_drawdown_usd")
        if max_total_usd is not None and max_total_usd > 0 and total_drawdown >= max_total_usd:
            return "risk_total_drawdown_limit_exceeded"
        max_total_pct = self._risk_setting_float(account, "max_total_drawdown_pct")
        total_pct = (total_drawdown / total_high * 100.0) if total_high > 0 else 0.0
        if max_total_pct is not None and max_total_pct > 0 and total_pct >= max_total_pct:
            return "risk_total_drawdown_limit_exceeded"
        return None

    def _etoro_live_gate_reason(
        self, account: BrokerAccount, *, plan: RecommendationPlan
    ) -> str | None:
        if not self._risk_setting_bool(account, "live_trading_enabled", False):
            return "etoro_live_trading_disabled"
        if not self._risk_setting_bool(account, "live_acknowledged", False):
            return "etoro_live_acknowledgement_missing"
        require_demo = self._risk_setting_bool(account, "require_demo_validation", True)
        demo_override = self._risk_setting_bool(account, "demo_validation_override", False)
        has_demo_artifact = bool(
            str(account.risk_settings.get("demo_validation_artifact_id") or "").strip()
        )
        if require_demo and not has_demo_artifact and not demo_override:
            return "etoro_demo_validation_missing"
        validation = account.validation_evidence or {}
        permission_scope = str(validation.get("permission_scope") or "").lower()
        permissions = validation.get("permissions")
        permission_set = (
            {str(item).lower() for item in permissions} if isinstance(permissions, list) else set()
        )
        if permission_scope != "real" and "real_trading" not in permission_set:
            return "etoro_permission_missing"
        price_reason = self._etoro_price_tolerance_reason(account, plan)
        if price_reason is not None:
            return price_reason
        if self._risk_setting_bool(account, "live_shadow_enabled", False):
            return "etoro_live_shadow_would_submit"
        return None

    def _etoro_price_tolerance_reason(
        self, account: BrokerAccount, plan: RecommendationPlan
    ) -> str | None:
        tolerance_pct = self._risk_setting_float(account, "max_entry_slippage_pct")
        if tolerance_pct is None or tolerance_pct <= 0:
            return None
        if self.latest_price_lookup is None:
            return "etoro_price_unavailable"
        latest_price = self.latest_price_lookup(plan.ticker.upper())
        if latest_price is None or latest_price <= 0:
            return "etoro_price_unavailable"
        low = plan.entry_price_low
        high = plan.entry_price_high
        if low is None or high is None or low <= 0 or high <= 0:
            return "etoro_price_unavailable"
        lower_bound = float(low) * (1.0 - float(tolerance_pct) / 100.0)
        upper_bound = float(high) * (1.0 + float(tolerance_pct) / 100.0)
        if float(latest_price) < lower_bound or float(latest_price) > upper_bound:
            return "etoro_price_outside_entry_tolerance"
        return None

    def _global_live_risk_reason(
        self,
        *,
        candidate_notional: float,
        existing_orders: list[BrokerOrderExecution],
    ) -> str | None:
        caps = self.settings.get_global_broker_risk_caps()
        max_live_notional = caps.get("global_max_live_open_notional_usd")
        if max_live_notional is not None and float(max_live_notional) > 0:
            active_live_notional = sum(
                max(0.0, float(order.notional_amount or 0.0))
                for order in existing_orders
                if order.account_mode == "live" and self._is_active_order(order)
            )
            if active_live_notional + candidate_notional > float(max_live_notional):
                return "risk_global_live_notional_limit_exceeded"
        max_live_order_count = caps.get("global_max_live_order_count_per_day")
        if max_live_order_count is not None and int(max_live_order_count) > 0:
            live_today_count = self._today_order_count(
                [order for order in existing_orders if order.account_mode == "live"]
            )
            if live_today_count + 1 > int(max_live_order_count):
                return "risk_global_live_order_count_limit_exceeded"
        return None

    @classmethod
    def _active_orders_for_account(
        cls,
        orders: list[BrokerOrderExecution],
        broker_account_id: str,
    ) -> list[BrokerOrderExecution]:
        return [
            order
            for order in orders
            if order.broker_account_id == broker_account_id and cls._is_active_order(order)
        ]

    @staticmethod
    def _is_active_order(order: BrokerOrderExecution) -> bool:
        return order.status not in TERMINAL_EXECUTION_STATUSES

    @staticmethod
    def _today_order_count(orders: list[BrokerOrderExecution]) -> int:
        today = datetime.now(UTC).date()
        return sum(
            1 for order in orders if order.created_at.astimezone(UTC).date() == today
        )

    @staticmethod
    def _risk_setting_int(account: BrokerAccount, key: str) -> int | None:
        value = account.risk_settings.get(key)
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _risk_setting_float(account: BrokerAccount, key: str) -> float | None:
        value = account.risk_settings.get(key)
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _risk_setting_bool(account: BrokerAccount, key: str, default: bool) -> bool:
        value = account.risk_settings.get(key)
        if value is None or value == "":
            return default
        if isinstance(value, bool):
            return value
        normalized = str(value).strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        return default

    @staticmethod
    def _candidate_notional(candidate_result: object) -> float:
        candidate = getattr(candidate_result, "candidate", None)
        if candidate is None:
            return 0.0
        return round(float(candidate.notional_amount), 4)

    @classmethod
    def _candidate_notional_for_account(
        cls,
        account: BrokerAccount,
        config: dict[str, object],
        candidate_result: object,
    ) -> float:
        if account.broker == "etoro" and account.account_mode == "demo":
            return cls._candidate_notional(candidate_result)
        return cls._candidate_notional(candidate_result)

    @staticmethod
    def _notional_for_account(account: BrokerAccount, config: dict[str, object]) -> float:
        if account.notional_cap_usd is not None and account.notional_cap_usd > 0:
            return float(account.notional_cap_usd)
        return float(config.get("notional_per_plan") or 0.0)

    @classmethod
    def _order_notional_amount(
        cls,
        *,
        account: BrokerAccount,
        config: dict[str, object],
        quantity: int,
        entry_price: float,
        adjusted_notional_amount: float | None = None,
    ) -> float:
        if account.broker == "etoro" and account.account_mode == "demo":
            return round(
                float(adjusted_notional_amount)
                if adjusted_notional_amount is not None
                else cls._notional_for_account(account, config),
                4,
            )
        return round(quantity * entry_price, 4)

    def _store_skip(
        self,
        plan: RecommendationPlan,
        *,
        account: BrokerAccount,
        run_id: int | None,
        job_id: int | None,
        reason: str,
        entry_price: float | None = None,
        stop_loss: float | None = None,
        take_profit: float | None = None,
    ) -> BrokerOrderExecution:
        order = BrokerOrderExecution(
            broker_account_id=account.broker_account_id,
            broker=account.broker,
            account_mode=account.account_mode,
            recommendation_plan_id=plan.id or 0,
            recommendation_plan_ticker=plan.ticker,
            run_id=run_id,
            job_id=job_id,
            ticker=plan.ticker.upper(),
            action=plan.action,
            side="buy" if plan.action == "long" else "sell" if plan.action == "short" else "",
            order_type="limit",
            time_in_force="gtc",
            quantity=0,
            notional_amount=0.0,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            status=ExecutionStatus.SKIPPED.value,
            client_order_id=(
                f"tp-run-{run_id or 'none'}-plan-{plan.id or 'new'}-"
                f"{plan.ticker.lower()}-{account.broker_account_id}"
            ),
            request_payload={
                "reason": reason,
                "would_submit": reason == "etoro_live_shadow_would_submit",
            },
            error_message=reason,
        )
        return self.executions.create_candidate_once(order)

    @staticmethod
    def _order_payload(
        candidate: object,
        *,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        account: BrokerAccount,
        notional_amount: float,
        instrument_id: str | None = None,
        skip_reason: str | None = None,
    ) -> dict[str, object]:
        if account.broker == "etoro" and account.account_mode == "demo":
            payload = {
                "symbol": candidate.plan.ticker.upper(),
                "side": candidate.side,
                "type": "market",
                "time_in_force": "gtc",
                "amount": notional_amount,
                "instrumentId": instrument_id or "",
                "stopLossRate": stop_loss,
                "takeProfitRate": take_profit,
                "client_order_id": candidate.client_order_id,
            }
        else:
            payload = {
                "symbol": candidate.plan.ticker.upper(),
                "qty": candidate.quantity,
                "side": candidate.side,
                "type": "limit",
                "time_in_force": "gtc",
                "limit_price": entry_price,
                "order_class": "bracket",
                "take_profit": {"limit_price": take_profit},
                "stop_loss": {"stop_price": stop_loss},
                "client_order_id": candidate.client_order_id,
            }
        if skip_reason == "etoro_live_shadow_would_submit":
            payload["would_submit"] = True
            payload["reason"] = skip_reason
        return payload

    @staticmethod
    def _normalize_price(price: float) -> float:
        value = Decimal(str(price))
        quantum = Decimal("0.01") if abs(value) >= 1 else Decimal("0.0001")
        return float(value.quantize(quantum, rounding=ROUND_HALF_UP))

    @staticmethod
    def _broker_order_request(order: BrokerOrderExecution) -> BrokerOrderRequest:
        return BrokerOrderRequest(
            client_order_id=order.client_order_id,
            symbol=order.ticker,
            side=order.side,
            order_type=order.order_type,
            quantity=order.quantity,
            notional_amount=order.notional_amount,
            instrument_id=(
                str(order.request_payload.get("instrumentId"))
                if order.request_payload.get("instrumentId")
                else None
            ),
            time_in_force=order.time_in_force,
            stop_loss=order.stop_loss,
            take_profit=order.take_profit,
            payload=order.request_payload,
        )

    @staticmethod
    def _order_type_for_account(account: BrokerAccount) -> str:
        if account.broker == "etoro" and account.account_mode == "demo":
            return "market"
        return "limit"

    @staticmethod
    def _etoro_demo_preflight(
        adapter: BrokerAdapter, *, symbol: str
    ) -> tuple[str | None, str | None]:
        validation = adapter.validate_credentials()
        if not validation.valid:
            return "etoro_demo_validation_failed", None
        if validation.account_mode not in {"demo", "unknown"}:
            return "etoro_demo_validation_wrong_environment", None
        instrument = adapter.resolve_instrument(symbol)
        if instrument.ambiguous:
            return "etoro_instrument_ambiguous", None
        if not instrument.instrument_id:
            return "etoro_instrument_missing", None
        if not instrument.tradable:
            return "etoro_instrument_unavailable", None
        return None, instrument.instrument_id

    @staticmethod
    def _bump(values: dict[str, int], key: str) -> None:
        values[key] = values.get(key, 0) + 1

    @staticmethod
    def _setting_bool(value: str | None, default: bool) -> bool:
        normalized = (value or "").strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        return default

    @staticmethod
    def _group_counts(orders: list[BrokerOrderExecution]) -> dict[str, dict[str, int]]:
        grouped: dict[str, dict[str, int]] = {}
        for order in orders:
            bucket = grouped.setdefault(
                order.broker_account_id,
                {"submitted": 0, "skipped": 0, "failed": 0, "duplicate_or_existing": 0},
            )
            if order.status == ExecutionStatus.SKIPPED.value:
                bucket["skipped"] += 1
            elif order.status in {ExecutionStatus.FAILED.value, ExecutionStatus.REJECTED.value}:
                bucket["failed"] += 1
            else:
                bucket["submitted"] += 1
        return grouped
