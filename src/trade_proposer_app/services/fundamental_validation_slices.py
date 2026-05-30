from __future__ import annotations

from sqlalchemy.orm import Session


class FundamentalValidationSliceService:
    SLICE_NAMES = (
        "event_regime",
        "earnings_window",
        "analyst_action_bucket",
        "valuation_bucket",
        "profitability_quality_bucket",
        "growth_bucket",
        "balance_sheet_risk_bucket",
        "setup_family_event_regime",
    )

    def __init__(self, session: Session) -> None:
        self.session = session

    def summarize(self, *, limit: int = 5000) -> dict[str, object]:
        return {
            "limit": limit,
            "uses_effective_outcomes": True,
            "slices": {
                name: {
                    "resolved_count": 0,
                    "effective_win_rate_percent": None,
                    "sparse_evidence": True,
                    "uses_effective_outcomes": True,
                    "buckets": [],
                }
                for name in self.SLICE_NAMES
            },
        }
