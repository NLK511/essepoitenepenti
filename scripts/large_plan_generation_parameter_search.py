#!/usr/bin/env python
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import random
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, fields, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

from trade_proposer_app.db import SessionLocal
from trade_proposer_app.services.confidence_calibration_health import (
    ConfidenceCalibrationObservation,
    calibration_health_report,
)
from trade_proposer_app.services.plan_generation_tuning import PlanGenerationTuningService
from trade_proposer_app.services.plan_generation_tuning_parameters import (
    PARAMETER_BY_KEY,
    candidate_validation_depth,
    normalize_plan_generation_tuning_config,
)
from trade_proposer_app.services.plan_generation_walk_forward import (
    PlanGenerationWalkForwardService,
)
from trade_proposer_app.services.tuning_evidence_partitions import (
    EvidencePartitionError,
    build_evidence_partitions,
    records_for_dates,
    select_stratified_dates,
    stable_hash,
)
from trade_proposer_app.services.tuning_stability import TuningStabilityEvaluator

Fingerprint = str
MinActionableMode = Literal["rank_only", "hard_gate"]
ObjectiveProfile = Literal["research_precision", "research_ev_per_trade", "promotion_candidate"]
ReplayEvidenceProfile = Literal["research", "promotion", "phantom_selectivity"]
SearchCampaign = Literal[
    "selectivity_only",
    "entry_risk_only",
    "stop_risk_only",
    "take_profit_family_only",
    "combined_small_delta",
    "high_risk_research",
]

CAMPAIGN_PARAMETER_KEYS: dict[SearchCampaign, tuple[str, ...]] = {
    "selectivity_only": ("global.actionable_confidence_floor_percent",),
    "entry_risk_only": (
        "global.entry_band_risk_fraction",
        "setup_family.entry_band_multiplier",
    ),
    "stop_risk_only": (
        "global.headwind_stop_multiplier",
        "global.volatility_stop_multiplier",
        "setup_family.breakout.stop_distance_multiplier",
        "setup_family.mean_reversion.stop_distance_multiplier",
    ),
    "take_profit_family_only": tuple(
        key for key, definition in PARAMETER_BY_KEY.items() if definition.category == "reward"
    ),
    "combined_small_delta": tuple(PARAMETER_BY_KEY.keys()),
    "high_risk_research": tuple(PARAMETER_BY_KEY.keys()),
}
CAMPAIGN_MAX_CHANGED_KEYS: dict[SearchCampaign, int | None] = {
    "selectivity_only": 1,
    "entry_risk_only": 2,
    "stop_risk_only": 2,
    "take_profit_family_only": 1,
    "combined_small_delta": 3,
    "high_risk_research": None,
}


@dataclass(frozen=True)
class SearchResult:
    phase: str
    config: dict[str, float]
    changed_keys: list[str]
    search_actionable_count: int
    search_win_count: int
    search_expected_value: float
    search_ambiguous_count: int
    validation_actionable_count: int
    validation_win_count: int
    validation_expected_value: float
    validation_ambiguous_count: int
    search_research_plan_count: int = 0
    search_shadow_observation_count: int = 0
    validation_research_plan_count: int = 0
    validation_shadow_observation_count: int = 0
    stage: str = "legacy_discovery"
    stability_eligible: bool = True
    stability: dict[str, object] | None = None
    holdout: dict[str, object] | None = None
    campaign: str | None = None
    gate_blockers: list[str] | None = None

    @property
    def validation_win_rate(self) -> float:
        return (
            self.validation_win_count / self.validation_actionable_count
            if self.validation_actionable_count
            else 0.0
        )

    @property
    def validation_expected_value_per_actionable(self) -> float:
        if self.validation_actionable_count <= 0:
            return 0.0
        return self.validation_expected_value / self.validation_actionable_count

    @property
    def search_win_rate(self) -> float:
        return (
            self.search_win_count / self.search_actionable_count
            if self.search_actionable_count
            else 0.0
        )

    def payload(self) -> dict[str, object]:
        depth = candidate_validation_depth(self.changed_keys)
        return {
            "phase": self.phase,
            "stage": self.stage,
            "config": self.config,
            "config_hash": _fingerprint(self.config),
            "changed_keys": self.changed_keys,
            "validation_depth": depth["validation_depth"],
            "validation_depth_reason": depth["validation_depth_reason"],
            "search_actionable_count": self.search_actionable_count,
            "search_win_count": self.search_win_count,
            "search_win_rate_percent": round(self.search_win_rate * 100.0, 2),
            "search_expected_value": round(self.search_expected_value, 4),
            "search_ambiguous_count": self.search_ambiguous_count,
            "search_research_plan_count": self.search_research_plan_count,
            "search_shadow_observation_count": self.search_shadow_observation_count,
            "validation_actionable_count": self.validation_actionable_count,
            "validation_win_count": self.validation_win_count,
            "validation_win_rate_percent": round(self.validation_win_rate * 100.0, 2),
            "validation_expected_value": round(self.validation_expected_value, 4),
            "validation_ambiguous_count": self.validation_ambiguous_count,
            "validation_research_plan_count": self.validation_research_plan_count,
            "validation_shadow_observation_count": self.validation_shadow_observation_count,
            "stability_eligible": self.stability_eligible,
            "stability": self.stability,
            "holdout": self.holdout,
            "campaign": self.campaign,
            "gate_blockers": list(self.gate_blockers or []),
            "promotion_capable": False,
        }


@dataclass(frozen=True)
class LoadedResumeCache:
    seen: set[Fingerprint]
    results: list[SearchResult]
    compatible: bool


