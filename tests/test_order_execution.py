import json
import unittest
import unittest.mock
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from trade_proposer_app.domain.enums import JobType, StrategyHorizon
from trade_proposer_app.domain.models import (
    BrokerOrderExecution,
    BrokerPosition,
    RecommendationPlan,
)
from trade_proposer_app.persistence.models import Base
from trade_proposer_app.repositories.broker_order_executions import BrokerOrderExecutionRepository
from trade_proposer_app.repositories.broker_positions import BrokerPositionRepository
from trade_proposer_app.repositories.broker_reconciliation_snapshots import (
    BrokerReconciliationSnapshotRepository,
)
from trade_proposer_app.repositories.jobs import JobRepository
from trade_proposer_app.repositories.observability_events import ObservabilityEventRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.repositories.runs import RunRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.alpaca_paper_client import (
    AlpacaOrderSubmissionResult,
    AlpacaPaperClient,
    AlpacaPaperClientError,
)
from trade_proposer_app.services.brokers import (
    BrokerAdapterResultStatus,
    BrokerCapabilities,
    BrokerOrderResult,
    FakeBrokerAdapter,
)
from trade_proposer_app.services.job_execution import JobExecutionService
from trade_proposer_app.services.order_execution import OrderExecutionService
from trade_proposer_app.services.performance_assessment import PerformanceAssessmentService


def create_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


class StubAlpacaClient:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []
        self.cancel_requests: list[str] = []
        self.close_requests: list[str] = []
        self.get_requests: list[str] = []

    def get_account(self) -> AlpacaOrderSubmissionResult:
        return AlpacaOrderSubmissionResult(status_code=200, payload={"buying_power": "100000"})

    def list_open_orders(self) -> AlpacaOrderSubmissionResult:
        return AlpacaOrderSubmissionResult(status_code=200, payload={"items": []})

    def list_open_positions(self) -> AlpacaOrderSubmissionResult:
        return AlpacaOrderSubmissionResult(status_code=200, payload={"items": []})

    def submit_order(self, payload: dict[str, object]) -> AlpacaOrderSubmissionResult:
        self.requests.append(payload)
        return AlpacaOrderSubmissionResult(
            status_code=200,
            payload={"id": "alpaca-order-1", "status": "accepted", "symbol": payload["symbol"]},
        )

    def get_order(self, order_id: str) -> AlpacaOrderSubmissionResult:
        self.get_requests.append(order_id)
        return AlpacaOrderSubmissionResult(
            status_code=200,
            payload={
                "id": order_id,
                "status": "filled",
                "order_class": "bracket",
                "filled_at": "2026-04-22T15:00:00Z",
                "submitted_at": "2026-04-22T14:30:00Z",
                "legs": [],
            },
        )

    def cancel_order(self, order_id: str) -> AlpacaOrderSubmissionResult:
        self.cancel_requests.append(order_id)
        return AlpacaOrderSubmissionResult(
            status_code=200,
            payload={"id": order_id, "status": "canceled"},
        )

    def amend_order(self, order_id: str, payload: dict[str, object]) -> AlpacaOrderSubmissionResult:
        self.requests.append({"order_id": order_id, **payload})
        return AlpacaOrderSubmissionResult(
            status_code=200,
            payload={"id": order_id, "status": "accepted", **payload},
        )

    def close_position(self, symbol: str) -> AlpacaOrderSubmissionResult:
        self.close_requests.append(symbol)
        return AlpacaOrderSubmissionResult(
            status_code=200,
            payload={"symbol": symbol, "status": "closed"},
        )


class FakeHttpxResponse:
    def __init__(self, status_code: int, payload: object, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self) -> object:
        return self._payload


class FakeHttpxClient:
    def __init__(self, responses: list[FakeHttpxResponse]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, object | None]] = []

    def request(
        self,
        method: str,
        url: str,
        content: object | None = None,
        headers: object | None = None,
        timeout: float | None = None,
    ):
        self.calls.append((method, url, content))
        if not self.responses:
            raise AssertionError("no fake response queued")
        return self.responses.pop(0)


class StubWatchlistOrchestrationService:
    def execute(self, watchlist, tickers, *, job_id=None, run_id=None, as_of=None):
        return {
            "summary": {"mode": "watchlist_orchestration", "ticker_count": len(tickers)},
            "artifact": {"mode": "watchlist_orchestration"},
            "ticker_generation": [],
            "warnings_found": False,
        }


class StubOrderExecutionService:
    def __init__(self) -> None:
        self.calls: list[list[RecommendationPlan]] = []

    def execute_plans(self, plans: list[RecommendationPlan], *, run_id=None, job_id=None):
        self.calls.append(list(plans))
        return type(
            "OrderExecutionOutcome",
            (),
            {
                "summary": {
                    "enabled": True,
                    "warnings_found": False,
                    "submitted_order_count": len(plans),
                },
                "orders": [],
            },
        )()


