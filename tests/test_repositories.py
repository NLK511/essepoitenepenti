import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import pandas as pd

from sqlalchemy.exc import IntegrityError

from sqlalchemy import create_engine, update
from sqlalchemy.orm import Session

from trade_proposer_app.config import settings
from trade_proposer_app.domain.enums import JobType, RecommendationDirection, StrategyHorizon
from trade_proposer_app.domain.statuses import (
    broker_position_status_to_outcome,
    is_resolved_trade_outcome,
    is_terminal_execution_status,
)
from trade_proposer_app.domain.models import (
    EvaluationRunResult,
    IndustryContextRefreshPayload,
    IndustryContextSnapshot,
    MacroContextRefreshPayload,
    MacroContextSnapshot,
    Recommendation,
    RecommendationDecisionSample,
    BrokerPosition,
    RecommendationPlan,
    RecommendationPlanEvidenceSummary,
    RecommendationPlanOutcome,
    RecommendationPlanSignalBreakdown,
    AccountRiskState,
    BrokerOrderExecution,
    RecommendationTransmissionSummary,
    RunDiagnostics,
    RunOutput,
    TickerSignalDiagnostics,
    TickerSignalSnapshot,
    TickerSignalSourceBreakdown,
)
from trade_proposer_app.persistence.models import Base, JobRecord, ProviderCredentialRecord, RunRecord
from trade_proposer_app.repositories.historical_market_data import HistoricalMarketDataRepository
from trade_proposer_app.repositories.jobs import JobRepository
from trade_proposer_app.repositories.runs import RunRepository
from trade_proposer_app.repositories.context_snapshots import ContextSnapshotRepository
from trade_proposer_app.repositories.effective_plan_outcomes import EffectivePlanOutcomeRepository
from trade_proposer_app.repositories.recommendation_decision_samples import RecommendationDecisionSampleRepository
from trade_proposer_app.repositories.recommendation_outcomes import RecommendationOutcomeRepository
from trade_proposer_app.repositories.broker_order_executions import BrokerOrderExecutionRepository
from trade_proposer_app.repositories.broker_positions import BrokerPositionRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.repositories.watchlists import WatchlistRepository
from trade_proposer_app.services.evaluation_execution import EvaluationExecutionService
from trade_proposer_app.services.industry_context import IndustryContextService
from trade_proposer_app.services.job_execution import JobExecutionService
from trade_proposer_app.services.macro_context import MacroContextService
from trade_proposer_app.services.recommendation_outcome_cohorts import RecommendationOutcomeCohortBuilder
from trade_proposer_app.services.recommendation_plan_calibration import RecommendationPlanCalibrationService
from trade_proposer_app.services.recommendation_plan_evaluations import RecommendationPlanEvaluationService
from trade_proposer_app.services.risk_management import BrokerRiskManager
from trade_proposer_app.services.ticker_deep_analysis import TickerDeepAnalysisService
from trade_proposer_app.services.execution_candidates import ExecutionCandidateBuilder
from trade_proposer_app.services.plan_reliability_features import PlanReliabilityFeatureBuilder
from trade_proposer_app.services.plan_policy_evaluator import PlanPolicyEvaluator
from trade_proposer_app.services.plan_reliability_report import PlanReliabilityReportService
from trade_proposer_app.services.trade_policy_evaluation import TradePolicyEvaluationService
from trade_proposer_app.services.broker_reconciliation import BrokerReconciliationService
from trade_proposer_app.services.settings_domains import SettingsDomainService
from trade_proposer_app.services.settings_mutations import SettingsMutationService
from trade_proposer_app.services.trade_decision_policy import TradeDecisionPolicy, TradeDecisionPolicyService
from trade_proposer_app.services.trading_performance_metrics import TradingPerformanceMetricsService
from trade_proposer_app.services.watchlist_orchestration import WatchlistOrchestrationService


def create_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


class StubEffectiveOutcomeRepository:
    def __init__(self, outcomes: list[RecommendationPlanOutcome]) -> None:
        self.outcomes = outcomes
        self.list_outcomes_calls = 0

    def list_outcomes(self, **_kwargs):
        self.list_outcomes_calls += 1
        return self.outcomes


class StubWatchlistOrchestrationService:
    def execute(self, watchlist, tickers, *, job_id=None, run_id=None, as_of=None):
        return {
            "summary": {
                "mode": "watchlist_orchestration",
                "ticker_count": len(tickers),
            },
            "artifact": {
                "mode": "watchlist_orchestration",
            },
            "ticker_generation": [
                {
                    "ticker": ticker,
                    "status": "cheap_scan_only",
                    "shortlisted": False,
                }
                for ticker in tickers
            ],
            "warnings_found": False,
        }


class FailingWatchlistOrchestrationService:
    def execute(self, watchlist, tickers, *, job_id=None, run_id=None, as_of=None):
        failing = tickers[0] if tickers else "unknown"
        raise RuntimeError(f"boom: {failing}")


class FailOnSecondTickerWatchlistOrchestrationService:
    def execute(self, watchlist, tickers, *, job_id=None, run_id=None, as_of=None):
        ticker_generation = []
        for index, ticker in enumerate(tickers, start=1):
            if index == 2:
                ticker_generation.append(
                    {
                        "ticker": ticker,
                        "status": "failed",
                        "error_message": f"ticker not found: {ticker}",
                    }
                )
                error = RuntimeError(f"ticker not found: {ticker}")
                error.ticker_generation = ticker_generation
                raise error
            ticker_generation.append(
                {
                    "ticker": ticker,
                    "status": "completed",
                }
            )
        return {
            "summary": {"mode": "watchlist_orchestration", "ticker_count": len(tickers)},
            "artifact": {"mode": "watchlist_orchestration"},
            "ticker_generation": ticker_generation,
            "warnings_found": False,
        }


class StubEvaluationExecutionService(EvaluationExecutionService):
    def __init__(self) -> None:
        pass

    def execute(self, run=None, as_of=None) -> EvaluationRunResult:
        return EvaluationRunResult(
            evaluated_recommendation_plans=12,
            synced_recommendation_plan_outcomes=4,
            pending_recommendation_plan_outcomes=5,
            win_recommendation_plan_outcomes=4,
            loss_recommendation_plan_outcomes=3,
            output="evaluation complete",
        )


class CheapScanProposalService:
    def score(self, ticker: str, horizon: StrategyHorizon, as_of=None):
        from trade_proposer_app.services.watchlist_cheap_scan import CheapScanSignal

        confidence_map = {"AAPL": 84.0, "MSFT": 67.0, "TSLA": 41.0}
        direction_map = {
            "AAPL": "long",
            "MSFT": "short",
            "TSLA": "long",
        }
        return CheapScanSignal(
            ticker=ticker,
            horizon=horizon,
            directional_bias=direction_map[ticker],
            directional_score={"AAPL": 0.62, "MSFT": -0.38, "TSLA": 0.08}[ticker],
            confidence_percent=confidence_map[ticker],
            attention_score={"AAPL": 82.0, "MSFT": 71.0, "TSLA": 35.0}[ticker],
            trend_score={"AAPL": 80.0, "MSFT": 35.0, "TSLA": 52.0}[ticker],
            momentum_score={"AAPL": 78.0, "MSFT": 30.0, "TSLA": 48.0}[ticker],
            breakout_score={"AAPL": 74.0, "MSFT": 28.0, "TSLA": 45.0}[ticker],
            volatility_score=55.0,
            liquidity_score=72.0,
            diagnostics={"model": "cheap_scan_test", "price_history": {"source": "database", "selected_bar_count": 60, "remote_attempt_count": 0}},
            indicator_summary=f"cheap scan {ticker}",
        )


class CatalystLaneCheapScanService:
    def score(self, ticker: str, horizon: StrategyHorizon, as_of=None):
        from trade_proposer_app.services.watchlist_cheap_scan import CheapScanSignal

        fixtures = {
            "AAPL": {"direction": "long", "directional": 0.58, "confidence": 82.0, "attention": 80.0, "trend": 78.0, "momentum": 76.0, "breakout": 72.0},
            "SHOP": {"direction": "long", "directional": 0.54, "confidence": 44.0, "attention": 68.0, "trend": 52.0, "momentum": 60.0, "breakout": 92.0},
            "IBM": {"direction": "long", "directional": 0.12, "confidence": 49.0, "attention": 46.0, "trend": 51.0, "momentum": 48.0, "breakout": 40.0},
        }
        item = fixtures[ticker]
        return CheapScanSignal(
            ticker=ticker,
            horizon=horizon,
            directional_bias=item["direction"],
            directional_score=item["directional"],
            confidence_percent=item["confidence"],
            attention_score=item["attention"],
            trend_score=item["trend"],
            momentum_score=item["momentum"],
            breakout_score=item["breakout"],
            volatility_score=55.0,
            liquidity_score=72.0,
            diagnostics={"model": "cheap_scan_test", "price_history": {"source": "database", "selected_bar_count": 60, "remote_attempt_count": 0}},
            indicator_summary=f"cheap scan {ticker}",
        )


class DeepAnalysisProposalService:
    def generate(self, ticker: str, as_of=None) -> RunOutput:
        direction_map = {
            "AAPL": RecommendationDirection.LONG,
            "MSFT": RecommendationDirection.SHORT,
        }
        confidence_map = {"AAPL": 78.0, "MSFT": 74.0}
        analysis = {
            "summary": {"text": f"deep analysis for {ticker}"},
            "sentiment": {
                "macro": {"score": 0.3},
                "industry": {"score": 0.2},
                "ticker": {"score": 0.4},
            },
            "news": {"item_count": 3},
            "ticker_deep_analysis": {
                "setup_family": "breakout" if ticker == "AAPL" else "breakdown",
                "price_history": {"source": "remote", "fallback_used": False, "remote_attempt_count": 1, "selected_bar_count": 250},
                "transmission_analysis": {
                    "alignment_percent": 72.0,
                    "context_bias": "tailwind" if ticker == "AAPL" else "headwind",
                    "catalyst_intensity_percent": 68.0,
                    "context_strength_percent": 70.0,
                    "context_event_relevance_percent": 66.0,
                    "contradiction_count": 0,
                    "transmission_tags": ["industry_dominant", "catalyst_active"],
                    "transmission_tag_details": [
                        {"key": "industry_dominant", "label": "industry dominant"},
                        {"key": "catalyst_active", "label": "catalyst active"},
                    ],
                    "primary_drivers": ["industry_context_support", "ticker_sentiment_confirmation"],
                    "primary_driver_details": [
                        {"key": "industry_context_support", "label": "industry context support"},
                        {"key": "ticker_sentiment_confirmation", "label": "ticker sentiment confirmation"},
                    ],
                    "industry_exposure_channels": ["industry_demand"],
                    "industry_exposure_channel_details": [
                        {"key": "industry_demand", "label": "industry demand"},
                    ],
                    "ticker_exposure_channels": ["ticker_sentiment", "news_catalyst"],
                    "ticker_exposure_channel_details": [
                        {"key": "ticker_sentiment", "label": "ticker sentiment"},
                        {"key": "news_catalyst", "label": "news catalyst"},
                    ],
                    "ticker_relationship_edges": [
                        {"type": "supplier_to", "target": "TSM", "channel": "supply_chain"},
                        {"type": "peer_of", "target": "SONY", "channel": "competitive_position"},
                    ],
                    "matched_ticker_relationships": [
                        {"type": "supplier_to", "target": "TSM", "target_label": "TSM", "channel": "supply_chain", "relevance_hits": 2},
                    ],
                    "expected_transmission_window": "2d_5d",
                    "conflict_flags": [],
                    "decay_state": "fresh",
                }
            },
        }
        return RunOutput(
            recommendation=Recommendation(
                ticker=ticker,
                direction=direction_map[ticker],
                confidence=confidence_map[ticker],
                entry_price=100.0,
                stop_loss=96.0,
                take_profit=108.0,
                indicator_summary=f"deep analysis {ticker}",
            ),
            diagnostics=RunDiagnostics(analysis_json=json.dumps(analysis)),
        )


class StubOptimizationService:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def run(self, *args, **kwargs):
        class StubRun:
            id = 1
            winning_candidate_id = 1
            promoted_config_version_id = None
            summary = {
                "winner_candidate_id": 1,
                "best_config": {"setup_family.breakout.take_profit_distance_multiplier": 1.07},
            }

        return StubRun()


class StubMacroContextRefreshService:
    def __init__(self) -> None:
        self.calls: list[tuple[int | None, int | None]] = []

    def refresh(self, *, job_id: int | None = None, run_id: int | None = None) -> dict[str, object]:
        self.calls.append((job_id, run_id))
        snapshot = MacroContextRefreshPayload(
            subject_key="global_macro",
            subject_label="Global Macro",
            score=0.2,
            label="POSITIVE",
        )
        return {
            "payload": snapshot,
            "summary": {
                "scope": "macro",
                "subject_key": "global_macro",
                "subject_label": "Global Macro",
                "score": 0.2,
                "label": "POSITIVE",
                "expires_at": "2026-03-22T06:00:00+00:00",
            },
        }


class StubIndustryContextRefreshService:
    def __init__(self) -> None:
        self.calls: list[tuple[int | None, int | None]] = []

    def refresh_all(self, *, job_id: int | None = None, run_id: int | None = None) -> dict[str, object]:
        self.calls.append((job_id, run_id))
        snapshots = [
            IndustryContextRefreshPayload(
                subject_key="consumer_electronics",
                subject_label="Consumer Electronics",
                score=0.15,
                label="POSITIVE",
            )
        ]
        return {
            "payloads": snapshots,
            "summary": {
                "scope": "industry",
                "snapshot_count": 1,
                "industries": [
                    {
                        "subject_key": "consumer_electronics",
                        "subject_label": "Consumer Electronics",
                        "score": 0.15,
                        "label": "POSITIVE",
                    }
                ],
            },
        }


