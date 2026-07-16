import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from trade_proposer_app.domain.enums import JobType, RunStatus, StrategyHorizon
from trade_proposer_app.domain.models import HistoricalMarketBar, IndustryContextSnapshot, MacroContextSnapshot, NewsArticle, RecommendationPlan, TickerSignalSnapshot
from trade_proposer_app.persistence.models import (
    Base,
    HistoricalReplayBatchRecord,
    HistoricalReplaySliceRecord,
    RecommendationPlanRecord,
    ReplayEligibilityRecord,
    ReplayPlanOutcomeRecord,
)
from trade_proposer_app.repositories.context_snapshots import ContextSnapshotRepository
from trade_proposer_app.repositories.fundamental_analysis_snapshots import FundamentalAnalysisSnapshotRepository
from trade_proposer_app.repositories.historical_market_data import HistoricalMarketDataRepository
from trade_proposer_app.repositories.historical_news import HistoricalNewsRepository
from trade_proposer_app.repositories.historical_replay import HistoricalReplayRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.repositories.replay_plan_outcomes import ReplayPlanOutcomeRepository
from trade_proposer_app.repositories.replay_eligibility import ReplayEligibilityRepository
from trade_proposer_app.repositories.jobs import JobRepository
from trade_proposer_app.repositories.runs import RunRepository
from trade_proposer_app.services.builders import create_historical_replay_service
from trade_proposer_app.services.historical_bars_access import HistoricalBarsAccessService
from trade_proposer_app.services.historical_market_data import HistoricalMarketDataService, YahooHistoricalBarProvider
from trade_proposer_app.services.historical_replay import HistoricalReplayService
from trade_proposer_app.services.watchlist_orchestration import WatchlistOrchestrationService
from trade_proposer_app.services.job_execution import JobExecutionService
from trade_proposer_app.services.replay_eligibility_reclassification import ReplayEligibilityReclassificationService


def create_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


class StubHistoricalBarProvider:
    provider_name = "stub"
    source_tier = "research"

    def fetch_daily_bars(self, ticker: str, start_at: datetime, end_at: datetime) -> list[HistoricalMarketBar]:
        return [
            HistoricalMarketBar(
                ticker=ticker,
                timeframe="1d",
                bar_time=datetime(2024, 2, 5, tzinfo=timezone.utc),
                available_at=datetime(2024, 2, 5, 23, 59, 59, tzinfo=timezone.utc),
                open_price=100.0,
                high_price=102.0,
                low_price=99.0,
                close_price=101.0,
                volume=1000,
                adjusted_close=101.0,
                source="stub",
                source_tier="research",
                metadata_json="{}",
            )
        ]


class StubReplayOrchestration:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.replay_provenance: dict[str, object] | None = None
        self.provenance_seen: dict[str, object] | None = None
        self.plan_generation_tuning_config: dict[str, object] | None = None
        self.config_override_seen: dict[str, object] | None = None

    def set_replay_provenance(self, provenance):
        self.replay_provenance = provenance

    def set_plan_generation_tuning_override(self, config):
        self.plan_generation_tuning_config = config

    def execute(self, watchlist, tickers, *, job_id=None, run_id=None, as_of=None):
        self.provenance_seen = self.replay_provenance
        self.config_override_seen = self.plan_generation_tuning_config
        self.calls.append(
            {
                "watchlist": watchlist,
                "tickers": list(tickers),
                "job_id": job_id,
                "run_id": run_id,
                "as_of": as_of,
            }
        )
        return {
            "summary": {
                "signal_count": len(tickers),
                "plan_count": 1,
                "source_kind": "historical_replay",
            },
            "artifact": {"ticker_generation": [{"ticker": tickers[0]}] if tickers else []},
            "warnings_found": False,
        }


class PersistingReplayOrchestration(StubReplayOrchestration):
    def __init__(self, session: Session, *, plan_kwargs: dict[str, object] | None = None) -> None:
        super().__init__()
        self.plans = RecommendationPlanRepository(session)
        self.plan_kwargs = dict(plan_kwargs or {})

    def execute(self, watchlist, tickers, *, job_id=None, run_id=None, as_of=None):
        payload = super().execute(watchlist, tickers, job_id=job_id, run_id=run_id, as_of=as_of)
        base_kwargs = {
            "ticker": "AAPL",
            "action": "long",
            "confidence_percent": 75.0,
            "entry_price_low": 100.0,
            "entry_price_high": 100.0,
            "stop_loss": 95.0,
            "take_profit": 105.0,
            "computed_at": as_of or datetime.now(timezone.utc),
            "job_id": job_id,
            "run_id": run_id,
            "signal_breakdown": {"setup_family": "breakout"},
        }
        base_kwargs.update(self.plan_kwargs)
        stored = self.plans.create_plan(RecommendationPlan(**base_kwargs))
        payload["summary"]["plan_count"] = 1
        payload["summary"]["plan_ids"] = [stored.id]
        return payload


