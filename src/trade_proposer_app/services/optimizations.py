import hashlib
import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from trade_proposer_app.config import settings


class WeightOptimizationError(Exception):
    pass


class WeightOptimizationService:
    def __init__(self, minimum_resolved_trades: int = 50) -> None:
        self.minimum_resolved_trades = minimum_resolved_trades

    @staticmethod
    def get_prototype_optimization_script_path() -> Path:
        return (
            Path(settings.prototype_repo_path)
            / ".pi"
            / "skills"
            / "trade-proposer"
            / "scripts"
            / "optimize_weights.py"
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

    @staticmethod
    def get_prototype_weights_path() -> Path:
        return (
            Path(settings.prototype_repo_path)
            / ".pi"
            / "skills"
            / "trade-proposer"
            / "data"
            / "weights.json"
        )

    @classmethod
    def get_prototype_weights_backup_dir(cls) -> Path:
        return cls.get_prototype_weights_path().parent / "weight_backups"

    def execute(self) -> tuple[dict[str, object], dict[str, object]]:
        script_path = self.get_prototype_optimization_script_path()
        if not script_path.exists():
            raise WeightOptimizationError(f"prototype optimization script not found: {script_path}")

        resolved_trade_count = self.count_resolved_trades()
        if resolved_trade_count < self.minimum_resolved_trades:
            raise WeightOptimizationError(
                "weight optimization skipped: only "
                f"{resolved_trade_count} resolved trades available, minimum is {self.minimum_resolved_trades}"
            )

        weights_path = self.get_prototype_weights_path()
        before_fingerprint = self._fingerprint_file(weights_path)
        backup_metadata = self.create_backup(weights_path)

        result = subprocess.run(
            [settings.prototype_python_executable, str(script_path)],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=settings.prototype_repo_path,
        )
        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        combined_output = stdout + (("\n" + stderr) if stderr else "")
        if result.returncode != 0:
            restored = None
            if backup_metadata is not None:
                restored = self.restore_backup(Path(str(backup_metadata["path"])))
            restore_note = ""
            if restored is not None:
                restore_note = f"; weights restored from backup {restored['restored_from']}"
            raise WeightOptimizationError(
                (combined_output.strip() or f"prototype optimization exited with code {result.returncode}") + restore_note
            )

        after_fingerprint = self._fingerprint_file(weights_path)
        weights_changed = before_fingerprint.get("sha256") != after_fingerprint.get("sha256")

        summary = {
            "status": "completed",
            "resolved_trade_count": resolved_trade_count,
            "minimum_resolved_trades": self.minimum_resolved_trades,
            "weights_changed": weights_changed,
            "stdout": stdout,
            "stderr": stderr,
        }
        artifact = {
            "weights_path": str(weights_path),
            "backup": backup_metadata,
            "rollback_available": backup_metadata is not None,
            "before": before_fingerprint,
            "after": after_fingerprint,
        }
        return summary, artifact

    def count_resolved_trades(self) -> int:
        trade_log_path = self.get_prototype_trade_log_path()
        if not trade_log_path.exists():
            return 0
        connection = sqlite3.connect(trade_log_path)
        try:
            row = connection.execute(
                "SELECT COUNT(*) FROM trades WHERE UPPER(COALESCE(status, '')) IN ('WIN', 'LOSS')"
            ).fetchone()
            return int(row[0]) if row is not None else 0
        finally:
            connection.close()

    def describe_state(self) -> dict[str, object]:
        weights_path = self.get_prototype_weights_path()
        backups = self.list_backups(limit=10)
        return {
            "minimum_resolved_trades": self.minimum_resolved_trades,
            "weights_path": str(weights_path),
            "weights": self._fingerprint_file(weights_path),
            "backup_dir": str(self.get_prototype_weights_backup_dir()),
            "backup_count": len(self.list_backups()),
            "latest_backup": backups[0] if backups else None,
            "recent_backups": backups,
        }

    def create_backup(self, path: Path | None = None) -> dict[str, object] | None:
        weights_path = path or self.get_prototype_weights_path()
        if not weights_path.exists():
            return None
        backup_dir = self.get_prototype_weights_backup_dir()
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
        backup_dir = self.get_prototype_weights_backup_dir()
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
        weights_path = self.get_prototype_weights_path()
        weights_path.parent.mkdir(parents=True, exist_ok=True)
        before = self._fingerprint_file(weights_path)
        shutil.copy2(backup_path, weights_path)
        after = self._fingerprint_file(weights_path)
        return {
            "status": "rolled_back",
            "restored_from": str(backup_path),
            "weights_path": str(weights_path),
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
