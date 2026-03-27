import json
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from trade_proposer_app.domain.enums import JobType, RunStatus, StrategyHorizon
from trade_proposer_app.domain.models import RecommendationPlan, RecommendationPlanOutcome
from trade_proposer_app.persistence.models import Base
from trade_proposer_app.repositories.jobs import JobRepository
from trade_proposer_app.repositories.recommendation_outcomes import RecommendationOutcomeRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.repositories.runs import RunRepository
from trade_proposer_app.services.job_execution import JobExecutionService
from trade_proposer_app.services.optimizations import WeightOptimizationError, WeightOptimizationService
from trade_proposer_app.services.proposals import ProposalService


def create_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


class WeightOptimizationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(bind=self.engine)
        self.session = Session(bind=self.engine)
        self.jobs = JobRepository(self.session)
        self.runs = RunRepository(self.session)
        self.plan_repository = RecommendationPlanRepository(self.session)
        self.outcome_repository = RecommendationOutcomeRepository(self.session)
        self.job = self.jobs.create("Optimization Job", [], None, job_type=JobType.WEIGHT_OPTIMIZATION)

    def tearDown(self) -> None:
        self.session.close()

    def _add_plan_outcome(self, outcome: str, *, action: str = "long") -> int:
        run = self.runs.create(self.job.id or 0, RunStatus.COMPLETED.value)
        plan = self.plan_repository.create_plan(
            RecommendationPlan(
                ticker="AAPL",
                horizon=StrategyHorizon.ONE_WEEK,
                action=action,
                status="ok",
                confidence_percent=70.0,
                entry_price_low=100.0,
                entry_price_high=101.0,
                stop_loss=95.0,
                take_profit=110.0,
                holding_period_days=5,
                risk_reward_ratio=1.8,
                thesis_summary="test thesis",
                rationale_summary="test rationale",
                run_id=run.id,
                job_id=self.job.id,
            )
        )
        stored = self.outcome_repository.upsert_outcome(
            RecommendationPlanOutcome(
                recommendation_plan_id=plan.id or 0,
                ticker="AAPL",
                action=action,
                outcome=outcome,
                status="resolved" if outcome in {"win", "loss", "no_action", "watchlist"} else "open",
                confidence_bucket="65_to_79",
                setup_family="continuation",
                run_id=run.id,
            )
        )
        return stored.id or 0

    def _create_weights_file(self, temp_dir: Path, overrides: dict | None = None) -> Path:
        weights_path = temp_dir / "weights.json"
        weights_path.parent.mkdir(parents=True, exist_ok=True)
        content = overrides or {
            "confidence": {
                "momentum_medium": 1.0,
                "atr_penalty": -1.0,
            },
            "aggregators": {
                "direction": {"short_momentum": 1.0, "sentiment_bias": 1.0},
                "risk": {"atr": 1.0, "sentiment_volatility": 1.0},
                "entry": {"short_trend": 1.0, "volatility": -0.5},
            },
        }
        weights_path.write_text(json.dumps(content, indent=2))
        return weights_path

    def test_count_resolved_trades_reports_win_and_loss_totals(self) -> None:
        self._add_plan_outcome("win")
        self._add_plan_outcome("loss")
        self._add_plan_outcome("no_action", action="no_action")
        self._add_plan_outcome("watchlist", action="watchlist")
        with tempfile.TemporaryDirectory() as temp_dir:
            weights_path = self._create_weights_file(Path(temp_dir))
            service = WeightOptimizationService(
                session=self.session,
                minimum_resolved_trades=1,
                weights_path=weights_path,
            )
            win_count, loss_count, resolved_count = service.count_resolved_trades()
        self.assertEqual(win_count, 1)
        self.assertEqual(loss_count, 1)
        self.assertEqual(resolved_count, 2)

    def test_execute_raises_when_not_enough_resolved_trades(self) -> None:
        self._add_plan_outcome("win")
        with tempfile.TemporaryDirectory() as temp_dir:
            weights_path = self._create_weights_file(Path(temp_dir))
            service = WeightOptimizationService(
                session=self.session,
                minimum_resolved_trades=2,
                weights_path=weights_path,
            )
            with self.assertRaises(WeightOptimizationError) as context:
                service.execute()
        self.assertIn("minimum is 2", str(context.exception))

    def test_execute_adjusts_weights_when_wins_outnumber_losses(self) -> None:
        self._add_plan_outcome("win")
        self._add_plan_outcome("win")
        self._add_plan_outcome("loss")
        with tempfile.TemporaryDirectory() as temp_dir:
            weights_path = self._create_weights_file(Path(temp_dir))
            service = WeightOptimizationService(
                session=self.session,
                minimum_resolved_trades=3,
                weights_path=weights_path,
            )
            summary, artifact = service.execute()
            new_weights = json.loads(weights_path.read_text())
        self.assertEqual(summary["resolved_recommendation_plan_outcomes"], 3)
        self.assertEqual(summary["minimum_resolved_recommendation_plan_outcomes"], 3)
        self.assertEqual(summary["win_recommendation_plan_outcomes"], 2)
        self.assertEqual(summary["loss_recommendation_plan_outcomes"], 1)
        self.assertTrue(summary["weights_changed"])
        self.assertGreater(new_weights["confidence"]["momentum_medium"], 1.0)
        self.assertGreater(new_weights["aggregators"]["direction"]["short_momentum"], 1.0)
        self.assertEqual(new_weights["aggregators"]["risk"]["atr"], 1.0)
        self.assertEqual(artifact["weights_path"], str(weights_path))
        self.assertIsNotNone(artifact["backup"])
        self.assertTrue(artifact["rollback_available"])
        self.assertIn("before", artifact)
        self.assertIn("after", artifact)

    def test_rollback_latest_backup_restores_prior_weights(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            weights_path = self._create_weights_file(Path(temp_dir))
            service = WeightOptimizationService(
                session=self.session,
                minimum_resolved_trades=1,
                weights_path=weights_path,
            )
            backup = service.create_backup()
            self.assertIsNotNone(backup)
            weights_path.write_text(json.dumps({"confidence": {"momentum_medium": 5.0}}))
            rollback = service.rollback_latest_backup()
            restored_confidence = json.loads(weights_path.read_text())["confidence"]["momentum_medium"]
        self.assertEqual(rollback["status"], "rolled_back")
        self.assertEqual(restored_confidence, 1.0)
        self.assertEqual(rollback["before"]["exists"], True)
        self.assertEqual(rollback["after"]["exists"], True)

    def test_job_execution_uses_internal_data_for_optimization_runs(self) -> None:
        self._add_plan_outcome("win")
        self._add_plan_outcome("loss")
        self._add_plan_outcome("win")
        with tempfile.TemporaryDirectory() as temp_dir:
            weights_path = self._create_weights_file(Path(temp_dir))
            service = JobExecutionService(
                jobs=self.jobs,
                runs=self.runs,
                proposals=ProposalService(),
                optimizations=WeightOptimizationService(
                    session=self.session,
                    minimum_resolved_trades=3,
                    weights_path=weights_path,
                ),
            )
            queued_run = service.enqueue_job(self.job.id or 0)
            processed_run, recommendations = service.process_next_queued_run()
        self.assertIsNotNone(processed_run)
        self.assertEqual(processed_run.id, queued_run.id)
        self.assertEqual(processed_run.status, "completed")
        self.assertEqual(recommendations, [])
        stored_run = self.runs.get_run(processed_run.id or 0)
        summary = json.loads(stored_run.summary_json or "{}")
        artifact = json.loads(stored_run.artifact_json or "{}")
        self.assertEqual(summary.get("resolved_recommendation_plan_outcomes"), 3)
        self.assertTrue(summary.get("weights_changed"))
        self.assertEqual(artifact.get("weights_path"), str(weights_path))
        self.assertTrue(artifact.get("rollback_available"))


if __name__ == "__main__":
    unittest.main()
