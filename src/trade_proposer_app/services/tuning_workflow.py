from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Mapping

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from trade_proposer_app.persistence.models import TuningExperimentRecord
from trade_proposer_app.utils.json_payloads import loads_json_object


OBJECTIVES = {
    "tier_a_win_rate",
    "expected_value",
    "average_5d_return",
    "loss_severity",
    "balanced_score",
}
PROMOTION_TARGETS = {"research_only", "paper_config", "live_guarded_config", "live_full_autonomy"}


def _json_dumps(payload: Mapping[str, Any]) -> str:
    return json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), default=str)


def _date_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class TuningWorkflowError(ValueError):
    pass


class TuningWorkflowService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_experiments(self, *, include_archived: bool = False, limit: int = 50) -> list[dict[str, object]]:
        query = select(TuningExperimentRecord).order_by(desc(TuningExperimentRecord.updated_at)).limit(limit)
        if not include_archived:
            query = query.where(TuningExperimentRecord.status != "archived")
        return [self.experiment_summary(row) for row in self.session.scalars(query).all()]

    def get_experiment(self, experiment_id: int) -> TuningExperimentRecord:
        record = self.session.get(TuningExperimentRecord, experiment_id)
        if record is None:
            raise TuningWorkflowError(f"tuning experiment {experiment_id} not found")
        return record

    def create_experiment(self, payload: Mapping[str, object]) -> dict[str, object]:
        normalized = self._normalize_payload(payload, partial=False)
        record = TuningExperimentRecord(
            name=str(normalized["name"]),
            notes=str(normalized.get("notes") or ""),
            hypothesis=str(normalized.get("hypothesis") or ""),
            universe_json=_json_dumps(normalized["universe"]),
            windows_json=_json_dumps(normalized["windows"]),
            discovery_settings_json=_json_dumps(normalized["discovery_settings"]),
            replay_settings_json=_json_dumps(normalized["replay_settings"]),
            objective=str(normalized["objective"]),
            baseline_json=_json_dumps(normalized["baseline"]),
            promotion_target=str(normalized["promotion_target"]),
            advanced_settings_json=_json_dumps(normalized["advanced_settings"]),
            metadata_json="{}",
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return self.experiment_detail(record)

    def update_experiment(self, experiment_id: int, payload: Mapping[str, object]) -> dict[str, object]:
        record = self.get_experiment(experiment_id)
        if record.status == "archived":
            raise TuningWorkflowError("archived experiments cannot be edited")
        current = self._record_payload(record)
        merged = {**current, **dict(payload)}
        normalized = self._normalize_payload(merged, partial=False)
        record.name = str(normalized["name"])
        record.notes = str(normalized.get("notes") or "")
        record.hypothesis = str(normalized.get("hypothesis") or "")
        record.universe_json = _json_dumps(normalized["universe"])
        record.windows_json = _json_dumps(normalized["windows"])
        record.discovery_settings_json = _json_dumps(normalized["discovery_settings"])
        record.replay_settings_json = _json_dumps(normalized["replay_settings"])
        record.objective = str(normalized["objective"])
        record.baseline_json = _json_dumps(normalized["baseline"])
        record.promotion_target = str(normalized["promotion_target"])
        record.advanced_settings_json = _json_dumps(normalized["advanced_settings"])
        self.session.commit()
        self.session.refresh(record)
        return self.experiment_detail(record)

    def archive_experiment(self, experiment_id: int) -> dict[str, object]:
        record = self.get_experiment(experiment_id)
        record.status = "archived"
        record.archived_at = datetime.now(timezone.utc)
        self.session.commit()
        self.session.refresh(record)
        return self.experiment_detail(record)

    def experiment_summary(self, record: TuningExperimentRecord) -> dict[str, object]:
        detail = self.experiment_detail(record)
        return {
            "id": detail["id"],
            "name": detail["name"],
            "status": detail["status"],
            "current_stage": detail["current_stage"],
            "next_action": detail["next_action"],
            "blockers": detail["blockers"],
            "objective": detail["objective"],
            "promotion_target": detail["promotion_target"],
            "created_at": detail["created_at"],
            "updated_at": detail["updated_at"],
        }

    def experiment_detail(self, record: TuningExperimentRecord) -> dict[str, object]:
        universe = loads_json_object(record.universe_json)
        windows = loads_json_object(record.windows_json)
        discovery_settings = loads_json_object(record.discovery_settings_json)
        replay_settings = loads_json_object(record.replay_settings_json)
        baseline = loads_json_object(record.baseline_json)
        advanced_settings = loads_json_object(record.advanced_settings_json)
        setup = self._setup_status(record, universe, windows, discovery_settings, replay_settings, baseline)
        lifecycle = self._lifecycle(record, setup)
        sections = self._sections(record, setup, lifecycle)
        return {
            "id": record.id,
            "name": record.name,
            "status": record.status,
            "notes": record.notes,
            "hypothesis": record.hypothesis,
            "universe": universe,
            "windows": windows,
            "discovery_settings": discovery_settings,
            "replay_settings": replay_settings,
            "objective": record.objective,
            "baseline": baseline,
            "promotion_target": record.promotion_target,
            "advanced_settings": advanced_settings,
            "setup_completeness": setup,
            "current_stage": lifecycle["current_stage"],
            "next_action": lifecycle["next_action"],
            "blockers": lifecycle["blockers"],
            "sections": sections,
            "computation_labels": {
                "discovery": "discovery-only evidence; not promotion evidence",
                "replay": "replay validation required before promotion",
                "holdout": "holdout/stability validation required for promotion confidence",
            },
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
            "archived_at": record.archived_at.isoformat() if record.archived_at else None,
        }

    def _normalize_payload(self, payload: Mapping[str, object], *, partial: bool) -> dict[str, object]:
        name = str(payload.get("name") or "").strip()
        if not partial and not name:
            raise TuningWorkflowError("experiment name is required")
        objective = str(payload.get("objective") or "balanced_score")
        if objective not in OBJECTIVES:
            raise TuningWorkflowError(f"unsupported objective: {objective}")
        promotion_target = str(payload.get("promotion_target") or "paper_config")
        if promotion_target not in PROMOTION_TARGETS:
            raise TuningWorkflowError(f"unsupported promotion target: {promotion_target}")
        universe = dict(payload.get("universe") or {})
        windows = dict(payload.get("windows") or {})
        discovery_settings = {"search_size": "small", "candidate_count": 25, **dict(payload.get("discovery_settings") or {})}
        replay_settings = {"max_candidates": 5, "max_concurrency": 1, "cache_only": True, **dict(payload.get("replay_settings") or {})}
        replay_settings["cache_only"] = True
        replay_settings["max_concurrency"] = max(1, min(1, int(replay_settings.get("max_concurrency") or 1)))
        replay_settings["max_candidates"] = max(1, min(10, int(replay_settings.get("max_candidates") or 5)))
        baseline = dict(payload.get("baseline") or {})
        advanced_settings = {
            "candidate_sources": ["manual_config", "risk_reward_geometry_variants", "strict_quality_gate_variants"],
            "data_quality_policy": "block_hard_gaps",
            "manual_review_required": True,
            **dict(payload.get("advanced_settings") or {}),
        }
        return {
            "name": name,
            "notes": str(payload.get("notes") or ""),
            "hypothesis": str(payload.get("hypothesis") or ""),
            "universe": universe,
            "windows": windows,
            "discovery_settings": discovery_settings,
            "replay_settings": replay_settings,
            "objective": objective,
            "baseline": baseline,
            "promotion_target": promotion_target,
            "advanced_settings": advanced_settings,
        }

    def _record_payload(self, record: TuningExperimentRecord) -> dict[str, object]:
        return {
            "name": record.name,
            "notes": record.notes,
            "hypothesis": record.hypothesis,
            "universe": loads_json_object(record.universe_json),
            "windows": loads_json_object(record.windows_json),
            "discovery_settings": loads_json_object(record.discovery_settings_json),
            "replay_settings": loads_json_object(record.replay_settings_json),
            "objective": record.objective,
            "baseline": loads_json_object(record.baseline_json),
            "promotion_target": record.promotion_target,
            "advanced_settings": loads_json_object(record.advanced_settings_json),
        }

    def _setup_status(
        self,
        record: TuningExperimentRecord,
        universe: Mapping[str, object],
        windows: Mapping[str, object],
        discovery_settings: Mapping[str, object],
        replay_settings: Mapping[str, object],
        baseline: Mapping[str, object],
    ) -> dict[str, object]:
        missing: list[str] = []
        warnings: list[str] = []
        if not record.name.strip():
            missing.append("experiment name")
        tickers = universe.get("tickers")
        if not universe.get("watchlist_id") and not universe.get("source_replay_batch_id") and not (isinstance(tickers, list) and tickers):
            missing.append("universe")
        for key in ("discovery_start", "discovery_end", "replay_start", "replay_end", "holdout_start", "holdout_end"):
            if not _date_string(windows.get(key)):
                missing.append(key.replace("_", " "))
        if not record.objective:
            missing.append("primary objective")
        if not baseline.get("source"):
            missing.append("baseline selection")
        if int(replay_settings.get("max_candidates") or 0) > 10:
            warnings.append("candidate replay limit should stay within 5–10 on this VPS")
        if windows.get("discovery_end") and windows.get("replay_start") and str(windows["discovery_end"]) > str(windows["replay_start"]):
            warnings.append("discovery window overlaps replay validation window")
        if windows.get("discovery_end") and windows.get("holdout_start") and str(windows["discovery_end"]) > str(windows["holdout_start"]):
            warnings.append("holdout overlaps discovery window")
        return {"complete": not missing, "missing_fields": missing, "warnings": warnings}

    def _lifecycle(self, record: TuningExperimentRecord, setup: Mapping[str, object]) -> dict[str, object]:
        if record.status == "archived":
            return {"current_stage": "archived", "next_action": "No action; experiment is archived.", "blockers": []}
        missing = list(setup.get("missing_fields") or [])
        if missing:
            return {
                "current_stage": "setup_incomplete",
                "next_action": "Complete required setup fields before running readiness or discovery.",
                "blockers": missing,
            }
        return {
            "current_stage": "readiness_needed",
            "next_action": "Run a cache-only evidence readiness audit before candidate discovery.",
            "blockers": [],
        }

    def _sections(
        self,
        record: TuningExperimentRecord,
        setup: Mapping[str, object],
        lifecycle: Mapping[str, object],
    ) -> dict[str, object]:
        setup_status = "complete" if setup.get("complete") else "blocked"
        return {
            "setup": {"status": setup_status, "warnings": setup.get("warnings", []), "blockers": setup.get("missing_fields", [])},
            "evidence_readiness": {"status": "not_run", "cache_only": True, "warnings": []},
            "candidate_pool": {"status": "empty", "candidates": [], "label": "discovery-only evidence"},
            "shortlist": {"status": "empty", "max_candidates": 5},
            "baseline_replay": {"status": "missing", "batch_id": None},
            "candidate_replay_validation": {"status": "blocked", "reason": "baseline and shortlist are required"},
            "stability_validation": {"status": "not_run", "label": "stability/overfit screen"},
            "promotion_proposal": {"status": "blocked", "reason": "replay and holdout validation are required"},
            "post_promotion_monitoring": {"status": "not_applicable"},
        }
