#!/usr/bin/env python
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import random
from collections.abc import Iterable
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path

from trade_proposer_app.db import SessionLocal
from trade_proposer_app.services.plan_generation_tuning import PlanGenerationTuningService
from trade_proposer_app.services.plan_generation_tuning_parameters import (
    PARAMETER_BY_KEY,
    normalize_plan_generation_tuning_config,
)

Fingerprint = str


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

    @property
    def validation_win_rate(self) -> float:
        return (
            self.validation_win_count / self.validation_actionable_count
            if self.validation_actionable_count
            else 0.0
        )

    @property
    def search_win_rate(self) -> float:
        return (
            self.search_win_count / self.search_actionable_count
            if self.search_actionable_count
            else 0.0
        )

    def payload(self) -> dict[str, object]:
        return {
            "phase": self.phase,
            "config": self.config,
            "changed_keys": self.changed_keys,
            "search_actionable_count": self.search_actionable_count,
            "search_win_count": self.search_win_count,
            "search_win_rate_percent": round(self.search_win_rate * 100.0, 2),
            "search_expected_value": round(self.search_expected_value, 4),
            "search_ambiguous_count": self.search_ambiguous_count,
            "validation_actionable_count": self.validation_actionable_count,
            "validation_win_count": self.validation_win_count,
            "validation_win_rate_percent": round(self.validation_win_rate * 100.0, 2),
            "validation_expected_value": round(self.validation_expected_value, 4),
            "validation_ambiguous_count": self.validation_ambiguous_count,
        }


@dataclass(frozen=True)
class LoadedResumeCache:
    seen: set[Fingerprint]
    results: list[SearchResult]
    compatible: bool


