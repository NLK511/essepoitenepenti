from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.large_plan_generation_parameter_search import (
    ResumeCache,
    SearchResult,
    _fingerprint,
    _keep_top,
    coarse_candidates,
    evaluate_stream,
    fine_candidates,
    run_large_parameter_search,
)
from trade_proposer_app.services.plan_generation_tuning_parameters import (
    normalize_plan_generation_tuning_config,
)


def test_large_search_candidate_stream_is_deterministic_and_bounded() -> None:
    active = normalize_plan_generation_tuning_config(None)

    first = list(coarse_candidates(active, count=5, seed=123))
    second = list(coarse_candidates(active, count=5, seed=123))

    assert first == second
    assert first[0] == active
    assert len(first) == 5
    for config in first:
        assert 40.0 <= config["global.actionable_confidence_floor_percent"] <= 70.0


def test_large_search_ranks_precision_before_expected_value() -> None:
    top: list[SearchResult] = []
    for index, (wins, ev) in enumerate([(5, 10.0), (7, 2.0), (6, 3.0)]):
        _keep_top(
            top,
            SearchResult(
                phase="coarse",
                config={"x": float(index)},
                changed_keys=["x"],
                search_actionable_count=10,
                search_win_count=wins,
                search_expected_value=ev,
                search_ambiguous_count=0,
                validation_actionable_count=10,
                validation_win_count=wins,
                validation_expected_value=ev,
                validation_ambiguous_count=0,
            ),
            top_k=2,
            min_validation_actionable=5,
        )

    assert [item.validation_win_count for item in top] == [7, 6]


def test_large_search_ev_per_trade_objective_ranks_ev_per_actionable_first() -> None:
    top: list[SearchResult] = []
    for wins, actionable, ev in [(8, 20, 8.0), (4, 5, 5.0)]:
        _keep_top(
            top,
            SearchResult(
                phase="selection_walk_forward",
                config={"wins": float(wins)},
                changed_keys=["wins"],
                search_actionable_count=actionable,
                search_win_count=wins,
                search_expected_value=ev,
                search_ambiguous_count=0,
                validation_actionable_count=actionable,
                validation_win_count=wins,
                validation_expected_value=ev,
                validation_ambiguous_count=0,
            ),
            top_k=2,
            min_validation_actionable=1,
            objective_profile="research_ev_per_trade",
        )

    assert top[0].validation_expected_value_per_actionable == 1.0


def test_large_search_hard_gate_rejects_low_sample_non_baseline_but_keeps_baseline() -> None:
    active = normalize_plan_generation_tuning_config(None)
    top: list[SearchResult] = []

    _keep_top(
        top,
        SearchResult(
            phase="selection_walk_forward",
            config=active,
            changed_keys=[],
            search_actionable_count=1,
            search_win_count=0,
            search_expected_value=-1.0,
            search_ambiguous_count=99,
            validation_actionable_count=1,
            validation_win_count=0,
            validation_expected_value=-1.0,
            validation_ambiguous_count=99,
            stage="selection_walk_forward",
        ),
        top_k=5,
        min_validation_actionable=50,
        min_actionable_mode="hard_gate",
    )
    _keep_top(
        top,
        SearchResult(
            phase="selection_walk_forward",
            config={**active, "global.actionable_confidence_floor_percent": 50.0},
            changed_keys=["global.actionable_confidence_floor_percent"],
            search_actionable_count=12,
            search_win_count=7,
            search_expected_value=28.0,
            search_ambiguous_count=88,
            validation_actionable_count=12,
            validation_win_count=7,
            validation_expected_value=28.0,
            validation_ambiguous_count=88,
            stage="selection_walk_forward",
        ),
        top_k=5,
        min_validation_actionable=50,
        min_actionable_mode="hard_gate",
    )

    assert len(top) == 1
    assert top[0].changed_keys == []