class OrderExecutionTests(unittest.TestCase):
    def test_order_execution_service_places_limit_bracket_orders_with_fixed_notional(self) -> None:
        session = create_session()
        try:
            settings = SettingsRepository(session)
            settings.set_order_execution_config(enabled=True, notional_per_plan=1000.0)
            observability = ObservabilityEventRepository(session)
            order_service = OrderExecutionService(
                settings=settings,
                executions=BrokerOrderExecutionRepository(session),
                client=StubAlpacaClient(),
                observability=observability,
            )
            plan = RecommendationPlan(
                id=1,
                ticker="AAPL",
                horizon=StrategyHorizon.ONE_WEEK,
                action="long",
                confidence_percent=82.0,
                entry_price_low=99.0,
                entry_price_high=101.0,
                stop_loss=95.0,
                take_profit=110.0,
                computed_at=datetime.now(timezone.utc),
                run_id=10,
                job_id=11,
            )

            outcome = order_service.execute_plans([plan], run_id=10, job_id=11)

            self.assertEqual(outcome.summary["submitted_order_count"], 1)
            self.assertEqual(outcome.summary["failed_order_count"], 0)
            self.assertEqual(outcome.summary["skipped_order_count"], 0)
            self.assertEqual(outcome.summary["warnings_found"], False)
            self.assertEqual(len(outcome.orders), 1)
            self.assertEqual(outcome.orders[0].quantity, 10)
            self.assertEqual(outcome.orders[0].status, "accepted")
            self.assertEqual(outcome.orders[0].broker_order_id, "alpaca-order-1")
            stored = BrokerOrderExecutionRepository(session).list_all()
            self.assertEqual(len(stored), 1)
            self.assertEqual(stored[0].side, "buy")
            self.assertEqual(stored[0].order_type, "limit")
            self.assertEqual(stored[0].request_payload["order_class"], "bracket")
            self.assertEqual(stored[0].request_payload["qty"], 10)
            events = observability.list_events(limit=10)
            self.assertEqual(
                [event["event_type"] for event in reversed(events)],
                [
                    "broker.reconciliation_snapshot_recorded",
                    "broker.order_submit_started",
                    "broker.order_submit_finished",
                ],
            )
            snapshots = BrokerReconciliationSnapshotRepository(session).list_latest(limit=10)
            self.assertEqual(len(snapshots), 1)
            self.assertEqual(snapshots[0].run_id, 10)
            self.assertEqual(snapshots[0].job_id, 11)
            self.assertEqual(snapshots[0].drift_severity, "ok")
            self.assertEqual(events[-1]["run_id"], 10)
            self.assertEqual(events[-1]["job_id"], 11)
        finally:
            session.close()

    def test_order_execution_service_resubmits_failed_order_with_fresh_client_order_id(
        self,
    ) -> None:
        session = create_session()
        try:
            settings = SettingsRepository(session)
            settings.set_order_execution_config(enabled=True, notional_per_plan=1000.0)
            settings.upsert_provider_credential("alpaca", "paper-key", "paper-secret")
            repository = BrokerOrderExecutionRepository(session)
            original = repository.create(
                BrokerOrderExecution(
                    broker="alpaca",
                    account_mode="paper",
                    recommendation_plan_id=1,
                    recommendation_plan_ticker="AAPL",
                    run_id=10,
                    job_id=11,
                    ticker="AAPL",
                    action="long",
                    side="buy",
                    order_type="limit",
                    time_in_force="gtc",
                    quantity=10,
                    notional_amount=1000.0,
                    entry_price=100.0,
                    stop_loss=95.0,
                    take_profit=110.0,
                    status="failed",
                    client_order_id="tp-run-10-plan-1-aapl",
                    request_payload={
                        "symbol": "AAPL",
                        "qty": 10,
                        "limit_price": 100.0,
                        "client_order_id": "tp-run-10-plan-1-aapl",
                    },
                    response_payload={"id": "alpaca-order-1", "status": "rejected"},
                    error_message="reject",
                )
            )
            client = StubAlpacaClient()
            service = OrderExecutionService(settings=settings, executions=repository, client=client)

            resubmitted = service.resubmit_execution(original.id or 0)

            self.assertEqual(len(client.requests), 1)
            self.assertEqual(client.requests[0]["limit_price"], 100.0)
            self.assertNotEqual(resubmitted.client_order_id, original.client_order_id)
            self.assertTrue(resubmitted.client_order_id.startswith(original.client_order_id))
            self.assertEqual(resubmitted.status, "accepted")
            self.assertEqual(resubmitted.broker_order_id, "alpaca-order-1")
            self.assertEqual(len(repository.list_all()), 2)
        finally:
            session.close()

    def test_order_execution_service_normalizes_prices_to_alpaca_tick_sizes(self) -> None:
        session = create_session()
        try:
            settings = SettingsRepository(session)
            settings.set_order_execution_config(enabled=True, notional_per_plan=1000.0)
            order_service = OrderExecutionService(
                settings=settings,
                executions=BrokerOrderExecutionRepository(session),
                client=StubAlpacaClient(),
            )
            plan = RecommendationPlan(
                id=2,
                ticker="FCX",
                horizon=StrategyHorizon.ONE_WEEK,
                action="long",
                confidence_percent=82.0,
                entry_price_low=67.6682,
                entry_price_high=67.6682,
                stop_loss=66.0934,
                take_profit=69.6859,
                computed_at=datetime.now(timezone.utc),
                run_id=10,
                job_id=11,
            )

            outcome = order_service.execute_plans([plan], run_id=10, job_id=11)

            self.assertEqual(outcome.summary["submitted_order_count"], 1)
            self.assertEqual(len(outcome.orders), 1)
            stored = BrokerOrderExecutionRepository(session).list_all()
            self.assertEqual(stored[0].request_payload["limit_price"], 67.67)
            self.assertEqual(stored[0].request_payload["take_profit"]["limit_price"], 69.69)
            self.assertEqual(stored[0].request_payload["stop_loss"]["stop_price"], 66.09)
        finally:
            session.close()

    def test_order_execution_service_refreshes_filled_order_and_cancels_open_order(self) -> None:
        session = create_session()
        try:
            settings = SettingsRepository(session)
            settings.upsert_provider_credential("alpaca", "paper-key", "paper-secret")
            repository = BrokerOrderExecutionRepository(session)
            refresh_target = repository.create(
                BrokerOrderExecution(
                    broker="alpaca",
                    account_mode="paper",
                    recommendation_plan_id=1,
                    recommendation_plan_ticker="AAPL",
                    run_id=10,
                    job_id=11,
                    ticker="AAPL",
                    action="long",
                    side="buy",
                    order_type="limit",
                    time_in_force="gtc",
                    quantity=10,
                    notional_amount=1000.0,
                    entry_price=100.0,
                    stop_loss=95.0,
                    take_profit=110.0,
                    status="submitted",
                    broker_order_id="alpaca-order-2",
                    client_order_id="tp-run-10-plan-1-aapl-live",
                    submitted_at=datetime.now(timezone.utc),
                    request_payload={
                        "symbol": "AAPL",
                        "qty": 10,
                        "limit_price": 100.0,
                        "client_order_id": "tp-run-10-plan-1-aapl-live",
                    },
                    response_payload={"id": "alpaca-order-2", "status": "accepted"},
                )
            )
            cancel_target = repository.create(
                BrokerOrderExecution(
                    broker="alpaca",
                    account_mode="paper",
                    recommendation_plan_id=2,
                    recommendation_plan_ticker="MSFT",
                    run_id=10,
                    job_id=11,
                    ticker="MSFT",
                    action="long",
                    side="buy",
                    order_type="limit",
                    time_in_force="gtc",
                    quantity=10,
                    notional_amount=1000.0,
                    entry_price=200.0,
                    stop_loss=190.0,
                    take_profit=220.0,
                    status="submitted",
                    broker_order_id="alpaca-order-3",
                    client_order_id="tp-run-10-plan-2-msft-live",
                    submitted_at=datetime.now(timezone.utc),
                    request_payload={
                        "symbol": "MSFT",
                        "qty": 10,
                        "limit_price": 200.0,
                        "client_order_id": "tp-run-10-plan-2-msft-live",
                    },
                    response_payload={"id": "alpaca-order-3", "status": "accepted"},
                )
            )
            client = StubAlpacaClient()
            service = OrderExecutionService(settings=settings, executions=repository, client=client)

            refreshed = service.refresh_execution(refresh_target.id or 0)
            canceled = service.cancel_execution(cancel_target.id or 0)

            self.assertEqual(client.get_requests, ["alpaca-order-2"])
            self.assertEqual(refreshed.status, "open")
            self.assertIsNotNone(refreshed.filled_at)
            self.assertEqual(client.cancel_requests, ["alpaca-order-3"])
            self.assertEqual(canceled.status, "canceled")
            self.assertEqual(canceled.response_payload["status"], "canceled")
            self.assertIsNotNone(canceled.canceled_at)
            self.assertEqual(repository.get(cancel_target.id or 0).status, "canceled")
        finally:
            session.close()

    def test_order_execution_service_classifies_filled_bracket_exit_legs(self) -> None:
        class ExitLegClient(StubAlpacaClient):
            def __init__(self, payload: dict[str, object]) -> None:
                super().__init__()
                self.payload = payload

            def get_order(self, order_id: str) -> AlpacaOrderSubmissionResult:
                self.get_requests.append(order_id)
                return AlpacaOrderSubmissionResult(
                    status_code=200, payload={"id": order_id, **self.payload}
                )

        for leg_type, expected_status in (("limit", "win"), ("stop", "loss")):
            session = create_session()
            try:
                settings = SettingsRepository(session)
                settings.upsert_provider_credential("alpaca", "paper-key", "paper-secret")
                repository = BrokerOrderExecutionRepository(session)
                stored = repository.create(
                    BrokerOrderExecution(
                        broker="alpaca",
                        account_mode="paper",
                        recommendation_plan_id=1,
                        recommendation_plan_ticker="AAPL",
                        ticker="AAPL",
                        action="long",
                        side="buy",
                        order_type="limit",
                        quantity=10,
                        notional_amount=1000.0,
                        entry_price=100.0,
                        stop_loss=95.0,
                        take_profit=110.0,
                        status="open",
                        broker_order_id=f"alpaca-order-{leg_type}",
                        client_order_id=f"tp-run-10-plan-1-aapl-{leg_type}",
                        request_payload={"symbol": "AAPL"},
                        response_payload={"id": f"alpaca-order-{leg_type}", "status": "filled"},
                    )
                )
                client = ExitLegClient(
                    {
                        "status": "filled",
                        "filled_at": "2026-04-22T14:30:00Z",
                        "legs": [
                            {
                                "id": f"exit-{leg_type}",
                                "type": leg_type,
                                "status": "filled",
                                "filled_at": "2026-04-22T15:00:00Z",
                            }
                        ],
                    }
                )
                service = OrderExecutionService(
                    settings=settings, executions=repository, client=client
                )

                refreshed = service.refresh_execution(stored.id or 0)

                self.assertEqual(refreshed.status, expected_status)
                self.assertIsNotNone(refreshed.filled_at)
            finally:
                session.close()

    def test_order_execution_service_persists_open_protective_order_leg_evidence(self) -> None:
        class OpenBracketClient(StubAlpacaClient):
            def get_order(self, order_id: str) -> AlpacaOrderSubmissionResult:
                self.get_requests.append(order_id)
                return AlpacaOrderSubmissionResult(
                    status_code=200,
                    payload={
                        "id": order_id,
                        "status": "filled",
                        "filled_qty": "10",
                        "filled_avg_price": "100.00",
                        "filled_at": "2026-04-22T14:30:00Z",
                        "order_class": "bracket",
                        "legs": [
                            {
                                "id": "take-profit-leg-open",
                                "type": "limit",
                                "status": "new",
                                "limit_price": "110.00",
                            },
                            {
                                "id": "stop-loss-leg-open",
                                "type": "stop",
                                "status": "new",
                                "stop_price": "95.00",
                            },
                        ],
                    },
                )

        session = create_session()
        try:
            settings = SettingsRepository(session)
            settings.upsert_provider_credential("alpaca", "paper-key", "paper-secret")
            orders = BrokerOrderExecutionRepository(session)
            positions = BrokerPositionRepository(session)
            stored = orders.create(
                BrokerOrderExecution(
                    broker="alpaca",
                    account_mode="paper",
                    recommendation_plan_id=1,
                    recommendation_plan_ticker="AAPL",
                    ticker="AAPL",
                    action="long",
                    side="buy",
                    order_type="limit",
                    quantity=10,
                    notional_amount=1000.0,
                    entry_price=100.0,
                    stop_loss=95.0,
                    take_profit=110.0,
                    status="open",
                    broker_order_id="alpaca-order-open-protected",
                    client_order_id="tp-run-10-plan-1-aapl-open-protected",
                    request_payload={"symbol": "AAPL"},
                    response_payload={"id": "alpaca-order-open-protected", "status": "filled"},
                )
            )
            service = OrderExecutionService(
                settings=settings,
                executions=orders,
                positions=positions,
                client=OpenBracketClient(),
            )

            refreshed = service.refresh_execution(stored.id or 0)
            position = positions.get_by_order_execution_id(refreshed.id or 0)

            self.assertIsNotNone(position)
            self.assertEqual(position.status, "open")
            self.assertIsNone(position.exit_order_id)
            self.assertEqual(position.stop_loss_order_id, "stop-loss-leg-open")
            self.assertEqual(position.stop_loss_order_status, "new")
            self.assertEqual(position.stop_loss_order_price, 95.0)
            self.assertEqual(position.take_profit_order_id, "take-profit-leg-open")
            self.assertEqual(position.take_profit_order_status, "new")
            self.assertEqual(position.take_profit_order_price, 110.0)
            self.assertEqual(position.protective_orders_source, "broker_order_legs")
            self.assertIsNotNone(position.protective_orders_verified_at)
        finally:
            session.close()

    def test_order_execution_service_persists_position_lifecycle_and_realized_pnl(self) -> None:
        class ExitLegClient(StubAlpacaClient):
            def get_order(self, order_id: str) -> AlpacaOrderSubmissionResult:
                self.get_requests.append(order_id)
                return AlpacaOrderSubmissionResult(
                    status_code=200,
                    payload={
                        "id": order_id,
                        "status": "filled",
                        "filled_qty": "10",
                        "filled_avg_price": "100.00",
                        "filled_at": "2026-04-22T14:30:00Z",
                        "legs": [
                            {
                                "id": "take-profit-leg",
                                "type": "limit",
                                "status": "filled",
                                "filled_qty": "10",
                                "filled_avg_price": "110.00",
                                "filled_at": "2026-04-22T15:00:00Z",
                            },
                            {"id": "stop-leg", "type": "stop", "status": "canceled"},
                        ],
                    },
                )

        session = create_session()
        try:
            settings = SettingsRepository(session)
            settings.upsert_provider_credential("alpaca", "paper-key", "paper-secret")
            orders = BrokerOrderExecutionRepository(session)
            positions = BrokerPositionRepository(session)
            stored = orders.create(
                BrokerOrderExecution(
                    broker="alpaca",
                    account_mode="paper",
                    recommendation_plan_id=1,
                    recommendation_plan_ticker="AAPL",
                    ticker="AAPL",
                    action="long",
                    side="buy",
                    order_type="limit",
                    quantity=10,
                    notional_amount=1000.0,
                    entry_price=100.0,
                    stop_loss=95.0,
                    take_profit=110.0,
                    status="open",
                    broker_order_id="alpaca-order-win",
                    client_order_id="tp-run-10-plan-1-aapl-win",
                    request_payload={"symbol": "AAPL"},
                    response_payload={"id": "alpaca-order-win", "status": "filled"},
                )
            )
            service = OrderExecutionService(
                settings=settings, executions=orders, positions=positions, client=ExitLegClient()
            )

            refreshed = service.refresh_execution(stored.id or 0)
            position = positions.get_by_order_execution_id(refreshed.id or 0)

            self.assertEqual(refreshed.status, "win")
            self.assertIsNotNone(position)
            self.assertEqual(position.status, "win")
            self.assertEqual(position.exit_reason, "take_profit")
            self.assertEqual(position.current_quantity, 0)
            self.assertEqual(position.realized_pnl, 100.0)
            self.assertEqual(position.realized_return_pct, 10.0)
            self.assertEqual(position.realized_r_multiple, 2.0)
        finally:
            session.close()

    def test_performance_assessment_includes_broker_resolved_outcomes(self) -> None:
        session = create_session()
        try:
            plans = RecommendationPlanRepository(session)
            first_plan = plans.create_plan(
                RecommendationPlan(
                    ticker="AAPL",
                    action="long",
                    confidence_percent=70.0,
                    thesis_summary="Broker winner",
                )
            )
            second_plan = plans.create_plan(
                RecommendationPlan(
                    ticker="MSFT",
                    action="long",
                    confidence_percent=60.0,
                    thesis_summary="Broker loser",
                )
            )
            BrokerPositionRepository(session).create(
                BrokerPosition(
                    broker_order_execution_id=1,
                    broker="alpaca",
                    account_mode="paper",
                    recommendation_plan_id=first_plan.id or 0,
                    recommendation_plan_ticker="AAPL",
                    ticker="AAPL",
                    action="long",
                    side="buy",
                    quantity=10,
                    current_quantity=0,
                    status="win",
                    entry_avg_price=100.0,
                    exit_avg_price=110.0,
                    exit_filled_at=datetime.now(timezone.utc),
                    realized_pnl=100.0,
                    realized_return_pct=10.0,
                )
            )
            BrokerPositionRepository(session).create(
                BrokerPosition(
                    broker_order_execution_id=2,
                    broker="alpaca",
                    account_mode="paper",
                    recommendation_plan_id=second_plan.id or 0,
                    recommendation_plan_ticker="MSFT",
                    ticker="MSFT",
                    action="long",
                    side="buy",
                    quantity=10,
                    current_quantity=0,
                    status="loss",
                    entry_avg_price=100.0,
                    exit_avg_price=95.0,
                    exit_filled_at=datetime.now(timezone.utc),
                    realized_pnl=-50.0,
                    realized_return_pct=-5.0,
                )
            )

            windows = PerformanceAssessmentService(session)._windowed_assessments()
            one_month = next(item for item in windows if item["window"] == "1M")

            self.assertEqual(one_month["broker_closed_positions"], 2)
            self.assertEqual(one_month["broker_wins"], 1)
            self.assertEqual(one_month["broker_losses"], 1)
            self.assertEqual(one_month["broker_win_rate_percent"], 50.0)
            self.assertEqual(one_month["broker_realized_pnl"], 50.0)
            self.assertEqual(one_month["overall_win_rate_percent"], 50.0)
        finally:
            session.close()

    def test_order_execution_service_sync_open_executions_refreshes_active_orders(self) -> None:
        session = create_session()
        try:
            settings = SettingsRepository(session)
            settings.upsert_provider_credential("alpaca", "paper-key", "paper-secret")
            repository = BrokerOrderExecutionRepository(session)
            repository.create(
                BrokerOrderExecution(
                    broker="alpaca",
                    account_mode="paper",
                    recommendation_plan_id=1,
                    recommendation_plan_ticker="AAPL",
                    run_id=10,
                    job_id=11,
                    ticker="AAPL",
                    action="long",
                    side="buy",
                    order_type="limit",
                    time_in_force="gtc",
                    quantity=10,
                    notional_amount=1000.0,
                    entry_price=100.0,
                    stop_loss=95.0,
                    take_profit=110.0,
                    status="filled",
                    broker_order_id="alpaca-order-2",
                    client_order_id="tp-run-10-plan-1-aapl-live",
                    submitted_at=datetime.now(timezone.utc),
                    request_payload={
                        "symbol": "AAPL",
                        "qty": 10,
                        "limit_price": 100.0,
                        "client_order_id": "tp-run-10-plan-1-aapl-live",
                    },
                    response_payload={"id": "alpaca-order-2", "status": "filled"},
                )
            )
            repository.create(
                BrokerOrderExecution(
                    broker="alpaca",
                    account_mode="paper",
                    recommendation_plan_id=2,
                    recommendation_plan_ticker="MSFT",
                    run_id=10,
                    job_id=11,
                    ticker="MSFT",
                    action="long",
                    side="buy",
                    order_type="limit",
                    time_in_force="gtc",
                    quantity=10,
                    notional_amount=1000.0,
                    entry_price=200.0,
                    stop_loss=190.0,
                    take_profit=220.0,
                    status="canceled",
                    broker_order_id="alpaca-order-3",
                    client_order_id="tp-run-10-plan-2-msft-live",
                    submitted_at=datetime.now(timezone.utc),
                    canceled_at=datetime.now(timezone.utc),
                    request_payload={
                        "symbol": "MSFT",
                        "qty": 10,
                        "limit_price": 200.0,
                        "client_order_id": "tp-run-10-plan-2-msft-live",
                    },
                    response_payload={"id": "alpaca-order-3", "status": "canceled"},
                )
            )
            client = StubAlpacaClient()
            observability = ObservabilityEventRepository(session)
            service = OrderExecutionService(
                settings=settings, executions=repository, client=client, observability=observability
            )

            outcome = service.sync_open_executions()

            self.assertEqual(outcome.summary["synced_count"], 1)
            self.assertEqual(outcome.summary["skipped_count"], 1)
            self.assertEqual(client.get_requests, ["alpaca-order-2"])
            self.assertEqual(
                repository.get_by_client_order_id("alpaca", "tp-run-10-plan-1-aapl-live").status,
                "open",
            )
            events = observability.list_events(limit=10)
            self.assertEqual(
                [event["event_type"] for event in reversed(events)],
                [
                    "broker.order_sync_started",
                    "broker.order_refresh_started",
                    "broker.order_refresh_finished",
                    "broker.order_sync_finished",
                ],
            )
            refresh_started = next(
                event for event in events if event["event_type"] == "broker.order_refresh_started"
            )
            self.assertEqual(refresh_started["run_id"], 10)
            self.assertEqual(refresh_started["job_id"], 11)
        finally:
            session.close()

    def test_order_execution_service_amends_open_order_levels(self) -> None:
        session = create_session()
        try:
            settings = SettingsRepository(session)
            settings.upsert_provider_credential("alpaca", "paper-key", "paper-secret")
            repository = BrokerOrderExecutionRepository(session)
            stored = repository.create(
                BrokerOrderExecution(
                    broker="alpaca",
                    account_mode="paper",
                    recommendation_plan_id=1,
                    recommendation_plan_ticker="AAPL",
                    run_id=10,
                    job_id=11,
                    ticker="AAPL",
                    action="long",
                    side="buy",
                    order_type="limit",
                    time_in_force="gtc",
                    quantity=10,
                    notional_amount=1000.0,
                    entry_price=100.0,
                    stop_loss=95.0,
                    take_profit=110.0,
                    status="submitted",
                    broker_order_id="alpaca-order-9",
                    client_order_id="tp-run-10-plan-1-aapl-open",
                    submitted_at=datetime.now(timezone.utc),
                    request_payload={"symbol": "AAPL", "qty": 10},
                    response_payload={"id": "alpaca-order-9", "status": "accepted"},
                )
            )
            client = StubAlpacaClient()
            service = OrderExecutionService(settings=settings, executions=repository, client=client)

            amended = service.amend_execution(stored.id or 0, stop_loss=97.5, take_profit=108.5)

            self.assertEqual(client.get_requests, ["alpaca-order-9"])
            self.assertEqual(client.requests[-1]["order_id"], "alpaca-order-9")
            self.assertEqual(client.requests[-1]["stop_loss"]["stop_price"], 97.5)
            self.assertEqual(client.requests[-1]["take_profit"]["limit_price"], 108.5)
            self.assertEqual(amended.stop_loss, 97.5)
            self.assertEqual(amended.take_profit, 108.5)
        finally:
            session.close()

    def test_order_execution_service_amends_through_broker_adapter_contract(self) -> None:
        session = create_session()
        try:
            settings = SettingsRepository(session)
            repository = BrokerOrderExecutionRepository(session)
            stored = repository.create(
                BrokerOrderExecution(
                    broker="fake",
                    account_mode="paper",
                    recommendation_plan_id=1,
                    recommendation_plan_ticker="AAPL",
                    ticker="AAPL",
                    action="long",
                    side="buy",
                    order_type="limit",
                    time_in_force="gtc",
                    quantity=10,
                    notional_amount=1000.0,
                    entry_price=100.0,
                    stop_loss=95.0,
                    take_profit=110.0,
                    status="submitted",
                    broker_order_id="fake-order-9",
                    client_order_id="tp-run-10-plan-1-aapl-open",
                    request_payload={"order_class": "bracket"},
                    response_payload={"id": "fake-order-9", "status": "accepted"},
                )
            )
            adapter = FakeBrokerAdapter(
                capabilities=BrokerCapabilities(
                    broker="fake", account_mode="paper", supports_amend_protection=True
                )
            )
            adapter.orders["fake-order-9"] = BrokerOrderResult(
                status=BrokerAdapterResultStatus.SUCCESS,
                operation="lookup_order",
                client_request_id="fake-order-9",
                broker_order_id="fake-order-9",
                broker_status="accepted",
                payload={"id": "fake-order-9", "status": "accepted", "order_class": "bracket"},
            )
            service = OrderExecutionService(
                settings=settings, executions=repository, adapter=adapter
            )

            amended = service.amend_execution(stored.id or 0, stop_loss=97.5, take_profit=108.5)

            self.assertEqual(amended.stop_loss, 97.5)
            self.assertEqual(amended.take_profit, 108.5)
            self.assertEqual(amended.response_payload["status"], "accepted")
        finally:
            session.close()

    def test_order_execution_service_rejects_non_bracket_amendments(self) -> None:
        session = create_session()
        try:
            settings = SettingsRepository(session)
            settings.upsert_provider_credential("alpaca", "paper-key", "paper-secret")
            repository = BrokerOrderExecutionRepository(session)
            stored = repository.create(
                BrokerOrderExecution(
                    broker="alpaca",
                    account_mode="paper",
                    recommendation_plan_id=1,
                    recommendation_plan_ticker="AAPL",
                    run_id=10,
                    job_id=11,
                    ticker="AAPL",
                    action="long",
                    side="buy",
                    order_type="limit",
                    time_in_force="gtc",
                    quantity=10,
                    notional_amount=1000.0,
                    entry_price=100.0,
                    stop_loss=95.0,
                    take_profit=110.0,
                    status="submitted",
                    broker_order_id="alpaca-order-9",
                    client_order_id="tp-run-10-plan-1-aapl-open",
                    submitted_at=datetime.now(timezone.utc),
                    request_payload={"symbol": "AAPL", "qty": 10},
                    response_payload={"id": "alpaca-order-9", "status": "accepted"},
                )
            )

            class NonBracketAmendClient(StubAlpacaClient):
                def get_order(self, order_id: str) -> AlpacaOrderSubmissionResult:
                    self.get_requests.append(order_id)
                    return AlpacaOrderSubmissionResult(
                        status_code=200, payload={"id": order_id, "status": "accepted"}
                    )

            service = OrderExecutionService(
                settings=settings, executions=repository, client=NonBracketAmendClient()
            )

            with self.assertRaises(ValueError):
                service.amend_execution(stored.id or 0, stop_loss=97.5)
        finally:
            session.close()

    def test_order_execution_service_rejects_invalid_manual_actions(self) -> None:
        session = create_session()
        try:
            settings = SettingsRepository(session)
            repository = BrokerOrderExecutionRepository(session)
            failed = repository.create(
                BrokerOrderExecution(
                    broker="alpaca",
                    account_mode="paper",
                    recommendation_plan_id=1,
                    recommendation_plan_ticker="AAPL",
                    run_id=10,
                    job_id=11,
                    ticker="AAPL",
                    action="long",
                    side="buy",
                    order_type="limit",
                    time_in_force="gtc",
                    quantity=0,
                    notional_amount=0.0,
                    status="failed",
                    client_order_id="tp-run-10-plan-1-aapl-failed",
                    request_payload={"reason": "reject"},
                    response_payload={},
                    error_message="reject",
                )
            )
            submitted = repository.create(
                BrokerOrderExecution(
                    broker="alpaca",
                    account_mode="paper",
                    recommendation_plan_id=1,
                    recommendation_plan_ticker="AAPL",
                    run_id=10,
                    job_id=11,
                    ticker="AAPL",
                    action="long",
                    side="buy",
                    order_type="limit",
                    time_in_force="gtc",
                    quantity=10,
                    notional_amount=1000.0,
                    status="submitted",
                    client_order_id="tp-run-10-plan-1-aapl-open",
                    broker_order_id="alpaca-order-3",
                    request_payload={
                        "symbol": "AAPL",
                        "qty": 10,
                        "limit_price": 100.0,
                        "client_order_id": "tp-run-10-plan-1-aapl-open",
                    },
                    response_payload={"id": "alpaca-order-3", "status": "accepted"},
                )
            )
            incomplete = repository.create(
                BrokerOrderExecution(
                    broker="alpaca",
                    account_mode="paper",
                    recommendation_plan_id=1,
                    recommendation_plan_ticker="AAPL",
                    run_id=10,
                    job_id=11,
                    ticker="AAPL",
                    action="long",
                    side="buy",
                    order_type="limit",
                    time_in_force="gtc",
                    quantity=10,
                    notional_amount=1000.0,
                    status="failed",
                    client_order_id="tp-run-10-plan-1-aapl-incomplete",
                    request_payload={"symbol": "AAPL"},
                    response_payload={},
                    error_message="reject",
                )
            )
            canceled = repository.create(
                BrokerOrderExecution(
                    broker="alpaca",
                    account_mode="paper",
                    recommendation_plan_id=1,
                    recommendation_plan_ticker="AAPL",
                    run_id=10,
                    job_id=11,
                    ticker="AAPL",
                    action="long",
                    side="buy",
                    order_type="limit",
                    time_in_force="gtc",
                    quantity=10,
                    notional_amount=1000.0,
                    status="canceled",
                    broker_order_id="alpaca-order-4",
                    client_order_id="tp-run-10-plan-1-aapl-canceled",
                    request_payload={
                        "symbol": "AAPL",
                        "qty": 10,
                        "limit_price": 100.0,
                        "client_order_id": "tp-run-10-plan-1-aapl-canceled",
                    },
                    response_payload={"id": "alpaca-order-4", "status": "canceled"},
                )
            )
            filled = repository.create(
                BrokerOrderExecution(
                    broker="alpaca",
                    account_mode="paper",
                    recommendation_plan_id=1,
                    recommendation_plan_ticker="AAPL",
                    run_id=10,
                    job_id=11,
                    ticker="AAPL",
                    action="long",
                    side="buy",
                    order_type="limit",
                    time_in_force="gtc",
                    quantity=10,
                    notional_amount=1000.0,
                    status="filled",
                    broker_order_id="alpaca-order-5",
                    client_order_id="tp-run-10-plan-1-aapl-filled",
                    request_payload={
                        "symbol": "AAPL",
                        "qty": 10,
                        "limit_price": 100.0,
                        "client_order_id": "tp-run-10-plan-1-aapl-filled",
                    },
                    response_payload={"id": "alpaca-order-5", "status": "filled"},
                )
            )
            no_id = repository.create(
                BrokerOrderExecution(
                    broker="alpaca",
                    account_mode="paper",
                    recommendation_plan_id=1,
                    recommendation_plan_ticker="AAPL",
                    run_id=10,
                    job_id=11,
                    ticker="AAPL",
                    action="long",
                    side="buy",
                    order_type="limit",
                    time_in_force="gtc",
                    quantity=10,
                    notional_amount=1000.0,
                    status="submitted",
                    client_order_id="tp-run-10-plan-1-aapl-no-id",
                    request_payload={
                        "symbol": "AAPL",
                        "qty": 10,
                        "limit_price": 100.0,
                        "client_order_id": "tp-run-10-plan-1-aapl-no-id",
                    },
                    response_payload={"id": "alpaca-order-6", "status": "accepted"},
                )
            )
            service = OrderExecutionService(
                settings=settings, executions=repository, client=StubAlpacaClient()
            )

            with self.assertRaises(ValueError):
                service.resubmit_execution(submitted.id or 0)
            with self.assertRaises(ValueError):
                service.resubmit_execution(incomplete.id or 0)
            with self.assertRaises(ValueError):
                service.cancel_execution(failed.id or 0)
            with self.assertRaises(ValueError):
                service.cancel_execution(canceled.id or 0)
            with self.assertRaises(ValueError):
                service.cancel_execution(filled.id or 0)
            with self.assertRaises(ValueError):
                service.cancel_execution(no_id.id or 0)
        finally:
            session.close()

    def test_order_execution_service_skips_when_disabled(self) -> None:
        session = create_session()
        try:
            settings = SettingsRepository(session)
            settings.set_order_execution_config(enabled=False, notional_per_plan=1000.0)
            service = OrderExecutionService(
                settings=settings,
                executions=BrokerOrderExecutionRepository(session),
                client=StubAlpacaClient(),
            )
            plan = RecommendationPlan(
                id=1,
                ticker="AAPL",
                horizon=StrategyHorizon.ONE_WEEK,
                action="long",
                confidence_percent=80.0,
                entry_price_low=99.0,
                entry_price_high=101.0,
                stop_loss=95.0,
                take_profit=110.0,
                computed_at=datetime.now(timezone.utc),
            )

            outcome = service.execute_plans([plan])

            self.assertEqual(outcome.summary["skipped_order_count"], 1)
            self.assertEqual(outcome.summary["submitted_order_count"], 0)
            self.assertEqual(outcome.summary["orders"], [])
            self.assertEqual(outcome.orders, [])
            self.assertEqual(BrokerOrderExecutionRepository(session).list_all(), [])
        finally:
            session.close()

    def test_order_execution_service_skips_when_risk_manager_blocks_candidate(self) -> None:
        session = create_session()
        try:
            settings = SettingsRepository(session)
            settings.set_order_execution_config(enabled=True, notional_per_plan=1000.0)
            settings.set_risk_management_config(
                enabled=True,
                max_daily_realized_loss_usd=50.0,
                max_open_positions=3,
                max_open_notional_usd=3000.0,
                max_position_notional_usd=500.0,
                max_same_ticker_open_positions=1,
                max_consecutive_losses=3,
            )
            client = StubAlpacaClient()
            service = OrderExecutionService(
                settings=settings,
                executions=BrokerOrderExecutionRepository(session),
                positions=BrokerPositionRepository(session),
                client=client,
            )
            plan = RecommendationPlan(
                id=1,
                ticker="AAPL",
                horizon=StrategyHorizon.ONE_WEEK,
                action="long",
                confidence_percent=80.0,
                entry_price_low=99.0,
                entry_price_high=101.0,
                stop_loss=95.0,
                take_profit=110.0,
                computed_at=datetime.now(timezone.utc),
            )

            outcome = service.execute_plans([plan])
            stored = BrokerOrderExecutionRepository(session).list_all(limit=10)

            self.assertEqual(outcome.summary["submitted_order_count"], 0)
            self.assertEqual(outcome.summary["skipped_order_count"], 1)
            self.assertEqual(client.requests, [])
            self.assertEqual(stored[0].status, "skipped")
            self.assertIn("risk_position_notional_limit_exceeded", stored[0].error_message)
        finally:
            session.close()

    def test_order_execution_service_skips_when_credential_is_missing(self) -> None:
        session = create_session()
        try:
            settings = SettingsRepository(session)
            settings.set_order_execution_config(enabled=True, notional_per_plan=1000.0)
            settings.get_provider_credential_map = lambda: {}  # type: ignore[method-assign]
            service = OrderExecutionService(
                settings=settings, executions=BrokerOrderExecutionRepository(session)
            )
            plan = RecommendationPlan(
                id=1,
                ticker="AAPL",
                horizon=StrategyHorizon.ONE_WEEK,
                action="long",
                confidence_percent=80.0,
                entry_price_low=99.0,
                entry_price_high=101.0,
                stop_loss=95.0,
                take_profit=110.0,
                computed_at=datetime.now(timezone.utc),
            )

            outcome = service.execute_plans([plan])

            self.assertEqual(outcome.summary["skipped_order_count"], 1)
            self.assertTrue(outcome.summary["warnings_found"])
            self.assertIn("missing_alpaca_credential", str(outcome.summary["skips"]))
        finally:
            session.close()

    def test_order_execution_service_handles_plan_validation_and_duplicate_paths(self) -> None:
        scenarios = [
            (
                "missing_plan_id",
                RecommendationPlan(
                    ticker="AAPL",
                    horizon=StrategyHorizon.ONE_WEEK,
                    action="long",
                    confidence_percent=80.0,
                    entry_price_low=99.0,
                    entry_price_high=101.0,
                    stop_loss=95.0,
                    take_profit=110.0,
                    computed_at=datetime.now(timezone.utc),
                ),
            ),
            (
                "missing_entry_price",
                RecommendationPlan(
                    id=2,
                    ticker="AAPL",
                    horizon=StrategyHorizon.ONE_WEEK,
                    action="long",
                    confidence_percent=80.0,
                    stop_loss=95.0,
                    take_profit=110.0,
                    computed_at=datetime.now(timezone.utc),
                ),
            ),
            (
                "missing_exit_levels",
                RecommendationPlan(
                    id=3,
                    ticker="AAPL",
                    horizon=StrategyHorizon.ONE_WEEK,
                    action="long",
                    confidence_percent=80.0,
                    entry_price_low=99.0,
                    entry_price_high=101.0,
                    computed_at=datetime.now(timezone.utc),
                ),
            ),
            (
                "invalid_trade_levels",
                RecommendationPlan(
                    id=4,
                    ticker="AAPL",
                    horizon=StrategyHorizon.ONE_WEEK,
                    action="long",
                    confidence_percent=80.0,
                    entry_price_low=99.0,
                    entry_price_high=101.0,
                    stop_loss=120.0,
                    take_profit=110.0,
                    computed_at=datetime.now(timezone.utc),
                ),
            ),
            (
                "quantity_below_minimum",
                RecommendationPlan(
                    id=5,
                    ticker="AAPL",
                    horizon=StrategyHorizon.ONE_WEEK,
                    action="long",
                    confidence_percent=80.0,
                    entry_price_low=2500.0,
                    entry_price_high=2500.0,
                    stop_loss=2400.0,
                    take_profit=2700.0,
                    computed_at=datetime.now(timezone.utc),
                ),
            ),
        ]
        for expected_reason, plan in scenarios:
            with self.subTest(expected_reason=expected_reason):
                session = create_session()
                try:
                    settings = SettingsRepository(session)
                    settings.set_order_execution_config(enabled=True, notional_per_plan=1000.0)
                    service = OrderExecutionService(
                        settings=settings,
                        executions=BrokerOrderExecutionRepository(session),
                        client=StubAlpacaClient(),
                    )

                    outcome = service.execute_plans([plan])

                    self.assertEqual(outcome.summary["skipped_order_count"], 1)
                    self.assertIn(
                        expected_reason, {item["reason"] for item in outcome.summary["skips"]}
                    )
                finally:
                    session.close()

        session = create_session()
        try:
            settings = SettingsRepository(session)
            settings.set_order_execution_config(enabled=True, notional_per_plan=1000.0)
            repository = BrokerOrderExecutionRepository(session)
            repository.create(
                BrokerOrderExecution(
                    broker="alpaca",
                    account_mode="paper",
                    recommendation_plan_id=99,
                    recommendation_plan_ticker="AAPL",
                    run_id=10,
                    job_id=11,
                    ticker="AAPL",
                    action="long",
                    side="buy",
                    order_type="limit",
                    time_in_force="gtc",
                    quantity=10,
                    notional_amount=1000.0,
                    entry_price=100.0,
                    stop_loss=95.0,
                    take_profit=110.0,
                    status="submitted",
                    broker_order_id="alpaca-order-dup",
                    client_order_id="tp-run-none-plan-99-aapl",
                    request_payload={
                        "symbol": "AAPL",
                        "qty": 10,
                        "limit_price": 100.0,
                        "client_order_id": "tp-run-none-plan-99-aapl",
                    },
                    response_payload={"id": "alpaca-order-dup", "status": "accepted"},
                )
            )
            duplicate_plan = RecommendationPlan(
                id=99,
                ticker="AAPL",
                horizon=StrategyHorizon.ONE_WEEK,
                action="long",
                confidence_percent=80.0,
                entry_price_low=99.0,
                entry_price_high=101.0,
                stop_loss=95.0,
                take_profit=110.0,
                computed_at=datetime.now(timezone.utc),
            )
            service = OrderExecutionService(
                settings=settings, executions=repository, client=StubAlpacaClient()
            )

            outcome = service.execute_plans([duplicate_plan])

            self.assertEqual(outcome.summary["duplicate_order_count"], 1)
            self.assertEqual(outcome.summary["submitted_order_count"], 0)
            self.assertEqual(len(repository.list_all()), 1)
        finally:
            session.close()

    def test_close_position_marks_local_position_as_closing_without_resolving_trade(self) -> None:
        session = create_session()
        try:
            settings = SettingsRepository(session)
            executions = BrokerOrderExecutionRepository(session)
            positions = BrokerPositionRepository(session)
            order = executions.create(
                BrokerOrderExecution(
                    recommendation_plan_id=1,
                    recommendation_plan_ticker="AAPL",
                    ticker="AAPL",
                    action="long",
                    side="buy",
                    order_type="limit",
                    time_in_force="gtc",
                    quantity=10,
                    status="filled",
                    broker_order_id="entry-order-1",
                    response_payload={"id": "entry-order-1", "status": "filled"},
                )
            )
            position = positions.create(
                BrokerPosition(
                    broker_order_execution_id=order.id or 0,
                    recommendation_plan_id=1,
                    recommendation_plan_ticker="AAPL",
                    ticker="AAPL",
                    action="long",
                    side="buy",
                    quantity=10,
                    current_quantity=10,
                    status="open",
                    entry_order_id="entry-order-1",
                    entry_avg_price=100.0,
                )
            )
            client = StubAlpacaClient()
            service = OrderExecutionService(
                settings=settings, executions=executions, positions=positions, client=client
            )

            service.close_position("AAPL")

            updated = positions.get(position.id or 0)
            self.assertEqual(updated.status, "closing")
            self.assertEqual(updated.exit_reason, "steering_close_submitted")
            self.assertEqual(updated.current_quantity, 10)
            self.assertIsNone(updated.realized_pnl)
            self.assertEqual(
                updated.raw_broker_payload["close_position_response"]["status"], "closed"
            )
            self.assertEqual(client.close_requests, ["AAPL"])
        finally:
            session.close()

    def test_close_position_rejected_response_does_not_mark_position_closing(self) -> None:
        session = create_session()
        try:
            settings = SettingsRepository(session)
            executions = BrokerOrderExecutionRepository(session)
            positions = BrokerPositionRepository(session)
            order = executions.create(
                BrokerOrderExecution(
                    recommendation_plan_id=1,
                    recommendation_plan_ticker="AAPL",
                    ticker="AAPL",
                    action="long",
                    side="buy",
                    order_type="limit",
                    quantity=10,
                    status="filled",
                    broker_order_id="entry-order-1",
                )
            )
            position = positions.create(
                BrokerPosition(
                    broker_order_execution_id=order.id or 0,
                    recommendation_plan_id=1,
                    recommendation_plan_ticker="AAPL",
                    ticker="AAPL",
                    action="long",
                    side="buy",
                    quantity=10,
                    current_quantity=10,
                    status="open",
                    entry_order_id="entry-order-1",
                    entry_avg_price=100.0,
                )
            )

            class RejectedCloseClient(StubAlpacaClient):
                def close_position(self, symbol: str) -> AlpacaOrderSubmissionResult:
                    self.close_requests.append(symbol)
                    return AlpacaOrderSubmissionResult(
                        status_code=200,
                        payload={
                            "symbol": symbol,
                            "status": "rejected",
                            "reason": "no close accepted",
                        },
                    )

            client = RejectedCloseClient()
            service = OrderExecutionService(
                settings=settings, executions=executions, positions=positions, client=client
            )

            service.close_position("AAPL")

            updated = positions.get(position.id or 0)
            self.assertEqual(updated.status, "open")
            self.assertIsNone(updated.exit_reason)
            self.assertEqual(client.close_requests, ["AAPL"])
        finally:
            session.close()

    def test_alpaca_paper_client_supports_submit_get_cancel_and_close_position(self) -> None:
        responses = [
            FakeHttpxResponse(200, {"id": "alpaca-order-1", "status": "accepted"}),
            FakeHttpxResponse(200, {"id": "alpaca-order-1", "status": "filled", "legs": []}),
            FakeHttpxResponse(200, {"id": "alpaca-order-1", "status": "canceled"}),
            FakeHttpxResponse(200, {"id": "alpaca-order-1", "status": "accepted"}),
            FakeHttpxResponse(200, {"symbol": "AAPL", "status": "closed"}),
        ]
        client = FakeHttpxClient(responses)
        alpaca = AlpacaPaperClient(api_key="paper-key", api_secret="paper-secret", client=client)

        submitted = alpaca.submit_order({"symbol": "AAPL", "qty": 10})
        fetched = alpaca.get_order("alpaca-order-1")
        canceled = alpaca.cancel_order("alpaca-order-1")
        amended = alpaca.amend_order("alpaca-order-1", {"take_profit": {"limit_price": 111.0}})
        closed = alpaca.close_position("AAPL")

        self.assertEqual(submitted.broker_order_id, "alpaca-order-1")
        self.assertEqual(fetched.payload["legs"], [])
        self.assertEqual(canceled.broker_status, "canceled")
        self.assertEqual(amended.broker_status, "accepted")
        self.assertEqual(closed.broker_status, "closed")
        self.assertEqual(
            [call[0] for call in client.calls], ["POST", "GET", "DELETE", "PATCH", "DELETE"]
        )
        self.assertTrue(str(client.calls[1][1]).endswith("/v2/orders/alpaca-order-1?nested=true"))

    def test_alpaca_paper_client_raises_on_http_error_and_non_object_payload(self) -> None:
        error_client = AlpacaPaperClient(
            api_key="paper-key",
            api_secret="paper-secret",
            client=FakeHttpxClient([FakeHttpxResponse(400, {"message": "bad request"})]),
        )
        with self.assertRaises(AlpacaPaperClientError):
            error_client.submit_order({"symbol": "AAPL", "qty": 10})

        payload_client = AlpacaPaperClient(
            api_key="paper-key",
            api_secret="paper-secret",
            client=FakeHttpxClient([FakeHttpxResponse(200, ["not", "an", "object"])]),
        )
        with self.assertRaises(AlpacaPaperClientError):
            payload_client.cancel_order("alpaca-order-1")

    def test_order_execution_service_places_short_order(self) -> None:
        session = create_session()
        try:
            settings = SettingsRepository(session)
            settings.set_order_execution_config(enabled=True, notional_per_plan=1000.0)
            service = OrderExecutionService(
                settings=settings,
                executions=BrokerOrderExecutionRepository(session),
                client=StubAlpacaClient(),
            )
            plan = RecommendationPlan(
                id=7,
                ticker="TSLA",
                horizon=StrategyHorizon.ONE_WEEK,
                action="short",
                confidence_percent=77.0,
                entry_price_low=199.0,
                entry_price_high=201.0,
                stop_loss=220.0,
                take_profit=190.0,
                computed_at=datetime.now(timezone.utc),
            )

            outcome = service.execute_plans([plan], run_id=21, job_id=22)

            self.assertEqual(outcome.summary["submitted_order_count"], 1)
            self.assertEqual(outcome.orders[0].side, "sell")
            self.assertEqual(outcome.orders[0].status, "accepted")
            self.assertEqual(outcome.orders[0].client_order_id, "tp-run-21-plan-7-tsla")
        finally:
            session.close()

    def test_order_execution_service_records_failed_submission_when_broker_rejects(self) -> None:
        class RejectingClient:
            def submit_order(self, payload: dict[str, object]) -> AlpacaOrderSubmissionResult:
                return AlpacaOrderSubmissionResult(
                    status_code=200, payload={"id": "alpaca-order-reject", "status": "rejected"}
                )

        session = create_session()
        try:
            settings = SettingsRepository(session)
            settings.set_order_execution_config(enabled=True, notional_per_plan=1000.0)
            service = OrderExecutionService(
                settings=settings,
                executions=BrokerOrderExecutionRepository(session),
                client=RejectingClient(),
            )
            plan = RecommendationPlan(
                id=8,
                ticker="AAPL",
                horizon=StrategyHorizon.ONE_WEEK,
                action="long",
                confidence_percent=77.0,
                entry_price_low=99.0,
                entry_price_high=101.0,
                stop_loss=95.0,
                take_profit=110.0,
                computed_at=datetime.now(timezone.utc),
            )

            outcome = service.execute_plans([plan], run_id=21, job_id=22)

            self.assertEqual(outcome.summary["failed_order_count"], 1)
            self.assertEqual(outcome.orders[0].status, "rejected")
            self.assertEqual(outcome.orders[0].response_payload["status"], "rejected")
        finally:
            session.close()

    def test_order_execution_service_caches_broker_unavailable_tickers_and_allows_forced_retry(
        self,
    ) -> None:
        class UnavailableTickerClient:
            def __init__(self) -> None:
                self.requests: list[dict[str, object]] = []

            def submit_order(self, payload: dict[str, object]) -> AlpacaOrderSubmissionResult:
                self.requests.append(payload)
                raise AlpacaPaperClientError(
                    "alpaca request failed with status 422",
                    status_code=422,
                    payload={"message": "symbol not tradable on alpaca"},
                )

        session = create_session()
        try:
            settings = SettingsRepository(session)
            settings.set_order_execution_config(enabled=True, notional_per_plan=1000.0)
            repository = BrokerOrderExecutionRepository(session)
            client = UnavailableTickerClient()
            service = OrderExecutionService(settings=settings, executions=repository, client=client)
            plan = RecommendationPlan(
                id=9,
                ticker="AAPL",
                horizon=StrategyHorizon.ONE_WEEK,
                action="long",
                confidence_percent=77.0,
                entry_price_low=99.0,
                entry_price_high=101.0,
                stop_loss=95.0,
                take_profit=110.0,
                computed_at=datetime.now(timezone.utc),
            )

            first_outcome = service.execute_plans([plan], run_id=21, job_id=22)
            second_outcome = service.execute_plans([plan], run_id=23, job_id=24)
            forced_outcome = service.execute_plans(
                [plan], run_id=25, job_id=26, force_tickers={"AAPL"}
            )

            self.assertEqual(len(client.requests), 2)
            self.assertEqual(first_outcome.summary["skipped_order_count"], 1)
            self.assertEqual(first_outcome.orders[0].status, "skipped")
            self.assertEqual(second_outcome.summary["skipped_order_count"], 1)
            self.assertEqual(second_outcome.orders[0].status, "skipped")
            self.assertEqual(forced_outcome.summary["failed_order_count"], 0)
            self.assertEqual(forced_outcome.summary["skipped_order_count"], 1)
            self.assertEqual(forced_outcome.orders[0].status, "skipped")
            self.assertTrue(repository.has_known_unavailable_ticker("alpaca", "AAPL"))
        finally:
            session.close()

    def test_order_execution_service_builds_live_snapshot_through_broker_adapter(self) -> None:
        session = create_session()
        try:
            settings = SettingsRepository(session)
            service = OrderExecutionService(
                settings=settings,
                executions=BrokerOrderExecutionRepository(session),
                adapter=FakeBrokerAdapter(),
                reconciliation_snapshots=BrokerReconciliationSnapshotRepository(session),
            )

            snapshot = service._live_broker_snapshot(run_id=1, job_id=2, ticker="AAPL")

            self.assertIsNotNone(snapshot)
            self.assertEqual(snapshot.account["equity"], 100000.0)
            stored = BrokerReconciliationSnapshotRepository(session).list_latest(limit=1)[0]
            self.assertEqual(stored.broker_account_id, "alpaca-paper-default")
            self.assertEqual(stored.snapshot_type, "pre_submit")
        finally:
            session.close()

    def test_order_execution_service_can_submit_through_broker_adapter_without_raw_client(
        self,
    ) -> None:
        session = create_session()
        try:
            settings = SettingsRepository(session)
            settings.set_order_execution_config(enabled=True, notional_per_plan=1000.0)
            repository = BrokerOrderExecutionRepository(session)
            service = OrderExecutionService(
                settings=settings,
                executions=repository,
                adapter=FakeBrokerAdapter(),
            )
            plan = RecommendationPlan(
                id=10,
                ticker="AAPL",
                horizon=StrategyHorizon.ONE_WEEK,
                action="long",
                confidence_percent=77.0,
                entry_price_low=99.0,
                entry_price_high=101.0,
                stop_loss=95.0,
                take_profit=110.0,
                computed_at=datetime.now(timezone.utc),
            )

            outcome = service.execute_plans([plan], run_id=21, job_id=22)

            self.assertEqual(outcome.summary["submitted_order_count"], 1)
            self.assertEqual(outcome.orders[0].broker_order_id, "fake-1")
            self.assertEqual(outcome.orders[0].status, "accepted")
        finally:
            session.close()

    def test_order_execution_service_uses_instantiated_alpaca_client_when_not_provided(
        self,
    ) -> None:
        class PatchedClient:
            def __init__(self, *args, **kwargs) -> None:
                self.requests: list[dict[str, object]] = []

            def submit_order(self, payload: dict[str, object]) -> AlpacaOrderSubmissionResult:
                self.requests.append(payload)
                return AlpacaOrderSubmissionResult(
                    status_code=200, payload={"id": "alpaca-order-patched", "status": "accepted"}
                )

        session = create_session()
        try:
            settings = SettingsRepository(session)
            settings.set_order_execution_config(enabled=True, notional_per_plan=1000.0)
            settings.upsert_provider_credential("alpaca", "paper-key", "paper-secret")
            repository = BrokerOrderExecutionRepository(session)
            plan = RecommendationPlan(
                id=9,
                ticker="AAPL",
                horizon=StrategyHorizon.ONE_WEEK,
                action="long",
                confidence_percent=77.0,
                entry_price_low=99.0,
                entry_price_high=101.0,
                stop_loss=95.0,
                take_profit=110.0,
                computed_at=datetime.now(timezone.utc),
            )
            with unittest.mock.patch(
                "trade_proposer_app.services.order_execution.AlpacaPaperClient", PatchedClient
            ):
                service = OrderExecutionService(settings=settings, executions=repository)
                outcome = service.execute_plans([plan], run_id=21, job_id=22)

            self.assertEqual(outcome.summary["submitted_order_count"], 1)
            self.assertEqual(len(repository.list_all()), 1)
        finally:
            session.close()

    def test_job_execution_hooks_order_execution_after_proposal_generation(self) -> None:
        session = create_session()
        try:
            jobs = JobRepository(session)
            runs = RunRepository(session)
            plans = RecommendationPlanRepository(session)
            job = jobs.create(
                name="Execution test",
                job_type=JobType.PROPOSAL_GENERATION,
                tickers=["AAPL"],
                watchlist_id=None,
                schedule=None,
            )
            run = runs.enqueue(job.id or 0, job_type=JobType.PROPOSAL_GENERATION)
            plans.create_plan(
                RecommendationPlan(
                    ticker="AAPL",
                    horizon=StrategyHorizon.ONE_WEEK,
                    action="long",
                    confidence_percent=80.0,
                    entry_price_low=99.0,
                    entry_price_high=101.0,
                    stop_loss=95.0,
                    take_profit=110.0,
                    computed_at=datetime.now(timezone.utc),
                    run_id=run.id,
                    job_id=job.id,
                    watchlist_id=None,
                )
            )

            order_stub = StubOrderExecutionService()
            service = JobExecutionService(
                jobs=jobs,
                runs=runs,
                watchlist_orchestration=StubWatchlistOrchestrationService(),
                recommendation_plans=plans,
                order_execution=order_stub,
            )

            service.execute_run(run.id or 0)
            updated_run = runs.get_run(run.id or 0)
            summary = json.loads(updated_run.summary_json or "{}")

            self.assertEqual(len(order_stub.calls), 1)
            self.assertEqual(len(order_stub.calls[0]), 1)
            self.assertEqual(order_stub.calls[0][0].ticker, "AAPL")
            self.assertIn("order_execution", summary)
            self.assertEqual(summary["order_execution"]["submitted_order_count"], 1)
        finally:
            session.close()
