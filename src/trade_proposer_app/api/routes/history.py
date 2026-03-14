from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.models import RecommendationHistoryItem
from trade_proposer_app.repositories.runs import RunRepository

router = APIRouter(prefix="/history", tags=["history"])


@router.get("")
async def get_history(
    ticker: str = Query(default=""),
    direction: str = Query(default=""),
    state: str = Query(default=""),
    warnings: str = Query(default=""),
    sort: str = Query(default="created_at"),
    order: str = Query(default="desc"),
    page: int = Query(default=1),
    per_page: int = Query(default=10),
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    repository = RunRepository(session)
    items = repository.list_recommendation_history()

    ticker_filter = ticker.strip().upper()
    direction_filter = direction.strip().upper()
    state_filter = state.strip().upper()
    warning_filter = warnings.strip().lower()
    sort_by = sort.strip().lower() or "created_at"
    sort_order = order.strip().lower() or "desc"

    normalized_page = max(1, page)
    normalized_per_page = per_page if per_page in (10, 20, 50, 100) else 10

    filtered: list[RecommendationHistoryItem] = []
    for item in items:
        if ticker_filter and ticker_filter not in item.ticker.upper():
            continue
        if direction_filter and item.direction.value != direction_filter:
            continue
        if state_filter and item.state.value != state_filter:
            continue
        if warning_filter == "only" and not item.warnings:
            continue
        if warning_filter == "none" and item.warnings:
            continue
        filtered.append(item)

    reverse = sort_order != "asc"
    if sort_by == "ticker":
        filtered.sort(key=lambda item: (item.ticker, item.created_at), reverse=reverse)
    elif sort_by == "confidence":
        filtered.sort(key=lambda item: (item.confidence, item.created_at), reverse=reverse)
    elif sort_by == "direction":
        filtered.sort(key=lambda item: (item.direction.value, item.created_at), reverse=reverse)
    elif sort_by == "state":
        filtered.sort(key=lambda item: (item.state.value, item.created_at), reverse=reverse)
    else:
        sort_by = "created_at"
        filtered.sort(key=lambda item: item.created_at, reverse=reverse)

    total_results = len(filtered)
    total_pages = max(1, (total_results + normalized_per_page - 1) // normalized_per_page)
    if normalized_page > total_pages:
        normalized_page = total_pages

    start = (normalized_page - 1) * normalized_per_page
    end = start + normalized_per_page
    paginated_items = filtered[start:end]

    filters = {
        "ticker": ticker_filter,
        "direction": direction_filter,
        "state": state_filter,
        "warnings": warning_filter,
        "sort": sort_by,
        "order": sort_order,
        "per_page": normalized_per_page,
    }
    pagination = {
        "page": normalized_page,
        "per_page": normalized_per_page,
        "total_results": total_results,
        "total_pages": total_pages,
        "has_prev": normalized_page > 1,
        "has_next": normalized_page < total_pages,
        "prev_page": normalized_page - 1,
        "next_page": normalized_page + 1,
    }

    return {
        "items": paginated_items,
        "filters": filters,
        "pagination": pagination,
    }
