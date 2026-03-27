import json
import unittest
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from trade_proposer_app.domain.enums import JobType, RecommendationDirection, StrategyHorizon
from trade_proposer_app.domain.models import (
    EvaluationRunResult,
    IndustryContextSnapshot,
    MacroContextSnapshot,
    Recommendation,
    RecommendationPlan,
    RecommendationPlanOutcome,
    RunDiagnostics,
    RunOutput,
    SentimentSnapshot,
    TickerSignalSnapshot,
)
from trade_proposer_app.persistence.models import Base, JobRecord, ProviderCredentialRecord, RunRecord
from trade_proposer_app.repositories.jobs import JobRepository
from trade_proposer_app.repositories.runs import RunRepository
from trade_proposer_app.repositories.context_snapshots import ContextSnapshotRepository
from trade_proposer_app.repositories.recommendation_outcomes import RecommendationOutcomeRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.repositories.sentiment_snapshots import SentimentSnapshotRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.repositories.watchlists import WatchlistRepository
from trade_proposer_app.services.evaluation_execution import EvaluationExecutionService
from trade_proposer_app.services.industry_context import IndustryContextService
from trade_proposer_app.services.job_execution import JobExecutionService
from trade_proposer_app.services.macro_context import MacroContextService
from trade_proposer_app.services.proposals import ProposalService
from trade_proposer_app.services.recommendation_plan_calibration import RecommendationPlanCalibrationService
from trade_proposer_app.services.ticker_deep_analysis import TickerDeepAnalysisService
from trade_proposer_app.services.watchlist_orchestration import WatchlistOrchestrationService


def create_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


class FailingProposalService:
    def generate(self, ticker: str) -> RunOutput:
        raise RuntimeError(f"boom: {ticker}")


class FailOnSecondTickerProposalService:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, ticker: str) -> RunOutput:
        self.calls += 1
        if self.calls == 2:
            raise RuntimeError(f"ticker not found: {ticker}")
        return RunOutput(
            recommendation=Recommendation(
                ticker=ticker,
                direction=RecommendationDirection.LONG,
                confidence=75.0,
                entry_price=100.0,
                stop_loss=95.0,
                take_profit=110.0,
                indicator_summary="Above SMA200 · RSI 55.0",
            ),
            diagnostics=RunDiagnostics(),
        )


class StubEvaluationExecutionService(EvaluationExecutionService):
    def __init__(self) -> None:
        pass

    def execute(self, run=None) -> EvaluationRunResult:
        return EvaluationRunResult(
            evaluated_recommendation_plans=12,
            synced_recommendation_plan_outcomes=4,
            pending_recommendation_plan_outcomes=5,
            win_recommendation_plan_outcomes=4,
            loss_recommendation_plan_outcomes=3,
            output="evaluation complete",
        )


class CheapScanProposalService:
    def score(self, ticker: str, horizon: StrategyHorizon):
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
            diagnostics={"model": "cheap_scan_test"},
            indicator_summary=f"cheap scan {ticker}",
        )


class CatalystLaneCheapScanService:
    def score(self, ticker: str, horizon: StrategyHorizon):
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
            diagnostics={"model": "cheap_scan_test"},
            indicator_summary=f"cheap scan {ticker}",
        )


class DeepAnalysisProposalService:
    def generate(self, ticker: str) -> RunOutput:
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

    def execute(self) -> tuple[dict[str, object], dict[str, object]]:
        return (
            {
                "status": "completed",
                "resolved_trade_count": 88,
                "minimum_resolved_trades": 50,
                "weights_changed": True,
                "stdout": "optimization complete",
                "stderr": "",
            },
            {
                "weights_path": "/tmp/weights.json",
                "before": {"exists": True, "sha256": "abc"},
                "after": {"exists": True, "sha256": "def"},
            },
        )


