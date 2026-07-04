from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Mapping

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import PlanGenerationTuningConfigVersion, PlanGenerationTuningEvent
from trade_proposer_app.persistence.models import HistoricalMarketBarRecord, HistoricalReplayBatchRecord, HistoricalReplaySliceRecord, TuningExperimentRecord
from trade_proposer_app.repositories.plan_generation_tuning import PlanGenerationTuningRepository
from trade_proposer_app.services.input_access import stable_hash
from trade_proposer_app.services.plan_generation_tuning_parameters import PARAMETER_DEFAULTS, candidate_validation_depth, normalize_plan_generation_tuning_config
from trade_proposer_app.services.replay_validation_efficiency import ReplayValidationAggregateService
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
    def __init__(self, session: Session, *, historical_replay_service: object | None = None) -> None:
        self.session = session
        self.historical_replay_service = historical_replay_service

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

    def run_readiness_audit(self, experiment_id: int) -> dict[str, object]:
        record = self.get_experiment(experiment_id)
        universe = loads_json_object(record.universe_json)
        windows = loads_json_object(record.windows_json)
        tickers = self._experiment_tickers(universe)
        replay_start = _date_string(windows.get("replay_start"))
        replay_end = _date_string(windows.get("replay_end"))
        blockers: list[str] = []
        warnings: list[str] = []
        if not tickers:
            blockers.append("universe has no explicit tickers for readiness audit")
        if not replay_start or not replay_end:
            blockers.append("replay validation window is required")
        ticker_rows: list[dict[str, object]] = []
        repeated_gap_tickers: list[str] = []
        if not blockers:
            start_dt = datetime.fromisoformat(replay_start.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(replay_end.replace("Z", "+00:00"))
            expected_days = max(1, (end_dt.date() - start_dt.date()).days + 1)
            for ticker in tickers:
                count = int(self.session.scalar(select(func.count()).select_from(HistoricalMarketBarRecord).where(
                    HistoricalMarketBarRecord.ticker == ticker,
                    HistoricalMarketBarRecord.timeframe == "1d",
                    HistoricalMarketBarRecord.bar_time >= start_dt,
                    HistoricalMarketBarRecord.bar_time <= end_dt,
                )) or 0)
                coverage = round((count / expected_days) * 100.0, 2)
                row = {"ticker": ticker, "cached_bars": count, "expected_calendar_days": expected_days, "coverage_percent": coverage}
                ticker_rows.append(row)
                if coverage < 50.0:
                    repeated_gap_tickers.append(ticker)
            if repeated_gap_tickers:
                warnings.append("some tickers have low cached bar coverage and should be considered for watchlist pruning")
        audit = {
            "status": "blocked" if blockers else ("warning" if warnings else "ok"),
            "cache_only": True,
            "remote_fetch_used": False,
            "blockers": blockers,
            "warnings": warnings,
            "ticker_count": len(tickers),
            "tickers": ticker_rows,
            "repeated_gap_tickers": repeated_gap_tickers,
            "pruning_recommendations": [{"ticker": ticker, "reason": "low cached replay bar coverage"} for ticker in repeated_gap_tickers],
            "audited_at": datetime.now(timezone.utc).isoformat(),
        }
        metadata = loads_json_object(record.metadata_json)
        metadata["readiness_audit"] = audit
        record.metadata_json = _json_dumps(metadata)
        self.session.commit()
        self.session.refresh(record)
        return self.experiment_detail(record)

    def generate_candidate_pool(self, experiment_id: int) -> dict[str, object]:
        record = self.get_experiment(experiment_id)
        baseline_config = normalize_plan_generation_tuning_config({})
        variants: list[tuple[str, dict[str, float], list[str], str]] = []
        variants.append(("strict_actionability_floor", {"global.actionable_confidence_floor_percent": baseline_config["global.actionable_confidence_floor_percent"] + 5.0}, ["global.actionable_confidence_floor_percent"], "strict quality-gate variant"))
        variants.append(("wider_entry_band", {"global.entry_band_risk_fraction": baseline_config["global.entry_band_risk_fraction"] + 0.05}, ["global.entry_band_risk_fraction"], "risk/reward geometry variant"))
        variants.append(("tighter_breakout_stop", {"setup_family.breakout.stop_distance_multiplier": max(0.1, baseline_config["setup_family.breakout.stop_distance_multiplier"] - 0.1)}, ["setup_family.breakout.stop_distance_multiplier"], "risk/reward geometry variant"))
        variants.append(("larger_breakout_reward", {"setup_family.breakout.take_profit_distance_multiplier": baseline_config["setup_family.breakout.take_profit_distance_multiplier"] + 0.1}, ["setup_family.breakout.take_profit_distance_multiplier"], "risk/reward geometry variant"))
        candidates: list[dict[str, object]] = []
        seen_hashes: set[str] = set()
        for index, (label, overrides, changed_keys, source) in enumerate(variants, start=1):
            config = normalize_plan_generation_tuning_config({**baseline_config, **overrides})
            config_hash = stable_hash(config)
            if config_hash in seen_hashes:
                continue
            seen_hashes.add(config_hash)
            depth = candidate_validation_depth(changed_keys)
            candidates.append({
                "id": f"cand-{index}",
                "label": label,
                "source": source,
                "status": "discovered",
                "rank": index,
                "config": config,
                "config_hash": config_hash,
                "changed_keys": changed_keys,
                "validation_depth": depth["validation_depth"],
                "validation_depth_reason": depth["validation_depth_reason"],
                "promotion_capable": False,
                "computation_label": "discovery-only evidence; requires replay and holdout before promotion",
            })
        metadata = loads_json_object(record.metadata_json)
        metadata["candidate_pool"] = {"status": "generated", "candidates": candidates, "generated_at": datetime.now(timezone.utc).isoformat()}
        metadata.setdefault("shortlist", {"candidate_ids": []})
        record.metadata_json = _json_dumps(metadata)
        self.session.commit()
        self.session.refresh(record)
        return self.experiment_detail(record)

    def add_manual_candidate(self, experiment_id: int, *, label: str, config: Mapping[str, object]) -> dict[str, object]:
        record = self.get_experiment(experiment_id)
        normalized_config = normalize_plan_generation_tuning_config(dict(config))
        baseline = normalize_plan_generation_tuning_config({})
        changed_keys = [key for key, value in normalized_config.items() if value != baseline.get(key)]
        if not changed_keys:
            raise TuningWorkflowError("manual candidate must change at least one registered parameter")
        depth = candidate_validation_depth(changed_keys)
        if depth.get("unknown_keys"):
            raise TuningWorkflowError("manual candidate contains unknown parameter keys")
        metadata = loads_json_object(record.metadata_json)
        pool = metadata.setdefault("candidate_pool", {"status": "generated", "candidates": []})
        candidates = pool.setdefault("candidates", [])
        config_hash = stable_hash(normalized_config)
        if any(isinstance(item, dict) and item.get("config_hash") == config_hash for item in candidates):
            raise TuningWorkflowError("duplicate candidate config")
        candidate_id = f"manual-{len(candidates) + 1}"
        candidates.append({
            "id": candidate_id,
            "label": label or candidate_id,
            "source": "manual_config",
            "status": "discovered",
            "rank": len(candidates) + 1,
            "config": normalized_config,
            "config_hash": config_hash,
            "changed_keys": changed_keys,
            "validation_depth": depth["validation_depth"],
            "validation_depth_reason": depth["validation_depth_reason"],
            "promotion_capable": False,
            "computation_label": "manual discovery candidate; requires replay and holdout before promotion",
        })
        pool["status"] = "generated"
        pool["updated_at"] = datetime.now(timezone.utc).isoformat()
        record.metadata_json = _json_dumps(metadata)
        self.session.commit()
        self.session.refresh(record)
        return self.experiment_detail(record)

    def reject_candidate(self, experiment_id: int, candidate_id: str, *, reason: str = "operator rejected") -> dict[str, object]:
        record = self.get_experiment(experiment_id)
        metadata = loads_json_object(record.metadata_json)
        candidates = metadata.get("candidate_pool", {}).get("candidates", [])
        found = False
        for candidate in candidates:
            if isinstance(candidate, dict) and str(candidate.get("id")) == candidate_id:
                candidate["status"] = "rejected"
                candidate["rejection_reason"] = reason
                found = True
        if not found:
            raise TuningWorkflowError(f"candidate {candidate_id} not found")
        shortlist = metadata.get("shortlist", {})
        if isinstance(shortlist, dict):
            shortlist["candidate_ids"] = [item for item in shortlist.get("candidate_ids", []) if str(item) != candidate_id]
        record.metadata_json = _json_dumps(metadata)
        self.session.commit()
        self.session.refresh(record)
        return self.experiment_detail(record)

    def update_shortlist(self, experiment_id: int, candidate_ids: list[str]) -> dict[str, object]:
        record = self.get_experiment(experiment_id)
        replay_settings = loads_json_object(record.replay_settings_json)
        max_candidates = int(replay_settings.get("max_candidates") or 5)
        if len(candidate_ids) > max_candidates:
            raise TuningWorkflowError(f"shortlist cannot exceed {max_candidates} candidates")
        metadata = loads_json_object(record.metadata_json)
        candidates = {str(item.get("id")): item for item in loads_json_object(record.metadata_json).get("candidate_pool", {}).get("candidates", []) if isinstance(item, dict)}
        unknown = [candidate_id for candidate_id in candidate_ids if candidate_id not in candidates]
        if unknown:
            raise TuningWorkflowError(f"unknown candidate ids: {', '.join(unknown)}")
        metadata["shortlist"] = {"candidate_ids": candidate_ids, "updated_at": datetime.now(timezone.utc).isoformat()}
        for candidate in metadata.get("candidate_pool", {}).get("candidates", []):
            if isinstance(candidate, dict) and str(candidate.get("id")) in candidate_ids:
                candidate["status"] = "shortlisted"
        record.metadata_json = _json_dumps(metadata)
        self.session.commit()
        self.session.refresh(record)
        return self.experiment_detail(record)

    def create_baseline_replay_batch(self, experiment_id: int, *, enqueue: bool = True) -> dict[str, object]:
        replay_service = self._require_historical_replay_service()
        record = self.get_experiment(experiment_id)
        universe = loads_json_object(record.universe_json)
        windows = loads_json_object(record.windows_json)
        tickers = self._experiment_tickers(universe)
        if not tickers:
            raise TuningWorkflowError("explicit tickers are required to create a baseline replay")
        start_dt, end_dt = self._window_datetimes(windows, "replay")
        batch = replay_service.create_batch(
            name=f"tuning-exp-{record.id}-baseline-{stable_hash({'id': record.id, 'window': [start_dt.isoformat(), end_dt.isoformat()]})[:10]}",
            mode="research",
            tickers=tickers,
            as_of_start=start_dt,
            as_of_end=end_dt,
            config={
                "source": "tuning_workflow_baseline_replay",
                "tuning_experiment_id": record.id,
                "cache_only": True,
            },
        )
        queued_runs = replay_service.enqueue_batch(batch.id or 0) if enqueue else []
        metadata = loads_json_object(record.metadata_json)
        metadata["baseline_replay"] = {
            "batch_id": batch.id,
            "status": "queued" if enqueue else batch.status,
            "queued_run_count": len(queued_runs),
            "summary": ReplayValidationAggregateService(self.session).aggregate_batch(batch.id or 0),
        }
        baseline = loads_json_object(record.baseline_json)
        baseline.update({"source": "rerun_baseline_replay", "replay_batch_id": batch.id, "status": metadata["baseline_replay"]["status"]})
        record.baseline_json = _json_dumps(baseline)
        record.metadata_json = _json_dumps(metadata)
        self.session.commit()
        self.session.refresh(record)
        return self.experiment_detail(record)

    def create_candidate_replay_batches(self, experiment_id: int, *, enqueue: bool = True) -> dict[str, object]:
        replay_service = self._require_historical_replay_service()
        record = self.get_experiment(experiment_id)
        metadata = loads_json_object(record.metadata_json)
        readiness = metadata.get("readiness_audit") if isinstance(metadata.get("readiness_audit"), dict) else {}
        if readiness.get("status") == "blocked":
            raise TuningWorkflowError("candidate replay is blocked by readiness audit")
        if not metadata.get("baseline_replay"):
            raise TuningWorkflowError("baseline replay is required before candidate replay")
        shortlist_ids = list(metadata.get("shortlist", {}).get("candidate_ids", []))
        if not shortlist_ids:
            raise TuningWorkflowError("shortlist is required before candidate replay")
        candidates = {str(item.get("id")): item for item in metadata.get("candidate_pool", {}).get("candidates", []) if isinstance(item, dict)}
        universe = loads_json_object(record.universe_json)
        windows = loads_json_object(record.windows_json)
        tickers = self._experiment_tickers(universe)
        start_dt, end_dt = self._window_datetimes(windows, "replay")
        created: dict[str, object] = {}
        for candidate_id in shortlist_ids:
            candidate = candidates.get(str(candidate_id))
            if not candidate:
                raise TuningWorkflowError(f"candidate {candidate_id} not found")
            config_hash = str(candidate.get("config_hash") or stable_hash(candidate.get("config") or {}))
            batch = replay_service.create_batch(
                name=f"tuning-exp-{record.id}-{candidate_id}-{config_hash[:10]}",
                mode="research",
                tickers=tickers,
                as_of_start=start_dt,
                as_of_end=end_dt,
                config={
                    "source": "tuning_workflow_candidate_replay",
                    "tuning_experiment_id": record.id,
                    "tuning_candidate_id": candidate_id,
                    "candidate_config_hash": config_hash,
                    "plan_generation_tuning_config_override": candidate.get("config") or {},
                    "candidate_validation_depth": candidate.get("validation_depth"),
                    "cache_only": True,
                },
            )
            queued_runs = replay_service.enqueue_batch(batch.id or 0) if enqueue else []
            created[str(candidate_id)] = {
                "batch_id": batch.id,
                "status": "queued" if enqueue else batch.status,
                "queued_run_count": len(queued_runs),
                "summary": ReplayValidationAggregateService(self.session).aggregate_batch(batch.id or 0),
            }
        metadata["candidate_replay_validation"] = {
            "status": "queued" if enqueue else "created",
            "label": "replay validation queued; not promotable until completed and summarized",
            "candidate_batches": created,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        record.metadata_json = _json_dumps(metadata)
        self.session.commit()
        self.session.refresh(record)
        return self.experiment_detail(record)

    def refresh_replay_summaries(self, experiment_id: int) -> dict[str, object]:
        record = self.get_experiment(experiment_id)
        metadata = loads_json_object(record.metadata_json)
        baseline = metadata.get("baseline_replay") if isinstance(metadata.get("baseline_replay"), dict) else None
        if baseline and baseline.get("batch_id") is not None:
            batch_id = int(baseline["batch_id"])
            batch = self.session.get(HistoricalReplayBatchRecord, batch_id)
            baseline.update({
                "status": batch.status if batch else baseline.get("status", "missing"),
                "progress": self._batch_progress(batch_id),
                "summary": ReplayValidationAggregateService(self.session).aggregate_batch(batch_id),
            })
        validation = metadata.get("candidate_replay_validation") if isinstance(metadata.get("candidate_replay_validation"), dict) else None
        if validation:
            candidate_batches = validation.get("candidate_batches") if isinstance(validation.get("candidate_batches"), dict) else {}
            for candidate_id, payload in candidate_batches.items():
                if not isinstance(payload, dict) or payload.get("batch_id") is None:
                    continue
                batch_id = int(payload["batch_id"])
                batch = self.session.get(HistoricalReplayBatchRecord, batch_id)
                payload.update({
                    "status": batch.status if batch else payload.get("status", "missing"),
                    "progress": self._batch_progress(batch_id),
                    "summary": ReplayValidationAggregateService(self.session).aggregate_batch(batch_id),
                })
            validation["comparisons"] = self._candidate_comparisons(metadata)
            statuses = [str(payload.get("status")) for payload in candidate_batches.values() if isinstance(payload, dict)]
            validation["status"] = "complete" if statuses and all(status == "completed" for status in statuses) else ("running" if any(status == "running" for status in statuses) else validation.get("status", "queued"))
        record.metadata_json = _json_dumps(metadata)
        self.session.commit()
        self.session.refresh(record)
        return self.experiment_detail(record)

    def stop_candidate_replay_after_current_slice(self, experiment_id: int) -> dict[str, object]:
        record = self.get_experiment(experiment_id)
        metadata = loads_json_object(record.metadata_json)
        controls = metadata.setdefault("operator_controls", {})
        controls["stop_after_current_slice_requested"] = True
        controls["requested_at"] = datetime.now(timezone.utc).isoformat()
        record.metadata_json = _json_dumps(metadata)
        self.session.commit()
        self.session.refresh(record)
        return self.experiment_detail(record)

    def bind_baseline_replay_batch(self, experiment_id: int, replay_batch_id: int) -> dict[str, object]:
        record = self.get_experiment(experiment_id)
        batch = self.session.get(HistoricalReplayBatchRecord, replay_batch_id)
        if batch is None:
            raise TuningWorkflowError(f"replay batch {replay_batch_id} not found")
        aggregate = ReplayValidationAggregateService(self.session).aggregate_batch(replay_batch_id)
        baseline = loads_json_object(record.baseline_json)
        baseline.update({"source": "existing_replay_batch", "replay_batch_id": replay_batch_id, "status": batch.status, "summary": aggregate})
        record.baseline_json = _json_dumps(baseline)
        metadata = loads_json_object(record.metadata_json)
        metadata["baseline_replay"] = {"batch_id": replay_batch_id, "status": batch.status, "summary": aggregate, "progress": self._batch_progress(replay_batch_id)}
        record.metadata_json = _json_dumps(metadata)
        self.session.commit()
        self.session.refresh(record)
        return self.experiment_detail(record)

    def record_candidate_replay_validation(self, experiment_id: int, batch_ids_by_candidate: Mapping[str, int]) -> dict[str, object]:
        record = self.get_experiment(experiment_id)
        metadata = loads_json_object(record.metadata_json)
        shortlist_ids = set(metadata.get("shortlist", {}).get("candidate_ids", []))
        if not shortlist_ids:
            raise TuningWorkflowError("shortlist is required before candidate replay validation")
        summaries: dict[str, object] = {}
        for candidate_id, batch_id in batch_ids_by_candidate.items():
            if candidate_id not in shortlist_ids:
                raise TuningWorkflowError(f"candidate {candidate_id} is not shortlisted")
            batch = self.session.get(HistoricalReplayBatchRecord, int(batch_id))
            if batch is None:
                raise TuningWorkflowError(f"replay batch {batch_id} not found")
            summaries[candidate_id] = {"batch_id": int(batch_id), "status": batch.status, "summary": ReplayValidationAggregateService(self.session).aggregate_batch(int(batch_id)), "progress": self._batch_progress(int(batch_id))}
        metadata["candidate_replay_validation"] = {
            "status": "complete" if summaries else "missing",
            "label": "replay-validated evidence",
            "candidate_batches": summaries,
            "comparisons": self._candidate_comparisons({**metadata, "candidate_replay_validation": {"candidate_batches": summaries}}),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        record.metadata_json = _json_dumps(metadata)
        self.session.commit()
        self.session.refresh(record)
        return self.experiment_detail(record)

    def record_stability_validation(self, experiment_id: int, candidate_id: str, *, status: str = "warning", notes: str = "") -> dict[str, object]:
        record = self.get_experiment(experiment_id)
        metadata = loads_json_object(record.metadata_json)
        replay_validation = metadata.get("candidate_replay_validation") if isinstance(metadata.get("candidate_replay_validation"), dict) else {}
        candidate_batches = replay_validation.get("candidate_batches") if isinstance(replay_validation.get("candidate_batches"), dict) else {}
        if candidate_id not in candidate_batches:
            raise TuningWorkflowError("candidate replay validation is required before stability validation")
        metadata["stability_validation"] = {
            "status": status,
            "candidate_id": candidate_id,
            "label": "holdout/stability evidence",
            "notes": notes,
            "promotion_satisfying": status == "pass",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        record.metadata_json = _json_dumps(metadata)
        self.session.commit()
        self.session.refresh(record)
        return self.experiment_detail(record)

    def execute_paper_promotion(self, experiment_id: int, *, reason: str = "workflow paper promotion") -> dict[str, object]:
        record = self.get_experiment(experiment_id)
        metadata = loads_json_object(record.metadata_json)
        proposal = metadata.get("promotion_proposal") if isinstance(metadata.get("promotion_proposal"), dict) else {}
        if proposal.get("status") != "recommended_for_paper":
            raise TuningWorkflowError("paper promotion requires a recommended_for_paper proposal")
        if record.promotion_target not in {"paper_config", "research_only"}:
            raise TuningWorkflowError("live promotion execution is disabled by default")
        candidate_id = str(proposal.get("candidate_id") or "")
        candidates = {str(item.get("id")): item for item in metadata.get("candidate_pool", {}).get("candidates", []) if isinstance(item, dict)}
        candidate = candidates.get(candidate_id)
        if not candidate:
            raise TuningWorkflowError("proposal candidate not found")
        config = normalize_plan_generation_tuning_config(candidate.get("config") if isinstance(candidate.get("config"), dict) else {})
        repository = PlanGenerationTuningRepository(self.session)
        version = repository.create_config_version(
            PlanGenerationTuningConfigVersion(
                version_label=f"paper-tuning-exp-{record.id}-{candidate_id}",
                status="paper_candidate",
                source="tuning_workflow_paper_promotion",
                config=config,
            )
        )
        repository.create_event(
            PlanGenerationTuningEvent(
                event_type="paper_config_proposed",
                config_version_id=version.id,
                actor_type="workflow",
                actor_identifier="tuning_workflow",
                payload={
                    "tuning_experiment_id": record.id,
                    "candidate_id": candidate_id,
                    "reason": reason,
                    "proposal": proposal,
                    "rollback_config": normalize_plan_generation_tuning_config({}),
                },
            )
        )
        metadata["promotion_execution"] = {
            "status": "paper_config_created",
            "target_config_version_id": version.id,
            "rollback_config": normalize_plan_generation_tuning_config({}),
            "reason": reason,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        metadata["post_promotion_monitoring"] = {
            "status": "pending_paper_trial",
            "config_version_id": version.id,
            "days_active": 0,
            "plans_generated": 0,
            "resolved_outcomes": 0,
            "message": "paper config created; monitoring evidence is pending",
        }
        record.metadata_json = _json_dumps(metadata)
        self.session.commit()
        self.session.refresh(record)
        return self.experiment_detail(record)

    def create_promotion_proposal(self, experiment_id: int, candidate_id: str) -> dict[str, object]:
        record = self.get_experiment(experiment_id)
        metadata = loads_json_object(record.metadata_json)
        shortlist_ids = set(metadata.get("shortlist", {}).get("candidate_ids", []))
        if candidate_id not in shortlist_ids:
            raise TuningWorkflowError("candidate must be shortlisted before promotion proposal")
        blockers = []
        if not metadata.get("baseline_replay"):
            blockers.append("baseline replay is required")
        if not metadata.get("candidate_replay_validation"):
            blockers.append("candidate replay validation is required")
        stability = metadata.get("stability_validation") if isinstance(metadata.get("stability_validation"), dict) else None
        if not stability:
            blockers.append("holdout/stability validation is required")
        elif not stability.get("promotion_satisfying"):
            blockers.append("holdout/stability validation has not passed")
        proposal = {
            "candidate_id": candidate_id,
            "status": "blocked" if blockers else "recommended_for_paper",
            "blockers": blockers,
            "target": record.promotion_target,
            "live_promotion_enabled": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        metadata["promotion_proposal"] = proposal
        record.metadata_json = _json_dumps(metadata)
        self.session.commit()
        self.session.refresh(record)
        return self.experiment_detail(record)

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
        metadata = loads_json_object(record.metadata_json)
        setup = self._setup_status(record, universe, windows, discovery_settings, replay_settings, baseline)
        lifecycle = self._lifecycle(record, setup, metadata)
        sections = self._sections(record, setup, lifecycle, metadata)
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

    def _require_historical_replay_service(self) -> object:
        if self.historical_replay_service is None:
            raise TuningWorkflowError("historical replay service is not configured")
        return self.historical_replay_service

    def _batch_progress(self, batch_id: int) -> dict[str, object]:
        rows = list(self.session.scalars(select(HistoricalReplaySliceRecord).where(HistoricalReplaySliceRecord.replay_batch_id == batch_id)).all())
        counts: dict[str, int] = {}
        failed_slice_ids: list[int] = []
        active_run_ids: list[int] = []
        for row in rows:
            counts[row.status] = counts.get(row.status, 0) + 1
            if row.status == "failed" and row.id is not None:
                failed_slice_ids.append(row.id)
            if row.status in {"queued", "running"} and row.run_id is not None:
                active_run_ids.append(row.run_id)
        total = len(rows)
        completed = counts.get("completed", 0)
        failed = counts.get("failed", 0)
        stale_or_failed = failed + counts.get("stale", 0)
        return {
            "slice_count": total,
            "completed_count": completed,
            "queued_count": counts.get("queued", 0),
            "running_count": counts.get("running", 0),
            "failed_count": failed,
            "stale_count": counts.get("stale", 0),
            "planned_count": counts.get("planned", 0),
            "progress_percent": round((completed / max(1, total)) * 100.0, 2),
            "has_failures_or_stale": stale_or_failed > 0,
            "failed_slice_ids": failed_slice_ids[:20],
            "active_run_ids": active_run_ids[:20],
        }

    def _candidate_comparisons(self, metadata: Mapping[str, object]) -> dict[str, object]:
        baseline = metadata.get("baseline_replay") if isinstance(metadata.get("baseline_replay"), dict) else {}
        baseline_summary = baseline.get("summary") if isinstance(baseline.get("summary"), dict) else {}
        validation = metadata.get("candidate_replay_validation") if isinstance(metadata.get("candidate_replay_validation"), dict) else {}
        candidate_batches = validation.get("candidate_batches") if isinstance(validation.get("candidate_batches"), dict) else {}
        comparisons: dict[str, object] = {}
        baseline_win_rate = baseline_summary.get("win_rate_percent")
        baseline_tier_a = int(baseline_summary.get("tier_a_count") or 0)
        for candidate_id, payload in candidate_batches.items():
            if not isinstance(payload, dict):
                continue
            summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
            candidate_win_rate = summary.get("win_rate_percent")
            win_rate_delta = None
            if isinstance(candidate_win_rate, (int, float)) and isinstance(baseline_win_rate, (int, float)):
                win_rate_delta = round(float(candidate_win_rate) - float(baseline_win_rate), 2)
            tier_a_count = int(summary.get("tier_a_count") or 0)
            comparisons[str(candidate_id)] = {
                "baseline_batch_id": baseline.get("batch_id"),
                "candidate_batch_id": payload.get("batch_id"),
                "baseline_tier_a_count": baseline_tier_a,
                "candidate_tier_a_count": tier_a_count,
                "tier_a_sample_delta": tier_a_count - baseline_tier_a,
                "baseline_win_rate_percent": baseline_win_rate,
                "candidate_win_rate_percent": candidate_win_rate,
                "win_rate_delta_percent": win_rate_delta,
                "baseline_loss_count": baseline_summary.get("loss_count"),
                "candidate_loss_count": summary.get("loss_count"),
                "candidate_top_ticker_concentration_percent": summary.get("top_ticker_concentration_percent"),
                "available": bool(baseline_summary) and bool(summary),
                "label": "replay comparison; not promotion evidence without holdout/stability gates",
            }
        return comparisons

    def _window_datetimes(self, windows: Mapping[str, object], prefix: str) -> tuple[datetime, datetime]:
        start = _date_string(windows.get(f"{prefix}_start"))
        end = _date_string(windows.get(f"{prefix}_end"))
        if not start or not end:
            raise TuningWorkflowError(f"{prefix} window is required")
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)
        return start_dt, end_dt

    def _experiment_tickers(self, universe: Mapping[str, object]) -> list[str]:
        raw_tickers = universe.get("tickers")
        if not isinstance(raw_tickers, list):
            return []
        return sorted({str(ticker).strip().upper() for ticker in raw_tickers if str(ticker).strip()})

    def _lifecycle(self, record: TuningExperimentRecord, setup: Mapping[str, object], metadata: Mapping[str, object]) -> dict[str, object]:
        if record.status == "archived":
            return {"current_stage": "archived", "next_action": "No action; experiment is archived.", "blockers": []}
        missing = list(setup.get("missing_fields") or [])
        if missing:
            return {
                "current_stage": "setup_incomplete",
                "next_action": "Complete required setup fields before running readiness or discovery.",
                "blockers": missing,
            }
        readiness = metadata.get("readiness_audit") if isinstance(metadata.get("readiness_audit"), dict) else None
        if not readiness:
            return {
                "current_stage": "readiness_needed",
                "next_action": "Run a cache-only evidence readiness audit before candidate discovery.",
                "blockers": [],
            }
        if readiness.get("status") == "blocked":
            return {"current_stage": "readiness_blocked", "next_action": "Fix hard readiness blockers or adjust the experiment.", "blockers": list(readiness.get("blockers") or [])}
        candidate_pool = metadata.get("candidate_pool") if isinstance(metadata.get("candidate_pool"), dict) else {}
        if not candidate_pool.get("candidates"):
            return {"current_stage": "candidate_discovery_needed", "next_action": "Generate or import a small candidate pool.", "blockers": []}
        shortlist = metadata.get("shortlist") if isinstance(metadata.get("shortlist"), dict) else {}
        if not shortlist.get("candidate_ids"):
            return {"current_stage": "shortlist_needed", "next_action": "Select a small replay shortlist.", "blockers": []}
        if not metadata.get("baseline_replay"):
            return {"current_stage": "baseline_needed", "next_action": "Bind or run a baseline replay before comparing candidates.", "blockers": ["baseline replay"]}
        if not metadata.get("candidate_replay_validation"):
            return {"current_stage": "candidate_replay_needed", "next_action": "Run candidate replay validation for shortlisted configs.", "blockers": []}
        if not metadata.get("stability_validation"):
            return {"current_stage": "stability_validation_needed", "next_action": "Run walk-forward or holdout validation for the leading candidate.", "blockers": []}
        if not metadata.get("promotion_proposal"):
            return {"current_stage": "promotion_proposal_needed", "next_action": "Create a promotion proposal with gate table.", "blockers": []}
        execution = metadata.get("promotion_execution") if isinstance(metadata.get("promotion_execution"), dict) else {}
        if execution.get("status") == "paper_config_created":
            return {"current_stage": "paper_promoted", "next_action": "Monitor the paper config before any guarded-live rollout.", "blockers": []}
        proposal = metadata.get("promotion_proposal") if isinstance(metadata.get("promotion_proposal"), dict) else {}
        return {"current_stage": str(proposal.get("status") or "promotion_proposal_ready"), "next_action": "Review promotion proposal.", "blockers": list(proposal.get("blockers") or [])}

    def _sections(
        self,
        record: TuningExperimentRecord,
        setup: Mapping[str, object],
        lifecycle: Mapping[str, object],
        metadata: Mapping[str, object],
    ) -> dict[str, object]:
        setup_status = "complete" if setup.get("complete") else "blocked"
        candidate_pool = metadata.get("candidate_pool") if isinstance(metadata.get("candidate_pool"), dict) else {"status": "empty", "candidates": []}
        shortlist = metadata.get("shortlist") if isinstance(metadata.get("shortlist"), dict) else {"candidate_ids": []}
        baseline_replay = metadata.get("baseline_replay") if isinstance(metadata.get("baseline_replay"), dict) else {"status": "missing", "batch_id": None}
        return {
            "setup": {"status": setup_status, "warnings": setup.get("warnings", []), "blockers": setup.get("missing_fields", [])},
            "evidence_readiness": metadata.get("readiness_audit") if isinstance(metadata.get("readiness_audit"), dict) else {"status": "not_run", "cache_only": True, "warnings": []},
            "candidate_pool": {**candidate_pool, "label": "discovery-only evidence"},
            "shortlist": {"status": "selected" if shortlist.get("candidate_ids") else "empty", "candidate_ids": shortlist.get("candidate_ids", []), "max_candidates": loads_json_object(record.replay_settings_json).get("max_candidates", 5)},
            "baseline_replay": baseline_replay,
            "candidate_replay_validation": metadata.get("candidate_replay_validation") if isinstance(metadata.get("candidate_replay_validation"), dict) else {"status": "blocked", "reason": "baseline and shortlist are required"},
            "stability_validation": metadata.get("stability_validation") if isinstance(metadata.get("stability_validation"), dict) else {"status": "not_run", "label": "stability/overfit screen"},
            "promotion_proposal": metadata.get("promotion_proposal") if isinstance(metadata.get("promotion_proposal"), dict) else {"status": "blocked", "reason": "replay and holdout validation are required"},
            "promotion_execution": metadata.get("promotion_execution") if isinstance(metadata.get("promotion_execution"), dict) else {"status": "not_run"},
            "post_promotion_monitoring": metadata.get("post_promotion_monitoring") if isinstance(metadata.get("post_promotion_monitoring"), dict) else {"status": "not_applicable"},
        }