def test_large_search_hard_gate_rejects_unstable_non_baseline() -> None:
    active = normalize_plan_generation_tuning_config(None)
    top: list[SearchResult] = []

    _keep_top(
        top,
        SearchResult(
            phase="stability_screen",
            stage="stability_screen",
            config={**active, "global.actionable_confidence_floor_percent": 50.0},
            changed_keys=["global.actionable_confidence_floor_percent"],
            search_actionable_count=80,
            search_win_count=50,
            search_expected_value=20.0,
            search_ambiguous_count=0,
            validation_actionable_count=80,
            validation_win_count=50,
            validation_expected_value=20.0,
            validation_ambiguous_count=0,
            stability_eligible=False,
            stability={"qualified_fold_count": 1, "reasons": ["insufficient_qualified_folds"]},
        ),
        top_k=5,
        min_validation_actionable=50,
        min_actionable_mode="hard_gate",
    )

    assert top == []


def test_large_search_rank_only_keeps_low_sample_research_candidate() -> None:
    active = normalize_plan_generation_tuning_config(None)
    top: list[SearchResult] = []

    _keep_top(
        top,
        SearchResult(
            phase="selection_walk_forward",
            config={**active, "global.actionable_confidence_floor_percent": 50.0},
            changed_keys=["global.actionable_confidence_floor_percent"],
            search_actionable_count=12,
            search_win_count=7,
            search_expected_value=28.0,
            search_ambiguous_count=88,
            validation_actionable_count=12,
            validation_win_count=7,
            validation_expected_value=28.0,
            validation_ambiguous_count=88,
            stage="selection_walk_forward",
        ),
        top_k=5,
        min_validation_actionable=50,
        min_actionable_mode="rank_only",
    )

    assert len(top) == 1
    assert top[0].changed_keys == ["global.actionable_confidence_floor_percent"]


def test_large_search_resume_cache_reloads_compatible_results(tmp_path: Path) -> None:
    cache_path = tmp_path / "large-search.cache.jsonl"
    active = normalize_plan_generation_tuning_config(None)
    metadata = {
        "baseline_config_version_id": 5,
        "active_config": active,
        "search_record_count": 10,
        "validation_record_count": 5,
        "requested": {"coarse_candidates": 2, "fine_candidates": 0},
    }
    result = SearchResult(
        phase="coarse",
        config=active,
        changed_keys=[],
        search_actionable_count=10,
        search_win_count=5,
        search_expected_value=1.0,
        search_ambiguous_count=0,
        validation_actionable_count=5,
        validation_win_count=3,
        validation_expected_value=2.0,
        validation_ambiguous_count=0,
    )

    cache = ResumeCache(cache_path, metadata)
    cache.initialize()
    cache.append_result(result)
    cache.close()

    loaded = ResumeCache(cache_path, metadata).load_existing()

    assert _fingerprint(active) in loaded.seen
    assert loaded.results[0].validation_expected_value == 2.0


def test_large_search_combined_small_delta_campaign_limits_changed_keys() -> None:
    active = normalize_plan_generation_tuning_config(None)

    candidates = list(
        coarse_candidates(active, count=25, seed=123, campaign="combined_small_delta")
    )

    assert len(candidates) == 25
    for candidate in candidates:
        changed = [
            key
            for key, value in candidate.items()
            if round(value, 4) != round(active.get(key, value), 4)
        ]
        assert len(changed) <= 3