class RepositoryTests(unittest.TestCase):
    def test_watchlist_repository_create_and_list(self) -> None:
        session = create_session()
        repository = WatchlistRepository(session)
        repository.create(
            "Core Tech",
            ["aapl", "MSFT", "AAPL"],
            description="US tech swing basket",
            region="US",
            exchange="NASDAQ",
            timezone="America/New_York",
            default_horizon=StrategyHorizon.ONE_DAY,
            allow_shorts=False,
            optimize_evaluation_timing=True,
        )
        items = repository.list_all()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].name, "Core Tech")
        self.assertEqual(items[0].description, "US tech swing basket")
        self.assertEqual(items[0].region, "US")
        self.assertEqual(items[0].exchange, "NASDAQ")
        self.assertEqual(items[0].timezone, "America/New_York")
        self.assertEqual(items[0].default_horizon, StrategyHorizon.ONE_DAY)
        self.assertFalse(items[0].allow_shorts)
        self.assertTrue(items[0].optimize_evaluation_timing)
        self.assertEqual(items[0].tickers, ["AAPL", "MSFT"])

    def test_watchlist_repository_rejects_ticker_already_assigned_to_another_watchlist(self) -> None:
        session = create_session()
        repository = WatchlistRepository(session)
        repository.create("Core Tech", ["AAPL", "MSFT"])

        with self.assertRaises(ValueError) as context:
            repository.create("More Tech", ["NVDA", "AAPL"])

        self.assertIn("ticker already assigned to another watchlist", str(context.exception))
        self.assertIn("AAPL", str(context.exception))

    def test_job_repository_requires_exactly_one_source_for_proposal_jobs(self) -> None:
        session = create_session()
        jobs = JobRepository(session)
        watchlist = WatchlistRepository(session).create("Core Tech", ["AAPL", "MSFT"])

        with self.assertRaises(ValueError):
            jobs.create("Invalid Empty", [], None)

        with self.assertRaises(ValueError):
            jobs.create("Invalid Both", ["AAPL"], None, watchlist_id=watchlist.id)

        created = jobs.create("From Watchlist", [], None, watchlist_id=watchlist.id)
        self.assertEqual(created.watchlist_id, watchlist.id)
        self.assertEqual(created.job_type, JobType.PROPOSAL_GENERATION)
        self.assertEqual(jobs.resolve_tickers(created.id or 0), ["AAPL", "MSFT"])

    def test_job_repository_allows_non_proposal_jobs_without_sources_and_rejects_sources(self) -> None:
        session = create_session()
        jobs = JobRepository(session)
        watchlist = WatchlistRepository(session).create("Core Tech", ["AAPL", "MSFT"])

        evaluation_job = jobs.create(
            "Daily Evaluation",
            [],
            "0 18 * * *",
            job_type=JobType.RECOMMENDATION_EVALUATION,
        )
        optimization_job = jobs.create(
            "Weekly Plan Generation Tuning",
            [],
            "0 2 * * 0",
            job_type=JobType.PLAN_GENERATION_TUNING,
        )

        self.assertEqual(evaluation_job.job_type, JobType.RECOMMENDATION_EVALUATION)
        self.assertEqual(optimization_job.job_type, JobType.PLAN_GENERATION_TUNING)

        with self.assertRaises(ValueError):
            jobs.create(
                "Invalid Evaluation Tickers",
                ["AAPL"],
                None,
                job_type=JobType.RECOMMENDATION_EVALUATION,
            )

        with self.assertRaises(ValueError):
            jobs.create(
                "Invalid Plan Generation Tuning Watchlist",
                [],
                None,
                watchlist_id=watchlist.id,
                job_type=JobType.PLAN_GENERATION_TUNING,
            )

    def test_run_repository_persists_job_type_and_run_metadata(self) -> None:
        session = create_session()
        jobs = JobRepository(session)
        runs = RunRepository(session)
        job = jobs.create(
            "Daily Evaluation",
            [],
            "0 18 * * *",
            job_type=JobType.RECOMMENDATION_EVALUATION,
        )

        run = runs.enqueue(job.id or 0)
        runs.set_summary(run.id or 0, {"synced_recommendation_plan_outcomes": 3, "pending_recommendation_plan_outcomes": 7})
        runs.set_artifact(run.id or 0, {"weights_path": "/tmp/weights.json", "changed": False})

        stored_run = runs.get_run(run.id or 0)
        self.assertEqual(stored_run.job_type, JobType.RECOMMENDATION_EVALUATION)
        self.assertIn('"synced_recommendation_plan_outcomes": 3', stored_run.summary_json or "")
        self.assertIn('"weights_path": "/tmp/weights.json"', stored_run.artifact_json or "")

    def test_context_and_recommendation_plan_repositories_persist_new_redesign_models(self) -> None:
        session = create_session()
        context_repository = ContextSnapshotRepository(session)
        plan_repository = RecommendationPlanRepository(session)
        outcome_repository = RecommendationOutcomeRepository(session)

        macro = context_repository.create_macro_context_snapshot(
            MacroContextSnapshot(
                summary_text="Oil shock risk remains salient.",
                saliency_score=0.88,
                confidence_percent=72.0,
                active_themes=[{"key": "oil_supply_shock_risk"}],
                regime_tags=["risk_off"],
                warnings=["headline_only_evidence"],
            )
        )
        industry = context_repository.create_industry_context_snapshot(
            IndustryContextSnapshot(
                industry_key="airlines",
                industry_label="Airlines",
                summary_text="Fuel-cost pressure is rising.",
                direction="negative",
                saliency_score=0.74,
                confidence_percent=68.0,
                linked_macro_themes=["oil_supply_shock_risk"],
            )
        )
        ticker_signal = context_repository.create_ticker_signal_snapshot(
            TickerSignalSnapshot(
                ticker="DAL",
                horizon=StrategyHorizon.ONE_WEEK,
                direction="short",
                swing_probability_percent=61.0,
                confidence_percent=64.0,
                attention_score=79.0,
                diagnostics={"stage": "cheap_scan_then_deep_analysis"},
            )
        )
        plan = plan_repository.create_plan(
            RecommendationPlan(
                ticker="DAL",
                horizon=StrategyHorizon.ONE_WEEK,
                action="short",
                status="ok",
                confidence_percent=64.0,
                entry_price_low=43.2,
                entry_price_high=43.8,
                stop_loss=45.1,
                take_profit=40.2,
                holding_period_days=5,
                risk_reward_ratio=1.7,
                thesis_summary="Oil-sensitive airlines face renewed cost pressure.",
                rationale_summary="Macro and industry context align bearish.",
                risks=["oil reversal"],
                signal_breakdown={"macro_exposure": 0.8, "setup_family": "macro_beneficiary_loser"},
                ticker_signal_snapshot_id=ticker_signal.id,
            )
        )
        outcome_repository.upsert_outcome(
            RecommendationPlanOutcome(
                recommendation_plan_id=plan.id or 0,
                ticker="DAL",
                action="short",
                outcome="loss",
                status="resolved",
                horizon_return_1d=-1.2,
                horizon_return_5d=-2.1,
                max_favorable_excursion=0.9,
                max_adverse_excursion=3.4,
                confidence_bucket="50_to_64",
                setup_family="macro_beneficiary_loser",
                notes="Stop was hit first.",
            )
        )

        macro_items = context_repository.list_macro_context_snapshots()
        industry_items = context_repository.list_industry_context_snapshots("airlines")
        ticker_items = context_repository.list_ticker_signal_snapshots("DAL")
        plans = plan_repository.list_plans(ticker="DAL", action="short")

        self.assertEqual(macro.id, macro_items[0].id)
        self.assertEqual(industry.id, industry_items[0].id)
        self.assertEqual(ticker_signal.id, ticker_items[0].id)
        self.assertEqual(plan.id, plans[0].id)
        self.assertEqual(macro_items[0].warnings, ["headline_only_evidence"])
        self.assertEqual(industry_items[0].linked_macro_themes, ["oil_supply_shock_risk"])
        self.assertEqual(ticker_items[0].diagnostics["stage"], "cheap_scan_then_deep_analysis")
        self.assertEqual(plans[0].action, "short")
        self.assertEqual(plans[0].signal_breakdown["macro_exposure"], 0.8)
        self.assertIsNotNone(plans[0].latest_outcome)
        self.assertEqual(plans[0].latest_outcome.outcome, "loss")
        self.assertEqual(plans[0].latest_outcome.setup_family, "macro_beneficiary_loser")
        self.assertEqual(plans[0].latest_outcome.transmission_bias_label, "unknown")
        self.assertEqual(plans[0].latest_outcome.transmission_bias_detail["label"], "unknown")
        self.assertEqual(plans[0].latest_outcome.context_regime_label, "mixed context")
        self.assertEqual(plans[0].latest_outcome.context_regime_detail["label"], "mixed context")

    def test_recommendation_plan_repository_persists_trade_policy_snapshot(self) -> None:
        session = create_session()
        try:
            plan_repository = RecommendationPlanRepository(session)
            stored = plan_repository.create_plan(
                RecommendationPlan(
                    ticker="AAPL",
                    horizon=StrategyHorizon.ONE_WEEK,
                    action="long",
                    confidence_percent=72.0,
                    thesis_summary="Policy snapshot test",
                    trade_policy_id="settings-active:baseline",
                    trade_policy_snapshot={
                        "policy_id": "settings-active:baseline",
                        "confidence_threshold": 60.0,
                    },
                )
            )

            fetched = plan_repository.get_plan(stored.id or 0)

            self.assertEqual(fetched.trade_policy_id, "settings-active:baseline")
            self.assertEqual(fetched.trade_policy_snapshot["confidence_threshold"], 60.0)
        finally:
            session.close()

    def test_recommendation_plan_repository_prefers_broker_evaluation_when_available(self) -> None:
        session = create_session()
        plan_repository = RecommendationPlanRepository(session)
        broker_repository = BrokerOrderExecutionRepository(session)

        plan = plan_repository.create_plan(
            RecommendationPlan(
                ticker="AAPL",
                horizon=StrategyHorizon.ONE_WEEK,
                action="long",
                confidence_percent=70.0,
                thesis_summary="Broker should win precedence",
                signal_breakdown={"setup_family": "continuation"},
            )
        )
        plan_repository.create_plan(
            RecommendationPlan(
                ticker="MSFT",
                horizon=StrategyHorizon.ONE_WEEK,
                action="long",
                confidence_percent=70.0,
                thesis_summary="Unrelated plan",
                signal_breakdown={"setup_family": "continuation"},
            )
        )
        outcome_repository = RecommendationOutcomeRepository(session)
        outcome_repository.upsert_outcome(
            RecommendationPlanOutcome(
                recommendation_plan_id=plan.id or 0,
                ticker="AAPL",
                action="long",
                outcome="win",
                status="resolved",
                confidence_bucket="65_to_79",
                setup_family="continuation",
                notes="Simulated outcome should be secondary.",
            )
        )
        broker_repository.create(
            BrokerOrderExecution(
                broker="alpaca",
                account_mode="paper",
                recommendation_plan_id=plan.id or 0,
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
                broker_order_id="alpaca-order-123",
                client_order_id="tp-run-1-plan-1-aapl-live",
                submitted_at=datetime.now(timezone.utc),
                filled_at=datetime.now(timezone.utc),
                request_payload={"symbol": "AAPL"},
                response_payload={"id": "alpaca-order-123", "status": "filled", "legs": []},
            )
        )

        loaded = plan_repository.get_plan(plan.id or 0)
        self.assertEqual(loaded.effective_evaluation_source, "broker")
        self.assertEqual(loaded.effective_evaluation, "entry")
        self.assertEqual(loaded.broker_order_status, "open")
        self.assertEqual(loaded.broker_order_id, "alpaca-order-123")
        self.assertIsNotNone(loaded.latest_outcome)
        self.assertEqual(loaded.latest_outcome.outcome, "win")

        listed = plan_repository.list_plans(ticker="AAPL", action="long", limit=10)
        self.assertEqual(listed[0].effective_evaluation_source, "broker")
        self.assertEqual(listed[0].effective_evaluation, "entry")

        self.assertEqual(plan_repository.list_plans(ticker="AAPL", resolved="resolved"), [])
        self.assertEqual(plan_repository.list_plans(ticker="AAPL", outcome="win"), [])
        self.assertEqual(plan_repository.count_plans(ticker="AAPL", resolved="resolved"), 0)
        self.assertEqual(plan_repository.count_plans(ticker="AAPL", outcome="win"), 0)
        unresolved = plan_repository.list_plans(ticker="AAPL", resolved="unresolved")
        self.assertEqual([item.id for item in unresolved], [plan.id])
        stats = plan_repository.summarize_stats(ticker="AAPL")
        self.assertEqual(stats.open_plans, 1)
        self.assertEqual(stats.win_outcomes, 0)

    def test_effective_plan_outcome_repository_prefers_broker_position_over_simulation(self) -> None:
        session = create_session()
        try:
            plan_repository = RecommendationPlanRepository(session)
            plan = plan_repository.create_plan(
                RecommendationPlan(
                    ticker="AAPL",
                    horizon=StrategyHorizon.ONE_WEEK,
                    action="long",
                    confidence_percent=72.0,
                    thesis_summary="Broker loss should override simulated win",
                    signal_breakdown={"setup_family": "continuation"},
                )
            )
            RecommendationOutcomeRepository(session).upsert_outcome(
                RecommendationPlanOutcome(
                    recommendation_plan_id=plan.id or 0,
                    ticker="AAPL",
                    action="long",
                    outcome="win",
                    status="resolved",
                    confidence_bucket="65_to_79",
                    setup_family="continuation",
                )
            )
            BrokerPositionRepository(session).create(
                BrokerPosition(
                    broker_order_execution_id=1,
                    broker="alpaca",
                    account_mode="paper",
                    recommendation_plan_id=plan.id or 0,
                    recommendation_plan_ticker="AAPL",
                    ticker="AAPL",
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
                    realized_r_multiple=-1.0,
                )
            )

            outcomes = EffectivePlanOutcomeRepository(session).list_outcomes(ticker="AAPL", limit=10)

            self.assertEqual(len(outcomes), 1)
            self.assertEqual(outcomes[0].outcome_source, "broker")
            self.assertEqual(outcomes[0].outcome, "loss")
            self.assertEqual(outcomes[0].status, "resolved")
            self.assertEqual(outcomes[0].realized_pnl, -50.0)
            self.assertEqual(outcomes[0].setup_family, "continuation")
        finally:
            session.close()

    def test_effective_plan_outcome_repository_uses_simulation_without_broker_position(self) -> None:
        session = create_session()
        try:
            plan_repository = RecommendationPlanRepository(session)
            plan = plan_repository.create_plan(
                RecommendationPlan(
                    ticker="MSFT",
                    horizon=StrategyHorizon.ONE_WEEK,
                    action="long",
                    confidence_percent=58.0,
                    thesis_summary="Simulation fallback",
                    signal_breakdown={"setup_family": "breakout"},
                )
            )
            RecommendationOutcomeRepository(session).upsert_outcome(
                RecommendationPlanOutcome(
                    recommendation_plan_id=plan.id or 0,
                    ticker="MSFT",
                    action="long",
                    outcome="win",
                    status="resolved",
                    confidence_bucket="50_to_64",
                    setup_family="breakout",
                )
            )

            outcome = EffectivePlanOutcomeRepository(session).list_outcomes(ticker="MSFT", limit=10)[0]

            self.assertEqual(outcome.outcome_source, "simulation")
            self.assertEqual(outcome.outcome, "win")
            self.assertEqual(outcome.setup_family, "breakout")
        finally:
            session.close()

    def test_calibration_counts_broker_effective_outcomes(self) -> None:
        session = create_session()
        try:
            plan_repository = RecommendationPlanRepository(session)
            for index, status in enumerate(["win", "loss"], start=1):
                plan = plan_repository.create_plan(
                    RecommendationPlan(
                        ticker=f"CAL{index}",
                        horizon=StrategyHorizon.ONE_WEEK,
                        action="long",
                        confidence_percent=70.0,
                        thesis_summary="Broker calibration",
                        signal_breakdown={"setup_family": "continuation"},
                    )
                )
                BrokerPositionRepository(session).create(
                    BrokerPosition(
                        broker_order_execution_id=index,
                        broker="alpaca",
                        account_mode="paper",
                        recommendation_plan_id=plan.id or 0,
                        recommendation_plan_ticker=f"CAL{index}",
                        ticker=f"CAL{index}",
                        action="long",
                        side="buy",
                        quantity=1,
                        current_quantity=0,
                        status=status,
                        exit_filled_at=datetime.now(timezone.utc),
                        realized_pnl=10.0 if status == "win" else -5.0,
                        realized_return_pct=10.0 if status == "win" else -5.0,
                    )
                )

            summary = RecommendationPlanCalibrationService(EffectivePlanOutcomeRepository(session)).summarize(limit=10)

            self.assertEqual(summary.resolved_outcomes, 2)
            self.assertEqual(summary.win_outcomes, 1)
            self.assertEqual(summary.loss_outcomes, 1)
            self.assertEqual(summary.overall_win_rate_percent, 50.0)
            self.assertIsNotNone(summary.calibration_report)
        finally:
            session.close()

    def test_status_taxonomy_helpers_map_domain_statuses(self) -> None:
        self.assertTrue(is_terminal_execution_status("WIN"))
        self.assertTrue(is_terminal_execution_status(" failed "))
        self.assertFalse(is_terminal_execution_status("open"))
        self.assertTrue(is_resolved_trade_outcome("loss"))
        self.assertFalse(is_resolved_trade_outcome("skipped"))
        self.assertEqual(broker_position_status_to_outcome("win"), "win")
        self.assertEqual(broker_position_status_to_outcome("needs_review"), "open")

    def test_plan_reliability_feature_builder_extracts_tuning_features(self) -> None:
        plan = RecommendationPlan(
            id=101,
            ticker="AAPL",
            horizon=StrategyHorizon.ONE_WEEK,
            action="long",
            confidence_percent=70.0,
            entry_price_low=99.0,
            entry_price_high=101.0,
            stop_loss=95.0,
            take_profit=110.0,
            thesis_summary="Reliable features",
            signal_breakdown={
                "setup_family": "Continuation",
                "transmission_summary": {"context_bias": "Tailwind"},
            },
        )
        outcome = RecommendationPlanOutcome(
            recommendation_plan_id=101,
            ticker="AAPL",
            action="long",
            outcome="win",
            stop_loss_hit=False,
            take_profit_hit=True,
            max_favorable_excursion=11.0,
            max_adverse_excursion=-1.0,
        )

        features = PlanReliabilityFeatureBuilder().build(plan, outcome)

        self.assertIsNotNone(features)
        assert features is not None
        self.assertEqual(features.entry_price, 100.0)
        self.assertEqual(features.setup_family, "continuation")
        self.assertEqual(features.context_bias, "tailwind")
        self.assertEqual(features.risk_percent, 5.0)
        self.assertEqual(features.reward_percent, 10.0)

    def test_plan_policy_evaluator_scores_selected_policy_outcomes(self) -> None:
        outcomes = [
            RecommendationPlanOutcome(
                recommendation_plan_id=1,
                ticker="AAPL",
                action="long",
                outcome="win",
                status="resolved",
                confidence_percent=70.0,
                confidence_bucket="65_to_79",
                setup_family="continuation",
                outcome_source="broker",
                realized_pnl=10.0,
                realized_return_pct=5.0,
                realized_r_multiple=2.0,
            ),
            RecommendationPlanOutcome(
                recommendation_plan_id=2,
                ticker="MSFT",
                action="long",
                outcome="loss",
                status="resolved",
                confidence_percent=66.0,
                confidence_bucket="65_to_79",
                setup_family="continuation",
                outcome_source="simulation",
                realized_pnl=-5.0,
                realized_return_pct=-2.0,
                realized_r_multiple=-1.0,
            ),
            RecommendationPlanOutcome(
                recommendation_plan_id=3,
                ticker="TSLA",
                action="short",
                outcome="win",
                status="resolved",
                confidence_percent=82.0,
                confidence_bucket="80_plus",
                setup_family="breakout",
                outcome_source="broker",
                realized_pnl=20.0,
            ),
            RecommendationPlanOutcome(
                recommendation_plan_id=4,
                ticker="NVDA",
                action="long",
                outcome="open",
                status="open",
                confidence_percent=72.0,
                confidence_bucket="65_to_79",
                setup_family="continuation",
                outcome_source="plan",
            ),
        ]
        policy = TradeDecisionPolicy(
            policy_id="test-policy",
            confidence_threshold=65.0,
            allow_longs=True,
            allow_shorts=False,
            allowed_setup_families=("continuation",),
        )

        evaluation = PlanPolicyEvaluator(StubEffectiveOutcomeRepository(outcomes)).evaluate(policy)

        self.assertEqual(evaluation.policy_id, "test-policy")
        self.assertEqual(evaluation.total_outcomes, 4)
        self.assertEqual(evaluation.selected_outcomes, 3)
        self.assertEqual(evaluation.resolved_selected_outcomes, 2)
        self.assertEqual(evaluation.broker_selected_outcomes, 1)
        self.assertEqual(evaluation.simulation_selected_outcomes, 1)
        self.assertEqual(evaluation.win_count, 1)
        self.assertEqual(evaluation.loss_count, 1)
        self.assertEqual(evaluation.win_rate_percent, 50.0)
        self.assertEqual(evaluation.average_confidence_percent, 68.0)
        self.assertEqual(evaluation.calibration_gap_percent, 18.0)
        self.assertEqual(evaluation.calibration_penalty, 18.0)
        self.assertEqual(evaluation.realized_pnl, 5.0)
        self.assertEqual(evaluation.average_return_percent, 1.5)
        self.assertEqual(evaluation.average_r_multiple, 0.5)
        self.assertEqual(evaluation.profit_factor, 2.0)
        self.assertEqual(evaluation.robustness_label, "insufficient")
        self.assertEqual(evaluation.selection_rate_percent, 75.0)

    def test_trade_policy_evaluation_service_combines_policy_and_reliability_reports(self) -> None:
        outcomes = [
            RecommendationPlanOutcome(
                recommendation_plan_id=1,
                ticker="AAPL",
                action="long",
                outcome="win",
                status="resolved",
                confidence_percent=60.0,
                confidence_bucket="50_to_64",
                setup_family="continuation",
                outcome_source="broker",
                realized_pnl=12.0,
            ),
            RecommendationPlanOutcome(
                recommendation_plan_id=2,
                ticker="MSFT",
                action="long",
                outcome="loss",
                status="resolved",
                confidence_percent=64.0,
                confidence_bucket="50_to_64",
                setup_family="continuation",
                outcome_source="broker",
                realized_pnl=-4.0,
            ),
        ]
        policy = TradeDecisionPolicy(
            policy_id="combined-policy",
            confidence_threshold=50.0,
            allow_longs=True,
            allow_shorts=True,
            allowed_setup_families=("continuation",),
        )

        repository = StubEffectiveOutcomeRepository(outcomes)
        summary = TradePolicyEvaluationService(repository).summarize(policy)

        self.assertEqual(repository.list_outcomes_calls, 1)
        self.assertEqual(summary.policy_evaluation.policy_id, "combined-policy")
        self.assertEqual(summary.policy_evaluation.resolved_selected_outcomes, 2)
        self.assertEqual(summary.reliability_report.total_outcomes, 2)
        self.assertEqual(summary.reliability_report.resolved_outcomes, 2)
        self.assertEqual(summary.reliability_report.by_confidence_bucket[0].key, "50_to_64")

    def test_plan_reliability_report_summarizes_canonical_effective_cohorts(self) -> None:
        outcomes = [
            RecommendationPlanOutcome(
                recommendation_plan_id=1,
                ticker="AAPL",
                action="long",
                outcome="win",
                status="resolved",
                confidence_percent=60.0,
                confidence_bucket="50_to_64",
                setup_family="continuation",
                outcome_source="broker",
                realized_pnl=12.0,
                realized_return_pct=3.0,
                realized_r_multiple=1.5,
            ),
            RecommendationPlanOutcome(
                recommendation_plan_id=2,
                ticker="MSFT",
                action="long",
                outcome="loss",
                status="resolved",
                confidence_percent=64.0,
                confidence_bucket="50_to_64",
                setup_family="continuation",
                outcome_source="broker",
                realized_pnl=-4.0,
                realized_return_pct=-1.0,
                realized_r_multiple=-1.0,
            ),
            RecommendationPlanOutcome(
                recommendation_plan_id=3,
                ticker="TSLA",
                action="short",
                outcome="open",
                status="open",
                confidence_percent=72.0,
                confidence_bucket="65_to_79",
                setup_family="breakout",
                outcome_source="plan",
            ),
        ]

        report = PlanReliabilityReportService(StubEffectiveOutcomeRepository(outcomes)).summarize()

        self.assertEqual(report.total_outcomes, 3)
        self.assertEqual(report.resolved_outcomes, 2)
        self.assertEqual(report.broker_outcomes, 2)
        bucket = report.by_confidence_bucket[0]
        self.assertEqual(bucket.key, "50_to_64")
        self.assertEqual(bucket.resolved_count, 2)
        self.assertEqual(bucket.win_count, 1)
        self.assertEqual(bucket.loss_count, 1)
        self.assertEqual(bucket.win_rate_percent, 50.0)
        self.assertEqual(bucket.average_confidence_percent, 62.0)
        self.assertEqual(bucket.calibration_gap_percent, 12.0)
        self.assertEqual(bucket.realized_pnl, 8.0)
        self.assertEqual(bucket.average_r_multiple, 0.25)
        self.assertEqual(bucket.profit_factor, 3.0)
        self.assertEqual(bucket.sample_status, "insufficient")
        self.assertEqual(bucket.broker_outcome_count, 2)

    def test_recommendation_outcome_cohort_builder_reuses_shared_bucket_math(self) -> None:
        outcomes = [
            RecommendationPlanOutcome(
                recommendation_plan_id=10,
                ticker="AAPL",
                action="long",
                outcome="win",
                status="resolved",
                setup_family="continuation",
                horizon="1w",
                confidence_percent=62.0,
                outcome_source="broker",
                max_favorable_excursion=4.0,
                max_adverse_excursion=-1.0,
            ),
            RecommendationPlanOutcome(
                recommendation_plan_id=11,
                ticker="MSFT",
                action="long",
                outcome="loss",
                status="resolved",
                setup_family="continuation",
                horizon="1w",
                confidence_percent=58.0,
                outcome_source="broker",
                max_favorable_excursion=1.0,
                max_adverse_excursion=-3.0,
            ),
            RecommendationPlanOutcome(
                recommendation_plan_id=12,
                ticker="TSLA",
                action="long",
                outcome="open",
                status="open",
                setup_family="continuation",
                horizon="1w",
                confidence_percent=55.0,
                outcome_source="plan",
                max_favorable_excursion=0.5,
                max_adverse_excursion=-0.5,
            ),
        ]

        builder = RecommendationOutcomeCohortBuilder()
        family_buckets = builder.grouped_summary(outcomes, group_by="setup_family", default_key="uncategorized", min_required_resolved_count=2)
        horizon_family_buckets = builder.combined_summary(
            outcomes,
            "horizon",
            "setup_family",
            default_left="unknown_horizon",
            default_right="uncategorized",
            slice_name="horizon_setup_family",
            min_required_resolved_count=2,
        )

        self.assertEqual(family_buckets[0].key, "continuation")
        self.assertEqual(family_buckets[0].resolved_count, 2)
        self.assertEqual(family_buckets[0].sample_status, "usable")
        self.assertEqual(family_buckets[0].win_rate_percent, 50.0)
        self.assertEqual(family_buckets[0].average_return_5d, None)
        self.assertEqual(horizon_family_buckets[0].slice_name, "horizon_setup_family")
        self.assertEqual(horizon_family_buckets[0].resolved_count, 2)

    def test_execution_candidate_builder_splits_plan_from_broker_candidate(self) -> None:
        plan = RecommendationPlan(
            id=42,
            ticker="AAPL",
            horizon=StrategyHorizon.ONE_WEEK,
            action="long",
            confidence_percent=70.0,
            entry_price_low=99.0,
            entry_price_high=101.0,
            stop_loss=95.0,
            take_profit=110.0,
            thesis_summary="Candidate split",
        )

        result = ExecutionCandidateBuilder().build(plan, notional_per_plan=1000.0, run_id=7)

        self.assertTrue(result.is_candidate)
        self.assertIsNotNone(result.candidate)
        assert result.candidate is not None
        self.assertEqual(result.candidate.entry_price, 100.0)
        self.assertEqual(result.candidate.quantity, 10)
        self.assertEqual(result.candidate.client_order_id, "tp-run-7-plan-42-aapl")
        self.assertEqual(result.candidate.side, "buy")

    def test_execution_candidate_builder_returns_skip_reason_for_invalid_plan(self) -> None:
        plan = RecommendationPlan(
            id=43,
            ticker="AAPL",
            horizon=StrategyHorizon.ONE_WEEK,
            action="long",
            confidence_percent=70.0,
            entry_price_low=100.0,
            stop_loss=105.0,
            take_profit=110.0,
            thesis_summary="Invalid candidate",
        )

        result = ExecutionCandidateBuilder().build(plan, notional_per_plan=1000.0, run_id=7)

        self.assertFalse(result.is_candidate)
        self.assertEqual(result.skip_reason, "invalid_trade_levels")

    def test_settings_domain_service_splits_strategy_risk_execution_and_operator_settings(self) -> None:
        session = create_session()
        try:
            domains = SettingsDomainService(session)

            strategy = domains.strategy_settings()
            risk = domains.risk_settings()
            execution = domains.execution_settings()
            operator = domains.operator_settings()
            scheduler = domains.scheduler_settings()

            self.assertIn("confidence_threshold", strategy.to_dict())
            self.assertIn("enabled", risk.risk_management)
            self.assertIn("enabled", execution.broker_order_execution)
            self.assertIn("friction_pct", execution.evaluation_realism)
            self.assertIn("summary_backend", operator.summary)
            self.assertIn("social_nitter_enabled", operator.social)
            self.assertIn("last_poll_at", scheduler.to_dict())
        finally:
            session.close()

    def test_risk_manager_returns_canonical_account_risk_state(self) -> None:
        session = create_session()
        try:
            assessment = BrokerRiskManager(SettingsRepository(session), BrokerPositionRepository(session)).assess()
            self.assertIsInstance(assessment, AccountRiskState)
            self.assertTrue(assessment.enabled)
            self.assertIn("enabled", assessment.config)
        finally:
            session.close()

    def test_settings_mutation_service_updates_typed_settings(self) -> None:
        session = create_session()
        try:
            service = SettingsMutationService(session)

            app_setting = service.set_app_setting(key=" custom_key ", value=" custom value ")
            self.assertEqual(app_setting.key, "custom_key")
            self.assertEqual(app_setting.value, "custom value")

            confidence_threshold = service.set_confidence_threshold("72.5")
            self.assertEqual(confidence_threshold.key, "confidence_threshold")
            self.assertEqual(confidence_threshold.value, "72.5")

            evaluation = service.set_evaluation_realism_settings(stop_buffer_pct="0.2", take_profit_buffer_pct="", friction_pct="0.3")
            self.assertEqual(evaluation["stop_buffer_pct"], 0.2)
            self.assertEqual(evaluation["take_profit_buffer_pct"], 0.05)
            self.assertEqual(evaluation["friction_pct"], 0.3)

            summary = service.set_summary_settings(backend="pi_agent", model="gpt-4o", timeout_seconds="70", max_tokens="250", pi_command="pi", pi_agent_dir="", pi_cli_args="", prompt="")
            self.assertIn("settings", summary)
            self.assertIn("summary_backend", summary["settings"])

            social = service.set_social_settings(sentiment_enabled="true", nitter_enabled="false")
            self.assertIn("settings", social)
            self.assertIn("social_sentiment_enabled", social["settings"])

            signal = service.set_signal_gating_tuning_settings(threshold_offset="1.5", confidence_adjustment="-0.5", near_miss_gap_cutoff="0.25", shortlist_aggressiveness="2.0", degraded_penalty="4.0")
            self.assertEqual(signal["signal_gating_tuning"]["threshold_offset"], 1.5)
            self.assertEqual(signal["signal_gating_tuning"]["confidence_adjustment"], -0.5)

            risk = service.set_risk_management_settings(enabled="false", max_daily_realized_loss_usd="12.5", max_open_positions="4", max_open_notional_usd="4000", max_position_notional_usd="1200", max_same_ticker_open_positions="2", max_consecutive_losses="5")
            self.assertFalse(risk["risk_management"]["enabled"])
            self.assertEqual(risk["risk_management"]["max_open_positions"], 4)

            halt = service.set_risk_halt(enabled=True, reason="manual halt")
            self.assertTrue(halt["halt_enabled"])
            self.assertEqual(halt["halt_reason"], "manual halt")

            execution = service.set_order_execution_settings(enabled="true", broker="alpaca", account_mode="paper", notional_per_plan="1500")
            self.assertTrue(execution["order_execution"]["enabled"])
            self.assertEqual(execution["order_execution"]["notional_per_plan"], 1500.0)

            provider = service.set_provider_credential(provider="alpaca", api_key="key", api_secret="secret")
            self.assertEqual(provider["provider"], "alpaca")
            self.assertEqual(provider["api_key"], "key")
        finally:
            session.close()

    def test_broker_reconciliation_service_builds_workbench_read_model(self) -> None:
        session = create_session()
        try:
            plan_repository = RecommendationPlanRepository(session)
            plan = plan_repository.create_plan(
                RecommendationPlan(
                    ticker="AAPL",
                    horizon=StrategyHorizon.ONE_WEEK,
                    action="long",
                    confidence_percent=68.0,
                    entry_price_low=100.0,
                    entry_price_high=101.0,
                    stop_loss=96.0,
                    take_profit=110.0,
                    thesis_summary="Broker workbench",
                )
            )
            BrokerOrderExecutionRepository(session).create(
                BrokerOrderExecution(
                    broker="alpaca",
                    account_mode="paper",
                    recommendation_plan_id=plan.id or 0,
                    recommendation_plan_ticker="AAPL",
                    ticker="AAPL",
                    action="long",
                    side="buy",
                    order_type="limit",
                    quantity=10,
                    notional_amount=1000.0,
                    entry_price=100.0,
                    stop_loss=96.0,
                    take_profit=110.0,
                    status="open",
                    broker_order_id="alpaca-order-1",
                    client_order_id="tp-run-1-plan-1-aapl-live",
                    request_payload={"symbol": "AAPL"},
                    response_payload={"id": "alpaca-order-1", "status": "filled"},
                )
            )

            workbench = BrokerReconciliationService(session).build_workbench(limit=10)

            self.assertIn("broker_orders", workbench)
            self.assertIn("broker_positions", workbench)
            self.assertIn("risk", workbench)
            self.assertIn("counts", workbench)
            self.assertEqual(workbench["counts"]["broker_orders"], 1)
            self.assertEqual(workbench["counts"]["broker_positions"], 0)
        finally:
            session.close()

    def test_trade_decision_policy_service_normalizes_active_strategy_policy(self) -> None:
        session = create_session()
        try:
            settings = SettingsRepository(session)
            settings.set_confidence_threshold(62.0)
            settings.set_signal_gating_tuning_config(
                threshold_offset=3.0,
                confidence_adjustment=-1.5,
                near_miss_gap_cutoff=0.25,
                shortlist_aggressiveness=2.0,
                degraded_penalty=4.0,
            )

            policy = TradeDecisionPolicyService(session).active_policy()

            self.assertEqual(policy.policy_id, "settings-active:baseline")
            self.assertEqual(policy.confidence_threshold, 62.0)
            self.assertEqual(policy.effective_confidence_threshold(), 65.0)
            self.assertEqual(policy.signal_gating.confidence_adjustment, -1.5)
            self.assertIn("global.entry_band_risk_fraction", policy.plan_generation_config)
            self.assertTrue(policy.action_allowed("long"))
            self.assertTrue(policy.action_allowed("short"))
            self.assertFalse(policy.action_allowed("no_action"))
        finally:
            session.close()

    def test_trade_decision_policy_applies_action_and_setup_family_filters(self) -> None:
        policy = TradeDecisionPolicy(
            policy_id="test-policy",
            confidence_threshold=60.0,
            allow_longs=True,
            allow_shorts=False,
            allowed_setup_families=("breakout", "continuation"),
            blocked_setup_families=("continuation",),
        )

        self.assertTrue(policy.action_allowed("long"))
        self.assertFalse(policy.action_allowed("short"))
        self.assertTrue(policy.setup_family_allowed("breakout"))
        self.assertFalse(policy.setup_family_allowed("continuation"))
        self.assertFalse(policy.setup_family_allowed("mean_reversion"))
        self.assertEqual(policy.to_dict()["effective_confidence_threshold"], 60.0)

    def test_trading_performance_metrics_summarizes_broker_and_effective_outcomes(self) -> None:
        session = create_session()
        try:
            plan_repository = RecommendationPlanRepository(session)
            for index, status in enumerate(["win", "loss"], start=1):
                plan = plan_repository.create_plan(
                    RecommendationPlan(
                        ticker=f"MET{index}",
                        horizon=StrategyHorizon.ONE_WEEK,
                        action="long",
                        confidence_percent=70.0,
                        thesis_summary="Shared metrics",
                        signal_breakdown={"setup_family": "continuation"},
                    )
                )
                BrokerPositionRepository(session).create(
                    BrokerPosition(
                        broker_order_execution_id=index,
                        broker="alpaca",
                        account_mode="paper",
                        recommendation_plan_id=plan.id or 0,
                        recommendation_plan_ticker=f"MET{index}",
                        ticker=f"MET{index}",
                        action="long",
                        side="buy",
                        quantity=1,
                        current_quantity=0,
                        status=status,
                        exit_filled_at=datetime.now(timezone.utc),
                        realized_pnl=12.0 if status == "win" else -4.0,
                        realized_return_pct=6.0 if status == "win" else -2.0,
                        realized_r_multiple=1.5 if status == "win" else -1.0,
                    )
                )
            simulation_plan = plan_repository.create_plan(
                RecommendationPlan(
                    ticker="SIM1",
                    horizon=StrategyHorizon.ONE_WEEK,
                    action="long",
                    confidence_percent=55.0,
                    thesis_summary="Simulation metric",
                    signal_breakdown={"setup_family": "breakout"},
                )
            )
            RecommendationOutcomeRepository(session).upsert_outcome(
                RecommendationPlanOutcome(
                    recommendation_plan_id=simulation_plan.id or 0,
                    ticker="SIM1",
                    action="long",
                    outcome="win",
                    status="resolved",
                    confidence_bucket="50_to_64",
                    setup_family="breakout",
                )
            )

            service = TradingPerformanceMetricsService(session)
            broker = service.summarize_broker_closed_positions()
            effective = service.summarize_effective_outcomes()

            self.assertEqual(broker.closed_positions, 2)
            self.assertEqual(broker.wins, 1)
            self.assertEqual(broker.losses, 1)
            self.assertEqual(broker.win_rate_percent, 50.0)
            self.assertEqual(broker.realized_pnl, 8.0)
            self.assertEqual(broker.average_return_percent, 2.0)
            self.assertEqual(broker.average_r_multiple, 0.25)
            self.assertEqual(effective.total_outcomes, 3)
            self.assertEqual(effective.resolved_outcomes, 3)
            self.assertEqual(effective.broker_outcomes, 2)
            self.assertEqual(effective.simulation_outcomes, 1)
            self.assertEqual(effective.win_rate_percent, 66.7)
        finally:
            session.close()

    def test_recommendation_plan_repository_counts_closed_broker_orders_as_resolved(self) -> None:
        session = create_session()
        plan_repository = RecommendationPlanRepository(session)
        broker_repository = BrokerOrderExecutionRepository(session)

        plan = plan_repository.create_plan(
            RecommendationPlan(
                ticker="NVDA",
                horizon=StrategyHorizon.ONE_WEEK,
                action="long",
                confidence_percent=72.0,
                thesis_summary="Closed broker winner should count as resolved",
                signal_breakdown={"setup_family": "continuation"},
            )
        )
        broker_repository.create(
            BrokerOrderExecution(
                broker="alpaca",
                account_mode="paper",
                recommendation_plan_id=plan.id or 0,
                recommendation_plan_ticker="NVDA",
                ticker="NVDA",
                action="long",
                side="buy",
                order_type="limit",
                quantity=2,
                notional_amount=500.0,
                entry_price=100.0,
                stop_loss=95.0,
                take_profit=110.0,
                status="win",
                broker_order_id="alpaca-order-win",
                client_order_id="tp-run-1-plan-1-nvda-live",
                submitted_at=datetime.now(timezone.utc),
                filled_at=datetime.now(timezone.utc),
                request_payload={"symbol": "NVDA"},
                response_payload={"id": "alpaca-order-win", "status": "filled"},
            )
        )

        loaded = plan_repository.get_plan(plan.id or 0)
        self.assertEqual(loaded.effective_evaluation_source, "broker")
        self.assertEqual(loaded.effective_evaluation, "win")
        self.assertEqual(plan_repository.list_plans(ticker="NVDA", resolved="resolved")[0].id, plan.id)
        self.assertEqual(plan_repository.list_plans(ticker="NVDA", outcome="win")[0].id, plan.id)
        stats = plan_repository.summarize_stats(ticker="NVDA")
        self.assertEqual(stats.open_plans, 0)
        self.assertEqual(stats.win_outcomes, 1)

    def test_recommendation_plan_repository_marks_failed_broker_orders_as_missing(self) -> None:
        session = create_session()
        plan_repository = RecommendationPlanRepository(session)
        broker_repository = BrokerOrderExecutionRepository(session)

        plan = plan_repository.create_plan(
            RecommendationPlan(
                ticker="TSLA",
                horizon=StrategyHorizon.ONE_WEEK,
                action="long",
                confidence_percent=68.0,
                thesis_summary="Failed broker order should not be treated as pending evaluation",
                signal_breakdown={"setup_family": "continuation"},
            )
        )
        broker_repository.create(
            BrokerOrderExecution(
                broker="alpaca",
                account_mode="paper",
                recommendation_plan_id=plan.id or 0,
                recommendation_plan_ticker="TSLA",
                ticker="TSLA",
                action="long",
                side="buy",
                order_type="limit",
                quantity=5,
                notional_amount=500.0,
                entry_price=100.0,
                stop_loss=95.0,
                take_profit=110.0,
                status="failed",
                broker_order_id="alpaca-order-failed",
                client_order_id="tp-run-1-plan-1-tsla-live",
                submitted_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                request_payload={"symbol": "TSLA"},
                response_payload={"id": "alpaca-order-failed", "status": "failed"},
                error_message="rejected by broker",
            )
        )

        loaded = plan_repository.get_plan(plan.id or 0)
        self.assertEqual(loaded.broker_order_status, "failed")
        self.assertEqual(loaded.effective_evaluation_source, "missing")
        self.assertIsNone(loaded.effective_evaluation)
        self.assertIn("failed", loaded.effective_evaluation_detail)
        self.assertEqual(loaded.latest_outcome, None)

    def test_recommendation_plan_repository_filters_shortlisted_state(self) -> None:
        session = create_session()
        plan_repository = RecommendationPlanRepository(session)

        shortlisted_plan = plan_repository.create_plan(
            RecommendationPlan(
                ticker="AAPL",
                horizon=StrategyHorizon.ONE_WEEK,
                action="long",
                confidence_percent=70.0,
                thesis_summary="Shortlisted plan",
                signal_breakdown={"setup_family": "continuation", "shortlisted": True, "shortlist_rank": 1},
                evidence_summary={"action_reason": "promoted"},
            )
        )
        not_shortlisted_plan = plan_repository.create_plan(
            RecommendationPlan(
                ticker="MSFT",
                horizon=StrategyHorizon.ONE_WEEK,
                action="no_action",
                confidence_percent=35.0,
                thesis_summary="Rejected before deep analysis",
                signal_breakdown={"setup_family": "continuation"},
                evidence_summary={"action_reason": "not_shortlisted"},
            )
        )

        shortlisted = plan_repository.list_plans(shortlisted=True, limit=10)
        rejected = plan_repository.list_plans(shortlisted=False, limit=10)

        self.assertEqual([plan.id for plan in shortlisted], [shortlisted_plan.id])
        self.assertEqual([plan.id for plan in rejected], [not_shortlisted_plan.id])
        self.assertEqual(plan_repository.count_plans(shortlisted=True), 1)
        self.assertEqual(plan_repository.count_plans(shortlisted=False), 1)
        self.assertEqual(plan_repository.summarize_stats(shortlisted=True).total_plans, 1)
        self.assertEqual(plan_repository.summarize_stats(shortlisted=False).total_plans, 1)

    def test_recommendation_outcome_upsert_recovers_from_integrity_error(self) -> None:
        session = create_session()
        context_repository = ContextSnapshotRepository(session)
        plan_repository = RecommendationPlanRepository(session)
        outcome_repository = RecommendationOutcomeRepository(session)

        ticker_signal = context_repository.create_ticker_signal_snapshot(
            TickerSignalSnapshot(
                ticker="AAPL",
                horizon=StrategyHorizon.ONE_WEEK,
                direction="long",
                swing_probability_percent=62.0,
                confidence_percent=66.0,
                attention_score=77.0,
                diagnostics={"stage": "retry-path"},
            )
        )
        plan = plan_repository.create_plan(
            RecommendationPlan(
                ticker="AAPL",
                horizon=StrategyHorizon.ONE_WEEK,
                action="long",
                status="ok",
                confidence_percent=66.0,
                entry_price_low=180.0,
                entry_price_high=181.0,
                stop_loss=176.0,
                take_profit=188.0,
                holding_period_days=5,
                risk_reward_ratio=1.8,
                thesis_summary="Retry coverage",
                rationale_summary="Testing retry behavior",
                risks=["market noise"],
                signal_breakdown={"setup_family": "momentum"},
                ticker_signal_snapshot_id=ticker_signal.id,
            )
        )
        outcome_repository.upsert_outcome(
            RecommendationPlanOutcome(
                recommendation_plan_id=plan.id or 0,
                ticker="AAPL",
                action="long",
                outcome="win",
                status="resolved",
                confidence_bucket="65_to_79",
                setup_family="momentum",
            )
        )

        original_commit = session.commit
        commit_calls = {"count": 0}

        def commit_side_effect():
            commit_calls["count"] += 1
            if commit_calls["count"] == 1:
                raise IntegrityError("stmt", "params", Exception("duplicate"))
            return original_commit()

        with patch.object(session, "commit", side_effect=commit_side_effect), patch.object(session, "rollback", wraps=session.rollback) as rollback_mock:
            stored = outcome_repository.upsert_outcome(
                RecommendationPlanOutcome(
                    recommendation_plan_id=plan.id or 0,
                    ticker="AAPL",
                    action="long",
                    outcome="loss",
                    status="resolved",
                    confidence_bucket="65_to_79",
                    setup_family="momentum",
                    notes="updated after retry",
                )
            )

        self.assertEqual(stored.outcome, "loss")
        self.assertGreaterEqual(rollback_mock.call_count, 1)

    def test_recommendation_outcome_upsert_overwrites_resolved_outcome_on_recompute(self) -> None:
        session = create_session()
        outcome_repository = RecommendationOutcomeRepository(session)
        plan_repository = RecommendationPlanRepository(session)

        plan = plan_repository.create_plan(
            RecommendationPlan(
                ticker="EOG",
                horizon=StrategyHorizon.ONE_WEEK,
                action="long",
                confidence_percent=67.95,
                entry_price_low=151.8925,
                entry_price_high=151.8925,
                stop_loss=149.0889,
                take_profit=156.2066,
                signal_breakdown={"setup_family": "catalyst_follow_through"},
                computed_at=datetime(2026, 3, 30, 15, 0, tzinfo=timezone.utc),
            )
        )
        outcome_repository.upsert_outcome(
            RecommendationPlanOutcome(
                recommendation_plan_id=plan.id or 0,
                ticker="EOG",
                action="long",
                outcome="loss",
                status="resolved",
                confidence_bucket="65_to_79",
                setup_family="catalyst_follow_through",
            )
        )

        stored = outcome_repository.upsert_outcome(
            RecommendationPlanOutcome(
                recommendation_plan_id=plan.id or 0,
                ticker="EOG",
                action="long",
                outcome="no_entry",
                status="open",
                confidence_bucket="65_to_79",
                setup_family="catalyst_follow_through",
                notes="recomputed with updated algorithm",
            )
        )

        self.assertEqual(stored.outcome, "no_entry")
        self.assertEqual(stored.status, "open")
        self.assertEqual(stored.notes, "recomputed with updated algorithm")

    def test_recommendation_outcome_repository_summarizes_entry_miss_diagnostics(self) -> None:
        session = create_session()
        plan_repository = RecommendationPlanRepository(session)
        outcome_repository = RecommendationOutcomeRepository(session)
        plan = plan_repository.create_plan(
            RecommendationPlan(
                ticker="EOG",
                horizon=StrategyHorizon.ONE_WEEK,
                action="long",
                confidence_percent=67.95,
                entry_price_low=151.8925,
                entry_price_high=151.8925,
                stop_loss=149.0889,
                take_profit=156.2066,
                signal_breakdown={"setup_family": "catalyst_follow_through"},
                computed_at=datetime(2026, 3, 30, 15, 0, tzinfo=timezone.utc),
            )
        )
        outcome_repository.upsert_outcome(
            RecommendationPlanOutcome(
                recommendation_plan_id=plan.id or 0,
                ticker="EOG",
                action="long",
                outcome="expired",
                status="resolved",
                entry_touched=False,
                entry_miss_distance_percent=0.12,
                near_entry_miss=True,
                direction_worked_without_entry=True,
                confidence_bucket="65_to_79",
                setup_family="catalyst_follow_through",
            )
        )

        summary = outcome_repository.summarize_entry_miss_diagnostics()
        self.assertEqual(summary["never_entered_count"], 1)
        self.assertEqual(summary["near_entry_miss_count"], 1)
        self.assertEqual(summary["direction_worked_without_entry_count"], 1)
        self.assertEqual(summary["near_entry_and_worked_count"], 1)
        self.assertEqual(summary["near_entry_and_worked_rate_percent"], 100.0)
        self.assertEqual(summary["average_entry_miss_distance_percent"], 0.12)

    def test_historical_market_data_list_bars_handles_missing_available_at_column(self) -> None:
        engine = create_engine("sqlite:///:memory:", future=True)
        with engine.begin() as connection:
            connection.exec_driver_sql(
                """
                CREATE TABLE historical_market_bars (
                    id INTEGER PRIMARY KEY,
                    ticker VARCHAR(32) NOT NULL,
                    timeframe VARCHAR(16) NOT NULL,
                    bar_time DATETIME NOT NULL,
                    open_price FLOAT NOT NULL,
                    high_price FLOAT NOT NULL,
                    low_price FLOAT NOT NULL,
                    close_price FLOAT NOT NULL,
                    volume FLOAT NOT NULL,
                    adjusted_close FLOAT,
                    source VARCHAR(64) NOT NULL,
                    source_tier VARCHAR(32) NOT NULL,
                    point_in_time_confidence FLOAT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
            connection.exec_driver_sql(
                """
                INSERT INTO historical_market_bars (
                    id, ticker, timeframe, bar_time, open_price, high_price, low_price, close_price,
                    volume, adjusted_close, source, source_tier, point_in_time_confidence, metadata_json,
                    created_at, updated_at
                ) VALUES
                    (1, 'EOG', '1d', '2026-03-28 00:00:00', 150.0, 151.0, 149.0, 150.5, 1000.0, NULL, 'seed', 'research', 1.0, '{}', '2026-03-28 00:00:00', '2026-03-28 00:00:00'),
                    (2, 'EOG', '1d', '2026-03-29 00:00:00', 151.0, 152.0, 150.0, 151.5, 1000.0, NULL, 'seed', 'research', 1.0, '{}', '2026-03-29 00:00:00', '2026-03-29 00:00:00'),
                    (3, 'EOG', '1d', '2026-03-30 00:00:00', 152.0, 153.0, 151.0, 152.5, 1000.0, NULL, 'seed', 'research', 1.0, '{}', '2026-03-30 00:00:00', '2026-03-30 00:00:00')
                """
            )
        repo = HistoricalMarketDataRepository(Session(bind=engine))
        bars = repo.list_bars(
            ticker="EOG",
            timeframe="1d",
            end_at=datetime(2026, 3, 31, tzinfo=timezone.utc),
            available_at=datetime(2026, 3, 31, tzinfo=timezone.utc),
            limit=2,
        )

        self.assertEqual(len(bars), 2)
        self.assertEqual(bars[0].bar_time, datetime(2026, 3, 29, tzinfo=timezone.utc))
        self.assertEqual(bars[1].bar_time, datetime(2026, 3, 30, tzinfo=timezone.utc))
        self.assertEqual(bars[1].available_at, datetime(2026, 3, 30, 23, 59, 59, tzinfo=timezone.utc))
        self.assertEqual(bars[1].high_price, 153.0)

    def test_historical_market_data_infers_intraday_available_at(self) -> None:
        inferred = HistoricalMarketDataRepository._infer_available_at(
            datetime(2026, 3, 31, 15, 0, tzinfo=timezone.utc),
            "5m",
        )

        self.assertEqual(inferred, datetime(2026, 3, 31, 15, 5, tzinfo=timezone.utc))

    def test_job_execution_enqueues_and_processes_run(self) -> None:
        session = create_session()
        jobs = JobRepository(session)
        runs = RunRepository(session)
        job = jobs.create("Morning", ["NVDA", "TSLA"], None)

        service = JobExecutionService(
            jobs=jobs,
            runs=runs,
            watchlist_orchestration=StubWatchlistOrchestrationService(),
        )
        queued_run = service.enqueue_job(job.id or 0)
        self.assertEqual(queued_run.status, "queued")

        duplicate = service.enqueue_job(job.id or 0)
        self.assertEqual(duplicate.id, queued_run.id)

        processed_run, recommendations = service.process_next_queued_run()

        self.assertIsNotNone(processed_run)
        self.assertEqual(recommendations, [])
        latest_runs = runs.list_latest_runs()
        self.assertEqual(len(latest_runs), 1)
        self.assertIn(latest_runs[0].status, {"completed", "completed_with_warnings"})
        self.assertIsNone(latest_runs[0].error_message)
        self.assertIsNotNone(latest_runs[0].started_at)
        self.assertIsNotNone(latest_runs[0].completed_at)
        self.assertIsNotNone(latest_runs[0].duration_seconds)
        self.assertIsNotNone(latest_runs[0].timing_json)
        assert latest_runs[0].timing_json is not None
        self.assertIn('"ticker_generation"', latest_runs[0].timing_json)
        refreshed_job = jobs.get(job.id or 0)
        self.assertIsNotNone(refreshed_job.last_enqueued_at)

    def test_job_execution_processes_watchlist_cheap_scan_shortlist_and_deep_analysis(self) -> None:
        session = create_session()
        watchlists = WatchlistRepository(session)
        jobs = JobRepository(session)
        runs = RunRepository(session)
        watchlist = watchlists.create(
            "Core Tech",
            ["AAPL", "MSFT", "TSLA"],
            default_horizon=StrategyHorizon.ONE_WEEK,
            allow_shorts=False,
        )
        job = jobs.create("Core Tech Run", [], None, watchlist_id=watchlist.id)
        queued_run = runs.enqueue(job.id or 0)
        orchestration = WatchlistOrchestrationService(
            context_snapshots=ContextSnapshotRepository(session),
            recommendation_plans=RecommendationPlanRepository(session),
            decision_samples=RecommendationDecisionSampleRepository(session),
            cheap_scan_service=CheapScanProposalService(),
            deep_analysis_service=TickerDeepAnalysisService(DeepAnalysisProposalService()),
            confidence_threshold=60.0,
        )
        service = JobExecutionService(
            jobs=jobs,
            runs=runs,
            watchlist_orchestration=orchestration,
        )

        processed_run, recommendations = service.process_next_queued_run()

        self.assertIsNotNone(processed_run)
        self.assertEqual(processed_run.status, "completed")
        self.assertEqual(recommendations, [])
        stored_run = runs.get_run(queued_run.id or 0)
        self.assertIn('"mode": "watchlist_orchestration"', stored_run.summary_json or "")
        self.assertIn('"shortlist_count": 1', stored_run.summary_json or "")
        self.assertIn('"shortlist_rules": {', stored_run.summary_json or "")
        self.assertIn('"shortlist_rejections": {', stored_run.summary_json or "")
        self.assertIn('"shortlist": [', stored_run.artifact_json or "")
        self.assertIn('"shortlist_decisions": [', stored_run.artifact_json or "")
        summary_payload = json.loads(stored_run.summary_json or "{}")
        artifact_payload = json.loads(stored_run.artifact_json or "{}")
        self.assertEqual(summary_payload["source_kind"], "watchlist")
        self.assertEqual(summary_payload["execution_path"], "redesign_orchestration")
        self.assertEqual(summary_payload["effective_horizon"], "1w")
        self.assertEqual(summary_payload["shortlist_rules"]["minimum_confidence_percent"], 48.0)
        self.assertEqual(summary_payload["shortlist_rules"]["minimum_attention_score"], 45.0)
        self.assertEqual(summary_payload["shortlist_rejections"]["shorts_disabled"], 1)
        self.assertEqual(summary_payload["shortlist_rejections"]["below_confidence_threshold"], 1)
        rejection_detail_map = {item["key"]: item for item in summary_payload["shortlist_rejection_details"]}
        self.assertEqual(rejection_detail_map["shorts_disabled"]["label"], "shorts disabled")
        self.assertIn("ticker_generation", artifact_payload)
        ticker_generation_map = {item["ticker"]: item for item in artifact_payload["ticker_generation"]}
        self.assertEqual(ticker_generation_map["AAPL"]["cheap_scan_price_history"]["source"], "database")
        self.assertEqual(ticker_generation_map["AAPL"]["deep_analysis_price_history"]["source"], "remote")
        decisions = {item["ticker"]: item for item in artifact_payload["shortlist_decisions"]}
        self.assertEqual(decisions["AAPL"]["shortlisted"], True)
        self.assertEqual(decisions["AAPL"]["shortlist_rank"], 1)
        self.assertEqual(decisions["AAPL"]["selection_lane"], "technical")
        self.assertEqual(decisions["AAPL"]["selection_lane_label"], "technical")
        self.assertEqual(decisions["MSFT"]["reasons"], ["shorts_disabled", "below_catalyst_lane_threshold"])
        self.assertEqual(decisions["MSFT"]["reason_details"][0]["label"], "shorts disabled")
        self.assertEqual(decisions["TSLA"]["reasons"], ["below_confidence_threshold", "below_attention_threshold", "below_catalyst_lane_threshold"])
        ticker_signals = ContextSnapshotRepository(session).list_ticker_signal_snapshots(limit=10)
        plans = RecommendationPlanRepository(session).list_plans(limit=10)
        samples = RecommendationDecisionSampleRepository(session).list_samples(limit=10)
        self.assertEqual(len(ticker_signals), 3)
        self.assertEqual(len(plans), 1)
        self.assertEqual(len(samples), 3)
        action_map = {plan.ticker: plan.action for plan in plans}
        self.assertEqual(action_map["AAPL"], "long")
        sample_map = {sample.ticker: sample for sample in samples}
        self.assertEqual(sample_map["AAPL"].action, "long")
        self.assertIsNotNone(sample_map["AAPL"].recommendation_plan_id)
        self.assertEqual(sample_map["MSFT"].action, "no_action")
        self.assertIsNone(sample_map["MSFT"].recommendation_plan_id)
        self.assertEqual(sample_map["MSFT"].decision_reason, "not_shortlisted")
        self.assertEqual(sample_map["TSLA"].action, "no_action")
        self.assertIsNone(sample_map["TSLA"].recommendation_plan_id)
        self.assertEqual(sample_map["TSLA"].decision_reason, "not_shortlisted")
        plan_map = {plan.ticker: plan for plan in plans}
        self.assertIsInstance(plan_map["AAPL"].signal_breakdown, RecommendationPlanSignalBreakdown)
        self.assertIsInstance(plan_map["AAPL"].signal_breakdown.get("transmission_summary"), RecommendationTransmissionSummary)
        self.assertEqual(plan_map["AAPL"].signal_breakdown["setup_family"], "breakout")
        self.assertEqual(plan_map["AAPL"].signal_breakdown["confidence_bucket"], "65_to_79")
        self.assertAlmostEqual(plan_map["AAPL"].signal_breakdown["cheap_scan_confidence_percent"], 84.61)
        self.assertEqual(plan_map["AAPL"].signal_breakdown["deep_analysis_confidence_percent"], 78.0)
        self.assertEqual(plan_map["AAPL"].signal_breakdown["raw_plan_confidence_percent"], 78.0)
        self.assertIn("confidence_components", plan_map["AAPL"].signal_breakdown)
        self.assertIsInstance(plan_map["AAPL"].evidence_summary, RecommendationPlanEvidenceSummary)
        self.assertEqual(plan_map["AAPL"].evidence_summary["entry_style"], "break_or_retest")
        self.assertEqual(plan_map["AAPL"].evidence_summary["stop_style"], "below_break_level_with_buffer")
        self.assertEqual(plan_map["AAPL"].evidence_summary["target_style"], "measured_move_or_next_resistance")
        self.assertEqual(plan_map["AAPL"].evidence_summary["timing_expectation"], "2d_5d")
        self.assertIn("follow_through_speed", plan_map["AAPL"].evidence_summary["evaluation_focus"])
        self.assertIn("breakout", plan_map["AAPL"].evidence_summary["invalidation_summary"])
        self.assertEqual(sample_map["TSLA"].evidence_summary["action_reason"], "not_shortlisted")
        self.assertEqual(sample_map["TSLA"].evidence_summary["action_reason_label"], "not shortlisted")
        self.assertIn("did not clear shortlist competition", sample_map["TSLA"].evidence_summary["action_reason_detail"])
        diagnostics_map = {item.ticker: item.diagnostics for item in ticker_signals}
        source_breakdown_map = {item.ticker: item.source_breakdown for item in ticker_signals}
        self.assertIsInstance(diagnostics_map["AAPL"], TickerSignalDiagnostics)
        self.assertIsInstance(source_breakdown_map["AAPL"], TickerSignalSourceBreakdown)
        self.assertEqual(diagnostics_map["AAPL"]["mode"], "deep_analysis")
        self.assertEqual(diagnostics_map["AAPL"]["shortlist_reasons"], [])
        self.assertEqual(diagnostics_map["AAPL"]["shortlist_reason_details"], [])
        self.assertEqual(diagnostics_map["AAPL"]["selection_lane"], "technical")
        self.assertEqual(diagnostics_map["AAPL"]["selection_lane_label"], "technical")
        self.assertEqual(diagnostics_map["AAPL"]["transmission_bias"], "tailwind")
        self.assertIn("primary_drivers", diagnostics_map["AAPL"])
        self.assertIn("primary_driver_details", diagnostics_map["AAPL"])
        self.assertIn("industry_exposure_channel_details", diagnostics_map["AAPL"])
        self.assertIn("ticker_exposure_channel_details", diagnostics_map["AAPL"])
        self.assertIn("transmission_confidence_adjustment", diagnostics_map["AAPL"])
        self.assertEqual(diagnostics_map["AAPL"]["expected_transmission_window"], "2d_5d")
        self.assertEqual(diagnostics_map["AAPL"]["expected_transmission_window_detail"]["label"], "2d-5d")
        self.assertEqual(diagnostics_map["AAPL"]["cheap_scan_price_history"]["source"], "database")
        self.assertEqual(diagnostics_map["AAPL"]["deep_analysis_price_history"]["source"], "remote")
        self.assertEqual(diagnostics_map["TSLA"]["mode"], "cheap_scan_only")
        self.assertEqual(diagnostics_map["TSLA"]["shortlist_reasons"], ["below_confidence_threshold", "below_attention_threshold", "below_catalyst_lane_threshold"])
        self.assertEqual(diagnostics_map["TSLA"]["shortlist_reason_details"][0]["label"], "below confidence threshold")
        self.assertEqual(source_breakdown_map["AAPL"]["deep_analysis_model"], "ticker_deep_analysis_v2")
        self.assertEqual(source_breakdown_map["AAPL"]["transmission_bias"], "tailwind")
        self.assertEqual(source_breakdown_map["AAPL"]["cheap_scan_price_history"]["source"], "database")
        self.assertEqual(source_breakdown_map["AAPL"]["deep_analysis_price_history"]["source"], "remote")
        self.assertIn("primary_drivers", source_breakdown_map["AAPL"])
        self.assertIn("industry_exposure_channel_details", source_breakdown_map["AAPL"])
        self.assertIn("ticker_exposure_channel_details", source_breakdown_map["AAPL"])
        self.assertIn("transmission_confidence_adjustment", source_breakdown_map["AAPL"])
        self.assertIn("transmission_summary", plan_map["AAPL"].signal_breakdown)
        self.assertEqual(plan_map["AAPL"].signal_breakdown["cheap_scan_price_history"]["source"], "database")
        self.assertEqual(plan_map["AAPL"].signal_breakdown["deep_analysis_price_history"]["source"], "remote")
        self.assertIn("primary_drivers", plan_map["AAPL"].signal_breakdown["transmission_summary"])
        self.assertIn("primary_driver_details", plan_map["AAPL"].signal_breakdown["transmission_summary"])
        self.assertIn("industry_exposure_channel_details", plan_map["AAPL"].signal_breakdown["transmission_summary"])
        self.assertIn("ticker_exposure_channel_details", plan_map["AAPL"].signal_breakdown["transmission_summary"])
        self.assertIn("ticker_relationship_edges", plan_map["AAPL"].signal_breakdown["transmission_summary"])
        self.assertIn("matched_ticker_relationships", plan_map["AAPL"].signal_breakdown["transmission_summary"])

    def test_job_execution_processes_manual_ticker_jobs_through_redesign_orchestration(self) -> None:
        session = create_session()
        jobs = JobRepository(session)
        runs = RunRepository(session)
        job = jobs.create("Manual Tech Run", ["AAPL", "TSLA"], None)
        queued_run = runs.enqueue(job.id or 0)
        orchestration = WatchlistOrchestrationService(
            context_snapshots=ContextSnapshotRepository(session),
            recommendation_plans=RecommendationPlanRepository(session),
            cheap_scan_service=CheapScanProposalService(),
            decision_samples=RecommendationDecisionSampleRepository(session),
            deep_analysis_service=TickerDeepAnalysisService(DeepAnalysisProposalService()),
            confidence_threshold=60.0,
        )
        service = JobExecutionService(
            jobs=jobs,
            runs=runs,
            watchlist_orchestration=orchestration,
        )

        processed_run, recommendations = service.process_next_queued_run()

        self.assertIsNotNone(processed_run)
        self.assertEqual(processed_run.status, "completed")
        self.assertEqual(recommendations, [])
        stored_run = runs.get_run(queued_run.id or 0)
        summary_payload = json.loads(stored_run.summary_json or "{}")
        artifact_payload = json.loads(stored_run.artifact_json or "{}")
        self.assertEqual(summary_payload["mode"], "watchlist_orchestration")
        self.assertEqual(summary_payload["source_kind"], "manual_tickers")
        self.assertEqual(summary_payload["execution_path"], "redesign_orchestration")
        self.assertEqual(summary_payload["effective_horizon"], "1w")
        self.assertEqual(summary_payload["manual_job_defaults"]["default_horizon"], "1w")
        self.assertEqual(summary_payload["manual_job_defaults"]["allow_shorts"], True)
        self.assertEqual(summary_payload["manual_job_defaults"]["job_name"], "Manual Tech Run")
        self.assertEqual(artifact_payload["source_kind"], "manual_tickers")
        self.assertEqual(artifact_payload["execution_path"], "redesign_orchestration")
        self.assertEqual(artifact_payload["manual_job_defaults"]["default_horizon"], "1w")
        ticker_signals = ContextSnapshotRepository(session).list_ticker_signal_snapshots(limit=10)
        plans = RecommendationPlanRepository(session).list_plans(limit=10)
        samples = RecommendationDecisionSampleRepository(session).list_samples(limit=10)
        self.assertEqual(len(ticker_signals), 2)
        self.assertEqual(len(plans), 1)
        self.assertEqual(len(samples), 2)
        self.assertEqual({plan.ticker: plan.action for plan in plans}, {"AAPL": "long"})
        self.assertIsNone(next(sample for sample in samples if sample.ticker == "TSLA").recommendation_plan_id)

    def test_watchlist_orchestration_shortlist_thresholds_vary_by_horizon_and_size(self) -> None:
        session = create_session()
        orchestration = WatchlistOrchestrationService(
            context_snapshots=ContextSnapshotRepository(session),
            recommendation_plans=RecommendationPlanRepository(session),
            cheap_scan_service=CheapScanProposalService(),
            deep_analysis_service=TickerDeepAnalysisService(DeepAnalysisProposalService()),
            confidence_threshold=60.0,
        )

        self.assertEqual(orchestration._shortlist_limit(StrategyHorizon.ONE_DAY, 4), 3)
        self.assertEqual(orchestration._shortlist_limit(StrategyHorizon.ONE_WEEK, 12), 3)
        self.assertEqual(orchestration._shortlist_limit(StrategyHorizon.ONE_MONTH, 24), 4)
        self.assertEqual(orchestration._minimum_shortlist_confidence(StrategyHorizon.ONE_DAY, 4), 52.0)
        self.assertEqual(orchestration._minimum_shortlist_confidence(StrategyHorizon.ONE_WEEK, 12), 53.0)
        self.assertEqual(orchestration._minimum_shortlist_attention(StrategyHorizon.ONE_MONTH, 24), 52.0)

    def test_watchlist_orchestration_uses_matched_relationships_in_plan_explanation_text(self) -> None:
        session = create_session()
        orchestration = WatchlistOrchestrationService(
            context_snapshots=ContextSnapshotRepository(session),
            recommendation_plans=RecommendationPlanRepository(session),
            cheap_scan_service=CheapScanProposalService(),
            deep_analysis_service=TickerDeepAnalysisService(DeepAnalysisProposalService()),
            confidence_threshold=60.0,
        )
        transmission_summary = {
            "context_bias": "tailwind",
            "expected_transmission_window": "2d_5d",
            "primary_drivers": ["industry_context_support"],
            "matched_ticker_relationships": [
                {"type": "supplier_to", "type_label": "supplier to", "target": "TSM", "target_label": "TSM", "channel": "supply_chain", "channel_label": "supply chain"},
                {"type": "peer_of", "type_label": "peer of", "target": "SONY", "target_label": "Sony", "channel": "competitive_position", "channel_label": "competitive position"},
            ],
        }

        self.assertIn("supplier to TSM via supply chain", orchestration._action_reason_detail("breakout", "actionable_setup", transmission_summary=transmission_summary))
        candidate = type(
            "Candidate",
            (),
            {
                "indicator_summary": "cheap scan",
                "attention_score": 74.0,
                "confidence_percent": 78.0,
            },
        )()
        self.assertIn("supplier to TSM via supply chain", orchestration._rationale_summary(
            TickerSignalSnapshot(ticker="AAPL", horizon="1w", attention_score=74.0, confidence_percent=78.0),
            candidate,
            "breakout",
            transmission_summary=transmission_summary,
        ))
        self.assertIn("supplier to TSM via supply chain", orchestration._actionable_thesis("long", "breakout", transmission_summary=transmission_summary))
        self.assertIn("supplier to TSM via supply chain", orchestration._invalidation_summary("breakout", transmission_summary=transmission_summary))
        self.assertIn("ticker relationship read-through can break if peer, supplier, or customer confirmation fades", orchestration._plan_risks([], "breakout", "long", transmission_summary))

    def test_watchlist_orchestration_uses_catalyst_lane_to_preserve_event_candidate(self) -> None:
        session = create_session()
        watchlist = WatchlistRepository(session).create(
            "Catalyst Watch",
            ["AAPL", "SHOP", "IBM"],
            default_horizon=StrategyHorizon.ONE_WEEK,
            allow_shorts=False,
        )
        orchestration = WatchlistOrchestrationService(
            context_snapshots=ContextSnapshotRepository(session),
            recommendation_plans=RecommendationPlanRepository(session),
            cheap_scan_service=CatalystLaneCheapScanService(),
            deep_analysis_service=TickerDeepAnalysisService(DeepAnalysisProposalService()),
            confidence_threshold=60.0,
        )

        result = orchestration.execute(watchlist, watchlist.tickers, run_id=1)

        self.assertEqual(result["summary"]["shortlist_count"], 2)
        decisions = {item["ticker"]: item for item in result["artifact"]["shortlist_decisions"]}
        self.assertEqual(decisions["AAPL"]["selection_lane"], "technical")
        self.assertEqual(decisions["AAPL"]["selection_lane_label"], "technical")
        self.assertEqual(decisions["SHOP"]["selection_lane"], "catalyst")
        self.assertEqual(decisions["SHOP"]["selection_lane_label"], "catalyst")
        self.assertTrue(decisions["SHOP"]["shortlisted"])
        self.assertIn("below_confidence_threshold", decisions["SHOP"]["reasons"])
        self.assertGreater(decisions["SHOP"]["catalyst_proxy_score"], result["summary"]["shortlist_rules"]["minimum_catalyst_proxy_score"])

    def test_watchlist_orchestration_uses_calibration_to_raise_action_thresholds(self) -> None:
        session = create_session()
        watchlist = WatchlistRepository(session).create(
            "Core Tech",
            ["AAPL", "MSFT", "TSLA"],
            default_horizon=StrategyHorizon.ONE_WEEK,
            allow_shorts=False,
        )
        plans = RecommendationPlanRepository(session)
        outcomes = RecommendationOutcomeRepository(session)
        for index in range(12):
            plan = plans.create_plan(
                RecommendationPlan(
                    ticker=f"BRK{index}",
                    horizon="1w",
                    action="long",
                    confidence_percent=72.0,
                    thesis_summary="weak breakout",
                    signal_breakdown={
                        "setup_family": "breakout",
                        "transmission_summary": {
                            "context_bias": "tailwind",
                            "transmission_tags": [],
                        },
                    },
                )
            )
            outcomes.upsert_outcome(
                RecommendationPlanOutcome(
                    recommendation_plan_id=plan.id or 0,
                    ticker=f"BRK{index}",
                    action="long",
                    outcome="loss",
                    status="resolved",
                    horizon_return_5d=-2.0,
                    confidence_bucket="65_to_79",
                    setup_family="breakout",
                    notes="failed breakout",
                )
            )
        orchestration = WatchlistOrchestrationService(
            context_snapshots=ContextSnapshotRepository(session),
            recommendation_plans=plans,
            cheap_scan_service=CheapScanProposalService(),
            deep_analysis_service=TickerDeepAnalysisService(DeepAnalysisProposalService()),
            confidence_threshold=60.0,
            calibration_service=RecommendationPlanCalibrationService(outcomes),
        )

        result = orchestration.execute(watchlist, watchlist.tickers, run_id=1)

        stored_plans = plans.list_plans(limit=10)
        plan_map = {plan.ticker: plan for plan in stored_plans if plan.ticker in {"AAPL", "MSFT", "TSLA"}}
        self.assertEqual(result["summary"]["calibration_enabled"], True)
        self.assertEqual(plan_map["AAPL"].action, "long")
        self.assertEqual(plan_map["AAPL"].evidence_summary["action_reason"], "actionable_setup")
        self.assertEqual(plan_map["AAPL"].evidence_summary["action_reason_label"], "actionable setup")
        calibration_review = plan_map["AAPL"].signal_breakdown["calibration_review"]
        self.assertEqual(calibration_review["enabled"], True)
        self.assertEqual(calibration_review["review_status"], "usable_for_gating")
        self.assertEqual(calibration_review["review_status_label"], "usable for gating")
        self.assertGreaterEqual(calibration_review["effective_confidence_threshold"], 72.0)
        self.assertLess(calibration_review["calibrated_confidence_percent"], calibration_review["raw_confidence_percent"])
        self.assertLess(plan_map["AAPL"].confidence_percent, calibration_review["raw_confidence_percent"])
        self.assertEqual(calibration_review["horizon"]["key"], "1w")
        self.assertEqual(calibration_review["transmission_bias"]["key"], "tailwind")
        self.assertEqual(calibration_review["transmission_bias"]["label"], "tailwind")
        self.assertEqual(calibration_review["transmission_bias"]["slice_label"], "transmission bias")
        self.assertEqual(calibration_review["transmission_bias"]["sample_status"], "usable")
        self.assertEqual(calibration_review["context_regime"]["key"], "context_plus_catalyst")
        self.assertEqual(calibration_review["context_regime"]["label"], "context plus catalyst")
        self.assertEqual(calibration_review["horizon_setup_family"]["key"], "1w__breakout")
        self.assertIn("setup_family_underperforming", calibration_review["reasons"])
        self.assertIn("confidence_bucket_underperforming", calibration_review["reasons"])
        self.assertEqual(calibration_review["reason_details"][0]["label"], "setup family underperforming")
        self.assertIn("horizon_underperforming", calibration_review["reasons"])
        self.assertIn("transmission_bias_underperforming", calibration_review["reasons"])
        self.assertNotIn("context_regime_underperforming", calibration_review["reasons"])
        self.assertIn("horizon_setup_family_underperforming", calibration_review["reasons"])

    def test_watchlist_orchestration_applies_signal_gating_tuning_config_to_live_action_thresholds(self) -> None:
        session = create_session()
        watchlist = WatchlistRepository(session).create(
            "SignalGatingTuning Demo",
            ["FOO"],
            default_horizon=StrategyHorizon.ONE_WEEK,
            allow_shorts=True,
        )

        class TunedCheapScanService:
            def score(self, ticker: str, horizon: StrategyHorizon, as_of=None):
                from trade_proposer_app.services.watchlist_cheap_scan import CheapScanSignal

                return CheapScanSignal(
                    ticker=ticker,
                    horizon=horizon,
                    directional_bias="long",
                    directional_score=0.44,
                    confidence_percent=58.0,
                    attention_score=68.0,
                    trend_score=66.0,
                    momentum_score=64.0,
                    breakout_score=62.0,
                    volatility_score=55.0,
                    liquidity_score=70.0,
                    diagnostics={"model": "cheap_scan_test"},
                    indicator_summary="cheap scan FOO",
                )

        class TunedDeepAnalysisService:
            def generate(self, ticker: str, as_of=None) -> RunOutput:
                analysis = {"summary": {"text": f"deep analysis for {ticker}"}, "ticker_deep_analysis": {"transmission_analysis": {"context_bias": "tailwind", "contradiction_count": 0}}}
                return RunOutput(
                    recommendation=Recommendation(
                        ticker=ticker,
                        direction=RecommendationDirection.LONG,
                        confidence=58.0,
                        entry_price=100.0,
                        stop_loss=95.0,
                        take_profit=110.0,
                        indicator_summary="deep analysis",
                    ),
                    diagnostics=RunDiagnostics(analysis_json=json.dumps(analysis)),
                )

        baseline = WatchlistOrchestrationService(
            context_snapshots=ContextSnapshotRepository(session),
            recommendation_plans=RecommendationPlanRepository(session),
            cheap_scan_service=TunedCheapScanService(),
            deep_analysis_service=TunedDeepAnalysisService(),
            confidence_threshold=60.0,
        )
        baseline_result = baseline.execute(watchlist, watchlist.tickers, run_id=1)
        baseline_plan = RecommendationPlanRepository(session).list_plans(limit=10)[0]

        tuned_session = create_session()
        tuned_watchlist = WatchlistRepository(tuned_session).create(
            "SignalGatingTuning Demo",
            ["FOO"],
            default_horizon=StrategyHorizon.ONE_WEEK,
            allow_shorts=True,
        )
        tuned = WatchlistOrchestrationService(
            context_snapshots=ContextSnapshotRepository(tuned_session),
            recommendation_plans=RecommendationPlanRepository(tuned_session),
            cheap_scan_service=TunedCheapScanService(),
            deep_analysis_service=TunedDeepAnalysisService(),
            confidence_threshold=60.0,
            signal_gating_tuning_config={
                "threshold_offset": -4.0,
                "confidence_adjustment": 4.0,
                "near_miss_gap_cutoff": 2.0,
                "shortlist_aggressiveness": 2.0,
                "degraded_penalty": 0.0,
            },
        )
        tuned_result = tuned.execute(tuned_watchlist, tuned_watchlist.tickers, run_id=1)
        tuned_plan = RecommendationPlanRepository(tuned_session).list_plans(limit=10)[0]

        self.assertEqual(baseline_result["summary"]["shortlist_count"], 1)
        self.assertEqual(baseline_plan.action, "no_action")
        self.assertEqual(baseline_plan.evidence_summary["action_reason"], "below_action_confidence_threshold")
        baseline_calibration = baseline_plan.signal_breakdown["calibration_review"]
        self.assertEqual(baseline_calibration["effective_confidence_threshold"], 60.0)
        self.assertEqual(baseline_calibration["calibrated_confidence_percent"], 58.0)

        self.assertEqual(tuned_result["summary"]["shortlist_count"], 1)
        self.assertEqual(tuned_plan.action, "long")
        self.assertEqual(tuned_plan.evidence_summary["action_reason"], "actionable_setup")
        tuned_calibration = tuned_plan.signal_breakdown["calibration_review"]
        self.assertEqual(tuned_calibration["effective_confidence_threshold"], 56.0)
        self.assertEqual(tuned_calibration["calibrated_confidence_percent"], 62.0)

    def test_recommendation_evaluation_resolves_phantom_trade_for_no_action_plan_with_trade_levels(self) -> None:
        session = create_session()
        plan = RecommendationPlanRepository(session).create_plan(
            RecommendationPlan(
                ticker="AAPL",
                horizon="1w",
                action="no_action",
                confidence_percent=61.0,
                entry_price_low=100.0,
                entry_price_high=100.0,
                stop_loss=95.0,
                take_profit=110.0,
                thesis_summary="Rejected despite a valid long setup.",
                computed_at=datetime(2026, 1, 5, 14, 30, tzinfo=timezone.utc),
                signal_breakdown={
                    "setup_family": "breakout",
                    "intended_action": "long",
                },
            )
        )
        service = RecommendationPlanEvaluationService(session)
        intraday_frame = pd.DataFrame(
            [
                {"bar_time": datetime(2026, 1, 5, 14, 35, tzinfo=timezone.utc), "available_at": datetime(2026, 1, 5, 14, 40, tzinfo=timezone.utc), "Open": 100.0, "High": 101.0, "Low": 99.5, "Close": 100.5},
                {"bar_time": datetime(2026, 1, 6, 14, 35, tzinfo=timezone.utc), "available_at": datetime(2026, 1, 6, 14, 40, tzinfo=timezone.utc), "Open": 100.5, "High": 111.0, "Low": 100.0, "Close": 110.5},
            ]
        ).set_index("bar_time")
        with patch.object(service, "_prepare_price_histories", return_value=({("AAPL", False): None, ("AAPL", True): intraday_frame}, [])):
            result = service.run_evaluation([plan.id or 0], as_of=datetime(2026, 1, 7, tzinfo=timezone.utc))

        outcome = RecommendationOutcomeRepository(session).get_outcomes_by_plan_ids([plan.id or 0])[plan.id or 0]
        self.assertEqual(outcome.outcome, "phantom_win")
        self.assertEqual(outcome.status, "resolved")
        self.assertIn("AAPL: phantom_win", result.output)

    def test_job_execution_processes_evaluation_run_and_persists_summary(self) -> None:
        session = create_session()
        jobs = JobRepository(session)
        runs = RunRepository(session)
        job = jobs.create(
            "Daily Evaluation",
            [],
            "0 18 * * *",
            job_type=JobType.RECOMMENDATION_EVALUATION,
        )
        service = JobExecutionService(
            jobs=jobs,
            runs=runs,
            evaluations=StubEvaluationExecutionService(),
        )
        queued_run = service.enqueue_job(job.id or 0)

        processed_run, recommendations = service.process_next_queued_run()

        self.assertIsNotNone(processed_run)
        self.assertEqual(processed_run.job_type, JobType.RECOMMENDATION_EVALUATION)
        self.assertEqual(processed_run.status, "completed")
        self.assertEqual(recommendations, [])
        stored_run = runs.get_run(queued_run.id or 0)
        self.assertIn('"synced_recommendation_plan_outcomes": 4', stored_run.summary_json or "")
        self.assertIn('"output": "evaluation complete"', stored_run.summary_json or "")
        self.assertIn('"evaluation_seconds"', stored_run.timing_json or "")

    def test_job_execution_processes_optimization_run_and_persists_summary_and_artifact(self) -> None:
        session = create_session()
        jobs = JobRepository(session)
        runs = RunRepository(session)
        job = jobs.create(
            "Weekly Plan Generation Tuning",
            [],
            "0 2 * * 0",
            job_type=JobType.PLAN_GENERATION_TUNING,
        )
        service = JobExecutionService(
            jobs=jobs,
            runs=runs,
            plan_generation_tuning=StubOptimizationService(),
        )
        queued_run = service.enqueue_job(job.id or 0)

        processed_run, recommendations = service.process_next_queued_run()

        self.assertIsNotNone(processed_run)
        self.assertEqual(processed_run.job_type, JobType.PLAN_GENERATION_TUNING)
        self.assertEqual(processed_run.status, "completed")
        self.assertEqual(recommendations, [])
        stored_run = runs.get_run(queued_run.id or 0)
        self.assertIn('"winner_candidate_id": 1', (stored_run.summary_json or "").lower())
        self.assertIn('"plan_generation_tuning_run_id": 1', stored_run.artifact_json or "")
        self.assertIn('"plan_generation_tuning_seconds"', stored_run.timing_json or "")

    def test_job_execution_processes_macro_context_refresh_and_persists_snapshot_metadata(self) -> None:
        session = create_session()
        jobs = JobRepository(session)
        runs = RunRepository(session)
        job = jobs.create(
            "Macro Refresh",
            [],
            "0 */6 * * *",
            job_type=JobType.MACRO_CONTEXT_REFRESH,
        )
        macro_service = StubMacroContextRefreshService()
        service = JobExecutionService(
            jobs=jobs,
            runs=runs,
            macro_context_refresh=macro_service,
            macro_context=MacroContextService(ContextSnapshotRepository(session)),
        )
        queued_run = service.enqueue_job(job.id or 0)

        processed_run, recommendations = service.process_next_queued_run()

        self.assertIsNotNone(processed_run)
        self.assertEqual(processed_run.job_type, JobType.MACRO_CONTEXT_REFRESH)
        self.assertEqual(processed_run.status, "completed")
        self.assertEqual(recommendations, [])
        self.assertEqual(len(macro_service.calls), 1)
        self.assertEqual(macro_service.calls[0][0], job.id)
        self.assertEqual(macro_service.calls[0][1], queued_run.id)
        stored_run = runs.get_run(queued_run.id or 0)
        self.assertIn('"scope": "macro"', stored_run.summary_json or "")
        self.assertIn('"macro_context_snapshot_id":', stored_run.summary_json or "")
        self.assertIn('"macro_context_snapshot_id":', stored_run.artifact_json or "")
        self.assertIn('"macro_context_seconds"', stored_run.timing_json or "")
        macro_context_snapshots = ContextSnapshotRepository(session).list_macro_context_snapshots(run_id=queued_run.id or 0)
        self.assertEqual(len(macro_context_snapshots), 1)
        self.assertEqual(macro_context_snapshots[0].source_breakdown["context_refresh_subject_key"], "global_macro")

    def test_job_execution_processes_industry_context_refresh_and_persists_snapshot_metadata(self) -> None:
        session = create_session()
        jobs = JobRepository(session)
        runs = RunRepository(session)
        job = jobs.create(
            "Industry Refresh",
            [],
            "0 */8 * * *",
            job_type=JobType.INDUSTRY_CONTEXT_REFRESH,
        )
        industry_service = StubIndustryContextRefreshService()
        service = JobExecutionService(
            jobs=jobs,
            runs=runs,
            industry_context_refresh=industry_service,
            industry_context=IndustryContextService(ContextSnapshotRepository(session)),
        )
        queued_run = service.enqueue_job(job.id or 0)

        processed_run, recommendations = service.process_next_queued_run()

        self.assertIsNotNone(processed_run)
        self.assertEqual(processed_run.job_type, JobType.INDUSTRY_CONTEXT_REFRESH)
        self.assertEqual(processed_run.status, "completed")
        self.assertEqual(recommendations, [])
        self.assertEqual(len(industry_service.calls), 1)
        self.assertEqual(industry_service.calls[0][0], job.id)
        self.assertEqual(industry_service.calls[0][1], queued_run.id)
        stored_run = runs.get_run(queued_run.id or 0)
        self.assertIn('"scope": "industry"', stored_run.summary_json or "")
        self.assertIn('"industry_context_snapshot_count": 1', stored_run.summary_json or "")
        self.assertIn('"snapshot_count": 1', stored_run.artifact_json or "")
        self.assertIn('"industry_context_snapshot_ids": [', stored_run.artifact_json or "")
        self.assertIn('"industry_context_seconds"', stored_run.timing_json or "")
        industry_context_snapshots = ContextSnapshotRepository(session).list_industry_context_snapshots(run_id=queued_run.id or 0)
        self.assertEqual(len(industry_context_snapshots), 1)
        self.assertEqual(industry_context_snapshots[0].source_breakdown["context_refresh_subject_key"], "consumer_electronics")

    def test_job_execution_blocks_second_optimization_enqueue_when_one_is_active(self) -> None:
        session = create_session()
        jobs = JobRepository(session)
        runs = RunRepository(session)
        job = jobs.create(
            "Weekly Plan Generation Tuning",
            [],
            None,
            job_type=JobType.PLAN_GENERATION_TUNING,
        )
        service = JobExecutionService(jobs=jobs, runs=runs)
        first = service.enqueue_job(job.id or 0)
        second = service.enqueue_job(job.id or 0)
        self.assertEqual(first.id, second.id)

    def test_job_execution_marks_run_failed_without_storing_dummy_recommendations(self) -> None:
        session = create_session()
        jobs = JobRepository(session)
        runs = RunRepository(session)
        job = jobs.create("Failure Case", ["AAPL"], None)
        service = JobExecutionService(
            jobs=jobs,
            runs=runs,
            watchlist_orchestration=FailingWatchlistOrchestrationService(),
        )
        queued_run = service.enqueue_job(job.id or 0)

        with self.assertRaises(RuntimeError):
            service.process_next_queued_run()

        latest_run = runs.list_latest_runs(limit=1)[0]
        self.assertEqual(latest_run.status, "failed")
        self.assertEqual(latest_run.id, queued_run.id)
        self.assertEqual(latest_run.error_message, "boom: AAPL")
        self.assertIsNotNone(latest_run.started_at)
        self.assertIsNotNone(latest_run.completed_at)
        self.assertIsNotNone(latest_run.duration_seconds)
        self.assertIsNotNone(latest_run.timing_json)
        self.assertIsNotNone(latest_run.artifact_json)
        assert latest_run.timing_json is not None
        self.assertIn('"recommendation_generation_seconds"', latest_run.timing_json)
        self.assertIn('"failed_after_phase": "recommendation_generation"', latest_run.artifact_json or "")
        self.assertIn('"had_summary_before_failure": false', latest_run.artifact_json or "")

    def test_job_execution_stops_immediately_on_multi_ticker_failure_without_partial_persistence(self) -> None:
        session = create_session()
        jobs = JobRepository(session)
        runs = RunRepository(session)
        job = jobs.create("Failure Mid Run", ["AAPL", "MISSING", "MSFT"], None)
        service = JobExecutionService(
            jobs=jobs,
            runs=runs,
            watchlist_orchestration=FailOnSecondTickerWatchlistOrchestrationService(),
        )
        queued_run = service.enqueue_job(job.id or 0)

        with self.assertRaises(RuntimeError):
            service.process_next_queued_run()

        latest_run = runs.get_run(queued_run.id or 0)
        self.assertEqual(latest_run.status, "failed")
        self.assertEqual(latest_run.error_message, "ticker not found: MISSING")
        self.assertIsNotNone(latest_run.timing_json)
        assert latest_run.timing_json is not None
        self.assertIn('"ticker": "AAPL"', latest_run.timing_json)
        self.assertIn('"status": "completed"', latest_run.timing_json)
        self.assertIn('"ticker": "MISSING"', latest_run.timing_json)
        self.assertIn('"status": "failed"', latest_run.timing_json)
        self.assertNotIn('"ticker": "MSFT"', latest_run.timing_json)
        self.assertIn('"failed_after_phase": "recommendation_generation"', latest_run.artifact_json or "")

    def test_decision_samples_can_be_upserted_without_plan_rows_when_signal_snapshot_exists(self) -> None:
        session = create_session()
        signal = ContextSnapshotRepository(session).create_ticker_signal_snapshot(
            TickerSignalSnapshot(
                ticker="AAPL",
                horizon=StrategyHorizon.ONE_WEEK,
                direction="long",
                swing_probability_percent=62.0,
                confidence_percent=66.0,
                attention_score=74.0,
                macro_exposure_score=55.0,
                industry_alignment_score=57.0,
                ticker_sentiment_score=59.0,
                technical_setup_score=61.0,
                catalyst_score=48.0,
                expected_move_score=43.0,
                execution_quality_score=58.0,
            )
        )
        repository = RecommendationDecisionSampleRepository(session)

        stored = repository.upsert_sample(
            RecommendationDecisionSample(
                recommendation_plan_id=None,
                ticker="AAPL",
                horizon="1w",
                action="no_action",
                decision_type="no_action",
                decision_reason="not_shortlisted",
                shortlisted=False,
                confidence_percent=66.0,
                setup_family="continuation",
                review_priority="low",
                ticker_signal_snapshot_id=signal.id,
            )
        )
        updated = repository.upsert_sample(
            RecommendationDecisionSample(
                recommendation_plan_id=None,
                ticker="AAPL",
                horizon="1w",
                action="no_action",
                decision_type="near_miss",
                decision_reason="not_shortlisted",
                shortlisted=False,
                confidence_percent=66.0,
                setup_family="continuation",
                review_priority="high",
                ticker_signal_snapshot_id=signal.id,
            )
        )

        self.assertEqual(stored.id, updated.id)
        self.assertIsNone(updated.recommendation_plan_id)
        self.assertEqual(updated.ticker_signal_snapshot_id, signal.id)
        self.assertEqual(updated.decision_type, "near_miss")
        self.assertEqual(updated.review_priority, "high")
        self.assertEqual(repository.count_samples(), 1)

    def test_decision_samples_can_filter_by_benchmark_result(self) -> None:
        session = create_session()
        repository = RecommendationDecisionSampleRepository(session)

        repository.upsert_sample(
            RecommendationDecisionSample(
                recommendation_plan_id=None,
                ticker="AAPL",
                horizon="1w",
                action="no_action",
                decision_type="no_action",
                decision_reason="not_shortlisted",
                shortlisted=False,
                confidence_percent=61.0,
                setup_family="continuation",
                review_priority="low",
                benchmark_status="pending",
                ticker_signal_snapshot_id=1001,
            )
        )
        repository.upsert_sample(
            RecommendationDecisionSample(
                recommendation_plan_id=None,
                ticker="MSFT",
                horizon="1w",
                action="no_action",
                decision_type="no_action",
                decision_reason="not_shortlisted",
                shortlisted=False,
                confidence_percent=64.0,
                setup_family="continuation",
                review_priority="low",
                benchmark_status="evaluated",
                benchmark_target_1d_hit=True,
                benchmark_target_5d_hit=False,
                benchmark_max_favorable_pct=3.2,
                ticker_signal_snapshot_id=1002,
            )
        )
        repository.upsert_sample(
            RecommendationDecisionSample(
                recommendation_plan_id=None,
                ticker="NVDA",
                horizon="1w",
                action="no_action",
                decision_type="no_action",
                decision_reason="not_shortlisted",
                shortlisted=False,
                confidence_percent=66.0,
                setup_family="continuation",
                review_priority="low",
                benchmark_status="evaluated",
                benchmark_target_1d_hit=False,
                benchmark_target_5d_hit=False,
                benchmark_max_favorable_pct=0.8,
                ticker_signal_snapshot_id=1003,
            )
        )

        pending = repository.list_samples(limit=10, benchmark_result="pending")
        hits = repository.list_samples(limit=10, benchmark_result="hit")
        misses = repository.list_samples(limit=10, benchmark_result="miss")

        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].ticker, "AAPL")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].ticker, "MSFT")
        self.assertEqual(len(misses), 1)
        self.assertEqual(misses[0].ticker, "NVDA")
        self.assertEqual(repository.count_samples(benchmark_result="pending"), 1)
        self.assertEqual(repository.count_samples(benchmark_result="hit"), 1)
        self.assertEqual(repository.count_samples(benchmark_result="miss"), 1)

    def test_job_repository_delete_removes_job_runs_and_recommendations_without_nulling_run_job_id(self) -> None:
        session = create_session()
        jobs = JobRepository(session)
        runs = RunRepository(session)
        job = jobs.create("Delete Me", ["AAPL"], None)
        run = runs.enqueue(job.id or 0)
        claimed = runs.claim_next_queued_run()
        assert claimed is not None
        runs.update_status(run.id or 0, "completed")
        plan = RecommendationPlanRepository(session).create_plan(
            RecommendationPlan(
                ticker="AAPL",
                horizon="1w",
                action="long",
                confidence_percent=80.0,
                entry_price_low=100.0,
                entry_price_high=101.0,
                stop_loss=95.0,
                take_profit=110.0,
                holding_period_days=5,
                risk_reward_ratio=2.0,
                thesis_summary="Seeded historical plan",
                rationale_summary="Repository delete cleanup coverage",
                run_id=run.id,
                job_id=job.id,
            )
        )
        RecommendationDecisionSampleRepository(session).upsert_sample(
            RecommendationDecisionSample(
                recommendation_plan_id=None,
                ticker="AAPL",
                horizon="1w",
                action="no_action",
                decision_type="no_action",
                decision_reason="not_shortlisted",
                confidence_percent=80.0,
                calibrated_confidence_percent=80.0,
                setup_family="continuation",
                reviewed_at=datetime(2026, 3, 24, 12, 0, tzinfo=timezone.utc),
                run_id=run.id,
                job_id=job.id,
                ticker_signal_snapshot_id=101,
            )
        )
        jobs.delete(job.id or 0)

        self.assertIsNone(session.get(JobRecord, job.id or 0))
        self.assertIsNone(session.get(RunRecord, run.id or 0))
        self.assertEqual(RecommendationDecisionSampleRepository(session).list_samples(limit=10), [])

    def test_run_repository_delete_removes_context_snapshots(self) -> None:
        session = create_session()
        jobs = JobRepository(session)
        runs = RunRepository(session)
        job = jobs.create("Delete Run", ["AAPL"], None)
        run = runs.enqueue(job.id or 0)
        claimed = runs.claim_next_queued_run()
        assert claimed is not None
        runs.update_status(run.id or 0, "completed")
        plan = RecommendationPlanRepository(session).create_plan(
            RecommendationPlan(
                ticker="AAPL",
                horizon="1w",
                action="long",
                confidence_percent=80.0,
                entry_price_low=100.0,
                entry_price_high=101.0,
                stop_loss=95.0,
                take_profit=110.0,
                holding_period_days=5,
                risk_reward_ratio=2.0,
                thesis_summary="Seeded historical plan",
                rationale_summary="Repository delete cleanup coverage",
                run_id=run.id,
                job_id=job.id,
            )
        )
        RecommendationDecisionSampleRepository(session).upsert_sample(
            RecommendationDecisionSample(
                recommendation_plan_id=None,
                ticker="AAPL",
                horizon="1w",
                action="no_action",
                decision_type="no_action",
                decision_reason="not_shortlisted",
                confidence_percent=80.0,
                calibrated_confidence_percent=80.0,
                setup_family="continuation",
                reviewed_at=datetime(2026, 3, 24, 12, 0, tzinfo=timezone.utc),
                run_id=run.id,
                job_id=job.id,
                ticker_signal_snapshot_id=202,
            )
        )
        ContextSnapshotRepository(session).create_macro_context_snapshot(
            MacroContextSnapshot(summary_text="cleanup", run_id=run.id, job_id=job.id)
        )

        runs.delete_run(run.id or 0)

        self.assertIsNone(session.get(RunRecord, run.id or 0))
        self.assertEqual(RecommendationDecisionSampleRepository(session).list_samples(limit=10), [])
        self.assertEqual(ContextSnapshotRepository(session).list_macro_context_snapshots(run_id=run.id or 0), [])

    def test_run_repository_recovers_stale_running_runs(self) -> None:
        session = create_session()
        jobs = JobRepository(session)
        runs = RunRepository(session)
        job = jobs.create("Stale Running", ["AAPL"], None)
        run = runs.enqueue(job.id or 0)
        # Manually set to RUNNING without lease to test legacy recovery
        session.execute(
            update(RunRecord)
            .where(RunRecord.id == run.id)
            .values(status="running", started_at=datetime(2026, 3, 24, 11, 0, tzinfo=timezone.utc))
        )
        session.commit()
        
        stale_now = datetime(2026, 3, 24, 12, 0, tzinfo=timezone.utc)
        recovered = runs.recover_stale_running_runs(stale_after_seconds=900, now=stale_now)
    
        self.assertEqual(len(recovered), 1)
        refreshed = runs.get_run(run.id or 0)
        self.assertEqual(refreshed.status, "failed")
        self.assertIn("Recovered stale running run", refreshed.error_message or "")
        self.assertIsNotNone(refreshed.completed_at)
        self.assertEqual(refreshed.duration_seconds, 3600.0)
        self.assertIn('"strategy": "started_at_timeout"', refreshed.timing_json or "")

    def test_enqueue_job_recovers_stale_running_run_before_active_run_check(self) -> None:
        session = create_session()
        jobs = JobRepository(session)
        runs = RunRepository(session)
        job = jobs.create("Recover Before Enqueue", ["AAPL"], None)
        original = runs.enqueue(job.id or 0)
        # Manually set to RUNNING without lease
        session.execute(
            update(RunRecord)
            .where(RunRecord.id == original.id)
            .values(status="running", started_at=datetime(2000, 1, 1, 0, 0, tzinfo=timezone.utc))
        )
        session.commit()
        
        service = JobExecutionService(
            jobs=jobs,
            runs=runs,
            watchlist_orchestration=StubWatchlistOrchestrationService(),
        )
        previous_timeout = settings.run_stale_after_seconds
        settings.run_stale_after_seconds = 60
        try:
            queued = service.enqueue_job(job.id or 0, scheduled_for=datetime(2026, 3, 24, 12, 0, tzinfo=timezone.utc))
        finally:
            settings.run_stale_after_seconds = previous_timeout

        self.assertNotEqual(queued.id, original.id)
        self.assertEqual(queued.status, "queued")
        stale_run = runs.get_run(original.id or 0)
        self.assertEqual(stale_run.status, "failed")

    def test_settings_repository_defaults_summary_backend_to_pi_agent(self) -> None:
        session = create_session()
        repository = SettingsRepository(session)
        summary_settings = repository.get_summary_settings()
        self.assertEqual(summary_settings["summary_backend"], "pi_agent")
        self.assertEqual(summary_settings["summary_pi_command"], "pi")
        self.assertEqual(summary_settings["summary_timeout_seconds"], "60")
        self.assertEqual(repository.get_plan_generation_tuning_settings()["min_actionable_resolved"], 20)
        self.assertEqual(repository.get_plan_generation_tuning_settings()["min_validation_resolved"], 8)
        self.assertIn("price fluctuation", summary_settings["summary_prompt"])
        self.assertIn("industry context", summary_settings["summary_prompt"])
        self.assertIn("global macroeconomic stage", summary_settings["summary_prompt"])

    def test_settings_repository_encrypts_provider_credentials_at_rest(self) -> None:
        session = create_session()
        repository = SettingsRepository(session)
        repository.set_setting("confidence_threshold", "60")
        repository.upsert_provider_credential("openai", "key-123", "secret-456")

        settings_map = repository.get_setting_map()
        providers = repository.list_provider_credentials()
        stored_row = session.get(ProviderCredentialRecord, "openai")

        self.assertEqual(settings_map["confidence_threshold"], "60")
        openai = next(provider for provider in providers if provider.provider == "openai")
        redacted = repository.list_provider_credentials_redacted()
        redacted_openai = next(provider for provider in redacted if provider.provider == "openai")
        self.assertEqual(openai.api_key, "key-123")
        self.assertEqual(openai.api_secret, "secret-456")
        self.assertEqual(redacted_openai.api_key, "key-123")
        self.assertEqual(redacted_openai.api_secret, "")
        self.assertIsNotNone(stored_row)
        assert stored_row is not None
        self.assertNotEqual(stored_row.api_key, "key-123")
        self.assertNotEqual(stored_row.api_secret, "secret-456")

    def test_settings_repository_preserves_existing_secret_when_secret_input_is_blank(self) -> None:
        session = create_session()
        repository = SettingsRepository(session)
        repository.upsert_provider_credential("openai", "key-123", "secret-456")
        repository.upsert_provider_credential("openai", "key-789", "")

        providers = repository.list_provider_credentials()
        openai = next(provider for provider in providers if provider.provider == "openai")
        redacted_openai = next(provider for provider in repository.list_provider_credentials_redacted() if provider.provider == "openai")

        self.assertEqual(openai.api_key, "key-789")
        self.assertEqual(openai.api_secret, "secret-456")
        self.assertEqual(redacted_openai.api_secret, "")

    def test_settings_repository_allows_key_only_credentials_for_newsapi(self) -> None:
        session = create_session()
        repository = SettingsRepository(session)
        credential = repository.upsert_provider_credential("newsapi", "news-key-123", "")

        self.assertEqual(credential.provider, "newsapi")
        self.assertEqual(credential.api_key, "news-key-123")
        self.assertEqual(credential.api_secret, "")

    def test_settings_repository_requires_secret_for_alpaca_creation(self) -> None:
        session = create_session()
        repository = SettingsRepository(session)

        with self.assertRaisesRegex(ValueError, "api secret is required"):
            repository.upsert_provider_credential("alpaca", "alpaca-key", "")


if __name__ == "__main__":
    unittest.main()
