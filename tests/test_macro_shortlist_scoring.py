from __future__ import annotations

from datetime import datetime, timezone

from trade_proposer_app.services.macro_shortlist_scoring import MacroShortlistScorer


class FakeResolver:
    def __init__(self, snapshot: dict[str, object] | None) -> None:
        self.snapshot = snapshot
        self.calls: list[datetime | None] = []

    def resolve_macro_snapshot(self, *, as_of: datetime | None = None) -> dict[str, object]:
        self.calls.append(as_of)
        return self.snapshot or {
            "context_snapshot_id": None,
            "context_quality_status": "blocked",
            "score": 0.0,
        }


def test_macro_shortlist_scorer_uses_resolver_as_of_and_maps_tailwind() -> None:
    as_of = datetime(2026, 1, 5, tzinfo=timezone.utc)
    resolver = FakeResolver(
        {
            "context_snapshot_id": 123,
            "score": 0.5,
            "context_quality_status": "usable",
            "source_breakdown": {"evidence_state": "usable", "coverage_state": "news"},
            "context_active_events": [{"label": "semiconductor capex and foundry spending improve"}],
            "context_regime_tags": ["ai_capex"],
        }
    )
    scorer = MacroShortlistScorer(resolver)

    support = scorer.score("AMAT", "long", as_of=as_of)

    assert resolver.calls == [as_of]
    assert support.snapshot_id == 123
    assert support.bias == "tailwind"
    assert support.adjustment > 0
    assert "macro_tailwind_boost" in support.reasons
    assert support.as_dict()["context_tags"] == ["ai_capex"]


def test_macro_shortlist_scorer_keeps_missing_and_degraded_neutral() -> None:
    missing = MacroShortlistScorer(FakeResolver(None)).score("AMAT", "long")
    assert missing.adjustment == 0
    assert missing.reasons == ("macro_context_missing",)

    degraded = MacroShortlistScorer(
        FakeResolver({"context_snapshot_id": 5, "score": 0.8, "context_quality_status": "blocked"})
    ).score("AMAT", "long")
    assert degraded.adjustment == 0
    assert degraded.reasons == ("macro_context_degraded",)


def test_macro_shortlist_scorer_penalizes_mapped_headwind() -> None:
    support = MacroShortlistScorer(
        FakeResolver(
            {
                "context_snapshot_id": 124,
                "score": 0.6,
                "context_quality_status": "usable",
                "source_breakdown": {"evidence_state": "usable", "coverage_state": "news"},
                "context_active_events": [{"label": "semiconductor capex and foundry spending improve"}],
            }
        )
    ).score("AMAT", "short")

    assert support.bias == "headwind"
    assert support.adjustment < 0
    assert "macro_headwind_penalty" in support.reasons
