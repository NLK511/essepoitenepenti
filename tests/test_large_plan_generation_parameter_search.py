from __future__ import annotations

from pathlib import Path

from scripts.large_plan_generation_parameter_search import (
    ResumeCache,
    SearchResult,
    _fingerprint,
    _keep_top,
    coarse_candidates,
    evaluate_stream,
    fine_candidates,
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


def test_large_search_top_k_keeps_best_validation_ev() -> None:
    top: list[SearchResult] = []
    for index, ev in enumerate([1.0, 3.0, 2.0]):
        _keep_top(
            top,
            SearchResult(
                phase="coarse",
                config={"x": float(index)},
                changed_keys=["x"],
                search_actionable_count=10,
                search_win_count=5,
                search_expected_value=ev,
                search_ambiguous_count=0,
                validation_actionable_count=10,
                validation_win_count=5,
                validation_expected_value=ev,
                validation_ambiguous_count=0,
            ),
            top_k=2,
            min_validation_actionable=5,
        )

    assert [item.validation_expected_value for item in top] == [3.0, 2.0]


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
