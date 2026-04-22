from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.models import RecommendationDecisionSample
from trade_proposer_app.repositories.recommendation_decision_samples import RecommendationDecisionSampleRepository

router = APIRouter(prefix="/recommendation-decision-samples", tags=["recommendation-decision-samples"])


@router.get("")
async def list_recommendation_decision_samples(
    ticker: str | None = Query(default=None),
    run_id: int | None = Query(default=None),
    decision_type: str | None = Query(default=None),
    review_priority: str | None = Query(default=None),
    shortlisted: bool | None = Query(default=None),
    setup_family: str | None = Query(default=None),
    transmission_bias: str | None = Query(default=None),
    context_regime: str | None = Query(default=None),
    benchmark_result: str | None = Query(default=None),
    created_after: str | None = Query(default=None),
    created_before: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    repository = RecommendationDecisionSampleRepository(session)
    normalized_ticker = ticker.strip().upper() if ticker else None
    normalized_decision_type = decision_type.strip().lower() if decision_type else None
    normalized_review_priority = review_priority.strip().lower() if review_priority else None
    normalized_setup_family = setup_family.strip().lower() if setup_family else None
    normalized_transmission_bias = transmission_bias.strip().lower() if transmission_bias else None
    normalized_context_regime = context_regime.strip().lower() if context_regime else None
    normalized_benchmark_result = benchmark_result.strip().lower() if benchmark_result else None
    normalized_created_after = _parse_datetime(created_after)
    normalized_created_before = _parse_datetime(created_before)
    items = repository.list_samples(
        ticker=normalized_ticker,
        run_id=run_id,
        decision_type=normalized_decision_type,
        review_priority=normalized_review_priority,
        shortlisted=shortlisted,
        setup_family=normalized_setup_family,
        transmission_bias=normalized_transmission_bias,
        context_regime=normalized_context_regime,
        benchmark_result=normalized_benchmark_result,
        created_after=normalized_created_after,
        created_before=normalized_created_before,
        limit=limit,
        offset=offset,
    )
    total = repository.count_samples(
        ticker=normalized_ticker,
        run_id=run_id,
        decision_type=normalized_decision_type,
        review_priority=normalized_review_priority,
        shortlisted=shortlisted,
        setup_family=normalized_setup_family,
        transmission_bias=normalized_transmission_bias,
        context_regime=normalized_context_regime,
        benchmark_result=normalized_benchmark_result,
        created_after=normalized_created_after,
        created_before=normalized_created_before,
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}



def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