def test_large_search_resume_cache_skips_already_evaluated_candidate(tmp_path: Path) -> None:
    class FakeService:
        calls = 0

        def _score_records(self, records, config):  # noqa: ANN001, ANN202, SLF001
            self.calls += 1
            return 1, 1, 1.0, 0

        def _memory_guard(self, stage: str) -> None:  # noqa: ARG002
            return None

    active = normalize_plan_generation_tuning_config(None)
    cached_result = SearchResult(
        phase="coarse",
        config=active,
        changed_keys=[],
        search_actionable_count=1,
        search_win_count=1,
        search_expected_value=1.0,
        search_ambiguous_count=0,
        validation_actionable_count=1,
        validation_win_count=1,
        validation_expected_value=1.0,
        validation_ambiguous_count=0,
    )
    metadata = {"baseline_config_version_id": 5}
    cache = ResumeCache(tmp_path / "cache.jsonl", metadata)
    cache.initialize()
    cache.append_result(cached_result)
    cache.close()
    loaded = cache.load_existing()
    service = FakeService()

    top, evaluated = evaluate_stream(
        service,  # type: ignore[arg-type]
        [active],
        active_config=active,
        search_records=[],
        validation_records=[],
        phase="coarse",
        top_k=5,
        min_validation_actionable=1,
        batch_log_interval=10,
        seen=loaded.seen,
        resume_cache=None,
    )

    assert evaluated == 0
    assert service.calls == 0
    assert top == []


def test_staged_search_bounds_expensive_survivors_and_keeps_partitions_disjoint() -> None:
    active = normalize_plan_generation_tuning_config(None)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    records = [
        SimpleNamespace(
            plan=SimpleNamespace(
                id=index + 1, ticker="TEST", computed_at=start + timedelta(days=index)
            )
        )
        for index in range(100)
    ]

    class FakeService:
        def __init__(self, session) -> None:  # noqa: ANN001, ARG002
            pass

        def _resolve_active_config_version(self):  # noqa: ANN202
            return SimpleNamespace(id=7, config=active)

        def _eligible_records(self, **kwargs):  # noqa: ANN003, ANN202
            return records

        def _score_records(self, rows, config):  # noqa: ANN001, ANN202
            count = len(rows)
            wins = count
            return count, wins, round(count * 0.1, 4), 0

        def _memory_guard(self, stage):  # noqa: ANN001, ANN202, ARG002
            return None

    with patch(
        "scripts.large_plan_generation_parameter_search.PlanGenerationTuningService",
        FakeService,
    ):
        artifact = run_large_parameter_search(
            object(),
            coarse_candidates_count=6,
            fine_candidates_count=3,
            top_k=5,
            fine_seeds=2,
            min_validation_actionable=1,
            stage1_survivors=4,
            stage2_survivors=3,
            finalists=2,
            discovery_panel_dates=12,
            stability_panel_dates=24,
        )

    assert artifact["schema_version"] == 2
    assert artifact["promotion_capable"] is False
    assert artifact["objective_profile"] == "research_ev_per_trade"
    assert artifact["min_actionable_mode"] == "hard_gate"
    assert artifact["baseline_included"] is True
    assert artifact["improvement_finalist_count"] <= len(artifact["top_candidates"])
    assert artifact["stages"]["broad_discovery"]["survivor_count"] <= 4
    assert artifact["stages"]["stability_screen"]["survivor_count"] <= 3
    assert len(artifact["top_candidates"]) <= 2
    partitions = artifact["partitions"]
    date_sets = [
        set(partitions[name]["evidence_dates"])
        for name in ("discovery", "selection", "locked_holdout")
    ]
    assert date_sets[0].isdisjoint(date_sets[1])
    assert date_sets[0].isdisjoint(date_sets[2])
    assert date_sets[1].isdisjoint(date_sets[2])


def test_large_search_fine_candidates_jitter_around_seed() -> None:
    active = normalize_plan_generation_tuning_config(None)
    seed_result = SearchResult(
        phase="coarse",
        config=active,
        changed_keys=[],
        search_actionable_count=10,
        search_win_count=5,
        search_expected_value=1.0,
        search_ambiguous_count=0,
        validation_actionable_count=10,
        validation_win_count=5,
        validation_expected_value=1.0,
        validation_ambiguous_count=0,
    )

    candidates = list(fine_candidates(active, [seed_result], count=3, seed=321))

    assert len(candidates) == 3
    assert all(set(candidate) == set(active) for candidate in candidates)