class ResumeCache:
    schema_version = 3

    def __init__(self, path: Path, metadata: dict[str, object]) -> None:
        self.path = path
        self.metadata = metadata
        self._handle = None

    def initialize(self) -> None:
        if not self._existing_metadata_compatible():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(
                    {
                        "type": "metadata",
                        "schema_version": self.schema_version,
                        "metadata": self.metadata,
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a", encoding="utf-8")

    def _existing_metadata_compatible(self) -> bool:
        if not self.path.exists():
            return False
        try:
            with self.path.open(encoding="utf-8") as handle:
                line = handle.readline()
            payload = json.loads(line) if line.strip() else {}
        except (OSError, json.JSONDecodeError):
            return False
        return (
            payload.get("type") == "metadata"
            and payload.get("schema_version") == self.schema_version
            and payload.get("metadata") == self.metadata
        )

    def load_existing(
        self,
        *,
        top_k: int | None = None,
        min_validation_actionable: int = 1,
        min_actionable_mode: MinActionableMode = "rank_only",
    ) -> LoadedResumeCache:
        if not self.path.exists():
            return LoadedResumeCache(seen=set(), results=[], compatible=False)
        seen: set[Fingerprint] = set()
        results: list[SearchResult] = []
        results_by_stage: dict[str, list[SearchResult]] = {}
        baseline_by_stage: dict[str, SearchResult] = {}
        compatible = False
        with self.path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    return LoadedResumeCache(seen=set(), results=[], compatible=False)
                if line_number == 1:
                    compatible = (
                        payload.get("type") == "metadata"
                        and payload.get("schema_version") == self.schema_version
                        and payload.get("metadata") == self.metadata
                    )
                    if not compatible:
                        return LoadedResumeCache(seen=set(), results=[], compatible=False)
                    continue
                if payload.get("type") != "result":
                    continue
                result_payload = payload.get("result")
                if not isinstance(result_payload, dict):
                    continue
                result = self._result_from_dict(result_payload)
                # A config can be evaluated once per stage. Cache identity includes stage.
                identity = _stage_fingerprint(result.config, result.stage)
                if identity in seen:
                    continue
                seen.add(identity)
                # Preserve schema-v1 caller compatibility while stage identities prevent
                # cross-stage cache reuse in the funnel.
                seen.add(_fingerprint(result.config))
                if not result.changed_keys:
                    baseline_by_stage[result.stage] = result
                if top_k is None:
                    results.append(result)
                else:
                    stage_results = results_by_stage.setdefault(result.stage, [])
                    _keep_top(
                        stage_results,
                        result,
                        top_k=max(1, top_k),
                        min_validation_actionable=min_validation_actionable,
                        min_actionable_mode=min_actionable_mode,
                        objective_profile="research_ev_per_trade",
                    )
        if top_k is not None:
            for stage, baseline in baseline_by_stage.items():
                stage_results = results_by_stage.setdefault(stage, [])
                results_by_stage[stage] = _ensure_baseline(
                    stage_results, baseline, top_k=max(1, top_k)
                )
            results = [
                result for stage in sorted(results_by_stage) for result in results_by_stage[stage]
            ]
        return LoadedResumeCache(seen=seen, results=results, compatible=compatible)

    def append_result(self, result: SearchResult) -> None:
        if self._handle is None:
            self.initialize()
        assert self._handle is not None
        self._handle.write(
            json.dumps(
                {
                    "type": "result",
                    "fingerprint": _stage_fingerprint(result.config, result.stage),
                    "stage": result.stage,
                    "result": asdict(result),
                    "evaluated_at": datetime.now(UTC).isoformat(),
                },
                sort_keys=True,
            )
            + "\n"
        )
        self._handle.flush()

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    @staticmethod
    def _result_from_dict(payload: dict[str, object]) -> SearchResult:
        allowed = {field.name for field in fields(SearchResult)}
        clean = {key: payload[key] for key in allowed if key in payload}
        clean["config"] = {key: float(value) for key, value in dict(clean["config"]).items()}
        clean["changed_keys"] = list(clean.get("changed_keys", []))
        return SearchResult(**clean)  # type: ignore[arg-type]


def _rank_key(
    result: SearchResult,
    *,
    min_validation_actionable: int,
    objective_profile: ObjectiveProfile = "research_precision",
) -> tuple[object, ...]:
    """Canonical ordering after stage gates; objective profile controls the primary metric."""
    enough_validation = result.validation_actionable_count >= min_validation_actionable
    common = (
        enough_validation,
        result.stability_eligible,
    )
    if objective_profile == "research_ev_per_trade":
        primary = (
            result.validation_expected_value_per_actionable,
            result.validation_win_rate,
            result.validation_expected_value,
            result.validation_win_count,
        )
    elif objective_profile == "promotion_candidate":
        positive_ev_per_trade = result.validation_expected_value_per_actionable > 0
        primary = (
            positive_ev_per_trade,
            result.validation_expected_value_per_actionable,
            result.validation_expected_value,
            result.validation_win_rate,
            result.validation_win_count,
        )
    else:
        primary = (
            result.validation_win_rate,
            result.validation_win_count,
            result.validation_expected_value_per_actionable,
            result.validation_expected_value,
        )
    return (
        *common,
        *primary,
        result.search_win_rate,
        result.search_expected_value,
        -result.validation_ambiguous_count,
        -len(result.changed_keys),
    )


def _is_baseline_result(result: SearchResult) -> bool:
    return not result.changed_keys


def _gate_blockers(
    result: SearchResult,
    *,
    min_validation_actionable: int,
    min_actionable_mode: MinActionableMode,
) -> list[str]:
    if min_actionable_mode == "rank_only" or _is_baseline_result(result):
        return []
    blockers: list[str] = []
    if result.validation_actionable_count < min_validation_actionable:
        blockers.append(
            "selection_actionable_below_minimum"
            if result.stage == "selection_walk_forward"
            else "validation_actionable_below_minimum"
        )
    if not result.stability_eligible and result.stage in {
        "stability_screen",
        "selection_walk_forward",
    }:
        stability = result.stability if isinstance(result.stability, dict) else {}
        qualified_slices = stability.get("qualified_slices")
        qualified_folds = stability.get("qualified_fold_count")
        if isinstance(qualified_slices, int) and qualified_slices < 3:
            blockers.append("walk_forward_qualified_slices_below_minimum")
        elif isinstance(qualified_folds, int) and qualified_folds < 3:
            blockers.append("holdout_qualified_folds_below_minimum")
        else:
            blockers.append("stability_gate_failed")
    return blockers


def _passes_min_actionable_gate(
    result: SearchResult,
    *,
    min_validation_actionable: int,
    min_actionable_mode: MinActionableMode,
) -> bool:
    return not _gate_blockers(
        result,
        min_validation_actionable=min_validation_actionable,
        min_actionable_mode=min_actionable_mode,
    )


def _keep_top(
    top: list[SearchResult],
    result: SearchResult,
    *,
    top_k: int,
    min_validation_actionable: int,
    min_actionable_mode: MinActionableMode = "rank_only",
    objective_profile: ObjectiveProfile = "research_precision",
) -> list[SearchResult]:
    if not _passes_min_actionable_gate(
        result,
        min_validation_actionable=min_validation_actionable,
        min_actionable_mode=min_actionable_mode,
    ):
        return top
    top.append(result)
    top.sort(
        key=lambda item: _rank_key(
            item,
            min_validation_actionable=min_validation_actionable,
            objective_profile=objective_profile,
        ),
        reverse=True,
    )
    if len(top) > top_k:
        del top[top_k:]
    return top


def _fingerprint(config: dict[str, float]) -> Fingerprint:
    canonical = json.dumps(
        {key: round(float(value), 4) for key, value in sorted(config.items())},
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _stage_fingerprint(config: dict[str, float], stage: str) -> Fingerprint:
    return f"{stage}:{_fingerprint(config)}"


def _bounded(key: str, value: float) -> float:
    definition = PARAMETER_BY_KEY[key]
    return round(max(definition.exploration_min, min(definition.exploration_max, value)), 4)


def _random_grid_value(key: str, rng: random.Random) -> float:
    definition = PARAMETER_BY_KEY[key]
    steps = int(round((definition.exploration_max - definition.exploration_min) / definition.step))
    return round(definition.exploration_min + (rng.randint(0, max(0, steps)) * definition.step), 4)


def coarse_candidates(
    active_config: dict[str, float],
    *,
    count: int,
    seed: int,
    campaign: SearchCampaign = "high_risk_research",
) -> Iterable[dict[str, float]]:
    rng = random.Random(seed)
    keys = CAMPAIGN_PARAMETER_KEYS[campaign]
    max_changed_keys = CAMPAIGN_MAX_CHANGED_KEYS[campaign]
    yield normalize_plan_generation_tuning_config(active_config)
    for _ in range(max(0, count - 1)):
        config = dict(active_config)
        candidate_keys = _sample_campaign_keys(keys, rng=rng, max_changed_keys=max_changed_keys)
        for key in candidate_keys:
            config[key] = _random_grid_value(key, rng)
        yield normalize_plan_generation_tuning_config(config)


def fine_candidates(
    active_config: dict[str, float],
    seeds: list[SearchResult],
    *,
    count: int,
    seed: int,
    campaign: SearchCampaign = "high_risk_research",
) -> Iterable[dict[str, float]]:
    if not seeds or count <= 0:
        return
    rng = random.Random(seed)
    keys = CAMPAIGN_PARAMETER_KEYS[campaign]
    max_changed_keys = CAMPAIGN_MAX_CHANGED_KEYS[campaign]
    for index in range(count):
        source = seeds[index % len(seeds)]
        config = dict(active_config)
        config.update(source.config)
        changed = [
            key
            for key in keys
            if round(float(config.get(key, active_config.get(key, 0.0))), 4)
            != round(float(active_config.get(key, 0.0)), 4)
        ]
        candidate_keys = tuple(changed) or _sample_campaign_keys(
            keys,
            rng=rng,
            max_changed_keys=max_changed_keys,
        )
        if max_changed_keys is not None and len(candidate_keys) > max_changed_keys:
            candidate_keys = tuple(sorted(candidate_keys))[:max_changed_keys]
        for key in candidate_keys:
            definition = PARAMETER_BY_KEY[key]
            radius = max(
                definition.step,
                (definition.exploration_max - definition.exploration_min) * 0.08,
            )
            jitter = rng.uniform(-radius, radius)
            stepped = round((float(config[key]) + jitter) / definition.step) * definition.step
            config[key] = _bounded(key, stepped)
        yield normalize_plan_generation_tuning_config(config)


def _sample_campaign_keys(
    keys: Sequence[str],
    *,
    rng: random.Random,
    max_changed_keys: int | None,
) -> tuple[str, ...]:
    if max_changed_keys is None or len(keys) <= max_changed_keys:
        return tuple(keys)
    sample_size = rng.randint(1, max(1, max_changed_keys))
    return tuple(rng.sample(tuple(keys), k=sample_size))


def evaluate_stream(
    service: PlanGenerationTuningService,
    candidates: Iterable[dict[str, float]],
    *,
    active_config: dict[str, float],
    search_records: Sequence,
    validation_records: Sequence,
    phase: str,
    top_k: int,
    min_validation_actionable: int,
    batch_log_interval: int,
    seen: set[Fingerprint],
    resume_cache: ResumeCache | None = None,
    stage: str = "legacy_discovery",
    min_actionable_mode: MinActionableMode = "rank_only",
    objective_profile: ObjectiveProfile = "research_precision",
    campaign: SearchCampaign | None = None,
) -> tuple[list[SearchResult], int]:
    top: list[SearchResult] = []
    baseline_result: SearchResult | None = None
    evaluated = 0
    skipped_duplicates = 0
    started = datetime.now(UTC)
    for config in candidates:
        identity = _stage_fingerprint(config, stage)
        if identity in seen:
            skipped_duplicates += 1
            continue
        seen.add(identity)
        search_actionable, search_win, search_ev, search_ambiguous = service._score_records(  # noqa: SLF001
            search_records, config
        )
        search_research, search_shadow = _research_shadow_counts(
            service,
            search_records, config
        )
        if search_records is validation_records:
            validation_actionable = search_actionable
            validation_win = search_win
            validation_ev = search_ev
            validation_ambiguous = search_ambiguous
            validation_research = search_research
            validation_shadow = search_shadow
        else:
            validation_actionable, validation_win, validation_ev, validation_ambiguous = (
                service._score_records(validation_records, config)  # noqa: SLF001
            )
            validation_research, validation_shadow = _research_shadow_counts(
                service,
                validation_records, config
            )
        result = SearchResult(
            phase=phase,
            stage=stage,
            config=config,
            changed_keys=_changed_keys(config, active_config),
            search_actionable_count=search_actionable,
            search_win_count=search_win,
            search_expected_value=search_ev,
            search_ambiguous_count=search_ambiguous,
            validation_actionable_count=validation_actionable,
            validation_win_count=validation_win,
            validation_expected_value=validation_ev,
            validation_ambiguous_count=validation_ambiguous,
            search_research_plan_count=search_research,
            search_shadow_observation_count=search_shadow,
            validation_research_plan_count=validation_research,
            validation_shadow_observation_count=validation_shadow,
            campaign=campaign,
        )
        if config == active_config:
            baseline_result = result
        _keep_top(
            top,
            result,
            top_k=top_k,
            min_validation_actionable=min_validation_actionable,
            min_actionable_mode=min_actionable_mode,
            objective_profile=objective_profile,
        )
        if resume_cache is not None:
            resume_cache.append_result(result)
        evaluated += 1
        if evaluated % max(1, batch_log_interval) == 0:
            _log_progress(stage, phase, evaluated, skipped_duplicates, started, top)
            gc.collect()
            service._memory_guard(stage=f"large-search-{stage}-{evaluated}")  # noqa: SLF001
    return _ensure_baseline(top, baseline_result, top_k=top_k), evaluated


def _research_shadow_counts(
    service: PlanGenerationTuningService,
    records: Sequence,
    config: dict[str, float],
) -> tuple[int, int]:
    counter = getattr(service, "_research_shadow_counts", None)
    if counter is None:
        return 0, 0
    return counter(records, config)


def _evaluate_stability_stage(
    service: PlanGenerationTuningService,
    configs: Iterable[dict[str, float]],
    *,
    active_config: dict[str, float],
    records: Sequence,
    stage: str,
    top_k: int,
    min_validation_actionable: int,
    min_fold_actionable: int,
    fold_count: int,
    batch_log_interval: int,
    seen: set[Fingerprint],
    resume_cache: ResumeCache | None,
    min_actionable_mode: MinActionableMode,
    objective_profile: ObjectiveProfile,
    campaign: SearchCampaign,
) -> tuple[list[SearchResult], int]:
    evaluator = TuningStabilityEvaluator(service)
    top: list[SearchResult] = []
    baseline_result: SearchResult | None = None
    evaluated = 0
    started = datetime.now(UTC)
    for config in configs:
        identity = _stage_fingerprint(config, stage)
        if identity in seen:
            continue
        seen.add(identity)
        stability = evaluator.evaluate(
            records,
            candidate_config=config,
            baseline_config=active_config,
            fold_count=fold_count,
            min_fold_actionable=min_fold_actionable,
        )
        aggregate = stability.candidate
        research_count, shadow_count = _research_shadow_counts(service, records, config)
        result = SearchResult(
            phase=stage,
            stage=stage,
            config=config,
            changed_keys=_changed_keys(config, active_config),
            search_actionable_count=aggregate.actionable_count,
            search_win_count=aggregate.win_count,
            search_expected_value=aggregate.expected_value_total,
            search_ambiguous_count=aggregate.ambiguous_count,
            validation_actionable_count=aggregate.actionable_count,
            validation_win_count=aggregate.win_count,
            validation_expected_value=aggregate.expected_value_total,
            validation_ambiguous_count=aggregate.ambiguous_count,
            search_research_plan_count=research_count,
            search_shadow_observation_count=shadow_count,
            validation_research_plan_count=research_count,
            validation_shadow_observation_count=shadow_count,
            stability_eligible=stability.stable or config == active_config,
            stability=stability.payload(include_dates=False),
            campaign=campaign,
        )
        if config == active_config:
            baseline_result = result
        _keep_top(
            top,
            result,
            top_k=top_k,
            min_validation_actionable=min_validation_actionable,
            min_actionable_mode=min_actionable_mode,
            objective_profile=objective_profile,
        )
        if resume_cache is not None:
            resume_cache.append_result(result)
        evaluated += 1
        if evaluated % max(1, batch_log_interval) == 0:
            _log_progress(stage, stage, evaluated, 0, started, top)
            gc.collect()
            service._memory_guard(stage=f"large-search-{stage}-{evaluated}")  # noqa: SLF001
    return _ensure_baseline(top, baseline_result, top_k=top_k), evaluated


def _evaluate_walk_forward_stage(
    service: PlanGenerationTuningService,
    configs: Sequence[dict[str, float]],
    *,
    active_config: dict[str, float],
    records: list,
    top_k: int,
    min_validation_actionable: int,
    seen: set[Fingerprint],
    resume_cache: ResumeCache | None,
    min_actionable_mode: MinActionableMode,
    objective_profile: ObjectiveProfile,
    campaign: SearchCampaign,
) -> tuple[list[SearchResult], int]:
    top: list[SearchResult] = []
    baseline_result: SearchResult | None = None
    evaluated = 0
    walk_forward = PlanGenerationWalkForwardService(service)
    date_count = len({item.plan.computed_at.date() for item in records if item.plan.computed_at})
    validation_days = max(7, min(30, max(7, date_count // 3)))
    step_days = max(1, validation_days // 2)
    min_slice = max(1, min_validation_actionable // 3)
    for config in configs:
        identity = _stage_fingerprint(config, "selection_walk_forward")
        if identity in seen:
            continue
        seen.add(identity)
        actionable, wins, expected_value, ambiguous = service._score_records(records, config)  # noqa: SLF001
        summary = walk_forward.summarize_records(
            records=records,
            candidate_config=config,
            baseline_config=active_config,
            candidate_label="candidate",
            baseline_label="baseline",
            lookback_days=max(30, date_count + validation_days),
            validation_days=validation_days,
            step_days=step_days,
            min_validation_resolved=min_slice,
        )
        eligible = config == active_config or (
            summary.qualified_slices >= 3
            and summary.severe_win_rate_regressions <= 1
            and summary.candidate_wins >= summary.baseline_wins
        )
        stability = summary.model_dump(mode="json")
        stability["stable"] = eligible
        research_count, shadow_count = _research_shadow_counts(service, records, config)
        result = SearchResult(
            phase="selection_walk_forward",
            stage="selection_walk_forward",
            config=config,
            changed_keys=_changed_keys(config, active_config),
            search_actionable_count=actionable,
            search_win_count=wins,
            search_expected_value=expected_value,
            search_ambiguous_count=ambiguous,
            validation_actionable_count=actionable,
            validation_win_count=wins,
            validation_expected_value=expected_value,
            validation_ambiguous_count=ambiguous,
            search_research_plan_count=research_count,
            search_shadow_observation_count=shadow_count,
            validation_research_plan_count=research_count,
            validation_shadow_observation_count=shadow_count,
            stability_eligible=eligible,
            stability=stability,
            campaign=campaign,
        )
        if config == active_config:
            baseline_result = result
        _keep_top(
            top,
            result,
            top_k=top_k,
            min_validation_actionable=min_validation_actionable,
            min_actionable_mode=min_actionable_mode,
            objective_profile=objective_profile,
        )
        if resume_cache is not None:
            resume_cache.append_result(result)
        evaluated += 1
    return _ensure_baseline(top, baseline_result, top_k=top_k), evaluated


def _evaluate_locked_holdout(
    service: PlanGenerationTuningService,
    finalists: Sequence[SearchResult],
    *,
    active_config: dict[str, float],
    records: Sequence,
    holdout_status: str,
    min_validation_actionable: int,
    objective_profile: ObjectiveProfile,
) -> list[SearchResult]:
    if not records or holdout_status not in {"locked", "defer_thin_holdout"}:
        status = {"status": holdout_status, "scoreable": False, "promotion_capable": False}
        return [replace(item, holdout=status) for item in finalists]
    evaluator = TuningStabilityEvaluator(service)
    output: list[SearchResult] = []
    for item in finalists:
        stability = evaluator.evaluate(
            records,
            candidate_config=item.config,
            baseline_config=active_config,
            fold_count=4,
            min_fold_actionable=max(1, min_validation_actionable // 4),
            min_qualified_folds=3,
        )
        depth = candidate_validation_depth(item.changed_keys)["validation_depth"]
        candidate_delta = stability.win_rate_delta_without_best_date
        proxy_passed = bool(
            (item.config == active_config or stability.stable)
            and candidate_delta is not None
            and candidate_delta >= -0.25
        )
        canonical_required = depth != "rescore_only"
        candidate_ev_per_actionable = stability.candidate.expected_value_per_actionable
        baseline_ev_total = stability.baseline.expected_value_total
        candidate_ev_total = stability.candidate.expected_value_total
        promotion_blockers = list(stability.reasons)
        if stability.qualified_fold_count < 3:
            promotion_blockers.append("holdout_qualified_folds_below_minimum")
        if candidate_ev_per_actionable is None or candidate_ev_per_actionable < 0:
            promotion_blockers.append("holdout_ev_per_actionable_negative")
        if candidate_ev_total < baseline_ev_total:
            promotion_blockers.append("exposure_expansion_loss")
        if canonical_required:
            promotion_blockers.append("requires_canonical_candidate_replay")
        hard_holdout_blockers = {
            "holdout_ev_per_actionable_negative",
            "exposure_expansion_loss",
            "holdout_qualified_folds_below_minimum",
        }
        if not _is_baseline_result(item) and any(
            blocker in hard_holdout_blockers for blocker in promotion_blockers
        ):
            proxy_passed = False
        if objective_profile == "promotion_candidate" and promotion_blockers:
            proxy_passed = False
        status = (
            "baseline_holdout_reference"
            if _is_baseline_result(item)
            else
            "requires_canonical_candidate_replay"
            if proxy_passed and canonical_required
            else "passed_holdout"
            if proxy_passed
            else "defer_thin_holdout"
            if holdout_status == "defer_thin_holdout"
            else "failed_holdout"
        )
        holdout = stability.payload(include_dates=True)
        holdout.update(
            {
                "status": status,
                "scoreable": True,
                "proxy_passed": proxy_passed,
                "canonical_candidate_replay_required": canonical_required,
                "promotion_capable": False,
                "promotion_blockers": sorted(set(promotion_blockers)),
                "objective_profile": objective_profile,
                "note": (
                    "Stored-plan holdout is a falsification screen; geometry-changing "
                    "configs require canonical candidate replay."
                ),
            }
        )
        output.append(replace(item, holdout=holdout))
    return output


def _calibration_health_for_records(
    service: PlanGenerationTuningService,
    records: Sequence,
    active_config: dict[str, float],
) -> dict[str, object]:
    if not hasattr(service, "_candidate_resolution"):
        return calibration_health_report([])
    config = dict(active_config)
    # The tuning scorer treats falsy floors as "use default"; use a near-zero
    # floor to inspect confidence reliability without applying the action gate.
    config["global.actionable_confidence_floor_percent"] = 0.01
    observations: list[ConfidenceCalibrationObservation] = []
    for record in records:
        resolution = service._candidate_resolution(record, config)  # noqa: SLF001
        if resolution is None:
            continue
        outcome, reward_pct, risk_pct = resolution
        expected_value = reward_pct if outcome == "win" else -risk_pct
        computed_at = getattr(record.plan, "computed_at", None)
        evidence_date = computed_at.date().isoformat() if computed_at is not None else None
        observations.append(
            ConfidenceCalibrationObservation(
                confidence_percent=float(record.plan.confidence_percent or 0.0),
                outcome=outcome,
                evidence_date=evidence_date,
                ticker=str(record.plan.ticker or ""),
                setup_family=str(record.setup_family or ""),
                context_bias=str(record.context_bias or ""),
                expected_value=expected_value,
            )
        )
    return calibration_health_report(observations)


def _evidence_preflight(
    *,
    records: Sequence[object],
    partitions,
    evidence_source: str,
    replay_evidence_profile: str,
) -> dict[str, object]:
    blockers: list[str] = []
    warnings = list(partitions.warnings)
    selection_dates = len(partitions.selection.evidence_dates)
    holdout_dates = len(partitions.locked_holdout.evidence_dates)
    promotion_profile = evidence_source != "replay" or replay_evidence_profile == "promotion"
    candidate_replay_required = (
        evidence_source == "replay" and replay_evidence_profile == "phantom_selectivity"
    )
    min_selection_dates = 20 if promotion_profile else 10
    min_holdout_dates = 20
    if not records:
        blockers.append("no_eligible_records")
    if not partitions.selection.records:
        blockers.append("no_selection_records")
    elif selection_dates < min_selection_dates:
        blockers.append("selection_distinct_dates_below_minimum")
    if promotion_profile:
        if partitions.holdout_status != "locked":
            blockers.append(partitions.holdout_status)
        elif not partitions.locked_holdout.records:
            blockers.append("no_locked_holdout_records")
        elif holdout_dates < min_holdout_dates:
            blockers.append("holdout_distinct_dates_below_minimum")
    elif partitions.holdout_status != "locked":
        warnings.append(partitions.holdout_status)

    if candidate_replay_required:
        warnings.append("phantom_selectivity_requires_candidate_specific_replay")

    return {
        "schema_version": "large-search-evidence-preflight-v1",
        "status": "scoreable" if not blockers else "thin_evidence",
        "run_role": (
            "research_phantom_selectivity"
            if candidate_replay_required and not blockers
            else "research_only"
            if not blockers
            else "research_thin_evidence"
        ),
        "evidence_source": evidence_source,
        "replay_evidence_profile": replay_evidence_profile
        if evidence_source == "replay"
        else None,
        "promotion_search_capable": promotion_profile and not blockers,
        "candidate_replay_required": candidate_replay_required,
        "eligible_record_count": len(records),
        "partition_record_counts": {
            "discovery": len(partitions.discovery.records),
            "selection": len(partitions.selection.records),
            "locked_holdout": len(partitions.locked_holdout.records),
        },
        "partition_distinct_date_counts": {
            "discovery": len(partitions.discovery.evidence_dates),
            "selection": selection_dates,
            "locked_holdout": holdout_dates,
        },
        "minimum_distinct_dates": {
            "selection": min_selection_dates,
            "locked_holdout": min_holdout_dates,
        },
        "holdout_status": partitions.holdout_status,
        "scoreable_locked_holdout": partitions.holdout_status == "locked"
        and bool(partitions.locked_holdout.records),
        "blockers": blockers,
        "warnings": sorted(set(warnings)),
    }


def _apply_calibration_promotion_blockers(
    results: Sequence[SearchResult],
    *,
    calibration_blockers: Sequence[str],
) -> list[SearchResult]:
    output: list[SearchResult] = []
    for item in results:
        if _is_baseline_result(item):
            output.append(item)
            continue
        holdout = dict(item.holdout or {})
        existing = [
            str(value)
            for value in holdout.get("promotion_blockers", [])
            if isinstance(value, str)
        ]
        holdout.update(
            {
                "status": "failed_holdout",
                "proxy_passed": False,
                "promotion_capable": False,
                "promotion_blockers": sorted(
                    set(
                        [
                            *existing,
                            "calibration_health_blocks_promotion",
                            *calibration_blockers,
                        ]
                    )
                ),
            }
        )
        output.append(replace(item, holdout=holdout))
    return output


def run_large_parameter_search(
    session,
    *,
    coarse_candidates_count: int = 200_000,
    fine_candidates_count: int = 50_000,
    top_k: int = 100,
    fine_seeds: int = 20,
    seed: int = 20260614,
    limit: int | None = None,
    min_validation_actionable: int = 50,
    batch_log_interval: int = 1000,
    artifact_path: Path | None = None,
    cache_path: Path | None = None,
    discovery_start: date | None = None,
    discovery_end: date | None = None,
    selection_start: date | None = None,
    selection_end: date | None = None,
    holdout_start: date | None = None,
    holdout_end: date | None = None,
    allow_derived_partitions: bool = True,
    discovery_panel_dates: int = 24,
    stability_panel_dates: int = 60,
    stage1_survivors: int = 2_000,
    stage2_survivors: int = 100,
    finalists: int = 10,
    min_actionable_mode: MinActionableMode = "hard_gate",
    objective_profile: ObjectiveProfile = "research_ev_per_trade",
    search_campaign: SearchCampaign = "combined_small_delta",
    evidence_source: Literal["stored", "replay"] = "stored",
    replay_tiers: set[str] | None = None,
    replay_evidence_profile: ReplayEvidenceProfile = "promotion",
) -> dict[str, object]:
    service = PlanGenerationTuningService(session)
    baseline_version = service._resolve_active_config_version()  # noqa: SLF001
    active_config = normalize_plan_generation_tuning_config(baseline_version.config)
    if evidence_source == "replay":
        records = service._replay_eligible_records(  # noqa: SLF001
            ticker=None,
            setup_family=None,
            limit=limit,
            tiers=replay_tiers or {"tier_a"},
            evidence_profile=replay_evidence_profile,
        )
    else:
        records = service._eligible_records(ticker=None, setup_family=None, limit=limit)  # noqa: SLF001
    partitions = build_evidence_partitions(
        records,
        discovery_start=discovery_start,
        discovery_end=discovery_end,
        selection_start=selection_start,
        selection_end=selection_end,
        holdout_start=holdout_start,
        holdout_end=holdout_end,
        allow_derived=allow_derived_partitions,
    )
    requested = {
        "coarse_candidates": coarse_candidates_count,
        "fine_candidates": fine_candidates_count,
        "top_k": top_k,
        "fine_seeds": fine_seeds,
        "seed": seed,
        "limit": limit,
        "min_validation_actionable": min_validation_actionable,
        "discovery_panel_dates": discovery_panel_dates,
        "stability_panel_dates": stability_panel_dates,
        "stage1_survivors": stage1_survivors,
        "stage2_survivors": stage2_survivors,
        "finalists": finalists,
        "min_actionable_mode": min_actionable_mode,
        "objective_profile": objective_profile,
        "search_campaign": search_campaign,
        "evidence_source": evidence_source,
        "replay_tiers": sorted(replay_tiers or {"tier_a"}) if evidence_source == "replay" else [],
        "replay_evidence_profile": replay_evidence_profile if evidence_source == "replay" else None,
    }
    discovery_dates = select_stratified_dates(
        partitions.discovery.evidence_dates, limit=discovery_panel_dates, seed=seed
    )
    stability_dates = select_stratified_dates(
        partitions.discovery.evidence_dates, limit=stability_panel_dates, seed=seed + 11
    )
    discovery_records = records_for_dates(partitions.discovery.records, discovery_dates)
    stability_records = records_for_dates(partitions.discovery.records, stability_dates)
    if not discovery_records:
        discovery_records = partitions.discovery.records
    if not stability_records:
        stability_records = partitions.discovery.records
    calibration_health = {
        "schema_version": "large-search-calibration-health-v1",
        "discovery": _calibration_health_for_records(
            service, discovery_records, active_config
        ),
        "selection": _calibration_health_for_records(
            service, partitions.selection.records, active_config
        ),
        "locked_holdout": _calibration_health_for_records(
            service, partitions.locked_holdout.records, active_config
        ),
    }
    calibration_blockers = sorted(
        {
            f"{name}:{blocker}"
            for name, report in calibration_health.items()
            if name != "schema_version" and isinstance(report, dict)
            for blocker in report.get("blockers", [])
        }
    )
    calibration_blocks_promotion = any(
        isinstance(report, dict) and bool(report.get("blocks_promotion"))
        for name, report in calibration_health.items()
        if name != "schema_version"
    )

    stage_policy = {
        "discovery_panel_hash": stable_hash([item.isoformat() for item in discovery_dates]),
        "stability_panel_hash": stable_hash([item.isoformat() for item in stability_dates]),
        "stage1_survivors": min(max(1, stage1_survivors), max(1, top_k, coarse_candidates_count)),
        "stage2_survivors": min(max(1, stage2_survivors), max(1, stage1_survivors)),
        "finalists": min(max(1, finalists), max(1, stage2_survivors)),
        "objective": objective_profile,
        "search_campaign": search_campaign,
        "campaign_parameter_keys": list(CAMPAIGN_PARAMETER_KEYS[search_campaign]),
        "campaign_max_changed_keys": CAMPAIGN_MAX_CHANGED_KEYS[search_campaign],
    }
    evidence_preflight = _evidence_preflight(
        records=records,
        partitions=partitions,
        evidence_source=evidence_source,
        replay_evidence_profile=replay_evidence_profile,
    )
    cache_metadata = {
        "schema_version": 3,
        "baseline_config_version_id": baseline_version.id,
        "baseline_config_hash": _fingerprint(active_config),
        "partitions": partitions.payload(),
        "stage_policy": stage_policy,
        "requested": requested,
    }
    resolved_cache_path = cache_path or (
        artifact_path.with_suffix(".cache.jsonl") if artifact_path is not None else None
    )
    resume_cache = ResumeCache(resolved_cache_path, cache_metadata) if resolved_cache_path else None
    loaded_cache = (
        resume_cache.load_existing(
            top_k=max(stage_policy["stage1_survivors"], top_k),
            min_validation_actionable=min_validation_actionable,
            min_actionable_mode=min_actionable_mode,
        )
        if resume_cache
        else LoadedResumeCache(set(), [], False)
    )
    seen = set(loaded_cache.seen)
    loaded_by_stage: dict[str, list[SearchResult]] = {}
    for item in loaded_cache.results:
        loaded_by_stage.setdefault(item.stage, []).append(item)
    if resume_cache:
        resume_cache.initialize()

    stage_counts: dict[str, int] = {}
    try:
        coarse_top, stage_counts["coarse_discovery"] = evaluate_stream(
            service,
            coarse_candidates(
                active_config,
                count=coarse_candidates_count,
                seed=seed,
                campaign=search_campaign,
            ),
            active_config=active_config,
            search_records=discovery_records,
            validation_records=discovery_records,
            phase="coarse",
            stage="coarse_discovery",
            top_k=int(stage_policy["stage1_survivors"]),
            min_validation_actionable=min_validation_actionable,
            batch_log_interval=batch_log_interval,
            seen=seen,
            resume_cache=resume_cache,
            min_actionable_mode="rank_only",
            objective_profile=objective_profile,
            campaign=search_campaign,
        )
        coarse_top = _merged_top(
            loaded_by_stage.get("coarse_discovery", []),
            coarse_top,
            top_k=int(stage_policy["stage1_survivors"]),
            min_validation_actionable=min_validation_actionable,
            min_actionable_mode="rank_only",
            objective_profile=objective_profile,
        )
        fine_top, stage_counts["fine_discovery"] = evaluate_stream(
            service,
            fine_candidates(
                active_config,
                coarse_top[: max(1, fine_seeds)],
                count=fine_candidates_count,
                seed=seed + 1,
                campaign=search_campaign,
            ),
            active_config=active_config,
            search_records=discovery_records,
            validation_records=discovery_records,
            phase="fine",
            stage="fine_discovery",
            top_k=int(stage_policy["stage1_survivors"]),
            min_validation_actionable=min_validation_actionable,
            batch_log_interval=batch_log_interval,
            seen=seen,
            resume_cache=resume_cache,
            min_actionable_mode="rank_only",
            objective_profile=objective_profile,
            campaign=search_campaign,
        )
        fine_top = _merged_top(
            loaded_by_stage.get("fine_discovery", []),
            fine_top,
            top_k=int(stage_policy["stage1_survivors"]),
            min_validation_actionable=min_validation_actionable,
            min_actionable_mode="rank_only",
            objective_profile=objective_profile,
        )
        stage1 = _deduplicated_top(
            [*coarse_top, *fine_top],
            active_config=active_config,
            top_k=int(stage_policy["stage1_survivors"]),
            min_validation_actionable=min_validation_actionable,
            min_actionable_mode="rank_only",
            objective_profile=objective_profile,
        )
        stage2, stage_counts["stability_screen"] = _evaluate_stability_stage(
            service,
            [item.config for item in stage1],
            active_config=active_config,
            records=stability_records,
            stage="stability_screen",
            top_k=int(stage_policy["stage2_survivors"]),
            min_validation_actionable=min_validation_actionable,
            min_fold_actionable=max(1, min_validation_actionable // 6),
            fold_count=6,
            batch_log_interval=max(1, batch_log_interval // 10),
            seen=seen,
            resume_cache=resume_cache,
            min_actionable_mode=min_actionable_mode,
            objective_profile=objective_profile,
            campaign=search_campaign,
        )
        stage2 = _merged_top(
            loaded_by_stage.get("stability_screen", []),
            stage2,
            top_k=int(stage_policy["stage2_survivors"]),
            min_validation_actionable=min_validation_actionable,
            min_actionable_mode=min_actionable_mode,
            objective_profile=objective_profile,
        )
        selection_records = list(partitions.selection.records)
        if selection_records:
            stage3, stage_counts["selection_walk_forward"] = _evaluate_walk_forward_stage(
                service,
                [item.config for item in stage2],
                active_config=active_config,
                records=selection_records,
                top_k=int(stage_policy["finalists"]),
                min_validation_actionable=min_validation_actionable,
                seen=seen,
                resume_cache=resume_cache,
                min_actionable_mode=min_actionable_mode,
                objective_profile=objective_profile,
                campaign=search_campaign,
            )
            stage3 = _merged_top(
                loaded_by_stage.get("selection_walk_forward", []),
                stage3,
                top_k=int(stage_policy["finalists"]),
                min_validation_actionable=min_validation_actionable,
                min_actionable_mode=min_actionable_mode,
                objective_profile=objective_profile,
            )
        else:
            stage_counts["selection_walk_forward"] = 0
            stage3 = stage2[: int(stage_policy["finalists"])]
        final_results = _evaluate_locked_holdout(
            service,
            stage3,
            active_config=active_config,
            records=partitions.locked_holdout.records,
            holdout_status=partitions.holdout_status,
            min_validation_actionable=min_validation_actionable,
            objective_profile=objective_profile,
        )
        if objective_profile == "promotion_candidate" and calibration_blocks_promotion:
            final_results = _apply_calibration_promotion_blockers(
                final_results,
                calibration_blockers=calibration_blockers,
            )
    finally:
        if resume_cache:
            resume_cache.close()

    stages = {
        "preflight": {
            "status": evidence_preflight["status"],
            "input_candidate_count": coarse_candidates_count + fine_candidates_count,
            "note": "normalization and config-hash deduplication are applied while streaming",
            "evidence": evidence_preflight,
        },
        "broad_discovery": {
            "status": "completed",
            "date_panel_hash": stage_policy["discovery_panel_hash"],
            "distinct_date_count": len(discovery_dates),
            "record_count": len(discovery_records),
            "evaluated": stage_counts.get("coarse_discovery", 0)
            + stage_counts.get("fine_discovery", 0),
            "survivor_count": len(stage1),
        },
        "stability_screen": {
            "status": "completed",
            "date_panel_hash": stage_policy["stability_panel_hash"],
            "distinct_date_count": len(stability_dates),
            "record_count": len(stability_records),
            "evaluated": stage_counts.get("stability_screen", 0),
            "survivor_count": len(stage2),
            "stable_survivor_count": sum(item.stability_eligible for item in stage2),
        },
        "selection_walk_forward": {
            "status": "completed" if partitions.selection.records else "skipped_thin_evidence",
            "partition_hash": partitions.selection.record_hash,
            "evaluated": stage_counts.get("selection_walk_forward", 0),
            "survivor_count": len(stage3),
        },
        "locked_holdout": {
            "status": partitions.holdout_status,
            "partition_hash": partitions.locked_holdout.record_hash,
            "evaluated": len(final_results) if partitions.locked_holdout.records else 0,
            "canonical_replay_required_count": sum(
                bool((item.holdout or {}).get("canonical_candidate_replay_required"))
                for item in final_results
            ),
        },
    }
    artifact: dict[str, object] = {
        "schema_version": 3,
        "generated_at": datetime.now(UTC).isoformat(),
        "run_role": evidence_preflight["run_role"],
        "promotion_capable": False,
        "objective_profile": objective_profile,
        "min_actionable_mode": min_actionable_mode,
        "search_campaign": search_campaign,
        "baseline_config_version_id": baseline_version.id,
        "baseline_config": active_config,
        "baseline_config_hash": _fingerprint(active_config),
        "eligible_record_count": len(records),
        "search_record_count": len(partitions.discovery.records),
        "validation_record_count": len(partitions.selection.records),
        "holdout_record_count": len(partitions.locked_holdout.records),
        "partitions": partitions.payload(),
        "stage_policy": stage_policy,
        "stages": stages,
        "requested": requested,
        "evidence_preflight": evidence_preflight,
        "evaluated": {
            **stage_counts,
            "loaded_from_cache": len(loaded_cache.results),
            "unique_stage_evaluations": len(seen),
        },
        "top_candidates": [item.payload() for item in final_results],
        "improvement_finalist_count": sum(1 for item in final_results if item.changed_keys),
        "baseline_included": any(not item.changed_keys for item in final_results),
        "resume_cache_path": str(resolved_cache_path) if resolved_cache_path else None,
        "resume_cache_compatible": loaded_cache.compatible,
        "locked_holdout_status": partitions.holdout_status,
        "calibration_health": calibration_health,
        "calibration_blocks_promotion": calibration_blocks_promotion,
        "calibration_blockers": calibration_blockers,
        "holdout_contamination_status": "clean_not_used_for_refinement",
        "note": (
            "Research artifact only. Discovery and selection are not holdout evidence. "
            "Geometry-changing finalists require canonical candidate replay before "
            "promotion review."
        ),
    }
    if artifact_path is not None:
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")
        artifact["artifact_path"] = str(artifact_path)
    return artifact


def _changed_keys(config: dict[str, float], active_config: dict[str, float]) -> list[str]:
    return [
        key
        for key, value in config.items()
        if round(float(value), 4) != round(float(active_config.get(key, value)), 4)
    ]


def _merged_top(
    first: Sequence[SearchResult],
    second: Sequence[SearchResult],
    *,
    top_k: int,
    min_validation_actionable: int,
    min_actionable_mode: MinActionableMode,
    objective_profile: ObjectiveProfile,
) -> list[SearchResult]:
    return _deduplicated_top(
        [*first, *second],
        active_config=None,
        top_k=top_k,
        min_validation_actionable=min_validation_actionable,
        min_actionable_mode=min_actionable_mode,
        objective_profile=objective_profile,
    )


def _deduplicated_top(
    results: Sequence[SearchResult],
    *,
    active_config: dict[str, float] | None,
    top_k: int,
    min_validation_actionable: int,
    min_actionable_mode: MinActionableMode,
    objective_profile: ObjectiveProfile,
) -> list[SearchResult]:
    best_by_config: dict[str, SearchResult] = {}
    for item in results:
        if not _passes_min_actionable_gate(
            item,
            min_validation_actionable=min_validation_actionable,
            min_actionable_mode=min_actionable_mode,
        ):
            continue
        fingerprint = _fingerprint(item.config)
        previous = best_by_config.get(fingerprint)
        if previous is None or _rank_key(
            item,
            min_validation_actionable=min_validation_actionable,
            objective_profile=objective_profile,
        ) > _rank_key(
            previous,
            min_validation_actionable=min_validation_actionable,
            objective_profile=objective_profile,
        ):
            best_by_config[fingerprint] = item
    ordered = sorted(
        best_by_config.values(),
        key=lambda item: _rank_key(
            item,
            min_validation_actionable=min_validation_actionable,
            objective_profile=objective_profile,
        ),
        reverse=True,
    )
    if active_config is not None and _fingerprint(active_config) not in {
        _fingerprint(item.config) for item in ordered[:top_k]
    }:
        baseline = next(
            (item for item in ordered if _fingerprint(item.config) == _fingerprint(active_config)),
            None,
        )
        selected = ordered[: max(0, top_k - 1)]
        if baseline:
            selected.append(baseline)
        return selected
    return ordered[:top_k]


def _ensure_baseline(
    results: list[SearchResult], baseline: SearchResult | None, *, top_k: int
) -> list[SearchResult]:
    if baseline is None or any(item.config == baseline.config for item in results):
        return results
    retained = results[: max(0, top_k - 1)] if len(results) >= top_k else list(results)
    return [*retained, baseline]


def _log_progress(
    stage: str,
    phase: str,
    evaluated: int,
    skipped_duplicates: int,
    started: datetime,
    top: Sequence[SearchResult],
) -> None:
    elapsed = (datetime.now(UTC) - started).total_seconds()
    best = top[0] if top else None
    print(
        json.dumps(
            {
                "stage": stage,
                "phase": phase,
                "evaluated": evaluated,
                "skipped_duplicates": skipped_duplicates,
                "elapsed_seconds": round(elapsed, 1),
                "best_win_rate_percent": round(best.validation_win_rate * 100.0, 2)
                if best
                else None,
                "best_expected_value": round(best.validation_expected_value, 4) if best else None,
            },
            sort_keys=True,
        ),
        flush=True,
    )


def _parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Memory-safe staged plan-generation parameter search"
    )
    parser.add_argument("--coarse-candidates", type=int, default=200_000)
    parser.add_argument("--fine-candidates", type=int, default=50_000)
    parser.add_argument("--top-k", type=int, default=100)
    parser.add_argument("--fine-seeds", type=int, default=20)
    parser.add_argument("--seed", type=int, default=20260614)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--min-validation-actionable", type=int, default=50)
    parser.add_argument("--batch-log-interval", type=int, default=1000)
    parser.add_argument("--discovery-start")
    parser.add_argument("--discovery-end")
    parser.add_argument("--selection-start")
    parser.add_argument("--selection-end")
    parser.add_argument("--holdout-start")
    parser.add_argument("--holdout-end")
    parser.add_argument("--require-explicit-partitions", action="store_true")
    parser.add_argument("--discovery-panel-dates", type=int, default=24)
    parser.add_argument("--stability-panel-dates", type=int, default=60)
    parser.add_argument("--stage1-survivors", type=int, default=2_000)
    parser.add_argument("--stage2-survivors", type=int, default=100)
    parser.add_argument("--finalists", type=int, default=10)
    parser.add_argument(
        "--min-actionable-mode",
        choices=("rank_only", "hard_gate"),
        default="hard_gate",
    )
    parser.add_argument(
        "--objective-profile",
        choices=("research_precision", "research_ev_per_trade", "promotion_candidate"),
        default="research_ev_per_trade",
    )
    parser.add_argument(
        "--search-campaign",
        choices=tuple(CAMPAIGN_PARAMETER_KEYS),
        default="combined_small_delta",
    )
    parser.add_argument(
        "--evidence-source",
        choices=("stored", "replay"),
        default="stored",
    )
    parser.add_argument(
        "--replay-tier",
        action="append",
        default=[],
        help=(
            "Replay eligibility tier to include when --evidence-source=replay. "
            "May be passed multiple times."
        ),
    )
    parser.add_argument(
        "--replay-evidence-profile",
        choices=("promotion", "phantom_selectivity", "research"),
        default="promotion",
        help=(
            "Replay profile for large search. Promotion keeps only closed intraday "
            "trade labels; phantom_selectivity is research-only."
        ),
    )
    parser.add_argument(
        "--artifact",
        type=Path,
        default=Path("artifacts/large-plan-generation-parameter-search.json"),
    )
    parser.add_argument("--cache", type=Path, default=None)
    args = parser.parse_args()

    session = SessionLocal()
    try:
        artifact = run_large_parameter_search(
            session,
            coarse_candidates_count=args.coarse_candidates,
            fine_candidates_count=args.fine_candidates,
            top_k=args.top_k,
            fine_seeds=args.fine_seeds,
            seed=args.seed,
            limit=args.limit,
            min_validation_actionable=args.min_validation_actionable,
            batch_log_interval=args.batch_log_interval,
            artifact_path=args.artifact,
            cache_path=args.cache,
            discovery_start=_parse_date(args.discovery_start),
            discovery_end=_parse_date(args.discovery_end),
            selection_start=_parse_date(args.selection_start),
            selection_end=_parse_date(args.selection_end),
            holdout_start=_parse_date(args.holdout_start),
            holdout_end=_parse_date(args.holdout_end),
            allow_derived_partitions=not args.require_explicit_partitions,
            discovery_panel_dates=args.discovery_panel_dates,
            stability_panel_dates=args.stability_panel_dates,
            stage1_survivors=args.stage1_survivors,
            stage2_survivors=args.stage2_survivors,
            finalists=args.finalists,
            min_actionable_mode=args.min_actionable_mode,
            objective_profile=args.objective_profile,
            search_campaign=args.search_campaign,
            evidence_source=args.evidence_source,
            replay_tiers=set(args.replay_tier or ["tier_a"]),
            replay_evidence_profile=args.replay_evidence_profile,
        )
        print(
            json.dumps(
                {
                    "artifact": str(args.artifact),
                    "best": artifact["top_candidates"][0] if artifact["top_candidates"] else None,
                },
                indent=2,
                sort_keys=True,
            )
        )
    except EvidencePartitionError as exc:
        raise SystemExit(f"invalid evidence partitions: {exc}") from exc
    finally:
        session.close()


if __name__ == "__main__":
    main()