class StubMacroSentimentService:
    def __init__(self) -> None:
        self.calls: list[tuple[int | None, int | None]] = []

    def refresh(self, *, job_id: int | None = None, run_id: int | None = None) -> dict[str, object]:
        self.calls.append((job_id, run_id))
        snapshot = SentimentSnapshot(
            id=7,
            scope="macro",
            subject_key="global_macro",
            subject_label="Global Macro",
            score=0.2,
            label="POSITIVE",
        )
        return {
            "snapshot": snapshot,
            "summary": {
                "scope": "macro",
                "subject_key": "global_macro",
                "subject_label": "Global Macro",
                "score": 0.2,
                "label": "POSITIVE",
                "expires_at": "2026-03-22T06:00:00+00:00",
            },
        }


class StubIndustrySentimentService:
    def __init__(self) -> None:
        self.calls: list[tuple[int | None, int | None]] = []

    def refresh_all(self, *, job_id: int | None = None, run_id: int | None = None) -> dict[str, object]:
        self.calls.append((job_id, run_id))
        snapshots = [
            SentimentSnapshot(
                id=12,
                scope="industry",
                subject_key="consumer_electronics",
                subject_label="Consumer Electronics",
                score=0.15,
                label="POSITIVE",
            )
        ]
        return {
            "snapshots": snapshots,
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
            "Weekly Optimization",
            [],
            "0 2 * * 0",
            job_type=JobType.WEIGHT_OPTIMIZATION,
        )

        self.assertEqual(evaluation_job.job_type, JobType.RECOMMENDATION_EVALUATION)
        self.assertEqual(optimization_job.job_type, JobType.WEIGHT_OPTIMIZATION)

        with self.assertRaises(ValueError):
            jobs.create(
                "Invalid Evaluation Tickers",
                ["AAPL"],
                None,
                job_type=JobType.RECOMMENDATION_EVALUATION,
            )

        with self.assertRaises(ValueError):
            jobs.create(
                "Invalid Optimization Watchlist",
                [],
                None,
                watchlist_id=watchlist.id,
                job_type=JobType.WEIGHT_OPTIMIZATION,
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

    def test_sentiment_snapshot_repository_returns_latest_valid_snapshot(self) -> None:
        session = create_session()
        repository = SentimentSnapshotRepository(session)
        now = datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc)

        repository.create_snapshot(
            scope="macro",
            subject_key="global_macro",
            subject_label="Global Macro",
            score=-0.1,
            label="NEGATIVE",
            computed_at=now,
            expires_at=now,
            coverage={"social_count": 2},
        )
        latest = repository.create_snapshot(
            scope="macro",
            subject_key="global_macro",
            subject_label="Global Macro",
            score=0.25,
            label="POSITIVE",
            computed_at=now.replace(hour=13),
            expires_at=now.replace(hour=19),
            coverage={"social_count": 5},
            drivers=["inflation cooled"],
        )

        resolved = repository.get_latest_valid_snapshot("macro", "global_macro", now=now.replace(hour=14))

        self.assertIsNotNone(resolved)
        assert resolved is not None
        self.assertEqual(resolved.id, latest.id)
        self.assertEqual(resolved.label, "POSITIVE")
        self.assertIn('"social_count": 5', resolved.coverage_json or "")

    def test_sentiment_snapshot_repository_ignores_expired_snapshot(self) -> None:
        session = create_session()
        repository = SentimentSnapshotRepository(session)
        snapshot = repository.create_snapshot(
            scope="macro",
            subject_key="global_macro",
            subject_label="Global Macro",
            score=0.05,
            label="NEUTRAL",
            computed_at=datetime(2026, 3, 22, 6, 0, tzinfo=timezone.utc),
            expires_at=datetime(2026, 3, 22, 8, 0, tzinfo=timezone.utc),
        )

        resolved = repository.get_latest_valid_snapshot(
            "macro",
            "global_macro",
            now=datetime(2026, 3, 22, 9, 0, tzinfo=timezone.utc),
        )

        self.assertIsNone(resolved)
        self.assertIsNotNone(snapshot.id)

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

    def test_job_execution_enqueues_and_processes_run(self) -> None:
        session = create_session()
        jobs = JobRepository(session)
        runs = RunRepository(session)
        job = jobs.create("Morning", ["NVDA", "TSLA"], None)

        service = JobExecutionService(jobs=jobs, runs=runs, proposals=ProposalService())
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
        stored = runs.list_recommendations_for_run(latest_runs[0].id or 0)
        outputs = runs.list_outputs_for_run(latest_runs[0].id or 0)
        self.assertEqual(stored, [])
        self.assertEqual(outputs, [])
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
            cheap_scan_service=CheapScanProposalService(),
            deep_analysis_service=TickerDeepAnalysisService(DeepAnalysisProposalService()),
            confidence_threshold=60.0,
        )
        service = JobExecutionService(
            jobs=jobs,
            runs=runs,
            proposals=ProposalService(),
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
        decisions = {item["ticker"]: item for item in artifact_payload["shortlist_decisions"]}
        self.assertEqual(decisions["AAPL"]["shortlisted"], True)
        self.assertEqual(decisions["AAPL"]["shortlist_rank"], 1)
        self.assertEqual(decisions["AAPL"]["selection_lane"], "technical")
        self.assertEqual(decisions["MSFT"]["reasons"], ["shorts_disabled", "below_catalyst_lane_threshold"])
        self.assertEqual(decisions["TSLA"]["reasons"], ["below_confidence_threshold", "below_attention_threshold", "below_catalyst_lane_threshold"])
        ticker_signals = ContextSnapshotRepository(session).list_ticker_signal_snapshots(limit=10)
        plans = RecommendationPlanRepository(session).list_plans(limit=10)
        self.assertEqual(len(ticker_signals), 3)
        self.assertEqual(len(plans), 3)
        action_map = {plan.ticker: plan.action for plan in plans}
        self.assertEqual(action_map["AAPL"], "long")
        self.assertEqual(action_map["MSFT"], "no_action")
        self.assertEqual(action_map["TSLA"], "no_action")
        plan_map = {plan.ticker: plan for plan in plans}
        self.assertEqual(plan_map["AAPL"].signal_breakdown["setup_family"], "breakout")
        self.assertEqual(plan_map["AAPL"].signal_breakdown["confidence_bucket"], "65_to_79")
        self.assertIn("confidence_components", plan_map["AAPL"].signal_breakdown)
        self.assertEqual(plan_map["AAPL"].evidence_summary["entry_style"], "break_or_retest")
        self.assertIn("breakout", plan_map["AAPL"].evidence_summary["invalidation_summary"])
        self.assertEqual(plan_map["TSLA"].evidence_summary["action_reason"], "not_shortlisted")
        diagnostics_map = {item.ticker: item.diagnostics for item in ticker_signals}
        source_breakdown_map = {item.ticker: item.source_breakdown for item in ticker_signals}
        self.assertEqual(diagnostics_map["AAPL"]["mode"], "deep_analysis")
        self.assertEqual(diagnostics_map["AAPL"]["shortlist_reasons"], [])
        self.assertEqual(diagnostics_map["AAPL"]["selection_lane"], "technical")
        self.assertEqual(diagnostics_map["AAPL"]["transmission_bias"], "tailwind")
        self.assertIn("primary_drivers", diagnostics_map["AAPL"])
        self.assertEqual(diagnostics_map["AAPL"]["expected_transmission_window"], "2d_5d")
        self.assertEqual(diagnostics_map["TSLA"]["mode"], "cheap_scan_only")
        self.assertEqual(diagnostics_map["TSLA"]["shortlist_reasons"], ["below_confidence_threshold", "below_attention_threshold", "below_catalyst_lane_threshold"])
        self.assertEqual(source_breakdown_map["AAPL"]["deep_analysis_model"], "ticker_deep_analysis_v2")
        self.assertEqual(source_breakdown_map["AAPL"]["transmission_bias"], "tailwind")
        self.assertIn("primary_drivers", source_breakdown_map["AAPL"])
        self.assertIn("transmission_summary", plan_map["AAPL"].signal_breakdown)
        self.assertIn("primary_drivers", plan_map["AAPL"].signal_breakdown["transmission_summary"])

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
            deep_analysis_service=TickerDeepAnalysisService(DeepAnalysisProposalService()),
            confidence_threshold=60.0,
        )
        service = JobExecutionService(
            jobs=jobs,
            runs=runs,
            proposals=ProposalService(),
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
        self.assertEqual(len(ticker_signals), 2)
        self.assertEqual(len(plans), 2)
        self.assertEqual({plan.ticker: plan.action for plan in plans}, {"AAPL": "long", "TSLA": "no_action"})

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
        self.assertEqual(decisions["SHOP"]["selection_lane"], "catalyst")
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
        calibration_review = plan_map["AAPL"].signal_breakdown["calibration_review"]
        self.assertEqual(calibration_review["enabled"], True)
        self.assertEqual(calibration_review["review_status"], "usable_for_gating")
        self.assertGreaterEqual(calibration_review["effective_confidence_threshold"], 75.0)
        self.assertEqual(calibration_review["horizon"]["key"], "1w")
        self.assertEqual(calibration_review["transmission_bias"]["key"], "tailwind")
        self.assertEqual(calibration_review["transmission_bias"]["sample_status"], "usable")
        self.assertEqual(calibration_review["context_regime"]["key"], "tailwind_without_dominant_tag")
        self.assertEqual(calibration_review["horizon_setup_family"]["key"], "1w__breakout")
        self.assertIn("setup_family_underperforming", calibration_review["reasons"])
        self.assertIn("confidence_bucket_underperforming", calibration_review["reasons"])
        self.assertIn("horizon_underperforming", calibration_review["reasons"])
        self.assertIn("transmission_bias_underperforming", calibration_review["reasons"])
        self.assertIn("context_regime_underperforming", calibration_review["reasons"])
        self.assertIn("horizon_setup_family_underperforming", calibration_review["reasons"])

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
            proposals=ProposalService(),
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
        self.assertEqual(runs.list_recommendations_for_run(stored_run.id or 0), [])

    def test_job_execution_processes_optimization_run_and_persists_summary_and_artifact(self) -> None:
        session = create_session()
        jobs = JobRepository(session)
        runs = RunRepository(session)
        job = jobs.create(
            "Weekly Optimization",
            [],
            "0 2 * * 0",
            job_type=JobType.WEIGHT_OPTIMIZATION,
        )
        service = JobExecutionService(
            jobs=jobs,
            runs=runs,
            proposals=ProposalService(),
            optimizations=StubOptimizationService(),
        )
        queued_run = service.enqueue_job(job.id or 0)

        processed_run, recommendations = service.process_next_queued_run()

        self.assertIsNotNone(processed_run)
        self.assertEqual(processed_run.job_type, JobType.WEIGHT_OPTIMIZATION)
        self.assertEqual(processed_run.status, "completed")
        self.assertEqual(recommendations, [])
        stored_run = runs.get_run(queued_run.id or 0)
        self.assertIn('"weights_changed": true', (stored_run.summary_json or "").lower())
        self.assertIn('"weights_path": "/tmp/weights.json"', stored_run.artifact_json or "")
        self.assertIn('"optimization_seconds"', stored_run.timing_json or "")
        self.assertEqual(runs.list_recommendations_for_run(stored_run.id or 0), [])

    def test_job_execution_processes_macro_sentiment_refresh_and_persists_snapshot_metadata(self) -> None:
        session = create_session()
        jobs = JobRepository(session)
        runs = RunRepository(session)
        job = jobs.create(
            "Macro Refresh",
            [],
            "0 */6 * * *",
            job_type=JobType.MACRO_SENTIMENT_REFRESH,
        )
        macro_service = StubMacroSentimentService()
        service = JobExecutionService(
            jobs=jobs,
            runs=runs,
            proposals=ProposalService(),
            macro_sentiment=macro_service,
            macro_context=MacroContextService(ContextSnapshotRepository(session)),
        )
        queued_run = service.enqueue_job(job.id or 0)

        processed_run, recommendations = service.process_next_queued_run()

        self.assertIsNotNone(processed_run)
        self.assertEqual(processed_run.job_type, JobType.MACRO_SENTIMENT_REFRESH)
        self.assertEqual(processed_run.status, "completed")
        self.assertEqual(recommendations, [])
        self.assertEqual(len(macro_service.calls), 1)
        self.assertEqual(macro_service.calls[0][0], job.id)
        self.assertEqual(macro_service.calls[0][1], queued_run.id)
        stored_run = runs.get_run(queued_run.id or 0)
        self.assertIn('"scope": "macro"', stored_run.summary_json or "")
        self.assertIn('"macro_context_snapshot_id":', stored_run.summary_json or "")
        self.assertIn('"snapshot_id": 7', stored_run.artifact_json or "")
        self.assertIn('"macro_context_snapshot_id":', stored_run.artifact_json or "")
        self.assertIn('"macro_refresh_seconds"', stored_run.timing_json or "")
        self.assertEqual(runs.list_recommendations_for_run(stored_run.id or 0), [])
        macro_context_snapshots = ContextSnapshotRepository(session).list_macro_context_snapshots(run_id=queued_run.id or 0)
        self.assertEqual(len(macro_context_snapshots), 1)
        self.assertEqual(macro_context_snapshots[0].source_breakdown["sentiment_snapshot_id"], 7)

    def test_job_execution_processes_industry_sentiment_refresh_and_persists_snapshot_metadata(self) -> None:
        session = create_session()
        jobs = JobRepository(session)
        runs = RunRepository(session)
        job = jobs.create(
            "Industry Refresh",
            [],
            "0 */8 * * *",
            job_type=JobType.INDUSTRY_SENTIMENT_REFRESH,
        )
        industry_service = StubIndustrySentimentService()
        service = JobExecutionService(
            jobs=jobs,
            runs=runs,
            proposals=ProposalService(),
            industry_sentiment=industry_service,
            industry_context=IndustryContextService(ContextSnapshotRepository(session)),
        )
        queued_run = service.enqueue_job(job.id or 0)

        processed_run, recommendations = service.process_next_queued_run()

        self.assertIsNotNone(processed_run)
        self.assertEqual(processed_run.job_type, JobType.INDUSTRY_SENTIMENT_REFRESH)
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
        self.assertIn('"industry_refresh_seconds"', stored_run.timing_json or "")
        self.assertEqual(runs.list_recommendations_for_run(stored_run.id or 0), [])
        industry_context_snapshots = ContextSnapshotRepository(session).list_industry_context_snapshots(run_id=queued_run.id or 0)
        self.assertEqual(len(industry_context_snapshots), 1)
        self.assertEqual(industry_context_snapshots[0].source_breakdown["sentiment_snapshot_id"], 12)

    def test_job_execution_blocks_second_optimization_enqueue_when_one_is_active(self) -> None:
        session = create_session()
        jobs = JobRepository(session)
        runs = RunRepository(session)
        job = jobs.create(
            "Weekly Optimization",
            [],
            None,
            job_type=JobType.WEIGHT_OPTIMIZATION,
        )
        service = JobExecutionService(jobs=jobs, runs=runs, proposals=ProposalService())
        first = service.enqueue_job(job.id or 0)
        second = service.enqueue_job(job.id or 0)
        self.assertEqual(first.id, second.id)

    def test_job_execution_marks_run_failed_without_storing_dummy_recommendations(self) -> None:
        session = create_session()
        jobs = JobRepository(session)
        runs = RunRepository(session)
        job = jobs.create("Failure Case", ["AAPL"], None)
        service = JobExecutionService(jobs=jobs, runs=runs, proposals=FailingProposalService())
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
        assert latest_run.timing_json is not None
        self.assertIn('"recommendation_generation_seconds"', latest_run.timing_json)
        self.assertEqual(runs.list_recommendations_for_run(latest_run.id or 0), [])

    def test_job_execution_stops_immediately_on_multi_ticker_failure_without_partial_persistence(self) -> None:
        session = create_session()
        jobs = JobRepository(session)
        runs = RunRepository(session)
        job = jobs.create("Failure Mid Run", ["AAPL", "MISSING", "MSFT"], None)
        service = JobExecutionService(jobs=jobs, runs=runs, proposals=FailOnSecondTickerProposalService())
        queued_run = service.enqueue_job(job.id or 0)

        with self.assertRaises(RuntimeError):
            service.process_next_queued_run()

        latest_run = runs.get_run(queued_run.id or 0)
        self.assertEqual(latest_run.status, "failed")
        self.assertEqual(latest_run.error_message, "ticker not found: MISSING")
        self.assertEqual(runs.list_recommendations_for_run(latest_run.id or 0), [])
        self.assertIsNotNone(latest_run.timing_json)
        assert latest_run.timing_json is not None
        self.assertIn('"ticker": "AAPL"', latest_run.timing_json)
        self.assertIn('"status": "completed"', latest_run.timing_json)
        self.assertIn('"ticker": "MISSING"', latest_run.timing_json)
        self.assertIn('"status": "failed"', latest_run.timing_json)
        self.assertNotIn('"ticker": "MSFT"', latest_run.timing_json)

    def test_job_repository_delete_removes_job_runs_and_recommendations_without_nulling_run_job_id(self) -> None:
        session = create_session()
        jobs = JobRepository(session)
        runs = RunRepository(session)
        job = jobs.create("Delete Me", ["AAPL"], None)
        run = runs.enqueue(job.id or 0)
        claimed = runs.claim_next_queued_run()
        assert claimed is not None
        runs.update_status(run.id or 0, "completed")
        runs.add_recommendation(
            run.id or 0,
            Recommendation(
                ticker="AAPL",
                direction=RecommendationDirection.LONG,
                confidence=80.0,
                entry_price=100.0,
                stop_loss=95.0,
                take_profit=110.0,
                indicator_summary="Above SMA200 · RSI 55.0",
            ),
            RunDiagnostics(),
        )

        jobs.delete(job.id or 0)

        self.assertIsNone(session.get(JobRecord, job.id or 0))
        self.assertIsNone(session.get(RunRecord, run.id or 0))
        self.assertEqual(runs.list_recommendations_for_run(run.id or 0), [])

    def test_settings_repository_defaults_summary_backend_to_pi_agent(self) -> None:
        session = create_session()
        repository = SettingsRepository(session)
        summary_settings = repository.get_summary_settings()
        self.assertEqual(summary_settings["summary_backend"], "pi_agent")
        self.assertEqual(summary_settings["summary_pi_command"], "pi")
        self.assertEqual(summary_settings["summary_timeout_seconds"], "60")
        self.assertEqual(repository.get_optimization_minimum_resolved_trades(), 50)
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
        self.assertEqual(openai.api_key, "key-123")
        self.assertEqual(openai.api_secret, "secret-456")
        self.assertIsNotNone(stored_row)
        assert stored_row is not None
        self.assertNotEqual(stored_row.api_key, "key-123")
        self.assertNotEqual(stored_row.api_secret, "secret-456")


if __name__ == "__main__":
    unittest.main()
