import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from trade_proposer_app.config import settings
from trade_proposer_app.persistence.models import RecommendationOutcomeRecord, RecommendationPlanRecord


class WeightOptimizationError(Exception):
    pass


class WeightOptimizationService:
    _momentum_adjustment_step = 0.1
    _risk_adjustment_step = 0.1

    def __init__(self, session: Session, minimum_resolved_trades: int = 50, weights_path: Path | None = None) -> None:
        self.session = session
        self.minimum_resolved_trades = minimum_resolved_trades
        self._weights_path = weights_path if weights_path is not None else self._default_weights_path()

    @property
    def weights_path(self) -> Path:
        return self._weights_path

    def get_backup_dir(self) -> Path:
        return self.weights_path.parent / "weight_backups"

    @staticmethod
    def _app_weights_path() -> Path:
        configured_path = settings.weights_file_path.strip()
        if configured_path:
            return Path(configured_path)
        return Path(__file__).resolve().parents[1] / "data" / "weights.json"

    @classmethod
    def _default_weights_path(cls) -> Path:
        return cls._app_weights_path()

    def execute(self) -> tuple[dict[str, object], dict[str, object]]:
        win_count, loss_count, resolved_count = self.count_resolved_trades()
        if resolved_count < self.minimum_resolved_trades:
            raise WeightOptimizationError(
                "weight optimization skipped: only "
                f"{resolved_count} resolved recommendation-plan outcomes available, minimum is {self.minimum_resolved_trades}"
            )

        weights_path = self.weights_path
        before_fingerprint = self._fingerprint_file(weights_path)
        backup_metadata = self.create_backup(weights_path)
        weights = self._load_weights(weights_path)
        adjusted_weights, delta_ratio, momentum_multiplier, risk_multiplier = self._adjust_weights(
            weights, win_count, loss_count, resolved_count
        )

        try:
            self._write_weights(adjusted_weights)
        except Exception as exc:
            if backup_metadata is not None:
                self.restore_backup(Path(str(backup_metadata["path"])))
            raise WeightOptimizationError(f"failed to write updated weights: {exc}") from exc

        after_fingerprint = self._fingerprint_file(weights_path)
        weights_changed = before_fingerprint.get("sha256") != after_fingerprint.get("sha256")

        summary = {
            "status": "completed",
            "resolved_recommendation_plan_outcomes": resolved_count,
            "minimum_resolved_recommendation_plan_outcomes": self.minimum_resolved_trades,
            "win_recommendation_plan_outcomes": win_count,
            "loss_recommendation_plan_outcomes": loss_count,
            "delta_ratio": delta_ratio,
            "momentum_multiplier": momentum_multiplier,
            "risk_multiplier": risk_multiplier,
            "weights_changed": weights_changed,
        }
        artifact = {
            "weights_path": str(weights_path),
            "backup": backup_metadata,
            "rollback_available": backup_metadata is not None,
            "before": before_fingerprint,
            "after": after_fingerprint,
        }
        return summary, artifact

    def count_resolved_trades(self) -> tuple[int, int, int]:
        query = (
            select(RecommendationOutcomeRecord.outcome, func.count())
            .join(
                RecommendationPlanRecord,
                RecommendationOutcomeRecord.recommendation_plan_id == RecommendationPlanRecord.id,
            )
            .where(RecommendationOutcomeRecord.outcome.in_({"win", "loss"}))
            .where(RecommendationPlanRecord.action.in_({"long", "short"}))
            .group_by(RecommendationOutcomeRecord.outcome)
        )
        results = {state: count for state, count in self.session.execute(query)}
        win_count = int(results.get("win", 0))
        loss_count = int(results.get("loss", 0))
        return win_count, loss_count, win_count + loss_count

    def describe_state(self) -> dict[str, object]:
        win_count, loss_count, resolved_count = self.count_resolved_trades()
        delta_ratio = (win_count - loss_count) / resolved_count if resolved_count else 0.0
        backups = self.list_backups(limit=10)
        return {
            "minimum_resolved_trades": self.minimum_resolved_trades,
            "resolved_recommendation_plan_outcomes": resolved_count,
            "win_recommendation_plan_outcomes": win_count,
            "loss_recommendation_plan_outcomes": loss_count,
            "delta_ratio": delta_ratio,
            "weights_path": str(self.weights_path),
            "weights": self._fingerprint_file(self.weights_path),
            "backup_dir": str(self.get_backup_dir()),
            "backup_count": len(self.list_backups()),
            "latest_backup": backups[0] if backups else None,
            "recent_backups": backups,
        }

    def create_backup(self, path: Path | None = None) -> dict[str, object] | None:
        weights_path = path or self.weights_path
        if not weights_path.exists():
            return None
        backup_dir = self.get_backup_dir()
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup_path = backup_dir / f"weights.{timestamp}.json.bak"
        shutil.copy2(weights_path, backup_path)
        return {
            "path": str(backup_path),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "fingerprint": self._fingerprint_file(backup_path),
        }

    def list_backups(self, limit: int | None = None) -> list[dict[str, object]]:
        backup_dir = self.get_backup_dir()
        if not backup_dir.exists():
            return []
        backups = sorted(
            (path for path in backup_dir.glob("weights.*.json.bak") if path.is_file()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if limit is not None:
            backups = backups[:limit]
        return [self._backup_metadata(path) for path in backups]

    def rollback_latest_backup(self) -> dict[str, object]:
        backups = self.list_backups(limit=1)
        if not backups:
            raise WeightOptimizationError("no weight backups available for rollback")
        return self.restore_backup(Path(str(backups[0]["path"])))

    def restore_backup(self, backup_path: Path | str) -> dict[str, object]:
        backup_path = Path(backup_path)
        if not backup_path.exists():
            raise WeightOptimizationError(f"backup not found: {backup_path}")
        before = self._fingerprint_file(self.weights_path)
        self.weights_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup_path, self.weights_path)
        after = self._fingerprint_file(self.weights_path)
        return {
            "status": "rolled_back",
            "restored_from": str(backup_path),
            "weights_path": str(self.weights_path),
            "before": before,
            "after": after,
        }

    @staticmethod
    def _backup_metadata(path: Path) -> dict[str, object]:
        return {
            "path": str(path),
            "created_at": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
            "fingerprint": WeightOptimizationService._fingerprint_file(path),
        }

    @staticmethod
    def _fingerprint_file(path: Path) -> dict[str, object]:
        if not path.exists():
            return {
                "exists": False,
                "sha256": None,
                "size_bytes": None,
                "modified_at": None,
            }
        sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        stat = path.stat()
        return {
            "exists": True,
            "sha256": sha256,
            "size_bytes": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        }

    def _load_weights(self, path: Path) -> dict[str, object]:
        if not path.exists():
            raise WeightOptimizationError(f"weights file not found: {path}")
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise WeightOptimizationError(f"unable to parse weights file: {exc}") from exc

    def _write_weights(self, weights: dict[str, object]) -> None:
        self.weights_path.parent.mkdir(parents=True, exist_ok=True)
        self.weights_path.write_text(json.dumps(weights, indent=2) + "\n")

    def _adjust_weights(
        self,
        weights: dict[str, object],
        win_count: int,
        loss_count: int,
        resolved_count: int,
    ) -> tuple[dict[str, object], float, float, float]:
        if resolved_count == 0:
            return weights, 0.0, 1.0, 1.0
        delta_ratio = (win_count - loss_count) / resolved_count
        momentum_multiplier = 1.0 + max(0.0, delta_ratio) * self._momentum_adjustment_step
        risk_multiplier = 1.0 + max(0.0, -delta_ratio) * self._risk_adjustment_step

        confidence = weights.setdefault("confidence", {})
        momentum_targets = [
            "momentum_medium",
            "news_coverage",
            "context_coverage",
            "polarity_trend",
            "sentiment",
            "enhanced_sentiment",
            "price_above_sma50",
            "price_above_sma200",
        ]
        for key in momentum_targets:
            if key in confidence:
                confidence[key] = self._scale_value(confidence[key], momentum_multiplier)

        risk_targets = ["atr_penalty", "sentiment_volatility", "rsi_penalty"]
        for key in risk_targets:
            if key in confidence:
                confidence[key] = self._scale_value(confidence[key], risk_multiplier)

        aggregators = weights.setdefault("aggregators", {})
        direction = aggregators.setdefault("direction", {})
        risk = aggregators.setdefault("risk", {})
        entry = aggregators.setdefault("entry", {})

        direction_targets = ["short_momentum", "medium_momentum", "long_momentum", "sentiment_bias"]
        for key in direction_targets:
            if key in direction:
                direction[key] = self._scale_value(direction[key], momentum_multiplier)

        entry_targets = ["short_trend", "medium_trend", "long_trend", "volatility"]
        for key in entry_targets:
            if key in entry:
                entry[key] = self._scale_value(entry[key], momentum_multiplier)

        risk_targets = ["atr", "momentum", "sentiment_volatility"]
        for key in risk_targets:
            if key in risk:
                risk[key] = self._scale_value(risk[key], risk_multiplier)

        return weights, delta_ratio, momentum_multiplier, risk_multiplier

    @staticmethod
    def _scale_value(value: object, multiplier: float) -> object:
        if not isinstance(value, (int, float)):
            return value
        return float(value) * multiplier
