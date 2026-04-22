import json
import unittest
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from trade_proposer_app.domain.enums import JobType, StrategyHorizon
from trade_proposer_app.domain.models import RecommendationPlan
from trade_proposer_app.persistence.models import Base
from trade_proposer_app.repositories.broker_order_executions import BrokerOrderExecutionRepository
from trade_proposer_app.repositories.jobs import JobRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.repositories.runs import RunRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.alpaca_paper_client import AlpacaOrderSubmissionResult
from trade_proposer_app.services.job_execution import JobExecutionService
from trade_proposer_app.services.order_execution import OrderExecutionService


def create_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


class StubAlpacaClient:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []

    def submit_order(self, payload: dict[str, object]) -> AlpacaOrderSubmissionResult:
        self.requests.append(payload)
        return AlpacaOrderSubmissionResult(
            status_code=200,
            payload={"id": "alpaca-order-1", "status": "accepted", "symbol": payload["symbol"]},
        )


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
                "summary": {"enabled": True, "warnings_found": False, "submitted_order_count": len(plans)},
                "orders": [],
            },
        )()


class OrderExecutionTests(unittest.TestCase):
    def test_order_execution_service_places_limit_bracket_orders_with_fixed_notional(self) -> None:
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
