import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from trade_proposer_app.config import settings
from trade_proposer_app.domain.enums import RecommendationState
from trade_proposer_app.domain.models import EvaluationRunResult
from trade_proposer_app.persistence.models import RecommendationRecord


class RecommendationEvaluationError(Exception):
    pass


class RecommendationEvaluationService:
    def __init__(self, session: Session) -> None:
        self.session = session

    @staticmethod
    def get_prototype_evaluation_script_path() -> Path:
        return (
            Path(settings.prototype_repo_path)
            / ".pi"
            / "skills"
            / "trade-proposer"
            / "scripts"
            / "evaluate_trades.py"
        )

    @staticmethod
    def get_prototype_trade_log_path() -> Path:
        return (
            Path(settings.prototype_repo_path)
            / ".pi"
            / "skills"
            / "trade-proposer"
            / "data"
            / "trade_log.db"
        )

    def run_evaluation(self, recommendation_ids: list[int] | None = None) -> EvaluationRunResult:
        script_path = self.get_prototype_evaluation_script_path()
        if not script_path.exists():
            raise RecommendationEvaluationError(f"prototype evaluation script not found: {script_path}")

        result = subprocess.run(
            [settings.prototype_python_executable, str(script_path)],
            capture_output=True,
            text=True,
            timeout=180,
            cwd=settings.prototype_repo_path,
        )
        output = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
        if result.returncode != 0:
            raise RecommendationEvaluationError(output.strip() or f"prototype evaluation exited with code {result.returncode}")

        synced_recommendations = self.sync_recommendation_states_from_trade_log(recommendation_ids=recommendation_ids)
        recommendations = self._list_recommendations(recommendation_ids=recommendation_ids)
        return EvaluationRunResult(
            evaluated_trade_log_entries=self._count_trade_log_entries(),
            synced_recommendations=synced_recommendations,
            pending_recommendations=sum(1 for recommendation in recommendations if recommendation.evaluation_state == RecommendationState.PENDING.value),
            win_recommendations=sum(1 for recommendation in recommendations if recommendation.evaluation_state == RecommendationState.WIN.value),
            loss_recommendations=sum(1 for recommendation in recommendations if recommendation.evaluation_state == RecommendationState.LOSS.value),
            output=output.strip(),
        )

    def sync_recommendation_states_from_trade_log(self, recommendation_ids: list[int] | None = None) -> int:
        trade_log_path = self.get_prototype_trade_log_path()
        if not trade_log_path.exists():
            return 0

        connection = sqlite3.connect(trade_log_path)
        connection.row_factory = sqlite3.Row
        try:
            trade_rows = connection.execute(
                """
                SELECT ticker, direction, entry_price, stop_loss, take_profit, status, timestamp, close_timestamp
                FROM trades
                ORDER BY timestamp DESC, id DESC
                """
            ).fetchall()
        finally:
            connection.close()

        recommendations = self._list_recommendations(recommendation_ids=recommendation_ids)
        synced = 0
        for recommendation in recommendations:
            matched_trade = self._match_trade(recommendation, trade_rows)
            if matched_trade is None:
                continue
            next_state = str(matched_trade["status"] or RecommendationState.PENDING.value)
            next_evaluated_at = self._parse_trade_timestamp(
                str(matched_trade["close_timestamp"]) if matched_trade["close_timestamp"] else None
            )
            if recommendation.evaluation_state != next_state or recommendation.evaluated_at != next_evaluated_at:
                recommendation.evaluation_state = next_state
                recommendation.evaluated_at = next_evaluated_at
                synced += 1

        if synced > 0:
            self.session.commit()
        return synced

    def _list_recommendations(self, recommendation_ids: list[int] | None = None) -> list[RecommendationRecord]:
        query = select(RecommendationRecord)
        if recommendation_ids:
            query = query.where(RecommendationRecord.id.in_(recommendation_ids))
        return list(self.session.scalars(query).all())

    def _count_trade_log_entries(self) -> int:
        trade_log_path = self.get_prototype_trade_log_path()
        if not trade_log_path.exists():
            return 0
        connection = sqlite3.connect(trade_log_path)
        try:
            row = connection.execute("SELECT COUNT(*) FROM trades").fetchone()
            return int(row[0]) if row is not None else 0
        finally:
            connection.close()

    @classmethod
    def _match_trade(cls, recommendation: RecommendationRecord, trade_rows: list[sqlite3.Row]) -> sqlite3.Row | None:
        matches: list[sqlite3.Row] = []
        for trade in trade_rows:
            if str(trade["ticker"]).upper() != recommendation.ticker.upper():
                continue
            if str(trade["direction"]).upper() != recommendation.direction.upper():
                continue
            if not cls._close_enough(float(trade["entry_price"]), recommendation.entry_price):
                continue
            if not cls._close_enough(float(trade["stop_loss"]), recommendation.stop_loss):
                continue
            if not cls._close_enough(float(trade["take_profit"]), recommendation.take_profit):
                continue
            matches.append(trade)

        if not matches:
            return None

        recommendation_created_at = recommendation.created_at
        if recommendation_created_at.tzinfo is None:
            recommendation_created_at = recommendation_created_at.replace(tzinfo=timezone.utc)
        return min(
            matches,
            key=lambda trade: abs(
                (
                    recommendation_created_at
                    - (cls._parse_trade_timestamp(str(trade["timestamp"])) or recommendation_created_at)
                ).total_seconds()
            ),
        )

    @staticmethod
    def _close_enough(left: float, right: float, tolerance: float = 1e-6) -> bool:
        return abs(left - right) <= tolerance

    @staticmethod
    def _parse_trade_timestamp(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