class ResumeCache:
    schema_version = 1

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
        self, *, top_k: int | None = None, min_validation_actionable: int = 1
    ) -> LoadedResumeCache:
        if not self.path.exists():
            return LoadedResumeCache(seen=set(), results=[], compatible=False)
        seen: set[Fingerprint] = set()
        results: list[SearchResult] = []
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
                fp = _fingerprint(result.config)
                if fp in seen:
                    continue
                seen.add(fp)
                if top_k is None:
                    results.append(result)
                else:
                    _keep_top(
                        results,
                        result,
                        top_k=max(1, top_k),
                        min_validation_actionable=min_validation_actionable,
                    )
        return LoadedResumeCache(seen=seen, results=results, compatible=compatible)

    def append_result(self, result: SearchResult) -> None:
        if self._handle is None:
            self.initialize()
        assert self._handle is not None
        self._handle.write(
            json.dumps(
                {
                    "type": "result",
                    "fingerprint": _fingerprint(result.config),
                    "result": asdict(result),
                    "evaluated_at": datetime.now(timezone.utc).isoformat(),
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


def _rank_key(result: SearchResult, *, min_validation_actionable: int) -> tuple[object, ...]:
    enough_validation = result.validation_actionable_count >= min_validation_actionable
    return (
        enough_validation,
        result.validation_expected_value,
        result.validation_win_rate,
        result.search_expected_value,
        result.search_win_rate,
        -result.validation_ambiguous_count,
        -len(result.changed_keys),
    )


def _keep_top(
    top: list[SearchResult],
    result: SearchResult,
    *,
    top_k: int,
    min_validation_actionable: int,
) -> list[SearchResult]:
    top.append(result)
    top.sort(
        key=lambda item: _rank_key(item, min_validation_actionable=min_validation_actionable),
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


def _bounded(key: str, value: float) -> float:
    definition = PARAMETER_BY_KEY[key]
    return round(max(definition.exploration_min, min(definition.exploration_max, value)), 4)


def _random_grid_value(key: str, rng: random.Random) -> float:
    definition = PARAMETER_BY_KEY[key]
    steps = int(round((definition.exploration_max - definition.exploration_min) / definition.step))
    return round(definition.exploration_min + (rng.randint(0, max(0, steps)) * definition.step), 4)


def coarse_candidates(
    active_config: dict[str, float], *, count: int, seed: int
) -> Iterable[dict[str, float]]:
    rng = random.Random(seed)
    keys = tuple(PARAMETER_BY_KEY.keys())
    yield normalize_plan_generation_tuning_config(active_config)
    for _ in range(max(0, count - 1)):
        config = dict(active_config)
        for key in keys:
            config[key] = _random_grid_value(key, rng)
        yield normalize_plan_generation_tuning_config(config)


def fine_candidates(
    active_config: dict[str, float],
    seeds: list[SearchResult],
    *,
    count: int,
    seed: int,
) -> Iterable[dict[str, float]]:
    if not seeds or count <= 0:
        return
    rng = random.Random(seed)
    keys = tuple(PARAMETER_BY_KEY.keys())
    emitted = 0
    seed_index = 0
    while emitted < count:
        source = seeds[seed_index % len(seeds)]
        seed_index += 1
        config = dict(active_config)
        config.update(source.config)
        for key in keys:
            definition = PARAMETER_BY_KEY[key]
            radius = max(
                definition.step,
                (definition.exploration_max - definition.exploration_min) * 0.08,
            )
            jitter = rng.uniform(-radius, radius)
            stepped = round((float(config[key]) + jitter) / definition.step) * definition.step
            config[key] = _bounded(key, stepped)
        emitted += 1
        yield normalize_plan_generation_tuning_config(config)


def evaluate_stream(
    service: PlanGenerationTuningService,
    candidates: Iterable[dict[str, float]],
    *,
    active_config: dict[str, float],
    search_records: list,
    validation_records: list,
    phase: str,
    top_k: int,
    min_validation_actionable: int,
    batch_log_interval: int,
    seen: set[Fingerprint],
    resume_cache: ResumeCache | None = None,
) -> tuple[list[SearchResult], int]:
    top: list[SearchResult] = []
    evaluated = 0
    skipped_duplicates = 0
    started = datetime.now(timezone.utc)
    for config in candidates:
        fp = _fingerprint(config)
        if fp in seen:
            skipped_duplicates += 1
            continue
        seen.add(fp)
        search_actionable, search_win, search_ev, search_ambiguous = service._score_records(
            search_records, config
        )  # noqa: SLF001 - offline research script
        validation_actionable, validation_win, validation_ev, validation_ambiguous = (
            service._score_records(validation_records, config)
        )  # noqa: SLF001 - offline research script
        changed_keys = [
            key
            for key, value in config.items()
            if round(float(value), 4) != round(float(active_config.get(key, value)), 4)
        ]
        result = SearchResult(
            phase=phase,
            config=config,
            changed_keys=changed_keys,
            search_actionable_count=search_actionable,
            search_win_count=search_win,
            search_expected_value=search_ev,
            search_ambiguous_count=search_ambiguous,
            validation_actionable_count=validation_actionable,
            validation_win_count=validation_win,
            validation_expected_value=validation_ev,
            validation_ambiguous_count=validation_ambiguous,
        )
        _keep_top(
            top,
            result,
            top_k=top_k,
            min_validation_actionable=min_validation_actionable,
        )
        if resume_cache is not None:
            resume_cache.append_result(result)
        evaluated += 1
        if evaluated % batch_log_interval == 0:
            elapsed = (datetime.now(timezone.utc) - started).total_seconds()
            best = top[0] if top else None
            print(
                json.dumps(
                    {
                        "phase": phase,
                        "evaluated": evaluated,
                        "skipped_duplicates": skipped_duplicates,
                        "elapsed_seconds": round(elapsed, 1),
                        "best_validation_ev": round(best.validation_expected_value, 4)
                        if best
                        else None,
                        "best_validation_win_rate_percent": round(
                            best.validation_win_rate * 100.0, 2
                        )
                        if best
                        else None,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
            gc.collect()
            service._memory_guard(stage=f"large-search-{phase}-{evaluated}")  # noqa: SLF001 - offline research script
    return top, evaluated


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
) -> dict[str, object]:
    service = PlanGenerationTuningService(session)
    baseline_version = service._resolve_active_config_version()  # noqa: SLF001 - offline research script
    active_config = normalize_plan_generation_tuning_config(baseline_version.config)
    records = service._eligible_records(ticker=None, setup_family=None, limit=limit)  # noqa: SLF001 - offline research script
    search_records, validation_records = service._split_records(
        records, min_validation=min_validation_actionable
    )  # noqa: SLF001 - offline research script
    requested = {
        "coarse_candidates": coarse_candidates_count,
        "fine_candidates": fine_candidates_count,
        "top_k": top_k,
        "fine_seeds": fine_seeds,
        "seed": seed,
        "limit": limit,
        "min_validation_actionable": min_validation_actionable,
    }
    cache_metadata = {
        "baseline_config_version_id": baseline_version.id,
        "active_config": active_config,
        "search_record_count": len(search_records),
        "validation_record_count": len(validation_records),
        "requested": requested,
    }
    resolved_cache_path = cache_path
    if resolved_cache_path is None and artifact_path is not None:
        resolved_cache_path = artifact_path.with_suffix(".cache.jsonl")
    resume_cache = ResumeCache(resolved_cache_path, cache_metadata) if resolved_cache_path else None
    loaded_cache = (
        resume_cache.load_existing(top_k=top_k, min_validation_actionable=min_validation_actionable)
        if resume_cache is not None
        else LoadedResumeCache(set(), [], False)
    )
    seen: set[Fingerprint] = set(loaded_cache.seen)
    if resume_cache is not None:
        resume_cache.initialize()
    loaded_coarse_top: list[SearchResult] = []
    loaded_fine_top: list[SearchResult] = []
    for result in loaded_cache.results:
        target = loaded_fine_top if result.phase == "fine" else loaded_coarse_top
        _keep_top(
            target,
            result,
            top_k=top_k,
            min_validation_actionable=min_validation_actionable,
        )
    try:
        coarse_top, coarse_evaluated = evaluate_stream(
            service,
            coarse_candidates(active_config, count=coarse_candidates_count, seed=seed),
            active_config=active_config,
            search_records=search_records,
            validation_records=validation_records,
            phase="coarse",
            top_k=top_k,
            min_validation_actionable=min_validation_actionable,
            batch_log_interval=max(1, batch_log_interval),
            seen=seen,
            resume_cache=resume_cache,
        )
        coarse_top = loaded_coarse_top + coarse_top
        coarse_top.sort(
            key=lambda item: _rank_key(item, min_validation_actionable=min_validation_actionable),
            reverse=True,
        )
        coarse_top = coarse_top[:top_k]
        fine_top, fine_evaluated = evaluate_stream(
            service,
            fine_candidates(
                active_config,
                coarse_top[: max(1, fine_seeds)],
                count=fine_candidates_count,
                seed=seed + 1,
            ),
            active_config=active_config,
            search_records=search_records,
            validation_records=validation_records,
            phase="fine",
            top_k=top_k,
            min_validation_actionable=min_validation_actionable,
            batch_log_interval=max(1, batch_log_interval),
            seen=seen,
            resume_cache=resume_cache,
        )
    finally:
        if resume_cache is not None:
            resume_cache.close()
    fine_top = loaded_fine_top + fine_top
    fine_top.sort(
        key=lambda item: _rank_key(item, min_validation_actionable=min_validation_actionable),
        reverse=True,
    )
    fine_top = fine_top[:top_k]
    combined = coarse_top + fine_top
    combined.sort(
        key=lambda item: _rank_key(item, min_validation_actionable=min_validation_actionable),
        reverse=True,
    )
    combined = combined[:top_k]
    artifact = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "baseline_config_version_id": baseline_version.id,
        "active_config": active_config,
        "eligible_record_count": len(records),
        "search_record_count": len(search_records),
        "validation_record_count": len(validation_records),
        "requested": requested,
        "evaluated": {
            "coarse": coarse_evaluated,
            "fine": fine_evaluated,
            "loaded_from_cache": len(loaded_cache.results),
            "unique_total": len(seen),
        },
        "top_candidates": [item.payload() for item in combined],
        "resume_cache_path": str(resolved_cache_path) if resolved_cache_path else None,
        "resume_cache_compatible": loaded_cache.compatible,
        "note": (
            "Research artifact only. Do not promote without normal holdout/walk-forward/paper "
            "validation."
        ),
    }
    if artifact_path is not None:
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")
        artifact["artifact_path"] = str(artifact_path)
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Memory-safe large plan-generation parameter search"
    )
    parser.add_argument("--coarse-candidates", type=int, default=200_000)
    parser.add_argument("--fine-candidates", type=int, default=50_000)
    parser.add_argument("--top-k", type=int, default=100)
    parser.add_argument("--fine-seeds", type=int, default=20)
    parser.add_argument("--seed", type=int, default=20260614)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--min-validation-actionable", type=int, default=50)
    parser.add_argument("--batch-log-interval", type=int, default=1000)
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
    finally:
        session.close()


if __name__ == "__main__":
    main()