class HistoricalReplayTests(unittest.TestCase):
    def _run_replay_resolution_case(
        self,
        *,
        intraday_bars: list[tuple[timedelta, float, float, float]],
        plan_kwargs: dict[str, object] | None = None,
        daily_high: float = 106.0,
        daily_low: float = 94.0,
    ) -> tuple[dict[str, object], dict[str, object]]:
        session = create_session()
        try:
            market_repository = HistoricalMarketDataRepository(session)
            historical_replay = HistoricalReplayService(
                historical_replays=HistoricalReplayRepository(session),
                jobs=JobRepository(session),
                runs=RunRepository(session),
                historical_market_data=HistoricalMarketDataService(
                    market_repository,
                    provider=StubHistoricalBarProvider(),
                ),
            )
            replay_as_of = datetime(2024, 2, 5, 23, 59, 59, tzinfo=timezone.utc)
            for offset, high, low, close in intraday_bars:
                bar_time = replay_as_of + offset
                market_repository.upsert_bar(
                    HistoricalMarketBar(
                        ticker="AAPL",
                        timeframe="1m",
                        bar_time=bar_time,
                        available_at=bar_time,
                        open_price=100.0,
                        high_price=high,
                        low_price=low,
                        close_price=close,
                        volume=1000,
                        source="fixture",
                    )
                )
            for day_offset in range(-12, 6):
                day = replay_as_of + timedelta(days=day_offset)
                market_repository.upsert_bar(
                    HistoricalMarketBar(
                        ticker="AAPL",
                        timeframe="1d",
                        bar_time=day,
                        available_at=min(day.replace(hour=23, minute=59, second=59), replay_as_of + timedelta(days=max(day_offset, 0))),
                        open_price=100.0,
                        high_price=daily_high,
                        low_price=daily_low,
                        close_price=100.0,
                        volume=1000,
                        source="fixture",
                    )
                )
            batch = historical_replay.create_batch(
                name="Replay resolution edge",
                mode="research",
                tickers=["AAPL"],
                as_of_start=datetime(2024, 2, 5, tzinfo=timezone.utc),
                as_of_end=replay_as_of,
            )
            historical_replay.enqueue_batch(batch.id or 0)
            execution = JobExecutionService(
                jobs=JobRepository(session),
                runs=RunRepository(session),
                historical_replay=historical_replay,
                watchlist_orchestration=PersistingReplayOrchestration(
                    session,
                    plan_kwargs=plan_kwargs,
                ),
            )
            claimed = RunRepository(session).claim_next_queued_run(worker_id="worker-test")
            assert claimed is not None
            final_run, _ = execution.execute_claimed_run(claimed, worker_id="worker-test")
            summary = json.loads(final_run.summary_json or "{}")
            slice_row = HistoricalReplayRepository(session).list_slices(batch.id or 0)[0]
            replay_outcomes = ReplayPlanOutcomeRepository(session).list_for_slice(slice_row.id or 0)
            self.assertEqual(1, len(replay_outcomes))
            eligibilities = ReplayEligibilityRepository(session).list_for_slice(slice_row.id or 0)
            self.assertEqual(1, len(eligibilities))
            return {**replay_outcomes[0], "eligibility": eligibilities[0]}, summary
        finally:
            session.close()

    def test_historical_bars_access_cache_only_returns_market_input_coverage_and_no_hydration(self) -> None:
        session = create_session()
        try:
            class CountingProvider(StubHistoricalBarProvider):
                calls = 0

                def fetch_daily_bars(self, ticker: str, start_at: datetime, end_at: datetime) -> list[HistoricalMarketBar]:
                    self.calls += 1
                    return super().fetch_daily_bars(ticker, start_at, end_at)

            provider = CountingProvider()
            market_repository = HistoricalMarketDataRepository(session)
            replay_as_of = datetime(2024, 2, 5, 23, 59, 59, tzinfo=timezone.utc)
            for day_offset in range(-12, 1):
                day = replay_as_of + timedelta(days=day_offset)
                market_repository.upsert_bar(
                    HistoricalMarketBar(
                        ticker="AAPL",
                        timeframe="1d",
                        bar_time=day,
                        available_at=day.replace(hour=23, minute=59, second=59),
                        open_price=100.0,
                        high_price=102.0,
                        low_price=99.0,
                        close_price=101.0,
                        volume=1000,
                        source="fixture",
                    )
                )
            service = HistoricalBarsAccessService(
                HistoricalMarketDataService(market_repository, provider=provider)
            )

            result = service.replay_market_inputs(
                tickers=["AAPL"],
                batch_start=datetime(2024, 2, 5, tzinfo=timezone.utc),
                batch_end=replay_as_of,
                as_of=replay_as_of,
                policy="cache_only",
            )

            self.assertEqual(0, provider.calls)
            self.assertEqual("skipped_remote_hydration", result.hydration_summary["status"])
            self.assertEqual(1, result.market_input["covered_ticker_count"])
            self.assertEqual("cache_only", result.coverage_report["policy"])
            self.assertEqual("HistoricalBarsAccessService", result.coverage_report["access_service"])
            self.assertIn("input_coverage_hash", result.coverage_report)
        finally:
            session.close()

    def test_historical_bars_access_replay_ignores_remote_policy_and_stays_cache_only(self) -> None:
        session = create_session()
        try:
            class CountingProvider(StubHistoricalBarProvider):
                def __init__(self) -> None:
                    self.tickers: list[str] = []

                def fetch_daily_bars(self, ticker: str, start_at: datetime, end_at: datetime) -> list[HistoricalMarketBar]:
                    self.tickers.append(ticker)
                    return super().fetch_daily_bars(ticker, start_at, end_at)

            provider = CountingProvider()
            market_repository = HistoricalMarketDataRepository(session)
            replay_as_of = datetime(2024, 2, 5, 23, 59, 59, tzinfo=timezone.utc)
            market_repository.upsert_bar(
                HistoricalMarketBar(
                    ticker="AAPL",
                    timeframe="1d",
                    bar_time=datetime(2024, 2, 5, tzinfo=timezone.utc),
                    available_at=replay_as_of,
                    open_price=100.0,
                    high_price=102.0,
                    low_price=99.0,
                    close_price=101.0,
                    volume=1000,
                    source="fixture",
                )
            )
            service = HistoricalBarsAccessService(HistoricalMarketDataService(market_repository, provider=provider))

            result = service.replay_market_inputs(
                tickers=["AAPL", "MSFT"],
                batch_start=datetime(2024, 2, 5, tzinfo=timezone.utc),
                batch_end=replay_as_of,
                as_of=replay_as_of,
                policy="cache_then_remote",
            )

            self.assertEqual([], provider.tickers)
            self.assertEqual("skipped_remote_hydration", result.hydration_summary["status"])
            self.assertEqual("cache_then_remote", result.hydration_summary["requested_policy"])
            self.assertEqual("cache_only", result.hydration_summary["policy"])
            self.assertEqual(["MSFT"], result.hydration_summary["gap_report"]["missing_tickers"])
            self.assertEqual(1, result.market_input["covered_ticker_count"])
            self.assertEqual("cache_only", result.coverage_report["policy"])
            self.assertEqual("cache", result.coverage_report["source"])
        finally:
            session.close()

    def test_historical_bars_access_typed_daily_and_intraday_methods_return_coverage(self) -> None:
        session = create_session()
        try:
            market_repository = HistoricalMarketDataRepository(session)
            replay_as_of = datetime(2024, 2, 5, 23, 59, 59, tzinfo=timezone.utc)
            market_repository.upsert_bar(
                HistoricalMarketBar(
                    ticker="AAPL",
                    timeframe="1m",
                    bar_time=datetime(2024, 2, 5, 15, 30, tzinfo=timezone.utc),
                    available_at=datetime(2024, 2, 5, 15, 31, tzinfo=timezone.utc),
                    open_price=100.0,
                    high_price=101.0,
                    low_price=99.0,
                    close_price=100.5,
                    volume=1000,
                    source="fixture",
                )
            )
            service = HistoricalBarsAccessService(HistoricalMarketDataService(market_repository, provider=StubHistoricalBarProvider()))

            daily = service.daily_bars(
                ticker="AAPL",
                start_at=datetime(2024, 2, 5, tzinfo=timezone.utc),
                end_at=replay_as_of,
                policy="cache_then_remote",
            )
            intraday = service.intraday_1m_bars(
                ticker="AAPL",
                start_at=datetime(2024, 2, 5, tzinfo=timezone.utc),
                end_at=replay_as_of,
                available_at=replay_as_of,
                policy="cache_then_remote",
            )

            self.assertEqual("1d", daily.timeframe)
            self.assertEqual(1, len(daily.bars))
            self.assertTrue(daily.coverage["covered"])
            self.assertEqual("1m", intraday.timeframe)
            self.assertEqual(1, len(intraday.bars))
            self.assertEqual("remote_hydration_not_supported_for_1m", intraday.hydration_summary["reason"])
        finally:
            session.close()

    def test_replay_eligibility_reclassification_repairs_corrupted_rows_from_stored_artifacts(self) -> None:
        session = create_session()
        try:
            market_repository = HistoricalMarketDataRepository(session)
            historical_replay = HistoricalReplayService(
                historical_replays=HistoricalReplayRepository(session),
                jobs=JobRepository(session),
                runs=RunRepository(session),
                historical_market_data=HistoricalMarketDataService(
                    market_repository,
                    provider=StubHistoricalBarProvider(),
                ),
            )
            replay_as_of = datetime(2024, 2, 5, 23, 59, 59, tzinfo=timezone.utc)
            for offset, high, low, close in [
                (timedelta(minutes=1), 101.0, 99.0, 100.0),
                (timedelta(minutes=2), 106.0, 100.0, 105.5),
                (timedelta(days=5), 100.0, 96.0, 100.0),
            ]:
                bar_time = replay_as_of + offset
                market_repository.upsert_bar(
                    HistoricalMarketBar(
                        ticker="AAPL",
                        timeframe="1m",
                        bar_time=bar_time,
                        available_at=bar_time,
                        open_price=100.0,
                        high_price=high,
                        low_price=low,
                        close_price=close,
                        volume=1000,
                        source="fixture",
                    )
                )
            for day_offset in range(-12, 6):
                day = replay_as_of + timedelta(days=day_offset)
                market_repository.upsert_bar(
                    HistoricalMarketBar(
                        ticker="AAPL",
                        timeframe="1d",
                        bar_time=day,
                        available_at=min(day.replace(hour=23, minute=59, second=59), replay_as_of + timedelta(days=max(day_offset, 0))),
                        open_price=100.0,
                        high_price=106.0,
                        low_price=94.0,
                        close_price=100.0,
                        volume=1000,
                        source="fixture",
                    )
                )
            batch = historical_replay.create_batch(
                name="Replay reclassify",
                mode="research",
                tickers=["AAPL"],
                as_of_start=datetime(2024, 2, 5, tzinfo=timezone.utc),
                as_of_end=replay_as_of,
            )
            historical_replay.enqueue_batch(batch.id or 0)
            execution = JobExecutionService(
                jobs=JobRepository(session),
                runs=RunRepository(session),
                historical_replay=historical_replay,
                watchlist_orchestration=PersistingReplayOrchestration(session),
            )
            claimed = RunRepository(session).claim_next_queued_run(worker_id="worker-test")
            assert claimed is not None
            execution.execute_claimed_run(claimed, worker_id="worker-test")
            plan_row = session.query(RecommendationPlanRecord).one()
            signal_breakdown = json.loads(plan_row.signal_breakdown_json or "{}")
            signal_breakdown.pop("replay_provenance", None)
            plan_row.signal_breakdown_json = json.dumps(signal_breakdown)
            row = session.query(ReplayEligibilityRecord).one()
            row.tier = "ineligible"
            row.eligible_for_tuning = False
            row.rejection_reasons_json = '["manual_corruption"]'
            session.commit()

            summary = ReplayEligibilityReclassificationService(session).reclassify_batch(batch.id or 0)

            self.assertEqual(1, summary.outcome_count)
            self.assertEqual(1, summary.reclassified_count)
            self.assertEqual(0, summary.before_eligible_count)
            self.assertEqual(1, summary.after_eligible_count)
            self.assertEqual(1, summary.after_tier_counts["tier_a"])
            repaired = session.query(ReplayEligibilityRecord).one()
            self.assertTrue(repaired.eligible_for_tuning)
            self.assertEqual("tier_a", repaired.tier)
            repaired_plan = session.query(RecommendationPlanRecord).one()
            repaired_signal_breakdown = json.loads(repaired_plan.signal_breakdown_json or "{}")
            self.assertEqual("historical_replay_reclassification", repaired_signal_breakdown["replay_provenance"]["source"])
        finally:
            session.close()

    def test_replay_eligibility_reclassification_reuses_slice_coverage(self) -> None:
        session = create_session()
        try:
            replay_as_of = datetime(2024, 2, 5, 23, 59, 59, tzinfo=timezone.utc)
            batch = HistoricalReplayBatchRecord(
                name="Replay reclassify coverage cache",
                mode="research",
                tickers_json='["AAPL"]',
                as_of_start=datetime(2024, 2, 5, tzinfo=timezone.utc),
                as_of_end=replay_as_of,
            )
            session.add(batch)
            session.flush()
            slice_row = HistoricalReplaySliceRecord(
                replay_batch_id=batch.id or 0,
                as_of=replay_as_of,
                status="completed",
                input_summary_json=json.dumps({"as_of": replay_as_of.isoformat()}),
            )
            session.add(slice_row)
            session.flush()

            provenance = {
                "source": "historical_replay",
                "as_of": replay_as_of.isoformat(),
                "replay_batch_id": batch.id,
                "replay_slice_id": slice_row.id,
                "code_version": "test",
                "settings_hash": "settings",
                "input_coverage_hash": "coverage",
                "plan_generation_config_hash": "config",
            }
            plan_ids: list[int] = []
            for index in range(2):
                plan = RecommendationPlanRecord(
                    ticker="AAPL",
                    action="long",
                    confidence_percent=75.0,
                    entry_price_low=100.0,
                    entry_price_high=100.0,
                    stop_loss=95.0,
                    take_profit=105.0,
                    computed_at=replay_as_of,
                    signal_breakdown_json=json.dumps({"replay_provenance": provenance}),
                )
                session.add(plan)
                session.flush()
                plan_ids.append(plan.id or 0)
                session.add(
                    ReplayPlanOutcomeRecord(
                        replay_batch_id=batch.id or 0,
                        replay_slice_id=slice_row.id or 0,
                        recommendation_plan_id=plan.id or 0,
                        candidate_config_hash=f"candidate-{index}",
                        resolution_source="intraday",
                        outcome="win",
                        status="resolved",
                        outcome_json='{"outcome": "win", "status": "resolved"}',
                    )
                )
            session.commit()

            coverage_report = {
                "input_coverage_hash": "coverage",
                "tickers": [{"ticker": "AAPL", "tier": "tier_a", "blockers": [], "warnings": []}],
            }
            with patch.object(
                ReplayEligibilityReclassificationService,
                "_coverage_report_for_slice",
                return_value=coverage_report,
            ) as coverage_for_slice:
                summary = ReplayEligibilityReclassificationService(session).reclassify_batch(batch.id or 0)

            self.assertEqual(2, summary.outcome_count)
            self.assertEqual(2, summary.reclassified_count)
            self.assertEqual(2, summary.after_eligible_count)
            self.assertEqual(1, coverage_for_slice.call_count)
            repaired_rows = session.query(ReplayEligibilityRecord).order_by(ReplayEligibilityRecord.id.asc()).all()
            self.assertEqual(["tier_a", "tier_a"], [row.tier for row in repaired_rows])
            self.assertEqual(plan_ids, [row.recommendation_plan_id for row in repaired_rows])
        finally:
            session.close()

    def test_replay_eligibility_rejects_missing_mandatory_provenance(self) -> None:
        eligibility = JobExecutionService._classify_replay_eligibility(
            ticker="AAPL",
            coverage={"tier": "tier_a", "blockers": [], "warnings": []},
            resolution_source="intraday",
            outcome={"outcome": "win", "status": "resolved"},
            candidate_config_hash="abc",
            replay_provenance={"as_of": "2024-02-05T23:59:59+00:00"},
        )

        self.assertFalse(eligibility["eligible_for_tuning"])
        self.assertEqual("tier_c", eligibility["tier"])
        self.assertIn("missing_replay_provenance:code_version", eligibility["rejection_reasons"])
        self.assertIn("missing_replay_provenance:settings_hash", eligibility["rejection_reasons"])
        self.assertIn("missing_replay_provenance:input_coverage_hash", eligibility["rejection_reasons"])

    def test_cache_only_replay_builds_coverage_from_stored_bars_without_remote_hydration(self) -> None:
        session = create_session()
        try:
            class CountingProvider(StubHistoricalBarProvider):
                calls = 0

                def fetch_daily_bars(self, ticker: str, start_at: datetime, end_at: datetime) -> list[HistoricalMarketBar]:
                    self.calls += 1
                    return super().fetch_daily_bars(ticker, start_at, end_at)

            provider = CountingProvider()
            market_repository = HistoricalMarketDataRepository(session)
            replay_as_of = datetime(2024, 2, 5, 23, 59, 59, tzinfo=timezone.utc)
            for day_offset in range(-12, 6):
                day = replay_as_of + timedelta(days=day_offset)
                market_repository.upsert_bar(
                    HistoricalMarketBar(
                        ticker="AAPL",
                        timeframe="1d",
                        bar_time=day,
                        available_at=day.replace(hour=23, minute=59, second=59),
                        open_price=100.0,
                        high_price=102.0,
                        low_price=99.0,
                        close_price=101.0,
                        volume=1000,
                        source="fixture",
                    )
                )
            historical_replay = HistoricalReplayService(
                historical_replays=HistoricalReplayRepository(session),
                jobs=JobRepository(session),
                runs=RunRepository(session),
                historical_market_data=HistoricalMarketDataService(market_repository, provider=provider),
                input_access_policy="cache_only",
            )
            batch = historical_replay.create_batch(
                name="Cache-only replay coverage",
                mode="research",
                tickers=["AAPL"],
                as_of_start=datetime(2024, 2, 5, tzinfo=timezone.utc),
                as_of_end=replay_as_of,
            )
            slice_row = HistoricalReplayRepository(session).list_slices(batch.id or 0)[0]

            input_summary, _ = historical_replay.build_slice_execution_payload(batch.id or 0, slice_row.id or 0)

            self.assertEqual(0, provider.calls)
            self.assertEqual("skipped_remote_hydration", input_summary["hydration_summary"]["status"])
            coverage = input_summary["replay_coverage_report"]
            self.assertEqual("cache_only", coverage["policy"])
            self.assertEqual(1, coverage["ticker_count"])
            self.assertIn("input_coverage_hash", coverage)
            self.assertEqual(1, coverage["tier_counts"]["tier_b"])
        finally:
            session.close()

    def test_cache_then_remote_replay_service_is_forced_to_cache_only(self) -> None:
        session = create_session()
        try:
            class CountingProvider(StubHistoricalBarProvider):
                calls = 0

                def fetch_daily_bars(self, ticker: str, start_at: datetime, end_at: datetime) -> list[HistoricalMarketBar]:
                    self.calls += 1
                    return super().fetch_daily_bars(ticker, start_at, end_at)

            provider = CountingProvider()
            market_repository = HistoricalMarketDataRepository(session)
            historical_replay = HistoricalReplayService(
                historical_replays=HistoricalReplayRepository(session),
                jobs=JobRepository(session),
                runs=RunRepository(session),
                historical_market_data=HistoricalMarketDataService(market_repository, provider=provider),
                input_access_policy="cache_then_remote",
            )
            replay_as_of = datetime(2024, 2, 5, 23, 59, 59, tzinfo=timezone.utc)
            batch = historical_replay.create_batch(
                name="Forced cache-only replay coverage",
                mode="research",
                tickers=["AAPL"],
                as_of_start=datetime(2024, 2, 5, tzinfo=timezone.utc),
                as_of_end=replay_as_of,
            )
            slice_row = HistoricalReplayRepository(session).list_slices(batch.id or 0)[0]

            input_summary, _ = historical_replay.build_slice_execution_payload(batch.id or 0, slice_row.id or 0)

            self.assertEqual(0, provider.calls)
            self.assertEqual("cache_then_remote", historical_replay.requested_input_access_policy)
            self.assertEqual("cache_only", historical_replay.input_access_policy)
            self.assertEqual("cache_only", input_summary["hydration_summary"]["requested_policy"])
            coverage = input_summary["replay_coverage_report"]
            self.assertEqual("cache_only", coverage["policy"])
            self.assertEqual("cache", coverage["source"])
            self.assertIn("input_coverage_hash", coverage)
        finally:
            session.close()

    def test_watchlist_orchestration_embeds_replay_provenance_in_signal_and_plan_payloads(self) -> None:
        service = WatchlistOrchestrationService(
            context_snapshots=MagicMock(),
            recommendation_plans=MagicMock(),
            cheap_scan_service=MagicMock(),
            deep_analysis_service=MagicMock(),
        )
        provenance = {"source": "historical_replay", "replay_slice_id": 7, "as_of": "2024-02-05T23:59:59+00:00"}
        service.set_replay_provenance(provenance)

        signal = service._with_replay_provenance_signal(TickerSignalSnapshot(ticker="AAPL"))
        plan = service._with_replay_provenance_plan(RecommendationPlan(ticker="AAPL", action="long"))

        self.assertEqual(provenance, signal.diagnostics["replay_provenance"])
        self.assertEqual(provenance, plan.signal_breakdown["replay_provenance"])
        self.assertEqual(provenance, plan.evidence_summary["replay_provenance"])

    def test_watchlist_orchestration_plan_generation_override_is_scoped_and_rejects_unknown_keys(self) -> None:
        service = WatchlistOrchestrationService(
            context_snapshots=MagicMock(),
            recommendation_plans=MagicMock(),
            cheap_scan_service=MagicMock(),
            deep_analysis_service=MagicMock(),
            plan_generation_tuning_config={"global.entry_band_risk_fraction": 0.05},
        )
        self.assertEqual(0.05, service._plan_generation_tuning_value("global.entry_band_risk_fraction", 0.0))

        service.set_plan_generation_tuning_override({"global.entry_band_risk_fraction": 0.2})
        self.assertEqual(0.2, service._plan_generation_tuning_value("global.entry_band_risk_fraction", 0.0))

        service.set_plan_generation_tuning_override(None)
        self.assertEqual(0.05, service._plan_generation_tuning_value("global.entry_band_risk_fraction", 0.0))

        with self.assertRaises(ValueError):
            service.set_plan_generation_tuning_override({"unknown.key": 1.0})

    def test_yahoo_provider_parses_daily_bar_payload(self) -> None:
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "chart": {
                "result": [
                    {
                        "timestamp": [1704067200],
                        "indicators": {
                            "quote": [
                                {
                                    "open": [100.0],
                                    "high": [101.0],
                                    "low": [99.5],
                                    "close": [100.5],
                                    "volume": [12345],
                                }
                            ],
                            "adjclose": [{"adjclose": [100.25]}],
                        },
                    }
                ]
            }
        }
        with patch("trade_proposer_app.services.historical_market_data.httpx.get", return_value=response):
            provider = YahooHistoricalBarProvider(base_url="https://query1.finance.yahoo.com")
            bars = provider.fetch_daily_bars(
                "AAPL",
                start_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                end_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            )
        self.assertEqual(1, len(bars))
        self.assertEqual("AAPL", bars[0].ticker)
        self.assertEqual(100.5, bars[0].close_price)
        self.assertEqual(100.25, bars[0].adjusted_close)
        self.assertEqual(datetime(2024, 1, 1, 23, 59, 59, tzinfo=timezone.utc), bars[0].available_at)

    def test_historical_market_bar_upsert_and_window_query(self) -> None:
        session = create_session()
        try:
            repository = HistoricalMarketDataRepository(session)
            repository.upsert_bar(
                HistoricalMarketBar(
                    ticker="AAPL",
                    timeframe="1d",
                    bar_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
                    available_at=datetime(2024, 1, 1, 23, 59, 59, tzinfo=timezone.utc),
                    open_price=100.0,
                    high_price=101.0,
                    low_price=99.0,
                    close_price=100.5,
                    volume=1000,
                    source="fixture",
                )
            )
            repository.upsert_bar(
                HistoricalMarketBar(
                    ticker="AAPL",
                    timeframe="1d",
                    bar_time=datetime(2024, 1, 2, tzinfo=timezone.utc),
                    available_at=datetime(2024, 1, 2, 23, 59, 59, tzinfo=timezone.utc),
                    open_price=101.0,
                    high_price=102.0,
                    low_price=100.0,
                    close_price=101.5,
                    volume=1100,
                    source="fixture",
                )
            )
            repository.upsert_bar(
                HistoricalMarketBar(
                    ticker="AAPL",
                    timeframe="1d",
                    bar_time=datetime(2024, 1, 2, tzinfo=timezone.utc),
                    available_at=datetime(2024, 1, 2, 23, 59, 59, tzinfo=timezone.utc),
                    open_price=101.0,
                    high_price=103.0,
                    low_price=100.0,
                    close_price=102.0,
                    volume=1200,
                    source="fixture-refresh",
                )
            )
            bars = repository.list_bars(
                ticker="AAPL",
                timeframe="1d",
                end_at=datetime(2024, 1, 2, tzinfo=timezone.utc),
                available_at=datetime(2024, 1, 2, 23, 59, 59, tzinfo=timezone.utc),
                limit=10,
            )
            self.assertEqual(2, len(bars))
            self.assertEqual(103.0, bars[-1].high_price)
            self.assertEqual("fixture-refresh", bars[-1].source)
        finally:
            session.close()

    def test_replay_coverage_report_separates_generation_and_resolution_bars(self) -> None:
        session = create_session()
        try:
            repository = HistoricalMarketDataRepository(session)
            service = HistoricalMarketDataService(repository, provider=StubHistoricalBarProvider())
            as_of = datetime(2024, 2, 15, 15, 30, tzinfo=timezone.utc)
            for day_offset in range(10):
                day = as_of - timedelta(days=day_offset + 1)
                repository.upsert_bar(
                    HistoricalMarketBar(
                        ticker="AAPL",
                        timeframe="1d",
                        bar_time=day,
                        available_at=day.replace(hour=23, minute=59, second=59),
                        open_price=100.0,
                        high_price=101.0,
                        low_price=99.0,
                        close_price=100.5,
                        volume=1000,
                        source="fixture",
                    )
                )
            repository.upsert_bar(
                HistoricalMarketBar(
                    ticker="AAPL",
                    timeframe="1m",
                    bar_time=as_of - timedelta(minutes=1),
                    available_at=as_of,
                    open_price=100.0,
                    high_price=100.2,
                    low_price=99.9,
                    close_price=100.1,
                    volume=100,
                    source="fixture",
                )
            )
            repository.upsert_bar(
                HistoricalMarketBar(
                    ticker="AAPL",
                    timeframe="1m",
                    bar_time=as_of + timedelta(minutes=1),
                    available_at=as_of + timedelta(minutes=2),
                    open_price=100.1,
                    high_price=101.0,
                    low_price=100.0,
                    close_price=100.9,
                    volume=100,
                    source="fixture",
                )
            )
            repository.upsert_bar(
                HistoricalMarketBar(
                    ticker="MSFT",
                    timeframe="1d",
                    bar_time=as_of - timedelta(days=1),
                    available_at=as_of + timedelta(days=1),
                    open_price=200.0,
                    high_price=201.0,
                    low_price=199.0,
                    close_price=200.5,
                    volume=1000,
                    source="fixture",
                )
            )

            report = service.build_replay_coverage_report(
                tickers=["AAPL", "MSFT"],
                as_of=as_of,
                minimum_generation_daily_bars=10,
            )

            self.assertEqual(1, report["tier_counts"]["tier_a"])
            self.assertEqual(1, report["tier_counts"]["ineligible"])
            aapl = report["tickers"][0]
            msft = report["tickers"][1]
            self.assertEqual("tier_a", aapl["tier"])
            self.assertEqual(10, aapl["generation"]["daily_bar_count"])
            self.assertEqual(1, aapl["resolution"]["intraday_1m_bar_count"])
            self.assertEqual("ineligible", msft["tier"])
            self.assertEqual(0, msft["generation"]["daily_bar_count"])
            self.assertIn("insufficient_generation_daily_bars", msft["blockers"])
        finally:
            session.close()

    def test_complete_slice_marks_invalid_json_envelopes_degraded(self) -> None:
        session = create_session()
        try:
            service = HistoricalReplayService(
                historical_replays=HistoricalReplayRepository(session),
                jobs=JobRepository(session),
                runs=RunRepository(session),
                historical_market_data=HistoricalMarketDataService(
                    HistoricalMarketDataRepository(session),
                    provider=StubHistoricalBarProvider(),
                ),
            )
            batch = service.create_batch(
                name="Replay invalid envelope",
                mode="research",
                tickers=["AAPL"],
                as_of_start=datetime(2024, 1, 2, tzinfo=timezone.utc),
                as_of_end=datetime(2024, 1, 2, 23, 59, 59, tzinfo=timezone.utc),
            )
            slice_row = HistoricalReplayRepository(session).list_slices(batch.id or 0)[0]

            completed = service.complete_slice(
                slice_row.id or 0,
                input_summary={"replay_batch_id": batch.id},
                output_summary={"batch_id": batch.id},
                timing={},
            )

            self.assertEqual("degraded", completed.status)
            payload = json.loads(completed.input_summary_json)
            self.assertTrue(payload["degraded"])
            self.assertIn("missing_replay_input_summary:as_of", payload["validation_blockers"])
        finally:
            session.close()

    def test_canonical_replay_builder_configures_required_input_services(self) -> None:
        session = create_session()
        try:
            service = create_historical_replay_service(session, input_access_policy="cache_only")
            self.assertIsNotNone(service.historical_market_data)
            self.assertIsNotNone(service.historical_bars_access)
            self.assertIsNotNone(service.historical_news_access)
            self.assertIsNotNone(service.context_snapshot_access)
            self.assertIsNotNone(service.fundamental_snapshot_access)
            self.assertEqual("cache_only", service.input_access_policy)
        finally:
            session.close()

    def test_canonical_replay_builder_defaults_to_cache_only_for_vps_safety(self) -> None:
        session = create_session()
        try:
            service = create_historical_replay_service(session)
            self.assertEqual("cache_only", service.input_access_policy)
        finally:
            session.close()

    def test_replay_execution_requires_bars_access_service(self) -> None:
        session = create_session()
        try:
            service = HistoricalReplayService(
                historical_replays=HistoricalReplayRepository(session),
                jobs=JobRepository(session),
                runs=RunRepository(session),
            )
            batch = service.create_batch(
                name="Replay fixture without bars",
                mode="research",
                tickers=["AAPL"],
                as_of_start=datetime(2024, 1, 2, tzinfo=timezone.utc),
                as_of_end=datetime(2024, 1, 2, 23, 59, 59, tzinfo=timezone.utc),
            )
            slice_row = HistoricalReplayRepository(session).list_slices(batch.id or 0)[0]
            with self.assertRaisesRegex(RuntimeError, "historical bars access service is required"):
                service.build_slice_execution_payload(batch.id or 0, slice_row.id or 0)
        finally:
            session.close()

    def test_create_batch_creates_daily_slices_from_universe_preset(self) -> None:
        session = create_session()
        try:
            service = HistoricalReplayService(
                historical_replays=HistoricalReplayRepository(session),
                jobs=JobRepository(session),
                runs=RunRepository(session),
            )
            batch = service.create_batch(
                name="Replay MVP",
                mode="research",
                universe_preset="us_large_cap_top20_v1",
                as_of_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                as_of_end=datetime(2024, 1, 3, 23, 59, 59, tzinfo=timezone.utc),
            )
            repository = HistoricalReplayRepository(session)
            slices = repository.list_slices(batch.id or 0)
            self.assertEqual(2, len(slices))
            self.assertEqual(["planned", "planned"], [item.status for item in slices])
            self.assertEqual([datetime(2024, 1, 2, 23, 59, 59, tzinfo=timezone.utc), datetime(2024, 1, 3, 23, 59, 59, tzinfo=timezone.utc)], [item.as_of for item in slices])
            summary = repository.summarize_batch(batch.id or 0)
            self.assertEqual(2, summary["slice_count"])
            self.assertEqual(2, summary["planned_count"])
            self.assertEqual("us_large_cap_top20_v1", batch.universe_preset)
            self.assertEqual("next_open", batch.entry_timing)
        finally:
            session.close()

    def test_historical_replay_run_invokes_plan_generation_when_orchestration_is_configured(self) -> None:
        session = create_session()
        try:
            historical_replay = HistoricalReplayService(
                historical_replays=HistoricalReplayRepository(session),
                jobs=JobRepository(session),
                runs=RunRepository(session),
                historical_market_data=HistoricalMarketDataService(
                    HistoricalMarketDataRepository(session),
                    provider=StubHistoricalBarProvider(),
                ),
            )
            candidate_override = {"global.entry_band_risk_fraction": 0.2}
            batch = historical_replay.create_batch(
                name="Replay plan generation",
                mode="research",
                tickers=["AAPL", "MSFT"],
                as_of_start=datetime(2024, 2, 5, tzinfo=timezone.utc),
                as_of_end=datetime(2024, 2, 5, 23, 59, 59, tzinfo=timezone.utc),
                config={"plan_generation_tuning_config_override": candidate_override},
            )
            historical_replay.enqueue_batch(batch.id or 0)
            orchestration = StubReplayOrchestration()
            execution = JobExecutionService(
                jobs=JobRepository(session),
                runs=RunRepository(session),
                historical_replay=historical_replay,
                watchlist_orchestration=orchestration,
            )
            claimed = RunRepository(session).claim_next_queued_run(worker_id="worker-test")
            assert claimed is not None

            final_run, _ = execution.execute_claimed_run(claimed, worker_id="worker-test")

            self.assertEqual(RunStatus.COMPLETED, final_run.status)
            self.assertEqual(1, len(orchestration.calls))
            self.assertIsNotNone(orchestration.provenance_seen)
            self.assertEqual("historical_replay", orchestration.provenance_seen["source"])
            self.assertEqual(batch.id, orchestration.provenance_seen["replay_batch_id"])
            self.assertEqual(candidate_override, orchestration.config_override_seen)
            self.assertEqual(["AAPL", "MSFT"], orchestration.calls[0]["tickers"])
            self.assertEqual(datetime(2024, 2, 5, 23, 59, 59, tzinfo=timezone.utc), orchestration.calls[0]["as_of"])
            summary = json.loads(final_run.summary_json or "{}")
            self.assertEqual("plans_resolved", summary["pipeline_stage"])
            self.assertEqual(1, summary["plan_generation"]["plan_count"])
            self.assertTrue(summary["plan_generation"]["candidate_config_override_applied"])
            self.assertEqual("historical_replay", summary["plan_generation"]["replay_provenance"]["source"])
            slice_row = HistoricalReplayRepository(session).list_slices(batch.id or 0)[0]
            output_summary = json.loads(slice_row.output_summary_json)
            self.assertEqual("plans_resolved", output_summary["pipeline_stage"])
            self.assertEqual("build replay eligibility records from replay-generated plans and outcomes", output_summary["next_step"])
        finally:
            session.close()

    def test_replay_resolution_uses_intraday_order_when_stop_and_target_are_touched_on_different_bars(self) -> None:
        outcome, summary = self._run_replay_resolution_case(
            intraday_bars=[
                (timedelta(minutes=1), 101.0, 99.0, 100.0),
                (timedelta(minutes=2), 106.0, 100.0, 105.5),
                (timedelta(minutes=3), 100.0, 94.0, 95.0),
                (timedelta(days=5), 100.0, 96.0, 100.0),
            ],
        )

        self.assertEqual("plans_resolved", summary["pipeline_stage"])
        self.assertEqual("win", outcome["outcome"])
        self.assertEqual("resolved", outcome["status"])
        self.assertEqual("intraday", outcome["resolution_source"])
        self.assertEqual("tier_a", outcome["eligibility"]["tier"])
        self.assertTrue(outcome["eligibility"]["eligible_for_tuning"])
        self.assertEqual("AAPL", outcome["eligibility"]["diagnostics"]["artifact_key"]["ticker"])
        self.assertIn("code_version", outcome["eligibility"]["diagnostics"]["artifact_versions"])

    def test_replay_resolution_same_bar_stop_and_target_tie_is_conservative_loss(self) -> None:
        outcome, summary = self._run_replay_resolution_case(
            intraday_bars=[
                (timedelta(minutes=1), 106.0, 94.0, 100.0),
                (timedelta(days=5), 100.0, 96.0, 100.0),
            ],
        )

        self.assertEqual({"loss": 1}, summary["replay_resolution"]["outcome_counts"])
        self.assertEqual("loss", outcome["outcome"])
        self.assertEqual("resolved", outcome["status"])
        self.assertIn("same bar", outcome["outcome_payload"]["notes"])

    def test_replay_eligibility_tier_b_accepts_daily_prefilter_fallback(self) -> None:
        outcome, summary = self._run_replay_resolution_case(
            intraday_bars=[],
            plan_kwargs={"holding_period_days": 1, "horizon": StrategyHorizon.ONE_DAY},
            daily_high=99.5,
            daily_low=96.0,
        )

        self.assertEqual("daily_prefilter", outcome["resolution_source"])
        self.assertEqual("expired", outcome["outcome"])
        self.assertEqual("tier_b", outcome["eligibility"]["tier"])
        self.assertTrue(outcome["eligibility"]["eligible_for_tuning"])
        self.assertIn("accepted_daily_prefilter_resolution", outcome["eligibility"]["rejection_reasons"])
        self.assertEqual({"tier_b": 1}, summary["replay_resolution"]["eligibility_tier_counts"])

    def test_replay_resolution_preserves_open_no_entry_before_horizon_expiration(self) -> None:
        outcome, summary = self._run_replay_resolution_case(
            intraday_bars=[
                (timedelta(minutes=1), 99.5, 96.0, 98.0),
                (timedelta(days=5), 99.5, 96.0, 98.0),
            ],
            plan_kwargs={"holding_period_days": 10, "horizon": StrategyHorizon.ONE_MONTH},
        )

        self.assertEqual({"no_entry": 1}, summary["replay_resolution"]["outcome_counts"])
        self.assertEqual("no_entry", outcome["outcome"])
        self.assertEqual("open", outcome["status"])
        self.assertFalse(outcome["outcome_payload"]["entry_touched"])
        self.assertEqual("tier_c", outcome["eligibility"]["tier"])
        self.assertFalse(outcome["eligibility"]["eligible_for_tuning"])
        self.assertIn("unresolved_open_outcome", outcome["eligibility"]["rejection_reasons"])

    def test_replay_resolution_expires_no_entry_after_plan_horizon(self) -> None:
        outcome, summary = self._run_replay_resolution_case(
            intraday_bars=[
                (timedelta(minutes=1), 99.5, 96.0, 98.0),
                (timedelta(days=5), 99.5, 96.0, 98.0),
            ],
            plan_kwargs={"holding_period_days": 1, "horizon": StrategyHorizon.ONE_DAY},
        )

        self.assertEqual({"expired": 1}, summary["replay_resolution"]["outcome_counts"])
        self.assertEqual("expired", outcome["outcome"])
        self.assertEqual("resolved", outcome["status"])
        self.assertIn("Horizon elapsed", outcome["outcome_payload"]["notes"])
        self.assertEqual("tier_a", outcome["eligibility"]["tier"])
        self.assertTrue(outcome["eligibility"]["eligible_for_tuning"])

    def test_historical_replay_run_resolves_generated_plans_into_separate_replay_outcomes(self) -> None:
        session = create_session()
        try:
            market_repository = HistoricalMarketDataRepository(session)
            historical_replay = HistoricalReplayService(
                historical_replays=HistoricalReplayRepository(session),
                jobs=JobRepository(session),
                runs=RunRepository(session),
                historical_market_data=HistoricalMarketDataService(
                    market_repository,
                    provider=StubHistoricalBarProvider(),
                ),
            )
            replay_as_of = datetime(2024, 2, 5, 23, 59, 59, tzinfo=timezone.utc)
            resolution_end = replay_as_of + timedelta(days=5)
            for bar_time, high, low, close in [
                (replay_as_of + timedelta(minutes=1), 106.0, 99.0, 105.5),
                (resolution_end, 106.0, 100.0, 105.0),
            ]:
                market_repository.upsert_bar(
                    HistoricalMarketBar(
                        ticker="AAPL",
                        timeframe="1m",
                        bar_time=bar_time,
                        available_at=bar_time,
                        open_price=100.0,
                        high_price=high,
                        low_price=low,
                        close_price=close,
                        volume=1000,
                        source="fixture",
                    )
                )
            for day_offset in range(0, 6):
                day = replay_as_of + timedelta(days=day_offset)
                market_repository.upsert_bar(
                    HistoricalMarketBar(
                        ticker="AAPL",
                        timeframe="1d",
                        bar_time=day,
                        available_at=day.replace(hour=23, minute=59, second=59),
                        open_price=100.0,
                        high_price=106.0,
                        low_price=99.0,
                        close_price=105.0,
                        volume=1000,
                        source="fixture",
                    )
                )
            batch = historical_replay.create_batch(
                name="Replay resolution",
                mode="research",
                tickers=["AAPL"],
                as_of_start=datetime(2024, 2, 5, tzinfo=timezone.utc),
                as_of_end=replay_as_of,
            )
            historical_replay.enqueue_batch(batch.id or 0)
            execution = JobExecutionService(
                jobs=JobRepository(session),
                runs=RunRepository(session),
                historical_replay=historical_replay,
                watchlist_orchestration=PersistingReplayOrchestration(session),
            )
            claimed = RunRepository(session).claim_next_queued_run(worker_id="worker-test")
            assert claimed is not None

            final_run, _ = execution.execute_claimed_run(claimed, worker_id="worker-test")

            self.assertEqual(RunStatus.COMPLETED, final_run.status)
            summary = json.loads(final_run.summary_json or "{}")
            self.assertEqual("plans_resolved", summary["pipeline_stage"])
            self.assertEqual(1, summary["replay_resolution"]["stored_outcome_count"])
            self.assertEqual({"intraday": 1}, summary["replay_resolution"]["source_counts"])
            slice_row = HistoricalReplayRepository(session).list_slices(batch.id or 0)[0]
            replay_outcomes = ReplayPlanOutcomeRepository(session).list_for_slice(slice_row.id or 0)
            self.assertEqual(1, len(replay_outcomes))
            self.assertEqual("win", replay_outcomes[0]["outcome"])
            self.assertEqual("resolved", replay_outcomes[0]["status"])
            self.assertEqual("intraday", replay_outcomes[0]["resolution_source"])
        finally:
            session.close()

    def test_enqueue_and_execute_single_slice_run_with_market_data_coverage(self) -> None:
        session = create_session()
        try:
            historical_replay = HistoricalReplayService(
                historical_replays=HistoricalReplayRepository(session),
                jobs=JobRepository(session),
                runs=RunRepository(session),
                historical_market_data=HistoricalMarketDataService(
                    HistoricalMarketDataRepository(session),
                    provider=StubHistoricalBarProvider(),
                ),
                historical_news=HistoricalNewsRepository(session),
                context_snapshots=ContextSnapshotRepository(session),
                fundamental_snapshots=FundamentalAnalysisSnapshotRepository(session),
            )
            replay_as_of = datetime(2024, 2, 5, 23, 59, 59, tzinfo=timezone.utc)
            market_repository = HistoricalMarketDataRepository(session)
            for ticker, close in [("AAPL", 101.0), ("MSFT", 205.0)]:
                market_repository.upsert_bar(
                    HistoricalMarketBar(
                        ticker=ticker,
                        timeframe="1d",
                        bar_time=datetime(2024, 2, 5, tzinfo=timezone.utc),
                        available_at=replay_as_of,
                        open_price=close - 1.0,
                        high_price=close + 1.0,
                        low_price=close - 2.0,
                        close_price=close,
                        volume=1000,
                        source="fixture",
                    )
                )
            HistoricalNewsRepository(session).save_news(
                "AAPL",
                "fixture",
                [
                    NewsArticle(
                        title="Replay-safe news",
                        summary="summary",
                        publisher="Reuters",
                        link="aapl-news",
                        published_at=replay_as_of - timedelta(hours=2),
                        available_at=replay_as_of - timedelta(hours=1),
                    ),
                    NewsArticle(
                        title="Future-available news",
                        summary="summary",
                        publisher="Reuters",
                        link="aapl-future-news",
                        published_at=replay_as_of - timedelta(hours=2),
                        available_at=replay_as_of + timedelta(minutes=1),
                    ),
                ],
            )
            context_repo = ContextSnapshotRepository(session)
            aapl_industry_key = context_repo.taxonomy_service.get_industry_profile("AAPL")["subject_key"]
            context_repo.create_macro_context_snapshot(
                MacroContextSnapshot(
                    computed_at=replay_as_of - timedelta(hours=3),
                    summary_text="Macro backdrop",
                    status="ok",
                )
            )
            context_repo.create_industry_context_snapshot(
                IndustryContextSnapshot(
                    industry_key=aapl_industry_key,
                    industry_label="AAPL industry",
                    computed_at=replay_as_of - timedelta(hours=2),
                    summary_text="Industry backdrop",
                    status="ok",
                    direction="positive",
                )
            )
            FundamentalAnalysisSnapshotRepository(session).create_snapshot(
                ticker="AAPL",
                as_of=replay_as_of - timedelta(days=1),
                source_set=["fixture"],
                coverage_status="ok",
                freshness_status="fresh",
                payload={"summary": "fundamentals"},
                warnings=[],
                missing_inputs=[],
            )
            batch = historical_replay.create_batch(
                name="Replay single day",
                mode="research",
                tickers=["AAPL", "MSFT"],
                entry_timing="next_close",
                as_of_start=datetime(2024, 2, 5, tzinfo=timezone.utc),
                as_of_end=replay_as_of,
            )
            queued_runs = historical_replay.enqueue_batch(batch.id or 0)
            self.assertEqual(1, len(queued_runs))
            queued_run = queued_runs[0]
            self.assertEqual(JobType.HISTORICAL_REPLAY, queued_run.job_type)

            execution = JobExecutionService(
                jobs=JobRepository(session),
                runs=RunRepository(session),
                historical_replay=historical_replay,
            )
            claimed = RunRepository(session).claim_next_queued_run(worker_id="worker-test")
            assert claimed is not None
            final_run, _ = execution.execute_claimed_run(claimed, worker_id="worker-test")
            self.assertEqual(RunStatus.COMPLETED, final_run.status)
            summary = json.loads(final_run.summary_json or "{}")
            self.assertEqual(batch.id, summary["replay_batch_id"])
            self.assertEqual("research", summary["mode"])
            self.assertEqual("next_close", summary["entry_timing"])
            self.assertEqual(1.0, summary["coverage_ratio"])

            repository = HistoricalReplayRepository(session)
            refreshed_batch = repository.get_batch(batch.id or 0)
            self.assertEqual("completed", refreshed_batch.status)
            slice_row = repository.list_slices(batch.id or 0)[0]
            self.assertEqual("completed", slice_row.status)
            output_summary = json.loads(slice_row.output_summary_json)
            self.assertEqual("Historical replay market-data input assembly completed.", output_summary["message"])
            self.assertEqual("market_inputs_prepared", output_summary["pipeline_stage"])
            input_summary = json.loads(slice_row.input_summary_json)
            self.assertEqual(2, input_summary["market_input"]["covered_ticker_count"])
            replay_coverage = input_summary["replay_coverage_report"]
            self.assertEqual(1, replay_coverage["news_coverage"]["article_count_by_ticker"]["AAPL"])
            self.assertEqual(0, replay_coverage["news_coverage"]["article_count_by_ticker"]["MSFT"])
            self.assertTrue(replay_coverage["context_coverage"]["macro"]["available"])
            self.assertEqual(1, replay_coverage["context_coverage"]["industry_counts"]["available"])
            self.assertEqual(1, replay_coverage["fundamental_coverage"]["covered_ticker_count"])
            self.assertTrue(replay_coverage["fundamental_coverage"]["by_ticker"]["AAPL"]["available"])
            self.assertFalse(replay_coverage["fundamental_coverage"]["by_ticker"]["MSFT"]["available"])
            self.assertEqual("market_inputs_prepared", input_summary["pipeline_stage"])
        finally:
            session.close()
